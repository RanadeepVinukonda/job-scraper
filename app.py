import streamlit as st
import json, csv, io
from pathlib import Path
from collections import Counter
import pandas as pd
from continuous_scraper import COMPANIES, DEMO_COMPANIES, run, load_jobs

st.set_page_config(page_title="Job Scraper", page_icon="📋", layout="wide")

JOBS_FILE = Path("data") / "job_listings.json"

def to_csv_string(jobs):
    if not jobs: return ""
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(jobs[0].keys()))
    w.writeheader(); w.writerows(jobs)
    return out.getvalue()

# ── UI ───────────────────────────────────────────────────────────────

st.title("📋 Job Scraper")
st.markdown("Scrapes job listings from company career pages. Data is updated every 6 hours via GitHub Actions.")

st.sidebar.markdown("### About")
st.sidebar.info(
    "This scraper polls **27 companies** on a schedule.\n"
    "New jobs are detected by comparing `apply_url` against a registry.\n"
    "Removed jobs are marked inactive (not deleted)."
)

jobs = load_jobs()

if not jobs:
    st.warning("No data yet. Run `python continuous_scraper.py --demo` to generate sample data.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Run demo scrape (3 companies)"):
            with st.spinner("Scraping..."):
                run(DEMO_COMPANIES, force_new=True)
                st.rerun()
    with col2:
        if st.button("🚀 Run full scrape (all 27)"):
            with st.spinner("Scraping..."):
                run(COMPANIES, force_new=True)
                st.rerun()
    st.stop()

active = [j for j in jobs if j.get("is_active", True)]
inactive = [j for j in jobs if not j.get("is_active", True)]

st.success(f"✅ **{len(active)} active jobs** across {len(set(j['company_name'] for j in active))} companies")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Active", len(active))
col2.metric("Inactive (removed)", len(inactive))
col3.metric("Companies", len(set(j["company_name"] for j in active)))
col4.metric("Last update", jobs[0].get("discovered_at","—")[:10] if jobs else "—")

t1, t2 = st.tabs(["📊 Dashboard", "📥 Download"])

with t1:
    st.subheader("Employment Type")
    et = Counter(j["employment_type"] for j in active)
    df = pd.DataFrame([{"Type":k,"Count":v} for k,v in et.most_common()])
    ca, cb = st.columns([1,2])
    ca.dataframe(df, hide_index=True, use_container_width=True)
    cb.bar_chart(df.set_index("Type"))

    st.subheader("Jobs by Company (top 15)")
    co = Counter(j["company_name"] for j in active).most_common(15)
    st.bar_chart(pd.DataFrame([{"Company":k,"Jobs":v} for k,v in co]).set_index("Company"))

    st.subheader("All Jobs")
    st.dataframe(pd.DataFrame(active), hide_index=True, use_container_width=True)

with t2:
    col_j, col_c = st.columns(2)
    col_j.download_button("📥 Download JSON", json.dumps(active, indent=2, ensure_ascii=False),
                          "job_listings.json", "application/json", use_container_width=True)
    col_c.download_button("📥 Download CSV", to_csv_string(active),
                          "job_listings.csv", "text/csv", use_container_width=True)
    st.subheader("Preview (first 10)")
    st.code(json.dumps(active[:10], indent=2), language="json")
