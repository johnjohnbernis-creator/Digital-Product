# ----------------------------------------------------------
# Digital Product Portfolio — SQLite Cloud Version
# Includes:
# ✅ Project (Feature) Editor
# ✅ KPI Cards
# ✅ Feature Table
# ✅ Roadmap (Gantt)
# ----------------------------------------------------------

import io
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Any

import pandas as pd
import plotly.express as px
import streamlit as st
import sqlitecloud

# ================== CONFIG ==================
APP_TITLE = "Digital Product — Web Version"
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

JJMD_PATTERN = re.compile(r"^JJMD-\d{7}$", re.IGNORECASE)

# ================== HELPERS ==================
def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def safe_index(options, value, default=0):
    return options.index(value) if value in options else default

def validate_planisware(flag: str, number: Any) -> Optional[str]:
    if str(flag).lower() == "yes":
        if not number:
            raise ValueError("Planisware number required.")
        value = str(number).upper().strip()
        if not JJMD_PATTERN.fullmatch(value):
            raise ValueError("Format must be JJMD-#######")
        return value
    return None

# ================== SQLITE CLOUD ==================
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

# ================== APP BOOT ==================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

# ================== LOAD DATA ==================
with conn() as c:
    df_all = pd.read_sql_query(f'SELECT * FROM "{TABLE}" ORDER BY id', c)

# ================== OPTIONS ==================
digital_products = sorted(
    set(PRESET_DIGITAL_PRODUCTS) | set(df_all["digital_product"].dropna())
)
owners = sorted(df_all["owner"].dropna().unique().tolist())

# ================== SESSION STATE ==================
if "feature_selector" not in st.session_state:
    st.session_state.feature_selector = NEW_LABEL

# ================== PROJECT EDITOR ==================
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
        digital_products,
        index=safe_index(digital_products, loaded["digital_product"] if loaded else ""),
    )
    priority = st.number_input(
        "Priority", 1, 99, loaded["priority"] if loaded else 5
    )
    description = st.text_area(
        "Description", loaded["description"] if loaded else ""
    )

    owner = st.selectbox(
        "Owner*",
        owners,
        index=safe_index(owners, loaded["owner"] if loaded else ""),
    )
    status = st.selectbox(
        "Status",
        STATUS_LIST,
        index=safe_index(STATUS_LIST, loaded["status"] if loaded else "Planned"),
    )

    start_date = st.date_input(
        "Start Date", pd.to_datetime(loaded["start_date"]) if loaded and loaded["start_date"] else None
    )
    due_date = st.date_input(
        "Due Date", pd.to_datetime(loaded["due_date"]) if loaded and loaded["due_date"] else None
    )

    planisware_feature = st.selectbox(
        "Planisware Feature", ["No", "Yes"],
        index=1 if loaded and loaded["planisware_feature"] == "Yes" else 0,
    )
    planisware_number = st.text_input(
        "Planisware Number", loaded["planisware_number"] if loaded else ""
    )

    b1, b2, b3 = st.columns(3)
    save_new = b1.form_submit_button("Save")
    update = b2.form_submit_button("Update")
    delete = b3.form_submit_button("Delete")

# ================== CRUD ==================
if save_new:
    pw = validate_planisware(planisware_feature, planisware_number)
    with conn() as c:
        c.execute(
            f'''INSERT INTO "{TABLE}"
            (name,digital_product,priority,description,owner,status,
             start_date,due_date,planisware_feature,planisware_number,
             created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                name, digital_product, priority, description, owner, status,
                str(start_date) if start_date else None,
                str(due_date) if due_date else None,
                planisware_feature, pw, now_ts(), now_ts()
            ),
        )
    st.success("Feature created")
    st.experimental_rerun()

if update and loaded:
    pw = validate_planisware(planisware_feature, planisware_number)
    with conn() as c:
        c.execute(
            f'''UPDATE "{TABLE}" SET
            name=?, digital_product=?, priority=?, description=?, owner=?, status=?,
            start_date=?, due_date=?, planisware_feature=?, planisware_number=?, updated_at=?
            WHERE id=?''',
            (
                name, digital_product, priority, description, owner, status,
                str(start_date) if start_date else None,
                str(due_date) if due_date else None,
                planisware_feature, pw, now_ts(), loaded["id"]
            ),
        )
    st.success("Feature updated")
    st.experimental_rerun()

if delete and loaded:
    with conn() as c:
        c.execute(f'DELETE FROM "{TABLE}" WHERE id=?', (loaded["id"],))
    st.warning("Feature deleted")
    st.experimental_rerun()

# ================== KPI CARDS ==================
st.markdown("---")
st.subheader("KPIs")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Features", len(df_all))
k2.metric("Completed", (df_all["status"] == "Completed").sum())
k3.metric("Ongoing", (df_all["status"] != "Completed").sum())
k4.metric("Digital Products", df_all["digital_product"].nunique())

# ================== FEATURE TABLE ==================
st.markdown("---")
st.subheader("Feature Table")
st.dataframe(df_all, use_container_width=True)

# ================== ROADMAP ==================
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
