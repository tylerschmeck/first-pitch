#!/usr/bin/env python3
"""
Build docs/data/schools.json from the U.S. Dept. of Education EADA survey.

The EADA (Equity in Athletics Disclosure Act) dataset covers every Title IV
school that sponsors athletics -- NCAA, NAIA, NJCAA, CCCAA, NWAC, USCAA, etc.
We keep only schools that sponsor softball and extract the fields the site
shows: division, location, enrollment, sector, and softball program finances.

Run rarely (data updates once a year):
    python3 scripts/build_school_dataset.py path/to/eada_dir

where eada_dir contains schools.xlsx (per-sport) and instLevel.xlsx
(per-institution) from the "EADA_YYYY-YYYY.zip" download at
https://ope.ed.gov/athletics/#/datafile/list

Optional extras alongside eada_dir:
  * sibling dirs named eada_YYYY-YYYY/ with a Schools.xlsx each -> budget
    and roster trends per school across years
  * dir_I.json / dir_II.json / dir_III.json from
    https://web3.ncaa.org/directory/api/directory/memberList?type=12&division=I
    -> conference name + athletics site per NCAA school
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "data" / "schools.json"

EADA_YEAR_LABEL = "2024–25"  # academic year the survey covers


def norm_name(s):
    """Normalize a school name into a matching key."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\bst\.?\b", "saint", s)
    s = re.sub(r"\bmt\.?\b", "mount", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(the|at)\b", " ", s)
    s = re.sub(r"\bmain campus\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_STATE_NAMES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
)


def name_variants(key, city=""):
    """Alternate keys a job posting might use for the same school."""
    v = set()
    # drop leading articles/prefixes
    for pre in ("university of ", "college of "):
        if key.startswith(pre):
            v.add(key[len(pre):])
    # drop trailing institution words
    for suf in (
        " university", " college", " community college", " state university",
        " state college", " junior college", " technical college",
        " institute of technology", " a and m university",
    ):
        if key.endswith(suf) and len(key) > len(suf) + 3:
            v.add(key[: -len(suf)])
    # campus-city suffix: "kent state university kent" -> "kent state university"
    c = norm_name(city) if city else ""
    if c and key.endswith(" " + c) and len(key) > len(c) + 4:
        v.add(key[: -(len(c) + 1)])
    # SUNY long forms -> "suny <campus>"
    for pre in (
        "state university of new york ",
        "suny college of technology ",
        "suny college of agriculture and technology ",
        "suny college ",
    ):
        if key.startswith(pre) and len(key) > len(pre) + 2:
            v.add("suny " + key[len(pre):])
    # trailing state name: "saint john s university new york" -> without it
    for st in _STATE_NAMES:
        if key.endswith(" " + st) and len(key) > len(st) + 6:
            v.add(key[: -(len(st) + 1)])
    # "x university y" -> "x university" is unsafe in general; skip.
    v.discard(key)
    return v


def classify(classification_name, classification_other):
    """Map EADA classification to a compact division label + sort group."""
    c = (classification_name or "").strip()
    other = (classification_other or "").strip()
    m = {
        "NCAA Division I-FBS": ("NCAA D1", "d1"),
        "NCAA Division I-FCS": ("NCAA D1", "d1"),
        "NCAA Division I without football": ("NCAA D1", "d1"),
        "NCAA Division II with football": ("NCAA D2", "d2"),
        "NCAA Division II without football": ("NCAA D2", "d2"),
        "NCAA Division III with football": ("NCAA D3", "d3"),
        "NCAA Division III without football": ("NCAA D3", "d3"),
        "NAIA Division I": ("NAIA", "naia"),
        "NAIA Division II": ("NAIA", "naia"),
        "NJCAA Division I": ("NJCAA D1", "juco"),
        "NJCAA Division II": ("NJCAA D2", "juco"),
        "NJCAA Division III": ("NJCAA D3", "juco"),
    }
    if c in m:
        return m[c]
    cl = (c + " " + other).lower()
    if "njcaa" in cl:
        return ("NJCAA", "juco")
    if "naia" in cl:
        return ("NAIA", "naia")
    if "cccaa" in cl or "california community" in cl or "coa " in cl:
        return ("CCCAA (JC)", "juco")
    if "nwac" in cl or "northwest athletic" in cl:
        return ("NWAC (JC)", "juco")
    if "uscaa" in cl:
        return ("USCAA", "other")
    if "nccaa" in cl:
        return ("NCCAA", "other")
    if "independent" in cl or "other" in cl:
        return ("Other", "other")
    return (c or "Other", "other")


def load_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    for r in rows:
        yield dict(zip(header, r))


def find_file(directory, *names):
    """Case-insensitive file lookup."""
    lower = {p.name.lower(): p for p in Path(directory).iterdir()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def load_trends(base_dir):
    """Softball expenses/roster per school per year from eada_YYYY-YYYY dirs."""
    trends = {}
    for d in sorted(Path(base_dir).glob("eada_*-*")):
        try:
            year = int(d.name.split("-")[-1])
        except ValueError:
            continue
        f = find_file(d, "schools.xlsx")
        if not f:
            continue
        n = 0
        for row in load_rows(f):
            if (row.get("Sports") or "").strip() != "Softball":
                continue
            uid = str(row["unitid"])
            trends.setdefault(uid, {})[year] = [row.get("EXP_WOMEN"), row.get("PARTIC_WOMEN")]
            n += 1
        print("  trends %s: %d softball rows" % (d.name, n))
    return trends


def load_directory(base_dir):
    """NCAA directory: normalized name -> conference / athletics url / state."""
    out = []
    for div in ("I", "II", "III"):
        f = Path(base_dir) / ("dir_%s.json" % div)
        if not f.exists():
            continue
        for e in json.loads(f.read_text()):
            url = (e.get("athleticWebUrl") or "").strip()
            if url and not url.startswith("http"):
                url = "https://" + url
            out.append({
                "key": norm_name(e.get("nameOfficial") or ""),
                "state": ((e.get("memberOrgAddress") or {}).get("state") or "").strip(),
                "conference": (e.get("conferenceName") or "").strip(),
                "url": url,
                "org_id": e.get("orgId"),
            })
    return out


def main(eada_dir):
    eada = Path(eada_dir)
    base = eada.parent
    trends = load_trends(base)
    directory = load_directory(base)

    # institution-level: salaries / aid / recruiting (averages across women's teams)
    inst = {}
    for d in load_rows(eada / "instLevel.xlsx"):
        inst[d["unitid"]] = {
            "hc_salary_women": d.get("HDCOACH_SAL_FTE_WOMN") or d.get("HDCOACH_SALARY_WOMEN"),
            "ac_salary_women": d.get("ASCOACH_SAL_FTE_WOMN") or d.get("ASCOACH_SALARY_WOMEN"),
            "student_aid_women": d.get("STUDENTAID_WOMEN"),
            "recruit_exp_women": d.get("RECRUITEXP_WOMEN"),
        }

    schools = {}
    for d in load_rows(eada / "schools.xlsx"):
        if (d.get("Sports") or "").strip() != "Softball":
            continue
        unitid = d["unitid"]
        name = (d["institution_name"] or "").strip()
        division, group = classify(d.get("classification_name"), d.get("ClassificationOther"))
        ii = inst.get(unitid, {})
        ft_head = (d.get("WOMEN_FTHDCOACH_MALE") or 0) + (d.get("WOMEN_FTHDCOACH_FEM") or 0)
        pt_head = (d.get("WOMEN_PTHDCOACH_MALE") or 0) + (d.get("WOMEN_PTHDCOACH_FEM") or 0)
        ft_asst = (d.get("WOMEN_FTASCOACH_MALE") or 0) + (d.get("WOMEN_FTASTCOACH_FEM") or 0)
        pt_asst = (d.get("WOMEN_PTASCOACH_MALE") or 0) + (d.get("WOMEN_PTASTCOACH_FEM") or 0)
        schools[str(unitid)] = {
            "name": name,
            "city": (d.get("city_txt") or "").strip(),
            "state": (d.get("state_cd") or "").strip(),
            "division": division,
            "group": group,  # d1 | d2 | d3 | naia | juco | other
            "sector": (d.get("sector_name") or "").strip(),
            "enrollment": d.get("EFTotalCount"),
            "sb_players": d.get("PARTIC_WOMEN"),
            "sb_opexp": d.get("OPEXPPERTEAM_WOMEN"),   # operating (game-day) expenses
            "sb_expenses": d.get("EXP_WOMEN"),          # full program expenses
            "sb_revenue": d.get("REV_WOMEN"),
            "sb_head_ft": ft_head, "sb_head_pt": pt_head,
            "sb_asst_ft": ft_asst, "sb_asst_pt": pt_asst,
            "hc_salary_women": ii.get("hc_salary_women"),
            "ac_salary_women": ii.get("ac_salary_women"),
            "student_aid_women": ii.get("student_aid_women"),
            "recruit_exp_women": ii.get("recruit_exp_women"),
            "conference": "",
            "ath_url": "",
        }
        yr_map = trends.get(str(unitid), {})
        yr_map[2025] = [d.get("EXP_WOMEN"), d.get("PARTIC_WOMEN")]
        years = sorted(yr_map)
        schools[str(unitid)]["trend_years"] = years
        schools[str(unitid)]["trend_exp"] = [yr_map[y][0] for y in years]
        schools[str(unitid)]["trend_players"] = [yr_map[y][1] for y in years]

    # Build name index. Exact normalized names always win; variant keys fill
    # gaps, and variant collisions resolve to the higher division (a posting
    # saying just "Kent State University" means the D1 campus, not a branch).
    PRIORITY = {"d1": 0, "d2": 1, "d3": 2, "naia": 3, "juco": 4, "other": 5}
    primary, variants = {}, {}
    for unitid, s in schools.items():
        key = norm_name(s["name"])
        if key in primary and primary[key] != unitid:
            primary[key] = None  # two schools share an exact name: ambiguous
        else:
            primary.setdefault(key, unitid)
        for v in name_variants(key, s["city"]):
            if v in variants and variants[v] != unitid:
                a, b = variants[v], unitid
                if a is None:
                    continue
                pa = PRIORITY[schools[a]["group"]]
                pb = PRIORITY[schools[b]["group"]]
                variants[v] = a if pa < pb else (b if pb < pa else None)
            else:
                variants.setdefault(v, unitid)

    index = {k: v for k, v in variants.items() if v is not None}
    index.update({k: v for k, v in primary.items() if v is not None})

    # graft NCAA directory info (conference, athletics site) onto schools
    grafted = 0
    for e in directory:
        uid = index.get(e["key"])
        if not uid:
            continue
        s = schools[uid]
        if e["state"] and s["state"] and e["state"] != s["state"]:
            continue
        if not s["conference"]:
            s["conference"] = e["conference"]
            s["ath_url"] = e["url"]
            grafted += 1
    print("Directory grafted onto %d NCAA schools" % grafted)

    out = {
        "eada_year": EADA_YEAR_LABEL,
        "schools": schools,
        "index": index,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    counts = {}
    for s in schools.values():
        counts[s["group"]] = counts.get(s["group"], 0) + 1
    print(f"Wrote {OUT} — {len(schools)} softball schools, {len(index)} name keys")
    print("By group:", counts)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
