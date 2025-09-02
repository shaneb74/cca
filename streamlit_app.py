import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import streamlit as st

JSON_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"  # optional

# ---------- Helpers ----------
def money(x):
    try:
        return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0

def _read_json(path: str):
    try:
        with Path(path).open('r', encoding='utf-8') as f:
            return json.loads(f.read())
    except json.JSONDecodeError as e:
        st.error(f"Error decoding JSON file {path}: {str(e)}")
        return {}

def load_spec_with_overlay(base_path: str, overlay_path: str | None = None):
    spec = _read_json(base_path)
    if not spec:
        st.error(f"Failed to load base spec from {base_path}")
        return {}
    if overlay_path and Path(overlay_path).exists():
        overlay = _read_json(overlay_path)
        if not overlay:
            st.warning(f"Failed to load overlay from {overlay_path}, proceeding with base spec")
        else:
            if overlay.get("lookups"):
                spec.setdefault("lookups", {}).update(overlay["lookups"])
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

def apply_ui_group_answers(groups_cfg, grouped_answers, existing_fields=None):
    flat = dict(existing_fields or {})
    groups = {g["id"]: g for g in groups_cfg}
    for gid, answers in grouped_answers.items():
        cfg = groups.get(gid)
        if not cfg:
            continue
        cond = cfg.get("condition")
        if cond and flat.get(cond.get("field")) != cond.get("equals"):
            continue
        for f in cfg["fields"]:
            field_name = f["field"]
            label = f.get("label", f["field"])
            kind = f.get("kind", "currency")
            default = f.get("default", 0)
            raw_val = answers.get(label)
            if raw_val is None:
                raw_val = answers.get(field_name, default)
            value = raw_val
            if kind == "currency":
                try:
                    flat[field_name] = float(value)
                except Exception:
                    flat[field_name] = 0.0
            elif kind == "boolean":
                truthy = {"yes","y","true","1",True,1}
                is_true = str(value).strip().lower() in truthy if not isinstance(value,bool) else value
                flat[field_name] = f.get("true_value","Yes") if is_true else f.get("false_value","No")
            elif kind == "select":
                flat[field_name] = value
            else:
                flat[field_name] = value
    return flat

def compute(spec, inputs):
    settings = spec.get("settings", {})
    lookups = spec.get("lookups", {})
    def per_person_cost(person):
        care_type = inputs.get(f"care_type_person_{person}")
        care_level = inputs.get(f"care_level_person_{person}")
        mobility = inputs.get(f"mobility_person_{person}")
        chronic = inputs.get(f"chronic_person_{person}")
        care_level_add = lookups.get("care_level_adders", {}).get(care_level, 0)
        mobility_fac = lookups.get("mobility_adders", {}).get("facility", {}).get(mobility, 0)
        mobility_home = lookups.get("mobility_adders", {}).get("in_home", {}).get(mobility, 0)
        chronic_add = lookups.get("chronic_adders", {}).get(chronic, 0)
        state_mult = lookups.get("state_multipliers", {}).get(inputs.get("state", "National"), 1.0)
        if care_type == "In-Home Care (professional staff such as nurses, CNAs, or aides)":
            hours = str(inputs.get(f"hours_per_day_person_{person}", "0"))
            hourly = lookups.get("in_home_care_matrix", {}).get(hours, 0)
            in_home_cost = hourly * settings.get("days_per_month", 30) + mobility_home + chronic_add
            return money(in_home_cost * state_mult)
        elif care_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room_type = inputs.get(f"room_type_person_{person}")
            base_room = lookups.get("room_type", {}).get(room_type, 0)
            if care_type == "Memory Care":
                base_room *= settings.get("memory_care_multiplier", 1.2)
            facility_cost = base_room + care_level_add + mobility_fac + chronic_add
            return money(facility_cost * state_mult)
        return 0.0

    def shared_unit_adjustment():
        if not (inputs.get("person_a_in_care") and inputs.get("person_b_in_care")):
            return 0.0
        if not inputs.get("share_one_unit"):
            return 0.0
        a_type = inputs.get("care_type_person_a")
        b_type = inputs.get("care_type_person_b")
        facility_types = ["Assisted Living (or Adult Family Home)", "Memory Care"]
        if (a_type in facility_types) and (b_type in facility_types):
            room_type_b = inputs.get("room_type_person_b")
            room_base_b = lookups.get("room_type", {}).get(room_type_b, 0)
            if b_type == "Memory Care":
                room_base_b *= settings.get("memory_care_multiplier", 1.2)
            return money(room_base_b - settings.get("second_person_cost", 1500))
        return 0.0

    a_selected = per_person_cost("a") if inputs.get("person_a_in_care") else 0.0
    b_selected = per_person_cost("b") if inputs.get("person_b_in_care") else 0.0
    shared_adj = shared_unit_adjustment()
    care_cost_total = money(a_selected + b_selected - shared_adj)
    optional_fields = ["optional_rx","optional_personal_care","optional_phone_internet","optional_life_insurance",
                       "optional_transportation","optional_family_travel","optional_auto","optional_auto_insurance",
                       "optional_other","heloc_payment_monthly", "medicare_premiums", "dental_vision_hearing",
                       "home_modifications_monthly", "other_debts_monthly", "pet_care", "entertainment_hobbies"]
    optional_sum = sum(inputs.get(k, 0.0) for k in optional_fields)
    home_fields = ["mortgage","taxes","insurance","hoa","utilities"]
    home_sum = sum(inputs.get(k, 0.0) for k in home_fields)
    house_cost_total = home_sum if inputs.get("maintain_home_household") else 0.0
    va_total = inputs.get("va_benefit_person_a", 0.0) + inputs.get("va_benefit_person_b", 0.0)
    ltc_total = (settings.get("ltc_monthly_add", 2500) if inputs.get("ltc_insurance_person_a") == "Yes" else 0) + \
                (settings.get("ltc_monthly_add", 2500) if inputs.get("ltc_insurance_person_b") == "Yes" else 0)
    reinv = inputs.get("re_investment_income", 0.0) + inputs.get("hecm_draw_monthly", 0.0) + inputs.get("heloc_draw_monthly", 0.0)
    investment_returns = inputs.get("other_assets", 0.0) * (inputs.get("investment_return_rate", 0.04) / 12)
    reinv += investment_returns
    household_income = sum([
        inputs.get("social_security_person_a", 0.0),
        inputs.get("social_security_person_b", 0.0),
        inputs.get("pension_person_a", 0.0),
        inputs.get("pension_person_b", 0.0),
        reinv
    ]) + va_total + ltc_total
    tax_rate = inputs.get("estimated_tax_rate", 0.15)
    household_income_after_tax = household_income * (1 - tax_rate)
    monthly_cost_full = care_cost_total + house_cost_total + optional_sum
    monthly_gap = max(0.0, monthly_cost_full - household_income_after_tax)
    total_assets = inputs.get("home_equity", 0.0) + inputs.get("other_assets", 0.0)
    inflation_rate = inputs.get("inflation_rate", 0.03)
    if monthly_gap <= 0:
        display_years = settings.get("display_cap_years_funded", 30)
    else:
        if inflation_rate > 0:
            years_funded = total_assets / (monthly_gap * 12) if monthly_gap > 0 else float("inf")
            years_funded /= (1 + inflation_rate)
        else:
            years_funded = total_assets / (monthly_gap * 12) if monthly_gap > 0 else float("inf")
        display_years = min(years_funded, settings.get("display_cap_years_funded", 30))
    return {
        "monthly_cost": monthly_cost_full,
        "monthly_gap": monthly_gap,
        "household_income": household_income_after_tax,
        "total_assets": total_assets,
        "years_funded_cap30": display_years if display_years != float("inf") else None,
        "care_cost_total": care_cost_total,
        "house_cost_total": house_cost_total,
        "optional_sum": optional_sum,
        "breakdown": {"Care": care_cost_total, "Home": house_cost_total, "Optional": optional_sum}
    }

# ---------- UI Setup ----------
spec = load_spec_with_overlay(JSON_PATH, OVERLAY_PATH)
if not spec:
    st.error("Application cannot start due to invalid JSON configuration. Check logs for details.")
    st.stop()

groups_cfg = spec.get("ui_groups", [])
groups = {g["id"]: g for g in groups_cfg}
modules = spec.get("modules", [])
lookups = spec.get("lookups", {})

# Wizard state
if "step" not in st.session_state:
    st.session_state.step = 1
if "inputs" not in st.session_state:
    st.session_state.inputs = {}
if "name_hint" not in st.session_state:
    st.session_state.name_hint = {"A": "Person A", "B": "Person B"}
if "grouped_answers" not in st.session_state:
    st.session_state.grouped_answers = {}

st.title("Senior Care Cost Planner")
st.markdown("Let's plan step by step. We'll estimate costs, income, and funding.")

# Step 1: Who and Strategy
if st.session_state.step == 1:
    st.header("Step 1: About the Plan")
    who = st.radio("Who are you planning for?", ["Myself", "Spouse or Partner", "Parent or Loved One", "A Couple (both parents)"])
    st.session_state.include_b = who == "A Couple (both parents)"
    if who == "A Couple (both parents)":
        name_a = st.text_input("Name for first person", value="Person A")
        name_b = st.text_input("Name for second person", value="Person B")
        st.session_state.name_hint = {"A": name_a, "B": name_b}
    else:
        name_a = st.text_input("Name of the person", value="Person A")
        st.session_state.name_hint = {"A": name_a, "B": "Person B"}
    state = st.selectbox("State (for cost adjustments)", list(lookups.get("state_multipliers", {}).keys()), index=0)
    st.session_state.inputs["state"] = state
    home_plan = st.radio("Do you plan to use the sale of the home or home equity to pay for care?", ["No, keep the home without using equity", "Yes, sell the home", "Yes, use reverse mortgage (HECM)", "Yes, use home equity line of credit (HELOC)"])
    st.session_state.maintain_home_household = home_plan != "Yes, sell the home"
    st.session_state.home_to_assets = home_plan == "Yes, sell the home"
    st.session_state.home_plan = home_plan  # Save for potential logic in Step 3 (e.g., show HECM/HELOC fields)
    if st.button("Next"):
        st.session_state.step = 2

# Step 2: Care Needs
elif st.session_state.step == 2:
    st.header("Step 2: Care Needs")
    person_a_in_care = st.checkbox(f"Does {st.session_state.name_hint['A']} need care?", value=True)
    st.session_state.inputs["person_a_in_care"] = person_a_in_care
    person_b_in_care = False  # Default to False if include_b is False
    if st.session_state.get("include_b", False):
        person_b_in_care = st.checkbox(f"Does {st.session_state.name_hint['B']} need care?")
    st.session_state.inputs["person_b_in_care"] = person_b_in_care
    if person_a_in_care or person_b_in_care:
        share_unit = st.checkbox("Will they share a unit/room if in facility care?")
        st.session_state.inputs["share_one_unit"] = share_unit
    for person, in_care in [("a", person_a_in_care), ("b", person_b_in_care)]:
        if in_care:
            name = st.session_state.name_hint["A" if person == "a" else "B"]
            st.subheader(f"Care for {name}")
            care_type = st.selectbox(f"Care type for {name}", ["In-Home Care (professional staff such as nurses, CNAs, or aides)", "Assisted Living (or Adult Family Home)", "Memory Care"], key=f"care_type_person_{person}")
            st.session_state.inputs[f"care_type_person_{person}"] = care_type
            if "In-Home" in care_type:
                hours = st.slider(f"Hours per day for {name}", 0, 24, 8, key=f"hours_per_day_person_{person}")
                st.session_state.inputs[f"hours_per_day_person_{person}"] = hours
            else:
                room_type = st.selectbox(f"Room type for {name}", list(lookups.get("room_type", {}).keys()), key=f"room_type_person_{person}")
                st.session_state.inputs[f"room_type_person_{person}"] = room_type
            care_level = st.selectbox(f"Care level for {name}", list(lookups.get("care_level_adders", {}).keys()), key=f"care_level_person_{person}")
            st.session_state.inputs[f"care_level_person_{person}"] = care_level
            mobility = st.selectbox(f"Mobility needs for {name}", list(lookups.get("mobility_adders", {}).get("facility", {}).keys()), key=f"mobility_person_{person}")
            st.session_state.inputs[f"mobility_person_{person}"] = mobility
            chronic = st.selectbox(f"Chronic conditions for {name}", list(lookups.get("chronic_adders", {}).keys()), key=f"chronic_person_{person}")
            st.session_state.inputs[f"chronic_person_{person}"] = chronic
    if st.button("Next"):
        st.session_state.step = 3

# Step 3: Financials
elif st.session_state.step == 3:
    st.header("Step 3: Financial Details")
    with st.form("finance_form"):
        for cat, gids in spec.get("category_map", {}).items():
            st.markdown(f"### {cat}")
            for gid in gids:
                if gid.endswith("_person_b") and not st.session_state.get("include_b"):
                    continue
                if gid not in groups:
                    continue
                person_label = st.session_state.name_hint.get("A" if "person_a" in gid else "B", "Person")
                g = groups.get(gid)
                with st.expander(f"{g.get('label', '').replace('Person A', person_label).replace('Person B', person_label)}"):
                    st.caption(g.get("prompt", ""))
                    ans = {}
                    for f in g.get("fields", []):
                        label = f.get("label", f.get("field", ""))
                        kind = f.get("kind", "currency")
                        default = f.get("default", 0)
                        tooltip = f.get("tooltip", "")
                        if tooltip:
                            st.caption(tooltip)
                        if kind == "boolean":
                            v = st.checkbox(label, value=default == "Yes")
                            ans[label] = v
                        elif kind == "select":
                            v = st.selectbox(label, f.get("options", []))
                            ans[label] = v
                        else:
                            v = st.number_input(label, min_value=0.0, value=float(default), step=50.0, format="%.2f")
                            ans[label] = v
                    st.session_state.grouped_answers[gid] = ans
        st.subheader("Advanced Adjustments")
        inflation_rate = st.slider("Annual inflation rate (%)", 0.0, 10.0, 3.0) / 100
        st.session_state.inputs["inflation_rate"] = inflation_rate
        investment_return_rate = st.slider("Annual return on assets (%)", 0.0, 10.0, 4.0) / 100
        st.session_state.inputs["investment_return_rate"] = investment_return_rate
        estimated_tax_rate = st.slider("Estimated tax rate on income (%)", 0.0, 30.0, 15.0) / 100
        st.session_state.inputs["estimated_tax_rate"] = estimated_tax_rate
        submitted = st.form_submit_button("Calculate")
    if submitted:
        flat_inputs = apply_ui_group_answers(groups_cfg, st.session_state.grouped_answers, st.session_state.inputs)
        res = compute(spec, flat_inputs)
        st.session_state.res = res
        st.session_state.step = 4

# Step 4: Results
elif st.session_state.step == 4:
    st.header("Step 4: Your Results")
    res = st.session_state.res
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Monthly Total Cost", f"${res['monthly_cost']:,.2f}")
    with col2:
        st.metric("Monthly Income (After Tax)", f"${res['household_income']:,.2f}")
    with col3:
        st.metric("Monthly Gap", f"${res['monthly_gap']:,.2f}")
    st.metric("Total Assets", f"${res['total_assets']:,.2f}")
    st.metric("Estimated Years Funded (with inflation, cap 30)", res['years_funded_cap30'] or "N/A")
    if st.button("Restart"):
        st.session_state.step = 1
        st.session_state.inputs = {}
        st.session_state.grouped_answers = {}