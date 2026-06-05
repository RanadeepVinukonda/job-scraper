"""
Continuous Job Scraper — multi-ATS support (Greenhouse, Lever, Workday).

Usage:
    python continuous_scraper.py           # Full run (all companies)
    python continuous_scraper.py --demo    # Demo run (6 companies, ~100-200 jobs)
    python continuous_scraper.py --demo --force-new   # Demo + treat all as new

Output:
    data/job_listings.json   — all discovered jobs
    data/seen_jobs.json      — dedup registry (apply_url -> timestamp)
"""

import json, time, re, os, sys, math
import logging
import urllib.parse

from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# Configure basic logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Global scrape statistics for validation reporting
SCRAPE_STATS = {
    "total_raw_jobs": 0,
    "invalid_apply_urls": 0,
    "valid_apply_urls": 0,
    "logo_primary": 0,
    "logo_fallback": 0,
    "logo_default": 0,
}

# -----------------------------------
# Helper utilities for URL normalization and logo handling
# -----------------------------------
DEFAULT_LOGO = "https://via.placeholder.com/100?text=No+Logo"

def is_valid_url(url: str) -> bool:
    """Basic validation that the URL has a proper scheme and netloc."""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False

def follow_redirects(url: str) -> str | None:
    """Return final URL after following redirects, or None on failure."""
    try:
        resp = requests.get(url, allow_redirects=True, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            return resp.url
        else:
            logger.warning(f"URL {url} returned status {resp.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Error fetching URL {url}: {e}")
        return None

def normalize_apply_url(raw_url: str, base_url: str | None = None) -> str | None:
    """Normalize and verify an apply URL.
    * Handles protocol‑relative URLs (//example.com)
    * Resolves relative URLs using base_url
    * Ensures a proper scheme
    * Follows redirects and returns the final destination
    Returns None if the URL is invalid or unreachable.
    """
    if not raw_url or not isinstance(raw_url, str):
        return None
    raw_url = raw_url.strip()
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    if base_url and raw_url.startswith("/"):
        raw_url = urllib.parse.urljoin(base_url, raw_url)
    # Ensure scheme present
    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.scheme:
        raw_url = "https://" + raw_url
        parsed = urllib.parse.urlparse(raw_url)
    if not is_valid_url(raw_url):
        logger.warning(f"Invalid URL format: {raw_url}")
        return None
    final = follow_redirects(raw_url)
    return final

def validate_image_url(url: str) -> bool:
    """Check that a URL returns a 200 response with an image content type."""
    try:
        head = requests.head(url, timeout=10, allow_redirects=True)
        ct = head.headers.get("Content-Type", "")
        return head.status_code == 200 and ct.startswith("image/")
    except Exception as e:
        logger.info(f"Error checking logo URL {url}: {e}")
        return False

def get_logo_url(domain: str) -> tuple[str, str]:
    """Return a reliable logo URL for the given domain.
    Returns a tuple (url, source) where source is 'primary', 'fallback' or 'default'.
    If LOGODEV_PUBLISHABLE_KEY and LOGODEV_SECRET_KEY environment variables are set,
    they are appended as query parameters to the primary logo.dev request.
    """
    if not domain:
        return DEFAULT_LOGO, "default"
    # Base img.logo.dev URL
    primary_base = f"https://img.logo.dev/{domain}"
    # Append auth keys if they exist in the environment (no hard‑coded secrets)
    pk = os.getenv("LOGODEV_PUBLISHABLE_KEY")
    sk = os.getenv("LOGODEV_SECRET_KEY")
    if pk and sk:
        primary = f"{primary_base}?pk={pk}&sk={sk}"
    else:
        primary = primary_base
    if validate_image_url(primary):
        return primary, "primary"
    # Fallback to Google favicon service
    fallback = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
    if validate_image_url(fallback):
        return fallback, "fallback"
    return DEFAULT_LOGO, "default"


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

SEEN_FILE = DATA_DIR / "seen_jobs.json"
JOBS_FILE = DATA_DIR / "job_listings.json"

# ── Company Database ──────────────────────────────────────────────

GREENHOUSE_COMPANIES = [
    {"name": "Stripe",       "board": "stripe",      "domain": "stripe.com"},
    {"name": "Airbnb",       "board": "airbnb",      "domain": "airbnb.com"},
    {"name": "Lyft",         "board": "lyft",        "domain": "lyft.com"},
    {"name": "Pinterest",    "board": "pinterest",   "domain": "pinterest.com"},
    {"name": "Datadog",      "board": "datadog",     "domain": "datadoghq.com"},
    {"name": "Vercel",       "board": "vercel",      "domain": "vercel.com"},
    {"name": "GitLab",       "board": "gitlab",      "domain": "gitlab.com"},
    {"name": "Reddit",       "board": "reddit",      "domain": "reddit.com"},
    {"name": "MongoDB",      "board": "mongodb",     "domain": "mongodb.com"},
    {"name": "Cloudflare",   "board": "cloudflare",  "domain": "cloudflare.com"},
    {"name": "Dropbox",      "board": "dropbox",     "domain": "dropbox.com"},
    {"name": "Instacart",    "board": "instacart",   "domain": "instacart.com"},
    {"name": "Asana",        "board": "asana",       "domain": "asana.com"},
    {"name": "Coinbase",     "board": "coinbase",    "domain": "coinbase.com"},
    {"name": "Doordash",     "board": "doordash",    "domain": "doordash.com"},
    {"name": "HubSpot",      "board": "hubspot",     "domain": "hubspot.com"},
    {"name": "Webflow",      "board": "webflow",     "domain": "webflow.com"},
    {"name": "Anthropic",    "board": "anthropic",   "domain": "anthropic.com"},
    {"name": "Intercom",     "board": "intercom",    "domain": "intercom.com"},
    {"name": "Okta",         "board": "okta",        "domain": "okta.com"},
    {"name": "Twilio",       "board": "twilio",      "domain": "twilio.com"},
    {"name": "Affirm",       "board": "affirm",      "domain": "affirm.com"},
    {"name": "Robinhood",    "board": "robinhood",   "domain": "robinhood.com"},
    {"name": "Brex",         "board": "brex",        "domain": "brex.com"},
    {"name": "Carta",        "board": "carta",       "domain": "carta.com"},
    {"name": "Figma",        "board": "figma",       "domain": "figma.com"},
    {"name": "Calendly",     "board": "calendly",    "domain": "calendly.com"},
    {"name": "Amplitude",    "board": "amplitude",   "domain": "amplitude.com"},
    {"name": "Descript",     "board": "descript",    "domain": "descript.com"},
    {"name": "GoDaddy",      "board": "godaddy",     "domain": "godaddy.com"},
]

LEVER_COMPANIES = [
    {"name": "Palantir",     "board": "palantir",    "domain": "palantir.com"},
    {"name": "Ro",           "board": "ro",          "domain": "ro.co"},
    {"name": "Outreach",     "board": "outreach",    "domain": "outreach.io"},
    {"name": "Toptal",       "board": "toptal",      "domain": "toptal.com"},
    {"name": "Neon",         "board": "neon",        "domain": "neon.tech"},
    {"name": "Employ",       "board": "employ",      "domain": "employ.com"},
    {"name": "LinkedIn",     "board": "linkedin",    "domain": "linkedin.com"},
]

WORKDAY_COMPANIES = [
    {"name": "NVIDIA",       "tenant": "nvidia",        "cluster": "wd5",  "site": "NVIDIAExternalCareerSite",           "domain": "nvidia.com"},
]

ALL_COMPANIES = (
    [{"ats": "greenhouse", **c} for c in GREENHOUSE_COMPANIES]
    + [{"ats": "lever", **c} for c in LEVER_COMPANIES]
    + [{"ats": "workday", **c} for c in WORKDAY_COMPANIES]
)

DEMO_COMPANIES = [
    {"ats": "greenhouse", "name": "Stripe",       "board": "stripe",      "domain": "stripe.com"},
    {"ats": "greenhouse", "name": "Figma",        "board": "figma",       "domain": "figma.com"},
    {"ats": "lever",      "name": "Palantir",     "board": "palantir",    "domain": "palantir.com"},
    {"ats": "lever",      "name": "Neon",         "board": "neon",        "domain": "neon.tech"},
    {"ats": "workday",    "name": "NVIDIA",       "tenant": "nvidia",     "cluster": "wd5", "site": "NVIDIAExternalCareerSite", "domain": "nvidia.com"},
]


def infer_employment_type(job_title, content=""):
    text = (job_title + " " + content[:2000]).lower()
    if re.search(r'\bintern\b|\binternship\b', text): return 'Internship'
    if re.search(r'\bcontract\b|\btemporary\b|\btemp\b', text): return 'Contract'
    if re.search(r'\bpart[-\s]?time\b', text): return 'Part-time'
    return 'Full-time'


# ── Greenhouse Scraper ────────────────────────────────────────────

def fetch_greenhouse(company):
    board = company["board"]
    name = company["name"]
    domain = company.get("domain", "")
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true&per_page=500"

    try:
        resp = requests.get(url, timeout=15)
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    jobs_data = resp.json().get("jobs", [])
    results = []
    career_page = f"https://{domain}/careers" if domain else ""
    # Resolve logo via reliable services
    logo_url, _ = get_logo_url(domain)

    for job in jobs_data:
        # Count raw job entry for stats
        SCRAPE_STATS["total_raw_jobs"] += 1
        departments = job.get("departments", [])
        gh_jid = job.get("id")
        # Build raw apply URL first, then normalize/validate it
        raw_apply = f"https://boards.greenhouse.io/{board}/jobs/{gh_jid}" if gh_jid else job.get("absolute_url", "")
        apply_url = normalize_apply_url(raw_apply, base_url=career_page)
        if not apply_url:
            SCRAPE_STATS["invalid_apply_urls"] += 1
            continue
        # Successful apply URL
        SCRAPE_STATS["valid_apply_urls"] += 1
        results.append({
            "company_name": job.get("company_name") or name,
            "company_domain": domain,
            "career_page": career_page,
            "job_title": job.get("title", "Unknown"),
            "department": departments[0]["name"] if departments else "General",
            "location": job.get("location", {}).get("name", "Remote"),
            "employment_type": infer_employment_type(job.get("title", ""), job.get("content", "")),
            "apply_url": apply_url,
            "source": "company_careers_page",
            "ats": "Greenhouse",
            "logo_url": logo_url,
        })
        # Increment logo source stats based on the source used for this company
        # (logo_url is already resolved via get_logo_url) – we infer source by pattern
        if logo_url.startswith("https://img.logo.dev"):
            SCRAPE_STATS["logo_primary"] += 1
        elif logo_url.startswith("https://www.google.com/s2/favicons"):
            SCRAPE_STATS["logo_fallback"] += 1
        else:
            SCRAPE_STATS["logo_default"] += 1

    return results


# ── Lever Scraper ─────────────────────────────────────────────────

def fetch_lever(company):
    board = company["board"]
    name = company["name"]
    domain = company.get("domain", "")
    url = f"https://api.lever.co/v0/postings/{board}?mode=json"

    try:
        resp = requests.get(url, timeout=15)
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    try:
        postings = resp.json()
    except Exception:
        return []

    if not isinstance(postings, list):
        return []

    results = []
    career_page = f"https://{domain}/careers" if domain else ""
    # Resolve logo via reliable services, capture source
    logo_url, logo_source = get_logo_url(domain)

    for posting in postings:
        # Count raw posting for stats
        SCRAPE_STATS["total_raw_jobs"] += 1
        categories = posting.get("categories", {}) or {}
        # Normalize apply URL
        raw_apply = posting.get("hostedUrl", "")
        apply_url = normalize_apply_url(raw_apply, base_url=career_page)
        if not apply_url:
            SCRAPE_STATS["invalid_apply_urls"] += 1
            continue
        # Successful apply URL
        SCRAPE_STATS["valid_apply_urls"] += 1
        results.append({
            "company_name": name,
            "company_domain": domain,
            "career_page": career_page,
            "job_title": posting.get("text", "Unknown"),
            "department": categories.get("team", "General"),
            "location": categories.get("location", "Remote"),
            "employment_type": infer_employment_type(posting.get("text", ""), categories.get("commitment", "")),
            "apply_url": apply_url,
            "source": "company_careers_page",
            "ats": "Lever",
            "logo_url": logo_url,
        })
        # Increment logo source stats based on the source used for this company
        if logo_source == "primary":
            SCRAPE_STATS["logo_primary"] += 1
        elif logo_source == "fallback":
            SCRAPE_STATS["logo_fallback"] += 1
        else:
            SCRAPE_STATS["logo_default"] += 1

    return results


# ── Workday Scraper ───────────────────────────────────────────────

WORKDAY_TIMEOUT = 5
WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX_PAGES = 50

def _wd_api_url(company):
    return (f"https://{company['tenant']}.{company['cluster']}.myworkdayjobs.com"
            f"/wday/cxs/{company['tenant']}/{company['site']}/jobs")

def _wd_apply_url(company, ext_path):
    base = f"https://{company['tenant']}.{company['cluster']}.myworkdayjobs.com"
    if ext_path.startswith("/"):
        return f"{base}/en-US/{company['site']}{ext_path}"
    return f"{base}/en-US/{company['site']}/job/{ext_path}"

def _wd_extract_department(bullet_fields):
    for field in bullet_fields:
        if not re.match(r'^(JR|R|WD|REQ)\d+', field, re.IGNORECASE):
            return field
    return "General"

def fetch_workday(company):
    name = company["name"]
    domain = company.get("domain", "")
    api_url = _wd_api_url(company)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    career_page = f"https://{domain}/careers" if domain else ""
    # Resolve logo via reliable services, capture source
    logo_url, logo_source = get_logo_url(domain)

    try:
        resp = requests.post(api_url, json={"limit": WORKDAY_PAGE_SIZE, "offset": 0, "searchText": "", "appliedFacets": {}}, headers=headers, timeout=WORKDAY_TIMEOUT)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception as e:
        return []

    total = data.get("total", 0)
    if total == 0:
        return []

    all_postings = list(data.get("jobPostings", []))
    pages = min(math.ceil(total / WORKDAY_PAGE_SIZE), WORKDAY_MAX_PAGES)

    for page in range(1, pages):
        try:
            resp = requests.post(api_url, json={"limit": WORKDAY_PAGE_SIZE, "offset": page * WORKDAY_PAGE_SIZE, "searchText": "", "appliedFacets": {}}, headers=headers, timeout=WORKDAY_TIMEOUT)
            if resp.status_code == 200:
                more = resp.json().get("jobPostings", [])
                all_postings.extend(more)
        except Exception:
            pass
        if page % 5 == 0:
            done = min((page + 1) * WORKDAY_PAGE_SIZE, total)
            print(f"     ... {done}/{total} jobs fetched")

    results = []
    for posting in all_postings:
        # Count raw posting for stats
        SCRAPE_STATS["total_raw_jobs"] += 1
        ext_path = posting.get("externalPath", "")
        bullet = posting.get("bulletFields", []) or []
        department = _wd_extract_department(bullet)

        # Resolve apply URL for Workday postings
        raw_apply = _wd_apply_url(company, ext_path) if ext_path else ""
        apply_url = normalize_apply_url(raw_apply, base_url=career_page)
        if not apply_url:
            SCRAPE_STATS["invalid_apply_urls"] += 1
            continue
        SCRAPE_STATS["valid_apply_urls"] += 1
        results.append({
            "company_name": name,
            "company_domain": domain,
            "career_page": career_page,
            "job_title": posting.get("title", "Unknown"),
            "department": department,
            "location": posting.get("locationsText", "Remote"),
            "employment_type": infer_employment_type(posting.get("title", ""), " ".join(bullet)),
            "apply_url": apply_url,
            "source": "company_careers_page",
            "ats": "Workday",
            "logo_url": logo_url,
        })
        # Increment logo source stats based on the source used for this company
        if logo_source == "primary":
            SCRAPE_STATS["logo_primary"] += 1
        elif logo_source == "fallback":
            SCRAPE_STATS["logo_fallback"] += 1
        else:
            SCRAPE_STATS["logo_default"] += 1

    return results


# ── Dispatcher ────────────────────────────────────────────────────

ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "workday": fetch_workday,
}


def fetch_company_jobs(company):
    ats = company.get("ats", "greenhouse")
    fetcher = ATS_FETCHERS.get(ats)
    if not fetcher:
        return []
    return fetcher(company)


# ── State Management ──────────────────────────────────────────────

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


OUTPUT_FIELDS = [
    "id", "company_name", "company_domain", "career_page", "job_title",
    "department", "location", "employment_type", "apply_url",
    "source", "ats", "logo_url",
]


def save_jobs(jobs):
    cleaned = []
    for idx, job in enumerate(jobs, 1):
        job["id"] = idx
        entry = {k: job.get(k, "") for k in OUTPUT_FIELDS}
        cleaned.append(entry)
    JOBS_FILE.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")


def verify_url(url):
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True)
        return resp.status_code == 200
    except:
        return False


# ── Main Run ──────────────────────────────────────────────────────

def run(companies, force_new=False):
    seen = load_seen()
    existing = load_jobs()

    all_new = []
    all_current_urls = set()

    key = lambda c: c["name"].lower()

    print(f"scraping {len(companies)} companies...\n")

    with ThreadPoolExecutor(max_workers=10) as pool:
        fut_map = {pool.submit(fetch_company_jobs, c): c for c in companies}

        for i, fut in enumerate(as_completed(fut_map), 1):
            company = fut_map[fut]
            jobs = fut.result()
            print(f"  [{i}/{len(companies)}] {company['name']:20s} {company.get('ats','?'):12s} {len(jobs):4d} jobs", end="")

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

            is_first = key(company) not in seen.get("companies_seen", [])
            if is_first and not force_new:
                seen.setdefault("companies_seen", []).append(key(company))
                print(f"  (first scrape - archived)")
            elif new_count > 0:
                print(f"  ({new_count} new)")
            else:
                print()

    existing.extend(all_new)

    for job in existing:
        job["is_active"] = job["apply_url"] in all_current_urls

    save_jobs(existing)
    save_seen(seen)

    print(f"\nDone! {len(all_new)} new jobs, {len(existing)} total\n")
    # Write validation report for URL and logo integrity
    report = {
        "jobs_scraped": len(existing),
        "valid_apply_urls": SCRAPE_STATS["valid_apply_urls"],
        "invalid_apply_urls": SCRAPE_STATS["invalid_apply_urls"],
        "valid_logos_primary": SCRAPE_STATS["logo_primary"],
        "valid_logos_fallback": SCRAPE_STATS["logo_fallback"],
        "valid_logos_default": SCRAPE_STATS["logo_default"],
    }
    report_path = DATA_DIR / "validation_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Validation report written to {report_path}")

    return existing


if __name__ == "__main__":
    is_demo = "--demo" in sys.argv
    force_new = "--force-new" in sys.argv

    if is_demo:
        print("=== DEMO MODE ===\n")
        companies = DEMO_COMPANIES
    else:
        companies = ALL_COMPANIES

    jobs = run(companies, force_new=force_new)

    active = [j for j in jobs if j.get("is_active", True)]
    gh = [j for j in active if j.get("ats") == "Greenhouse"]
    lv = [j for j in active if j.get("ats") == "Lever"]
    wd = [j for j in active if j.get("ats") == "Workday"]
    print(f"Active jobs: {len(active)} (GH: {len(gh)}, Lever: {len(lv)}, Workday: {len(wd)})")
    print(f"Output: {JOBS_FILE}")
