# ----------------------------------------------------------
# Digital Product Portfolio — SAFE Runtime Fix
# ✅ No schema rebuild
# ✅ No DROP TABLE
# ✅ Uses existing data
# ✅ SQLite Cloud compatible
# ----------------------------------------------------------

import io
import re
from contextlib import contextmanager
from datetime import datetime, date
from typing import Optional, Any, List

import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st
import sqlitecloud

# ------------------ App Identity ------------------
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

EXPORT_COL_RENAME = {
    "digital_product": "Digital Product",
    "planisware_feature": "Planisware Feature",
    "planisware_number": "Planisware Number",
}

JJMD_PATTERN = re.compile(r"^JJMD-\d{7}$", re.IGNORECASE)

# ------------------ Helpers ------------------
def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _clean(x):
    return (x or "").strip()

def safe_index(opts, val, default=0):
    return opts.index(val) if val in opts else default

def safe_int(x, default=5):
    try:
        return int(x)
    except Exception:
        return default

def to_iso(d):
    return d.strftime("%Y-%m-%d") if d else ""

def for_display(df):
    return df.rename(columns=EXPORT_COL_RENAME) if not df.empty else df

def for_export_csv(df):
    return for_display(df).to_csv(index=False).encode("utf-8")

def status_to_state(s):
    return "Completed" if str(s).lower() == "completed" else "Ongoing"

def validate_planisware(flag: str, number: Any) -> Optional[str]:
    if str(flag).lower() == "yes":
        if not number:
            raise ValueError("Planisware Feature Number required.")
        val = str(number).strip().upper()
        if not JJMD_PATTERN.fullmatch(val):
            raise ValueError("Format must be JJMD-#######")
        return val
    return None

# ------------------ SQLite Cloud (SAFE) ------------------
def _get_url():
    url = (
        st.secrets.get("SQLITECLOUD_URL_PRODUCT")
        or st.secrets.get("SQLITECLOUD_URL")
        or ""
    ).strip()

    if not url:
        st.error(
            "Missing SQLite Cloud secret. "
            "Set SQLITECLOUD_URL_PRODUCT or SQLITECLOUD_URL."
        )
        st.stop()

    return url

@contextmanager
def conn():
    c = sqlitecloud.connect(_get_url())
    try:
        yield c
    finally:
        c.close()

def exec_sql(c, sql, params=None):
    sql = " ".join(sql.strip().split())
    return c.execute(sql, params) if params else c.execute(sql)

# ------------------ App Boot ------------------
st.set_page_config(page_title=APP_PAGE_TITLE, layout="wide")
st.title(APP_TITLE)

# ------------------ Session State ------------------
if "feature_selector" not in st.session_state:
    st.session_state.feature_selector = NEW_LABEL

# ------------------ Load Existing Data (NO CHANGES) ------------------
with conn() as c:
    df_all = pd.read_sql_query(f'SELECT * FROM "{TABLE}"', c)

# ------------------ Feature Selector ------------------
feature_options = [NEW_LABEL] + [
    f"{r.id} — {r.name}" for r in df_all[["id", "name"]].sort_values("name").itertuples()
]

selected_feature = st.selectbox(
    "Select Feature to Edit",
    feature_options,
    index=safe_index(feature_options, st.session_state.feature_selector),
    key="feature_selector",
)

loaded_feature = None
if selected_feature != NEW_LABEL:
    fid = int(selected_feature.split(" — ")[0])
    row = df_all[df_all["id"] == fid]
    if not row.empty:
        loaded_feature = row.iloc[0].to_dict()

# ------------------ Options ------------------
pillar_options = sorted(
    set(PRESET_DIGITAL_PRODUCTS) | set(df_all["digital_product"].dropna())
)
owner_options = [""] + sorted(df_all["owner"].dropna().unique().tolist())

# ------------------ Feature Editor ------------------
st.markdown("---")
st.subheader("Feature Editor")

with st.form("feature_form"):
    c1, c2 = st.columns(2)

    name = st.text_input("Name*", loaded_feature["name"] if loaded_feature else "")
    digital_product = st.selectbox(
        "Digital Product*",
        pillar_options,
        index=safe_index(
            pillar_options,
            loaded_feature["digital_product"] if loaded_feature else "",
        ),
    )
    priority = st.number_input(
        "Priority", 1, 99,
        safe_int(loaded_feature["priority"]) if loaded_feature else 5
    )
    description = st.text_area(
        "Description", loaded_feature["description"] if loaded_feature else ""
    )

    owner = st.selectbox(
        "Owner*",
        owner_options,
        index=safe_index(
            owner_options,
            loaded_feature["owner"] if loaded_feature else "",
        ),
    )
    status = st.selectbox(
        "Status",
        STATUS_LIST,
        index=safe_index(
            STATUS_LIST,
            loaded_feature["status"] if loaded_feature else "Planned",
        ),
    )

    planisware_feature = st.selectbox(
        "Planisware Feature",
        ["No", "Yes"],
        index=safe_index(
            ["No", "Yes"],
            loaded_feature["planisware_feature"] if loaded_feature else "No",
        ),
    )
    planisware_number = st.text_input(
        "Planisware Number",
        loaded_feature["planisware_number"] if loaded_feature else "",
    )

    b1, b2, b3 = st.columns(3)
    save_new = b1.form_submit_button("Save Feature")
    update = b2.form_submit_button("Update Feature")
    delete = b3.form_submit_button("Delete Feature")

# ------------------ CRUD (SAFE) ------------------
if save_new:
    errors = []
    if not name:
        errors.append("Name required")
    if not digital_product:
        errors.append("Digital Product required")
    if not owner:
        errors.append("Owner required")

    try:
        pw = validate_planisware(planisware_feature, planisware_number)
    except Exception as e:
        errors.append(str(e))

    if errors:
        st.error(" • ".join(errors))
    else:
        ts = now_ts()
        with conn() as c:
            exec_sql(
                c,
                f'''INSERT INTO "{TABLE}"
                (name,digital_product,priority,description,owner,status,
                 planisware_feature,planisware_number,created_at,updated_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (
                    name, digital_product, priority, description,
                    owner, status, planisware_feature, pw, ts, ts
                ),
            )
        st.success("✅ Feature created")
        st.session_state.feature_selector = NEW_LABEL
        st.experimental_rerun()

if update and loaded_feature:
    ts = now_ts()
    with conn() as c:
        exec_sql(
            c,
            f'''UPDATE "{TABLE}" SET
            name=?, digital_product=?, priority=?, description=?,
            owner=?, status=?, planisware_feature=?, planisware_number=?, updated_at=?
            WHERE id=?''',
            (
                name, digital_product, priority, description,
                owner, status, planisware_feature, planisware_number,
                ts, loaded_feature["id"]
            ),
        )
    st.success("✅ Feature updated")
    st.experimental_rerun()

if delete and loaded_feature:
    with conn() as c:
        exec_sql(
            c,
            f'DELETE FROM "{TABLE}" WHERE id=?',
            (loaded_feature["id"],),
        )
    st.warning("🗑️ Feature deleted")
    st.session_state.feature_selector = NEW_LABEL
    st.experimental_rerun()

# ------------------ KPIs ------------------
st.markdown("---")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Features", len(df_all))
k2.metric("Completed", (df_all["status"] == "Completed").sum())
k3.metric("Ongoing", (df_all["status"] != "Completed").sum())
k4.metric("Digital Products", df_all["digital_product"].nunique())

# ------------------ Chart ------------------
if not df_all.empty:
    chart_df = (
        df_all.assign(state=df_all["status"].apply(status_to_state))
        .groupby(["digital_product", "state"])
        .size()
        .reset_index(name="count")
    )
    fig = px.bar(
        chart_df,
        x="digital_product",
        y="count",
        color="state",
        title="Features by Digital Product"
    )
    st.plotly_chart(fig, use_container_width=True)

# ------------------ Roadmap ------------------
st.markdown("---")
st.subheader("Roadmap")

gantt = df_all.copy()
gantt["Start"] = pd.to_datetime(gantt["start_date"], errors="coerce")
gantt["Finish"] = pd.to_datetime(gantt["due_date"], errors="coerce")
gantt = gantt.dropna(subset=["Start", "Finish"])

if not gantt.empty:
    road_fig = px.timeline(
        gantt,
        x_start="Start",
        x_end="Finish",
        y="name",
        color="digital_product",
    )
    road_fig.update_yaxes(autorange="reversed")
    st.plotly_chart(road_fig, use_container_width=True)

# ------------------ Table ------------------
st.markdown("---")
st.subheader("All Features")
st.dataframe(for_display(df_all), use_container_width=True)

# ------------------ Export ------------------
st.markdown("---")
st.subheader("Export")

st.download_button(
    "⬇️ Download CSV",
    data=for_export_csv(df_all),
    file_name="digital_product_portfolio.csv",
    mime="text/csv",
)
