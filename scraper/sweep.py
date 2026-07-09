#!/usr/bin/env python3
"""Sweep all job boards, enrich with school data, write docs/data/jobs.json.

Runs locally or in CI. Never fails the whole run because one board changed:
per-source status is recorded and shown on the site.
"""
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sources import SOURCES, to_state_code  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "docs" / "data"
JOBS_OUT = DATA / "jobs.json"

# A coaching search that's been open this long is filled or abandoned —
# never show it, even if a board still lists it.
MAX_AGE_DAYS = 120
# How long to remember a job's first_seen after it stops being shown
# (prevents dropped stale jobs from flapping back as "NEW").
SEEN_MEMORY_DAYS = 400


# ---------------------------------------------------------------- matching

def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\bst\.?\b", "saint", s)
    s = re.sub(r"\bmt\.?\b", "mount", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(the|at)\b", " ", s)
    s = re.sub(r"\bmain campus\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


GENERIC_TOKENS = {"university", "college", "state", "community", "of", "and",
                  "saint", "the", "at", "junior", "technical"}

# common athletic identities that differ from the school's federal (IPEDS) name
ALIASES = {
    "long beach state": "california state university long beach",
    "long beach state university": "california state university long beach",
    "sacramento state": "california state university sacramento",
    "sac state": "california state university sacramento",
    "fresno state": "california state university fresno",
    "san diego state": "san diego state university",
    "san jose state": "san jose state university",
    "florida tech": "florida institute of technology",
    "tennessee tech": "tennessee technological university",
    "tennessee tech university": "tennessee technological university",
    "louisiana tech": "louisiana tech university",
    "virginia tech": "virginia polytechnic institute and state university",
    "georgia tech": "georgia institute of technology",
    "indiana tech": "indiana institute of technology",
    "ole miss": "university of mississippi",
    "penn state": "pennsylvania state university",
    "umass": "university of massachusetts amherst",
    "umass lowell": "university of massachusetts lowell",
    "uconn": "university of connecticut",
    "ucf": "university of central florida",
    "smu": "southern methodist university",
    "tcu": "texas christian university",
    "byu": "brigham young university",
    "lsu": "louisiana state university and agricultural and mechanical college",
    "unlv": "university of nevada las vegas",
    "utep": "university of texas el paso",
    "vcu": "virginia commonwealth university",
    "unc": "university of north carolina chapel hill",
    "usc": "university of southern california",
    "ucla": "university of california los angeles",
    "vermont state university castleton": "vermont state university",
    "vermont state university johnson": "vermont state university",
    "vermont state university lyndon": "vermont state university",
}


def match_school(name, state, db):
    """Return unitid for a raw school name, or None. State-verified."""
    if not name:
        return None
    index, schools = db["index"], db["schools"]

    def hit(key):
        uid = index.get(key)
        if uid and state and schools[uid]["state"] and schools[uid]["state"] != state:
            return None  # same name, wrong state (e.g. the two St. Joseph's)
        return uid

    key = norm_name(re.sub(r"\([^)]*\)?", " ", name))
    if not key:
        return None
    key = ALIASES.get(key, key)
    uid = hit(key)
    if uid:
        return uid
    # posting-side variants
    trials = []
    for pre in ("university of ", "college of "):
        if key.startswith(pre):
            trials.append(key[len(pre):])
    for suf in (" university", " college", " community college", " state university",
                " state college", " junior college", " athletics"):
        if key.endswith(suf) and len(key) > len(suf) + 3:
            trials.append(key[: -len(suf)])
    if key.startswith("suny college "):
        trials.append("suny " + key[len("suny college "):])
    # progressively drop trailing campus qualifiers: "x university castleton"
    toks_full = key.split()
    for cut in (1, 2):
        if len(toks_full) - cut >= 2:
            trials.append(" ".join(toks_full[:-cut]))
    for t in trials:
        uid = hit(t)
        if uid:
            return uid
    # last resort: unique token-superset match, state-checked
    toks = set(key.split()) - GENERIC_TOKENS
    if len(toks) >= 2 or (len(toks) == 1 and len(next(iter(toks))) > 5):
        cands = []
        for k, u in index.items():
            ktoks = set(k.split())
            if toks <= ktoks:
                if state and schools[u]["state"] and schools[u]["state"] != state:
                    continue
                cands.append(u)
        if len(set(cands)) == 1:
            return cands[0]
    return None


# ------------------------------------------------------------ classification

def classify_type(title):
    t = title.lower()
    if re.search(r"\bdirector of (softball )?ops|operations\b", t) and "coach" not in t:
        return "other"
    if re.search(r"\b(grad(uate)?|volunteer|intern)\b", t):
        return "other"
    if re.search(r"\b(assistant|asst|associate head)\b", t):
        return "assistant"
    if re.search(r"\bhead\b", t):
        return "head"
    if re.search(r"\bcoach\b", t):
        return "head"  # plain "Softball Coach" postings are head jobs
    return "other"


def is_relevant(title):
    """Keep coaching/program jobs, drop stray non-softball items."""
    t = title.lower()
    if "softball" in t:
        return True
    # NFCA/category items sometimes omit the word in the title
    return bool(re.search(r"\b(coach|coaching|operations|recruiting)\b", t))


DIV_HINT = [
    (re.compile(r"njcaa|juco|junior college", re.I), None),
    (re.compile(r"naia", re.I), "NAIA"),
    (re.compile(r"n?caa?\s*d(?:iv(?:ision)?)?\.?\s*(i{1,3}|[123])\b", re.I), "NCAA"),
]


def parse_division_hint(hint):
    """Turn 'NCAA DIII' / 'NJCAA DI' / 'NAIA' into a display label."""
    h = (hint or "").strip()
    if not h:
        return ""
    hl = h.lower()
    roman = {"i": "1", "ii": "2", "iii": "3"}
    m = re.search(r"\bd(?:iv(?:ision)?)?\.?\s*(iii|ii|i|[123])\b", hl)
    n = roman.get(m.group(1), m.group(1)) if m else ""
    if "njcaa" in hl:
        return ("NJCAA D%s" % n) if n else "NJCAA"
    if "naia" in hl:
        return "NAIA"
    if "ncaa" in hl:
        return ("NCAA D%s" % n) if n else "NCAA"
    if "cccaa" in hl:
        return "CCCAA (JC)"
    if "nwac" in hl:
        return "NWAC (JC)"
    return h[:24]


def group_for_division(div):
    d = (div or "").upper()
    if "NCAA D1" in d: return "d1"
    if "NCAA D2" in d: return "d2"
    if "NCAA D3" in d: return "d3"
    if "NAIA" in d: return "naia"
    if "NJCAA" in d or "(JC)" in d or "CCCAA" in d or "NWAC" in d: return "juco"
    return "other"


SALARY_RE = re.compile(
    r"\$\s?\d{2,3}[,.]?\d{3}(?:\.\d\d)?(?:\s*(?:-|to|–)\s*\$?\s?\d{2,3}[,.]?\d{3}(?:\.\d\d)?)?")


TITLE_NOISE = {
    "the", "of", "a", "an", "for", "and", "or", "to",
    "softball", "coach", "coaching", "women", "womens", "s", "w",
    "university", "college", "athletics", "athletic", "department",
    "division", "student", "affairs", "position", "program", "umd",
}


def title_tokens(title):
    """Distinguishing tokens of a title, ignoring board phrasing noise."""
    t = re.sub(r"\([^)]*\)?", " ", title)
    all_caps = title.isupper()
    kept = []
    for w in re.sub(r"[^A-Za-z0-9]+", " ", t).split():
        if any(ch.isdigit() for ch in w):
            continue  # req codes like GA017
        if not all_caps and len(w) <= 4 and w.isupper():
            continue  # school acronyms like UMD
        wl = w.lower()
        if wl not in TITLE_NOISE:
            kept.append(wl)
    return frozenset(kept)


def job_id(school_key, jtype, toks):
    core = " ".join(sorted(toks))
    return hashlib.sha1(("%s|%s|%s" % (school_key, jtype, core)).encode()).hexdigest()[:12]


def main():
    db = json.loads((DATA / "schools.json").read_text())
    prev_jobs, prev_seen = [], {}
    if JOBS_OUT.exists():
        try:
            prev = json.loads(JOBS_OUT.read_text())
            prev_jobs = prev.get("jobs", [])
            prev_seen = dict(prev.get("seen", {}))
        except Exception:
            pass
    for j in prev_jobs:
        prev_seen.setdefault(j["id"], j.get("first_seen"))

    def inherit_first_seen(jid, skey, jtype, toks):
        """Carry first_seen across runs even if a board retitles the job."""
        if jid in prev_seen:
            return prev_seen[jid]
        for p in prev_jobs:
            if p.get("school_key") == skey and p.get("type") == jtype:
                ptoks = set(p.get("tok", []))
                if ptoks and (ptoks <= toks or toks <= ptoks):
                    return p.get("first_seen")
        return None

    raw, status = [], []
    for name, fn in SOURCES:
        try:
            items = fn()
            raw.extend(items)
            status.append({"name": name, "ok": True, "count": len(items)})
            print("  %-20s %3d postings" % (name, len(items)))
        except Exception as e:
            status.append({"name": name, "ok": False, "error": str(e)[:200]})
            print("  %-20s FAILED: %s" % (name, e))

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    # group candidate entries by (school, type); merge token-subset titles,
    # so "Head Coach" (NFCA) and "Head Softball Coach" (NCAA Market) collapse
    groups = {}
    for r in raw:
        title = r["title"].strip()
        if not is_relevant(title):
            continue
        state = to_state_code(r.get("state", "")) or r.get("state", "")
        uid = match_school(r.get("school", ""), state, db)
        school_key = uid or norm_name(r.get("school", "")) or "unknown"
        jtype = classify_type(title)
        toks = title_tokens(title)
        r = dict(r, _uid=uid, _skey=school_key, _type=jtype, _toks=toks, title=title)
        groups.setdefault((school_key, jtype), []).append(r)

    merged = []
    for (skey, jtype), items in groups.items():
        items.sort(key=lambda r: len(r["_toks"]), reverse=True)
        slots = []
        for r in items:
            target = None
            for s in slots:
                if r["_toks"] <= s["_toks"] or s["_toks"] <= r["_toks"]:
                    target = s
                    break
            if target is None:
                slots.append({
                    "_toks": r["_toks"], "_uid": r["_uid"], "_skey": skey,
                    "_type": jtype, "_desc": r.get("description", ""),
                    "title": r["title"], "school_raw": r.get("school", ""),
                    "city": r.get("city", ""), "state": r.get("state", ""),
                    "division_hint": r.get("division_hint", ""),
                    "links": [{"source": r["source"], "url": r["url"]}],
                    "posted": r.get("posted"),
                    "deadline": r.get("deadline", ""),
                    "contact": r.get("contact", ""),
                })
            else:
                target["_toks"] = target["_toks"] | r["_toks"]
                target["links"].append({"source": r["source"], "url": r["url"]})
                p = r.get("posted")
                if p and (not target["posted"] or p < target["posted"]):
                    target["posted"] = p
                for f in ("deadline", "contact", "division_hint", "city", "state"):
                    if r.get(f) and not target[f]:
                        target[f] = r[f]
                if len(r.get("description", "")) > len(target["_desc"]):
                    target["_desc"] = r["description"]
                if len(r["title"]) > len(target["title"]):
                    target["title"] = r["title"]
        merged.extend(slots)

    jobs, seen_out, stale_dropped = [], {}, 0
    for e in merged:
        uid = e.pop("_uid")
        skey, jtype, toks = e.pop("_skey"), e.pop("_type"), e.pop("_toks")
        school = db["schools"].get(uid) if uid else None
        state = to_state_code(e.pop("state", "")) or ""
        city = e.pop("city", "")
        jid = job_id(skey, jtype, toks)
        e.update({
            "id": jid,
            "type": jtype,
            "school_key": skey,
            "tok": sorted(toks),
            "unitid": uid,
            "school_name": school["name"] if school else e.pop("school_raw").strip(),
            "city": city or (school["city"] if school else ""),
            "state": state or (school["state"] if school else ""),
        })
        e.pop("school_raw", None)
        desc = e.pop("_desc")
        msal = SALARY_RE.search(desc)
        school = db["schools"].get(e["unitid"]) if e["unitid"] else None
        division = (school["division"] if school else "") or parse_division_hint(e["division_hint"])
        first_seen = inherit_first_seen(jid, skey, jtype, set(toks)) or today
        posted = e["posted"] or first_seen
        seen_out[jid] = first_seen
        try:
            age = (now.date() - datetime.strptime(posted, "%Y-%m-%d").date()).days
        except ValueError:
            age = 0
        if age > MAX_AGE_DAYS:
            stale_dropped += 1
            continue
        e.update({
            "division": division or "—",
            "group": group_for_division(division),
            "posted": posted,
            "posted_is_estimate": not bool(e["posted"]),
            "first_seen": first_seen,
            "salary": msal.group(0) if msal else "",
            "snippet": desc[:420].rsplit(" ", 1)[0] + ("…" if len(desc) > 420 else ""),
            "school": ({k: school[k] for k in (
                "name", "city", "state", "division", "group", "sector", "enrollment",
                "sb_players", "sb_opexp", "sb_expenses", "sb_revenue",
                "sb_head_ft", "sb_head_pt", "sb_asst_ft", "sb_asst_pt",
                "hc_salary_women", "ac_salary_women", "student_aid_women",
                "recruit_exp_women", "conference", "ath_url",
                "trend_years", "trend_exp", "trend_players")} if school else None),
        })
        del e["division_hint"]
        jobs.append(e)

    jobs.sort(key=lambda j: (j["posted"] or "", j["first_seen"]), reverse=True)

    # carry forward first_seen for jobs not in this sweep, pruned by age
    for jid, fs in prev_seen.items():
        if jid in seen_out or not fs:
            continue
        try:
            if (now.date() - datetime.strptime(fs, "%Y-%m-%d").date()).days <= SEEN_MEMORY_DAYS:
                seen_out[jid] = fs
        except ValueError:
            pass

    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "eada_year": db.get("eada_year", ""),
        "max_age_days": MAX_AGE_DAYS,
        "sources": status,
        "count": len(jobs),
        "jobs": jobs,
        "seen": seen_out,
    }
    JOBS_OUT.write_text(json.dumps(out, indent=1))
    matched = sum(1 for j in jobs if j["unitid"])
    print("\n%d jobs (%d matched to school data, %d stale dropped) -> %s"
          % (len(jobs), matched, stale_dropped, JOBS_OUT))


if __name__ == "__main__":
    main()
