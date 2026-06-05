import streamlit as st
import json, csv, io, time
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import pandas as pd
from continuous_scraper import ALL_COMPANIES, DEMO_COMPANIES, run, load_jobs

st.set_page_config(page_title="Job Scraper", page_icon="📋", layout="wide")

JOBS_FILE = Path("data") / "job_listings.json"

ALL_COMPANIES_FLAT = ALL_COMPANIES


def to_csv_string(jobs):
    if not jobs: return ""
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(jobs[0].keys()))
    w.writeheader(); w.writerows(jobs)
    return out.getvalue()


st.title("📋 Job Scraper")
st.markdown("Scrapes job listings from company career pages across **Greenhouse · Lever · Workday**. Data is updated hourly via GitHub Actions.")

st.sidebar.markdown("### About")
st.sidebar.info(
    f"Multi-ATS scraper polling **{len(ALL_COMPANIES_FLAT)} companies** "
    f"({sum(1 for c in ALL_COMPANIES_FLAT if c['ats']=='greenhouse')} GH, "
    f"{sum(1 for c in ALL_COMPANIES_FLAT if c['ats']=='lever')} Lever, "
    f"{sum(1 for c in ALL_COMPANIES_FLAT if c['ats']=='workday')} Workday) on a schedule.\n"
    "New jobs detected by `apply_url` dedup.\n"
)

jobs = load_jobs()

if not jobs:
    st.warning("No data yet. Run `python continuous_scraper.py --demo` to generate sample data.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Run demo scrape (6 companies, 3 ATS)"):
            with st.spinner("Scraping..."):
                run(DEMO_COMPANIES, force_new=True)
                st.rerun()
    with col2:
        if st.button("Run full scrape (all companies)"):
            with st.spinner("Scraping..."):
                run(ALL_COMPANIES_FLAT, force_new=True)
                st.rerun()
    st.stop()

now = time.time()
mtime = JOBS_FILE.stat().st_mtime
elapsed = now - mtime
companies_count = len(set(j["company_name"] for j in jobs))
ats_counts = Counter(j.get("ats","?") for j in jobs)
if elapsed < 7200:
    st.success(f"Updated {int(elapsed // 60)} min ago — {len(jobs)} jobs across {companies_count} companies")
else:
    updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    st.info(f"{updated_at} — {len(jobs)} jobs across {companies_count} companies")

col1, col2, col3 = st.columns(3)
col1.metric("Total jobs", len(jobs))
col2.metric("Companies", companies_count)
col3.metric("Last update", datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%b %d, %Y"))

t1, t2 = st.tabs(["Dashboard", "Download"])

with t1:
    gh_c, lv_c, wd_c = ats_counts.get("Greenhouse",0), ats_counts.get("Lever",0), ats_counts.get("Workday",0)
    st.subheader("Jobs by ATS")
    st.bar_chart(pd.DataFrame([{"ATS":"Greenhouse","Jobs":gh_c},{"ATS":"Lever","Jobs":lv_c},{"ATS":"Workday","Jobs":wd_c}]).set_index("ATS"))

    st.subheader("Employment Type")
    et = Counter(j["employment_type"] for j in jobs)
    df = pd.DataFrame([{"Type":k,"Count":v} for k,v in et.most_common()])
    ca, cb = st.columns([1,2])
    ca.dataframe(df, hide_index=True, use_container_width=True)
    cb.bar_chart(df.set_index("Type"))

    st.subheader("Jobs by Company (top 15)")
    co = Counter(j["company_name"] for j in jobs).most_common(15)
    st.bar_chart(pd.DataFrame([{"Company":k,"Jobs":v} for k,v in co]).set_index("Company"))

    st.subheader(f"Jobs ({len(jobs)})")
    df_jobs = pd.DataFrame(jobs)
    if not df_jobs.empty:
        st.dataframe(
            df_jobs,
            column_config={"apply_url": st.column_config.LinkColumn("Apply URL")},
            hide_index=True, use_container_width=True,
        )

with t2:
    count = st.number_input("Number of jobs to download", min_value=1, max_value=len(jobs), value=len(jobs))
    subset = jobs[:count]
    col_j, col_c = st.columns(2)
    col_j.download_button("Download JSON", json.dumps(subset, indent=2, ensure_ascii=False),
                          "job_listings.json", "application/json", use_container_width=True)
    col_c.download_button("Download CSV", to_csv_string(subset),
                          "job_listings.csv", "text/csv", use_container_width=True)
    st.subheader("Preview (first 10)")
    st.code(json.dumps(jobs[:10], indent=2), language="json")
