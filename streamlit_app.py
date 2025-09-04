import json
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import streamlit as st
import altair as alt

APP_VERSION = "v2025-09-03-rb13-no-reportlab-no-css"
SPEC_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"

# ---------- utils
def money(x):
    """Convert value to float with 2 decimal places, handling errors."""
    try:
        return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0

def mfmt(x):
    """Format number as currency string."""
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return "$0.00"

def read_json(p):
    """Read JSON file with error handling."""
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        st.warning(f"Failed to load {p}. Using defaults.")
        return {}

# ---------- currency parsing helpers
def parse_currency_str(s, default=0.0):
    """Parse currency string, removing commas and $, with validation."""
    if s is None:
        return float(default)
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(",", "").replace("$", "")
    if s == "":
        return float(default)
    try:
        val = float(s)
        return val
    except Exception:
        st.error("Invalid currency input. Please enter a number (e.g., 1000 or 1,000).")
        return float(default)

def currency_input(label, store_name, default=0.0, drawer_name=None, help_text=None):
    """Render currency input with placeholder and validation."""
    raw_key = f"{store_name}_raw"
    # Ensure default is a float
    try:
        default = float(default)
    except (TypeError, ValueError):
        default = 0.0
    # Get existing value, ensuring it's a float
    existing = st.session_state.inputs.get(store_name, default)
    try:
        existing = float(existing)
    except (TypeError, ValueError):
        existing = default
    if raw_key not in st.session_state:
        st.session_state[raw_key] = f"{existing:,.2f}" if existing else ""
    raw = st.text_input(
        label,
        value=st.session_state.get(raw_key, ""),
        placeholder="$0.00",
        key=raw_key,
        help=help_text,
        on_change=mark_touched if drawer_name else None,
        args=(drawer_name,) if drawer_name else None,
    )
    val = parse_currency_str(raw, default=default)
    st.session_state.inputs[store_name] = val
    if val != parse_currency_str(raw, default=None):
        st.success(f"Formatted input as {mfmt(val)}")
    return val

# ---------- spec
def load_spec():
    """Load and merge base and overlay JSON schemas."""
    spec = read_json(SPEC_PATH)
    ov = read_json(OVERLAY_PATH)
    if ov:
        spec.setdefault("lookups", {}).update(ov.get("lookups", {}))
        spec.setdefault("ui_group_additions", []).extend(ov.get("ui_group_additions", []))
        if "ui_group_overrides" in ov:
            spec.setdefault("ui_group_overrides", {}).update(ov["ui_group_overrides"])
    return spec

def interp(matrix, h):
    """Interpolate value from matrix based on hours."""
    ks = sorted(int(k) for k in matrix.keys())
    if not ks:
        return 0.0
    if h <= ks[0]:
        return float(matrix[str(ks[0])])
    if h >= ks[-1]:
        return float(matrix[str(ks[-1])])
    lo = max(k for k in ks if k <= h)
    hi = min(k for k in ks if k >= h)
    if lo == hi:
        return float(matrix[str(lo)])
    frac = (h - lo) / (hi - lo)
    return float(matrix[str(lo)]) + frac * (float(matrix[str(hi)]) - float(matrix[str(lo)]))

# ---------- core calc
def get_lookup_value(lookup, key, default=0.0):
    """Safely retrieve value from lookup dictionary."""
    return float(lookup.get(key, default))

def calculate_care_cost(inputs, spec, tag):
    """Calculate care cost for a person (A or B)."""
    L = spec["lookups"]
    S = spec["settings"]
    state_mult = get_lookup_value(L["state_multipliers"], inputs.get("state", "National"), 1.0)
    ct = inputs.get(f"care_type_{tag}", "None")

    if not ct or ct == "None":
        return 0.0

    if ct.startswith("In-Home"):
        hrs = int(inputs.get(f"hours_{tag}", 4) or 4)
        days = int(inputs.get(f"days_{tag}", 20) or 20)
        lvl = inputs.get(f"care_level_{tag}", "Medium")
        mob = inputs.get(f"mobility_{tag}", "Medium")
        chrk = inputs.get(f"chronic_{tag}", "None")
        base = interp(L["in_home_care_matrix"], hrs) * days
        base += get_lookup_value(L["mobility_adders"]["in_home"], mob, 100)
        base += get_lookup_value(L["chronic_adders"], chrk, 0)
        return money(base * state_mult)

    if ct in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
        rm = inputs.get(f"room_{tag}", "Studio")
        lvl = inputs.get(f"care_level_{tag}", "Medium")
        mob = inputs.get(f"mobility_{tag}", "Medium")
        chrk = inputs.get(f"chronic_{tag}", "None")
        base = get_lookup_value(L["room_type"], rm, 4200)
        base += get_lookup_value(L["care_level_adders"], lvl, 400)
        base += get_lookup_value(L["mobility_adders"]["facility"], mob, 150)
        base += get_lookup_value(L["chronic_adders"], chrk, 0)
        if ct == "Memory Care":
            base *= float(S["memory_care_multiplier"])
        return money(base * state_mult)

    return 0.0

def calculate_home_costs(inputs):
    """Calculate total home maintenance costs if keeping home."""
    if not inputs.get("maintain_home", False):
        return 0.0
    return money(sum(
        float(inputs.get(k, 0.0))
        for k in ["mortgage", "taxes", "insurance", "hoa", "utilities"]
    ))

def calculate_optional_costs(inputs):
    """Calculate total optional monthly costs."""
    return money(sum(
        float(inputs.get(k, 0.0))
        for k in [
            "medicare_premiums",
            "dental_vision_hearing",
            "home_modifications_monthly",
            "other_debts_monthly",
            "pet_care",
            "entertainment_hobbies",
            "optional_rx",
            "optional_personal_care",
            "optional_phone_internet",
            "optional_life_insurance",
            "optional_new_car",
            "optional_auto",
            "optional_auto_insurance",
            "optional_other",
            "heloc_payment_monthly",
        ]
    ))

def calculate_income(inputs):
    """Calculate total household income."""
    return money(sum(
        float(inputs.get(k, 0.0))
        for k in [
            "social_security_person_a",
            "pension_person_a",
            "social_security_person_b",
            "pension_person_b",
            "rental_income",
            "wages_part_time",
            "alimony_support",
            "dividends_interest",
            "other_income_monthly",
            "ltc_insurance_person_a_monthly",
            "ltc_insurance_person_b_monthly",
        ]
    ))

def calculate_va_benefits(inputs, spec, care_cost):
    """Calculate VA benefits for Person A and B."""
    L = spec["lookups"]
    cat_a = inputs.get("va_cat_a", "None")
    cat_b = inputs.get("va_cat_b", "None")
    medical = money(
        care_cost +
        float(inputs.get("medicare_premiums", 0)) +
        float(inputs.get("dental_vision_hearing", 0)) +
        float(inputs.get("optional_rx", 0)) +
        float(inputs.get("optional_personal_care", 0))
    )
    income = calculate_income(inputs)
    
    # Determine MAPR based on VA categories
    mapr = get_lookup_value(L["va_categories"], "None")
    if "Two veterans" in cat_a or "Two veterans" in cat_b:
        mapr = get_lookup_value(L["va_categories"], "Two veterans married, both A&A (household ceiling)")
    elif "Veteran with spouse" in cat_a or "Veteran with spouse" in cat_b:
        mapr = get_lookup_value(L["va_categories"], "Veteran with spouse (A&A)")
    elif "Veteran only" in cat_a:
        mapr = get_lookup_value(L["va_categories"], "Veteran only (A&A)")
    elif "Veteran only" in cat_b:
        mapr = get_lookup_value(L["va_categories"], "Veteran only (A&A)")
    elif "Surviving spouse" in cat_a:
        mapr = get_lookup_value(L["va_categories"], "Surviving spouse (A&A)")
    elif "Surviving spouse" in cat_b:
        mapr = get_lookup_value(L["va_categories"], "Surviving spouse (A&A)")

    va_month = money(max(0.0, mapr * 12 - max(0.0, income * 12 - medical * 12)) / 12.0)
    if "Two veterans" in cat_a or "Two veterans" in cat_b:
        va_a = money(va_month / 2)
        va_b = money(va_month / 2)
    else:
        va_a = money(va_month if "Veteran" in cat_a or "Surviving spouse" in cat_a else 0.0)
        va_b = money(va_month if "Veteran" in cat_b or "Surviving spouse" in cat_b else 0.0)
    
    return va_a, va_b

def calculate_assets(inputs, spec):
    """Calculate total liquid assets and years funded."""
    S = spec["settings"]
    asset_keys = [
        f["field"] for group in spec.get("ui_group_additions", [])
        for f in group["fields"] if group["id"] in ["group_assets_common", "group_assets_more"]
    ]
    liquid = money(sum(float(inputs.get(k, 0.0)) for k in asset_keys))
    if inputs.get("home_to_assets", False):
        liquid += float(inputs.get("home_equity", 0.0))
    liquid = max(0.0, liquid - float(inputs.get("home_modifications_monthly", 0.0) * 12))
    return liquid

def compute(inputs, spec):
    """Compute all financial metrics for the care plan."""
    care_a = calculate_care_cost(inputs, spec, "a")
    care_b = calculate_care_cost(inputs, spec, "b")
    
    # Apply second-person discount
    S = spec["settings"]
    state_mult = get_lookup_value(spec["lookups"]["state_multipliers"], inputs.get("state", "National"), 1.0)
    disc = money(
        float(S["second_person_cost"]) * state_mult
        if inputs.get("care_type_a") in ["Assisted Living (or Adult Family Home)", "Memory Care"]
        and inputs.get("care_type_b") in ["Assisted Living (or Adult Family Home)", "Memory Care"]
        else 0.0
    )
    care = money(care_a + care_b - disc)
    
    home = calculate_home_costs(inputs)
    opt = calculate_optional_costs(inputs)
    month_cost = money(care + home + opt)
    
    income = calculate_income(inputs)
    va_a, va_b = calculate_va_benefits(inputs, spec, care)
    gap = money(max(0.0, month_cost - (income + va_a + va_b)))
    
    liquid = calculate_assets(inputs, spec)
    years = liquid / (gap * 12.0) if gap > 0 else float("inf")
    
    return {
        "care": care,
        "month_cost": month_cost,
        "income": income,
        "va_a": va_a,
        "va_b": va_b,
        "gap": gap,
        "liquid": liquid,
        "years": min(years, S["display_cap_years_funded"]),
    }

# ---------- UI helpers
def mark_touched(drawer):
    """Mark an expander as touched for persistence."""
    st.session_state.touched.add(drawer)

def expander(drawer, title, preview_val):
    """Render an expander with preview value."""
    is_open = drawer in st.session_state.touched
    with st.expander(f"{title} — {mfmt(preview_val)}", expanded=is_open):
        return st.container()

def home_mods_ui(inp, spec):
    """Render UI for home modifications."""
    with expander("home_mods", "Home modifications (optional)", inp.get("home_modifications_monthly", 0.0)):
        grab_bars = spec["lookups"].get("home_mod_specs", {}).get("grab_bars", {})
        inp["grab_bars"] = st.slider(
            grab_bars.get("label", "Grab bars and rails"),
            min_value=float(grab_bars.get("min", 0)),
            max_value=float(grab_bars.get("max", 500)),
            value=float(inp.get("grab_bars", grab_bars.get("avg", 250))),
            step=float(grab_bars.get("step", 25)),
            help=grab_bars.get("note", ""),
            key="grab_bars",
        )
        inp["home_modifications_monthly"] = money(inp.get("grab_bars", 0) / 12)

# ---------- main
def main():
    # Initialize session state
    if "step" not in st.session_state:
        st.session_state.step = 1
    if "inputs" not in st.session_state:
        st.session_state.inputs = {}
    if "touched" not in st.session_state:
        st.session_state.touched = set()
    if "names" not in st.session_state:
        st.session_state.names = {"A": "Person A", "B": "Person B"}

    # Empathetic onboarding
    st.info("We’re here to help you navigate senior care costs. Take it one step at a time, and don’t worry if you’re unsure—we can estimate.")

    # Progress bar
    st.progress(st.session_state.step / 4, text=f"Step {st.session_state.step} of 4")

    # Sidebar: Help resources
    with st.sidebar:
        st.header("Help & Resources")
        st.markdown("""
        - [VA Aid & Attendance](https://www.va.gov/pension/aid-attendance-housebound/)
        - [Medicare Information](https://www.medicare.gov/)
        - [FAQ: Understanding Care Costs](https://www.aarp.org/caregiving/financial-legal/)
        """)
        st.markdown(f"App {APP_VERSION}")

    spec = load_spec()
    inp = st.session_state.inputs
    names = st.session_state.names

    if st.session_state.step == 1:
        st.header("Step 1 · Who is this for?")
        names["A"] = st.text_input("Name of Person A", value=names.get("A", "Person A"), help="Enter the primary person's name.")
        include_b = st.checkbox("Include a second person (e.g., spouse)", value=st.session_state.get("include_b", False))
        st.session_state.include_b = include_b
        if include_b:
            names["B"] = st.text_input("Name of Person B", value=names.get("B", "Person B"), help="Enter the second person's name.")
        if st.button("Next →", type="primary", use_container_width=True):
            st.session_state.step = 2
            st.rerun()

    elif st.session_state.step == 2:
        st.header("Step 2 · Care Needs")
        care_types = ["In-Home Care", "Assisted Living (or Adult Family Home)", "Memory Care", "None"]
        inp["care_type_a"] = st.selectbox(f"Care type for {names['A']}", care_types, index=care_types.index(inp.get("care_type_a", "None")))
        if inp["care_type_a"].startswith("In-Home"):
            inp["hours_a"] = st.slider(f"Daily hours for {names['A']}", 0, 24, int(inp.get("hours_a", 4)), help="Estimate hours of care needed per day.")
            inp["days_a"] = st.slider(f"Days per month for {names['A']}", 0, 30, int(inp.get("days_a", 20)), help="Estimate days per month for care.")
            inp["care_level_a"] = st.selectbox(f"Care level for {names['A']}", ["Low", "Medium", "High"], index=1)
            inp["mobility_a"] = st.selectbox(f"Mobility for {names['A']}", ["Low", "Medium", "High"], index=1)
            inp["chronic_a"] = st.selectbox(f"Chronic conditions for {names['A']}", ["None", "Some", "Multiple/Complex"], index=0)
        elif inp["care_type_a"] in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            inp["room_a"] = st.selectbox(f"Room type for {names['A']}", ["Studio", "1 Bedroom", "Shared"], index=0)
            inp["care_level_a"] = st.selectbox(f"Care level for {names['A']}", ["Low", "Medium", "High"], index=1)
            inp["mobility_a"] = st.selectbox(f"Mobility for {names['A']}", ["Low", "Medium", "High"], index=1)
            inp["chronic_a"] = st.selectbox(f"Chronic conditions for {names['A']}", ["None", "Some", "Multiple/Complex"], index=0)

        if st.session_state.get("include_b", False):
            inp["care_type_b"] = st.selectbox(f"Care type for {names['B']}", care_types, index=care_types.index(inp.get("care_type_b", "None")))
            if inp["care_type_b"].startswith("In-Home"):
                inp["hours_b"] = st.slider(f"Daily hours for {names['B']}", 0, 24, int(inp.get("hours_b", 4)), help="Estimate hours of care needed per day.")
                inp["days_b"] = st.slider(f"Days per month for {names['B']}", 0, 30, int(inp.get("days_b", 20)), help="Estimate days per month for care.")
                inp["care_level_b"] = st.selectbox(f"Care level for {names['B']}", ["Low", "Medium", "High"], index=1)
                inp["mobility_b"] = st.selectbox(f"Mobility for {names['B']}", ["Low", "Medium", "High"], index=1)
                inp["chronic_b"] = st.selectbox(f"Chronic conditions for {names['B']}", ["None", "Some", "Multiple/Complex"], index=0)
            elif inp["care_type_b"] in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
                inp["room_b"] = st.selectbox(f"Room type for {names['B']}", ["Studio", "1 Bedroom", "Shared"], index=0)
                inp["care_level_b"] = st.selectbox(f"Care level for {names['B']}", ["Low", "Medium", "High"], index=1)
                inp["mobility_b"] = st.selectbox(f"Mobility for {names['B']}", ["Low", "Medium", "High"], index=1)
                inp["chronic_b"] = st.selectbox(f"Chronic conditions for {names['B']}", ["None", "Some", "Multiple/Complex"], index=0)

        inp["state"] = st.selectbox("State", list(spec["lookups"]["state_multipliers"].keys()), index=0)
        c1, c2 = st.columns(2)
        if c1.button("← Back", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
        if c2.button("Next →", type="primary", use_container_width=True):
            st.session_state.step = 3
            st.rerun()

    elif st.session_state.step == 3:
        st.header("Step 3 · Finances")
        try:
            with expander("income_a", f"Income — {names['A']}", inp.get("social_security_person_a", 0.0) + inp.get("pension_person_a", 0.0)):
                inp["social_security_person_a"] = currency_input(f"Social Security — {names['A']}", "social_security_person_a", default=inp.get("social_security_person_a", 0.0), drawer_name="income_a", help="Enter monthly Social Security income.")
                inp["pension_person_a"] = currency_input(f"Pension — {names['A']}", "pension_person_a", default=inp.get("pension_person_a", 0.0), drawer_name="income_a", help="Enter monthly pension income.")
            if st.session_state.get("include_b", False):
                with expander("income_b", f"Income — {names['B']}", inp.get("social_security_person_b", 0.0) + inp.get("pension_person_b", 0.0)):
                    inp["social_security_person_b"] = currency_input(f"Social Security — {names['B']}", "social_security_person_b", default=inp.get("social_security_person_b", 0.0), drawer_name="income_b", help="Enter monthly Social Security income.")
                    inp["pension_person_b"] = currency_input(f"Pension — {names['B']}", "pension_person_b", default=inp.get("pension_person_b", 0.0), drawer_name="income_b", help="Enter monthly pension income.")
            with expander("income_household", "Income — Household", sum(inp.get(k, 0.0) for k in ["rental_income", "wages_part_time", "alimony_support", "dividends_interest", "other_income_monthly"])):
                for f in spec.get("ui_group_additions", [])[0]["fields"]:
                    inp[f["field"]] = currency_input(f["label"], f["field"], default=inp.get(f["field"], 0.0), drawer_name="income_household", help=f.get("help", f["prompt"]))
            with expander("benefits", "Benefits", inp.get("va_benefit_person_a", 0.0) + inp.get("va_benefit_person_b", 0.0)):
                inp["va_cat_a"] = st.selectbox(f"VA status — {names['A']}", list(spec["lookups"]["va_categories"].keys()), index=0, help="Select VA benefit category.")
                inp["va_benefit_person_a"] = currency_input(f"VA benefit — {names['A']}", "va_benefit_person_a", default=inp.get("va_benefit_person_a", 0.0), drawer_name="benefits")
                ltc_a_on = st.checkbox(f"{names['A']} has LTC policy", value=bool(inp.get("ltc_insurance_person_a", False)), key="ltc_insurance_person_a", on_change=mark_touched, args=("benefits",))
                inp["ltc_insurance_person_a"] = ltc_a_on
                if ltc_a_on:
                    inp["ltc_insurance_person_a_monthly"] = currency_input(f"Monthly LTC benefit — {names['A']}", "ltc_insurance_person_a_monthly", default=inp.get("ltc_insurance_person_a_monthly", 0.0), drawer_name="benefits")
                if st.session_state.get("include_b", False):
                    inp["va_cat_b"] = st.selectbox(f"VA status — {names['B']}", list(spec["lookups"]["va_categories"].keys()), index=0, help="Select VA benefit category.")
                    inp["va_benefit_person_b"] = currency_input(f"VA benefit — {names['B']}", "va_benefit_person_b", default=inp.get("va_benefit_person_b", 0.0), drawer_name="benefits")
                    ltc_b_on = st.checkbox(f"{names['B']} has LTC policy", value=bool(inp.get("ltc_insurance_person_b", False)), key="ltc_insurance_person_b", on_change=mark_touched, args=("benefits",))
                    inp["ltc_insurance_person_b"] = ltc_b_on
                    if ltc_b_on:
                        inp["ltc_insurance_person_b_monthly"] = currency_input(f"Monthly LTC benefit — {names['B']}", "ltc_insurance_person_b_monthly", default=inp.get("ltc_insurance_person_b_monthly", 0.0), drawer_name="benefits")
            with expander("home_carry", "Home costs (if keeping home)", sum(inp.get(k, 0.0) for k in ["mortgage", "taxes", "insurance", "hoa", "utilities"])):
                inp["maintain_home"] = st.checkbox("Keep home", value=inp.get("maintain_home", False))
                if inp["maintain_home"]:
                    try:
                        for f in spec["ui_groups"][3]["fields"]:
                            inp[f["field"]] = currency_input(f["label"], f["field"], default=inp.get(f["field"], 0.0), drawer_name="home_carry", help="Enter monthly cost.")
                    except Exception as e:
                        st.error(f"Error rendering home costs: {str(e)}")
            with expander("optional", "Other monthly costs (optional)", sum(inp.get(k, 0.0) for k in [f["field"] for f in spec["ui_groups"][4]["fields"]])):
                try:
                    for f in spec["ui_groups"][4]["fields"]:
                        inp[f["field"]] = currency_input(f["label"], f["field"], default=inp.get(f["field"], 0.0), drawer_name="optional", help="Leave at 0 if not applicable.")
                except Exception as e:
                    st.error(f"Error rendering optional costs: {str(e)}")
            with expander("assets_common", "Assets — Common balances", sum(inp.get(k, 0.0) for k in [f["field"] for f in spec.get("ui_group_additions", [])[1]["fields"]])):
                for f in spec.get("ui_group_additions", [])[1]["fields"]:
                    inp[f["field"]] = currency_input(f["label"], f["field"], default=inp.get(f["field"], 0.0), drawer_name="assets_common", help="Enter current balance.")
            with expander("assets_more", "More asset types (optional)", sum(inp.get(k, 0.0) for k in [f["field"] for f in spec.get("ui_group_additions", [])[2]["fields"]])):
                for f in spec.get("ui_group_additions", [])[2]["fields"]:
                    inp[f["field"]] = currency_input(f["label"], f["field"], default=inp.get(f["field"], 0.0), drawer_name="assets_more", help="Enter current balance or leave at 0.")
            home_mods_ui(inp, spec)
            inp["home_to_assets"] = st.checkbox("Include home equity in liquid assets", value=inp.get("home_to_assets", False), help="Check if you plan to sell or access home equity.")
        except Exception as e:
            st.error(f"Error in Step 3: {str(e)}")
            st.write("Please check the schema files and try again.")
        c1, c2 = st.columns(2)
        if c1.button("← Back", use_container_width=True):
            st.session_state.step = 2
            st.rerun()
        if c2.button("Calculate →", type="primary", use_container_width=True):
            st.session_state.step = 4
            st.rerun()

    elif st.session_state.step == 4:
        st.header("Step 4 · Results")
        with st.spinner("Calculating..."):
            res = compute(inp, spec)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Total Monthly Cost", mfmt(res["month_cost"]))
            st.metric("Care Cost", mfmt(res["care"]))
        with c2:
            st.metric("Household Income", mfmt(res["income"]))
            st.metric("Monthly Gap", mfmt(res["gap"]))
        with c3:
            st.metric(f"VA Benefit — {names['A']}", mfmt(res["va_a"]))
            if st.session_state.get("include_b", False):
                st.metric(f"VA Benefit — {names['B']}", mfmt(res["va_b"]))
        if res["gap"] <= 0.0:
            st.success("No deficit. Your monthly income covers the planned costs, so assets are not needed for ongoing expenses.")
        else:
            st.info(f"At a monthly deficit of {mfmt(res['gap'])}, your liquid assets of {mfmt(res['liquid'])} will last about **{res['years']:.1f} years** ({res['years']*12:.0f} months).")
            data = [{"Years Funded": res["years"]}]
            chart = alt.Chart(data).mark_bar(color="#4CAF50").encode(
                x=alt.X("Years Funded:Q", title="Years Funded"),
                tooltip=alt.Tooltip("Years Funded:Q", format=".1f")
            ).properties(width="container")
            st.altair_chart(chart, use_container_width=True)
        st.markdown("**Note**: This is an estimate. Consult a financial advisor for personalized planning.")
        if st.button("Start Over", use_container_width=True):
            st.session_state.clear()
            st.rerun()

if __name__ == "__main__":
    main()