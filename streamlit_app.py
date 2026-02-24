# ----------------------------------------------------------
# Digital Product Portfolio — SQLite Cloud Version
# Streamlit 1.12 compatible (uses st.experimental_rerun)
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

def validate_plainsware(plainsware_project: str, plainsware_number: Any) -> Optional[str]:
    """
    DB column remains plainsware_project; on the form we label it as "Plainsware Feature?"
    """
    if str(plainsware_project).strip().lower() == "yes":
        if plainsware_number is None or not str(plainsware_number).strip():
            raise ValueError("Planisware Feature Number must be entered when Plainsware Feature is Yes.")
        value = str(plainsware_number).strip().upper()
        if not JJMD_PATTERN.fullmatch(value):
            raise ValueError("Planisware Feature Number must be in the format JJMD-0079575 (JJMD- + 7 digits).")
        return value
    return None

# ------------------ App Identity ------------------
APP_TITLE = "Digital Product — Web Version"
APP_PAGE_TITLE = "Digital Product Portfolio"

# Keep your existing schema/table naming
TABLE = "Projects"
NEW_LABEL = "<New Project>"
ALL_LABEL = "All"

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

PRESET_STATUSES = ["Planned", "In Progress", "Completed", "On Hold"]

def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ------------------ Streamlit helpers ------------------
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
        st.error("SQLITECLOUD_URL_PRODUCT still contains placeholder YOUR_REAL_API_KEY.")
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

# ------------------ Minimal schema ensure (safe; no migrations/rebuild) ------------------
def ensure_schema() -> None:
    """
    Create the table if it doesn't exist.
    Does NOT rename/alter existing working schemas.
    """
    with conn() as c:
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{TABLE}" (
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

# ------------------ Misc helpers ------------------
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
            f"""
            SELECT DISTINCT "{col}" AS v
            FROM "{TABLE}"
            WHERE "{col}" IS NOT NULL AND TRIM("{col}") <> ''
            ORDER BY v
            """,
            c,
        )
    return df["v"].dropna().astype(str).tolist()

def fetch_df(filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    q = f'SELECT * FROM "{TABLE}"'
    args: List[Any] = []
    where: List[str] = []

    if filters:
        for col in ["pillar", "status", "owner"]:
            if filters.get(col) and filters[col] != ALL_LABEL:
                where.append(f'"{col}" = ?')
                args.append(filters[col])

        if filters.get("plainsware") and filters["plainsware"] != ALL_LABEL:
            where.append('"plainsware_project" = ?')
            args.append(filters["plainsware"])

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

def fetch_all_projects() -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(f'SELECT * FROM "{TABLE}" ORDER BY id', c)

# ------------------ PDF Export ------------------
def build_pdf_report(df: pd.DataFrame, title: str = "Report") -> bytes:
    if not REPORTLAB_AVAILABLE:
        return b""
    buffer = io.BytesIO()
    cpdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    cpdf.setFont("Helvetica-Bold", 14)
    cpdf.drawString(40, height - 40, title)

    cpdf.setFont("Helvetica", 9)
    y = height - 70

    cols = ["id", "name", "pillar", "priority", "owner", "status",
            "start_date", "due_date", "plainsware_project", "plainsware_number"]
    cpdf.drawString(40, y, " | ".join(cols))
    y -= 14

    for _, row in df.iterrows():
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
    st.session_state["pillar_f"] = ALL_LABEL
    st.session_state["status_f"] = ALL_LABEL
    st.session_state["owner_f"] = ALL_LABEL
    st.session_state["priority_f"] = ALL_LABEL
    st.session_state["plainsware_f"] = ALL_LABEL
    st.session_state["search_f"] = ""
    _notify("Cleared filters.", "success")

# ------------------ App Boot ------------------
st.set_page_config(page_title=APP_PAGE_TITLE, layout="wide")
st.title(APP_TITLE)

assert_db_awake()
ensure_schema()

# ------------------ Session State (safe reset pattern) ------------------
if "Project_selector" not in st.session_state:
    st.session_state.Project_selector = NEW_LABEL

# IMPORTANT: reset flag to avoid "cannot modify after widget instantiated"
if "reset_project_selector" not in st.session_state:
    st.session_state.reset_project_selector = False

# Apply reset BEFORE widget is created
if st.session_state.reset_project_selector:
    st.session_state.Project_selector = NEW_LABEL
    st.session_state.reset_project_selector = False

# ------------------ Feature Editor ------------------
st.markdown("---")
st.subheader("Feature Editor")

with conn() as c:
    df_projects = pd.read_sql_query(f'SELECT id, name FROM "{TABLE}" ORDER BY name', c)

Project_options = [NEW_LABEL] + [f"{row['id']} — {row['name']}" for _, row in df_projects.iterrows()]

selected_Project = st.selectbox(
    "Select Feature to Edit",
    Project_options,
    index=safe_index(Project_options, st.session_state.Project_selector),
    key="Project_selector",
)

loaded_Project = None
if selected_Project != NEW_LABEL:
    try:
        Project_id = int(selected_Project.split(" — ", 1)[0])
        with conn() as c:
            df = pd.read_sql_query(f'SELECT * FROM "{TABLE}" WHERE id=?', c, params=[Project_id])
        loaded_Project = df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        loaded_Project = None

status_from_db = distinct_values("status")
status_list = sorted(set(PRESET_STATUSES) | set(status_from_db))
owner_list = distinct_values("owner")

bcol1, bcol2 = st.columns([1, 1])
new_clicked = bcol1.button("New", key="btn_new_project")
bcol2.button("Clear Filters", key="btn_clear_filters", on_click=reset_filters)

if new_clicked:
    st.session_state.reset_project_selector = True
    _rerun()

# ------------------ FORM (ONLY wording changes applied here) ------------------
pillar_from_db = distinct_values("pillar")
pillar_options = sorted(set(PRESET_PILLARS) | set(pillar_from_db)) or [""]

with st.form("Project_form"):
    c1, c2 = st.columns(2)

    name_val = loaded_Project.get("name") if loaded_Project else ""
    pillar_val = loaded_Project.get("pillar") if loaded_Project else (pillar_options[0] if pillar_options else "")
    priority_val = int(loaded_Project.get("priority", 5)) if loaded_Project else 5
    owner_val = loaded_Project.get("owner") if loaded_Project else ""
    status_val = loaded_Project.get("status") if loaded_Project else "Planned"
    start_val = try_date(loaded_Project.get("start_date")) if loaded_Project else date.today()
    due_val = try_date(loaded_Project.get("due_date")) if loaded_Project else date.today()
    desc_val = loaded_Project.get("description") if loaded_Project else ""

    pw_val = loaded_Project.get("plainsware_project", "No") if loaded_Project else "No"
    pw_num_val = loaded_Project.get("plainsware_number") if loaded_Project else None

    with c1:
        Project_name = st.text_input("Name*", value=name_val, key="editor_name")

        pillar_index = pillar_options.index(pillar_val) if pillar_val in pillar_options else 0

        # ✅ FORM change: "Pillar" -> "Digital Product"
        Project_pillar = st.selectbox(
            "Digital Product*",
            options=pillar_options,
            index=pillar_index,
            key="editor_pillar",
        )

        # ✅ FORM change: "Pillar" -> "Digital Product"
        new_pillar = st.text_input(
            "Or type a new Digital Product (optional)",
            value="",
            key="editor_pillar_new",
        )
        if new_pillar.strip():
            Project_pillar = new_pillar.strip()

        Project_priority = st.number_input(
            "Priority", min_value=1, max_value=99, value=int(priority_val),
            step=1, format="%d", key="editor_priority"
        )
        description = st.text_area("Description", value=desc_val, height=120, key="editor_desc")

    with c2:
        owner_options = owner_list[:] if owner_list else [""]
        owner_index = owner_options.index(owner_val) if owner_val in owner_options else 0
        Project_owner = st.selectbox("Owner*", options=owner_options, index=owner_index, key="editor_owner")

        new_owner = st.text_input("Or type a new Owner (optional)", value="", key="editor_owner_new")
        if new_owner.strip():
            Project_owner = new_owner.strip()

        Project_status = st.selectbox("Status", status_list, index=safe_index(status_list, status_val), key="editor_status")
        start_date = st.date_input("Start Date", value=start_val, key="editor_start")
        due_date = st.date_input("Due Date", value=due_val, key="editor_due")

        # ✅ FORM change: "Project" -> "Feature"
        plainsware_project = st.selectbox(
            "Plainsware Feature?",
            ["No", "Yes"],
            index=1 if str(pw_val).strip() == "Yes" else 0,
            key="editor_plainsware_project",
        )

        plainsware_number = None
        if plainsware_project == "Yes":
            default_num = str(pw_num_val).strip() if pw_num_val is not None else ""
            # ✅ FORM change: "Project" -> "Feature"
            plainsware_number = st.text_input(
                "Planisware Feature Number (JJMD-0079575)*",
                value=default_num,
                placeholder="JJMD-0079575",
                key="editor_plainsware_number",
            )
            if plainsware_number.strip() and not JJMD_PATTERN.fullmatch(plainsware_number.strip()):
                st.warning("Format must be JJMD-0079575 (JJMD- + 7 digits).")

    col_a, col_b, col_c = st.columns(3)
    # ✅ FORM change: "Project" -> "Feature"
    submitted_new = col_a.form_submit_button("Save New Feature")
    submitted_update = col_b.form_submit_button("Update Feature")
    submitted_delete = col_c.form_submit_button("Delete")

# ------------------ CRUD ------------------
if submitted_new:
    errors = []
    Project_name_clean = _clean(Project_name)
    Project_pillar_clean = _clean(Project_pillar)
    Project_owner_clean = _clean(Project_owner)
    Project_status_clean = _clean(Project_status)
    safe_priority_val = safe_int(Project_priority, default=5)

    if not Project_name_clean:
        errors.append("Name is required.")
    if not Project_pillar_clean:
        errors.append("Digital Product is required.")  # ✅ aligns with form label
    if not Project_owner_clean:
        errors.append("Owner is required.")

    pw_number_db = None
    if plainsware_project == "Yes":
        try:
            pw_number_db = validate_plainsware(plainsware_project, plainsware_number)
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
                    (name, pillar, priority, description, owner, status, start_date, due_date,
                     plainsware_project, plainsware_number, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        Project_name_clean,
                        Project_pillar_clean,
                        safe_priority_val,
                        _clean(description),
                        Project_owner_clean,
                        Project_status_clean,
                        to_iso(start_date),
                        to_iso(due_date),
                        plainsware_project,
                        pw_number_db,
                        ts,
                        ts,
                    ),
                )
            _notify("✅ Feature created successfully!", "success")
            st.session_state.reset_project_selector = True
            _rerun()
        except Exception as e:
            st.error(f"Save error: {e}")
            st.stop()

if submitted_update:
    if not loaded_Project:
        st.warning("Select an existing Feature to update.")
    else:
        errors = []
        Project_name_clean = _clean(Project_name)
        Project_pillar_clean = _clean(Project_pillar)
        Project_owner_clean = _clean(Project_owner)
        Project_status_clean = _clean(Project_status)
        safe_priority_val = safe_int(Project_priority, default=5)

        if not Project_name_clean:
            errors.append("Name is required.")
        if not Project_pillar_clean:
            errors.append("Digital Product is required.")
        if not Project_owner_clean:
            errors.append("Owner is required.")

        pw_number_db = None
        if plainsware_project == "Yes":
            try:
                pw_number_db = validate_plainsware(plainsware_project, plainsware_number)
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
                        SET name=?, pillar=?, priority=?, description=?, owner=?, status=?, start_date=?, due_date=?,
                            plainsware_project=?, plainsware_number=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            Project_name_clean,
                            Project_pillar_clean,
                            safe_priority_val,
                            _clean(description),
                            Project_owner_clean,
                            Project_status_clean,
                            to_iso(start_date),
                            to_iso(due_date),
                            plainsware_project,
                            pw_number_db,
                            ts,
                            int(loaded_Project["id"]),
                        ),
                    )
                _notify("✅ Feature updated!", "success")
                st.session_state.reset_project_selector = True
                _rerun()
            except Exception as e:
                st.error(f"Update error: {e}")
                st.stop()

if submitted_delete:
    if not loaded_Project:
        st.warning("Select an existing Feature to delete.")
    else:
        try:
            with conn() as c:
                c.execute(f'DELETE FROM "{TABLE}" WHERE id=?', (int(loaded_Project["id"]),))
            _notify("Feature deleted.", "warning")
            st.session_state.reset_project_selector = True
            _rerun()
        except Exception as e:
            st.error(f"Delete error: {e}")
            st.stop()

# ==========================================================
# ✅ FILTERS SECTION (RESTORED — this is what you asked for)
# ==========================================================
st.markdown("---")
st.subheader("Filters")

colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

pillars = [ALL_LABEL] + sorted(set(PRESET_PILLARS) | set(distinct_values("pillar")))
owners = [ALL_LABEL] + distinct_values("owner")
statuses = [ALL_LABEL] + status_list

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

# ------------------ KPI Cards ------------------
st.markdown("---")
st.subheader("Key Metrics")

if data.empty:
    st.info("No data available for KPIs (check Filters).")
else:
    total_features = len(data)
    completed = (data["status"].apply(status_to_state) == "Completed").sum()
    ongoing = (data["status"].apply(status_to_state) != "Completed").sum()
    pillar_count = data["pillar"].replace("", pd.NA).dropna().nunique()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Features", int(total_features))
    k2.metric("Completed", int(completed))
    k3.metric("Ongoing", int(ongoing))
    k4.metric("Distinct Pillars", int(pillar_count))

# ------------------ Chart: Completed vs Ongoing ------------------
st.markdown("---")
st.subheader("Projects by Digital Product — Completed vs Ongoing")

fig = px.bar(
    pillar_summary,
    x="pillar",  # ✅ KEEP column name
    y="count",
    color="state",
    barmode="group",
    title="Projects by Digital Product — Completed vs Ongoing",
    labels={
        "pillar": "Digital Product",
        "count": "Count",
        "state": "State",
    },
)
    show_chart(fig)
else:
    st.info("No data available for chart (check Filters).")

# ------------------ Top N ------------------
st.markdown("---")
st.subheader("Top Projects per Digital Product")

top_n = st.slider("Top N per Pillar", min_value=1, max_value=10, value=5, key="top_n")

if not data.empty:
top_df_display = top_df.rename(columns={"pillar": "Digital Product"})
show_df(top_df_display)
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
        color="pillar",
        title="Project Timeline",
    )
    roadmap_fig.update_yaxes(autorange="reversed")
    show_chart(roadmap_fig)
else:
    st.info("No valid date ranges to draw the roadmap.")

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


