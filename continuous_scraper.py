"""
Continuous Job Scraper — scheduled polling with delta detection.

Usage:
    python continuous_scraper.py           # Full run (all companies)
    python continuous_scraper.py --demo    # Demo run (3 companies, ~20-30 jobs)
    python continuous_scraper.py --demo --force-new   # Demo + treat all as new

Output:
    data/job_listings.json   — all discovered jobs
    data/seen_jobs.json      — dedup registry (apply_url → timestamp)
"""

import json, time, re, os, sys
from pathlib import Path
from datetime import datetime, timezone
import requests

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

SEEN_FILE = DATA_DIR / "seen_jobs.json"
JOBS_FILE = DATA_DIR / "job_listings.json"

COMPANIES = [
    {"name": "Stripe",       "board": "stripe",      "domain": "stripe.com"},
    {"name": "Lyft",         "board": "lyft",        "domain": "lyft.com"},
    {"name": "Pinterest",    "board": "pinterest",   "domain": "pinterest.com"},
    {"name": "Datadog",      "board": "datadog",     "domain": "datadoghq.com"},
    {"name": "GoDaddy",      "board": "godaddy",     "domain": "godaddy.com"},
    {"name": "Vercel",       "board": "vercel",      "domain": "vercel.com"},
    {"name": "GitLab",       "board": "gitlab",      "domain": "gitlab.com"},
    {"name": "Reddit",       "board": "reddit",      "domain": "reddit.com"},
    {"name": "MongoDB",      "board": "mongodb",     "domain": "mongodb.com"},
    {"name": "Cloudflare",   "board": "cloudflare",  "domain": "cloudflare.com"},
    {"name": "Okta",         "board": "okta",        "domain": "okta.com"},
    {"name": "Twilio",       "board": "twilio",      "domain": "twilio.com"},
    {"name": "Airbnb",       "board": "airbnb",      "domain": "airbnb.com"},
    {"name": "Dropbox",      "board": "dropbox",     "domain": "dropbox.com"},
    {"name": "Instacart",    "board": "instacart",   "domain": "instacart.com"},
    {"name": "Asana",        "board": "asana",       "domain": "asana.com"},
    {"name": "Affirm",       "board": "affirm",      "domain": "affirm.com"},
    {"name": "Robinhood",    "board": "robinhood",   "domain": "robinhood.com"},
    {"name": "Brex",         "board": "brex",        "domain": "brex.com"},
    {"name": "Carta",        "board": "carta",       "domain": "carta.com"},
    {"name": "Figma",        "board": "figma",       "domain": "figma.com"},
    {"name": "Intercom",     "board": "intercom",    "domain": "intercom.com"},
    {"name": "Calendly",     "board": "calendly",    "domain": "calendly.com"},
    {"name": "Amplitude",    "board": "amplitude",   "domain": "amplitude.com"},
    {"name": "Webflow",      "board": "webflow",     "domain": "webflow.com"},
    {"name": "Anthropic",    "board": "anthropic",   "domain": "anthropic.com"},
    {"name": "Descript",     "board": "descript",    "domain": "descript.com"},
]

DEMO_COMPANIES = [
    {"name": "Stripe",       "board": "stripe",      "domain": "stripe.com"},
    {"name": "Figma",        "board": "figma",       "domain": "figma.com"},
    {"name": "Calendly",     "board": "calendly",    "domain": "calendly.com"},
]


def infer_employment_type(job_title, content=""):
    text = (job_title + " " + content[:2000]).lower()
    if re.search(r'\bintern\b|\binternship\b', text): return 'Internship'
    if re.search(r'\bcontract\b|\btemporary\b|\btemp\b', text): return 'Contract'
    if re.search(r'\bpart[-\s]?time\b', text): return 'Part-time'
    return 'Full-time'


def fetch_company_jobs(company):
    board = company.get("board") or company["name"].lower().replace(" ", "")
    name = company["name"]
    domain = company.get("domain", "")
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

    try:
        resp = requests.get(url, timeout=15)
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    jobs_data = resp.json().get("jobs", [])
    results = []
    career_page = f"https://{domain}/careers" if domain else ""
    logo_url = f"https://logo.clearbit.com/{domain}" if domain else ""

    for job in jobs_data:
        departments = job.get("departments", [])
        gh_jid = job.get("id")
        results.append({
            "company_name": job.get("company_name") or name,
            "company_domain": domain,
            "career_page": career_page,
            "job_title": job.get("title", "Unknown"),
            "department": departments[0]["name"] if departments else "General",
            "location": job.get("location", {}).get("name", "Remote"),
            "employment_type": infer_employment_type(job.get("title", ""), job.get("content", "")),
            "apply_url": job.get("absolute_url", ""),
            "boards_url": f"https://boards.greenhouse.io/{board}/jobs/{gh_jid}" if gh_jid else "",
            "source": "greenhouse",
            "ats": "Greenhouse",
            "logo_url": logo_url,
        })

    return results


def load_seen():
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    return {"urls": {}, "companies_seen": []}


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False), encoding="utf-8")


def load_jobs():
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    return []


def save_jobs(jobs):
    for idx, job in enumerate(jobs, 1):
        job["id"] = idx
    JOBS_FILE.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")


def verify_url(url):
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True)
        return resp.status_code == 200
    except:
        return False


def run(companies, force_new=False):
    seen = load_seen()
    existing = load_jobs()
    existing_by_url = {j["apply_url"]: j for j in existing}

    all_new = []
    all_current_urls = set()

    print(f"scraping {len(companies)} companies...\n")

    for i, company in enumerate(companies, 1):
        board = company.get("board", company["name"].lower().replace(" ", ""))
        is_first = board not in seen.get("companies_seen", []) and not force_new

        jobs = fetch_company_jobs(company)
        print(f"  [{i}/{len(companies)}] {company['name']:15s}  {len(jobs):4d} jobs", end="")

        if not jobs:
            print()
            continue

        urls = {j["apply_url"] for j in jobs}
        all_current_urls |= urls

        new_count = 0
        for job in jobs:
            if force_new or job["apply_url"] not in seen["urls"]:
                job["discovered_at"] = datetime.now(timezone.utc).isoformat()
                all_new.append(job)
                seen["urls"][job["apply_url"]] = time.time()
                new_count += 1

        if is_first:
            seen.setdefault("companies_seen", []).append(board)
            print(f"  (first scrape — archived)")
        elif new_count > 0:
            print(f"  ({new_count} new)")
        else:
            print()

        time.sleep(0.3)

    # Merge: keep existing + add new
    existing.extend(all_new)

    # Step 1 — mark active/inactive by API presence
    for job in existing:
        job["is_active"] = job["apply_url"] in all_current_urls

    # Step 2 — HEAD-check suspected-dead jobs to confirm
    suspected = [j for j in existing if not j.get("is_active")]
    if suspected:
        print(f"\nVerifying {len(suspected)} removed jobs...")
        recovered = 0
        for job in suspected:
            job["is_active"] = verify_url(job["apply_url"])
            if job["is_active"]:
                recovered += 1
        print(f"  {recovered} still live (recovered), {len(suspected) - recovered} confirmed dead")

    save_jobs(existing)
    save_seen(seen)

    print(f"\nDone! {len(all_new)} new jobs, {len(existing)} total\n")

    return existing


if __name__ == "__main__":
    is_demo = "--demo" in sys.argv
    force_new = "--force-new" in sys.argv

    if is_demo:
        print("=== DEMO MODE ===\n")
        companies = DEMO_COMPANIES
    else:
        companies = COMPANIES

    jobs = run(companies, force_new=force_new)

    active = [j for j in jobs if j.get("is_active", True)]
    print(f"Active jobs: {len(active)}")
    print(f"Output: {JOBS_FILE}")
