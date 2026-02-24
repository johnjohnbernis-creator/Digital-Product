# ----------------------------------------------------------
# Digital Product Portfolio — SQLite Cloud Version
# Streamlit 1.12 compatible (uses experimental_rerun, no toast)
# ✅ Uses SQLite Cloud (persistent)
# ✅ Robust schema migration (cleans leftover temp tables)
# ✅ Exports show "Digital Product" column name (friendly)
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
import sqlitecloud  # SQLite Cloud Python SDK

# ------------------ Optional dependencies ------------------
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

try:
    import kaleido  # noqa: F401
    KALEIDO_AVAILABLE = True
except Exception:
    KALEIDO_AVAILABLE = False

# ------------------ Planisware/JJMD validation ------------------
JJMD_PATTERN = re.compile(r"^JJMD-\d{7}$", re.IGNORECASE)

def validate_planisware(planisware_feature: str, planisware_number: Any) -> Optional[str]:
    """
    If Planisware Feature is Yes, require a JJMD-####### value.
    """
    if str(planisware_feature).strip().lower() == "yes":
        if planisware_number is None or not str(planisware_number).strip():
            raise ValueError("Planisware Feature Number must be entered when Planisware Feature is Yes.")
        value = str(planisware_number).strip().upper()
        if not JJMD_PATTERN.fullmatch(value):
            raise ValueError("Planisware Feature Number must be in the format JJMD-0079575 (JJMD- + 7 digits).")
        return value
    return None

# ------------------ App Identity ------------------
APP_TITLE = "Digital Product — Web Version"
APP_PAGE_TITLE = "Digital Product Portfolio"

TABLE = "features"
NEW_LABEL = "<New Feature>"
ALL_LABEL = "All"

# ✅ Digital Products (formerly Pillars)
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

# ✅ Statuses
PRESET_STATUSES = ["Planned", "In Progress", "Completed", "On Hold"]

def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ------------------ Canonical Schema (safe column names) ------------------
EXPECTED_COLUMNS: Dict[str, str] = {
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

# ------------------ Presentation helpers (pretty column names) ------------------
EXPORT_COL_RENAME = {
    "digital_product": "Digital Product",
    "planisware_feature": "Planisware Feature",
    "planisware_number": "Planisware Number",
}

def for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with user-friendly column names for tables/exports."""
    if df is None or df.empty:
        return df
    return df.rename(columns=EXPORT_COL_RENAME)

def for_export_csv(df: pd.DataFrame) -> bytes:
    """CSV bytes with user-friendly column names."""
    return for_display(df).to_csv(index=False).encode("utf-8")

# ------------------ Streamlit 1.12 helpers ------------------
def _rerun():
    try:
        st.experimental_rerun()
    except Exception:
        pass

def _notify(msg: str, kind: str = "info"):
    if kind == "success":
        st.success(msg)
    elif kind == "warning":
        st.warning(msg)
    elif kind == "error":
        st.error(msg)
    else:
        st.info(msg)

def show_df(df: pd.DataFrame):
    try:
        st.dataframe(df, use_container_width=True)
    except TypeError:
        st.dataframe(df)

def show_chart(fig):
    try:
        st.plotly_chart(fig, use_container_width=True)
    except TypeError:
        st.plotly_chart(fig)

# ------------------ Safe URL masking for UI/debug ------------------
def _mask_url(url: str) -> str:
    try:
        u = urlparse(url)
        q = parse_qs(u.query)
        if "apikey" in q:
            q["apikey"] = ["****"]
        masked_query = "&".join([f"{k}={v[0]}" for k, v in q.items()])
        return f"{u.scheme}://{u.netloc}{u.path}" + (f"?{masked_query}" if masked_query else "")
    except Exception:
        return "****"

def _get_sqlitecloud_url() -> str:
    url = (st.secrets.get("SQLITECLOUD_URL_PRODUCT") or st.secrets.get("SQLITECLOUD_URL") or "").strip()
    if not url:
        st.error("Missing Streamlit secret: SQLITECLOUD_URL_PRODUCT (or SQLITECLOUD_URL).")
        st.stop()
    if "YOUR_REAL_API_KEY" in url:
        st.error("SQLITECLOUD_URL_PRODUCT still contains placeholder YOUR_REAL_API_KEY. Paste the real API key into Streamlit Secrets.")
        st.caption(f"Current: {_mask_url(url)}")
        st.stop()
    return url

@contextmanager
def conn():
    url = _get_sqlitecloud_url()
    c = sqlitecloud.connect(url)
    try:
        yield c
    finally:
        try:
            c.close()
        except Exception:
            pass

def assert_db_awake():
    url = (st.secrets.get("SQLITECLOUD_URL_PRODUCT") or st.secrets.get("SQLITECLOUD_URL") or "").strip()
    try:
        with conn() as c:
            c.execute("SELECT 1")
    except Exception as e:
        st.error("🚨 Database unavailable.")
        st.caption(f"Connection: {_mask_url(url)}")
        st.exception(e)
        st.stop()

# ------------------ Schema / Migration Helpers ------------------
def _table_info_df(c, table_name: str) -> pd.DataFrame:
    return pd.read_sql_query(f'PRAGMA table_info("{table_name}")', c)

def _table_exists(c, table_name: str) -> bool:
    df = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        c,
        params=[table_name],
    )
    return not df.empty

def _rebuild_features_table(c, source_table: str) -> None:
    """
    Rebuild canonical TABLE using EXPECTED_COLUMNS, pulling data from source_table and mapping legacy column names.
    Safe against partial previous migrations (drops temp table first + rollback on error).
    """
    old_info = _table_info_df(c, source_table)
    old_cols = old_info["name"].tolist() if not old_info.empty else []

    # Legacy mappings (Project -> Feature, Pillar -> Digital Product, Plainsware/Planisware drift)
    legacy_map = {
        # Pillar -> Digital Product
        "pillar": "digital_product",
        "Pillar": "digital_product",
        "digital product": "digital_product",
        "Digital Product": "digital_product",

        # Plainsware/Planisware naming drift
        "plainsware_project": "planisware_feature",
        "plainsware_proj": "planisware_feature",
        "planisware_project": "planisware_feature",
        "planisware_feature": "planisware_feature",
        "plainsware_feature": "planisware_feature",

        "plainsware_num": "planisware_number",
        "plainsware_number": "planisware_number",
        "planisware_num": "planisware_number",
        "planisware_number": "planisware_number",
    }

    keep_old, keep_new = [], []
    for col in old_cols:
        if col == "id":
            continue
        if col in EXPECTED_COLUMNS:
            keep_old.append(col)
            keep_new.append(col)
        elif col in legacy_map and legacy_map[col] in EXPECTED_COLUMNS:
            keep_old.append(col)
            keep_new.append(legacy_map[col])

    temp_table = f"{TABLE}__new"

    try:
        c.execute("BEGIN")

        # ✅ critical: remove leftover temp table from any prior failed migration
        c.execute(f'DROP TABLE IF EXISTS "{temp_table}"')

        # create fresh temp table with canonical schema
        ddl_cols = ", ".join([f'"{k}" {v}' for k, v in EXPECTED_COLUMNS.items()])
        c.execute(f'CREATE TABLE "{temp_table}" ({ddl_cols})')

        # copy data from legacy/source table using mapped columns
        if keep_old:
            insert_cols = ", ".join([f'"{x}"' for x in keep_new])
            select_cols = ", ".join([f'"{x}"' for x in keep_old])
            c.execute(
                f'''
                INSERT INTO "{temp_table}" ({insert_cols})
                SELECT {select_cols}
                FROM "{source_table}"
                '''
            )

        # normalize timestamps
        c.execute(
            f'''
            UPDATE "{temp_table}"
            SET created_at = COALESCE(NULLIF(created_at,''), CURRENT_TIMESTAMP),
                updated_at = COALESCE(NULLIF(updated_at,''), CURRENT_TIMESTAMP)
            '''
        )

        # swap tables
        c.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
        c.execute(f'ALTER TABLE "{temp_table}" RENAME TO "{TABLE}"')

        c.execute("COMMIT")

    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise

def ensure_schema_and_migrate() -> None:
    with conn() as c:
        # One-time safety cleanup of stale temp tables
        c.execute(f'DROP TABLE IF EXISTS "{TABLE}__new"')

        # If legacy table exists (Projects/Features with different names), migrate it into TABLE = "features"
        legacy_tables = ["Projects", "projects", "Features", "features_old", "project_portfolio", "digital_product_portfolio"]
        source = None

        if _table_exists(c, TABLE):
            source = TABLE
        else:
            for t in legacy_tables:
                if _table_exists(c, t):
                    source = t
                    break

        # If no source table exists, create canonical fresh table
        if source is None:
            ddl_cols = ", ".join([f'"{k}" {v}' for k, v in EXPECTED_COLUMNS.items()])
            c.execute(f'CREATE TABLE IF NOT EXISTS "{TABLE}" ({ddl_cols})')
            return

        # If source exists but is not canonical schema, rebuild/migrate into canonical
        info = _table_info_df(c, source)
        existing_cols = set(info["name"].tolist()) if not info.empty else set()

        required = {"name", "digital_product"}
        has_required = required.issubset(existing_cols)
        has_legacy_pillar = ("pillar" in existing_cols) or ("Pillar" in existing_cols)
        has_space_digital_product = ("Digital Product" in existing_cols) or ("digital product" in existing_cols)
        has_legacy_plainsware = any(col in existing_cols for col in ["plainsware_project", "plainsware_proj", "plainsware_num", "plainsware_number"])

        if (source != TABLE) or (not has_required) or has_legacy_pillar or has_space_digital_product or has_legacy_plainsware:
            _rebuild_features_table(c, source)
            return

        # If already canonical, ensure missing optional columns are added
        info = _table_info_df(c, TABLE)
        existing_cols = set(info["name"].tolist()) if not info.empty else set()

        for col, ddl in EXPECTED_COLUMNS.items():
            if col not in existing_cols:
                try:
                    c.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN "{col}" {ddl}')
                except Exception:
                    # last-resort rebuild if ALTER fails
                    _rebuild_features_table(c, TABLE)
                    break

# ------------------ Misc Helpers ------------------
def to_iso(d: Optional[date]) -> str:
    return d.strftime("%Y-%m-%d") if d else ""

def try_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None

def safe_index(options: List[str], val: Optional[str], default: int = 0) -> int:
    try:
        if val in options:
            return options.index(val)
    except Exception:
        pass
    return default

def safe_int(x: Any, default: int = 5) -> int:
    try:
        return int(x)
    except Exception:
        return default

def status_to_state(x: Any) -> str:
    s = str(x).strip().lower()
    return "Completed" if s in {"done", "complete", "completed"} else "Ongoing"

def _clean(s: Any) -> str:
    return (s or "").strip()

def distinct_values(col: str) -> List[str]:
    with conn() as c:
        df = pd.read_sql_query(
            f'''
            SELECT DISTINCT "{col}" AS v
            FROM "{TABLE}"
            WHERE "{col}" IS NOT NULL AND TRIM("{col}") <> ''
            ORDER BY v
            ''',
            c,
        )
    return df["v"].dropna().astype(str).tolist()

def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    q = f'SELECT * FROM "{TABLE}"'
    args, where = [], []

    if filters:
        for col in ["digital_product", "status", "owner"]:
            if filters.get(col) and filters[col] != ALL_LABEL:
                where.append(f'"{col}" = ?')
                args.append(filters[col])

        if filters.get("planisware_feature") and filters["planisware_feature"] != ALL_LABEL:
            where.append('"planisware_feature" = ?')
            args.append(filters["planisware_feature"])

        if filters.get("priority") and filters["priority"] != ALL_LABEL:
            where.append('"priority" = ?')
            try:
                args.append(int(filters["priority"]))
            except Exception:
                where.pop()

        if filters.get("search"):
            s = f"%{filters['search'].lower()}%"
            where.append('(LOWER("name") LIKE ? OR LOWER("description") LIKE ?)')
            args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    q += ' ORDER BY COALESCE("start_date",""), COALESCE("due_date",""), COALESCE("created_at","")'

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)

def fetch_all_features() -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(f'SELECT * FROM "{TABLE}" ORDER BY id', c)

# ------------------ PDF Export ------------------
def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
    if not REPORTLAB_AVAILABLE:
        return b""

    dfp = for_display(df)  # ✅ pretty headers for PDF

    buffer = io.BytesIO()
    cpdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    cpdf.setFont("Helvetica-Bold", 14)
    cpdf.drawString(40, height - 40, title)

    cpdf.setFont("Helvetica", 9)
    y = height - 70

    cols = [
        "id", "name", "Digital Product", "priority", "owner", "status",
        "start_date", "due_date", "Planisware Feature", "Planisware Number"
    ]
    cpdf.drawString(40, y, " | ".join(cols))
    y -= 14

    for _, row in dfp.iterrows():
        line = " | ".join([str(row.get(col, ""))[:40] for col in cols])
        cpdf.drawString(40, y, line)
        y -= 12
        if y < 50:
            cpdf.showPage()
            cpdf.setFont("Helvetica", 9)
            y = height - 50

    cpdf.save()
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

# ------------------ Callbacks ------------------
def reset_filters():
    st.session_state["digital_product_f"] = ALL_LABEL
    st.session_state["status_f"] = ALL_LABEL
    st.session_state["owner_f"] = ALL_LABEL
    st.session_state["priority_f"] = ALL_LABEL
    st.session_state["planisware_f"] = ALL_LABEL
    st.session_state["search_f"] = ""
    _notify("Cleared filters.", "success")

# ------------------ App Boot ------------------
st.set_page_config(page_title=APP_PAGE_TITLE, layout="wide")
st.title(APP_TITLE)

# ✅ confirm DB connectivity before doing anything else
assert_db_awake()
ensure_schema_and_migrate()

# ------------------ Session State ------------------
if "feature_selector" not in st.session_state:
    st.session_state.feature_selector = NEW_LABEL
if "reset_feature_selector" not in st.session_state:
    st.session_state.reset_feature_selector = False
if st.session_state.reset_feature_selector:
    st.session_state.feature_selector = NEW_LABEL
    st.session_state.reset_feature_selector = False

# ------------------ Feature Editor ------------------
st.markdown("---")
st.subheader("Feature Editor")

with conn() as c:
    df_features = pd.read_sql_query(f'SELECT id, name FROM "{TABLE}" ORDER BY name', c)

feature_options = [NEW_LABEL] + [f"{row['id']} — {row['name']}" for _, row in df_features.iterrows()]

selected_feature = st.selectbox(
    "Select Feature to Edit",
    feature_options,
    index=safe_index(feature_options, st.session_state.feature_selector),
    key="feature_selector",
)

loaded_feature = None
if selected_feature != NEW_LABEL:
    try:
        feature_id = int(selected_feature.split(" — ", 1)[0])
        with conn() as c:
            df = pd.read_sql_query(f'SELECT * FROM "{TABLE}" WHERE id=?', c, params=[feature_id])
        loaded_feature = df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        loaded_feature = None

status_from_db = distinct_values("status")
status_list = sorted(set(PRESET_STATUSES) | set(status_from_db))
owner_list = distinct_values("owner")

bcol1, bcol2 = st.columns([1, 1])
new_clicked = bcol1.button("New", key="btn_new_feature")
bcol2.button("Clear Filters", key="btn_clear_filters", on_click=reset_filters)

if new_clicked:
    st.session_state.reset_feature_selector = True
    _rerun()

# ------------------ Form ------------------
digital_product_from_db = distinct_values("digital_product")
digital_product_options = sorted(set(PRESET_DIGITAL_PRODUCTS) | set(digital_product_from_db)) or [""]

with st.form("feature_form"):
    c1, c2 = st.columns(2)

    name_val = loaded_feature.get("name") if loaded_feature else ""
    digital_product_val = loaded_feature.get("digital_product") if loaded_feature else (digital_product_options[0] if digital_product_options else "")
    priority_val = int(loaded_feature.get("priority", 5)) if loaded_feature else 5
    owner_val = loaded_feature.get("owner") if loaded_feature else ""
    status_val = loaded_feature.get("status") if loaded_feature else "Planned"
    start_val = try_date(loaded_feature.get("start_date")) if loaded_feature else date.today()
    due_val = try_date(loaded_feature.get("due_date")) if loaded_feature else date.today()
    desc_val = loaded_feature.get("description") if loaded_feature else ""

    pw_val = loaded_feature.get("planisware_feature", "No") if loaded_feature else "No"
    pw_num_val = loaded_feature.get("planisware_number") if loaded_feature else None

    with c1:
        feature_name = st.text_input("Name*", value=name_val, key="editor_name")

        dp_index = digital_product_options.index(digital_product_val) if digital_product_val in digital_product_options else 0
        feature_digital_product = st.selectbox("Digital Product*", options=digital_product_options, index=dp_index, key="editor_digital_product")

        new_digital_product = st.text_input("Or type a new Digital Product (optional)", value="", key="editor_digital_product_new")
        if new_digital_product.strip():
            feature_digital_product = new_digital_product.strip()

        feature_priority = st.number_input(
            "Priority", min_value=1, max_value=99, value=int(priority_val), step=1, format="%d", key="editor_priority"
        )
        description = st.text_area("Description", value=desc_val, height=120, key="editor_desc")

    with c2:
        owner_options = owner_list[:] if owner_list else [""]
        owner_index = owner_options.index(owner_val) if owner_val in owner_options else 0
        feature_owner = st.selectbox("Owner*", options=owner_options, index=owner_index, key="editor_owner")

        new_owner = st.text_input("Or type a new Owner (optional)", value="", key="editor_owner_new")
        if new_owner.strip():
            feature_owner = new_owner.strip()

        feature_status = st.selectbox("Status", status_list, index=safe_index(status_list, status_val), key="editor_status")

        start_date = st.date_input("Start Date", value=start_val, key="editor_start")
        due_date = st.date_input("Due Date", value=due_val, key="editor_due")

        planisware_feature = st.selectbox(
            "Planisware Feature?", ["No", "Yes"],
            index=1 if str(pw_val).strip() == "Yes" else 0,
            key="editor_planisware_feature"
        )

        planisware_number = None
        if planisware_feature == "Yes":
            default_num = str(pw_num_val).strip() if pw_num_val is not None else ""
            planisware_number = st.text_input(
                "Planisware Feature Number (JJMD-0079575)*",
                value=default_num, placeholder="JJMD-0079575",
                key="editor_planisware_number"
            )
            if planisware_number.strip() and not JJMD_PATTERN.fullmatch(planisware_number.strip()):
                st.warning("Format must be JJMD-0079575 (JJMD- + 7 digits).")

    col_a, col_b, col_c = st.columns(3)
    submitted_new = col_a.form_submit_button("Save New")
    submitted_update = col_b.form_submit_button("Update")
    submitted_delete = col_c.form_submit_button("Delete")

# ------------------ CRUD Actions (autocommit) ------------------
if submitted_new:
    errors = []
    feature_name_clean = _clean(feature_name)
    feature_digital_product_clean = _clean(feature_digital_product)
    feature_owner_clean = _clean(feature_owner)
    feature_status_clean = _clean(feature_status)
    safe_priority_val = safe_int(feature_priority, default=5)

    if not feature_name_clean:
        errors.append("Name is required.")
    if not feature_digital_product_clean:
        errors.append("Digital Product is required.")
    if not feature_owner_clean:
        errors.append("Owner is required.")

    pw_number_db = None
    if planisware_feature == "Yes":
        try:
            pw_number_db = validate_planisware(planisware_feature, planisware_number)
        except Exception as e:
            errors.append(str(e))

    if errors:
        st.error(" ".join(errors))
    else:
        ts = now_ts()
        try:
            with conn() as c:
                c.execute(
                    f"""
                    INSERT INTO "{TABLE}"
                    (name, digital_product, priority, description, owner, status, start_date, due_date,
                     planisware_feature, planisware_number,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feature_name_clean,
                        feature_digital_product_clean,
                        safe_priority_val,
                        _clean(description),
                        feature_owner_clean,
                        feature_status_clean,
                        to_iso(start_date),
                        to_iso(due_date),
                        planisware_feature,
                        pw_number_db,
                        ts,
                        ts,
                    ),
                )
            _notify("✅ Feature created successfully!", "success")
            st.session_state.reset_feature_selector = True
            _rerun()
        except Exception as e:
            st.error(f"Save error: {e}")
            st.stop()

if submitted_update:
    if not loaded_feature:
        st.warning("Select an existing Feature to update.")
    else:
        errors = []
        feature_name_clean = _clean(feature_name)
        feature_digital_product_clean = _clean(feature_digital_product)
        feature_owner_clean = _clean(feature_owner)
        feature_status_clean = _clean(feature_status)
        safe_priority_val = safe_int(feature_priority, default=5)

        if not feature_name_clean:
            errors.append("Name is required.")
        if not feature_digital_product_clean:
            errors.append("Digital Product is required.")
        if not feature_owner_clean:
            errors.append("Owner is required.")

        pw_number_db = None
        if planisware_feature == "Yes":
            try:
                pw_number_db = validate_planisware(planisware_feature, planisware_number)
            except Exception as e:
                errors.append(str(e))

        if errors:
            st.error(" ".join(errors))
        else:
            ts = now_ts()
            try:
                with conn() as c:
                    c.execute(
                        f"""
                        UPDATE "{TABLE}"
                        SET name=?, digital_product=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?,
                            planisware_feature=?, planisware_number=?,
                            updated_at=?
                        WHERE id=?
                        """,
                        (
                            feature_name_clean,
                            feature_digital_product_clean,
                            safe_priority_val,
                            _clean(description),
                            feature_owner_clean,
                            feature_status_clean,
                            to_iso(start_date),
                            to_iso(due_date),
                            planisware_feature,
                            pw_number_db,
                            ts,
                            int(loaded_feature["id"]),
                        ),
                    )
                _notify("✅ Feature updated!", "success")
                _rerun()
            except Exception as e:
                st.error(f"Update error: {e}")
                st.stop()

if submitted_delete:
    if not loaded_feature:
        st.warning("Select an existing Feature to delete.")
    else:
        try:
            with conn() as c:
                c.execute(f'DELETE FROM "{TABLE}" WHERE id=?', (int(loaded_feature["id"]),))
            _notify("Feature deleted.", "warning")
            st.session_state.reset_feature_selector = True
            _rerun()
        except Exception as e:
            st.error(f"Delete error: {e}")
            st.stop()

# ------------------ Filters + Reports ------------------
st.markdown("---")
st.subheader("Filters")

colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

digital_products = [ALL_LABEL] + sorted(set(PRESET_DIGITAL_PRODUCTS) | set(distinct_values("digital_product")))
owners = [ALL_LABEL] + distinct_values("owner")
statuses = [ALL_LABEL] + status_list

priority_vals: List[int] = []
try:
    pv = distinct_values("priority")
    priority_vals = sorted({int(x) for x in pv if str(x).strip().isdigit()})
except Exception:
    pass
priority_opts = [ALL_LABEL] + [str(x) for x in priority_vals]

planisware_opts = [ALL_LABEL, "Yes", "No"]

digital_product_f = colF1.selectbox("Digital Product", digital_products, key="digital_product_f")
status_f = colF2.selectbox("Status", statuses, key="status_f")
owner_f = colF3.selectbox("Owner", owners, key="owner_f")
priority_f = colF4.selectbox("Priority", priority_opts, key="priority_f")
planisware_f = colF5.selectbox("Planisware", planisware_opts, key="planisware_f")
search_f = colF6.text_input("Search", key="search_f")

filters = dict(
    digital_product=digital_product_f,
    status=status_f,
    owner=owner_f,
    priority=priority_f,
    planisware_feature=planisware_f,
    search=search_f
)

data = fetch_df(filters)

# Derived years
data["start_year"] = pd.to_datetime(data.get("start_date", ""), errors="coerce").dt.year
data["due_year"] = pd.to_datetime(data.get("due_date", ""), errors="coerce").dt.year

st.markdown("---")
st.subheader("Report Controls")

rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])
year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"], key="year_mode")
year_col = "start_year" if year_mode == "Start Year" else "due_year"
years = [ALL_LABEL] + sorted(data[year_col].dropna().astype(int).unique().tolist())
year_f = rc2.selectbox("Year", years, key="year_f")
top_n = rc3.slider("Top N per Digital Product", min_value=1, max_value=10, value=5, key="top_n")
show_all = rc4.checkbox("Show ALL Reports", value=True, key="show_all_reports")

if year_f != ALL_LABEL:
    data = data[data[year_col] == int(year_f)]

if show_all:
    show_kpi = show_digital_product_chart = show_roadmap = show_table = True
else:
    cK1, cK2, cK3, cK4 = st.columns(4)
    show_kpi = cK1.checkbox("KPI Cards", True, key="show_kpi")
    show_digital_product_chart = cK2.checkbox("Digital Product Status Chart", True, key="show_digital_product_chart")
    show_roadmap = cK3.checkbox("Roadmap", True, key="show_roadmap")
    show_table = cK4.checkbox("Feature Table", True, key="show_table")

if show_kpi:
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    total = len(data)
    completed = (data["status"].apply(status_to_state) == "Completed").sum()
    ongoing = (data["status"].apply(status_to_state) != "Completed").sum()
    digital_product_count = data["digital_product"].replace("", pd.NA).dropna().nunique()

    k1.metric("Features", int(total))
    k2.metric("Completed", int(completed))
    k3.metric("Ongoing", int(ongoing))
    k4.metric("Distinct Digital Products", int(digital_product_count))

if show_digital_product_chart:
    st.markdown("---")
    status_df = data.copy()
    if not status_df.empty:
        status_df["state"] = status_df["status"].apply(status_to_state)
        dp_summary = (
            status_df.groupby(["digital_product", "state"], dropna=False)
            .size()
            .reset_index(name="count")
        )
        dp_summary["digital_product"] = dp_summary["digital_product"].replace("", "(Unspecified)")
        fig = px.bar(
            dp_summary,
            x="digital_product",
            y="count",
            color="state",
            barmode="group",
            title="Features by Digital Product — Completed vs Ongoing",
        )
        show_chart(fig)
    else:
        st.info("No data available for Digital Product chart.")

st.markdown("---")
st.subheader(f"Top {top_n} Features per Digital Product")
if not data.empty:
    top_df = (
        data.replace({"digital_product": {"": "(Unspecified)"}})
        .sort_values(["digital_product", "priority", "name"], na_position="last")
        .groupby("digital_product", dropna=False, as_index=False)
        .head(top_n)
    )
    # ✅ show friendly column name
    show_df(for_display(top_df))
else:
    st.info("No Features to display for Top N.")

roadmap_fig = None
if show_roadmap:
    st.markdown("---")
    st.subheader("Roadmap")
    gantt = data.copy()
    gantt["Start"] = pd.to_datetime(gantt.get("start_date", ""), errors="coerce")
    gantt["Finish"] = pd.to_datetime(gantt.get("due_date", ""), errors="coerce")
    gantt = gantt.dropna(subset=["Start", "Finish"])
    if not gantt.empty:
        roadmap_fig = px.timeline(
            gantt,
            x_start="Start",
            x_end="Finish",
            y="name",
            color="digital_product",
            title="Feature Timeline",
        )
        roadmap_fig.update_yaxes(autorange="reversed")
        show_chart(roadmap_fig)
    else:
        st.info("No valid date ranges to draw the roadmap.")

if show_table:
    st.markdown("---")
    st.subheader("Features")
    # ✅ show friendly column name
    show_df(for_display(data))

# ------------------ Export Options ------------------
st.markdown("---")
st.subheader("Export Options")

st.download_button(
    "⬇️ Download CSV Report (Filtered)",
    data=for_export_csv(data),  # ✅ Digital Product header in CSV
    file_name="digital_product_filtered.csv",
    mime="text/csv",
    key="export_csv_filtered",
)

full_df = fetch_all_features()
st.download_button(
    "🗄️ Download FULL Database (CSV)",
    data=for_export_csv(full_df),  # ✅ Digital Product header in CSV
    file_name="digital_product_full_database.csv",
    mime="text/csv",
    key="export_csv_full_db",
)

if REPORTLAB_AVAILABLE:
    pdf_bytes = build_pdf_report(data, title="Digital Product Report (Filtered)")
    st.download_button(
        "🖨️ Download Printable Report (PDF)",
        data=pdf_bytes,
        file_name="digital_product_report_filtered.pdf",
        mime="application/pdf",
        key="export_pdf_filtered",
    )

if roadmap_fig is not None:
    st.markdown("---")
    st.subheader("Export Roadmap")
    st.download_button(
        "🌐 Download Roadmap (Interactive HTML)",
        data=roadmap_fig.to_html(include_plotlyjs="cdn"),
        file_name="digital_product_roadmap.html",
        mime="text/html",
        key="export_roadmap_html",
    )
    if KALEIDO_AVAILABLE:
        try:
            img_bytes = pio.to_image(roadmap_fig, format="png", scale=2)
            st.download_button(
                "📸 Download Roadmap (PNG)",
                data=img_bytes,
                file_name="digital_product_roadmap.png",
                mime="image/png",
                key="export_roadmap_png",
            )
        except Exception as e:
            st.info(f"PNG export unavailable in this runtime: {e}")
