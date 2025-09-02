
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
    return json.loads(Path(path).read_text())

def load_spec_with_overlay(base_path: str, overlay_path: str | None = None):
    spec = _read_json(base_path)

    if overlay_path and Path(overlay_path).exists():
        overlay = _read_json(overlay_path)

        # Merge top-level modules
        if overlay.get("modules"):
            spec["modules"] = overlay["modules"]

        # Apply ui_group overrides
        overrides = overlay.get("ui_group_overrides", {})
        gid_to_group = {g["id"]: g for g in spec.get("ui_groups", [])}
        for gid, ov in overrides.items():
            g = gid_to_group.get(gid)
            if not g:
                continue
            if "module" in ov:
                g["module"] = ov["module"]

            # Field overrides
            field_ovs = ov.get("field_overrides", {})
            wildcard = field_ovs.get("*", {})
            for f in g.get("fields", []):
                label = f.get("label", f["field"])
                this_ov = field_ovs.get(label, {})
                # Apply wildcard first, then specific
                for k, v in wildcard.items():
                    f.setdefault(k, v)
                for k, v in this_ov.items():
                    f[k] = v

        # Ensure defaults for optional + skip_value if overlay present
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
        # Respect conditional groups against current flat state
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
    settings = spec["settings"]
    lookups = spec["lookups"]

    def per_person_cost(person):
        care_type = inputs.get(f"care_type_person_{person}")
        care_level = inputs.get(f"care_level_person_{person}")
        mobility = inputs.get(f"mobility_person_{person}")
        chronic = inputs.get(f"chronic_person_{person}")

        care_level_add = lookups["care_level_adders"].get(care_level, 0)
        mobility_fac = lookups["mobility_adders"]["facility"].get(mobility, 0)
        mobility_home = lookups["mobility_adders"]["in_home"].get(mobility, 0)
        chronic_add = lookups["chronic_adders"].get(chronic, 0)

        if care_type == "In-Home Care (professional staff such as nurses, CNAs, or aides)":
            hours = str(inputs.get(f"hours_per_day_person_{person}", "0"))
            hourly = lookups["in_home_care_matrix"].get(hours, 0)
            in_home_cost = hourly * settings["days_per_month"] + mobility_home + chronic_add
            return money(in_home_cost)
        elif care_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room_type = inputs.get(f"room_type_person_{person}")
            base_room = lookups["room_type"].get(room_type, 0)
            if care_type == "Memory Care":
                base_room *= settings["memory_care_multiplier"]
            facility_cost = base_room + care_level_add + mobility_fac + chronic_add
            return money(facility_cost)
        else:
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
            room_base_b = spec["lookups"]["room_type"].get(room_type_b, 0)
            if b_type == "Memory Care":
                room_base_b *= spec["settings"]["memory_care_multiplier"]
            return money(room_base_b - spec["settings"]["second_person_cost"])
        return 0.0

    a_selected = per_person_cost("a") if inputs.get("person_a_in_care") else 0.0
    b_selected = per_person_cost("b") if inputs.get("person_b_in_care") else 0.0
    shared_adj = shared_unit_adjustment()
    care_cost_total = money(a_selected + b_selected - shared_adj)

    optional_fields = ["optional_rx","optional_personal_care","optional_phone_internet","optional_life_insurance",
                       "optional_transportation","optional_family_travel","optional_auto","optional_auto_insurance","optional_other"]
    optional_sum = sum(inputs.get(k, 0.0) for k in optional_fields)
    home_fields = ["mortgage","taxes","insurance","hoa","utilities"]
    home_sum = sum(inputs.get(k, 0.0) for k in home_fields)
    house_cost_total = home_sum if inputs.get("maintain_home_household") else 0.0

    va_total = inputs.get("va_benefit_person_a", 0.0) + inputs.get("va_benefit_person_b", 0.0)
    ltc_total = (spec["settings"]["ltc_monthly_add"] if inputs.get("ltc_insurance_person_a") == "Yes" else 0) + \
                (spec["settings"]["ltc_monthly_add"] if inputs.get("ltc_insurance_person_b") == "Yes" else 0)

    household_income = sum([
        inputs.get("social_security_person_a", 0.0),
        inputs.get("social_security_person_b", 0.0),
        inputs.get("pension_person_a", 0.0),
        inputs.get("pension_person_b", 0.0),
        inputs.get("re_investment_income", 0.0)
    ]) + va_total + ltc_total

    monthly_cost_full = care_cost_total + house_cost_total + optional_sum
    monthly_gap = max(0.0, monthly_cost_full - household_income)
    total_assets = inputs.get("home_equity", 0.0) + inputs.get("other_assets", 0.0)

    if monthly_gap <= 0:
        display_years = spec["settings"]["display_cap_years_funded"]
    else:
        years_funded = total_assets / (monthly_gap * 12) if (monthly_gap * 12) > 0 else float("inf")
        display_years = min(years_funded, spec["settings"]["display_cap_years_funded"])

    return {
        "care_cost_total": money(care_cost_total),
        "monthly_cost": money(monthly_cost_full),
        "household_income": money(household_income),
        "monthly_gap": money(monthly_gap),
        "total_assets": money(total_assets),
        "years_funded_cap30": (None if display_years is None or display_years == float("inf") else round(display_years,2))
    }

# ---------- UI (progressive steps + modular categories) ----------
st.set_page_config(page_title="Senior Care Cost Wizard", page_icon="🧭", layout="centered")
spec = load_spec_with_overlay(JSON_PATH, OVERLAY_PATH)

groups_cfg = spec.get("ui_groups", [])
groups = {g["id"]: g for g in groups_cfg}

if "step" not in st.session_state:
    st.session_state.step = 1

st.title("🧭 Senior Care Cost Wizard")
with st.expander("Loaded calculator spec (JSON)", expanded=False):
    st.code(JSON_PATH + (" + overlay" if Path(OVERLAY_PATH).exists() else ""))

# Names from state
care_recipient = st.session_state.get("care_recipient", "Care Recipient")
planner_name = st.session_state.get("planner", "Planner")
person_b_name = st.session_state.get("person_b_name", "Partner")

# ---------- Step 1 ----------
st.header("Step 1 · Who is this plan for?")
who = st.radio("Who are you planning care for?", ["Myself", "Someone else"], index=0, key="who_radio")
if who == "Someone else":
    st.selectbox("Your relationship to the person:", [
        "Spouse / Partner", "Parent / Parent-in-law", "Other relative / POA", "Friend / Other"
    ], key="relationship")

col1, col2 = st.columns(2)
with col1:
    care_recipient = st.text_input("Care recipient's name", value=care_recipient, key="care_recipient")
with col2:
    planner_name = st.text_input("Your name (if different)", value=(planner_name if who=="Someone else" else ""), key="planner")

if st.button("Continue to care plan →", type="primary"):
    st.session_state.step = max(st.session_state.step, 2)

st.divider()

# ---------- Step 2 ----------
inputs = {"person_a_in_care": True, "person_b_in_care": False}
if st.session_state.step >= 2:
    st.header(f"Step 2 · {care_recipient or 'Person A'} — Care plan")
    care_type = st.selectbox(
        "Care type",
        ["In-Home Care (professional staff such as nurses, CNAs, or aides)",
         "Assisted Living (or Adult Family Home)",
         "Memory Care"],
        key="care_type_a"
    )
    inputs["care_type_person_a"] = care_type

    if care_type.startswith("In-Home Care"):
        inputs["hours_per_day_person_a"] = st.selectbox("Hours of care per day", ["4","6","8","10","12","24"], index=2, key="hours_a")
    else:
        inputs["room_type_person_a"] = st.selectbox("Room type", ["Studio","1 Bedroom","2 Bedroom"], index=0, key="room_a")

    inputs["care_level_person_a"] = st.selectbox("Care level", ["Low","Medium","High"], index=1, key="level_a")
    inputs["mobility_person_a"]   = st.selectbox("Mobility", ["None","Walker","Wheelchair"], index=1, key="mob_a")
    inputs["chronic_person_a"]    = st.selectbox("Chronic conditions", ["None","Some conditions (manageable)","Multiple conditions (complex)"], index=1, key="cc_a")

    st.subheader("Spouse / Partner (optional)")
    st.caption("Even if your spouse/partner isn’t receiving paid care, keeping the home (mortgage/taxes/insurance/utilities) can affect how affordable your care is. Add them to account for household costs.")
    include_b = st.checkbox("Include spouse/partner in this plan?", value=False, key="include_b")

    if include_b:
        inputs["person_b_in_care"] = True
        person_b_name = st.text_input("Person B name", value=person_b_name, key="person_b_name")
        st.subheader(f"{person_b_name or 'Person B'} — Care plan")

        care_b = st.selectbox(
            "Care type (Person B)",
            ["Stay at Home",
             "In-Home Care (professional staff such as nurses, CNAs, or aides)",
             "Assisted Living (or Adult Family Home)",
             "Memory Care"],
            index=0, key="care_type_b"
        )
        inputs["care_type_person_b"] = care_b

        if care_b.startswith("In-Home Care"):
            inputs["hours_per_day_person_b"] = st.selectbox("Hours/day (B)", ["4","6","8","10","12","24"], index=1, key="hours_b")
        elif care_b in ["Assisted Living (or Adult Family Home)","Memory Care"]:
            inputs["room_type_person_b"] = st.selectbox("Room type (B)", ["Studio","1 Bedroom","2 Bedroom"], index=0, key="room_b")

        same_adders = st.checkbox("Use same care level/mobility/chronic as Person A", value=True, key="same_adders_b")
        if same_adders:
            inputs["care_level_person_b"] = inputs["care_level_person_a"]
            inputs["mobility_person_b"]   = inputs["mobility_person_a"]
            inputs["chronic_person_b"]    = inputs["chronic_person_a"]
        else:
            inputs["care_level_person_b"] = st.selectbox("Care level (B)", ["Low","Medium","High"], index=0, key="level_b")
            inputs["mobility_person_b"]   = st.selectbox("Mobility (B)", ["None","Walker","Wheelchair"], index=0, key="mob_b")
            inputs["chronic_person_b"]    = st.selectbox("Chronic conditions (B)", ["None","Some conditions (manageable)","Multiple conditions (complex)"], index=0, key="cc_b")

        facility_types = ["Assisted Living (or Adult Family Home)", "Memory Care"]
        if (inputs["care_type_person_a"] in facility_types) and (care_b in facility_types):
            inputs["share_one_unit"] = st.checkbox("Share one unit?", value=False, key="share_unit")

    if st.button("Continue to finances →", type="primary"):
        st.session_state.step = max(st.session_state.step, 3)

st.divider()

# ---------- Step 3: Modular Household & Finances ----------
if st.session_state.step >= 3:
    st.header("Step 3 · Choose what you want to enter")
    st.caption("Check the categories you want to include. We’ll only ask for those details. You can come back and add more any time.")

    # Build categories dynamically from spec["modules"] if present; else fallback
    modules = spec.get("modules")
    if modules:
        cat_order = [m["label"] for m in modules]
        id_by_label = {m["label"]: m["id"] for m in modules}
        default_on = {m["label"] for m in modules if m.get("default_selected", True)}
        # Map module id -> group ids
        mod_to_groupids = {}
        for g in groups_cfg:
            mod = g.get("module")
            if mod:
                mod_to_groupids.setdefault(mod, []).append(g["id"])
        CATEGORY_MAP = {label: mod_to_groupids.get(id_by_label[label], []) for label in cat_order}
    else:
        CATEGORY_MAP = {
            "Income": ["group_income_person_a", "group_income_person_b"],
            "Benefits (VA / LTC)": ["group_benefits_person_a", "group_benefits_person_b"],
            "House carry (mortgage/taxes/etc.)": ["group_home_carry"],
            "Optional monthly costs": ["group_optional_costs"],
            "Assets": ["group_assets"]
        }
        default_on = {"Income", "Benefits (VA / LTC)", "Optional monthly costs", "Assets"}

    # CHECKBOXES for categories
    chosen_flags = {}
    st.markdown("**Categories:**")
    for cat in CATEGORY_MAP.keys():
        chosen_flags[cat] = st.checkbox(cat, value=(cat in default_on), key=f"cat_{cat}")

    keep_home = st.checkbox("Maintain current home while in care?", value=False, key="keep_home")
    inputs["maintain_home_household"] = keep_home

    def group_form_modular(gid, name_hint=None):
        g = groups[gid]
        cond = g.get("condition")
        if cond and inputs.get(cond["field"]) != cond["equals"]:
            return None
        heading = g['label']
        if name_hint:
            heading = heading.replace("Person A", name_hint.get("A","Person A")).replace("Person B", name_hint.get("B","Person B"))
        with st.expander(f"{heading} — {g['prompt']}", expanded=True):
            ans = {}
            for f in g["fields"]:
                label = f.get("label", f["field"])
                kind = f.get("kind","currency")
                default = f.get("default", 0)

                include_item = True
                if kind == "currency":
                    include_item = st.checkbox(f"Include: {label}", value=True, key=f"inc_{gid}_{label}")
                elif kind == "boolean":
                    include_item = st.checkbox(f"Include: {label}", value=False, key=f"inc_{gid}_{label}")

                if not include_item:
                    ans[label] = f.get("skip_value", 0 if kind=="currency" else "No")
                    continue

                if kind == "boolean":
                    v = st.checkbox(label, value=(str(default).lower() in {'yes','true','1'}), key=f"bool_{gid}_{label}")
                    ans[label] = v
                else:
                    v = st.number_input(label, min_value=0.0, value=float(default), step=50.0, format="%.2f", key=f"num_{gid}_{label}")
                    ans[label] = v
            return ans

    grouped_answers = {}
    with st.form("finance_form"):
        name_hint = {"A": care_recipient or "Person A", "B": person_b_name or "Person B"}

        for cat, on in chosen_flags.items():
            if not on:
                continue
            for gid in CATEGORY_MAP[cat]:
                if gid.endswith("_person_b") and not st.session_state.get("include_b"):
                    continue
                if gid not in groups:
                    continue
                ans = group_form_modular(gid, name_hint=name_hint)
                if ans is not None:
                    grouped_answers[gid] = ans

        submitted = st.form_submit_button("Calculate")

    if submitted:
        flat_inputs = apply_ui_group_answers(groups_cfg, grouped_answers, existing_fields=inputs)
        res = compute(spec, flat_inputs)
        st.success("Calculation complete")
        colA, colB, colC = st.columns(3)
        with colA:
            st.metric("Monthly cost (all-in)", f"${res['monthly_cost']:,.2f}")
            st.metric("Monthly gap", f"${res['monthly_gap']:,.2f}")
        with colB:
            st.metric("Household income", f"${res['household_income']:,.2f}")
            st.metric("Assets total", f"${res['total_assets']:,.2f}")
        with colC:
            yf = res['years_funded_cap30']
            st.metric("Years funded (cap 30)", "N/A" if yf is None else yf)
