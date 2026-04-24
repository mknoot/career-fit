import requests
import json
import time
import re

BASE_URL = "https://utaustin.wd1.myworkdayjobs.com/wday/cxs/utaustin/UTstaff"
JOBS_URL = f"{BASE_URL}/jobs"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def strip_html(html):
    """Remove HTML tags and clean up whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_all_jobs():
    all_jobs = []
    offset = 0
    limit = 20
    total = None

    print("Fetching job listings...")

    while True:
        payload = {
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": ""
        }

        try:
            resp = requests.post(JOBS_URL, json=payload, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ERROR at offset {offset}: {e}")
            break

        jobs = data.get("jobPostings", [])
        if total is None:
            total = data.get("total", 0)
            print(f"  Total jobs reported by API: {total}")

        if not jobs:
            print(f"  No jobs returned at offset {offset}, stopping.")
            break

        all_jobs.extend(jobs)
        print(f"  Fetched {len(all_jobs)}/{total} jobs")

        offset += limit
        if offset >= total:
            break

        time.sleep(0.25)

    return all_jobs


def fetch_job_description(external_path):
    """Fetch and return clean text description for a single job."""
    url = f"{BASE_URL}{external_path}"
    try:
        resp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        info = data.get("jobPostingInfo", {})
        html_desc = info.get("jobDescription", "")
        return strip_html(html_desc)
    except Exception as e:
        return f"[Error: {e}]"


def main():
    jobs = fetch_all_jobs()
    print(f"\nTotal collected: {len(jobs)}\n")

    # Save plain list first
    with open("jobs_list.txt", "w", encoding="utf-8") as f:
        f.write(f"Total jobs: {len(jobs)}\n\n")
        for job in jobs:
            f.write(f"{job.get('title')} | {job.get('locationsText')} | {job.get('postedOn')} | {job.get('externalPath', '')}\n")
    print("Saved jobs_list.txt")

    # Fetch descriptions
    print(f"\nFetching descriptions for {len(jobs)} jobs...")
    results = []
    for i, job in enumerate(jobs):
        path = job.get("externalPath", "")
        desc = fetch_job_description(path) if path else ""
        results.append({
            "title": job.get("title", ""),
            "location": job.get("locationsText", ""),
            "posted": job.get("postedOn", ""),
            "path": path,
            "description": desc
        })
        if (i + 1) % 50 == 0 or (i + 1) == len(jobs):
            print(f"  {i+1}/{len(jobs)} descriptions fetched")
        time.sleep(0.2)

    with open("jobs_full.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nDone. Saved {len(results)} jobs to jobs_full.json")


if __name__ == "__main__":
    main()
