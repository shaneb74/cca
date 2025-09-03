
# streamlit_app.py — rb8: drawer stability + touched badges, home mod tiers, asset runway, wording tweak
import json
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import streamlit as st

APP_VERSION = "v2025-09-03-rb8"
SPEC_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"

# ---------- utils
def money(x):
    try:
        return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0

def mfmt(x):
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return "$0.00"

def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}

# ---------- spec
def load_spec():
    spec = read_json(SPEC_PATH)
    ov = read_json(OVERLAY_PATH)
    if ov:
        spec.setdefault("lookups", {}).update(ov.get("lookups", {}))
    spec.setdefault("lookups", {})
    spec["lookups"].setdefault("state_multipliers", {"National": 1.0})
    spec["lookups"].setdefault("room_type", {"Studio": 3500, "1 Bedroom": 4200, "Shared": 3000})
    spec["lookups"].setdefault("care_level_adders", {"Low": 200, "Medium": 600, "High": 1200})
    spec["lookups"].setdefault(
        "mobility_adders",
        {
            "facility": {"No support needed": 0, "Walker": 150, "Wheelchair": 300},
            "in_home": {"Low": 0, "Medium": 10, "High": 20},
        },
    )
    spec["lookups"].setdefault("chronic_adders", {"None": 0, "Some": 150, "Multiple/Complex": 400})
    spec["lookups"].setdefault("in_home_care_matrix", {2: 120, 4: 220, 6: 300, 8: 380, 10: 450})
    # 2025 A&A ceilings (monthly approximations)
    spec["lookups"].setdefault(
        "va_categories",
        {
            "None": 0.0,
            "Veteran only (A&A)": 2358.33,
            "Veteran with spouse (A&A)": 2795.67,
            "Two veterans married, both A&A (household ceiling)": 3740.50,
            "Surviving spouse (A&A)": 1515.58,
        },
    )
    spec.setdefault("settings", {}).setdefault("memory_care_multiplier", 1.25)
    spec["settings"].setdefault("second_person_cost", 1200.0)
    spec["settings"].setdefault("display_cap_years_funded", 30)
    return spec

def interp(matrix, h):
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
def compute(inputs, spec):
    L = spec["lookups"]
    S = spec["settings"]
    state_mult = float(L["state_multipliers"].get(inputs.get("state", "National"), 1.0))
    room = L["room_type"]
    add_level = L["care_level_adders"]
    mob_fac = L["mobility_adders"]["facility"]
    mob_home = L["mobility_adders"]["in_home"]
    chronic = L["chronic_adders"]
    mat = L["in_home_care_matrix"]
    mem = float(S["memory_care_multiplier"])

    def person(tag):
        ct = inputs.get(f"care_type_{tag}")
        lvl = inputs.get(f"care_level_{tag}", "Medium")
        mob = inputs.get(f"mobility_{tag}", "Medium")
        chrk = inputs.get(f"chronic_{tag}", "None")
        if ct and ct.startswith("In-Home"):
            hrs = int(inputs.get(f"hours_{tag}", 4) or 4)
            days = int(inputs.get(f"days_{tag}", 20) or 20)
            base = interp(mat, hrs) + mob_home.get("Medium", 10) + chronic.get(chrk, 0)
            return money(base * days * state_mult)
        if ct in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            rm = inputs.get(f"room_{tag}", "Studio")
            base = float(room.get(rm, 0)) + add_level.get(lvl, 0) + mob_fac.get(mob, 0) + chronic.get(chrk, 0)
            if ct == "Memory Care":
                base *= mem
            return money(base * state_mult)
        return 0.0

    a = person("a")
    b = person("b")
    disc = (
        money(float(S["second_person_cost"]) * state_mult)
        if inputs.get("care_type_a") in ["Assisted Living (or Adult Family Home)", "Memory Care"]
        and inputs.get("care_type_b") in ["Assisted Living (or Adult Family Home)", "Memory Care"]
        else 0.0
    )
    care = money(a + b - disc)

    home = 0.0
    if inputs.get("maintain_home"):
        for k in ["mortgage", "taxes", "insurance", "hoa", "utilities"]:
            home += float(inputs.get(k, 0.0))
    opt = sum(float(inputs.get(k, 0.0)) for k in ["medicare", "dvh", "rx", "personal", "other_monthly"])
    month_cost = money(care + home + opt)

    # income
    hh = sum(
        float(inputs.get(k, 0.0))
        for k in [
            "ss_a",
            "pension_a",
            "ss_b",
            "pension_b",
            "disability",
            "rental_income",
            "wages_part_time",
            "alimony_support",
            "dividends_interest",
            "other_income_monthly",
        ]
    )
    # LTC benefits
    hh += float(inputs.get("ltc_a_monthly", 0.0)) + float(inputs.get("ltc_b_monthly", 0.0))

    # VA
    catA = inputs.get("va_cat_a", "None")
    catB = inputs.get("va_cat_b", "None")
    mapr = L["va_categories"].get("None", 0.0)
    if "Two veterans" in catA or "Two veterans" in catB:
        mapr = L["va_categories"]["Two veterans married, both A&A (household ceiling)"]
    elif "Veteran with spouse" in catA or "Veteran with spouse" in catB:
        mapr = L["va_categories"]["Veteran with spouse (A&A)"]
    elif "Veteran only" in catA or "Veteran only" in catB:
        mapr = L["va_categories"]["Veteran only (A&A)"]
    elif "Surviving spouse" in catA or "Surviving spouse" in catB:
        mapr = L["va_categories"]["Surviving spouse (A&A)"]

    medical = money(
        care + float(inputs.get("medicare", 0)) + float(inputs.get("dvh", 0)) + float(inputs.get("rx", 0)) + float(inputs.get("personal", 0))
    )
    va_month = money(max(0.0, mapr * 12 - max(0.0, hh * 12 - medical * 12)) / 12.0)
    if "Two veterans" in catA or "Two veterans" in catB:
        va_a = money(va_month / 2)
        va_b = money(va_month / 2)
    elif "Veteran" in catA or "spouse" in catA:
        va_a = va_month
        va_b = 0.0
    elif "Veteran" in catB or "spouse" in catB:
        va_b = va_month
        va_a = 0.0
    else:
        va_a = 0.0
        va_b = 0.0

    # manual overrides
    if inputs.get("va_override_a_on"):
        va_a = money(inputs.get("va_override_a_val", 0.0))
    if inputs.get("va_override_b_on"):
        va_b = money(inputs.get("va_override_b_val", 0.0))

    income = money(hh + va_a + va_b + float(inputs.get("hecm_draw", 0.0)) + float(inputs.get("heloc_draw", 0.0)))
    gap = money(month_cost - income)
    return {"care": care, "home": home, "opt": opt, "month_cost": month_cost, "income": income, "gap": gap, "va_a": va_a, "va_b": va_b}

# ---------- sidebar
def sidebar_summary():
    st.sidebar.title("Live Summary")
    st.sidebar.caption("Updates as you type.")
    spec = load_spec()
    res = compute(st.session_state.inputs, spec) if "inputs" in st.session_state else {}
    names = st.session_state.get("names", {"A": "Person A", "B": "Person B"})
    include_b = st.session_state.get("include_b", False)
    if not res:
        st.sidebar.info("Fill in the steps to see totals.")
        return
    st.sidebar.metric("Total monthly cost", mfmt(res["month_cost"]))
    st.sidebar.metric("Household income", mfmt(res["income"]))
    st.sidebar.metric("Monthly gap", mfmt(res["gap"]))
    st.sidebar.metric(f"VA benefit — {names.get('A','Person A')}", mfmt(res["va_a"]))
    if include_b:
        st.sidebar.metric(f"VA benefit — {names.get('B','Person B')}", mfmt(res["va_b"]))

# ---------- drawer state/badges
def ensure_touched_store():
    if "drawer_touched" not in st.session_state:
        st.session_state.drawer_touched = {}
    if "open_drawers" not in st.session_state:
        st.session_state.open_drawers = {}

def mark_touched(name):
    ensure_touched_store()
    st.session_state.drawer_touched[name] = True
    st.session_state.open_drawers[name] = True

def expander_title(base, amount, name):
    ensure_touched_store()
    touched = st.session_state.drawer_touched.get(name, False)
    return f"{base} ✅ {mfmt(amount)}" if touched and amount and amount > 0 else base

def expander(name, title, amount):
    ensure_touched_store()
    expanded = bool(st.session_state.open_drawers.get(name, False))
    return st.expander(expander_title(title, amount, name), expanded=expanded)

# ---------- home mods UI
def home_mods_ui(inp):
    ensure_touched_store()
    total = 0.0
    name = "home_mods"
    with expander(name, "Home modifications (one-time costs)", inp.get("home_mod_total", 0.0)):
        st.caption("Pick what you expect to install, then choose a spec level or set your own number. Ranges reflect typical installs; your costs may vary.")
        SPEC = ["Typical", "Basic", "Custom"]

        def item(key, label, hint, low, high, avg):
            chosen = st.checkbox(label, key=f"hm_chk_{key}", value=bool(inp.get(f"hm_chk_{key}", False)), on_change=mark_touched, args=(name,))
            if not chosen:
                inp[f"hm_{key}_val"] = 0.0
                return 0.0
            spec_choice = st.selectbox(f"Spec level — {label}", SPEC, index=0, key=f"hm_spec_{key}", on_change=mark_touched, args=(name,))
            if spec_choice == "Typical":
                val = float(inp.get(f"hm_{key}_val", avg) or avg)
                st.info(f"Typical install ~ {mfmt(avg)}. Range {mfmt(low)} to {mfmt(high)}.")
                inp[f"hm_{key}_val"] = val
                mark_touched(name)
            elif spec_choice == "Basic":
                st.info(f"Basic choice set to {mfmt(low)}. Range {mfmt(low)} to {mfmt(high)}.")
                inp[f"hm_{key}_val"] = float(low)
                val = float(low)
                mark_touched(name)
            else:
                val = st.slider(
                    f"Custom estimate — {label}", int(low), int(high), int(inp.get(f"hm_{key}_val", avg) or avg), 25, key=f"hm_{key}_slider", on_change=mark_touched, args=(name,)
                )
                inp[f"hm_{key}_val"] = float(val)
            st.caption(hint)
            return float(inp[f"hm_{key}_val"])

        total += item("grab", "Grab bars and rails", "Typical installs; quantity and wall work drive costs.", 200, 500, 250)
        total += item("ramp", "Wheelchair ramps", "Length, material, and permits matter most.", 500, 3000, 1500)
        total += item("bath", "Bathroom modifications", "From grab bars to tub-to-shower conversions.", 1000, 15000, 7000)
        total += item("stair", "Stair lift", "Straight runs are cheaper than curved; rentals exist.", 1800, 8000, 2500)
        total += item("doors", "Widening doors", "Structure and electrical determine range.", 500, 2500, 1500)

        if st.checkbox("Other modifications", key="hm_other_chk", value=bool(inp.get("hm_other_chk", False)), on_change=mark_touched, args=(name,)):
            inp["hm_other_chk"] = True
            inp["hm_other_val"] = st.number_input(
                "Estimated cost — Other modifications",
                min_value=0.0,
                value=float(inp.get("hm_other_val", 0.0)),
                step=50.0,
                key="hm_other_val_num",
                on_change=mark_touched,
                args=(name,),
            )
            st.text_input("Describe and enter the expected cost.", key="hm_other_desc", on_change=mark_touched, args=(name,))
            total += float(inp.get("hm_other_val", 0.0))
        else:
            inp["hm_other_chk"] = False
            inp["hm_other_val"] = 0.0

        inp["home_mod_total"] = total
        st.info(f"Estimated total one-time home modifications: {mfmt(total)}")
    return total

# ---------- app
def main():
    st.set_page_config(page_title="Senior Care Planner", layout="wide")
    st.title("Senior Care Cost Planner")
    spec = load_spec()
    if "step" not in st.session_state:
        st.session_state.step = 1
    if "inputs" not in st.session_state:
        st.session_state.inputs = {}
    inp = st.session_state.inputs
    sidebar_summary()

    step = st.session_state.step
    st.progress(int((step - 1) / 3 * 100), text=f"Step {step} of 4")

    if step == 1:
        st.header("Step 1 · Who are we planning for?")
        who = st.radio(
            "Select the situation",
            [
                "I'm planning for myself",
                "I'm planning for my spouse/partner",
                "I'm planning for my parent/parent-in-law",
                "I'm planning for a couple (both parents/partners)",
                "I'm planning for a relative or POA",
                "I'm planning for a friend or someone else",
            ],
            index=0,
            key="who",
        )
        if who == "I'm planning for myself":
            your = st.text_input("Your name", placeholder="e.g., John", key="name_you")
            st.session_state.include_b = False
            st.session_state.names = {"A": your or "You", "B": "Partner"}
        elif who == "I'm planning for my spouse/partner":
            a = st.text_input("Care recipient's name", placeholder="e.g., John", key="name_a")
            b = st.text_input("Your name", placeholder="e.g., Jane", key="name_b")
            st.session_state.include_b = st.checkbox("Include you for household costs", value=True, key="inc_you_household")
            st.session_state.names = {"A": a or "Care Recipient", "B": b or "You"}
        elif who == "I'm planning for my parent/parent-in-law":
            a = st.text_input("Care recipient's name", placeholder="e.g., John", key="name_pa")
            b = st.text_input("Second parent's name (optional)", placeholder="e.g., Jane", key="name_pb")
            st.session_state.include_b = st.checkbox("Include the second parent for household costs", value=True, key="inc_parent_b") and bool((b or "").strip())
            st.session_state.names = {"A": a or "Parent 1", "B": (b or "Parent 2") if st.session_state.include_b else "Parent 2"}
        elif who == "I'm planning for a couple (both parents/partners)":
            a = st.text_input("First person's name", placeholder="e.g., John", key="name_ca")
            b = st.text_input("Second person's name", placeholder="e.g., Jane", key="name_cb")
            st.session_state.include_b = True
            st.session_state.names = {"A": a or "Person 1", "B": b or "Person 2"}
        else:
            a = st.text_input("Care recipient's name", placeholder="e.g., John", key="name_oa")
            b = st.text_input("Spouse/partner name (optional)", placeholder="e.g., Jane", key="name_ob")
            inc = st.checkbox("Include the spouse/partner for household costs", value=False, key="inc_other_spouse")
            st.session_state.include_b = inc and bool((b or "").strip())
            st.session_state.names = {"A": a or "Person A", "B": (b or "Partner") if st.session_state.include_b else "Partner"}

        # Location
        states = list(spec["lookups"]["state_multipliers"].keys())
        state = st.selectbox("Location for cost estimates", states, index=states.index("National") if "National" in states else 0, key="state_sel")
        inp["state"] = state

        # Home plan (wording tweak)
        plan = st.radio(
            "How will the home factor into paying for care?",
            ["Keep the home (don't tap equity)", "Sell the home (use net proceeds)", "Use reverse mortgage (HECM)", "Consider a HELOC (home equity line)"],
            index=0,
            key="home_plan",
        )
        inp["maintain_home"] = plan.startswith("Keep")
        inp["home_to_assets"] = plan.startswith("Sell")
        inp["expect_hecm"] = "HECM" in plan
        inp["expect_heloc"] = "HELOC" in plan

        # Net proceeds if selling
        if inp["home_to_assets"]:
            st.subheader("Home sale estimate")
            c1, c2, c3 = st.columns(3)
            with c1:
                sell = st.number_input("Estimated sale price", min_value=0.0, value=float(inp.get("sell_price", 0.0)), step=1000.0, format="%.2f", key="sell_price_key")
            with c2:
                payoff = st.number_input("Est. mortgage payoff", min_value=0.0, value=float(inp.get("mortgage_payoff", 0.0)), step=1000.0, format="%.2f", key="mortgage_payoff_key")
            with c3:
                fees = st.number_input("Selling costs (fees, repairs, etc.)", min_value=0.0, value=float(inp.get("selling_fees", 0.0)), step=500.0, format="%.2f", key="selling_fees_key")
            net = max(0.0, sell - payoff - fees)
            inp.update({"sell_price": sell, "mortgage_payoff": payoff, "selling_fees": fees, "home_equity": net})
            st.info(f"Estimated net proceeds added to Assets: {mfmt(net)}")

        if st.button("Continue →", type="primary", key="to_step2"):
            st.session_state.step = 2
            st.rerun()

    elif step == 2:
        st.header("Step 2 · Choose care plans")
        names = st.session_state.get("names", {"A": "Person A", "B": "Person B"})
        include_b = st.session_state.get("include_b", False)

        ALL_CT = [
            "Stay at Home (no paid care)",
            "In-Home Care (professional staff such as nurses, CNAs, or aides)",
            "Assisted Living (or Adult Family Home)",
            "Memory Care",
        ]

        def ensure_default(tag, want_default_stay):
            key = f"ct_{tag}"
            if key not in st.session_state:
                st.session_state[key] = "Stay at Home (no paid care)" if want_default_stay else "In-Home Care (professional staff such as nurses, CNAs, or aides)"
                st.session_state.inputs[f"care_type_{tag}"] = st.session_state[key]

        def person(tag, display, want_default_stay=False):
            ensure_default(tag, want_default_stay)
            ct = st.selectbox(f"Care type for {display}", ALL_CT, key=f"ct_{tag}")
            inp[f"care_type_{tag}"] = ct
            if ct.startswith("In-Home"):
                hrs = st.slider("Hours of paid care per day (0–24)", 0, 24, int(inp.get(f"hours_{tag}", 4) or 4), 1, key=f"hrs_{tag}")
                days = st.slider("Days of paid care per month (0–31)", 0, 31, int(inp.get(f"days_{tag}", 20) or 20), 1, key=f"days_{tag}")
                inp[f"hours_{tag}"] = int(hrs)
                inp[f"days_{tag}"] = int(days)
            elif ct in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
                room = st.selectbox("Room type", list(spec["lookups"]["room_type"].keys()), index=0, key=f"room_{tag}")
                inp[f"room_{tag}"] = room
            if ct == "Stay at Home (no paid care)":
                inp[f"care_level_{tag}"] = "None"
                inp[f"mobility_{tag}"] = "None"
                inp[f"chronic_{tag}"] = "None"
            else:
                lvl = st.selectbox("Care level", ["Low (help with a few tasks)", "Medium (daily support with several tasks)", "High (extensive supervision and care)"], index=1, key=f"lvl_{tag}")
                inp[f"care_level_{tag}"] = lvl.split(" (")[0]
                mob = st.selectbox("Mobility", ["No support needed (independent)", "Walker (needs walker or cane)", "Wheelchair (primarily wheelchair)"], index=1, key=f"mob_{tag}")
                inp[f"mobility_{tag}"] = mob.split(" (")[0]
                cc = st.selectbox("Chronic conditions", ["None (no chronic conditions)", "Some (one or two managed)", "Multiple/Complex (multiple or complex care)"], index=0, key=f"cc_{tag}")
                inp[f"chronic_{tag}"] = cc.split(" (")[0]

        person("a", names.get("A", "Person A"), want_default_stay=False)
        if include_b:
            st.subheader("Spouse / Partner / Second Parent")
            want_default_stay = st.session_state.get("who") in ["I'm planning for my spouse/partner", "I'm planning for my parent/parent-in-law"]
            person("b", names.get("B", "Person B"), want_default_stay=want_default_stay)

        c1, c2 = st.columns(2)
        if c1.button("← Back", key="back_to_step1"):
            st.session_state.step = 1
            st.rerun()
        if c2.button("Continue to finances →", type="primary", key="to_step3"):
            st.session_state.step = 3
            st.rerun()

    elif step == 3:
        st.header("Step 3 · Enter financial details")
        st.caption("Enter monthly income and asset balances. The summary updates live.")
        names = st.session_state.get("names", {"A": "Person A", "B": "Person B"})

        # Income A
        income_a_preview = float(inp.get("ss_a", 0.0)) + float(inp.get("pension_a", 0.0))
        with expander("income_a", f"Income — {names.get('A','Person A')}", income_a_preview):
            inp["ss_a"] = st.number_input("Social Security (monthly)", min_value=0.0, value=float(inp.get("ss_a", 0.0)), step=50.0, key="ss_a_key", on_change=mark_touched, args=("income_a",))
            inp["pension_a"] = st.number_input("Pension (monthly)", min_value=0.0, value=float(inp.get("pension_a", 0.0)), step=50.0, key="pension_a_key", on_change=mark_touched, args=("income_a",))

        # Income B
        if st.session_state.get("include_b", False):
            income_b_preview = float(inp.get("ss_b", 0.0)) + float(inp.get("pension_b", 0.0))
            with expander("income_b", f"Income — {names.get('B','Person B')}", income_b_preview):
                inp["ss_b"] = st.number_input("Social Security (monthly)", min_value=0.0, value=float(inp.get("ss_b", 0.0)), step=50.0, key="ss_b_key", on_change=mark_touched, args=("income_b",))
                inp["pension_b"] = st.number_input("Pension (monthly)", min_value=0.0, value=float(inp.get("pension_b", 0.0)), step=50.0, key="pension_b_key", on_change=mark_touched, args=("income_b",))

        # Household income
        hh_preview = float(inp.get("rental_income", 0.0)) + float(inp.get("wages_part_time", 0.0)) + float(inp.get("alimony_support", 0.0)) + float(inp.get("dividends_interest", 0.0)) + float(inp.get("other_income_monthly", 0.0))
        with expander("income_hh", "Income — Additional household", hh_preview):
            inp["rental_income"] = st.number_input("Rental income (monthly)", min_value=0.0, value=float(inp.get("rental_income", 0.0)), step=50.0, key="rental_income_key", on_change=mark_touched, args=("income_hh",))
            inp["wages_part_time"] = st.number_input("Wages (part-time)", min_value=0.0, value=float(inp.get("wages_part_time", 0.0)), step=50.0, key="wages_part_time_key", on_change=mark_touched, args=("income_hh",))
            inp["alimony_support"] = st.number_input("Alimony / support received", min_value=0.0, value=float(inp.get("alimony_support", 0.0)), step=50.0, key="alimony_support_key", on_change=mark_touched, args=("income_hh",))
            inp["dividends_interest"] = st.number_input("Dividends & interest", min_value=0.0, value=float(inp.get("dividends_interest", 0.0)), step=50.0, key="dividends_interest_key", on_change=mark_touched, args=("income_hh",))
            inp["other_income_monthly"] = st.number_input("Other income (monthly)", min_value=0.0, value=float(inp.get("other_income_monthly", 0.0)), step=50.0, key="other_income_monthly_key", on_change=mark_touched, args=("income_hh",))

        # Benefits (VA + LTC)
        va_preview = compute(inp, spec)
        with expander("benefits", "Benefits — VA Aid & Attendance, Long‑Term Care insurance, and other supports.", float(va_preview["va_a"]) + float(va_preview["va_b"]) + float(inp.get("ltc_a_monthly", 0.0)) + float(inp.get("ltc_b_monthly", 0.0))):
            c1, c2 = st.columns(2)
            cats = list(spec["lookups"]["va_categories"].keys())

            def catdisplay(c):
                return f"{c} ({mfmt(spec['lookups']['va_categories'][c])})"

            with c1:
                sel_a = st.selectbox(f"VA category — {names.get('A','Person A')}", [catdisplay(c) for c in cats], index=0, key="va_cat_a_key", on_change=mark_touched, args=("benefits",))
                inp["va_cat_a"] = sel_a.split(" (")[0]
            if st.session_state.get("include_b", False):
                with c2:
                    sel_b = st.selectbox(f"VA category — {names.get('B','Person B')}", [catdisplay(c) for c in cats], index=0, key="va_cat_b_key", on_change=mark_touched, args=("benefits",))
                    inp["va_cat_b"] = sel_b.split(" (")[0]

            st.caption("Short version: the VA category dropdown picks the ceiling (MAPR). The VA benefit (auto) is the actual computed award. You can override if you have an award letter.")
            st.text_input(f"VA benefit — {names.get('A','Person A')} (auto)", value=mfmt(va_preview["va_a"]), disabled=True, key="va_auto_a_disp")
            if st.checkbox(f"Override amount manually — {names.get('A','Person A')}", value=bool(inp.get("va_override_a_on", False)), key="va_override_a_on", on_change=mark_touched, args=("benefits",)):
                inp["va_override_a_on"] = True
                inp["va_override_a_val"] = st.number_input("VA amount override (monthly)", min_value=0.0, value=float(inp.get("va_override_a_val", 0.0)), step=25.0, key="va_override_a_val_key", on_change=mark_touched, args=("benefits",))
            else:
                inp["va_override_a_on"] = False
            if st.session_state.get("include_b", False):
                st.text_input(f"VA benefit — {names.get('B','Person B')} (auto)", value=mfmt(va_preview["va_b"]), disabled=True, key="va_auto_b_disp")
                if st.checkbox(f"Override amount manually — {names.get('B','Person B')}", value=bool(inp.get("va_override_b_on", False)), key="va_override_b_on", on_change=mark_touched, args=("benefits",)):
                    inp["va_override_b_on"] = True
                    inp["va_override_b_val"] = st.number_input("VA amount override (monthly)", min_value=0.0, value=float(inp.get("va_override_b_val", 0.0)), step=25.0, key="va_override_b_val_key", on_change=mark_touched, args=("benefits",))
                else:
                    inp["va_override_b_on"] = False

            st.markdown("---")
            st.subheader("Long‑Term Care insurance")
            ltc_a_on = st.checkbox(f"{names.get('A','Person A')} has LTC policy", value=bool(inp.get("ltc_a_on", False)), key="ltc_a_on", on_change=mark_touched, args=("benefits",))
            inp["ltc_a_on"] = ltc_a_on
            if ltc_a_on:
                inp["ltc_a_monthly"] = st.number_input("Monthly benefit amount (A)", min_value=0.0, value=float(inp.get("ltc_a_monthly", 0.0)), step=50.0, key="ltc_a_monthly_key", on_change=mark_touched, args=("benefits",))
            if st.session_state.get("include_b", False):
                ltc_b_on = st.checkbox(f"{names.get('B','Person B')} has LTC policy", value=bool(inp.get("ltc_b_on", False)), key="ltc_b_on", on_change=mark_touched, args=("benefits",))
                inp["ltc_b_on"] = ltc_b_on
                if ltc_b_on:
                    inp["ltc_b_monthly"] = st.number_input("Monthly benefit amount (B)", min_value=0.0, value=float(inp.get("ltc_b_monthly", 0.0)), step=50.0, key="ltc_b_monthly_key", on_change=mark_touched, args=("benefits",))

        # Other monthly costs
        other_preview = float(inp.get("medicare", 0.0)) + float(inp.get("dvh", 0.0)) + float(inp.get("rx", 0.0)) + float(inp.get("personal", 0.0)) + float(inp.get("other_monthly", 0.0))
        with expander("other_costs", "Other monthly costs (optional)", other_preview):
            inp["medicare"] = st.number_input("Medicare premiums", 0.0, value=float(inp.get("medicare", 0.0)), step=25.0, key="medicare_key", on_change=mark_touched, args=("other_costs",))
            inp["dvh"] = st.number_input("Dental / vision / hearing", 0.0, value=float(inp.get("dvh", 0.0)), step=25.0, key="dvh_key", on_change=mark_touched, args=("other_costs",))
            inp["rx"] = st.number_input("Prescriptions (optional)", 0.0, value=float(inp.get("rx", 0.0)), step=25.0, key="rx_key", on_change=mark_touched, args=("other_costs",))
            inp["personal"] = st.number_input("Personal care (optional)", 0.0, value=float(inp.get("personal", 0.0)), step=25.0, key="personal_key", on_change=mark_touched, args=("other_costs",))
            inp["other_monthly"] = st.number_input("Other monthly costs", 0.0, value=float(inp.get("other_monthly", 0.0)), step=25.0, key="other_monthly_key", on_change=mark_touched, args=("other_costs",))

        # Assets split
        assets_common_preview = float(inp.get("cash_savings", 0.0)) + float(inp.get("brokerage_taxable", 0.0)) + float(inp.get("ira_traditional", 0.0)) + float(inp.get("ira_roth", 0.0)) + float(inp.get("ira_total", 0.0)) + float(inp.get("employer_401k", 0.0)) + float(inp.get("home_equity", 0.0)) + float(inp.get("annuity_surrender", 0.0))
        with expander("assets_common", "Assets — Common balances", assets_common_preview):
            inp["cash_savings"] = st.number_input("Cash and savings", 0.0, value=float(inp.get("cash_savings", 0.0)), step=100.0, key="cash_savings_key", on_change=mark_touched, args=("assets_common",))
            inp["brokerage_taxable"] = st.number_input("Brokerage (taxable) total", 0.0, value=float(inp.get("brokerage_taxable", 0.0)), step=100.0, key="brokerage_taxable_key", on_change=mark_touched, args=("assets_common",))
            inp["ira_traditional"] = st.number_input("Traditional IRA balance", 0.0, value=float(inp.get("ira_traditional", 0.0)), step=100.0, key="ira_traditional_key", on_change=mark_touched, args=("assets_common",))
            inp["ira_roth"] = st.number_input("Roth IRA balance", 0.0, value=float(inp.get("ira_roth", 0.0)), step=100.0, key="ira_roth_key", on_change=mark_touched, args=("assets_common",))
            inp["ira_total"] = st.number_input("IRA total (leave 0 if using granular lines)", 0.0, value=float(inp.get("ira_total", 0.0)), step=100.0, key="ira_total_key", on_change=mark_touched, args=("assets_common",))
            inp["employer_401k"] = st.number_input("401(k) balance", 0.0, value=float(inp.get("employer_401k", 0.0)), step=100.0, key="employer_401k_key", on_change=mark_touched, args=("assets_common",))
            inp["home_equity"] = st.number_input("Home equity", 0.0, value=float(inp.get("home_equity", 0.0)), step=100.0, key="home_equity_key", on_change=mark_touched, args=("assets_common",))
            inp["annuity_surrender"] = st.number_input("Annuities (surrender value)", 0.0, value=float(inp.get("annuity_surrender", 0.0)), step=100.0, key="annuity_surrender_key", on_change=mark_touched, args=("assets_common",))

        assets_more_preview = float(inp.get("cds_balance", 0.0)) + float(inp.get("employer_403b", 0.0)) + float(inp.get("employer_457b", 0.0)) + float(inp.get("ira_sep", 0.0)) + float(inp.get("ira_simple", 0.0)) + float(inp.get("life_cash_value", 0.0)) + float(inp.get("hsa_balance", 0.0)) + float(inp.get("other_assets", 0.0))
        with expander("assets_more", "More asset types (optional)", assets_more_preview):
            inp["cds_balance"] = st.number_input("Certificates of deposit (CDs)", 0.0, value=float(inp.get("cds_balance", 0.0)), step=100.0, key="cds_balance_key", on_change=mark_touched, args=("assets_more",))
            inp["employer_403b"] = st.number_input("403(b) balance", 0.0, value=float(inp.get("employer_403b", 0.0)), step=100.0, key="employer_403b_key", on_change=mark_touched, args=("assets_more",))
            inp["employer_457b"] = st.number_input("457(b) balance", 0.0, value=float(inp.get("employer_457b", 0.0)), step=100.0, key="employer_457b_key", on_change=mark_touched, args=("assets_more",))
            inp["ira_sep"] = st.number_input("SEP IRA balance", 0.0, value=float(inp.get("ira_sep", 0.0)), step=100.0, key="ira_sep_key", on_change=mark_touched, args=("assets_more",))
            inp["ira_simple"] = st.number_input("SIMPLE IRA balance", 0.0, value=float(inp.get("ira_simple", 0.0)), step=100.0, key="ira_simple_key", on_change=mark_touched, args=("assets_more",))
            inp["life_cash_value"] = st.number_input("Life insurance cash value", 0.0, value=float(inp.get("life_cash_value", 0.0)), step=100.0, key="life_cash_value_key", on_change=mark_touched, args=("assets_more",))
            inp["hsa_balance"] = st.number_input("HSA balance", 0.0, value=float(inp.get("hsa_balance", 0.0)), step=100.0, key="hsa_balance_key", on_change=mark_touched, args=("assets_more",))
            inp["other_assets"] = st.number_input("Other assets (catch‑all)", 0.0, value=float(inp.get("other_assets", 0.0)), step=100.0, key="other_assets_key", on_change=mark_touched, args=("assets_more",))

        # Home modifications drawer
        hm_total = home_mods_ui(inp)

        c1, c2 = st.columns(2)
        if c1.button("← Back", key="back_to_step2"):
            st.session_state.step = 2
            st.rerun()
        if c2.button("Calculate →", type="primary", key="to_step4"):
            st.session_state.step = 4
            st.rerun()

    else:
        st.header("Step 4 · Results")
        res = compute(inp, load_spec())
        names = st.session_state.get("names", {"A": "Person A", "B": "Person B"})
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Total monthly cost", mfmt(res["month_cost"]))
            st.metric("Care cost", mfmt(res["care"]))
        with c2:
            st.metric("Household income", mfmt(res["income"]))
            st.metric("Monthly gap", mfmt(res["gap"]))
        with c3:
            st.metric(f"VA benefit — {names.get('A','Person A')}", mfmt(res["va_a"]))
            if st.session_state.get("include_b", False):
                st.metric(f"VA benefit — {names.get('B','Person B')}", mfmt(res["va_b"]))

        # Assets duration (runway)
        liquid = 0.0
        include_home = bool(st.session_state.inputs.get("home_to_assets"))
        liquid += float(inp.get("cash_savings", 0.0)) + float(inp.get("brokerage_taxable", 0.0)) + float(inp.get("ira_traditional", 0.0)) + float(inp.get("ira_roth", 0.0)) + float(inp.get("ira_total", 0.0)) + float(inp.get("employer_401k", 0.0)) + float(inp.get("annuity_surrender", 0.0)) + float(inp.get("cds_balance", 0.0)) + float(inp.get("employer_403b", 0.0)) + float(inp.get("employer_457b", 0.0)) + float(inp.get("ira_sep", 0.0)) + float(inp.get("ira_simple", 0.0)) + float(inp.get("life_cash_value", 0.0)) + float(inp.get("hsa_balance", 0.0)) + float(inp.get("other_assets", 0.0))
        if include_home:
            liquid += float(inp.get("home_equity", 0.0))
        # subtract one-time home modifications
        liquid = max(0.0, liquid - float(inp.get("home_mod_total", 0.0)))
        deficit = max(0.0, res["gap"])
        if deficit <= 0.0:
            st.success("No deficit. Monthly income covers current plan, so assets are not required to fund ongoing costs.")
        else:
            years = liquid / (deficit * 12.0)
            months = years * 12.0
            st.info(f"At the current deficit of {mfmt(deficit)} per month, liquid assets of {mfmt(liquid)} last about **{years:.1f} years** ({months:.0f} months).")

        if st.button("Start over", key="start_over"):
            st.session_state.clear()
            st.rerun()

if __name__ == "__main__":
    main()
