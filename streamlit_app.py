# ------------------ Project Editor ------------------
st.markdown("---")
st.subheader("Feature Editor")  # ✅ text only

with conn() as c:
    df_projects = pd.read_sql_query(f"SELECT id, name FROM {TABLE} ORDER BY name", c)

Project_options = [NEW_LABEL] + [f"{row['id']} — {row['name']}" for _, row in df_projects.iterrows()]

selected_Project = st.selectbox(
    "Select Feature to Edit",  # ✅ text only
    Project_options,
    index=safe_index(Project_options, st.session_state.Project_selector),
    key="Project_selector",
)

loaded_Project = None
if selected_Project != NEW_LABEL:
    try:
        Project_id = int(selected_Project.split(" — ", 1)[0])
        with conn() as c:
            df = pd.read_sql_query(f"SELECT * FROM {TABLE} WHERE id=?", c, params=[Project_id])
        loaded_Project = df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        loaded_Project = None

# ------------------ Form ------------------
with st.form("Feature_form"):  # ✅ text only
    c1, c2 = st.columns(2)

    name_val = loaded_Project.get("name") if loaded_Project else ""
    pillar_val = loaded_Project.get("pillar") if loaded_Project else ""
    priority_val = int(loaded_Project.get("priority", 5)) if loaded_Project else 5
    owner_val = loaded_Project.get("owner") if loaded_Project else ""
    status_val = loaded_Project.get("status") if loaded_Project else "Planned"
    desc_val = loaded_Project.get("description") if loaded_Project else ""

    with c1:
        Project_name = st.text_input("Name*", value=name_val)

        pillar = st.selectbox(
            "Digital Product*",  # ✅ text only
            options=pillar_options,
            index=safe_index(pillar_options, pillar_val),
        )

        new_pillar = st.text_input(
            "Or type a new Digital Product (optional)"  # ✅ text only
        )
        if new_pillar.strip():
            pillar = new_pillar.strip()

        priority = st.number_input(
            "Priority", min_value=1, max_value=99, value=priority_val, step=1
        )

        description = st.text_area("Description", value=desc_val)

    with c2:
        owner = st.selectbox("Owner*", owner_options, index=safe_index(owner_options, owner_val))
        status = st.selectbox("Status", status_list, index=safe_index(status_list, status_val))

    col_a, col_b = st.columns(2)
    submitted_new = col_a.form_submit_button("Save Feature")     # ✅ text only
    submitted_update = col_b.form_submit_button("Update Feature")  # ✅ text only
