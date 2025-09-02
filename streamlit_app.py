import streamlit as st
from pathlib import Path
import json
from calculator_engine import compute, apply_ui_group_answers
from ui_renderer import render_step, render_ui_groups

JSON_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"

# Cache JSON loading for performance
@st.cache_data
def _read_json(path: str):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        st.error(f"Error loading {path}: {e}")
        return {}

@st.cache_data
def load_spec_with_overlay(base_path: str, overlay_path: str | None = None):
    spec = _read_json(base_path)
    if overlay_path and Path(overlay_path).exists():
        overlay = _read_json(overlay_path)
        st.debug(f"Applied overlay: {overlay_path}")
        if overlay.get("modules"):
            spec["modules"] = overlay["modules"]
        overrides = overlay.get("ui_group_overrides", {})
        gid_to_group = {g["id"]: g for g in spec.get("ui_groups", [])}
        for gid, ov in overrides.items():
            g = gid_to_group.get(gid)
            if not g:
                continue
            if "module" in ov:
                g["module"] = ov["module"]
            field_ovs = ov.get("field_overrides", {})
            wildcard = field_ovs.get("*", {})
            for f in g.get("fields", []):
                label = f.get("label", f["field"])
                this_ov = field_ovs.get(label, {})
                for k, v in wildcard.items():
                    f.setdefault(k, v)
                for k, v in this_ov.items():
                    f[k] = v
        for g in spec.get("ui_groups", []):
            for f in g.get("fields", []):
                kind = f.get("kind", "currency")
                f.setdefault("optional", True)
                if kind == "currency":
                    f.setdefault("skip_value", 0)
                elif kind == "boolean":
                    f.setdefault("skip_value", "No")
                else:
                    f.setdefault("skip_value", None)
    return spec

# Initialize session state
if 'flow_state' not in st.session_state:
    st.session_state.flow_state = {
        'current_step': 'entry_mode',
        'answers': {},
        'mode': 'care_only',
        'audience': 'self'
    }

# Main app
st.set_page_config(page_title="Senior Care Cost Wizard", page_icon="🧭", layout="centered")
spec = load_spec_with_overlay(JSON_PATH, OVERLAY_PATH)
simulation_mode = st.checkbox("Simulation Mode", value=spec['features'].get('simulation_mode', True))

# Progress bar
steps = list(spec['user_flow'].keys())
current_step_idx = steps.index(st.session_state.flow_state['current_step'])
st.progress(min(current_step_idx / len(steps), 1.0))

# Render current step or results
if st.session_state.flow_state['current_step'] in spec['user_flow']:
    render_step(spec, st.session_state.flow_state, simulation_mode)
else:
    # Collect grouped answers and compute
    grouped_answers = st.session_state.flow_state.get('grouped_answers', {})
    flat_inputs = apply_ui_group_answers(spec['ui_groups'], grouped_answers)
    results = compute(spec, flat_inputs)
    
    # Display results
    result_config = spec['ui_guidance']['results']['simulation_mode' if simulation_mode else 'end_user'][spec['features']['flow_mode']]
    st.header("Results")
    for field in result_config['fields']:
        label = result_config.get('labels', {}).get(field, field.replace('_', ' ').title())
        value = results.get(field, 'N/A')
        if isinstance(value, (int, float)):
            value = f"${value:,.2f}"
        st.write(f"{label}: {value}")
    
    if simulation_mode and result_config.get('show_breakdown_tables'):
        for table in ['care_breakdown', 'home_carry_breakdown', 'optional_costs_breakdown']:
            if table in spec['calculation_logic']['debug_tables']:
                st.subheader(f"{table.replace('_', ' ').title()}")
                table_data = {k: results.get(k, flat_inputs.get(k, 0)) for k in spec['calculation_logic']['debug_tables'][table]}
                st.dataframe(table_data, use_container_width=True)