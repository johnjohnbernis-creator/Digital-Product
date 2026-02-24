# ----------------------------------------------------------
# Digital Product Portfolio — SQLite Cloud Version
# Streamlit 1.12 compatible
# ----------------------------------------------------------

import io
import re
from contextlib import contextmanager
from datetime import datetime, date
from typing import List, Dict, Optional, Any
from urllib.parse import urlparse, parse_qs

import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st
import sqlitecloud

# ==========================================================
# OPTIONAL DEPENDENCIES
# ==========================================================
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

try:
    import kaleido  # noqa
    KALEIDO_AVAILABLE = True
except Exception:
    KALEIDO_AVAILABLE = False

# ==========================================================
# CONSTANTS
# ==========================================================
APP_TITLE = "Digital Product — Web Version"
APP_PAGE_TITLE = "Digital Product Portfolio"

TABLE = "features"
NEW_LABEL = "<New Feature>"
ALL_LABEL = "All"

PRESET_DIGITAL_PRODUCTS = [
    "Memphis Analytics",
    "Mooresville Analytics",
    "WPB Analytics",
    "Data Architecture",
    "Transportation Cost Analytics",
    "DCPM Analytics",
    "Customer Service Analytics",
    "Coppell Analytics",
    "Digital",
]

STATUS_LIST = ["Planned", "In Progress", "Completed", "On Hold"]

EXPECTED_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "name": "TEXT NOT NULL",
    "digital_product": "TEXT NOT NULL",
    "priority": "INTEGER DEFAULT 5",
    "description": "TEXT",
    "owner": "TEXT",
    "status": "TEXT",
    "start_date": "TEXT",
    "due_date": "TEXT",
    "planisware_feature": "TEXT DEFAULT 'No'",
    "planisware_number": "TEXT",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

EXPORT_COL_RENAME = {
    "digital_product": "Digital Product",
    "planisware_feature": "Planisware Feature",
    "planisware_number": "Planisware Number",
}

JJMD_PATTERN = re.compile(r"^JJMD-\d{7}$", re.IGNORECASE)

# ==========================================================
# HELPERS
# ==========================================================
def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def safe_index(opts, val, default=0):
    return opts.index(val) if val in opts else default

def safe_int(x, default=5):
    try:
        return int(x)
    except Exception:
        return default

def to_iso(d):
    return d.strftime("%Y-%m-%d") if d else None

def for_display(df):
    return df.rename(columns=EXPORT_COL_RENAME) if not df.empty else df

def validate_planisware(flag: str, number: Any) -> Optional[str]:
    if str(flag).lower() == "yes":
        if not number:
            raise ValueError("Planisware number required.")
        val = str(number).strip().upper()
        if not JJMD_PATTERN.fullmatch(val):
            raise ValueError("Format must be JJMD-#######")
        return val
    return None

# ==========================================================
# SQLITE CLOUD
# ==========================================================
def _get_sqlitecloud_url():
    url = (
        st.secrets.get("SQLITECLOUD_URL_PRODUCT")
        or st.secrets.get("SQLITECLOUD_URL")
        or ""
    ).strip()
    if not url:
        st.error("Missing SQLite Cloud secret.")
        st.stop()
    return url

@contextmanager
def conn():
    c = sqlitecloud.connect(_get_sqlitecloud_url())
    try:
        yield c
    finally:
        c.close()

def exec_sql(c, sql, params=None):
    sql = " ".join(sql.strip().split())
    return c.execute(sql, params) if params else c.execute(sql)

# ==========================================================
# APP BOOT
# ==========================================================
st.set_page_config(page_title=APP_PAGE_TITLE, layout="wide")
st.title(APP_TITLE)

with conn() as c:
    ddl = ", ".join([f'"{k}" {v}' for k, v in EXPECTED_COLUMNS.items()])
    exec_sql(c, f'CREATE TABLE IF NOT EXISTS "{TABLE}" ({ddl})')

# ==========================================================
# SESSION STATE
# ==========================================================
if "feature_selector" not in st.session_state:
    st.session_state.feature_selector = NEW_LABEL

# ==========================================================
# LOAD DATA
# ==========================================================
with conn() as c:
    df_all = pd.read_sql_query(f'SELECT * FROM "{TABLE}" ORDER BY id', c)

# ==========================================================
# OPTIONS
# ==========================================================
pillar_options = sorted(
    set(PRESET_DIGITAL_PRODUCTS) | set(df_all["digital_product"].dropna())
)
owner_options = sorted(df_all["owner"].dropna().unique().tolist())

# ==========================================================
# PROJECT / FEATURE EDITOR
# ==========================================================
st.markdown("---")
st.subheader("Project / Feature Editor")

feature_options = [NEW_LABEL] + [
    f"{r.id} — {r.name}" for r in df_all.itertuples()
]

selected = st.selectbox(
    "Select Feature",
    feature_options,
    index=safe_index(feature_options, st.session_state.feature_selector),
    key="feature_selector",
)

loaded = None
if selected != NEW_LABEL:
    fid = int(selected.split(" — ")[0])
    loaded = df_all[df_all["id"] == fid].iloc[0].to_dict()

with st.form("feature_form"):
    c1, c2 = st.columns(2)

    name = st.text_input("Name*", loaded["name"] if loaded else "")
    digital_product = st.selectbox(
        "Digital Product*",
        pillar_options,
        index=safe_index(pillar_options, loaded["digital_product"] if loaded else ""),
    )
    priority = st.number_input("Priority", 1, 99, safe_int(loaded["priority"]) if loaded else 5)
    description = st.text_area("Description", loaded["description"] if loaded else "")

    owner = st.selectbox(
        "Owner*",
        owner_options,
        index=safe_index(owner_options, loaded["owner"] if loaded else ""),
    )
    status = st.selectbox(
        "Status",
        STATUS_LIST,
        index=safe_index(STATUS_LIST, loaded["status"] if loaded else "Planned"),
    )

    start_date = st.date_input(
        "Start Date",
        pd.to_datetime(loaded["start_date"]) if loaded and loaded["start_date"] else None
    )
    due_date = st.date_input(
        "Due Date",
        pd.to_datetime(loaded["due_date"]) if loaded and loaded["due_date"] else None
    )

    planisware_feature = st.selectbox(
        "Planisware Feature",
        ["No", "Yes"],
        index=1 if loaded and loaded["planisware_feature"] == "Yes" else 0,
    )
    planisware_number = st.text_input(
        "Planisware Number", loaded["planisware_number"] if loaded else ""
    )

    b1, b2, b3 = st.columns(3)
    save_new = b1.form_submit_button("Save")
    update = b2.form_submit_button("Update")
    delete = b3.form_submit_button("Delete")

# ==========================================================
# CRUD
# ==========================================================
if save_new:
    pw = validate_planisware(planisware_feature, planisware_number)
    with conn() as c:
        exec_sql(
            c,
            f'''INSERT INTO "{TABLE}"
            (name,digital_product,priority,description,owner,status,
             start_date,due_date,planisware_feature,planisware_number,
             created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                name, digital_product, priority, description, owner, status,
                to_iso(start_date), to_iso(due_date),
                planisware_feature, pw, now_ts(), now_ts()
            ),
        )
    st.experimental_rerun()

if update and loaded:
    pw = validate_planisware(planisware_feature, planisware_number)
    with conn() as c:
        exec_sql(
            c,
            f'''UPDATE "{TABLE}" SET
            name=?, digital_product=?, priority=?, description=?, owner=?, status=?,
            start_date=?, due_date=?, planisware_feature=?, planisware_number=?, updated_at=?
            WHERE id=?''',
            (
                name, digital_product, priority, description, owner, status,
                to_iso(start_date), to_iso(due_date),
                planisware_feature, pw, now_ts(), loaded["id"]
            ),
        )
    st.experimental_rerun()

if delete and loaded:
    with conn() as c:
        exec_sql(c, f'DELETE FROM "{TABLE}" WHERE id=?', (loaded["id"],))
    st.experimental_rerun()

# ==========================================================
# KPI CARDS
# ==========================================================
st.markdown("---")
st.subheader("KPIs")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Features", len(df_all))
k2.metric("Completed", (df_all["status"] == "Completed").sum())
k3.metric("Ongoing", (df_all["status"] != "Completed").sum())
k4.metric("Digital Products", df_all["digital_product"].nunique())

# ==========================================================
# FEATURE TABLE
# ==========================================================
st.markdown("---")
st.subheader("Feature Table")
st.dataframe(for_display(df_all), use_container_width=True)

# ==========================================================
# ROADMAP
# ==========================================================
st.markdown("---")
st.subheader("Roadmap")

gantt = df_all.copy()
gantt["Start"] = pd.to_datetime(gantt["start_date"], errors="coerce")
gantt["Finish"] = pd.to_datetime(gantt["due_date"], errors="coerce")
gantt = gantt.dropna(subset=["Start", "Finish"])

if not gantt.empty:
    fig = px.timeline(
        gantt,
        x_start="Start",
        x_end="Finish",
        y="name",
        color="digital_product",
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No valid dates to render roadmap.")
