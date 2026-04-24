import json
import re

with open("jobs_full.json", encoding="utf-8") as f:
    jobs = json.load(f)

# Replicate the YES scoring logic from evaluate_jobs.py
STRONG_YES_TITLE = [
    "program manager", "program director", "program administrator",
    "project manager", "project director",
    "IT manager", "IT director", "IT program",
    "technology manager", "technology director", "technology program",
    "digital transformation", "information technology",
    "operations manager", "operations director",
    "contract manager", "contract administrator", "procurement manager",
    "policy analyst", "policy advisor", "policy manager",
    "portfolio manager", "portfolio director",
    "strategy", "strategic",
    "product manager", "product director",
    "data program", "data manager",
    "vendor manager", "vendor management",
    "solutions architect", "enterprise architect",
    "change management", "organizational development",
    "business analyst", "business process",
    "compliance manager", "risk manager",
    "associate director", "assistant director",
    "director of",
]

HARD_NO_TITLE = [
    "engineer", "engineering", "accountant", "accounting", "auditor", "audit",
    "nurse", "physician", "doctor", "clinical", "medical", "dental", "pharmacy",
    "custodian", "maintenance", "electrician", "plumber", "hvac", "carpenter",
    "chef", "cook", "baker", "barista", "food service", "dining",
    "librarian", "archivist", "police", "security officer", "corrections",
    "groundskeeper", "landscaping", "research scientist", "postdoctoral", "postdoc",
    "professor", "lecturer", "faculty", "instructor", "coach", "athletic", "recreation",
    "social worker", "counselor", "therapist", "veterinarian", "animal",
    "painter", "driver", "transport", "warehouse", "inventory",
]

HARD_NO_DESC = [
    r"professional engineer|P\.E\. license|PE license",
    r"licensed professional engineer",
    r"CPA|certified public accountant",
    r"ecology|ecological|karst|endangered species",
    r"blueprint|construction site|job site|general contractor",
    r"HVAC|plumbing|electrical systems|building systems",
    r"FMLA|ADA accommodation|workplace investigation|employee relations",
    r"ICS 100|ICS 200|ICS 300|ICS 400|emergency operations center",
    r"psychiatric|inpatient psychiatric|mental health facility operations",
    r"Adobe Creative|video production|video editing|motion graphics",
    r"5 years.*Texas state agency|five years.*Texas state agency",
    r"federal grant.*lifecycle|grant writing|CFDA|grant management",
    r"bill analysis|legislative bill|state agency rulemaking",
    r"major gift|principal gift|planned giving|gift officer",
    r"fundraising|donor relations|benefactor|alumni relations",
    r"annual fund|capital campaign|endowment|development officer",
    r"prospect research|donor prospect",
]

GREEN_FLAGS_DESC = [
    r"program management|project management",
    r"stakeholder|cross.functional",
    r"IT program|technology program|software delivery",
    r"SaaS|cloud platform|digital transformation",
    r"government.*technology|technology.*government",
    r"vendor management|contract management|procurement",
    r"policy development|policy implementation",
    r"process improvement|operational efficiency",
    r"portfolio management",
    r"change management",
    r"strategic plan|strategic initiative",
    r"federal|FedRAMP|FISMA|compliance",
    r"agile|scrum|product management",
]

def score(job):
    t = job.get("title", "").lower()
    desc = job.get("description", "")

    for kw in HARD_NO_TITLE:
        if kw in t:
            return -2
    ts = 0
    for kw in STRONG_YES_TITLE:
        if kw in t:
            ts = 2
            break

    for pattern in HARD_NO_DESC:
        if re.search(pattern, desc, re.IGNORECASE):
            return ts - 3
    hits = sum(1 for p in GREEN_FLAGS_DESC if re.search(p, desc, re.IGNORECASE))
    ds = 3 if hits >= 4 else 2 if hits >= 2 else 1 if hits == 1 else 0

    return ts + ds

def get_min_salary(desc):
    amounts = re.findall(r"\$([0-9]{1,3}(?:,[0-9]{3})+)", desc)
    nums = [int(a.replace(",", "")) for a in amounts if a]
    salaries = [n for n in nums if 30000 <= n <= 300000]
    return min(salaries) if salaries else None

yes_jobs = [j for j in jobs if score(j) >= 3]
print(f"Total YES jobs: {len(yes_jobs)}")

below = [(j["title"], get_min_salary(j["description"])) for j in yes_jobs if (get_min_salary(j["description"]) or 999999) < 70000]
no_sal = [j["title"] for j in yes_jobs if get_min_salary(j["description"]) is None]

print(f"YES jobs below $70k: {len(below)}")
print(f"YES jobs with no salary listed: {len(no_sal)}")
print()
if below:
    print("Below $70k:")
    for title, sal in sorted(below, key=lambda x: x[1]):
        print(f"  ${sal:,} — {title}")
