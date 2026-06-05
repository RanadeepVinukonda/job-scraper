import streamlit as st
import json, csv, io, time
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import pandas as pd

st.set_page_config(page_title="Job Scraper", page_icon="📋", layout="wide")

DATA_DIR = Path("data")
JOBS_FILE = DATA_DIR / "job_listings.json"


def load_jobs():
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    return []


def to_csv_string(jobs):
    if not jobs:
        return ""
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(jobs[0].keys()))
    w.writeheader()
    w.writerows(jobs)
    return out.getvalue()


st.title("📋 Job Scraper")
st.markdown("Scrapes job listings from company career pages across **Greenhouse · Lever · Workday**. Data is updated hourly via GitHub Actions.")

jobs = load_jobs()

if not jobs:
    st.warning("No data yet. Run `python continuous_scraper.py` to generate data.")
    st.stop()

now = time.time()
mtime = JOBS_FILE.stat().st_mtime
elapsed = now - mtime
companies = sorted(set(j["company_name"] for j in jobs))
ats_counts = Counter(j.get("ats", "?") for j in jobs)

st.sidebar.markdown("### About")
st.sidebar.info(
    f"Multi-ATS scraper polling **{len(companies)} companies** "
    f"({ats_counts.get('Greenhouse', 0)} GH, "
    f"{ats_counts.get('Lever', 0)} Lever, "
    f"{ats_counts.get('Workday', 0)} Workday) on a schedule.\n"
    "New jobs detected by `apply_url` dedup.\n"
)

if elapsed < 7200:
    st.success(f"Updated {int(elapsed // 60)} min ago — {len(jobs)} jobs across {len(companies)} companies")
else:
    updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    st.info(f"{updated_at} — {len(jobs)} jobs across {len(companies)} companies")

col1, col2, col3 = st.columns(3)
col1.metric("Total jobs", len(jobs))
col2.metric("Companies", len(companies))
col3.metric("Last update", datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%b %d, %Y"))

t1, t2 = st.tabs(["Dashboard", "Download"])

with t1:
    gh_c = ats_counts.get("Greenhouse", 0)
    lv_c = ats_counts.get("Lever", 0)
    wd_c = ats_counts.get("Workday", 0)
    st.subheader("Jobs by ATS")
    st.bar_chart(pd.DataFrame([{"ATS": "Greenhouse", "Jobs": gh_c}, {"ATS": "Lever", "Jobs": lv_c}, {"ATS": "Workday", "Jobs": wd_c}]).set_index("ATS"))

    st.subheader("Employment Type")
    et = Counter(j["employment_type"] for j in jobs)
    df = pd.DataFrame([{"Type": k, "Count": v} for k, v in et.most_common()])
    ca, cb = st.columns([1, 2])
    ca.dataframe(df, hide_index=True, use_container_width=True)
    cb.bar_chart(df.set_index("Type"))

    st.subheader("Jobs by Company (top 15)")
    co = Counter(j["company_name"] for j in jobs).most_common(15)
    st.bar_chart(pd.DataFrame([{"Company": k, "Jobs": v} for k, v in co]).set_index("Company"))

    st.subheader(f"Jobs ({len(jobs)})")
    df_jobs = pd.DataFrame(jobs)
    if not df_jobs.empty:
        st.dataframe(
            df_jobs,
            column_config={
                "apply_url": st.column_config.LinkColumn("Apply URL"),
                "logo_url": st.column_config.LinkColumn("Logo URL"),
            },
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
