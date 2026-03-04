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
    DB column remains plainsware_project; UI label can say "Plainsware Feature?"
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

# Use real label in code; keep backward compatibility with old encoded value
NEW_LABEL = "<New Project>"
NEW_LABEL_OLD = "&lt;New Project&gt;"
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
    # Prefer st.rerun (newer Streamlit) then fall back to experimental_rerun (older).
    try:
        st.rerun()
        return
    except Exception:
        pass
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
    # IMPORTANT: no fallback; isolates this app from other apps/DBs.
    url = (st.secrets.get("SQLITECLOUD_URL_PRODUCT") or "").strip()
    if not url:
        st.error("Missing Streamlit secret: SQLITECLOUD_URL_PRODUCT.")
        st.stop()
    if "YOUR_REAL_API_KEY" in url:
        st.error("SQLITECLOUD_URL_PRODUCT still contains placeholder YOUR_REAL_API_KEY.")
        st.caption(f"Current: {_mask_url(url)}")
        st.stop()
    return url


def _get_sqlitecloud_db() -> str:
    # App 2 DB should be Portfolio (as you said)
    return (st.secrets.get("SQLITECLOUD_DB_PRODUCT") or "Portfolio").strip()


def _validate_db_name(db_name: str) -> bool:
    # Avoid injection; allow typical SQLiteCloud DB names
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", db_name))


@contextmanager
def conn():
    url = _get_sqlitecloud_url()
    c = sqlitecloud.connect(url)
    try:
        db_name = _get_sqlitecloud_db()
        if db_name:
            if not _validate_db_name(db_name):
                st.error("Invalid SQLITECLOUD_DB_PRODUCT. Only letters/digits/._- allowed.")
                st.caption(f"Value: {db_name!r}")
                st.stop()
            c.execute(f'USE DATABASE "{db_name}"')
        yield c
    finally:
        try:
            c.close()
        except Exception:
            pass


def assert_db_awake():
    url = _get_sqlitecloud_url()
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


# ------------------ Cache compatibility (Streamlit 1.12+ safe) ------------------
def _cache_decorator(show_spinner=False):
    # Prefer modern cache_data, fallback to experimental_memo, fallback to cache
    if hasattr(st, "cache_data"):
        return st.cache_data(show_spinner=show_spinner)
    if hasattr(st, "experimental_memo"):
        return st.experimental_memo(show_spinner=show_spinner)
    return st.cache(show_spinner=show_spinner)


def _clear_cached_function(func):
    # Streamlit docs: cached function can be cleared with func.clear() (cache_data) [1](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
    for method in ("clear", "clear_cache"):
        if hasattr(func, method):
            try:
                getattr(func, method)()
                return
            except Exception:
                pass

    # As fallback, clear global cache_data/memo/cache if available [1](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
    for cache_attr in ("cache_data", "experimental_memo", "cache"):
        cache_obj = getattr(st, cache_attr, None)
        if cache_obj is None:
            continue
        for method in ("clear", "clear_cache"):
            if hasattr(cache_obj, method):
                try:
                    getattr(cache_obj, method)()
                    return
                except Exception:
                    pass


# Cache key to prevent cross-db/cross-secret value bleed if you ever change DB targets.
import hashlib
def _db_cache_key() -> str:
    raw = (_get_sqlitecloud_url() + "|" + (_get_sqlitecloud_db() or "")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

_DB_KEY = _db_cache_key()


@_cache_decorator(show_spinner=False)
def distinct_values(col: str, _db_key: str = "") -> List[str]:
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


# ==========================================================
# Editor state helpers
# ==========================================================
def editor_defaults():
    return {
        "editor_name": "",
        "editor_pillar": PRESET_PILLARS[0] if PRESET_PILLARS else "",
        "editor_pillar_new": "",
        "editor_priority": 5,
        "editor_desc": "",
        "editor_owner": "",
        "editor_owner_new": "",
        "editor_status": PRESET_STATUSES[0] if PRESET_STATUSES else "",
        "editor_start": date.today(),
        "editor_due": date.today(),
        "editor_plainsware_project": "No",
        "editor_plainsware_number": "",
    }


def editor_clear_widgets():
    for k, v in editor_defaults().items():
        st.session_state[k] = v


def editor_prime_from_loaded(loaded_row: Optional[dict], pillar_options: List[str], owner_options: List[str], status_list: List[str]):
    # Called BEFORE the form is created
    if not loaded_row:
        editor_clear_widgets()
        return

    st.session_state["editor_name"] = loaded_row.get("name") or ""
    st.session_state["editor_desc"] = loaded_row.get("description") or ""
    st.session_state["editor_priority"] = safe_int(loaded_row.get("priority"), 5)

    # Pillar
    pv = loaded_row.get("pillar") or (pillar_options[0] if pillar_options else "")
    st.session_state["editor_pillar"] = pv if pv in pillar_options else (pillar_options[0] if pillar_options else "")
    st.session_state["editor_pillar_new"] = ""

    # Owner
    ov = loaded_row.get("owner") or (owner_options[0] if owner_options else "")
    st.session_state["editor_owner"] = ov if ov in owner_options else (owner_options[0] if owner_options else "")
    st.session_state["editor_owner_new"] = ""

    # Status
    sv = loaded_row.get("status") or (status_list[0] if status_list else "")
    st.session_state["editor_status"] = sv if sv in status_list else (status_list[0] if status_list else "")

    st.session_state["editor_start"] = try_date(loaded_row.get("start_date")) or date.today()
    st.session_state["editor_due"] = try_date(loaded_row.get("due_date")) or date.today()

    pw = loaded_row.get("plainsware_project", "No") or "No"
    st.session_state["editor_plainsware_project"] = "Yes" if str(pw).strip().lower() == "yes" else "No"
    st.session_state["editor_plainsware_number"] = (loaded_row.get("plainsware_number") or "").strip()


# ==========================================================
# Filter reset pattern (Streamlit-safe)
# ==========================================================
def reset_filters():
    st.session_state["reset_filters_flag"] = True
    _notify("Cleared filters.", "success")


# ------------------ App Boot ------------------
st.set_page_config(page_title=APP_PAGE_TITLE, layout="wide")
st.title(APP_TITLE)

# ✅ APP2 safety lock (must be BEFORE any DB call)
EXPECTED_DB_PATH = "/Portfolio"   # must match your App2 database path exactly

def assert_expected_db():
    path = urlparse(_get_sqlitecloud_url()).path or ""
    if path != EXPECTED_DB_PATH:
        st.error(f"❌ APP2 wrong DB configured. Expected {EXPECTED_DB_PATH}, got {path}")
        st.stop()

assert_expected_db()
assert_db_awake()
ensure_schema()

# ------------------ Session State (safe reset pattern) ------------------
if "Project_selector" not in st.session_state:
    st.session_state.Project_selector = NEW_LABEL

# Backward compatibility: if older encoded label exists, normalize
if st.session_state.Project_selector == NEW_LABEL_OLD:
    st.session_state.Project_selector = NEW_LABEL

if "reset_project_selector" not in st.session_state:
    st.session_state.reset_project_selector = False

if "last_loaded_feature_id" not in st.session_state:
    st.session_state.last_loaded_feature_id = None

if "reset_filters_flag" not in st.session_state:
    st.session_state.reset_filters_flag = False

# ✅ Owner persistence after save (fix)
if "owner_after_save" not in st.session_state:
    st.session_state.owner_after_save = ""

if "apply_owner_after_save" not in st.session_state:
    st.session_state.apply_owner_after_save = False

# apply reset BEFORE widget is created
if st.session_state.reset_project_selector:
    st.session_state.Project_selector = NEW_LABEL
    st.session_state.reset_project_selector = False
    st.session_state.last_loaded_feature_id = None
    editor_clear_widgets()

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
current_feature_id = None

if selected_Project != NEW_LABEL:
    try:
        current_feature_id = int(selected_Project.split(" — ", 1)[0])
        with conn() as c:
            df = pd.read_sql_query(f'SELECT * FROM "{TABLE}" WHERE id=?', c, params=[current_feature_id])
        loaded_Project = df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        loaded_Project = None
        current_feature_id = None

# Pull lists (cached)
status_from_db = distinct_values("status", _DB_KEY)
status_list = sorted(set(PRESET_STATUSES) | set(status_from_db))
owner_list = distinct_values("owner", _DB_KEY)

bcol1, bcol2, bcol3 = st.columns([1, 1, 1])
new_clicked = bcol1.button("New", key="btn_new_project")
clear_editor_clicked = bcol2.button("Clear Editor", key="btn_clear_editor")
bcol3.button("Clear Filters", key="btn_clear_filters", on_click=reset_filters)

if new_clicked:
    st.session_state.reset_project_selector = True
    editor_clear_widgets()
    _rerun()

if clear_editor_clicked:
    editor_clear_widgets()
    _rerun()

# ------------------ FORM ------------------
pillar_from_db = distinct_values("pillar", _DB_KEY)
pillar_options = sorted(set(PRESET_PILLARS) | set(pillar_from_db)) or [""]

# owner options for editor selectbox
owner_options = owner_list[:] if owner_list else [""]

# ✅ Apply owner after save BEFORE widgets render (prevents “must retype”) [3](https://discuss.streamlit.io/t/how-to-reset-selectbox-options-after-submitting/33573)[1](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
if st.session_state.apply_owner_after_save:
    st.session_state["editor_owner"] = st.session_state.owner_after_save
    st.session_state["editor_owner_new"] = ""
    st.session_state.apply_owner_after_save = False

# Defensive: ensure selected owner exists in dropdown options
desired_owner = (st.session_state.get("editor_owner") or "").strip()
if desired_owner and desired_owner not in owner_options:
    owner_options = sorted(list(set(owner_options + [desired_owner])))

# prime editor widget keys when selection changes (BEFORE form widgets render)
if current_feature_id != st.session_state.last_loaded_feature_id:
    if current_feature_id is None:
        editor_clear_widgets()
    else:
        editor_prime_from_loaded(loaded_Project, pillar_options, owner_options, status_list)
    st.session_state.last_loaded_feature_id = current_feature_id

with st.form("Project_form"):
    c1, c2 = st.columns(2)

    name_val = loaded_Project.get("name") if loaded_Project else ""
    priority_val = int(loaded_Project.get("priority", 5)) if loaded_Project else 5
    status_val = loaded_Project.get("status") if loaded_Project else "Planned"
    start_val = try_date(loaded_Project.get("start_date")) if loaded_Project else date.today()
    due_val = try_date(loaded_Project.get("due_date")) if loaded_Project else date.today()
    desc_val = loaded_Project.get("description") if loaded_Project else ""

    pw_val = loaded_Project.get("plainsware_project", "No") if loaded_Project else "No"
    pw_num_val = loaded_Project.get("plainsware_number") if loaded_Project else None

    with c1:
        Project_name = st.text_input("Name*", value=name_val, key="editor_name")

        pillar_index = pillar_options.index(st.session_state.get("editor_pillar", pillar_options[0] if pillar_options else "")) \
            if (pillar_options and st.session_state.get("editor_pillar") in pillar_options) else 0

        Project_pillar = st.selectbox(
            "Digital Product*",
            options=pillar_options,
            index=pillar_index,
            key="editor_pillar",
        )

        new_pillar = st.text_input(
            "Or type a new Digital Product (optional)",
            value="",
            key="editor_pillar_new",
        )
        if new_pillar.strip():
            Project_pillar = new_pillar.strip()

        Project_priority = st.number_input(
            "Priority",
            min_value=1,
            max_value=99,
            value=int(st.session_state.get("editor_priority", priority_val)),
            step=1,
            format="%d",
            key="editor_priority",
        )
        description = st.text_area("Description", value=desc_val, height=120, key="editor_desc")

    with c2:
        owner_index = owner_options.index(st.session_state.get("editor_owner", owner_options[0] if owner_options else "")) \
            if (owner_options and st.session_state.get("editor_owner") in owner_options) else 0

        Project_owner = st.selectbox("Owner*", options=owner_options, index=owner_index, key="editor_owner")

        new_owner = st.text_input("Or type a new Owner (optional)", value="", key="editor_owner_new")
        if new_owner.strip():
            Project_owner = new_owner.strip()

        Project_status = st.selectbox(
            "Status",
            status_list,
            index=safe_index(status_list, st.session_state.get("editor_status", status_val)),
            key="editor_status"
        )

        start_date = st.date_input("Start Date", value=st.session_state.get("editor_start", start_val), key="editor_start")
        due_date = st.date_input("Due Date", value=st.session_state.get("editor_due", due_val), key="editor_due")

        plainsware_project = st.selectbox(
            "Plainsware Feature?",
            ["No", "Yes"],
            index=1 if str(st.session_state.get("editor_plainsware_project", pw_val)).strip() == "Yes" else 0,
            key="editor_plainsware_project",
        )

        plainsware_number = None
        if plainsware_project == "Yes":
            default_num = str(pw_num_val).strip() if pw_num_val is not None else ""
            plainsware_number = st.text_input(
                "Planisware Feature Number (JJMD-0079575)*",
                value=default_num,
                placeholder="JJMD-0079575",
                key="editor_plainsware_number",
            )
            if plainsware_number.strip() and not JJMD_PATTERN.fullmatch(plainsware_number.strip()):
                st.warning("Format must be JJMD-0079575 (JJMD- + 7 digits).")

    col_a, col_b, col_c = st.columns(3)
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
            new_id = None
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
                # Try best way to get inserted ID (depends on sqlitecloud SDK)
                try:
                    new_id = getattr(c, "lastrowid", None)
                except Exception:
                    new_id = None

                if not new_id:
                    df_new = pd.read_sql_query(
                        f'SELECT id FROM "{TABLE}" WHERE name=? AND created_at=? ORDER BY id DESC LIMIT 1',
                        c,
                        params=[Project_name_clean, ts],
                    )
                    if not df_new.empty:
                        new_id = int(df_new.iloc[0]["id"])

            # ✅ Clear cached distinct values so new owner appears immediately [1](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
            _clear_cached_function(distinct_values)

            # ✅ Keep owner selected after rerun
            st.session_state.owner_after_save = Project_owner_clean
            st.session_state.apply_owner_after_save = True

            # ✅ Keep the newly created project selected (don’t lose loaded info)
            if new_id:
                st.session_state.Project_selector = f"{new_id} — {Project_name_clean}"
                st.session_state.last_loaded_feature_id = int(new_id)

            _notify("✅ Feature created successfully!", "success")
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

                # ✅ Clear cached distinct values so edited/new owner appears immediately [1](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
                _clear_cached_function(distinct_values)

                # ✅ Keep owner selected after rerun
                st.session_state.owner_after_save = Project_owner_clean
                st.session_state.apply_owner_after_save = True

                # ✅ Keep same project selected (don’t lose loaded info)
                st.session_state.Project_selector = f"{int(loaded_Project['id'])} — {Project_name_clean}"
                st.session_state.last_loaded_feature_id = int(loaded_Project["id"])

                _notify("✅ Feature updated!", "success")
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

            # Clear cached lists (owner/status/pillar could change)
            _clear_cached_function(distinct_values)  # [1](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)

            _notify("Feature deleted.", "warning")
            st.session_state.Project_selector = NEW_LABEL
            st.session_state.last_loaded_feature_id = None
            editor_clear_widgets()
            _rerun()
        except Exception as e:
            st.error(f"Delete error: {e}")
            st.stop()

# ==========================================================
# Filters + Clear Filters works reliably
# ==========================================================
st.markdown("---")
st.subheader("Filters")

# Apply reset BEFORE filter widgets are created
if st.session_state.reset_filters_flag:
    st.session_state["pillar_f"] = ALL_LABEL
    st.session_state["status_f"] = ALL_LABEL
    st.session_state["owner_f"] = ALL_LABEL
    st.session_state["priority_f"] = ALL_LABEL
    st.session_state["plainsware_f"] = ALL_LABEL
    st.session_state["search_f"] = ""
    st.session_state.reset_filters_flag = False

# Ensure filter keys exist
for k, v in {
    "pillar_f": ALL_LABEL,
    "status_f": ALL_LABEL,
    "owner_f": ALL_LABEL,
    "priority_f": ALL_LABEL,
    "plainsware_f": ALL_LABEL,
    "search_f": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

colF1, colF2, colF3, colF4, colF5, colF6 = st.columns([1, 1, 1, 1, 1, 2])

pillars = [ALL_LABEL] + sorted(set(PRESET_PILLARS) | set(distinct_values("pillar", _DB_KEY)))
owners = [ALL_LABEL] + distinct_values("owner", _DB_KEY)
statuses = [ALL_LABEL] + status_list

priority_vals: List[int] = []
try:
    pv = distinct_values("priority", _DB_KEY)
    priority_vals = sorted({int(x) for x in pv if str(x).strip().isdigit()})
except Exception:
    pass

priority_opts = [ALL_LABEL] + [str(x) for x in priority_vals]
plainsware_opts = [ALL_LABEL, "Yes", "No"]

pillar_f = colF1.selectbox("Digital Product", pillars, key="pillar_f")
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

# ==========================================================
# KPI Cards
# ==========================================================
st.markdown("---")
st.subheader("Key Metrics")

if data.empty:
    st.info("No data available for KPIs (check Filters).")
else:
    total_items = len(data)
    completed = (data["status"].apply(status_to_state) == "Completed").sum()
    ongoing = (data["status"].apply(status_to_state) != "Completed").sum()
    dp_count = data["pillar"].replace("", pd.NA).dropna().nunique()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Features", int(total_items))
    k2.metric("Completed", int(completed))
    k3.metric("Ongoing", int(ongoing))
    k4.metric("Distinct Digital Products", int(dp_count))

# ==========================================================
# Chart: Completed vs Ongoing
# ==========================================================
st.markdown("---")
st.subheader("Projects by Digital Product — Completed vs Ongoing")

if not data.empty:
    status_df = data.copy()
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
        title="Projects by Digital Product — Completed vs Ongoing",
        labels={"pillar": "Digital Product", "count": "Count", "state": "State"},
    )
    show_chart(fig)
else:
    st.info("No data available for chart (check Filters).")

# ==========================================================
# Top N
# ==========================================================
st.markdown("---")
st.subheader("Top Projects per Digital Product")

top_n = st.slider("Top N per Digital Product", min_value=1, max_value=10, value=5, key="top_n")

if not data.empty:
    top_df = (
        data.replace({"pillar": {"": "(Unspecified)"}})
        .sort_values(["pillar", "priority", "name"], na_position="last")
        .groupby("pillar", dropna=False, as_index=False)
        .head(top_n)
    )
    top_df_display = top_df.rename(columns={"pillar": "Digital Product"})
    show_df(top_df_display)
else:
    st.info("No projects to display for Top N.")

# ==========================================================
# Roadmap
# ==========================================================
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
        labels={"pillar": "Digital Product"},
    )
    roadmap_fig.update_yaxes(autorange="reversed")
    show_chart(roadmap_fig)
else:
    st.info("No valid date ranges to draw the roadmap.")

# ==========================================================
# Export Options
# ==========================================================
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
