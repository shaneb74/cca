
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import streamlit as st

# === Filenames (keep these the same for Streamlit Cloud) ===
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
    except Exception as e:
        st.error(f"Error reading JSON: {path} -> {e}")
        return {}

def load_spec_with_overlay(base_path: str, overlay_path: str | None = None):
    spec = _read_json(base_path)
    if not spec:
        return {}
    if overlay_path and Path(overlay_path).exists():
        overlay = _read_json(overlay_path) or {}
        # 1) merge lookups
        if overlay.get("lookups"):
            spec.setdefault("lookups", {}).update(overlay["lookups"])
        # 2) allow overlay to replace modules completely (keeps ordering)
        if overlay.get("modules"):
            spec["modules"] = overlay["modules"]
        # 3) apply ui_group overrides
        overrides = overlay.get("ui_group_overrides", {})
        gid_to_group = {g["id"]: g for g in spec.get("ui_groups", [])}
        for gid, ov in overrides.items():
            g = gid_to_group.get(gid)
            if not g:  # unknown group id; skip
                continue
            if "module" in ov:
                g["module"] = ov["module"]
            field_ovs = ov.get("field_overrides", {})
            wildcard = field_ovs.get("*", {})
            for f in g.get("fields", []):
                label = f.get("label", f["field"])
                this_ov = field_ovs.get(label, {})
                # wildcard defaults
                for k, v in wildcard.items():
                    f.setdefault(k, v)
                # specific overrides
                for k, v in this_ov.items():
                    f[k] = v
        # 4) defaults (optional + skip values)
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
    """
    Merge the UI answers into a flat dict using the group specs.
    """
    flat = dict(existing_fields or {})
    groups = {g["id"]: g for g in groups_cfg}
    for gid, answers in grouped_answers.items():
        cfg = groups.get(gid)
        if not cfg:
            # allow fallbacks (like spouse income) that aren't in the JSON
            for k, v in answers.items():
                flat[k] = v
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

    def per_person_cost(person_key):
        care_type = inputs.get(f"care_type_person_{person_key}")
        care_level = inputs.get(f"care_level_person_{person_key}")
        mobility   = inputs.get(f"mobility_person_{person_key}")
        chronic    = inputs.get(f"chronic_person_{person_key}")
        care_level_add = lookups.get("care_level_adders", {}).get(care_level, 0)
        mobility_fac   = lookups.get("mobility_adders", {}).get("facility", {}).get(mobility, 0)
        mobility_home  = lookups.get("mobility_adders", {}).get("in_home", {}).get(mobility, 0)
        chronic_add    = lookups.get("chronic_adders", {}).get(chronic, 0)
        state_mult = lookups.get("state_multipliers", {}).get(inputs.get("state", "National"), 1.0)

        if care_type == "In-Home Care (professional staff such as nurses, CNAs, or aides)":
            hours = str(inputs.get(f"hours_per_day_person_{person_key}", "0"))
            hourly = lookups.get("in_home_care_matrix", {}).get(hours, 0)
            base = hourly * settings.get("days_per_month", 30)
            return money((base + mobility_home + chronic_add) * state_mult)

        elif care_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room_type = inputs.get(f"room_type_person_{person_key}")
            base_room = lookups.get("room_type", {}).get(room_type, 0)
            if care_type == "Memory Care":
                base_room *= settings.get("memory_care_multiplier", 1.25)
            base = base_room + care_level_add + mobility_fac + chronic_add
            return money(base * state_mult)

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
            room_base_b = lookups.get("room_type", {}).get(room_type_b, 0)
            if b_type == "Memory Care":
                room_base_b *= settings.get("memory_care_multiplier", 1.25)
            return money(room_base_b - settings.get("second_person_cost", 1200))
        return 0.0

    a_selected = per_person_cost("a") if inputs.get("person_a_in_care") else 0.0
    b_selected = per_person_cost("b") if inputs.get("person_b_in_care") else 0.0
    shared_adj = shared_unit_adjustment()
    care_cost_total = money(a_selected + b_selected - shared_adj)

    # Optional costs include HELOC payment if any
    optional_fields = [
        "optional_rx","optional_personal_care","optional_phone_internet","optional_life_insurance",
        "optional_transportation","optional_family_travel","optional_auto","optional_auto_insurance",
        "optional_other","heloc_payment_monthly","medicare_premiums","dental_vision_hearing",
        "home_modifications_monthly","other_debts_monthly","pet_care","entertainment_hobbies"
    ]
    optional_sum = sum(inputs.get(k, 0.0) for k in optional_fields)

    # Home carry only if keeping the home
    home_fields = ["mortgage","taxes","insurance","hoa","utilities"]
    home_sum = sum(inputs.get(k, 0.0) for k in home_fields)
    house_cost_total = home_sum if inputs.get("maintain_home_household") else 0.0

    # Benefits
    va_total  = inputs.get("va_benefit_person_a", 0.0) + inputs.get("va_benefit_person_b", 0.0)
    ltc_total = (settings.get("ltc_monthly_add", 1800) if inputs.get("ltc_insurance_person_a") == "Yes" else 0) + \
                (settings.get("ltc_monthly_add", 1800) if inputs.get("ltc_insurance_person_b") == "Yes" else 0)

    # Re-investment + HECM + HELOC draw flow into income
    reinv = inputs.get("re_investment_income", 0.0) + inputs.get("hecm_draw_monthly", 0.0) + inputs.get("heloc_draw_monthly", 0.0)

    # Household income (pre-tax)
    household_income = sum([
        inputs.get("social_security_person_a", 0.0),
        inputs.get("social_security_person_b", 0.0),
        inputs.get("pension_person_a", 0.0),
        inputs.get("pension_person_b", 0.0),
        reinv
    ]) + va_total + ltc_total

    # Optional tax + investment return adjustments
    tax_rate = inputs.get("estimated_tax_rate", 0.0)  # default 0 in case we want gross
    household_income_after_tax = household_income * (1 - tax_rate)

    # Monthly totals
    monthly_cost_full = care_cost_total + house_cost_total + optional_sum
    monthly_gap = max(0.0, monthly_cost_full - household_income_after_tax)

    # Assets
    total_assets = inputs.get("home_equity", 0.0) + inputs.get("other_assets", 0.0)

    # Years funded (simple; with cap and optional inflation tempering)
    inflation_rate = inputs.get("inflation_rate", 0.0)
    if monthly_gap <= 0:
        display_years = settings.get("display_cap_years_funded", 30)
    else:
        years_funded = total_assets / (monthly_gap * 12) if (monthly_gap > 0) else float("inf")
        if inflation_rate > 0:
            years_funded /= (1 + inflation_rate)  # rough tempering
        display_years = min(years_funded, settings.get("display_cap_years_funded", 30))

    return {
        "care_cost_total": money(care_cost_total),
        "house_cost_total": money(house_cost_total),
        "optional_sum": money(optional_sum),
        "monthly_cost": money(monthly_cost_full),
        "household_income": money(household_income_after_tax),
        "monthly_gap": money(monthly_gap),
        "total_assets": money(total_assets),
        "years_funded_cap30": (None if display_years is None or display_years == float("inf") else round(display_years,2))
    }

# ---------- UI Setup ----------
st.set_page_config(page_title="Senior Care Cost Planner", page_icon="🧭", layout="centered")
spec = load_spec_with_overlay(JSON_PATH, OVERLAY_PATH)
if not spec:
    st.error("Could not load calculator spec. Make sure the JSON files are present and valid.")
    st.stop()

groups_cfg = spec.get("ui_groups", [])
groups     = {g["id"]: g for g in groups_cfg}
lookups    = spec.get("lookups", {})
modules    = spec.get("modules", [])

# Wizard session state
if "step" not in st.session_state: st.session_state.step = 1
if "inputs" not in st.session_state: st.session_state.inputs = {}
if "grouped_answers" not in st.session_state: st.session_state.grouped_answers = {}
if "name_hint" not in st.session_state: st.session_state.name_hint = {"A": "Person A", "B": "Person B"}

# ---------- Global progress bar (+ step pills) ----------
def render_progress(step:int):
    total = 4
    pct = int((step-1)/(total-1) * 100)
    st.progress(pct, text=f"Step {step} of {total}")
    cols = st.columns(4)
    labels = ["Who & Context", "Care Plan(s)", "Finances", "Results"]
    for i, c in enumerate(cols, start=1):
        with c:
            if i < step:
                st.markdown(f"✅ **{i}. {labels[i-1]}**")
            elif i == step:
                st.markdown(f"🟦 **{i}. {labels[i-1]}**")
            else:
                st.markdown(f"⬜ {i}. {labels[i-1]}")

st.title("🧭 Senior Care Cost Planner")
st.caption("A guided way to estimate care costs, include household realities, and understand funding options.")
render_progress(st.session_state.step)

# ---------- Step 1: Who & context ----------
if st.session_state.step == 1:
    st.header("Step 1 · Who is this plan for?")

    who = st.radio(
        "Choose the option that best describes this plan:",
        ["Myself", "My spouse/partner", "My parent / parent-in-law", "Other relative / POA / friend", "A couple (two people)"],
        index=0
    )

    colA, colB = st.columns(2)
    if who == "A couple (two people)":
        name_a = colA.text_input("Name of Person A", value="Person A")
        name_b = colB.text_input("Name of Person B", value="Person B")
        st.session_state.name_hint = {"A": name_a or "Person A", "B": name_b or "Person B"}
        st.session_state.include_b = True
        st.session_state.inputs["person_a_in_care"] = True
        st.session_state.inputs["person_b_in_care"] = True
    else:
        name_a = colA.text_input("Care recipient's name", value="Person A")
        planner = colB.text_input("Your name (planner)", value="")
        st.session_state.name_hint = {"A": name_a or "Person A", "B": "Partner"}
        st.session_state.include_b = st.checkbox("Include spouse/partner in this plan for household costs?", value=(who == "My spouse/partner"))
        # If planner is spouse, auto-fill B name
        if st.session_state.include_b and planner and (who in ["My spouse/partner"]):
            st.session_state.name_hint["B"] = planner

    # State (cost multiplier)
    state_options = list(lookups.get("state_multipliers", {"National":1.0}).keys())
    state_idx = state_options.index("National") if "National" in state_options else 0
    state = st.selectbox("Location for cost estimates", state_options, index=state_idx)
    st.session_state.inputs["state"] = state

    st.markdown("**Home & funding approach**")
    home_plan = st.radio(
        "How will the current home factor into paying for care?",
        ["Keep living in the home (don’t tap equity)",
         "Sell the home (use net proceeds)",
         "Use reverse mortgage (HECM)",
         "Consider a HELOC (optional)"],
        index=0
    )
    st.session_state.inputs["maintain_home_household"] = home_plan != "Sell the home (use net proceeds)"
    st.session_state.inputs["home_to_assets"] = (home_plan == "Sell the home (use net proceeds)")
    st.session_state.inputs["expect_hecm"] = (home_plan == "Use reverse mortgage (HECM)")
    st.session_state.inputs["expect_heloc"] = (home_plan == "Consider a HELOC (optional)")
    st.session_state.inputs["home_plan"] = home_plan

    if st.button("Continue to care plan →", type="primary"):
        st.session_state.step = 2
        st.rerun()
    st.divider()

# ---------- Step 2: Care plans ----------
elif st.session_state.step == 2:
    st.header(f"Step 2 · Care plan for {st.session_state.name_hint['A']}")
    inputs = st.session_state.inputs

    def render_person_care(person_key, name_label, with_paid_toggle=False):
        st.subheader(f"{name_label} — Care plan")
        care_opts = [
            "In-Home Care (professional staff such as nurses, CNAs, or aides)",
            "Assisted Living (or Adult Family Home)",
            "Memory Care"
        ]
        care_type = st.selectbox("Care type", care_opts, key=f"care_type_{person_key}")
        inputs[f"care_type_person_{person_key[-1]}"] = care_type

        if care_type.startswith("In-Home Care"):
            st.selectbox("Hours of care per day", ["4","6","8","10","12","24"], index=2, key=f"hours_{person_key}")
            inputs[f"hours_per_day_person_{person_key[-1]}"] = st.session_state[f"hours_{person_key}"]
        else:
            st.selectbox("Room type", list(spec["lookups"]["room_type"].keys()), index=0, key=f"room_{person_key}")
            inputs[f"room_type_person_{person_key[-1]}"] = st.session_state[f"room_{person_key}"]

        st.selectbox("Care level", list(spec["lookups"]["care_level_adders"].keys()), index=1, key=f"level_{person_key}")
        inputs[f"care_level_person_{person_key[-1]}"] = st.session_state[f"level_{person_key}"]

        st.selectbox("Mobility", list(spec["lookups"]["mobility_adders"]["facility"].keys()), index=1, key=f"mob_{person_key}")
        inputs[f"mobility_person_{person_key[-1]}"] = st.session_state[f"mob_{person_key}"]

        st.selectbox("Chronic conditions", list(spec["lookups"]["chronic_adders"].keys()), index=1, key=f"cc_{person_key}")
        inputs[f"chronic_person_{person_key[-1]}"] = st.session_state[f"cc_{person_key}"]

    # Person A is always in care for this wizard (the main care recipient)
    st.session_state.inputs["person_a_in_care"] = True
    render_person_care("person_a", st.session_state.name_hint["A"])

    # Optional Person B (spouse/partner or second person)
    if st.session_state.get("include_b"):
        st.subheader("Spouse / Partner (optional)")
        st.caption(
            f"You're planning care for **{st.session_state.name_hint['A']}**. Even if **{st.session_state.name_hint['B']}** "
            "won’t receive paid care, their household costs and any income/benefits can change what’s affordable."
        )
        care_b = st.selectbox(
            f"Care type for {st.session_state.name_hint['B']}",
            ["Stay at Home (no paid care)",
             "In-Home Care (professional staff such as nurses, CNAs, or aides)",
             "Assisted Living (or Adult Family Home)",
             "Memory Care"],
            index=0, key="care_type_person_b"
        )
        inputs["care_type_person_b"] = care_b
        inputs["person_b_in_care"] = care_b != "Stay at Home (no paid care)"

        b_has_paid = inputs["person_b_in_care"]
        if b_has_paid and st.checkbox("Use same care level, mobility, and chronic conditions as Person A?", value=False):
            inputs["care_level_person_b"] = inputs["care_level_person_a"]
            inputs["mobility_person_b"]   = inputs["mobility_person_a"]
            inputs["chronic_person_b"]    = inputs["chronic_person_a"]
        elif b_has_paid:
            st.selectbox("Care level (B)", list(spec["lookups"]["care_level_adders"].keys()), index=0, key="level_person_b")
            inputs["care_level_person_b"] = st.session_state["level_person_b"]
            st.selectbox("Mobility (B)", list(spec["lookups"]["mobility_adders"]["facility"].keys()), index=0, key="mob_person_b")
            inputs["mobility_person_b"] = st.session_state["mob_person_b"]
            st.selectbox("Chronic conditions (B)", list(spec["lookups"]["chronic_adders"].keys()), index=0, key="cc_person_b")
            inputs["chronic_person_b"] = st.session_state["cc_person_b"]

        if care_b.startswith("In-Home Care"):
            st.selectbox("Hours/day (B)", ["4","6","8","10","12","24"], index=1, key="hours_person_b")
            inputs["hours_per_day_person_b"] = st.session_state["hours_person_b"]
        elif care_b in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            st.selectbox("Room type (B)", list(spec["lookups"]["room_type"].keys()), index=0, key="room_person_b")
            inputs["room_type_person_b"] = st.session_state["room_person_b"]

        # If both are in facility settings, allow shared unit discount
        facility_types = ["Assisted Living (or Adult Family Home)", "Memory Care"]
        if (inputs["care_type_person_a"] in facility_types) and (care_b in facility_types):
            inputs["share_one_unit"] = st.checkbox("Share one unit?", value=False)

    # Nav
    c1, c2 = st.columns(2)
    if c1.button("← Back"):
        st.session_state.step = 1
        st.rerun()
    if c2.button("Continue to finances →", type="primary"):
        st.session_state.step = 3
        st.rerun()
    st.divider()

# ---------- Step 3: Financials ----------
elif st.session_state.step == 3:
    st.header("Step 3 · Enter financial details")
    st.caption("Expand a section to enter what applies. Leave any field at 0 (or un-checked) if it doesn’t apply.")

    inputs = st.session_state.inputs
    keep_home = bool(inputs.get("maintain_home_household"))
    if inputs.get("home_to_assets"):
        st.info("Home plan: **Sell the home** — Enter sale details below to compute net proceeds → Assets.")
    elif inputs.get("expect_hecm"):
        st.info("Home plan: **Reverse mortgage (HECM)** — Add expected monthly draw below (counts toward income).")
    elif inputs.get("expect_heloc"):
        st.info("Home plan: **Consider a HELOC** — Optional monthly draw/payment is available inside Assets.")
    else:
        st.info("Home plan: **Keep living in the home** — We’ll include monthly carry costs (mortgage/taxes/insurance/utilities).")

    # Build category map from modules (keeps order from JSON)
    mod_to_groupids = {}
    for g in groups_cfg:
        mod = g.get("module")
        if mod:
            mod_to_groupids.setdefault(mod, []).append(g["id"])
    cat_order = [m["label"] for m in modules]
    id_by_label = {m["label"]: m["id"] for m in modules}
    CATEGORY_MAP = {label: mod_to_groupids.get(id_by_label[label], []) for label in cat_order}

    # Sale → assets
    sale_result = None
    if inputs.get("home_to_assets"):
        st.markdown("### Home sale estimate")
        c1, c2, c3 = st.columns(3)
        sale_price = c1.number_input("Expected sale price", min_value=0.0, value=0.0, step=1000.0, format="%.2f")
        payoff     = c2.number_input("Remaining mortgage payoff", min_value=0.0, value=0.0, step=1000.0, format="%.2f")
        sell_pct   = c3.number_input("Selling costs (%)", min_value=0.0, value=8.0, step=0.5, format="%.2f")
        sale_result = max(0.0, sale_price - payoff - (sell_pct/100.0)*sale_price)
        st.metric("Estimated net proceeds → Assets", f"${sale_result:,.2f}")

    grouped_answers = {}

    def render_benefits_group(person_label: str, gid: str):
        g = groups[gid]
        with st.expander(f"{g['label'].replace('Person A', person_label).replace('Person B', person_label)} — {g.get('prompt','')}", expanded=False):
            ans = {}
            # VA selector is always shown, disabled until eligible is checked (so users can see tiers)
            eligible = st.checkbox(f"{person_label}: Qualifies for VA Aid & Attendance?", value=False, key=f"va_elig_{gid}")
            va_tiers = spec.get("lookups", {}).get("va_tiers", [])
            choice = st.selectbox(f"{person_label}: VA designation", [t["label"] for t in va_tiers] or ["Not applicable"],
                                  key=f"va_tier_{gid}", disabled=not eligible)
            monthly = 0.0
            if eligible:
                for t in va_tiers:
                    if t["label"] == choice:
                        monthly = float(t.get("monthly", 0.0))
                        break
            st.number_input(f"{person_label}: VA benefit (auto)", min_value=0.0, value=float(monthly), step=50.0, format="%.2f",
                            key=f"va_amt_{gid}", disabled=True)
            if eligible and monthly:
                st.caption(f"**VA impact:** adds **${monthly:,.0f}/mo** to income; reduces monthly gap by the same amount once calculated.")
            # write into the group's VA field
            for f in g["fields"]:
                if "VA benefit" in f.get("label",""):
                    ans[f.get("label")] = monthly
                    break
            # LTC
            for f in g["fields"]:
                if "LTC insurance" in f.get("label",""):
                    label = f"{person_label}: Has long‑term care insurance?"
                    has = st.checkbox(label, value=False, key=f"ltc_{gid}")
                    ans[f.get("label")] = has
            return ans

    def render_group(gid, rename_map=None):
        g = groups[gid]
        heading = g["label"]
        if rename_map:
            heading = heading.replace("Person A", rename_map.get("A","Person A")).replace("Person B", rename_map.get("B","Person B"))
        # Hide home carry if not keeping home
        if gid == "group_home_carry" and (not keep_home):
            return None
        with st.expander(f"{heading} — {g.get('prompt','')}", expanded=False):
            ans = {}
            # Assets special behaviors
            if gid == "group_assets":
                if keep_home and not inputs.get("home_to_assets"):
                    st.caption("Home equity is hidden because the plan is to **keep** the home. "
                               "To access equity without selling, consider a HELOC below.")
                    # Optional HELOC (only when keeping home and not HECM)
                    if inputs.get("expect_heloc", False) and not inputs.get("expect_hecm", False):
                        st.markdown("**Optional: HELOC access**")
                        st.caption("Enter a monthly draw (adds to income) and a monthly payment (adds to expenses).")
                        st.session_state.inputs["heloc_draw_monthly"] = st.number_input("HELOC monthly draw (income)",
                                                                                         min_value=0.0, value=float(st.session_state.inputs.get("heloc_draw_monthly", 0.0)),
                                                                                         step=50.0, format="%.2f")
                        st.session_state.inputs["heloc_payment_monthly"] = st.number_input("HELOC monthly payment (expense)",
                                                                                           min_value=0.0, value=float(st.session_state.inputs.get("heloc_payment_monthly", 0.0)),
                                                                                           step=50.0, format="%.2f")
                if inputs.get("home_to_assets"):
                    st.caption("Home equity will be populated from the **Home sale estimate** above; no need to enter manually.")
            # Render fields
            for f in g["fields"]:
                label = f.get("label", f["field"])
                kind = f.get("kind", "currency")
                default = f.get("default", 0)
                # hide direct Home equity input if keeping home or using sale auto-proceeds
                if gid == "group_assets" and "Home equity" in label and (keep_home or inputs.get("home_to_assets")):
                    continue
                if kind == "boolean":
                    v = st.checkbox(label, value=(str(default).lower() in {"yes","true","1"}))
                    ans[label] = v
                elif kind == "select":
                    v = st.selectbox(label, f.get("options", []))
                    ans[label] = v
                else:
                    v = st.number_input(label, min_value=0.0, value=float(default), step=50.0, format="%.2f")
                    ans[label] = v
            return ans

    name_map = {"A": st.session_state.name_hint["A"], "B": st.session_state.name_hint["B"]}
    with st.form("finance_form"):
        for cat, gids in CATEGORY_MAP.items():
            st.markdown(f"### {cat}")
            for gid in gids:
                # skip spouse groups if spouse isn't included
                if gid.endswith("_person_b") and not st.session_state.get("include_b"):
                    continue
                if gid not in groups:
                    # fallback: ensure spouse income never gets missed
                    if gid.endswith("_person_b") and st.session_state.get("include_b"):
                        with st.expander(f"Income — {name_map['B']}", expanded=False):
                            ssb = st.number_input("Social Security — B", min_value=0.0, value=0.0, step=50.0, format="%.2f")
                            penb = st.number_input("Pension — B", min_value=0.0, value=0.0, step=50.0, format="%.2f")
                            othb = st.number_input("Investment/Other household income", min_value=0.0, value=0.0, step=50.0, format="%.2f")
                        grouped_answers["_income_b_fallback"] = {
                            "social_security_person_b": ssb,
                            "pension_person_b": penb,
                            "re_investment_income": othb
                        }
                    continue
                if gid.startswith("group_benefits"):
                    person_label = name_map["A"] if gid.endswith("_person_a") else name_map["B"]
                    ans = render_benefits_group(person_label, gid)
                else:
                    ans = render_group(gid, rename_map=name_map)
                if ans is not None:
                    grouped_answers[gid] = ans

        # Advanced knobs (optional)
        st.markdown("### Advanced (optional)")
        col1, col2, col3 = st.columns(3)
        st.session_state.inputs["inflation_rate"] = col1.slider("Annual inflation (%)", 0.0, 8.0, 3.0) / 100
        st.session_state.inputs["estimated_tax_rate"] = col2.slider("Estimated tax on income (%)", 0.0, 30.0, 0.0) / 100
        st.session_state.inputs["re_investment_income"] = col3.number_input("Other household income (investments, etc.)", min_value=0.0, value=float(st.session_state.inputs.get("re_investment_income", 0.0)), step=50.0, format="%.2f")

        submitted = st.form_submit_button("Calculate")
    if submitted:
        # consolidate
        flat_inputs = apply_ui_group_answers(groups_cfg, grouped_answers, existing_fields=st.session_state.inputs)
        # inject sale proceeds into home_equity
        if sale_result is not None:
            flat_inputs["home_equity"] = float(sale_result)
        # ensure VA safeguards
        flat_inputs["va_benefit_person_a"] = float(flat_inputs.get("va_benefit_person_a", 0.0))
        flat_inputs["va_benefit_person_b"] = float(flat_inputs.get("va_benefit_person_b", 0.0))
        res = compute(spec, flat_inputs)
        st.session_state.res = res
        st.session_state.step = 4
        st.rerun()
    # Nav
    c1, c2 = st.columns(2)
    if c1.button("← Back"):
        st.session_state.step = 2
        st.rerun()
    st.divider()

# ---------- Step 4: Results ----------
elif st.session_state.step == 4:
    st.header("Step 4 · Results")
    res = st.session_state.get("res", {})
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Monthly cost (all-in)", f"${res.get('monthly_cost',0):,.2f}")
        st.metric("Monthly gap", f"${res.get('monthly_gap',0):,.2f}")
    with col2:
        st.metric("Household income", f"${res.get('household_income',0):,.2f}")
        st.metric("Assets total", f"${res.get('total_assets',0):,.2f}")
    with col3:
        yf = res.get("years_funded_cap30")
        st.metric("Years funded (cap 30)", "N/A" if yf is None else yf)

    st.divider()
    # Nav
    c1, c2 = st.columns(2)
    if c1.button("← Back"):
        st.session_state.step = 3
        st.rerun()
    if c2.button("Start over"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.session_state.step = 1
        st.rerun()
