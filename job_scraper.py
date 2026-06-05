import requests, json, csv, os, re, time, sys
from pathlib import Path
from collections import Counter

# ============================================================
# CONFIG
# ============================================================
DEFAULT_RATE_LIMIT = 0.5
DEFAULT_TIMEOUT = 15
LOG_PREFIX = "[scraper]"

# ============================================================
# BUILT-IN COMPANY DATABASE (27 companies using Greenhouse)
# ============================================================
BUILT_IN_COMPANIES = [
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

# ============================================================
# HELPERS
# ============================================================
def log(msg):
    print(f"{LOG_PREFIX} {msg}")

def infer_employment_type(job_title, content=""):
    text = (job_title + " " + content[:2000]).lower()
    if re.search(r'\bintern\b|\binternship\b', text): return 'Internship'
    if re.search(r'\bcontract\b|\btemporary\b|\btemp\b', text): return 'Contract'
    if re.search(r'\bpart[-\s]?time\b', text): return 'Part-time'
    return 'Full-time'

def make_id_generator():
    i = 1
    while True:
        yield i
        i += 1

# ============================================================
# COMPANY LIST SOURCES
# ============================================================
def load_companies_from_csv(path):
    companies = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            companies.append({
                "name": row.get("name") or row.get("company_name") or "",
                "board": row.get("board") or row.get("ats_board") or "",
                "domain": row.get("domain") or row.get("company_domain") or "",
            })
    log(f"Loaded {len(companies)} companies from CSV: {path}")
    return companies

def load_companies_from_json(path):
    with open(path, "r", encoding="utf-8") as f:
        companies = json.load(f)
    log(f"Loaded {len(companies)} companies from JSON: {path}")
    return companies

def fetch_greenhouse_directory():
    api_url = "https://boards-api.greenhouse.io/v1/boards"
    try:
        resp = requests.get(api_url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            boards = data.get("boards", [])
            companies = []
            for b in boards:
                companies.append({
                    "name": b.get("name", ""),
                    "board": b.get("slug", ""),
                    "domain": "",
                })
            log(f"Fetched {len(companies)} companies from Greenhouse directory")
            return companies
        else:
            log(f"Greenhouse directory returned HTTP {resp.status_code}")
            return []
    except Exception as e:
        log(f"Failed to fetch Greenhouse directory: {e}")
        return []

def fetch_wikipedia_fortune_500():
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "titles": "List_of_largest_companies_by_revenue",
        "prop": "extracts",
        "explaintext": True,
        "section": 0,
    }
    companies = []
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            extract = page.get("extract", "")
            for line in extract.split("\n"):
                line = line.strip()
                if not line or line.startswith("=="):
                    continue
                parts = line.split("|")
                if len(parts) >= 2:
                    name = parts[1].strip()
                    if name and len(name) < 100:
                        board = name.lower().replace(" ", "").replace(".", "").replace(",", "")
                        domain = ""
                        companies.append({"name": name, "board": board, "domain": domain})
    except Exception as e:
        log(f"Wikipedia fetch failed: {e}")
    log(f"Parsed {len(companies)} companies from Wikipedia")
    return companies

# ============================================================
# SCRAPER: Greenhouse API
# ============================================================
def scrape_greenhouse(companies, rate_limit=DEFAULT_RATE_LIMIT):
    next_id = make_id_generator()
    all_jobs = []
    results = {"ok": 0, "empty": 0, "failed": 0, "jobs": 0}

    for company in companies:
        board = company.get("board") or company.get("name", "").lower().replace(" ", "")
        name = company.get("name", board)
        domain = company.get("domain", "")

        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        try:
            resp = requests.get(url, timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                results["failed"] += 1
                time.sleep(rate_limit)
                continue

            jobs_data = resp.json().get("jobs", [])
            if not jobs_data:
                results["empty"] += 1
                time.sleep(rate_limit)
                continue

            career_page = f"https://{domain}/careers" if domain else ""
            logo_url = f"https://logo.clearbit.com/{domain}" if domain else ""

            for job in jobs_data:
                title = job.get("title", "Unknown")
                departments = job.get("departments", [])
                department = departments[0]["name"] if departments else "General"
                location = job.get("location", {}).get("name", "Remote")
                apply_url = job.get("absolute_url", "")
                content = job.get("content", "")
                employment_type = infer_employment_type(title, content)

                all_jobs.append({
                    "id": next(next_id),
                    "company_name": job.get("company_name") or name,
                    "company_domain": domain,
                    "career_page": career_page,
                    "job_title": title,
                    "department": department,
                    "location": location,
                    "employment_type": employment_type,
                    "apply_url": apply_url,
                    "source": "greenhouse",
                    "ats": "Greenhouse",
                    "logo_url": logo_url,
                })

            results["jobs"] += len(jobs_data)
            results["ok"] += 1

        except Exception as e:
            results["failed"] += 1

        time.sleep(rate_limit)

    log(f"Greenhouse: {results['ok']} ok, {results['empty']} empty, {results['failed']} failed = {results['jobs']} jobs")
    return all_jobs

# ============================================================
# SCRAPER: Lever API
# ============================================================
def scrape_lever(companies, rate_limit=DEFAULT_RATE_LIMIT):
    next_id = make_id_generator()
    all_jobs = []
    results = {"ok": 0, "empty": 0, "failed": 0, "jobs": 0}

    for company in companies:
        board = company.get("board") or company.get("name", "").lower().replace(" ", "")
        name = company.get("name", board)
        domain = company.get("domain", "")

        url = f"https://api.lever.co/v0/postings/{board}?mode=json"
        try:
            resp = requests.get(url, timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                results["failed"] += 1
                time.sleep(rate_limit)
                continue

            jobs_data = resp.json()
            if not jobs_data:
                results["empty"] += 1
                time.sleep(rate_limit)
                continue

            career_page = f"https://{domain}/careers" if domain else ""
            logo_url = f"https://logo.clearbit.com/{domain}" if domain else ""

            for job in jobs_data:
                title = job.get("text", "Unknown")
                categories = job.get("categories", {}) or {}
                department = categories.get("team", "General")
                location = categories.get("location", "Remote")
                commitment = categories.get("commitment", "")
                apply_url = job.get("hostedUrl", "")
                employment_type = "Full-time"
                if commitment:
                    employment_type = infer_employment_type(commitment)

                all_jobs.append({
                    "id": next(next_id),
                    "company_name": name,
                    "company_domain": domain,
                    "career_page": career_page,
                    "job_title": title,
                    "department": department,
                    "location": location,
                    "employment_type": employment_type,
                    "apply_url": apply_url,
                    "source": "lever",
                    "ats": "Lever",
                    "logo_url": logo_url,
                })

            results["jobs"] += len(jobs_data)
            results["ok"] += 1

        except Exception as e:
            results["failed"] += 1

        time.sleep(rate_limit)

    log(f"Lever: {results['ok']} ok, {results['empty']} empty, {results['failed']} failed = {results['jobs']} jobs")
    return all_jobs

# ============================================================
# OUTPUT
# ============================================================
def write_json(jobs, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    log(f"Wrote {len(jobs)} jobs to {path} ({os.path.getsize(path) / 1024:.1f} KB)")

def write_csv(jobs, path):
    if not jobs:
        log("No jobs to write")
        return
    fieldnames = list(jobs[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)
    log(f"Wrote {len(jobs)} jobs to {path}")

def print_stats(jobs):
    log(f"Total: {len(jobs)} jobs")
    if not jobs:
        return
    by_source = Counter(j["source"] for j in jobs)
    by_type = Counter(j["employment_type"] for j in jobs)
    by_company = Counter(j["company_name"] for j in jobs)
    print()
    print(f"  {'Source':20s} {'Jobs':>6s}")
    for k, v in by_source.most_common():
        print(f"  {k:20s} {v:6d}")
    print(f"  {'Employment Type':20s} {'Jobs':>6s}")
    for k, v in by_type.most_common():
        print(f"  {k:20s} {v:6d}")
    print(f"  {'Company':25s} {'Jobs':>6s}")
    for k, v in by_company.most_common(10):
        print(f"  {k:25s} {v:6d}")
    if len(by_company) > 10:
        print(f"  ... and {len(by_company) - 10} more")

# ============================================================
# CLI
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Job scraper: fetch real job listings from Greenhouse & Lever APIs."
    )
    parser.add_argument("-o", "--output", default="job_listings.json",
                        help="Output file path (extension: .json or .csv)")
    parser.add_argument("--rate-limit", type=float, default=0.5,
                        help="Seconds between API requests (default: 0.5)")
    parser.add_argument("--companies", "-c",
                        help="Path to company list (JSON or CSV). Loads built-in 27 if not provided.")
    parser.add_argument("--source", choices=["greenhouse", "lever", "all"], default="all",
                        help="Which ATS to scrape (default: all)")
    parser.add_argument("--greenhouse-directory", action="store_true",
                        help="Fetch company list from Greenhouse directory before scraping")
    args = parser.parse_args()

    companies = []

    # 1. Load from file if provided
    if args.companies:
        ext = Path(args.companies).suffix.lower()
        if ext == ".csv":
            companies = load_companies_from_csv(args.companies)
        elif ext == ".json":
            companies = load_companies_from_json(args.companies)

    # 2. Append Greenhouse directory if requested
    if args.greenhouse_directory:
        companies.extend(fetch_greenhouse_directory())

    # 3. Fallback to built-in list
    if not companies:
        log("No company list loaded — using built-in 27-company list")
        companies = BUILT_IN_COMPANIES

    log(f"Total companies to scrape: {len(companies)}")

    all_jobs = []

    # Scrape Greenhouse
    if args.source in ("greenhouse", "all"):
        gh_companies = [c for c in companies if c.get("ats", "").lower() in ("", "greenhouse")]
        if not gh_companies:
            gh_companies = companies
        all_jobs.extend(scrape_greenhouse(gh_companies, args.rate_limit))

    # Scrape Lever
    if args.source in ("lever", "all"):
        lv_companies = [c for c in companies if c.get("ats", "").lower() == "lever"]
        if lv_companies:
            all_jobs.extend(scrape_lever(lv_companies, args.rate_limit))

    if not all_jobs:
        log("No jobs found. Check company list or source availability.")
        return

    # Output
    output_path = args.output
    if output_path.endswith(".csv"):
        write_csv(all_jobs, output_path)
    else:
        write_json(all_jobs, output_path)

    print_stats(all_jobs)

if __name__ == "__main__":
    main()
