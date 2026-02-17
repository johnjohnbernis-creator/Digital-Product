# ----------------------------------------------------------
# Digital Product Portfolio (2nd app) - Streamlit 1.12 compatible
# Separate DB + different Pillars + fixed Status list
# ----------------------------------------------------------

import os
import io
import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional, Any

import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st

# ------------------ Optional dependencies ------------------
# PDF (ReportLab)
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# Plotly static image export (Kaleido + Chrome typically required)
try:
    import kaleido  # noqa: F401
    KALEIDO_AVAILABLE = True
except Exception:
    KALEIDO_AVAILABLE = False

# ------------------ Planisware/JJMD validation ------------------
import re
JJMD_PATTERN = re.compile(r"^JJMD-\d{7}$", re.IGNORECASE)

def validate_plainsware(plainsware_project: str, plainsware_number: Any) -> Optional[str]:
    """
    If Planisware = Yes, the user must manually enter a Planisware number
    in the format JJMD-0079575.

    Returns the validated Planisware number (to be saved to the column),
    or None if Planisware = No.
    """
    if str(plainsware_project).strip().lower() == "yes":
        if plainsware_number is None or not str(plainsware_number).strip():
            raise ValueError("Planisware Project Number must be entered when Plainsware Project is Yes.")

        value = str(plainsware_number).strip().upper()

        if not JJMD_PATTERN.fullmatch(value):
            raise ValueError("Planisware Project Number must be in the format JJMD-0079575 (JJMD- + 7 digits).")

        return value

    return None

# ------------------ App Identity (SECOND APP) ------------------
APP_TITLE = "Digital Product — Web Version"
APP_PAGE_TITLE = "Digital Product Portfolio"

# ✅ Separate database for this second app
DB_PATH = "digital_product.db"

TABLE = "projects"
NEW_LABEL = "<New Project>"
ALL_LABEL = "All"

# ✅ Pillars for the SECOND APP
PRESET_PILLARS = [
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

# ✅ Statuses (so Status dropdown is never empty on a new DB)
PRESET_STATUSES = [
    "Planned",
    "In Progress",
    "Completed",
    "On Hold",
]

def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ✅ IMPORTANT CHANGE: plainsware_number is TEXT now (supports JJMD-0079575)
EXPECTED_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "name": "TEXT NOT NULL",
    "pillar": "TEXT NOT NULL",
    "priority": "INTEGER DEFAULT 5",
    "description": "TEXT",
    "owner": "TEXT",
    "status": "TEXT",
    "start_date": "TEXT",
    "due_date": "TEXT",
    "plainsware_project": "TEXT DEFAULT 'No'",
    "plainsware_number": "TEXT",  # <-- CHANGED FROM INTEGER TO TEXT
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

# ------------------ Streamlit 1.12 helpers ------------------
def _rerun():
    # Streamlit 1.12 uses experimental_rerun
    try:
        st.experimental_rerun()
    except Exception:
        pass

def _notify(msg: str, kind: str = "info"):
    # Streamlit 1.12 has no st.toast. Use info/success/warning/error.
    if kind == "success":
        st.success(msg)
    elif kind == "warning":
        st.warning(msg)
    elif kind == "error":
        st.error(msg)
    else:
        st.info(msg)

def show_df(df: pd.DataFrame):
    """
    Streamlit-version-safe dataframe display.
    Streamlit 1.12 does NOT support use_container_width for st.dataframe.
    """
    try:
        st.dataframe(df, use_container_width=True)  # newer versions
    except TypeError:
        st.dataframe(df)  # Streamlit 1.12

def show_chart(fig):
    """
    Streamlit-version-safe plotly display.
    """
    try:
        st.plotly_chart(fig, use_container_width=True)
    except TypeError:
        st.plotly_chart(fig)

# ------------------ DB / Utility Helpers ------------------
def conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def _table_info_df(c: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)

def _needs_rebuild_due_to_created_at(info: pd.DataFrame) -> bool:
    """Rebuild if created_at exists and is NOT NULL but has no default."""
    if info.empty:
        return False
    row = info[info["name"] == "created_at"]
    if row.empty:
        return False
    notnull = int(row.iloc[0]["notnull"]) == 1
    dflt = row.iloc[0]["dflt_value"]
    no_default = pd.isna(dflt) or str(dflt).strip() == ""
    return bool(notnull and no_default)

def _needs_rebuild_due_to_plainsware_number_type(info: pd.DataFrame) -> bool:
    """Rebuild if plainsware_number exists but is not TEXT (old DB may have INTEGER)."""
    if info.empty:
        return False
    row = info[info["name"] == "plainsware_number"]
    if row.empty:
        return False
    col_type = str(row.iloc[0]["type"] or "").strip().upper()
    return col_type != "TEXT"

def _rebuild_projects_table(c: sqlite3.Connection) -> None:
    """Rebuild projects table to match expected schema (including TEXT plainsware_number)."""
    old_info = pd.read_sql_query(f"PRAGMA table_info({TABLE})", c)
    old_cols = old_info["name"].tolist()

    legacy_map = {
        "plainsware_proj": "plainsware_project",
        "plainsware_num": "plainsware_number",
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

    c.execute("BEGIN")
    c.execute(
        f"""
        CREATE TABLE {TABLE}__new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pillar TEXT NOT NULL,
            priority INTEGER DEFAULT 5,
            description TEXT,
            owner TEXT,
            status TEXT,
            start_date TEXT,
            due_date TEXT,
            plainsware_project TEXT DEFAULT 'No',
            plainsware_number TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    if keep_old:
        c.execute(
            f"""
            INSERT INTO {TABLE}__new ({", ".join(keep_new)})
            SELECT {", ".join(keep_old)} FROM {TABLE}
            """
        )

    c.execute(
        f"""
        UPDATE {TABLE}__new
        SET created_at = COALESCE(NULLIF(created_at,''), CURRENT_TIMESTAMP),
            updated_at = COALESCE(NULLIF(updated_at,''), CURRENT_TIMESTAMP)
        """
    )

    c.execute(f"DROP TABLE {TABLE}")
    c.execute(f"ALTER TABLE {TABLE}__new RENAME TO {TABLE}")
    c.execute("COMMIT")

def ensure_schema_and_migrate() -> None:
    """Ensure the projects table exists and includes required columns (with TEXT plainsware_number)."""
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pillar TEXT NOT NULL,
                priority INTEGER DEFAULT 5,
                description TEXT,
                owner TEXT,
                status TEXT,
                start_date TEXT,
                due_date TEXT,
                plainsware_project TEXT DEFAULT 'No',
                plainsware_number TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        c.commit()

        info = _table_info_df(c)
        existing_set = set(info["name"].tolist())

        # Rename legacy typo columns
        if "plainsware_proj" in existing_set and "plainsware_project" not in existing_set:
            try:
                c.execute(f'ALTER TABLE {TABLE} RENAME COLUMN "plainsware_proj" TO "plainsware_project"')
                c.commit()
            except Exception:
                _rebuild_projects_table(c)

        if "plainsware_num" in existing_set and "plainsware_number" not in existing_set:
            try:
                c.execute(f'ALTER TABLE {TABLE} RENAME COLUMN "plainsware_num" TO "plainsware_number"')
                c.commit()
            except Exception:
                _rebuild_projects_table(c)

        info = _table_info_df(c)

        # Rebuild if created_at default is wrong
        if _needs_rebuild_due_to_created_at(info):
            _rebuild_projects_table(c)
            info = _table_info_df(c)

        # Rebuild if plainsware_number type is not TEXT (old DB)
        if _needs_rebuild_due_to_plainsware_number_type(info):
            _rebuild_projects_table(c)
            info = _table_info_df(c)

        existing_set = set(info["name"].tolist())

        for col, ddl in EXPECTED_COLUMNS.items():
            if col not in existing_set and col not in ("id", "name", "pillar"):
                try:
                    c.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
                except Exception:
                    _rebuild_projects_table(c)
                    break

        c.commit()

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

def status_to_state(x: Any) -> str:
    s = str(x).strip().lower()
    return "Completed" if s in {"done", "complete", "completed"} else "Ongoing"

def safe_int(x: Any, default: int = 5) -> int:
    try:
        return int(x)
    except Exception:
        return default

def distinct_values(col: str) -> List[str]:
    # This uses a fixed set of col names in code; do not pass user input here.
    with conn() as c:
        df = pd.read_sql_query(
            f"""
            SELECT DISTINCT {col}
            FROM {TABLE}
            WHERE {col} IS NOT NULL AND TRIM({col}) <> ''
            ORDER BY {col}
            """,
            c,
        )
    return df[col].dropna().astype(str).tolist()

def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    q = f"SELECT * FROM {TABLE}"
    args, where = [], []

    if filters:
        for col in ["pillar", "status", "owner"]:
            if filters.get(col) and filters[col] != ALL_LABEL:
                where.append(f"{col} = ?")
                args.append(filters[col])

        if filters.get("plainsware") and filters["plainsware"] != ALL_LABEL:
            where.append("plainsware_project = ?")
            args.append(filters["plainsware"])

        if filters.get("priority") and filters["priority"] != ALL_LABEL:
            where.append("priority = ?")
            try:
                args.append(int(filters["priority"]))
            except Exception:
                where.pop()

        if filters.get("search"):
            s = f"%{filters['search'].lower()}%"
            where.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
            args.extend([s, s])

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY COALESCE(start_date,''), COALESCE(due_date,''), COALESCE(created_at,'')"

    with conn() as c:
        return pd.read_sql_query(q, c, params=args)

def fetch_all_projects() -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(f"SELECT * FROM {TABLE} ORDER BY id", c)

# ------------------ PDF Export ------------------
def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
    if not REPORTLAB_AVAILABLE:
        return b""

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, height - 40, title)

    c.setFont("Helvetica", 9)
    y = height - 70

    cols = [
        "id", "name", "pillar", "priority", "owner", "status",
        "start_date", "due_date", "plainsware_project", "plainsware_number"
    ]
    header = " | ".join(cols)
    c.drawString(40, y, header)
    y -= 14

    for _, row in df.iterrows():
        line = " | ".join([str(row.get(col, ""))[:40] for col in cols])
        c.drawString(40, y, line)
        y -= 12
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 9)
            y = height - 50

    c.save()
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

# ------------------ Callbacks ------------------
def reset_filters():
    st.session_state["pillar_f"] = ALL_LABEL
    st.session_state["status_f"] = ALL_LABEL
    st.session_state["owner_f"] = ALL_LABEL
    st.session_state["priority_f"] = ALL_LABEL
    st.session_state["plainsware_f"] = ALL_LABEL
    st.session_state["search_f"] = ""
    _notify("Cleared filters.", "success")
    # ✅ NO rerun here

# ------------------ App Boot ------------------
st.set_page_config(page_title=APP_PAGE_TITLE, layout="wide")
st.title(APP_TITLE)

ensure_schema_and_migrate()

# This check is mostly redundant because connecting creates the DB file,
# but leaving it here is harmless.
if not os.path.exists(DB_PATH):
    st.error("Database not found.")
    st.stop()

# ------------------ Session State ------------------
if "project_selector" not in st.session_state:
    st.session_state.project_selector = NEW_LABEL
if "reset_project_selector" not in st.session_state:
    st.session_state.reset_project_selector = False
if st.session_state.reset_project_selector:
    st.session_state.project_selector = NEW_LABEL
    st.session_state.reset_project_selector = False

# ------------------ Project Editor ------------------
st.markdown("---")
st.subheader("Project Editor")

with conn() as c:
    df_projects = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

project_options = [NEW_LABEL] + [f"{row['id']} — {row['name']}" for _, row in df_projects.iterrows()]

selected_project = st.selectbox(
    "Select Project to Edit",
    project_options,
    index=safe_index(project_options, st.session_state.project_selector),
    key="project_selector",
)

loaded_project = None
if selected_project != NEW_LABEL:
    try:
        project_id = int(selected_project.split(" — ", 1)[0])
        with conn() as c:
            df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[project_id])
        loaded_project = df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        loaded_project = None

# ✅ Status list now comes from preset + db
status_from_db = distinct_values("status")
status_list = sorted(set(PRESET_STATUSES) | set(status_from_db))

owner_list = distinct_values("owner")

bcol1, bcol2 = st.columns([1, 1])
new_clicked = bcol1.button("New", key="btn_new_project")
bcol2.button("Clear Filters", key="btn_clear_filters", on_click=reset_filters)

if new_clicked:
    st.session_state.reset_project_selector = True
    _rerun()

# ------------------ Form ------------------
def _clean(s: Any) -> str:
    return (s or "").strip()

pillar_from_db = distinct_values("pillar")
pillar_options = sorted(set(PRESET_PILLARS) | set(pillar_from_db))
if not pillar_options:
    pillar_options = [""]

with st.form("project_form"):
    c1, c2 = st.columns(2)

    name_val = loaded_project.get("name") if loaded_project else ""
    pillar_val = loaded_project.get("pillar") if loaded_project else (pillar_options[0] if pillar_options else "")
    priority_val = int(loaded_project.get("priority", 5)) if loaded_project else 5
    owner_val = loaded_project.get("owner") if loaded_project else ""
    status_val = loaded_project.get("status") if loaded_project else "Planned"
    start_val = try_date(loaded_project.get("start_date")) if loaded_project else date.today()
    due_val = try_date(loaded_project.get("due_date")) if loaded_project else date.today()
    desc_val = loaded_project.get("description") if loaded_project else ""

    pw_val = loaded_project.get("plainsware_project", "No") if loaded_project else "No"
    pw_num_val = loaded_project.get("plainsware_number") if loaded_project else None

    # LEFT
    with c1:
        project_name = st.text_input("Name*", value=name_val, key="editor_name")

        pillar_index = pillar_options.index(pillar_val) if pillar_val in pillar_options else 0
        project_pillar = st.selectbox("Pillar*", options=pillar_options, index=pillar_index, key="editor_pillar")

        new_pillar = st.text_input("Or type a new Pillar (optional)", value="", key="editor_pillar_new")
        if new_pillar.strip():
            project_pillar = new_pillar.strip()

        project_priority = st.number_input(
            "Priority", min_value=1, max_value=99, value=int(priority_val),
            step=1, format="%d", key="editor_priority",
        )

        description = st.text_area("Description", value=desc_val, height=120, key="editor_desc")

    # RIGHT
    with c2:
        owner_options = owner_list[:] if owner_list else [""]
        owner_index = owner_options.index(owner_val) if owner_val in owner_options else 0
        project_owner = st.selectbox("Owner*", options=owner_options, index=owner_index, key="editor_owner")

        new_owner = st.text_input("Or type a new Owner (optional)", value="", key="editor_owner_new")
        if new_owner.strip():
            project_owner = new_owner.strip()

        project_status = st.selectbox(
            "Status",
            status_list,
            index=safe_index(status_list, status_val),
            key="editor_status",
        )

        start_date = st.date_input("Start Date", value=start_val, key="editor_start")
        due_date = st.date_input("Due Date", value=due_val, key="editor_due")

        plainsware_project = st.selectbox(
            "Plainsware Project?", ["No", "Yes"],
            index=1 if str(pw_val).strip() == "Yes" else 0,
            key="editor_plainsware_project",
        )

        # ✅ NEW BOX: manual JJMD input (TEXT)
        plainsware_number = None
        if plainsware_project == "Yes":
            default_num = str(pw_num_val).strip() if pw_num_val is not None else ""
            plainsware_number = st.text_input(
                "Planisware Project Number (JJMD-0079575)*",
                value=default_num,
                placeholder="JJMD-0079575",
                key="editor_plainsware_number",
            )

            # Non-blocking live warning (submit validation handled later)
            if plainsware_number.strip() and not JJMD_PATTERN.fullmatch(plainsware_number.strip()):
                st.warning("Format must be JJMD-0079575 (JJMD- + 7 digits).")
        else:
            plainsware_number = None

    col_a, col_b, col_c = st.columns(3)
    submitted_new = col_a.form_submit_button("Save New")
    submitted_update = col_b.form_submit_button("Update")
    submitted_delete = col_c.form_submit_button("Delete")

# ------------------ CRUD Actions ------------------
if submitted_new:
    errors = []
    project_name_clean = _clean(project_name)
    project_pillar_clean = _clean(project_pillar)
    project_owner_clean = _clean(project_owner)
    project_status_clean = _clean(project_status)
    safe_priority_val = safe_int(project_priority, default=5)

    if not project_name_clean:
        errors.append("Name is required.")
    if not project_pillar_clean:
        errors.append("Pillar is required.")
    if not project_owner_clean:
        errors.append("Owner is required.")

    # ✅ Validate JJMD only if Yes
    pw_number_db = None
    if plainsware_project == "Yes":
        try:
            pw_number_db = validate_plainsware(plainsware_project, plainsware_number)  # returns TEXT
        except Exception as e:
            errors.append(str(e))

    if errors:
        st.error(" ".join(errors))
    else:
        try:
            ts = now_ts()
            with conn() as c:
                c.execute(
                    f"""
                    INSERT INTO {TABLE}
                    (name, pillar, priority, description, owner, status, start_date, due_date,
                     plainsware_project, plainsware_number,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_name_clean,
                        project_pillar_clean,
                        safe_priority_val,
                        _clean(description),
                        project_owner_clean,
                        project_status_clean,
                        to_iso(start_date),
                        to_iso(due_date),
                        plainsware_project,
                        pw_number_db,
                        ts,
                        ts,
                    ),
                )
                c.commit()

            _notify("✅ Project created successfully!", "success")
            st.session_state.reset_project_selector = True
            _rerun()

        except sqlite3.IntegrityError as e:
            st.error(f"SQLite IntegrityError: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Unexpected save error: {e}")
            st.stop()

if submitted_update:
    if not loaded_project:
        st.warning("Select an existing project to update.")
    else:
        errors = []
        project_name_clean = _clean(project_name)
        project_pillar_clean = _clean(project_pillar)
        project_owner_clean = _clean(project_owner)
        project_status_clean = _clean(project_status)
        safe_priority_val = safe_int(project_priority, default=5)

        if not project_name_clean:
            errors.append("Name is required.")
        if not project_pillar_clean:
            errors.append("Pillar is required.")
        if not project_owner_clean:
            errors.append("Owner is required.")

        pw_number_db = None
        if plainsware_project == "Yes":
            try:
                pw_number_db = validate_plainsware(plainsware_project, plainsware_number)  # returns TEXT
            except Exception as e:
                errors.append(str(e))

        if errors:
            st.error(" ".join(errors))
        else:
            try:
                ts = now_ts()
                with conn() as c:
                    c.execute(
                        f"""
                        UPDATE {TABLE}
                        SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?,
                            plainsware_project=?, plainsware_number=?,
                            updated_at=?
                        WHERE id=?
                        """,
                        (
                            project_name_clean,
                            project_pillar_clean,
                            safe_priority_val,
                            _clean(description),
                            project_owner_clean,
                            project_status_clean,
                            to_iso(start_date),
                            to_iso(due_date),
                            plainsware_project,
                            pw_number_db,
                            ts,
                            int(loaded_project["id"]),
                        ),
                    )
                    c.commit()

                _notify("✅ Project updated!", "success")
                _rerun()

            except sqlite3.IntegrityError as e:
                st.error(f"SQLite IntegrityError: {e}")
                st.stop()
            except Exception as e:
                st.error(f"Unexpected update error: {e}")
                st.stop()

if submitted_delete:
    if not loaded_project:
        st.warning("Select an existing project to delete.")
    else:
        try:
            with conn() as c:
                c.execute(f"DELETE FROM {TABLE} WHERE id=?", (int(loaded_project["id"]),))
                c.commit()

            _notify("Project deleted.", "warning")
            st.session_state.reset_project_selector = True
            _rerun()

        except sqlite3.IntegrityError as e:
            st.error(f"SQLite IntegrityError: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Unexpected delete error: {e}")
            st.stop()

# ------------------ Global Filters ------------------
st.markdown("---")
st.subheader("Filters")

colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

pillars = [ALL_LABEL] + sorted(set(PRESET_PILLARS) | set(distinct_values("pillar")))
owners = [ALL_LABEL] + distinct_values("owner")
statuses = [ALL_LABEL] + status_list  # ✅ uses preset + db

priority_vals: List[int] = []
try:
    pv = distinct_values("priority")
    priority_vals = sorted({int(x) for x in pv if str(x).strip().isdigit()})
except Exception:
    pass
priority_opts = [ALL_LABEL] + [str(x) for x in priority_vals]

plainsware_opts = [ALL_LABEL, "Yes", "No"]

pillar_f = colF1.selectbox("Pillar", pillars, key="pillar_f")
status_f = colF2.selectbox("Status", statuses, key="status_f")
owner_f = colF3.selectbox("Owner", owners, key="owner_f")
priority_f = colF4.selectbox("Priority", priority_opts, key="priority_f")
plainsware_f = colF5.selectbox("Plainsware", plainsware_opts, key="plainsware_f")
search_f = colF6.text_input("Search", key="search_f")

filters = dict(
    pillar=pillar_f,
    status=status_f,
    owner=owner_f,
    priority=priority_f,
    plainsware=plainsware_f,
    search=search_f,
)

data = fetch_df(filters)

# ------------------ Derived Years ------------------
data["start_year"] = pd.to_datetime(data.get("start_date", ""), errors="coerce").dt.year
data["due_year"] = pd.to_datetime(data.get("due_date", ""), errors="coerce").dt.year

# ------------------ Report Controls ------------------
st.markdown("---")
st.subheader("Report Controls")

rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])
year_mode = rc1.radio("Year Type", ["Start Year", "Due Year"], key="year_mode")
year_col = "start_year" if year_mode == "Start Year" else "due_year"

years = [ALL_LABEL] + sorted(data[year_col].dropna().astype(int).unique().tolist())
year_f = rc2.selectbox("Year", years, key="year_f")

top_n = rc3.slider("Top N per Pillar", min_value=1, max_value=10, value=5, key="top_n")
show_all = rc4.checkbox("Show ALL Reports", value=True, key="show_all_reports")

if not show_all:
    cK1, cK2, cK3, cK4 = st.columns(4)
    show_kpi = cK1.checkbox("KPI Cards", True, key="show_kpi")
    show_pillar_chart = cK2.checkbox("Pillar Status Chart", True, key="show_pillar_chart")
    show_roadmap = cK3.checkbox("Roadmap", True, key="show_roadmap")
    show_table = cK4.checkbox("Projects Table", True, key="show_table")
else:
    show_kpi = show_pillar_chart = show_roadmap = show_table = True

if year_f != ALL_LABEL:
    data = data[data[year_col] == int(year_f)]

# ------------------ KPI Cards ------------------
if show_kpi:
    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    total = len(data)
    completed = (data["status"].apply(status_to_state) == "Completed").sum()
    ongoing = (data["status"].apply(status_to_state) != "Completed").sum()
    pillars_count = data["pillar"].replace("", pd.NA).dropna().nunique()

    k1.metric("Projects", total)
    k2.metric("Completed", completed)
    k3.metric("Ongoing", ongoing)
    k4.metric("Distinct Pillars", int(pillars_count))

# ------------------ Pillar Status Chart ------------------
if show_pillar_chart:
    st.markdown("---")
    status_df = data.copy()
    if not status_df.empty:
        status_df["state"] = status_df["status"].apply(status_to_state)
        pillar_summary = (
            status_df.groupby(["pillar", "state"], dropna=False)
            .size()
            .reset_index(name="count")
        )
        pillar_summary["pillar"] = pillar_summary["pillar"].replace("", "(Unspecified)")
        fig = px.bar(
            pillar_summary,
            x="pillar",
            y="count",
            color="state",
            barmode="group",
            title="Projects by Pillar — Completed vs Ongoing",
        )
        show_chart(fig)
    else:
        st.info("No data available for pillar chart.")

# ------------------ Top N per Pillar ------------------
st.markdown("---")
st.subheader(f"Top {top_n} Projects per Pillar")

if not data.empty:
    top_df = (
        data.replace({"pillar": {"": "(Unspecified)"}})
        .sort_values(["pillar", "priority", "name"], na_position="last")
        .groupby("pillar", dropna=False, as_index=False)
        .head(top_n)
    )
    show_df(top_df)
else:
    st.info("No projects to display for Top N.")

# ------------------ Roadmap ------------------
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
            gantt, x_start="Start", x_end="Finish", y="name", color="pillar",
            title="Project Timeline"
        )
        roadmap_fig.update_yaxes(autorange="reversed")
        show_chart(roadmap_fig)
    else:
        st.info("No valid date ranges to draw the roadmap.")

# ------------------ Projects Table ------------------
if show_table:
    st.markdown("---")
    st.subheader("Projects")
    show_df(data)

# ------------------ Export Options ------------------
st.markdown("---")
st.subheader("Export Options")

st.download_button(
    "⬇️ Download CSV Report (Filtered)",
    data=data.to_csv(index=False).encode("utf-8"),
    file_name="digital_product_filtered.csv",
    mime="text/csv",
    key="export_csv_filtered",
)

full_df = fetch_all_projects()
st.download_button(
    "🗄️ Download FULL Database (CSV)",
    data=full_df.to_csv(index=False).encode("utf-8"),
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
