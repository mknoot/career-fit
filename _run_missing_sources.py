"""
Scrape only BNA, WeGo, THDA, Franklin, and TVA, then merge into
nashville_jobs_full.json (replacing any prior entries for those sources).
Run evaluate_nashville.py afterwards to regenerate the Excel.
"""
import json
import sys
sys.path.insert(0, ".")

from scrape_nashville import scrape_bna, scrape_wego, scrape_thda, scrape_franklin

SOURCES_TO_REPLACE = {"BNA", "WeGo", "THDA", "City of Franklin", "TVA"}

# Load existing jobs, drop old entries for these sources
with open("nashville_jobs_full.json", encoding="utf-8") as f:
    existing = json.load(f)

kept = [j for j in existing if j.get("source") not in SOURCES_TO_REPLACE]
print(f"Kept {len(kept)} jobs from other sources.")

# Scrape the fixed sources
fresh = []
fresh.extend(scrape_bna())
fresh.extend(scrape_wego())
fresh.extend(scrape_thda())
fresh.extend(scrape_franklin())

print(f"\nFresh from fixed sources: {len(fresh)}")
for src in SOURCES_TO_REPLACE:
    n = sum(1 for j in fresh if j["source"] == src)
    print(f"  {src}: {n}")

all_jobs = kept + fresh
with open("nashville_jobs_full.json", "w", encoding="utf-8") as f:
    json.dump(all_jobs, f, ensure_ascii=False, indent=2)
print(f"\nSaved {len(all_jobs)} total jobs to nashville_jobs_full.json")

# Auto-evaluate
print("\nRunning evaluator...")
import evaluate_nashville
evaluate_nashville.main()
