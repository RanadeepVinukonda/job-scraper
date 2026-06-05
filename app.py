import streamlit as st
import json, csv, io, re, time
from collections import Counter
import pandas as pd
import requests

st.set_page_config(page_title="Job Scraper", page_icon="📋", layout="wide")

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

def infer_employment_type(job_title, content=""):
    text = (job_title + " " + content[:2000]).lower()
    if re.search(r'\bintern\b|\binternship\b', text): return 'Internship'
    if re.search(r'\bcontract\b|\btemporary\b|\btemp\b', text): return 'Contract'
    if re.search(r'\bpart[-\s]?time\b', text): return 'Part-time'
    return 'Full-time'

def scrape_greenhouse(companies, rate_limit, progress_callback=None):
    all_jobs = []
    results = {"ok": 0, "empty": 0, "failed": 0}
    for i, company in enumerate(companies):
        board = company.get("board") or company.get("name", "").lower().replace(" ", "")
        name = company.get("name", board)
        domain = company.get("domain", "")
        if progress_callback:
            progress_callback(i, len(companies), name)
        try:
            resp = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
                timeout=15,
            )
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
            for job in jobs_data:
                departments = job.get("departments", [])
                all_jobs.append({
                    "company_name": job.get("company_name") or name,
                    "company_domain": domain,
                    "career_page": career_page,
                    "job_title": job.get("title", "Unknown"),
                    "department": departments[0]["name"] if departments else "General",
                    "location": job.get("location", {}).get("name", "Remote"),
                    "employment_type": infer_employment_type(job.get("title", ""), job.get("content", "")),
                    "apply_url": job.get("absolute_url", ""),
                    "source": "greenhouse",
                    "ats": "Greenhouse",
                    "logo_url": f"https://logo.clearbit.com/{domain}" if domain else "",
                })
            results["ok"] += 1
        except requests.exceptions.Timeout:
            results["failed"] += 1
        except Exception:
            results["failed"] += 1
        time.sleep(rate_limit)
    return all_jobs, results

def scrape_lever(companies, rate_limit, progress_callback=None):
    all_jobs = []
    results = {"ok": 0, "empty": 0, "failed": 0}
    for i, company in enumerate(companies):
        board = company.get("board") or company.get("name", "").lower().replace(" ", "")
        name = company.get("name", board)
        domain = company.get("domain", "")
        if progress_callback:
            progress_callback(i, len(companies), name)
        try:
            resp = requests.get(f"https://api.lever.co/v0/postings/{board}?mode=json", timeout=15)
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
            for job in jobs_data:
                cats = job.get("categories", {}) or {}
                commitment = cats.get("commitment", "")
                all_jobs.append({
                    "company_name": name,
                    "company_domain": domain,
                    "career_page": career_page,
                    "job_title": job.get("text", "Unknown"),
                    "department": cats.get("team", "General"),
                    "location": cats.get("location", "Remote"),
                    "employment_type": infer_employment_type(commitment) if commitment else "Full-time",
                    "apply_url": job.get("hostedUrl", ""),
                    "source": "lever",
                    "ats": "Lever",
                    "logo_url": f"https://logo.clearbit.com/{domain}" if domain else "",
                })
            results["ok"] += 1
        except Exception:
            results["failed"] += 1
        time.sleep(rate_limit)
    return all_jobs, results

def to_csv_string(jobs):
    if not jobs:
        return ""
    output = io.StringIO()
    fieldnames = list(jobs[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(jobs)
    return output.getvalue()

def parse_uploaded_companies(uploaded_file):
    content = uploaded_file.getvalue().decode("utf-8")
    companies = []
    if uploaded_file.name.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            companies.append({
                "name": row.get("name") or row.get("company_name", ""),
                "board": row.get("board") or row.get("ats_board", ""),
                "domain": row.get("domain") or row.get("company_domain", ""),
            })
    elif uploaded_file.name.endswith(".json"):
        data = json.loads(content)
        companies = data if isinstance(data, list) else data.get("companies", [])
    return companies

def fetch_greenhouse_directory():
    try:
        resp = requests.get("https://boards-api.greenhouse.io/v1/boards", timeout=15)
        if resp.status_code == 200:
            boards = resp.json().get("boards", [])
            return [{"name": b.get("name", ""), "board": b.get("slug", ""), "domain": ""} for b in boards]
    except Exception:
        pass
    return []

# --- UI ---
st.title("📋 Job Scraper")
st.markdown("Scrape real job listings from **Greenhouse** and **Lever** ATS APIs.")

with st.sidebar:
    st.header("⚙️ Config")
    company_source = st.radio(
        "Company list source",
        ["Built-in (27 companies)", "Upload CSV/JSON", "Fetch Greenhouse Directory"],
        index=0,
    )
    companies_to_scrape = []

    if company_source == "Built-in (27 companies)":
        companies_to_scrape = BUILT_IN_COMPANIES
        st.success(f"{len(companies_to_scrape)} companies loaded")
        with st.expander("Show companies"):
            for c in companies_to_scrape:
                st.write(f"- {c['name']}")

    elif company_source == "Upload CSV/JSON":
        uploaded = st.file_uploader(
            "Upload file", type=["csv", "json"],
            help="CSV columns: name,board,domain  |  JSON: array of objects",
        )
        if uploaded:
            companies_to_scrape = parse_uploaded_companies(uploaded)
            st.success(f"{len(companies_to_scrape)} companies loaded")
            with st.expander("Show companies"):
                for c in companies_to_scrape[:50]:
                    st.write(f"- {c.get('name', c.get('board', '?'))}")
                if len(companies_to_scrape) > 50:
                    st.write(f"... and {len(companies_to_scrape) - 50} more")

    elif company_source == "Fetch Greenhouse Directory":
        if st.button("📥 Fetch from Greenhouse"):
            with st.spinner("Fetching directory..."):
                gh_dir = fetch_greenhouse_directory()
            if gh_dir:
                st.success(f"{len(gh_dir)} companies found")
                st.session_state["gh_dir_companies"] = gh_dir
            else:
                st.error("Failed to fetch directory. The API may be unavailable.")
        companies_to_scrape = st.session_state.get("gh_dir_companies", [])

    source = st.selectbox("ATS to scrape", ["greenhouse", "lever", "all"], index=0)
    rate_limit = st.slider("Rate limit (seconds)", 0.1, 2.0, 0.3, 0.1)
    scrape_btn = st.button(
        "🚀 Start Scraping", type="primary", use_container_width=True,
        disabled=not companies_to_scrape,
    )

tab1, tab2, tab3 = st.tabs(["📊 Results", "📥 Download", "📖 Help"])

with tab3:
    st.markdown("""
### How to use

1. **Choose your company list** from the sidebar
   - *Built-in*: 27 well-known companies using Greenhouse
   - *Upload CSV/JSON*: Provide your own company list  
   - *Greenhouse Directory*: Fetch all companies listed on Greenhouse

2. **Select ATS source** to scrape
3. **Adjust rate limit** — be respectful to APIs (0.3–0.5s recommended)
4. **Click "Start Scraping"** and wait for results

### CSV company format
```csv
name,board,domain
Stripe,stripe,stripe.com
```

### JSON company format
```json
[{"name": "Stripe", "board": "stripe", "domain": "stripe.com"}]
```

### Output fields
| Field | Description |
|-------|-------------|
| company_name | Company name |
| company_domain | Domain (e.g. stripe.com) |
| career_page | Careers page URL |
| job_title | Job listing title |
| department | Department / team |
| location | Job location |
| employment_type | Full-time / Internship / Contract |
| apply_url | Direct application link |
| source | ATS name |
| logo_url | Clearbit logo URL |
""")

if scrape_btn and companies_to_scrape:
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    def progress(i, total, name):
        progress_bar.progress((i + 1) / total)
        status_text.text(f"🔄 {i+1}/{total} — {name}")

    all_jobs = []
    gh_results = {"ok": 0, "empty": 0, "failed": 0}
    lv_results = {"ok": 0, "empty": 0, "failed": 0}

    if source in ("greenhouse", "all"):
        with st.spinner("Scraping Greenhouse..."):
            gh_jobs, gh_results = scrape_greenhouse(companies_to_scrape, rate_limit, progress)
        all_jobs.extend(gh_jobs)

    if source in ("lever", "all"):
        lv_companies = [c for c in companies_to_scrape if c.get("ats", "").lower() == "lever"]
        if lv_companies:
            with st.spinner("Scraping Lever..."):
                lv_jobs, lv_results = scrape_lever(lv_companies, rate_limit, progress)
            all_jobs.extend(lv_jobs)

    progress_bar.empty()
    status_text.empty()

    for idx, job in enumerate(all_jobs, 1):
        job["id"] = idx

    if not all_jobs:
        st.error("No jobs found. Check your company list or try a different source.")
    else:
        st.session_state["scraped_jobs"] = all_jobs
        st.session_state["gh_results"] = gh_results
        st.session_state["lv_results"] = lv_results
        st.rerun()

if "scraped_jobs" in st.session_state and st.session_state["scraped_jobs"]:
    jobs = st.session_state["scraped_jobs"]
    gh = st.session_state["gh_results"]
    lv = st.session_state["lv_results"]

    with tab1:
        st.success(f"✅ Scraped **{len(jobs)}** job listings")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Jobs", len(jobs))
        col2.metric("Companies", len(set(j["company_name"] for j in jobs)))
        col3.metric("Greenhouse", f"{gh['ok']} OK / {gh['failed']} failed")
        col4.metric("Lever", f"{lv['ok']} OK / {lv['failed']} failed")

        st.subheader("Employment Type Breakdown")
        et_counts = Counter(j["employment_type"] for j in jobs)
        et_df = pd.DataFrame([{"Type": k, "Count": v} for k, v in et_counts.most_common()])
        col_a, col_b = st.columns([1, 2])
        col_a.dataframe(et_df, hide_index=True, use_container_width=True)
        col_b.bar_chart(et_df.set_index("Type"))

        st.subheader("Jobs by Company (top 25)")
        co_counts = Counter(j["company_name"] for j in jobs).most_common(25)
        co_df = pd.DataFrame([{"Company": k, "Jobs": v} for k, v in co_counts]).set_index("Company")
        st.bar_chart(co_df)

        st.subheader("Raw Data")
        st.dataframe(pd.DataFrame(jobs), hide_index=True, use_container_width=True)

    with tab2:
        st.subheader("Download Results")
        col_json, col_csv = st.columns(2)
        json_str = json.dumps(jobs, indent=2, ensure_ascii=False)
        csv_str = to_csv_string(jobs)
        col_json.download_button(
            label="📥 Download JSON", data=json_str,
            file_name="job_listings.json", mime="application/json",
            use_container_width=True,
        )
        col_csv.download_button(
            label="📥 Download CSV", data=csv_str,
            file_name="job_listings.csv", mime="text/csv",
            use_container_width=True,
        )
        st.subheader("Preview (first 10)")
        st.code(json.dumps(jobs[:10], indent=2), language="json")
