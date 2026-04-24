"""
Nashville-area government job scraper — three tiers:
  Federal  : USAJOBS REST API (50-mile radius from Nashville)
  TN State : stateoftn-careers.ttcportals.com
  Metro    : GovernmentJobs.com/NeoGov (Metro Nashville Davidson County)

Output: nashville_jobs_full.json  (same schema as jobs_full.json)

SETUP:
  pip install requests beautifulsoup4

  USAJOBS API key — free, takes ~10 minutes:
    1. Go to  https://developer.usajobs.gov/apirequest/
    2. Fill in name + email, submit.
    3. You'll get an email with your API key.
    4. Paste it into USAJOBS_API_KEY and USAJOBS_EMAIL below.
"""

import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup

# ── USAJOBS credentials (from environment — see .env.example) ──────────────────
USAJOBS_API_KEY = os.environ.get("USAJOBS_API_KEY", "")
USAJOBS_EMAIL   = os.environ.get("USAJOBS_EMAIL", "")

# ── Search radius (miles from Nashville centre) ───────────────────────────────
NASHVILLE_RADIUS = 50

# ── GovernmentJobs.com agency slugs to scrape ─────────────────────────────────
NEOGOV_AGENCIES = [
    ("nashville",   "Metro Nashville"),    # Metro Nashville-Davidson County
    ("brentwoodtn", "City of Brentwood"),  # City of Brentwood
]


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"&nbsp;",  " ", text)
    text = re.sub(r"&amp;",   "&", text)
    text = re.sub(r"&lt;",    "<", text)
    text = re.sub(r"&gt;",    ">", text)
    text = re.sub(r"&#\d+;",  " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ══════════════════════════════════════════════════════════════════════════════
# USAJOBS (Federal)
# ══════════════════════════════════════════════════════════════════════════════

USAJOBS_BASE = "https://data.usajobs.gov/api/search"

def scrape_usajobs() -> list[dict]:
    if not USAJOBS_API_KEY or not USAJOBS_EMAIL:
        print("[USAJOBS] Skipping — USAJOBS_API_KEY / USAJOBS_EMAIL env vars not set. See .env.example.")
        return []

    headers = {
        "Host":              "data.usajobs.gov",
        "User-Agent":        USAJOBS_EMAIL,
        "Authorization-Key": USAJOBS_API_KEY,
    }

    all_jobs = []
    page = 1
    per_page = 500

    print("[USAJOBS] Fetching federal jobs near Nashville...")

    while True:
        params = {
            "LocationName":    "Nashville, Tennessee",
            "Radius":          str(NASHVILLE_RADIUS),
            "ResultsPerPage":  str(per_page),
            "Page":            str(page),
        }
        try:
            r = requests.get(USAJOBS_BASE, headers=headers, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  ERROR page {page}: {e}")
            break

        items = data.get("SearchResult", {}).get("SearchResultItems", [])
        if not items:
            break

        for item in items:
            d = item.get("MatchedObjectDescriptor", {})
            ud = d.get("UserArea", {}).get("Details", {})

            title    = d.get("PositionTitle", "")
            locs     = d.get("PositionLocation", [{}])
            location = locs[0].get("LocationName", "Nashville, TN") if locs else "Nashville, TN"
            posted   = d.get("PublicationStartDate", "")[:10]   # ISO date

            # Salary — pick first remuneration entry
            rem = d.get("PositionRemuneration", [{}])
            sal_min = sal_max = ""
            if rem:
                sal_min = rem[0].get("MinimumRange", "")
                sal_max = rem[0].get("MaximumRange", "")
                interval = rem[0].get("RateIntervalCode", "")
                if interval == "PA":   # per annum
                    try:
                        lo = int(float(sal_min))
                        hi = int(float(sal_max))
                        sal_display = f"${lo:,} - ${hi:,}" if lo != hi else f"${lo:,}"
                    except Exception:
                        sal_display = f"{sal_min} - {sal_max}"
                else:
                    sal_display = f"{sal_min} - {sal_max} ({interval})"
            else:
                sal_display = ""

            # Description — combine summary, duties, requirements
            reqs = ud.get("Requirements", "")
            if isinstance(reqs, dict):
                reqs = reqs.get("Conditions", "")
            desc_parts = [
                ud.get("JobSummary", ""),
                " ".join(ud.get("MajorDuties", [])),
                reqs or "",
            ]
            description = " ".join(p for p in desc_parts if p)

            apply_uris = d.get("ApplyURI", [])
            url = apply_uris[0] if apply_uris else d.get("PositionURI", "")

            all_jobs.append({
                "title":       title,
                "location":    location,
                "posted":      posted,
                "url":         url,
                "description": description,
                "salary":      sal_display,
                "source":      "Federal",
            })

        total = data.get("SearchResult", {}).get("SearchResultCountAll", 0)
        print(f"  Fetched {len(all_jobs)}/{total} federal jobs (page {page})")

        if len(all_jobs) >= total:
            break
        page += 1
        time.sleep(0.5)

    print(f"[USAJOBS] Done — {len(all_jobs)} jobs collected.\n")
    return all_jobs


# ══════════════════════════════════════════════════════════════════════════════
# GovernmentJobs.com / NeoGov  (Metro Nashville + others)
# Uses X-Requested-With: XMLHttpRequest to get server-side rendered listing HTML
# ══════════════════════════════════════════════════════════════════════════════

NEOGOV_XHR_HEADERS = {
    "User-Agent":        BROWSER_UA,
    "Accept":            "application/json, text/html, */*",
    "X-Requested-With":  "XMLHttpRequest",
}


def scrape_neogov(agency_slug: str, agency_label: str) -> list[dict]:
    base = f"https://www.governmentjobs.com/careers/{agency_slug}"

    results = []
    page = 1
    seen_ids = set()

    print(f"[NeoGov/{agency_label}] Fetching listings...")

    while True:
        params = {"page": str(page)}
        try:
            r = requests.get(base, headers=NEOGOV_XHR_HEADERS, params=params, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"  ERROR page {page}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("li.list-item")

        if not items:
            break

        new_this_page = 0
        for item in items:
            job_id = item.get("data-job-id", "")
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Title and URL
            link = item.select_one("a.item-details-link")
            title   = link.get_text(strip=True) if link else ""
            href    = link.get("href", "") if link else ""
            job_url = ("https://www.governmentjobs.com" + href) if href.startswith("/") else href

            # Salary — first <li> in list-meta, format: "Full-Time Civil Service - $63,162.00 Annually"
            meta_items = item.select("ul.list-meta li")
            salary_raw = meta_items[0].get_text(" ", strip=True) if meta_items else ""
            salary_match = re.search(r"\$[\d,.]+(?: - \$[\d,.]+)?\s*\w+", salary_raw)
            salary = salary_match.group(0).strip() if salary_match else ""

            # Posted date
            posted_tag = item.select_one("span.list-entry-starts span")
            posted = posted_tag.get_text(strip=True) if posted_tag else ""

            # Description excerpt (already in the listing HTML)
            desc_tag = item.select_one("div.list-entry")
            description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            results.append({
                "title":       title,
                "location":    "Nashville, TN",
                "posted":      posted,
                "url":         job_url,
                "description": description,
                "salary":      salary,
                "source":      agency_label,
            })
            new_this_page += 1

        print(f"  Page {page}: +{new_this_page} jobs (total: {len(results)})")

        if new_this_page == 0:
            break
        page += 1
        time.sleep(0.3)

    print(f"[NeoGov/{agency_label}] Done — {len(results)} jobs.\n")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# Tennessee State Government  (TTCPortals)
# ══════════════════════════════════════════════════════════════════════════════

TN_STATE_BASE = "https://stateoftn-careers.ttcportals.com"

# Nashville-metro county names used to filter statewide listings
NASHVILLE_COUNTIES = {
    "davidson", "williamson", "rutherford", "wilson",
    "sumner", "cheatham", "dickson", "robertson",
    "nashville", "brentwood", "franklin", "murfreesboro",
    "smyrna", "gallatin", "hendersonville",
}


def _tn_is_nashville_area(location: str) -> bool:
    """
    Keep jobs explicitly in Nashville-metro counties, plus statewide/multiple-location
    postings (which are often based in Nashville as the state capital).
    """
    loc = location.lower().strip()
    if not loc:
        return True  # no location = likely Nashville HQ
    STATEWIDE_TERMS = {"statewide", "multiple", "various", "all counties", "multiple locations"}
    if any(t in loc for t in STATEWIDE_TERMS):
        return True
    return any(county in loc for county in NASHVILLE_COUNTIES)


def scrape_tn_state() -> list[dict]:
    """
    Scrape Tennessee state careers portal (TTCPortals) using Playwright.
    Runs a visible Chrome window to bypass Cloudflare bot protection.
    Filters for Nashville-metro area jobs only, then fetches full descriptions.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    _stealth = Stealth()
    print("[TN State] Opening browser (stealth mode — no Cloudflare challenge expected)...")

    nashville_jobs = []
    seen_titles = set()  # deduplicate same job posted across multiple counties

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=BROWSER_UA,
            viewport={"width": 1280, "height": 800},
        )
        listing_page = context.new_page()
        _stealth.apply_stealth_sync(listing_page)

        page_num = 1
        while True:
            url = f"{TN_STATE_BASE}/jobs/search?page={page_num}"
            try:
                listing_page.goto(url, wait_until="domcontentloaded", timeout=30000)
                listing_page.wait_for_selector("div.large-3 a[href*='/jobs/']", timeout=30000)
            except Exception as e:
                print(f"  ERROR loading page {page_num}: {e}")
                break

            html = listing_page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Each job is a div.row that contains a large-3 column with a job link
            job_rows = [
                div for div in soup.select("div.row")
                if div.select_one("div.large-3 a[href*='/jobs/']")
            ]

            if not job_rows:
                break

            new_this_page = 0
            for row in job_rows:
                link = row.select_one("div.large-3 a[href*='/jobs/']")
                title_raw = link.get_text(strip=True) if link else ""
                job_url   = link.get("href", "") if link else ""

                # Strip date/job-code suffix, e.g. "TITLE* - 04072026-76480"
                title = re.sub(r"\s*\*?\s*-\s*\d[\d/]+-\d+\s*$", "", title_raw).strip().title()

                # Columns: large-3 (title) | large-2 (location) | large-2 (date) | large-2 (agency)
                cols = row.select("div.large-2")
                location = ""
                posted   = ""
                agency   = ""
                if len(cols) >= 1:
                    location = re.sub(r"(?i)^location:\s*", "", cols[0].get_text(strip=True))
                if len(cols) >= 2:
                    posted = re.sub(r"(?i)last day to apply:\s*", "", cols[1].get_text(strip=True))
                if len(cols) >= 3:
                    agency = re.sub(r"(?i)^agency:\s*", "", cols[2].get_text(strip=True))

                # Filter for Nashville metro only
                if location and not _tn_is_nashville_area(location):
                    continue

                # Deduplicate same job posted across multiple counties.
                # Prefer Davidson County — if we already have this title from another
                # county and the current one is Davidson, replace it.
                title_key = title.lower().strip()
                is_davidson = "davidson" in location.lower()
                if title_key in seen_titles:
                    if is_davidson:
                        # Replace the existing entry with this Davidson County one
                        nashville_jobs[:] = [
                            j for j in nashville_jobs if j["title"].lower().strip() != title_key
                        ]
                    else:
                        continue
                seen_titles.add(title_key)

                loc_display = f"{location}, TN" if location else "Nashville, TN"
                nashville_jobs.append({
                    "title":    title,
                    "location": loc_display,
                    "posted":   f"Closes {posted}" if posted else "",
                    "url":      job_url,
                    "agency":   agency,
                })
                new_this_page += 1

            print(f"  Page {page_num}: +{new_this_page} Nashville-area jobs (total: {len(nashville_jobs)})")

            # Check for next page — links may appear as /jobs/search?page=N or ?page=N#
            next_page_num = page_num + 1
            has_next = soup.select_one(
                f"a[href='/jobs/search?page={next_page_num}'], "
                f"a[href='/jobs/search?page={next_page_num}#']"
            )
            if not has_next:
                break
            page_num += 1
            listing_page.wait_for_timeout(1500)

        # Fetch full descriptions for Nashville-area jobs in the same browser session
        print(f"\n[TN State] Fetching descriptions for {len(nashville_jobs)} Nashville-area jobs...")
        results = []
        detail_page = context.new_page()
        _stealth.apply_stealth_sync(detail_page)

        for i, job in enumerate(nashville_jobs):
            desc = f"Agency: {job['agency']}. Tennessee state government position."
            if job["url"]:
                try:
                    detail_page.goto(job["url"], wait_until="domcontentloaded", timeout=20000)
                    detail_page.wait_for_timeout(3000)
                    dhtml = detail_page.content()
                    dsoup = BeautifulSoup(dhtml, "html.parser")
                    for sel in ["div.job-description", "div#job-description",
                                "div.description-body", "main article", "div.main-content"]:
                        tag = dsoup.select_one(sel)
                        if tag:
                            desc = tag.get_text(" ", strip=True)
                            break
                except Exception as e:
                    pass  # keep default desc on error

            results.append({
                "title":       job["title"],
                "location":    job["location"],
                "posted":      job["posted"],
                "url":         job["url"],
                "description": desc,
                "salary":      "",
                "source":      "TN State",
            })

            if (i + 1) % 10 == 0 or (i + 1) == len(nashville_jobs):
                print(f"  {i+1}/{len(nashville_jobs)} descriptions fetched")

        browser.close()

    print(f"[TN State] Done — {len(results)} Nashville-area jobs.\n")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# Williamson County Government  (CivicPlus HTML)
# ══════════════════════════════════════════════════════════════════════════════

WILLIAMSON_BASE = "https://www.williamsoncounty-tn.gov"

def scrape_williamson_county() -> list[dict]:
    url     = f"{WILLIAMSON_BASE}/Jobs.aspx"
    headers = {"User-Agent": BROWSER_UA}

    print("[Williamson County] Fetching job listings...")
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  ERROR: {e}")
        return []

    soup    = BeautifulSoup(r.text, "html.parser")
    results = []

    for card in soup.select("div.job"):
        link = card.select_one("h3 a")
        if not link:
            continue

        title    = link.get_text(strip=True)
        href     = link.get("href", "")
        job_url  = (WILLIAMSON_BASE + href) if href.startswith("/") else href

        # Posted date — first <span> after <h3>
        spans  = card.select("span")
        posted = spans[0].get_text(strip=True) if spans else ""

        # Description excerpt — <p> tag
        p_tag = card.select_one("p")
        desc  = p_tag.get_text(" ", strip=True) if p_tag else ""

        results.append({
            "title":       title,
            "location":    "Williamson County, TN",
            "posted":      posted,
            "url":         job_url,
            "description": desc,
            "salary":      "",
            "source":      "Williamson County",
        })

    print(f"[Williamson County] Done — {len(results)} jobs.\n")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# MNPS — Metro Nashville Public Schools  (Oracle Fusion HCM)
# ══════════════════════════════════════════════════════════════════════════════

MNPS_API = "https://ibqhjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

def scrape_mnps() -> list[dict]:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept":     "application/json",
    }

    print("[MNPS] Fetching job listings...")
    results = []
    offset  = 0
    limit   = 25

    while True:
        params = {
            "expand": "requisitionList",
            "limit":  str(limit),
            "offset": str(offset),
        }
        try:
            r = requests.get(MNPS_API, headers=headers, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  ERROR at offset {offset}: {e}")
            break

        items = data.get("items", [])
        if not items:
            break

        for item in items:
            reqs = item.get("requisitionList", [])
            for req in reqs:
                title    = req.get("Title", "") or req.get("Name", "")
                location = req.get("PrimaryLocation", "") or "Nashville, TN"
                posted   = req.get("PostedDate", "")[:10] if req.get("PostedDate") else ""
                job_id   = req.get("Id", "")
                job_url  = req.get("ExternalURL", "") or f"https://ibqhjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/MNPS/requisitions/{job_id}"
                desc     = req.get("ExternalDescriptionStr", "") or req.get("ShortDescription", "")

                results.append({
                    "title":       title,
                    "location":    location,
                    "posted":      posted,
                    "url":         job_url,
                    "description": strip_html(desc),
                    "salary":      "",
                    "source":      "MNPS",
                })

        if not data.get("hasMore", False):
            break
        offset += limit
        time.sleep(0.3)

    if not results:
        print("  No current postings found (MNPS portal may be between hiring cycles).")
    print(f"[MNPS] Done — {len(results)} jobs.\n")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# Metro Nashville count verification
# ══════════════════════════════════════════════════════════════════════════════

def verify_metro_nashville_count() -> int:
    """
    Run a quick second pass on Metro Nashville to verify we captured all jobs.
    Returns the count from the verification pass for comparison.
    """
    headers = {
        "User-Agent":       BROWSER_UA,
        "Accept":           "application/json, text/html, */*",
        "X-Requested-With": "XMLHttpRequest",
    }
    total = 0
    page  = 1
    while True:
        try:
            r = requests.get(
                "https://www.governmentjobs.com/careers/nashville",
                headers=headers, params={"page": str(page)}, timeout=15
            )
            soup  = BeautifulSoup(r.text, "html.parser")
            items = soup.select("li.list-item")
            if not items:
                break
            total += len(items)
            if len(items) < 10:
                break
            page += 1
            time.sleep(0.3)
        except Exception:
            break
    return total


# ══════════════════════════════════════════════════════════════════════════════
# Manual-navigation Playwright scraper
# Used for sites that block automated requests (Incapsula, ADP, Taleo, etc.)
# Opens a visible Chrome window. If a bot challenge appears, click through it.
# Script waits until job listings are detected before scraping.
# ══════════════════════════════════════════════════════════════════════════════

def _scrape_with_browser(
    label: str,
    start_url: str,
    ready_selector: str,
    extract_fn,
    next_page_fn=None,
    source_name: str = None,
) -> list[dict]:
    """
    Generic Playwright scraper for bot-protected job boards.
    - Opens a visible Chrome window and navigates to start_url
    - Waits up to 90s for ready_selector (gives time to solve any challenge)
    - Calls extract_fn(soup) -> list[dict] to get jobs from rendered HTML
    - Calls next_page_fn(page, page_num) -> bool to advance pages (optional)
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    _stealth   = Stealth()
    src_label  = source_name or label
    results    = []

    print(f"[{label}] Opening browser...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=BROWSER_UA,
            viewport={"width": 1280, "height": 800},
        )
        pw_page = context.new_page()
        _stealth.apply_stealth_sync(pw_page)

        try:
            pw_page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            pw_page.wait_for_selector(ready_selector, timeout=90000)
        except Exception as e:
            print(f"  Could not load {label}: {e}")
            browser.close()
            return []

        page_num = 1
        while True:
            html  = pw_page.content()
            soup  = BeautifulSoup(html, "html.parser")
            jobs  = extract_fn(soup, src_label)
            results.extend(jobs)
            print(f"  Page {page_num}: +{len(jobs)} jobs (total: {len(results)})")

            if next_page_fn is None or not next_page_fn(pw_page, soup, page_num):
                break
            page_num += 1
            try:
                pw_page.wait_for_selector(ready_selector, timeout=20000)
            except Exception:
                break

        browser.close()

    print(f"[{label}] Done — {len(results)} jobs.\n")
    return results


# ── ADP Workforce Now helper (shared by BNA and WeGo) ─────────────────────────

def _scrape_adp(label: str, cid: str, source_name: str) -> list[dict]:
    """
    Scrapes an ADP Workforce Now career page via their public REST API.
    No browser needed — the /public/events/staffing/v1/job-requisitions endpoint
    requires no authentication and returns all jobs with full salary data.
    """
    api_url = (
        "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing"
        f"/v1/job-requisitions?cid={cid}&ccId=19000101_000001&count=200&offset=0"
    )
    career_base = (
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
        f"?cid={cid}&ccId=19000101_000001&type=JS&lang=en_US&selectedMenuKey=CurrentOpenings"
    )

    print(f"[{label}] Fetching from ADP public API...")
    try:
        r = requests.get(api_url, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ERROR: {e}")
        return []

    detail_base = (
        "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing"
        f"/v1/job-requisitions/{{item_id}}?cid={cid}&ccId=19000101_000001"
    )

    results = []
    requisitions = data.get("jobRequisitions", [])
    for idx, j in enumerate(requisitions):
        title  = j.get("requisitionTitle", "").strip()
        if not title:
            continue

        raw_id = j.get("itemID", "")
        job_id = raw_id.split("_")[0] if "_" in raw_id else raw_id
        job_url = f"{career_base}&jobId={job_id}" if job_id else career_base

        pay      = j.get("payGradeRange", {})
        min_r    = pay.get("minimumRate", {}).get("amountValue")
        max_r    = pay.get("maximumRate", {}).get("amountValue")
        sal_type = next(
            (f["shortName"] for f in j.get("customFieldGroup", {}).get("codeFields", [])
             if f.get("nameCode", {}).get("codeValue") == "SalaryType"),
            ""
        )
        if min_r and max_r:
            if sal_type and sal_type.lower() in ("hourly", "hr"):
                salary = f"${min_r:,.2f} - ${max_r:,.2f} Hourly"
            else:
                salary = f"${min_r:,.0f} - ${max_r:,.0f} Annually"
        else:
            salary = ""

        post_date = j.get("postDate", "")[:10]

        # Fetch full description from detail endpoint
        desc = ""
        if raw_id:
            try:
                dr = requests.get(
                    detail_base.format(item_id=raw_id),
                    headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
                    timeout=10,
                )
                if dr.ok:
                    html_desc = dr.json().get("requisitionDescription", "")
                    desc = BeautifulSoup(html_desc, "html.parser").get_text(" ", strip=True)
            except Exception:
                pass

        results.append({
            "title": title, "location": "Nashville, TN",
            "posted": post_date, "url": job_url,
            "description": desc, "salary": salary, "source": source_name,
        })
        if (idx + 1) % 5 == 0:
            print(f"  {idx + 1}/{len(requisitions)} descriptions fetched")

    print(f"[{label}] Done — {len(results)} jobs.\n")
    return results


# ── BNA Nashville Airport Authority (ADP Workforce Now) ──────────────────────

def scrape_bna() -> list[dict]:
    return _scrape_adp("BNA Airport Authority", "dd2210b0-7dc9-4b51-8524-cabc28981ada", "BNA")


# ── WeGo Public Transit (ADP Workforce Now) ───────────────────────────────────

def scrape_wego() -> list[dict]:
    return _scrape_adp("WeGo Transit", "676d8aac-7a2c-471a-8aa3-f40367a5c457", "WeGo")


# ── THDA Tennessee Housing Development Agency (Taleo) ────────────────────────

def scrape_thda() -> list[dict]:
    url      = "https://phh.tbe.taleo.net/phh01/ats/careers/v2/searchResults?org=THDA2&cws=38"
    selector = "div.oracletaleocwsv2-accordion"

    def extract(soup, source):
        jobs = []
        for acc in soup.select("div.oracletaleocwsv2-accordion"):
            link_el = acc.select_one("a.viewJobLink")
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            href  = link_el.get("href", "")
            if not title:
                continue
            head_info = acc.select_one("div.oracletaleocwsv2-accordion-head-info")
            location  = "Nashville, TN"
            if head_info:
                loc_divs = head_info.select("div[tabindex='0']")
                if loc_divs:
                    location = loc_divs[0].get_text(strip=True)
            jobs.append({
                "title": title, "location": location,
                "posted": "", "url": href,
                "description": "", "salary": "", "source": source,
            })
        return jobs

    return _scrape_with_browser("THDA", url, selector, extract, source_name="THDA")


# ── City of Franklin ──────────────────────────────────────────────────────────

def scrape_franklin() -> list[dict]:
    """
    City of Franklin uses Cadient Talent (JSP-based ATS).
    Simple requests fetch — no browser required.
    """
    FRANKLIN_JOBS_URL = (
        "https://cta.cadienttalent.com/index.jsp"
        "?SHOWRESULTS=true"
        "&APPLICATIONNAME=CityofFranklinTNKTMDReqExt"
        "&SEARCHOBJECT=Posting"
        "&SOURCE=featuredjobs"
        "&locale=en_US"
        "&EVENT=com.deploy.application.ca.plugin.PostingSearch.doSearch"
        "&SEQ=postingSearchResults&"
    )
    FRANKLIN_BASE = "https://cta.cadienttalent.com"

    print("[City of Franklin] Fetching from Cadient Talent...")
    try:
        r = requests.get(FRANKLIN_JOBS_URL, headers={"User-Agent": BROWSER_UA}, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  ERROR: {e}")
        return []

    soup    = BeautifulSoup(r.text, "html.parser")
    results = []

    # Cadient Talent renders job rows as <tr> elements inside a results table,
    # or as divs/anchors with job title links pointing to index.jsp?SEQ=jobDetails...
    SKIP_TITLES = {"job search", "all open jobs", "search", "apply", "login", "register"}

    for link in soup.find_all("a", href=re.compile(r"jobDetails|postingDetail|Posting", re.I)):
        title = link.get_text(strip=True)
        href  = link.get("href", "")
        if not title or len(title) < 5:
            continue
        if title.lower() in SKIP_TITLES:
            continue
        full_url = (FRANKLIN_BASE + href) if href.startswith("/") else href

        # Pull salary from surrounding row — extract first dollar-amount pattern only
        row = link.find_parent("tr") or link.find_parent("div")
        salary = ""
        if row:
            row_text = row.get_text(" ", strip=True)
            sal_match = re.search(r"\$[\d,]+(?:\.\d+)?(?:\s*[-–]\s*\$[\d,]+(?:\.\d+)?)?(?:/(?:hr|hour|Hourly|yr|year|Annually|Annual)|\s+(?:Hourly|Annually|Annual|per\s+hour|per\s+year))?", row_text, re.I)
            if sal_match:
                salary = sal_match.group(0).strip()

        results.append({
            "title": title, "location": "Franklin, TN",
            "posted": "", "url": full_url,
            "description": "", "salary": salary, "source": "City of Franklin",
        })

    print(f"[City of Franklin] {len(results)} jobs found.\n")
    return results


# ── TVA Tennessee Valley Authority (TTCPortals by Tyler Technologies) ──────────

def scrape_tva() -> list[dict]:
    """
    TVA uses TTCPortals (same platform as TN State careers) at tvacareers.ttcportals.com.
    The job listing structure is identical to scrape_tn_state(); we reuse the same
    selectors and filter for Nashville-metro jobs only.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    TVA_BASE = "https://tvacareers.ttcportals.com"
    print("[TVA] Opening browser (TTCPortals)...")

    tva_jobs = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(user_agent=BROWSER_UA, viewport={"width": 1280, "height": 800})
        listing_page = context.new_page()
        Stealth().apply_stealth_sync(listing_page)

        page_num = 1
        while True:
            url = f"{TVA_BASE}/jobs/search?sort_by=cfml3,desc&page={page_num}"
            try:
                listing_page.goto(url, wait_until="domcontentloaded", timeout=30000)
                listing_page.wait_for_selector("div.large-3 a[href*='/jobs/'], div.row", timeout=20000)
            except Exception as e:
                print(f"  ERROR loading TVA page {page_num}: {e}")
                break

            html = listing_page.content()
            soup = BeautifulSoup(html, "html.parser")

            job_rows = [
                div for div in soup.select("div.row")
                if div.select_one("div.large-3 a[href*='/jobs/']")
            ]
            if not job_rows:
                break

            new_this_page = 0
            for row in job_rows:
                link     = row.select_one("div.large-3 a[href*='/jobs/']")
                title_raw = link.get_text(strip=True) if link else ""
                job_url   = link.get("href", "") if link else ""
                title = re.sub(r"\s*\*?\s*-\s*\d[\d/]+-\d+\s*$", "", title_raw).strip().title()

                cols     = row.select("div.large-2")
                location = re.sub(r"(?i)^location:\s*", "", cols[0].get_text(strip=True)) if cols else ""
                posted   = re.sub(r"(?i)last day to apply:\s*", "", cols[1].get_text(strip=True)) if len(cols) > 1 else ""

                if location and not _tn_is_nashville_area(location):
                    continue

                tva_jobs.append({
                    "title": title, "location": f"{location}, TN" if location else "Nashville, TN",
                    "posted": f"Closes {posted}" if posted else "",
                    "url": job_url, "description": "", "salary": "", "source": "TVA",
                })
                new_this_page += 1

            total_rows = len(job_rows)
            print(f"  Page {page_num}: {total_rows} total rows, +{new_this_page} Nashville-area TVA jobs (total: {len(tva_jobs)})")

            next_num = page_num + 1
            has_next = soup.select_one(
                f"a[href*='page={next_num}'], a[href*='page={next_num}#']"
            )
            if not has_next:
                break
            page_num += 1
            listing_page.wait_for_timeout(1000)

        browser.close()

    print(f"[TVA] Done — {len(tva_jobs)} Nashville-area jobs.\n")
    return tva_jobs


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    all_jobs = []

    # Federal
    all_jobs.extend(scrape_usajobs())

    # NeoGov agencies (Metro Nashville + Brentwood)
    for slug, label in NEOGOV_AGENCIES:
        all_jobs.extend(scrape_neogov(slug, label))

    # Verify Metro Nashville count with a second pass
    metro_count = sum(1 for j in all_jobs if j["source"] == "Metro Nashville")
    verify_count = verify_metro_nashville_count()
    if abs(verify_count - metro_count) > 3:
        print(f"[WARNING] Metro Nashville count mismatch: scraped {metro_count}, verification pass found {verify_count}. Re-running...")
        all_jobs = [j for j in all_jobs if j["source"] != "Metro Nashville"]
        all_jobs.extend(scrape_neogov("nashville", "Metro Nashville"))
    else:
        print(f"[Metro Nashville] Count verified: {metro_count} jobs (verification pass: {verify_count})")

    # Williamson County
    all_jobs.extend(scrape_williamson_county())

    # MNPS
    all_jobs.extend(scrape_mnps())

    # TN State
    all_jobs.extend(scrape_tn_state())

    # Manual-navigation sources (bot-protected — Chrome window will open for each)
    print("\n" + "="*60)
    print("MANUAL NAVIGATION SOURCES")
    print("A Chrome window will open for each. If a bot challenge")
    print("appears, click through it. Otherwise just watch.")
    print("="*60 + "\n")
    all_jobs.extend(scrape_bna())
    all_jobs.extend(scrape_wego())
    all_jobs.extend(scrape_thda())
    all_jobs.extend(scrape_franklin())
    # TVA removed — no Nashville-area openings

    print(f"\nTotal collected across all sources: {len(all_jobs)}")

    # Summary by source
    from collections import Counter
    counts = Counter(j["source"] for j in all_jobs)
    for src, n in sorted(counts.items()):
        print(f"  {src}: {n}")

    with open("nashville_jobs_full.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, indent=2, ensure_ascii=False)

    print("\nSaved nashville_jobs_full.json")


if __name__ == "__main__":
    main()
