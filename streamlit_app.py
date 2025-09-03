
# streamlit_app.py — fixed: unique keys, sidebar summary, home-sale net proceeds
import json
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import streamlit as st

APP_VERSION = "v2025-09-03-rb4"
SPEC_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"

def money(x):
    try: return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except: return 0.0
def mfmt(x):
    try: return f"${float(x):,.2f}"
    except: return "$0.00"

def read_json(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except: return {}

def load_spec():
    spec = read_json(SPEC_PATH)
    ov = read_json(OVERLAY_PATH)
    if ov:
        spec.setdefault("lookups", {}).update(ov.get("lookups", {}))
        gid = {g["id"]: g for g in spec.get("ui_groups", [])}
        for k,patch in ov.get("ui_group_overrides", {}).items():
            if k in gid:
                g = gid[k]
                if "module" in patch: g["module"]=patch["module"]
                if "label" in patch: g["label"]=patch["label"]
                if "replace_fields" in patch: g["fields"]=list(patch["replace_fields"])
        for add in ov.get("ui_group_additions", []):
            if add["id"] not in {g["id"] for g in spec.get("ui_groups", [])}:
                spec.setdefault("ui_groups", []).append(add)
    spec.setdefault("lookups", {})
    spec["lookups"].setdefault("state_multipliers", {"National":1.0})
    spec["lookups"].setdefault("room_type", {"Studio":3500, "1 Bedroom":4200, "Shared":3000})
    spec["lookups"].setdefault("care_level_adders", {"Low":200, "Medium":600, "High":1200})
    spec["lookups"].setdefault("mobility_adders", {
        "facility":{"No support needed":0,"Walker":150,"Wheelchair":300},
        "in_home":{"Low":0,"Medium":10,"High":20}
    })
    spec["lookups"].setdefault("chronic_adders", {"None":0,"Some":150,"Multiple/Complex":400})
    spec["lookups"].setdefault("in_home_care_matrix", {2:120,4:220,6:300,8:380,10:450})
    spec["lookups"].setdefault("va_categories", {
        "None":0.0,
        "Veteran only (A&A)":2358.33,
        "Veteran with spouse (A&A)":2795.67,
        "Two veterans married, both A&A (household ceiling)":3740.50,
        "Surviving spouse (A&A)":1515.58
    })
    spec.setdefault("settings", {}).setdefault("memory_care_multiplier", 1.25)
    spec["settings"].setdefault("second_person_cost", 1200.0)
    spec["settings"].setdefault("display_cap_years_funded", 30)
    spec["settings"].setdefault("ltc_monthly_add", 1800.0)
    return spec

def interp(matrix, h):
    ks = sorted(int(k) for k in matrix.keys())
    if not ks: return 0.0
    if h<=ks[0]: return float(matrix[str(ks[0])])
    if h>=ks[-1]: return float(matrix[str(ks[-1])])
    lo = max(k for k in ks if k<=h); hi = min(k for k in ks if k>=h)
    if lo==hi: return float(matrix[str(lo)])
    frac=(h-lo)/(hi-lo)
    return float(matrix[str(lo)]) + frac*(float(matrix[str(hi)])-float(matrix[str(lo)]))

def compute(inputs, spec):
    L=spec["lookups"]; S=spec["settings"]
    state_mult=float(L["state_multipliers"].get(inputs.get("state","National"),1.0))
    room=L["room_type"]; add_level=L["care_level_adders"]
    mob_fac=L["mobility_adders"]["facility"]; mob_home=L["mobility_adders"]["in_home"]
    chronic=L["chronic_adders"]; mat=L["in_home_care_matrix"]; mem=float(S["memory_care_multiplier"])

    def person(tag):
        ct=inputs.get(f"care_type_{tag}")
        lvl=inputs.get(f"care_level_{tag}","Medium")
        mob=inputs.get(f"mobility_{tag}","Medium")
        chrk=inputs.get(f"chronic_{tag}","None")
        if ct and ct.startswith("In-Home"):
            hrs=int(inputs.get(f"hours_{tag}",4) or 4)
            days=int(inputs.get(f"days_{tag}",20) or 20)
            base = interp(mat, hrs) + mob_home.get("Medium",10) + chronic.get(chrk,0)
            return money(base*days*state_mult)
        if ct in ["Assisted Living (or Adult Family Home)","Memory Care"]:
            rm=inputs.get(f"room_{tag}","Studio")
            base = float(room.get(rm,0)) + add_level.get(lvl,0) + mob_fac.get(mob,0) + chronic.get(chrk,0)
            if ct=="Memory Care": base*=mem
            return money(base*state_mult)
        return 0.0

    a=person("a"); b=person("b")
    disc = money(float(S["second_person_cost"])*state_mult) if inputs.get("care_type_a") in ["Assisted Living (or Adult Family Home)","Memory Care"] and inputs.get("care_type_b") in ["Assisted Living (or Adult Family Home)","Memory Care"] else 0.0
    care = money(a+b-disc)

    home = 0.0
    if inputs.get("maintain_home"):
        for k in ["mortgage","taxes","insurance","hoa","utilities"]: home += float(inputs.get(k,0.0))
    opt = sum(float(inputs.get(k,0.0)) for k in ["medicare","dvh","rx","personal","other_monthly"])
    month_cost = money(care + home + opt)

    # income
    hh = sum(float(inputs.get(k,0.0)) for k in [
        "ss_a","pension_a","ss_b","pension_b","disability",
        "rental_income","wages_part_time","alimony_support","dividends_interest","other_income_monthly"
    ])
    # VA
    catA=inputs.get("va_cat_a","None"); catB=inputs.get("va_cat_b","None")
    mapr=L["va_categories"].get("None",0.0)
    if "Two veterans" in catA or "Two veterans" in catB: mapr=L["va_categories"]["Two veterans married, both A&A (household ceiling)"]
    elif "Veteran with spouse" in catA or "Veteran with spouse" in catB: mapr=L["va_categories"]["Veteran with spouse (A&A)"]
    elif "Veteran only" in catA or "Veteran only" in catB: mapr=L["va_categories"]["Veteran only (A&A)"]
    elif "Surviving spouse" in catA or "Surviving spouse" in catB: mapr=L["va_categories"]["Surviving spouse (A&A)"]
    medical = money(care + float(inputs.get("medicare",0)) + float(inputs.get("dvh",0)) + float(inputs.get("rx",0)) + float(inputs.get("personal",0)))
    va_month = money(max(0.0, mapr*12 - max(0.0, hh*12 - medical*12))/12.0)
    if "Two veterans" in catA or "Two veterans" in catB:
        va_a=money(va_month/2); va_b=money(va_month/2)
    elif "Veteran" in catA or "spouse" in catA: va_a=va_month; va_b=0.0
    elif "Veteran" in catB or "spouse" in catB: va_b=va_month; va_a=0.0
    else: va_a=0.0; va_b=0.0

    income = money(hh + va_a + va_b + float(inputs.get("hecm_draw",0.0)) + float(inputs.get("heloc_draw",0.0)))
    gap = money(month_cost - income)
    return {"care":care,"home":home,"opt":opt,"month_cost":month_cost,"income":income,"gap":gap,"va_a":va_a,"va_b":va_b}

def sidebar_summary():
    st.sidebar.title("Live Summary")
    st.sidebar.caption("Updates as you type.")
    spec=load_spec(); res=compute(st.session_state.inputs, spec) if "inputs" in st.session_state else {}
    if not res: 
        st.sidebar.info("Fill in the steps to see totals."); 
        return
    st.sidebar.metric("Total monthly cost", mfmt(res["month_cost"]))
    st.sidebar.metric("Household income", mfmt(res["income"]))
    st.sidebar.metric("Monthly gap", mfmt(res["gap"]))
    st.sidebar.metric("VA benefit — A", mfmt(res["va_a"]))
    st.sidebar.metric("VA benefit — B", mfmt(res["va_b"]))

def main():
    st.set_page_config(page_title="Senior Care Planner", layout="wide")
    st.title("Senior Care Cost Planner")
    spec=load_spec()
    if "step" not in st.session_state: st.session_state.step=1
    if "inputs" not in st.session_state: st.session_state.inputs={}
    inp=st.session_state.inputs
    sidebar_summary()

    step=st.session_state.step
    st.progress(int((step-1)/3*100), text=f"Step {step} of 4")

    if step==1:
        st.header("Step 1 · Who are we planning for?")
        who = st.radio("Select the situation",[
            "I'm planning for myself",
            "I'm planning for my spouse/partner",
            "I'm planning for my parent/parent-in-law",
            "I'm planning for a couple (both parents/partners)",
            "I'm planning for a relative or POA",
            "I'm planning for a friend or someone else"
        ], index=0, key="who")
        if who=="I'm planning for myself":
            your = st.text_input("Your name", placeholder="e.g., John", key="name_you")
            st.session_state.include_b=False
            st.session_state.names={"A": your or "You","B":"Partner"}
        elif who=="I'm planning for my spouse/partner":
            a=st.text_input("Care recipient's name", placeholder="e.g., John", key="name_a")
            b=st.text_input("Your name", placeholder="e.g., Jane", key="name_b")
            st.session_state.include_b = st.checkbox("Include you for household costs", value=True, key="inc_you_household")
            st.session_state.names={"A": a or "Care Recipient", "B": b or "You"}
        elif who=="I'm planning for my parent/parent-in-law":
            a=st.text_input("Care recipient's name", placeholder="e.g., John", key="name_pa")
            b=st.text_input("Second parent's name (optional)", placeholder="e.g., Jane", key="name_pb")
            st.session_state.include_b = st.checkbox("Include the second parent for household costs", value=True, key="inc_parent_b") and bool((b or "").strip())
            st.session_state.names={"A": a or "Parent 1","B": (b or "Parent 2") if st.session_state.include_b else "Parent 2"}
        elif who=="I'm planning for a couple (both parents/partners)":
            a=st.text_input("First person's name", placeholder="e.g., John", key="name_ca")
            b=st.text_input("Second person's name", placeholder="e.g., Jane", key="name_cb")
            st.session_state.include_b=True; st.session_state.names={"A": a or "Person 1","B": b or "Person 2"}
        else:
            a=st.text_input("Care recipient's name", placeholder="e.g., John", key="name_oa")
            b=st.text_input("Spouse/partner name (optional)", placeholder="e.g., Jane", key="name_ob")
            inc=st.checkbox("Include the spouse/partner for household costs", value=False, key="inc_other_spouse")
            st.session_state.include_b = inc and bool((b or "").strip())
            st.session_state.names={"A": a or "Person A","B": (b or "Partner") if st.session_state.include_b else "Partner"}

        # Location
        states=list(spec["lookups"]["state_multipliers"].keys())
        state=st.selectbox("Location for cost estimates", states, index=states.index("National") if "National" in states else 0, key="state_sel")
        inp["state"]=state

        # Home plan
        plan=st.radio("How will the home factor into paying for care?", [
            "Keep living in the home (don't tap equity)","Sell the home (use net proceeds)","Use reverse mortgage (HECM)","Consider a HELOC (home equity line)"
        ], index=0, key="home_plan")
        inp["maintain_home"]= (plan.startswith("Keep"))
        inp["home_to_assets"]= (plan.startswith("Sell"))
        inp["expect_hecm"]= ("HECM" in plan)
        inp["expect_heloc"]= ("HELOC" in plan)

        # Re-added: net proceeds if selling
        if inp["home_to_assets"]:
            st.subheader("Home sale estimate")
            c1,c2,c3 = st.columns(3)
            with c1:
                sell = st.number_input("Estimated sale price", min_value=0.0, value=float(inp.get("sell_price",0.0)), step=1000.0, format="%.2f", key="sell_price_key")
            with c2:
                payoff = st.number_input("Est. mortgage payoff", min_value=0.0, value=float(inp.get("mortgage_payoff",0.0)), step=1000.0, format="%.2f", key="mortgage_payoff_key")
            with c3:
                fees = st.number_input("Selling costs (fees, repairs, etc.)", min_value=0.0, value=float(inp.get("selling_fees",0.0)), step=500.0, format="%.2f", key="selling_fees_key")
            net = max(0.0, sell - payoff - fees)
            inp.update({"sell_price":sell,"mortgage_payoff":payoff,"selling_fees":fees,"home_equity":net})
            st.info(f"Estimated net proceeds added to Assets: {mfmt(net)}")

        if st.button("Continue →", type="primary", key="to_step2"): st.session_state.step=2; st.rerun()

    elif step==2:
        st.header("Step 2 · Choose care plans")
        names=st.session_state.get("names",{"A":"Person A","B":"Person B"})
        include_b=st.session_state.get("include_b", False)

        def person(tag, display, default_stay=False):
            opts=["In-Home Care (professional staff such as nurses, CNAs, or aides)","Assisted Living (or Adult Family Home)","Memory Care"]
            if default_stay: opts=["Stay at Home (no paid care)"]+opts
            def_idx = 0 if default_stay else opts.index("In-Home Care (professional staff such as nurses, CNAs, or aides)")
            ct=st.selectbox(f"Care type for {display}", opts, index=def_idx, key=f"ct_{tag}",
                            help="In‑home uses hourly estimates; Assisted Living/Memory Care use monthly room + adders.")
            inp[f"care_type_{tag}"]=ct
            if ct.startswith("In-Home"):
                hrs=st.slider("Hours of paid care per day (0–24)", 0, 24, int(inp.get(f"hours_{tag}",4) or 4), 1, key=f"hrs_{tag}",
                              help="Default is 4 hours/day; adjust as needed.")
                days=st.slider("Days of paid care per month (0–31)", 0, 31, int(inp.get(f"days_{tag}",20) or 20), 1, key=f"days_{tag}",
                               help="Default is 20 days/month.")
                inp[f"hours_{tag}"]=int(hrs); inp[f"days_{tag}"]=int(days)
            elif ct in ["Assisted Living (or Adult Family Home)","Memory Care"]:
                room=st.selectbox("Room type", list(spec["lookups"]["room_type"].keys()), index=0, key=f"room_{tag}")
                inp[f"room_{tag}"]=room
            if ct=="Stay at Home (no paid care)":
                inp[f"care_level_{tag}"]="None"; inp[f"mobility_{tag}"]="None"; inp[f"chronic_{tag}"]="None"
            else:
                lvl=st.selectbox("Care level", ["Low (help with a few tasks)","Medium (daily support with several tasks)","High (extensive supervision and care)"], index=1, key=f"lvl_{tag}")
                inp[f"care_level_{tag}"]=lvl.split(" (")[0]
                mob=st.selectbox("Mobility", ["No support needed (independent)","Walker (needs walker or cane)","Wheelchair (primarily wheelchair)"], index=1, key=f"mob_{tag}")
                inp[f"mobility_{tag}"]=mob.split(" (")[0]
                cc=st.selectbox("Chronic conditions", ["None (no chronic conditions)","Some (one or two managed)","Multiple/Complex (multiple or complex care)"], index=0, key=f"cc_{tag}")
                inp[f"chronic_{tag}"]=cc.split(" (")[0]

        person("a", names.get("A","Person A"), default_stay=False)
        if include_b:
            st.subheader("Spouse / Partner / Second Parent")
            default_stay = st.session_state.get("who") in ["I'm planning for my spouse/partner","I'm planning for my parent/parent-in-law"]
            person("b", names.get("B","Person B"), default_stay=default_stay)

        c1,c2 = st.columns(2)
        if c1.button("← Back", key="back_to_step1"): st.session_state.step=1; st.rerun()
        if c2.button("Continue to finances →", type="primary", key="to_step3"): st.session_state.step=3; st.rerun()

    elif step==3:
        st.header("Step 3 · Enter financial details")
        st.caption("Enter monthly income and asset balances. The summary updates live.")
        # Give each input a unique key to avoid DuplicateElementId
        names=st.session_state.get("names",{"A":"Person A","B":"Person B"})
        with st.expander(f"Income — {names.get('A','Person A')}", expanded=False):
            inp["ss_a"]=st.number_input("Social Security (monthly)", min_value=0.0, value=float(inp.get("ss_a",0.0)), step=50.0, key="ss_a_key")
            inp["pension_a"]=st.number_input("Pension (monthly)", min_value=0.0, value=float(inp.get("pension_a",0.0)), step=50.0, key="pension_a_key")
        if st.session_state.get("include_b", False):
            with st.expander(f"Income — {names.get('B','Person B')}", expanded=False):
                inp["ss_b"]=st.number_input("Social Security (monthly)", min_value=0.0, value=float(inp.get("ss_b",0.0)), step=50.0, key="ss_b_key")
                inp["pension_b"]=st.number_input("Pension (monthly)", min_value=0.0, value=float(inp.get("pension_b",0.0)), step=50.0, key="pension_b_key")
        with st.expander("Income — Additional household", expanded=False):
            inp["rental_income"]=st.number_input("Rental income (monthly)", min_value=0.0, value=float(inp.get("rental_income",0.0)), step=50.0, key="rental_income_key")
            inp["wages_part_time"]=st.number_input("Wages (part-time)", min_value=0.0, value=float(inp.get("wages_part_time",0.0)), step=50.0, key="wages_part_time_key")
            inp["alimony_support"]=st.number_input("Alimony / support received", min_value=0.0, value=float(inp.get("alimony_support",0.0)), step=50.0, key="alimony_support_key")
            inp["dividends_interest"]=st.number_input("Dividends & interest", min_value=0.0, value=float(inp.get("dividends_interest",0.0)), step=50.0, key="dividends_interest_key")
            inp["other_income_monthly"]=st.number_input("Other income (monthly)", min_value=0.0, value=float(inp.get("other_income_monthly",0.0)), step=50.0, key="other_income_monthly_key")
        with st.expander("Benefits — VA Aid & Attendance", expanded=False):
            cats=list(spec["lookups"]["va_categories"].keys())
            def catdisplay(c): return f"{c} ({mfmt(spec['lookups']['va_categories'][c])})"
            inp["va_cat_a"]= st.selectbox(f"VA category — {names.get('A','Person A')}", [catdisplay(c) for c in cats], index=0, key="va_cat_a_key").split(" (")[0]
            if st.session_state.get("include_b", False):
                inp["va_cat_b"]= st.selectbox(f"VA category — {names.get('B','Person B')}", [catdisplay(c) for c in cats], index=0, key="va_cat_b_key").split(" (")[0]
            st.caption("We compute VA benefit automatically based on MAPR, your countable income, and medical deductions.")
        with st.expander("Other monthly costs (optional)", expanded=False):
            inp["medicare"]=st.number_input("Medicare premiums", 0.0, value=float(inp.get("medicare",0.0)), step=25.0, key="medicare_key")
            inp["dvh"]=st.number_input("Dental / vision / hearing", 0.0, value=float(inp.get("dvh",0.0)), step=25.0, key="dvh_key")
            inp["rx"]=st.number_input("Prescriptions (optional)", 0.0, value=float(inp.get("rx",0.0)), step=25.0, key="rx_key")
            inp["personal"]=st.number_input("Personal care (optional)", 0.0, value=float(inp.get("personal",0.0)), step=25.0, key="personal_key")
            inp["other_monthly"]=st.number_input("Other monthly costs", 0.0, value=float(inp.get("other_monthly",0.0)), step=25.0, key="other_monthly_key")
        with st.expander("Assets — Common balances", expanded=False):
            inp["cash_savings"]=st.number_input("Cash and savings", 0.0, value=float(inp.get("cash_savings",0.0)), step=100.0, key="cash_savings_key")
            inp["brokerage_taxable"]=st.number_input("Brokerage (taxable) total", 0.0, value=float(inp.get("brokerage_taxable",0.0)), step=100.0, key="brokerage_taxable_key")
            inp["ira_traditional"]=st.number_input("Traditional IRA balance", 0.0, value=float(inp.get("ira_traditional",0.0)), step=100.0, key="ira_traditional_key")
            inp["ira_roth"]=st.number_input("Roth IRA balance", 0.0, value=float(inp.get("ira_roth",0.0)), step=100.0, key="ira_roth_key")
            inp["ira_total"]=st.number_input("IRA total (leave 0 if using granular lines)", 0.0, value=float(inp.get("ira_total",0.0)), step=100.0, key="ira_total_key")
            inp["employer_401k"]=st.number_input("401(k) balance", 0.0, value=float(inp.get("employer_401k",0.0)), step=100.0, key="employer_401k_key")
            inp["home_equity"]=st.number_input("Home equity", 0.0, value=float(inp.get("home_equity",0.0)), step=100.0, key="home_equity_key")
            inp["annuity_surrender"]=st.number_input("Annuities (surrender value)", 0.0, value=float(inp.get("annuity_surrender",0.0)), step=100.0, key="annuity_surrender_key")

        c1,c2 = st.columns(2)
        if c1.button("← Back", key="back_to_step2"): st.session_state.step=2; st.rerun()
        if c2.button("Calculate →", type="primary", key="to_step4"): st.session_state.step=4; st.rerun()

    else:
        st.header("Step 4 · Results")
        res=compute(inp, load_spec())
        c1,c2,c3=st.columns(3)
        with c1:
            st.metric("Total monthly cost", mfmt(res["month_cost"]))
            st.metric("Care cost", mfmt(res["care"]))
        with c2:
            st.metric("Household income", mfmt(res["income"]))
            st.metric("Monthly gap", mfmt(res["gap"]))
        with c3:
            st.metric("VA benefit — A", mfmt(res["va_a"]))
            st.metric("VA benefit — B", mfmt(res["va_b"]))
        if st.button("Start over", key="start_over"):
            st.session_state.clear(); st.rerun()

if __name__ == "__main__":
    main()
