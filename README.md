# First Pitch 🥎

**Every college softball coaching job in the U.S. — on one page, refreshed
every 3 hours, with the context that matters.**

Freshness is enforced, not hoped for: the sweeper keeps only what the boards
list *right now*, stamps every posting with its original post date, and drops
anything older than 4 months (a coaching search open that long is filled or
abandoned). The header shows when the last sweep ran and turns amber if
sweeps ever pause.

Built for a coach who shouldn't have to check five job boards a day. Open the
page, see what's new, tap a card, understand the program in ten seconds, apply.

## What it does

- **Sweeps six boards automatically**: [NCAA Market](https://ncaamarket.ncaa.org)
  (all NCAA divisions), the [NFCA job page](https://nfca.org/nfca-job-postings)
  (the softball community hub — all levels), the
  [NJCAA Career Center](https://careers.njcaa.org) (junior colleges),
  [NAIA Careers](https://jobs.naia.org), the
  [CCCAA / 3C2A board](https://www.cccaasports.org/services/employ-current)
  (California community colleges — a separate body from the NJCAA), and the
  [NWAC board](https://nwacsports.com/employment) (Washington/Oregon community
  colleges). Cross-board duplicates are merged into one card with every apply
  link, and any listing older than four months is dropped automatically.
- **Knows the school.** Each posting is matched against the U.S. Department of
  Education's EADA athletics survey (~1,600 softball-sponsoring schools):
  division, conference, enrollment, public/private, roster size, softball
  program budget, average head-coach and assistant salaries, athletic aid,
  full-time vs part-time staffing.
- **Shows the trend.** A six-year budget sparkline per program — is this a
  school investing in softball, or cutting it?
- **Shows the situation.** Posting date and age, application deadline, salary
  when listed, hiring contact, plus one-tap links to program news and the
  team site.
- **Personal**: save jobs, hide the noise, filter by division / position /
  state / keyword — all remembered on her device. Light & dark mode. Fast on
  a phone.

## Deploy it (one command)

```bash
./deploy.sh
```

That's it. The script uses the [GitHub CLI](https://cli.github.com) (`brew
install gh` if you don't have it) to create a public repo, enable GitHub
Pages, and start the sweeper. It prints the URL to send her — the site then
maintains itself: a GitHub Action re-sweeps every 3 hours (8× a day) and
commits fresh data.

> **Note:** GitHub pauses cron schedules on repos with no activity for 60
> days. If that ever happens, open the repo's **Actions** tab and press "Run
> workflow" once — or just star the repo when you think of it.

## Run it locally

```bash
python3 -m pip install requests
python3 scraper/sweep.py          # refresh docs/data/jobs.json
python3 -m http.server -d docs    # open http://localhost:8000
```

## How it's put together

```
scraper/sweep.py      the 6-hourly pipeline: fetch → dedupe → enrich → jobs.json
scraper/sources.py    one fetcher per job board (defensive; a broken board
                      never kills the sweep — failures are shown on the site)
scripts/build_school_dataset.py
                      rebuilds docs/data/schools.json from EADA + NCAA
                      directory data (run ~once a year when new EADA drops)
docs/                 the site (vanilla HTML/CSS/JS, no build step)
docs/data/jobs.json   the live listings (committed by the Action)
docs/data/schools.json  the 1,619-school reference dataset
```

### Data honesty

- Finances come from schools' own federal EADA filings (2024–25 survey).
  They're the best public comparable numbers, but schools file them with
  varying rigor — context, not gospel.
- "Avg HC salary" averages across **all women's teams** at the school (the
  survey doesn't break salaries out by sport).
- Win/loss records aren't included: the NCAA's stats site blocks automated
  access. The "Program news" link on each card is the quickest manual check.
- A school with no snapshot usually means a **brand-new program** (or a
  non-college employer) — the card says so.
