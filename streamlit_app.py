
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import streamlit as st

JSON_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"

# ---------- Helpers ----------
def money(x):
    try:
        return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0

def load_spec(path: str):
    return json.loads(Path(path).read_text())

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
            label = f.get("label", field_name)
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

# ---------- UI ----------
st.set_page_config(page_title="Senior Care Cost Wizard", page_icon="🧭", layout="centered")
st.title("🧭 Senior Care Cost Wizard")

spec = load_spec(JSON_PATH)
groups_cfg = spec.get("ui_groups", [])

with st.expander("Loaded calculator spec (JSON)", expanded=False):
    st.code(JSON_PATH)

# Q0 — Who are you planning care for?
who = st.radio("Who are you planning care for?", ["Myself", "Someone else"], index=0)

relationship = None
if who == "Someone else":
    relationship = st.selectbox("Your relationship to the person:", [
        "Spouse / Partner", "Parent / Parent-in-law", "Other relative / POA", "Friend / Other"
    ])

# Q2 — Names
col1, col2 = st.columns(2)
with col1:
    care_recipient = st.text_input("Care recipient's name", value="Care Recipient")
with col2:
    planner = st.text_input("Your name (if different)", value="Planner" if who=="Someone else" else "")

# Branch flags
spouse_partner_two_person = (who == "Someone else" and relationship == "Spouse / Partner")

st.markdown("---")
st.subheader("Care Plan")

# Person A (care recipient)
st.markdown("**Person A (Care recipient)**")
care_type = st.selectbox(
    "Care type",
    ["In-Home Care (professional staff such as nurses, CNAs, or aides)",
     "Assisted Living (or Adult Family Home)",
     "Memory Care"]
)

inputs = {"person_a_in_care": True, "person_b_in_care": False}
inputs["care_type_person_a"] = care_type

if care_type.startswith("In-Home Care"):
    hours = st.selectbox("Hours of care per day", ["4","6","8","10","12","24"], index=2)
    inputs["hours_per_day_person_a"] = hours
else:
    room = st.selectbox("Room type", ["Studio","1 Bedroom","2 Bedroom"], index=0)
    inputs["room_type_person_a"] = room

# Adders for A
level = st.selectbox("Care level", ["Low","Medium","High"], index=1)
mob = st.selectbox("Mobility", ["None","Walker","Wheelchair"], index=1)
cc  = st.selectbox("Chronic conditions", ["None","Some conditions (manageable)","Multiple conditions (complex)"], index=1)
inputs["care_level_person_a"] = level
inputs["mobility_person_a"] = mob
inputs["chronic_person_a"] = cc

# Optional Person B (Spouse/Partner)
if spouse_partner_two_person:
    st.markdown("---")
    st.subheader("Spouse / Partner (optional second person)")
    include_b = st.checkbox("Include spouse/partner in the care plan?", value=False)
    if include_b:
        inputs["person_b_in_care"] = True
        pb_name = st.text_input("Person B name", value="Partner")
        care_b = st.selectbox(
            "Care type (Person B)",
            ["Stay at Home",
             "In-Home Care (professional staff such as nurses, CNAs, or aides)",
             "Assisted Living (or Adult Family Home)",
             "Memory Care"],
            index=0
        )
        inputs["care_type_person_b"] = care_b
        if care_b.startswith("In-Home Care"):
            hours_b = st.selectbox("Hours/day (B)", ["4","6","8","10","12","24"], index=1)
            inputs["hours_per_day_person_b"] = hours_b
        elif care_b in ["Assisted Living (or Adult Family Home)","Memory Care"]:
            room_b = st.selectbox("Room type (B)", ["Studio","1 Bedroom","2 Bedroom"], index=0)
            inputs["room_type_person_b"] = room_b

        same_adders = st.checkbox("Use same care level/mobility/chronic as Person A", value=True)
        if same_adders:
            inputs["care_level_person_b"] = inputs["care_level_person_a"]
            inputs["mobility_person_b"] = inputs["mobility_person_a"]
            inputs["chronic_person_b"] = inputs["chronic_person_a"]
        else:
            level_b = st.selectbox("Care level (B)", ["Low","Medium","High"], index=0)
            mob_b   = st.selectbox("Mobility (B)", ["None","Walker","Wheelchair"], index=0)
            cc_b    = st.selectbox("Chronic conditions (B)", ["None","Some conditions (manageable)","Multiple conditions (complex)"], index=0)
            inputs["care_level_person_b"] = level_b
            inputs["mobility_person_b"] = mob_b
            inputs["chronic_person_b"] = cc_b

        facility_types = ["Assisted Living (or Adult Family Home)", "Memory Care"]
        if (care_type in facility_types) and (care_b in facility_types):
            share = st.checkbox("Share one unit?", value=False)
            inputs["share_one_unit"] = share

st.markdown("---")
st.subheader("Household & Finances")

keep_home = st.checkbox("Maintain current home while in care?", value=False)
inputs["maintain_home_household"] = keep_home

# Render ui_groups dynamically
groups = {g["id"]: g for g in groups_cfg}

def group_form(gid):
    g = groups[gid]
    cond = g.get("condition")
    if cond and inputs.get(cond["field"]) != cond["equals"]:
        return None
    st.markdown(f"**{g['label']}** — {g['prompt']}")
    ans = {}
    for f in g["fields"]:
        label = f.get("label", f["field"])
        kind = f.get("kind","currency")
        default = f.get("default", 0)
        if kind == "boolean":
            v = st.checkbox(label, value=(str(default).lower() in {"yes","true","1"}))
            ans[label] = v
        else:
            v = st.number_input(label, min_value=0.0, value=float(default), step=50.0, format="%.2f")
            ans[label] = v
    return ans

grouped_answers = {}

with st.form("finance_form"):
    # Income A
    if "group_income_person_a" in groups:
        ans = group_form("group_income_person_a")
        if ans: grouped_answers["group_income_person_a"] = ans

    # Income B only if exists
    if inputs.get("person_b_in_care") and "group_income_person_b" in groups:
        ans = group_form("group_income_person_b")
        if ans: grouped_answers["group_income_person_b"] = ans

    # Optional costs
    if "group_optional_costs" in groups:
        ans = group_form("group_optional_costs")
        if ans: grouped_answers["group_optional_costs"] = ans

    # Home carry
    if "group_home_carry" in groups:
        ans = group_form("group_home_carry")
        if ans: grouped_answers["group_home_carry"] = ans

    # Benefits
    if "group_benefits_person_a" in groups:
        ans = group_form("group_benefits_person_a")
        if ans: grouped_answers["group_benefits_person_a"] = ans
    if inputs.get("person_b_in_care") and "group_benefits_person_b" in groups:
        ans = group_form("group_benefits_person_b")
        if ans: grouped_answers["group_benefits_person_b"] = ans

    # Assets
    if "group_assets" in groups:
        ans = group_form("group_assets")
        if ans: grouped_answers["group_assets"] = ans

    submitted = st.form_submit_button("Calculate")

if submitted:
    flat_inputs = apply_ui_group_answers(groups_cfg, grouped_answers, existing_fields=inputs)
    res = compute(spec, flat_inputs)

    st.success("Calculation complete")
    st.metric("Monthly cost (all-in)", f"${res['monthly_cost']:,.2f}")
    st.metric("Household income", f"${res['household_income']:,.2f}")
    st.metric("Monthly gap", f"${res['monthly_gap']:,.2f}")
    st.metric("Assets total", f"${res['total_assets']:,.2f}")
    yf = res['years_funded_cap30']
    st.metric("Years funded (cap 30)", "N/A" if yf is None else yf)
