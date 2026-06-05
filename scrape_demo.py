import requests
import json
import time
import re

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
    {"name": "Coinbase",     "board": "coinbase",    "domain": "coinbase.com"},
    {"name": "HubSpot",      "board": "hubspot",     "domain": "hubspot.com"},
    {"name": "Grammarly",    "board": "grammarly",   "domain": "grammarly.com"},
]

def clean_html(html_text):
    text = re.sub(r'<[^>]+>', '', html_text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&#39;', "'")
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:500]

def extract_employment_type(content, title):
    text = (title + " " + content[:2000]).lower()
    if re.search(r'\bintern\b|\binternship\b', text):
        return 'Internship'
    if re.search(r'\bcontract\b|\btemporary\b|\btemp\b', text):
        return 'Contract'
    if re.search(r'\bpart[-\s]?time\b', text):
        return 'Part-time'
    return 'Full-time'

all_jobs = []
job_id = 1

for company in COMPANIES:
    board = company["board"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    print(f"Fetching {company['name']} ({board})...", end=" ")

    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code} - skipped")
            time.sleep(0.5)
            continue

        data = resp.json()
        jobs = data.get("jobs", [])
        if not jobs:
            print("0 jobs - skipped")
            time.sleep(0.5)
            continue

        print(f"{len(jobs)} jobs")

        for job in jobs:
            title = job.get("title", "Unknown")
            location = job.get("location", {}).get("name", "Remote")
            departments = job.get("departments", [])
            department = departments[0]["name"] if departments else "General"
            apply_url = job.get("absolute_url", f"https://boards.greenhouse.io/{board}/jobs/{job.get('id')}")
            content = job.get("content", "")
            employment_type = extract_employment_type(content, title)
            career_page = f"https://{company['domain']}/careers" if company['domain'] else ""

            all_jobs.append({
                "id": job_id,
                "company_name": company["name"],
                "company_domain": company["domain"],
                "career_page": career_page,
                "job_title": title,
                "department": department,
                "location": location,
                "employment_type": employment_type,
                "apply_url": apply_url,
                "source": "greenhouse",
                "ats": "Greenhouse",
                "logo_url": f"https://logo.clearbit.com/{company['domain']}"
            })
            job_id += 1

    except Exception as e:
        print(f"Error: {e}")

    time.sleep(0.5)

output_path = "demo_job_listings.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(all_jobs, f, indent=2, ensure_ascii=False)

print(f"\nDone! Scraped {len(all_jobs)} jobs from {len([c for c in COMPANIES if any(j['company_name']==c['name'] for j in all_jobs)])} companies")
print(f"Output: {output_path}")
