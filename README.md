# career-fit

Exploratory scripts that scrape public-sector job postings and score them against a
candidate profile. Two pipelines:

- **UT Austin** — Workday ATS scraper (`scrape_jobs.py`) + evaluator (`evaluate_jobs.py`)
- **Nashville metro** — multi-source scraper (`scrape_nashville.py`) covering USAJOBS,
  Metro Nashville / Brentwood (NeoGov), Williamson County, MNPS (Oracle HCM),
  Tennessee state careers, BNA, WeGo, THDA, City of Franklin + evaluator
  (`evaluate_nashville.py`)

Each evaluator emits an `.xlsx` with YES / MAYBE / UNLIKELY / NO tabs.

## Setup

```bash
pip install requests beautifulsoup4 openpyxl playwright playwright-stealth
playwright install chromium
```

For the USAJOBS portion, request a free API key at
<https://developer.usajobs.gov/apirequest/> and populate a `.env` file:

```bash
cp .env.example .env
# edit .env and set USAJOBS_API_KEY + USAJOBS_EMAIL
```

Then `export` those vars (or use `python-dotenv`) before running the scrapers.

## Running

```bash
python scrape_jobs.py              # UT Austin Workday → jobs_full.json
python evaluate_jobs.py            # → job_recommendations.xlsx

python scrape_nashville.py         # Nashville sources → nashville_jobs_full.json
python evaluate_nashville.py       # → nashville_job_recommendations.xlsx
```

Some Nashville sources (TN State, THDA) open a visible Chrome window via Playwright
to bypass Cloudflare — click through any challenges, the scraper waits.

## Tuning for your own profile

The scoring lives in `STRONG_YES_TITLE`, `HARD_NO_TITLE`, `HARD_NO_DESC`, and
`GREEN_FLAGS_DESC` at the top of each `evaluate_*.py` file. Edit those keyword
lists to match your background.

## Notes

- Generated `.xlsx`, `.json`, and `.txt` output files are gitignored — they're
  candidate-specific.
- No credentials are committed; USAJOBS creds come from env vars.
