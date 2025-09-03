
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import streamlit as st

# ============== Files ==============
JSON_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"  # optional

# ============== Helpers ==============
def money(x):
    try:
        return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0

def _read_json(path: str):
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception as e:
        st.error(f"Error reading JSON: {path} -> {e}")
        return {}

def load_spec(base_path: str, overlay_path: str | None = None):
    spec = _read_json(base_path)
    if not spec:
        return {}
    if overlay_path and Path(overlay_path).exists():
        overlay = _read_json(overlay_path) or {}
        # merge lookups
        if overlay.get("lookups"):
            spec.setdefault("lookups", {}).update(overlay["lookups"])
        # replace modules if provided
        if overlay.get("modules"):
            spec["modules"] = overlay["modules"]
        # ui_group overrides
        ov = overlay.get("ui_group_overrides", {})
        by_id = {g["id"]: g for g in spec.get("ui_groups", [])}
        for gid, patch in ov.items():
            g = by_id.get(gid)
            if not g:
                continue
            if "module" in patch:
                g["module"] = patch["module"]
            field_ovs = patch.get("field_overrides", {})
            wild = field_ovs.get("*", {})
            for f in g.get("fields", []):
                for k, v in wild.items():
                    f.setdefault(k, v)
                this = field_ovs.get(f.get("label", f.get("field","")), {})
                for k, v in this.items():
                    f[k] = v
    return spec

def compute(spec, inputs):
    settings = spec.get("settings", {})
    lookups = spec.get("lookups", {})

    def in_home_hourly(hours_val: int):
        # linear interpolation across the provided matrix keys
        matrix = {int(k): v for k, v in lookups.get("in_home_care_matrix", {}).items()}
        if not matrix:
            return 0
        if hours_val in matrix:
            return matrix[hours_val]
        keys = sorted(matrix.keys())
        lo = max([k for k in keys if k <= hours_val], default=keys[0])
        hi = min([k for k in keys if k >= hours_val], default=keys[-1])
        if lo == hi:
            return matrix[lo]
        frac = (hours_val - lo) / (hi - lo)
        return matrix[lo] + frac * (matrix[hi] - matrix[lo])

    def per_person_cost(tag):
        care_type = inputs.get(f"care_type_person_{tag}")
        level     = inputs.get(f"care_level_person_{tag}")
        mobility  = inputs.get(f"mobility_person_{tag}")
        chronic   = inputs.get(f"chronic_person_{tag}")
        level_add = lookups.get("care_level_adders", {}).get(level, 0)
        mob_fac   = lookups.get("mobility_adders", {}).get("facility", {}).get(mobility, 0)
        mob_home  = lookups.get("mobility_adders", {}).get("in_home", {}).get(mobility, 0)
        chronic_add = lookups.get("chronic_adders", {}).get(chronic, 0)
        mult = lookups.get("state_multipliers", {}).get(inputs.get("state","National"), 1.0)

        if care_type and care_type.startswith("In-Home Care"):
            hours = int(inputs.get(f"hours_per_day_person_{tag}", 0))
            hourly = in_home_hourly(hours)
            base = hourly * settings.get("days_per_month", 30)
            return money((base + mob_home + chronic_add) * mult)
        elif care_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room = inputs.get(f"room_type_person_{tag}")
            base_room = lookups.get("room_type", {}).get(room, 0)
            if care_type == "Memory Care":
                base_room *= settings.get("memory_care_multiplier", 1.25)
            return money((base_room + level_add + mob_fac + chronic_add) * mult)
        return 0.0

    def shared_unit_discount():
        a_type = inputs.get("care_type_person_a")
        b_type = inputs.get("care_type_person_b")
        if not (a_type and b_type):
            return 0.0
        if not inputs.get("share_one_unit"):
            return 0.0
        fac = ["Assisted Living (or Adult Family Home)", "Memory Care"]
        if a_type in fac and b_type in fac:
            room_b = inputs.get("room_type_person_b")
            base_b = lookups.get("room_type", {}).get(room_b, 0)
            if b_type == "Memory Care":
                base_b *= settings.get("memory_care_multiplier", 1.25)
            # discount: second person cost instead of full room
            return money(base_b - settings.get("second_person_cost", 1200))
        return 0.0

    care_cost = per_person_cost("a") + per_person_cost("b") - shared_unit_discount()

    # home carry
    home_fields = ["mortgage","taxes","insurance","hoa","utilities"]
    home_sum = sum(inputs.get(k, 0.0) for k in home_fields) if inputs.get("maintain_home_household") else 0.0

    # optional costs (incl. heloc payment)
    optional_fields = [
        "medicare_premiums","dental_vision_hearing","home_modifications_monthly","other_debts_monthly",
        "pet_care","entertainment_hobbies","optional_rx","optional_personal_care","optional_phone_internet",
        "optional_life_insurance","optional_transportation","optional_family_travel","optional_auto",
        "optional_auto_insurance","optional_other","heloc_payment_monthly"
    ]
    optional_sum = sum(inputs.get(k, 0.0) for k in optional_fields)

    # benefits & income
    va_total = inputs.get("va_benefit_person_a", 0.0) + inputs.get("va_benefit_person_b", 0.0)
    ltc_add  = settings.get("ltc_monthly_add", 1800)
    ltc_total = (ltc_add if inputs.get("ltc_insurance_person_a") == "Yes" else 0) + \
                (ltc_add if inputs.get("ltc_insurance_person_b") == "Yes" else 0)

    hecm = inputs.get("hecm_draw_monthly", 0.0)
    heloc_draw = inputs.get("heloc_draw_monthly", 0.0)
    re_inv = inputs.get("re_investment_income", 0.0)

    household_income = sum([
        inputs.get("social_security_person_a", 0.0),
        inputs.get("pension_person_a", 0.0),
        inputs.get("social_security_person_b", 0.0),
        inputs.get("pension_person_b", 0.0),
        hecm, heloc_draw, re_inv
    ]) + va_total + ltc_total

    tax_rate = inputs.get("estimated_tax_rate", 0.0)  # gross by default
    household_income_after_tax = household_income * (1 - tax_rate)

    monthly_cost = money(care_cost + home_sum + optional_sum)
    gap = max(0.0, monthly_cost - household_income_after_tax)

    total_assets = inputs.get("home_equity", 0.0) + inputs.get("other_assets", 0.0)
    if gap <= 0:
        years = spec.get("settings", {}).get("display_cap_years_funded", 30)
    else:
        years = min(total_assets / (gap * 12), spec.get("settings", {}).get("display_cap_years_funded", 30))

    return {
        "monthly_cost": money(monthly_cost),
        "household_income": money(household_income_after_tax),
        "monthly_gap": money(gap),
        "total_assets": money(total_assets),
        "years_funded_cap30": round(years, 2) if years is not None else None
    }

# ============== UI CONFIG ==============
st.set_page_config(page_title="Senior Care Cost Planner", page_icon="🧭", layout="centered")
spec = load_spec(JSON_PATH, OVERLAY_PATH)
if not spec:
    st.error("Could not load calculator spec. Ensure JSON files are present and valid.")
    st.stop()

groups = {g["id"]: g for g in spec.get("ui_groups", [])}
modules = spec.get("modules", [])
lookups = spec.get("lookups", {})

# tooltips
HELP_HOURS = "Paid caregiver hours per day (0–24)."
HELP_LEVEL = "ADL context: Low = independent/minimal help; Medium = some ADLs; High = extensive ADL/cognitive support."
HELP_MOB   = "Mobility needs can change staffing and costs."
HELP_CHRON = "More complex or multiple conditions generally increase care needs."
HELP_ROOM  = "Studio = lowest cost; 1BR = standard; 2BR = largest. Actual costs vary by community."
HELP_VA_EL = "Check if they qualify for VA Aid & Attendance. If unsure, you can still preview tiers."
HELP_VA_T  = "Choose the official VA Aid & Attendance designation. Amount fills automatically; only applies if eligible."
HELP_HMOD  = "Monthly‑ize one‑time projects like ramps, grab bars, and stair lifts."

# session_state
if "step" not in st.session_state: st.session_state.step = 1
if "inputs" not in st.session_state: st.session_state.inputs = {}
if "name_hint" not in st.session_state: st.session_state.name_hint = {"A": "Person A", "B": "Person B"}
if "include_b" not in st.session_state: st.session_state.include_b = False

def progress(step:int):
    labels = ["Who & Context", "Care Plan(s)", "Finances", "Results"]
    st.progress(int((step-1)/3*100), text=f"Step {step} of 4")
    cols = st.columns(4)
    for i, c in enumerate(cols, start=1):
        with c:
            if i < step: st.markdown(f"✅ **{labels[i-1]}**")
            elif i == step: st.markdown(f"🟦 **{labels[i-1]}**")
            else: st.markdown(f"⬜ {labels[i-1]}")

st.title("🧭 Senior Care Cost Planner")
st.caption("Estimate realistic care costs, include household realities, and understand funding options.")
progress(st.session_state.step)

# ============== Step 1 ==============
if st.session_state.step == 1:
    st.header("Step 1 · Who is this plan for?")

    who = st.radio("Choose one:", [
        "Myself", "My spouse/partner", "My parent / parent-in-law", "Other relative / POA / friend", "A couple (two people)"
    ])

    c1, c2 = st.columns(2)
    if who == "A couple (two people)":
        a_name = c1.text_input("Name of Person A", value="Person A")
        b_name = c2.text_input("Name of Person B", value="Person B")
        st.session_state.name_hint = {"A": a_name or "Person A", "B": b_name or "Person B"}
        st.session_state.include_b = True
        st.session_state.inputs["person_b_in_care"] = True  # both in scope
    else:
        a_name = c1.text_input("Care recipient's name", value="Person A")
        planner = c2.text_input("Your name (planner)", value="")
        st.session_state.name_hint = {"A": a_name or "Person A", "B": "Partner"}
        st.session_state.include_b = st.checkbox("Include spouse/partner in this plan for household costs?", value=(who == "My spouse/partner"))
        if st.session_state.include_b and planner:
            st.session_state.name_hint["B"] = planner

    # State
    states = list(lookups.get("state_multipliers", {"National":1.0}).keys())
    s_idx = states.index("National") if "National" in states else 0
    state = st.selectbox("Location for cost estimates", states, index=s_idx)
    st.session_state.inputs["state"] = state

    # Home strategy
    st.markdown("**Home & funding approach**")
    home_plan = st.radio("How will the home factor into paying for care?",
                         ["Keep living in the home (don’t tap equity)",
                          "Sell the home (use net proceeds)",
                          "Use reverse mortgage (HECM)",
                          "Consider a HELOC (optional)"], index=0)
    st.session_state.inputs["maintain_home_household"] = (home_plan != "Sell the home (use net proceeds)")
    st.session_state.inputs["home_to_assets"] = (home_plan == "Sell the home (use net proceeds)")
    st.session_state.inputs["expect_hecm"]   = (home_plan == "Use reverse mortgage (HECM)")
    st.session_state.inputs["expect_heloc"]  = (home_plan == "Consider a HELOC (optional)")
    st.session_state.inputs["home_plan"]     = home_plan

    if st.button("Continue to care plan →", type="primary"):
        st.session_state.step = 2
        st.rerun()
    st.divider()

# ============== Step 2 ==============
elif st.session_state.step == 2:
    st.header(f"Step 2 · Care plan for {st.session_state.name_hint['A']}")
    inputs = st.session_state.inputs

    def render_person(tag_key: str, name_label: str):
        st.subheader(f"{name_label} — Care plan")
        care_opts = [
            "In-Home Care (professional staff such as nurses, CNAs, or aides)",
            "Assisted Living (or Adult Family Home)",
            "Memory Care"
        ]
        care = st.selectbox("Care type", care_opts, key=f"care_type_{tag_key}")
        inputs[f"care_type_person_{tag_key[-1]}"] = care

        if care.startswith("In-Home Care"):
            hrs = st.slider("Hours of care per day", 0, 24, 8, 1, help=HELP_HOURS, key=f"hours_{tag_key}")
            inputs[f"hours_per_day_person_{tag_key[-1]}"] = int(hrs)
        else:
            room = st.selectbox("Room type", list(lookups["room_type"].keys()), help=HELP_ROOM, key=f"room_{tag_key}")
            inputs[f"room_type_person_{tag_key[-1]}"] = room

        level_disp = st.selectbox("Care level", [
            "Low (independent or minimal ADL help)",
            "Medium (help with some ADLs)",
            "High (extensive ADL/cognitive support)"
        ], index=1, help=HELP_LEVEL, key=f"level_{tag_key}")
        level_key = "Low" if level_disp.startswith("Low") else "High" if level_disp.startswith("High") else "Medium"
        inputs[f"care_level_person_{tag_key[-1]}"] = level_key

        mob = st.selectbox("Mobility", list(lookups["mobility_adders"]["facility"].keys()), index=1, help=HELP_MOB, key=f"mob_{tag_key}")
        inputs[f"mobility_person_{tag_key[-1]}"] = mob
        cc = st.selectbox("Chronic conditions", list(lookups["chronic_adders"].keys()), index=1, help=HELP_CHRON, key=f"cc_{tag_key}")
        inputs[f"chronic_person_{tag_key[-1]}"] = cc

    # Person A always has a care plan
    render_person("person_a", st.session_state.name_hint["A"])

    # Optional Person B
    if st.session_state.include_b:
        st.subheader("Spouse / Partner (optional)")
        st.caption(f"Planning for **{st.session_state.name_hint['A']}**. Even if **{st.session_state.name_hint['B']}** won’t receive paid care, their costs and income affect affordability.")
        care_b = st.selectbox(f"Care type for {st.session_state.name_hint['B']}",
                              ["Stay at Home (no paid care)",
                               "In-Home Care (professional staff such as nurses, CNAs, or aides)",
                               "Assisted Living (or Adult Family Home)",
                               "Memory Care"], index=0, key="care_type_person_b")
        inputs["care_type_person_b"] = care_b
        inputs["person_b_in_care"] = care_b != "Stay at Home (no paid care)"

        if inputs["person_b_in_care"]:
            # choose separate details or copy A
            if st.checkbox("Use same care level, mobility, and chronic as Person A?", value=False):
                inputs["care_level_person_b"] = inputs["care_level_person_a"]
                inputs["mobility_person_b"] = inputs["mobility_person_a"]
                inputs["chronic_person_b"] = inputs["chronic_person_a"]
            else:
                level_b = st.selectbox("Care level (B)", [
                    "Low (independent or minimal ADL help)",
                    "Medium (help with some ADLs)",
                    "High (extensive ADL/cognitive support)"
                ], index=0, help=HELP_LEVEL, key="level_person_b")
                inputs["care_level_person_b"] = "Low" if level_b.startswith("Low") else "High" if level_b.startswith("High") else "Medium"
                mob_b = st.selectbox("Mobility (B)", list(lookups["mobility_adders"]["facility"].keys()), index=0, help=HELP_MOB, key="mob_person_b")
                inputs["mobility_person_b"] = mob_b
                cc_b = st.selectbox("Chronic conditions (B)", list(lookups["chronic_adders"].keys()), index=0, help=HELP_CHRON, key="cc_person_b")
                inputs["chronic_person_b"] = cc_b

            if care_b.startswith("In-Home Care"):
                hrsb = st.slider("Hours/day (B)", 0, 24, 6, 1, help=HELP_HOURS, key="hours_person_b")
                inputs["hours_per_day_person_b"] = int(hrsb)
            else:
                room_b = st.selectbox("Room type (B)", list(lookups["room_type"].keys()), help=HELP_ROOM, key="room_person_b")
                inputs["room_type_person_b"] = room_b

            facility_types = ["Assisted Living (or Adult Family Home)", "Memory Care"]
            if inputs["care_type_person_a"] in facility_types and care_b in facility_types:
                inputs["share_one_unit"] = st.checkbox("Share one unit?", value=False)
                if inputs["share_one_unit"]:
                    st.caption("When both are in a facility, couples can sometimes share one unit; this reduces costs for the second person.")

    # nav
    c1, c2 = st.columns(2)
    if c1.button("← Back"):
        st.session_state.step = 1
        st.rerun()
    if c2.button("Continue to finances →", type="primary"):
        st.session_state.step = 3
        st.rerun()
    st.divider()

# ============== Step 3 ==============
elif st.session_state.step == 3:
    st.header("Step 3 · Enter financial details")
    st.caption("Open a section to enter details. Leave anything at 0 (or un-checked) if it doesn’t apply.")
    inputs = st.session_state.inputs

    # VA spouse flags
    if "va_spouse_is_b" not in st.session_state: st.session_state.va_spouse_is_b = False
    if "va_both_vets_combined" not in st.session_state: st.session_state.va_both_vets_combined = False

    # Home plan banner
    if inputs.get("home_to_assets"):
        st.info("Home plan: **Sell the home** — Enter sale details below to compute net proceeds → Assets.")
    elif inputs.get("expect_hecm"):
        st.info("Home plan: **Reverse mortgage (HECM)** — Add expected monthly draw below (counts toward income).")
    elif inputs.get("expect_heloc"):
        st.info("Home plan: **Consider a HELOC** — Optional monthly draw/payment is in the Assets section.")
    else:
        st.info("Home plan: **Keep living in the home** — We’ll include mortgage/taxes/insurance/utilities.")

    # Build category map from JSON module ordering
    mod_to_ids = {}
    for g in spec.get("ui_groups", []):
        mod = g.get("module")
        if mod: mod_to_ids.setdefault(mod, []).append(g["id"])
    cat_labels = [m["label"] for m in modules]
    cat_ids = {m["label"]: m["id"] for m in modules}
    CATEGORY_MAP = {label: mod_to_ids.get(cat_ids[label], []) for label in cat_labels}

    # Sale -> Assets
    sale_net = None
    if inputs.get("home_to_assets"):
        st.markdown("### Home sale estimate")
        c1, c2, c3 = st.columns(3)
        price = c1.number_input("Expected sale price", min_value=0.0, value=0.0, step=1000.0, format="%.2f")
        payoff = c2.number_input("Remaining mortgage payoff", min_value=0.0, value=0.0, step=1000.0, format="%.2f")
        costs  = c3.number_input("Selling costs (%)", min_value=0.0, value=8.0, step=0.5, format="%.2f")
        sale_net = max(0.0, price - payoff - (costs/100.0)*price)
        st.metric("Estimated net proceeds → Assets", f"${sale_net:,.2f}")

    def render_benefits(person_label: str, gid: str):
        g = groups[gid]
        with st.expander(f"{g['label'].replace('Person A', person_label).replace('Person B', person_label)} — {g.get('prompt','')}", expanded=False):
            ans = {}
            eligible = st.checkbox(f"{person_label}: Qualifies for VA Aid & Attendance?", value=False, key=f"va_elig_{gid}", help=HELP_VA_EL)
            st.caption("VA Aid & Attendance is a **tax‑free monthly benefit** for wartime veterans and their spouses to help cover care costs.")
            tiers = lookups.get("va_tiers", [])
            choice = st.selectbox(f"{person_label}: VA designation", [t['label'] for t in tiers] or ["Not applicable"], key=f"va_tier_{gid}", help=HELP_VA_T)
            monthly = 0.0
            for t in tiers:
                if t["label"] == choice:
                    monthly = float(t.get("monthly", 0.0))
                    break
            if not eligible:
                monthly = 0.0
            st.number_input(f"{person_label}: VA benefit (auto)", min_value=0.0, value=float(monthly), step=50.0, format="%.2f", key=f"va_amt_{gid}", disabled=True)
            if eligible and monthly:
                st.caption(f"**VA impact:** adds **${monthly:,.0f}/mo** to income; reduces monthly gap by the same amount once calculated.")
            # write answers into the group's fields
            for f in g["fields"]:
                if "VA benefit" in f.get("label",""):
                    ans[f.get("label")] = monthly
            for f in g["fields"]:
                if "LTC insurance" in f.get("label",""):
                    has = st.checkbox(f"{person_label}: Has long‑term care insurance?", value=False, key=f"ltc_{gid}")
                    ans[f.get("label")] = has
            return ans, choice, eligible

    def render_group(gid: str, rename: dict | None = None):
        g = groups[gid]
        label = g["label"]
        if rename:
            label = label.replace("Person A", rename.get("A","Person A")).replace("Person B", rename.get("B","Person B"))
        # hide home carry if not keeping
        if gid == "group_home_carry" and not inputs.get("maintain_home_household"):
            return None
        with st.expander(f"{label} — {g.get('prompt','')}", expanded=False):
            ans = {}
            if gid == "group_assets":
                if inputs.get("home_to_assets"):
                    st.caption("Home equity will be populated from **Home sale estimate** above.")
                elif inputs.get("maintain_home_household"):
                    st.caption("Home equity is hidden because the plan is to **keep** the home. To access equity without selling, consider a HELOC below.")
                    if inputs.get("expect_heloc") and not inputs.get("expect_hecm"):
                        st.markdown("**Optional: Access home equity without selling (HELOC)**")
                        inputs["heloc_draw_monthly"] = st.number_input("HELOC monthly draw (adds to income)", min_value=0.0, value=float(inputs.get("heloc_draw_monthly", 0.0)), step=50.0, format="%.2f")
                        inputs["heloc_payment_monthly"] = st.number_input("HELOC monthly payment (adds to expenses)", min_value=0.0, value=float(inputs.get("heloc_payment_monthly", 0.0)), step=50.0, format="%.2f")
            for f in g["fields"]:
                fld_label = f.get("label", f["field"])
                if gid == "group_assets" and fld_label == "Other liquid assets":
                    fld_label = "Other savings & investments"
                # hide direct Home equity input if keeping or selling autocalc
                if gid == "group_assets" and "Home equity" in fld_label and (inputs.get("maintain_home_household") or inputs.get("home_to_assets")):
                    continue
                kind = f.get("kind", "currency")
                default = f.get("default", 0)
                help_txt = None
                if gid == "group_home_carry":
                    if "Mortgage" in fld_label: help_txt = "Principal & interest portion of your monthly mortgage."
                    if "Property taxes" in fld_label: help_txt = "Average monthly amount for taxes."
                    if "Home insurance" in fld_label: help_txt = "Homeowner’s/hazard insurance monthlyized."
                    if "HOA" in fld_label: help_txt = "Monthly HOA dues (if any)."
                    if "Utilities" in fld_label: help_txt = "Power, water, sewer, trash, gas."
                if gid == "group_assets" and "Other savings" in fld_label:
                    help_txt = "Checking/savings, brokerage, CDs, spendable 401k/IRA, cash reserves."
                if gid == "group_optional_costs":
                    if "Home modifications" in fld_label:
                        help_txt = HELP_HMOD
                        with st.expander("Calculate a monthly amount from a one‑time project (optional)", expanded=True):
                            one = st.number_input("One‑time modification cost ($)", min_value=0.0, value=float(inputs.get("hm_one_time", 0.0)), step=100.0, format="%.2f")
                            months = st.number_input("Spread over (months)", min_value=1, value=int(inputs.get("hm_months", 24)), step=1)
                            monthly_est = one / max(1, months)
                            st.caption(f"Estimated monthly: **${monthly_est:,.2f}**")
                            inputs["home_modifications_monthly"] = monthly_est
                    if "Medicare premiums" in fld_label: help_txt = "Monthly total for Parts B/D/Advantage premiums."
                    if "Dental" in fld_label or "vision" in fld_label: help_txt = "Out‑of‑pocket monthly average for dental/vision/hearing."
                    if "Other debts" in fld_label: help_txt = "Credit cards, personal loans, etc."
                # render
                if kind == "boolean":
                    v = st.checkbox(fld_label, value=(str(default).lower() in {"yes","true","1"}))
                    ans[fld_label] = v
                elif kind == "select":
                    v = st.selectbox(fld_label, f.get("options", []), help=help_txt)
                    ans[fld_label] = v
                else:
                    v = st.number_input(fld_label, min_value=0.0, value=float(default), step=50.0, format="%.2f", help=help_txt)
                    ans[fld_label] = v
            return ans

    name_map = {"A": st.session_state.name_hint["A"], "B": st.session_state.name_hint["B"]}
    with st.form("finances_form"):
        grouped = {}
        for cat, gids in CATEGORY_MAP.items():
            st.markdown(f"### {cat}")
            for gid in gids:
                if gid.endswith("_person_b") and not st.session_state.include_b:
                    continue
                if gid.startswith("group_benefits"):
                    person_label = name_map["A"] if gid.endswith("_person_a") else name_map["B"]
                    # spouse suppression
                    if gid.endswith("_person_b") and (st.session_state.va_spouse_is_b or st.session_state.va_both_vets_combined):
                        with st.expander(f"{groups[gid]['label'].replace('Person B', person_label)} — {groups[gid].get('prompt','')}", expanded=False):
                            st.info("VA is already accounted for in Person A’s selection. No separate VA entry needed for the spouse.")
                            ans = {f.get("label"): 0.0 for f in groups[gid]["fields"] if "VA benefit" in f.get("label","")}
                            for f in groups[gid]["fields"]:
                                if "LTC insurance" in f.get("label",""):
                                    has = st.checkbox(f"{person_label}: Has long‑term care insurance?", value=False, key=f"ltc_{gid}")
                                    ans[f.get("label")] = has
                        grouped[gid] = ans
                    else:
                        ans, choice, elig = render_benefits(person_label, gid)
                        grouped[gid] = ans
                        # spouse logic hooks only from A's selection
                        if gid.endswith("_person_a") and st.session_state.include_b:
                            if choice == "Veteran with spouse":
                                is_spouse_b = st.checkbox(f"Is {name_map['B']} the spouse included in this plan?", value=True, key="va_is_spouse_b")
                                st.session_state.va_spouse_is_b = bool(elig and is_spouse_b)
                                st.session_state.va_both_vets_combined = False
                            elif choice == "Two married veterans (both A&A)":
                                st.info("This tier reflects the combined A&A amount for two married veterans. We’ll apply the full benefit once, and you won’t need to enter a separate VA amount for the spouse.")
                                st.session_state.va_spouse_is_b = False
                                st.session_state.va_both_vets_combined = bool(elig)
                            else:
                                st.session_state.va_spouse_is_b = False
                                if choice != "Two married veterans (both A&A)":
                                    st.session_state.va_both_vets_combined = False
                else:
                    ans = render_group(gid, rename=name_map)
                    if ans is not None:
                        grouped[gid] = ans

        # Advanced
        st.markdown("### Advanced (optional)")
        col1, col2, col3 = st.columns(3)
        inputs["inflation_rate"] = col1.slider("Annual inflation (%)", 0.0, 8.0, 3.0) / 100
        inputs["estimated_tax_rate"] = col2.slider("Estimated tax on income (%)", 0.0, 30.0, 0.0) / 100
        inputs["re_investment_income"] = col3.number_input("Other household income (investments, etc.)", min_value=0.0, value=float(inputs.get("re_investment_income", 0.0)), step=50.0, format="%.2f")

        submitted = st.form_submit_button("Calculate")

    if submitted:
        # flatten grouped answers into inputs by matching labels/fields
        flat = dict(inputs)
        for gid, ans in grouped.items():
            g = groups.get(gid, {})
            for f in g.get("fields", []):
                field = f.get("field")
                label = f.get("label", field)
                if label in ans:
                    v = ans[label]
                    if isinstance(v, bool):
                        v = f.get("true_value","Yes") if v else f.get("false_value","No")
                    if isinstance(v, (int,float,str)):
                        flat[field] = v
        # sale proceeds into home_equity
        if sale_net is not None:
            flat["home_equity"] = float(sale_net)
        # compute
        st.session_state.res = compute(spec, flat)
        st.session_state.step = 4
        st.rerun()

    c1, c2 = st.columns(2)
    if c1.button("← Back"):
        st.session_state.step = 2
        st.rerun()
    st.divider()

# ============== Step 4 ==============
elif st.session_state.step == 4:
    st.header("Step 4 · Results")
    r = st.session_state.get("res", {})
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Monthly cost (all‑in)", f"${r.get('monthly_cost',0):,.2f}")
        st.metric("Monthly gap", f"${r.get('monthly_gap',0):,.2f}")
    with col2:
        st.metric("Household income", f"${r.get('household_income',0):,.2f}")
        st.metric("Assets total", f"${r.get('total_assets',0):,.2f}")
    with col3:
        y = r.get("years_funded_cap30")
        st.metric("Years funded (cap 30)", "N/A" if y is None else y)

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("← Back"):
        st.session_state.step = 3
        st.rerun()
    if c2.button("Start over"):
        st.session_state.clear()
        st.session_state.step = 1
        st.rerun()
