"""Job-board fetchers. Each returns a list of raw job dicts:

    {title, school, city, state, url, source, posted (date|None),
     description, division_hint, deadline, contact}

All parsing is defensive: a source that changes shape raises, and sweep.py
records the failure without killing the run.
"""
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

STATE_CODES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR",
}
VALID_CODES = set(STATE_CODES.values())


def fetch(url, timeout=30):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                     timeout=timeout)
    r.raise_for_status()
    return r.text


def clean_text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def to_state_code(s):
    s = (s or "").strip()
    if s.upper() in VALID_CODES:
        return s.upper()
    return STATE_CODES.get(s.lower(), "")


def _rss_items(xml):
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        item = m.group(1)
        d = {"_raw": item}
        for tag in ("title", "link", "description", "pubDate"):
            t = re.search(r"<%s>(.*?)</%s>" % (tag, tag), item, re.S)
            d[tag] = t.group(1).strip() if t else ""
        yield d


def _parse_pubdate(s):
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).date().isoformat()
    except Exception:
        return None


# ---------------------------------------------------------------- YM Careers
# NCAA Market and the NJCAA Career Center both run on YM Careers, which
# exposes search results as RSS via ?display=rss. Item titles look like
# "Assistant Softball Coach | Radford University" and descriptions start
# with "City, StateName,  ...".

def _ym_feed(base, params, source):
    jobs = []
    for page in range(1, 5):
        url = "%s&display=rss&page=%d" % (base + params, page)
        xml = fetch(url)
        items = list(_rss_items(xml))
        for it in items:
            title_full = clean_text(it["title"])
            if "|" in title_full:
                title, school = [x.strip() for x in title_full.rsplit("|", 1)]
            else:
                title, school = title_full, ""
            desc = clean_text(it["description"])
            city = state = ""
            mloc = re.match(r"^([^,]{2,40}),\s*([A-Za-z. ]{2,25}?),\s+(.*)$", desc, re.S)
            if mloc and to_state_code(mloc.group(2)):
                city, state, desc = mloc.group(1).strip(), to_state_code(mloc.group(2)), mloc.group(3)
            link = clean_text(it["link"]).replace("/jobs/rss/", "/jobs/")
            jobs.append({
                "title": title, "school": school, "city": city, "state": state,
                "url": link, "source": source, "posted": _parse_pubdate(it["pubDate"]),
                "description": desc, "division_hint": "", "deadline": "", "contact": "",
            })
        if len(items) < 50:
            break
    return jobs


SOFTBALL_TITLE = re.compile(r"softball", re.I)


def ncaa_market():
    # the dedicated softball-coaching category: every item is relevant
    jobs = _ym_feed("https://ncaamarket.ncaa.org/jobs/category/coaching-softball",
                    "?", "NCAA Market")
    seen = {j["url"] for j in jobs}
    # keyword search catches postings filed outside the softball category,
    # but matches descriptions too — keep only titles that say softball
    for j in _ym_feed("https://ncaamarket.ncaa.org/jobs/", "?keywords=softball",
                      "NCAA Market"):
        if j["url"] not in seen and SOFTBALL_TITLE.search(j["title"]):
            jobs.append(j)
    return jobs


def njcaa():
    jobs = _ym_feed("https://careers.njcaa.org/jobs/", "?keywords=softball",
                    "NJCAA Career Center")
    return [j for j in jobs if SOFTBALL_TITLE.search(j["title"])]


# --------------------------------------------------------------------- NFCA
# nfca.org/nfca-job-postings is a hand-curated accordion list, one block per
# job, grouped under HEAD COACH / ASSISTANT COACH / GRADUATE ASSISTANT COACH
# anchors. Each block: <h3 class="uk-accordion-title">School (DIVISION)</h3>
# then a content div with "Title | School (Div) | City, ST", a Posting Date,
# an Application Deadline and an APPLY HERE link.

def nfca():
    page = fetch("https://nfca.org/nfca-job-postings")
    # restrict to the job-list region (starts at the first section anchor)
    start = page.find('id="headcoach"')
    if start == -1:
        raise ValueError("NFCA page shape changed: no #headcoach anchor")
    region = page[start:]
    end = region.find('id="business"')
    if end > -1:
        region = region[:end]

    jobs = []
    blocks = re.split(r'<h3 class="uk-accordion-title">', region)[1:]
    for b in blocks:
        mhead = re.match(r"\s*(.*?)</h3>", b, re.S)
        heading = clean_text(mhead.group(1)) if mhead else ""
        division_hint = ""
        mdiv = re.search(r"\(([^)]*(?:NCAA|NAIA|NJCAA|CCCAA|NWAC|USCAA|JC|Juco)[^)]*)\)?",
                         heading, re.I)
        if mdiv:
            division_hint = mdiv.group(1).strip()

        def clean_school(s):
            s = re.sub(r"\([^)]*\)?", " ", s)          # parens, even unclosed
            s = re.sub(r"\s[-–—]\s.*$", " ", s)         # " - Pitching" suffixes
            return re.sub(r"\s+", " ", s).strip(" ,-")

        school_h = clean_school(heading)

        # strong header line: Title | School (Div) | City, ST
        title, city, state = "", "", ""
        mstrong = re.search(r"<strong>(.*?)</strong>", b, re.S)
        if mstrong:
            parts = [clean_text(p) for p in mstrong.group(1).split("|")]
            if parts:
                title = parts[0]
            if len(parts) >= 3:
                mid = clean_school(parts[1])
                if len(mid) > 3:
                    school_h = mid
                mloc = re.match(r"^(.*?),\s*([A-Za-z]{2})\b", parts[-1])
                if mloc:
                    city, state = mloc.group(1).strip(), mloc.group(2).upper()

        posted = None
        mp = re.search(r"Posting Date:\s*</strong>?\s*([\d/]+)", b) or \
             re.search(r"Posting Date:</strong>\s*([\d/]+)", b) or \
             re.search(r"Posting Date:\s*([\d/]+)", clean_text(b))
        if mp:
            try:
                mth, day, yr = [int(x) for x in mp.group(1).split("/")]
                yr += 2000 if yr < 100 else 0
                posted = datetime(yr, mth, day).date().isoformat()
            except Exception:
                posted = None

        deadline = ""
        md = re.search(r"Application Deadline:\s*</strong>\s*(.*?)</p>", b, re.S)
        if md:
            deadline = clean_text(md.group(1))

        apply_url = ""
        ma = re.search(r'<a href="(https?://[^"]+)"[^>]*>\s*<em[^>]*>\s*<button', b) or \
             re.search(r'<a href="(https?://[^"]+)"[^>]*>(?:(?!</a>).)*APPLY', b, re.S | re.I)
        if ma:
            apply_url = html.unescape(ma.group(1))

        contact = ""
        mc = re.search(r"Contact:\s*</strong>\s*<a[^>]*>(.*?)</a>", b, re.S)
        if mc:
            contact = clean_text(mc.group(1))

        # description: text after the posting-date paragraph, before APPLY
        desc = clean_text(re.sub(r"<a href.*$", "", b, flags=re.S))
        desc = re.sub(r"^.*?(?:Until position is filled|Posting Date:\s*[\d/]+)", "", desc).strip()

        if not title:
            title = "Softball Coach"
        jobs.append({
            "title": title, "school": school_h, "city": city, "state": state,
            "url": apply_url or "https://nfca.org/nfca-job-postings",
            "source": "NFCA", "posted": posted, "description": desc,
            "division_hint": division_hint, "deadline": deadline, "contact": contact,
        })
    if not jobs:
        raise ValueError("NFCA page shape changed: no accordion blocks parsed")
    return jobs


# --------------------------------------------------------------------- NAIA
# jobs.naia.org is a WordPress (WP Job Manager) board with a job_feed.

def naia():
    jobs = []
    seen = set()
    for params in ("?feed=job_feed&search_keywords=softball",
                   "?feed=job_feed&posts_per_page=100",
                   "?feed=job_feed"):
        try:
            xml = fetch("https://jobs.naia.org/" + params)
        except Exception:
            continue
        for it in _rss_items(xml):
            title = clean_text(it["title"])
            desc = clean_text(re.sub(r"<!\[CDATA\[|\]\]>", "", it["description"]))
            if "softball" not in (title + " " + desc).lower():
                continue
            url = clean_text(it["link"])
            if url in seen:
                continue
            seen.add(url)
            school = ""
            mc = re.search(r"<job_listing:company>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</job_listing:company>",
                           it.get("_raw", ""), re.S)
            if mc:
                school = clean_text(mc.group(1))
            jobs.append({
                "title": title, "school": school,
                "city": "", "state": "",
                "url": url, "source": "NAIA Careers",
                "posted": _parse_pubdate(it["pubDate"]),
                "description": desc, "division_hint": "NAIA",
                "deadline": "", "contact": "",
            })
    return jobs


SOURCES = [
    ("NCAA Market", ncaa_market),
    ("NFCA", nfca),
    ("NJCAA Career Center", njcaa),
    ("NAIA Careers", naia),
]
