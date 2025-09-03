
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import streamlit as st

# ============================
# App Config & Constants
# ============================

JSON_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"

APP_TITLE = "Senior Care Cost Planner"
APP_SUBTITLE = "A simple step‑by‑step guide for estimating care costs and affordability"

THEME_CSS = """
<style>
/* Larger, senior‑friendly sizing */
:root {
  --base-font-size: 18px;
}
html, body, [class*="css"]  {
  font-size: var(--base-font-size);
  line-height: 1.5;
}
h1, h2, h3 { font-weight: 700; }
h1 { font-size: 1.8rem; }
h2 { font-size: 1.4rem; }
h3 { font-size: 1.2rem; }
/* Buttons & inputs */
.stButton>button {
  padding: 0.75rem 1.25rem;
  border-radius: 12px;
  font-size: 1rem;
}
input, select, textarea { font-size: 1rem !important; }
[data-testid="stSidebar"] { width: 360px; min-width: 360px; }
/* High‑contrast section headers */
.block-container h2, .block-container h3 {
  color: #111827;
}
.small-muted { color: #4b5563; font-size: 0.95rem; }
.helptext { color: #374151; font-size: 0.95rem; }
div[data-testid="stMetricValue"] { font-size: 1.4rem; }
hr { border: 0; height: 1px; background: #e5e7eb; margin: 0.75rem 0; }
</style>
"""

# ============================
# Helpers
# ============================

def money(x) -> float:
    try:
        return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0

def mfmt(x: float) -> str:
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return "$0.00"

def _read_json(path: str) -> Dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception as e:
        st.error(f"Error reading JSON: {path} -> {e}")
        return {}

def load_spec(base_path: str, overlay_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Merge base spec with overlay using sensible precedence:
    - overlay.lookups extends/overrides base.lookups
    - overlay.modules replaces base.modules if provided
    - overlay.ui_group_overrides can:
        * patch fields via field_overrides
        * replace_fields: replace entire fields list
        * append_fields: append new fields
    - overlay.ui_group_additions: add new ui_groups
    """
    spec = _read_json(base_path)
    if not spec:
        return {}

    if overlay_path and Path(overlay_path).exists():
        overlay = _read_json(overlay_path) or {}
        # Merge lookups
        if overlay.get("lookups"):
            spec.setdefault("lookups", {}).update(overlay["lookups"])
        # Replace modules
        if overlay.get("modules"):
            spec["modules"] = overlay["modules"]
        # Patch UI groups
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
                # Match by label first, then field
                this = field_ovs.get(f.get("label", f.get("field", "")), {})
                for k, v in this.items():
                    f[k] = v
    return spec

def compute_results(inputs: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    settings = spec.get("settings", {})
    lookups = spec.get("lookups", {})

    def in_home_hourly(hours_val: int) -> float:
        matrix = {int(k): float(v) for k, v in lookups.get("in_home_care_matrix", {}).items()}
        if not matrix:
            return 0.0
        if hours_val in matrix:
            return matrix[hours_val]
        keys = sorted(matrix.keys())
        lo = max([k for k in keys if k <= hours_val], default=keys[0])
        hi = min([k for k in keys if k >= hours_val], default=keys[-1])
        if lo == hi:
            return matrix[lo]
        frac = (hours_val - lo) / (hi - lo) if hi != lo else 0
        return matrix[lo] + frac * (matrix[hi] - matrix[lo])

    def per_person_cost(tag: str) -> float:
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
            hours = int(inputs.get(f"hours_per_day_person_{tag}", 0) or 0)
            hourly = in_home_hourly(hours)
            base = hourly * settings.get("days_per_month", 30)
            return money((base + mob_home + chronic_add) * mult)
        elif care_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room = inputs.get(f"room_type_person_{tag}")
            base_room = lookups.get("room_type", {}).get(room, 0)
            base = base_room + level_add + mob_fac + chronic_add
            if care_type == "Memory Care":
                base *= settings.get("memory_care_multiplier", 1.25)
            return money(base * mult)
        return 0.0

    def shared_unit_discount() -> float:
        a_type = inputs.get("care_type_person_a")
        b_type = inputs.get("care_type_person_b")
        if not (a_type and b_type):
            return 0.0
        if a_type in ["Assisted Living (or Adult Family Home)", "Memory Care"] and b_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room = inputs.get("room_type_person_a")
            base_a = lookups.get("room_type", {}).get(room, 0)
            if a_type == "Memory Care":
                base_a *= settings.get("memory_care_multiplier", 1.25)
            return money(base_a - settings.get("second_person_cost", 1200))
        return 0.0

    # Core costs
    care_cost = per_person_cost("a") + per_person_cost("b") - shared_unit_discount()

    # Home carry (only if keeping the home)
    home_fields = ["mortgage","taxes","insurance","hoa","utilities"]
    home_sum = sum(inputs.get(k, 0.0) for k in home_fields) if inputs.get("maintain_home_household") else 0.0

    # Optional monthly
    optional_fields = [
        "medicare_premiums","dental_vision_hearing","home_modifications_monthly","other_debts_monthly",
        "pet_care","entertainment_hobbies","optional_rx","optional_personal_care","optional_phone_internet",
        "optional_life_insurance","optional_transportation","optional_family_travel","optional_auto",
        "optional_auto_insurance","optional_other","heloc_payment_monthly"
    ]
    optional_sum = sum(inputs.get(k, 0.0) for k in optional_fields)

    # Benefits and LTC
    va_total = inputs.get("va_benefit_person_a", 0.0) + inputs.get("va_benefit_person_b", 0.0)
    ltc_add  = settings.get("ltc_monthly_add", 1800)
    ltc_total = (ltc_add if inputs.get("ltc_insurance_person_a") == "Yes" else 0) + \
                (ltc_add if inputs.get("ltc_insurance_person_b") == "Yes" else 0)

    # Other income injections
    hecm = inputs.get("hecm_draw_monthly", 0.0)
    heloc_draw = inputs.get("heloc_draw_monthly", 0.0)
    re_inv = inputs.get("re_investment_income", 0.0)

    household_income = sum([
        inputs.get("social_security_person_a", 0.0),
        inputs.get("pension_person_a", 0.0),
        inputs.get("social_security_person_b", 0.0),
        inputs.get("pension_person_b", 0.0),
        inputs.get("disability_income", 0.0),
        inputs.get("rental_income", 0.0),
        inputs.get("dividends_interest", 0.0),
        inputs.get("wages_part_time", 0.0),
        inputs.get("other_income_monthly", 0.0),
        va_total, hecm, heloc_draw, re_inv, ltc_total
    ])

    optional_and_home = optional_sum + home_sum
    monthly_cost = care_cost + optional_and_home

    # Assets
    total_assets = sum([
        inputs.get("home_equity", 0.0),
        inputs.get("other_assets", 0.0),
        inputs.get("cash_savings", 0.0),
        inputs.get("ira_total", 0.0),
        inputs.get("employer_retirement_total", 0.0),
        inputs.get("brokerage_taxable", 0.0),
        inputs.get("other_assets_grouped", 0.0)
    ])

    gap = monthly_cost - household_income
    gap = money(gap)

    # Years funded calc (cap at display setting)
    years = None
    if gap <= 0:
        years = None  # covered by income
    else:
        monthly_gap = max(0.0, gap)
        if total_assets > 0 and monthly_gap > 0:
            years = min(int(total_assets // monthly_gap // 12), spec.get("settings", {}).get("display_cap_years_funded", 30))

    return {
        "care_cost": money(care_cost),
        "home_sum": money(home_sum),
        "optional_sum": money(optional_sum),
        "monthly_cost": money(monthly_cost),
        "household_income": money(household_income),
        "monthly_gap": money(gap),
        "total_assets": money(total_assets),
        "years_funded_cap30": years,
    }

# ============================
# UI Pieces
# ============================

def sidebar_summary(results: Dict[str, Any], step: int):
    st.sidebar.title("Live Summary")
    st.sidebar.caption("Updates as you make changes.")
    if not results:
        st.sidebar.info("Complete steps to see your summary.")
        return
    st.sidebar.metric("Care cost", mfmt(results.get("care_cost", 0)))
    st.sidebar.metric("Home + optionals", mfmt(results.get("home_sum",0) + results.get("optional_sum",0)))
    st.sidebar.metric("Total monthly cost", mfmt(results.get("monthly_cost",0)))
    st.sidebar.metric("Household income", mfmt(results.get("household_income",0)))
    gap = results.get("monthly_gap", 0)
    color = "🔴" if gap > 0 else "🟢"
    st.sidebar.metric(f"{color} Monthly gap", mfmt(gap))
    y = results.get("years_funded_cap30")
    st.sidebar.metric("Years funded (cap 30)", "N/A" if y is None else y)
    st.sidebar.markdown("---")
    with st.sidebar.expander("Save or Load Plan", expanded=False):
        save_btn = st.button("Download current plan (JSON)", key="save_json_btn")
        if save_btn:
            st.session_state["_download_plan"] = json.dumps(st.session_state.get("inputs", {}), indent=2)
        if "_download_plan" in st.session_state:
            st.download_button("Save file", st.session_state["_download_plan"], file_name="care_plan.json", mime="application/json")
        up = st.file_uploader("Load a saved plan", type=["json"], key="plan_upload")
        if up is not None:
            try:
                st.session_state.inputs = json.loads(up.getvalue().decode("utf-8"))
                st.success("Loaded plan data.")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Could not load plan: {e}")

def progress_header(step: int):
    labels = ["Who & Context", "Care Plan(s)", "Finances", "Results"]
    pct = int((step-1)/3*100)
    st.progress(pct, text=f"Step {step} of 4")
    cols = st.columns(4)
    for i, c in enumerate(cols, start=1):
        with c:
            if i < step: st.markdown(f"✅ **{labels[i-1]}**")
            elif i == step: st.markdown(f"🟦 **{labels[i-1]}**")
            else: st.markdown(f"▫️ {labels[i-1]}")

def validate_basic(inputs: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    # Simple contradictions to assist seniors
    a_in = inputs.get("care_type_person_a")
    b_in = inputs.get("care_type_person_b")
    if inputs.get("person_b_in_care") and not b_in:
        return False, "You marked the spouse/partner as 'in care' but didn’t choose their care type."
    return True, None

# ============================
# Main App
# ============================

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)

    if "step" not in st.session_state: st.session_state.step = 1
    if "inputs" not in st.session_state: st.session_state.inputs = {}
    if "name_hint" not in st.session_state: st.session_state.name_hint = {"A": "Person A", "B": "Person B"}
    if "include_b" not in st.session_state: st.session_state.include_b = False

    spec = load_spec(JSON_PATH, OVERLAY_PATH)
    if not spec:
        st.error("Could not load calculator spec.")
        st.stop()

    lookups = spec.get("lookups", {})
    groups = {g["id"]: g for g in spec.get("ui_groups", [])}

    HELP = {
        "HOURS": "Paid caregiver hours per day (0–24).",
        "LEVEL": "Low = little help; Medium = some ADLs; High = extensive ADL or memory support.",
        "MOB": "Mobility affects staffing and costs.",
        "CHRON": "Multiple or complex conditions generally increase care needs.",
        "ROOM": "Studio is least expensive. Actual rates vary by community.",
        "VA_EL": "If you’re not sure, pick 'Not sure' to preview estimates.",
        "HM": "Spread one‑time home changes as a monthly estimate."
    }

    # Live summary scaffold
    results_for_sidebar = {}

    step = st.session_state.step
    progress_header(step)

    # ================= Step 1: Who & Context =================
    if step == 1:
        c1, c2 = st.columns([2,1])
        with c1:
            st.header("Step 1 · Who are we planning for?")
            who = st.radio("Select the situation", [
                "I'm planning for myself",
                "I'm planning for my spouse/partner",
                "I'm planning for my parent/parent‑in‑law",
                "I'm planning for a relative or POA",
                "I'm planning for a friend or someone else"
            ], index=2)
            a_name = st.text_input("Care recipient's name", placeholder="e.g., Mary")
            planner = st.text_input("Your name", placeholder="e.g., Alex")
            include_spouse = st.checkbox("Include their spouse/partner for household costs?", value=False)
            st.session_state.include_b = include_spouse
            st.session_state.name_hint = {"A": a_name or "Person A", "B": "Partner"}

            # Location
            states = list(lookups.get("state_multipliers", {"National":1.0}).keys())
            if "Washington" not in states:
                states.append("Washington")
            states = (["National"] if "National" in states else []) + sorted([s for s in states if s != "National"])
            s_idx = states.index("National") if "National" in states else 0
            state = st.selectbox("Location for cost estimates", states, index=s_idx)
            st.session_state.inputs["state"] = state

            # Home plan
            st.markdown("**Home & funding approach**")
            home_plan = st.radio("How will the home factor into paying for care?", [
                "Keep living in the home (don’t tap equity)",
                "Sell the home (use net proceeds)",
                "Use reverse mortgage (HECM)",
                "Consider a HELOC (home equity line)"
            ], index=0)
            inp = st.session_state.inputs
            inp["maintain_home_household"] = (home_plan == "Keep living in the home (don’t tap equity)")
            inp["home_to_assets"] = (home_plan == "Sell the home (use net proceeds)")
            inp["expect_hecm"] = (home_plan == "Use reverse mortgage (HECM)")
            inp["expect_heloc"] = (home_plan == "Consider a HELOC (home equity line)")

            if inp["home_to_assets"]:
                st.markdown("**Home sale estimate**")
                sell_price = st.number_input("Estimated sale price", min_value=0.0, value=float(inp.get("sell_price", 0.0)), step=1000.0, format="%.2f")
                mortgage_payoff = st.number_input("Est. mortgage payoff", min_value=0.0, value=float(inp.get("mortgage_payoff", 0.0)), step=1000.0, format="%.2f")
                fees = st.number_input("Selling costs (fees, repairs, etc.)", min_value=0.0, value=float(inp.get("selling_fees", 0.0)), step=500.0, format="%.2f")
                net = max(0.0, sell_price - mortgage_payoff - fees)
                st.info(f"Estimated **net proceeds**: {mfmt(net)} → will appear in Assets later.")
                inp["sell_price"], inp["mortgage_payoff"], inp["selling_fees"] = sell_price, mortgage_payoff, fees
                inp["home_equity"] = net

        with c2:
            st.info("Tip: You can save your plan from the sidebar at any time.")

        c1, c2 = st.columns(2)
        if c1.button("Continue →", type="primary"):
            st.session_state.step = 2
            st.experimental_rerun()

    # ================= Step 2: Care Plans =================
    elif step == 2:
        st.header("Step 2 · Choose care plans")
        inp = st.session_state.inputs

        def render_person(tag_key: str, display_name: str):
            st.subheader(display_name)
            care = st.selectbox(f"Care type for {display_name}", [
                "Stay at Home (no paid care)",
                "In-Home Care (professional staff such as nurses, CNAs, or aides)",
                "Assisted Living (or Adult Family Home)",
                "Memory Care"
            ], index=0, key=f"care_type_{tag_key}")
            inp[f"care_type_person_{tag_key[-1]}"] = care
            inp[f"person_{tag_key[-1]}_in_care"] = (care != "Stay at Home (no paid care)")

            if care.startswith("In-Home Care"):
                hours = st.number_input("Hours of paid care per day", min_value=0, max_value=24, value=int(inp.get(f"hours_per_day_person_{tag_key[-1]}", 0)), step=1, key=f"hours_{tag_key}")
                inp[f"hours_per_day_person_{tag_key[-1]}"] = int(hours)
            elif care in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
                room = st.selectbox("Room type", list(st.session_state.get("_room_types", []) or spec["lookups"]["room_type"].keys()), index=0, key=f"room_{tag_key}")
                inp[f"room_type_person_{tag_key[-1]}"] = room

            level = st.selectbox("Care level", ["Low", "Medium", "High"], index=1, key=f"level_{tag_key}")
            inp[f"care_level_person_{tag_key[-1]}"] = level

            mob = st.selectbox("Mobility", list(spec["lookups"]["mobility_adders"]["facility"].keys()), index=1, key=f"mob_{tag_key}")
            inp[f"mobility_person_{tag_key[-1]}"] = mob

            cc = st.selectbox("Chronic conditions", list(spec["lookups"]["chronic_adders"].keys()), index=1, key=f"cc_{tag_key}")
            inp[f"chronic_person_{tag_key[-1]}"] = cc

        # preload room types for predictable ordering
        st.session_state["_room_types"] = list(spec.get("lookups", {}).get("room_type", {}).keys())

        render_person("person_a", st.session_state.name_hint.get("A", "Person A"))
        if st.session_state.include_b:
            st.divider()
            st.subheader("Spouse / Partner")
            render_person("person_b", st.session_state.name_hint.get("B", "Person B"))

        c1, c2 = st.columns(2)
        if c1.button("← Back"):
            st.session_state.step = 1
            st.experimental_rerun()
        if c2.button("Continue to finances →", type="primary"):
            st.session_state.step = 3
            st.experimental_rerun()

    # ================= Step 3: Finances =================
    elif step == 3:
        st.header("Step 3 · Enter financial details")
        st.caption("Enter **monthly income** (not withdrawals) and **asset balances**. If something doesn’t apply, leave it at 0.")

        inp = st.session_state.inputs
        groups = {g["id"]: g for g in spec.get("ui_groups", [])}

        # Show home plan hint
        if inp.get("home_to_assets"):
            st.info("Home plan: **Sell the home** — Net proceeds auto‑populate in Assets.")
        elif inp.get("expect_hecm"):
            st.info("Home plan: **Reverse mortgage (HECM)** — Add expected monthly draw in Assets.")
        elif inp.get("expect_heloc"):
            st.info("Home plan: **Consider a HELOC** — Optional draw and payment in Assets.")
        else:
            st.info("Home plan: **Keep living in the home** — Mortgage/taxes/insurance/utilities will be included.")

        # Render group helper
        def render_group(gid: str, rename: Optional[Dict[str,str]] = None):
            g = groups[gid]
            label = g["label"]
            if rename:
                label = label.replace("Person A", rename.get("A","Person A")).replace("Person B", rename.get("B","Person B"))
            if gid == "group_home_carry" and not inp.get("maintain_home_household"):
                return None
            with st.expander(f"{label} — {g.get('prompt','')}", expanded=gid.startswith("group_income") or gid.startswith("group_benefits")):
                ans = {}
                for f in g["fields"]:
                    fld_label = f.get("label", f["field"])
                    kind = f.get("kind", "currency")
                    default = f.get("default", 0)
                    help_txt = f.get("tooltip", None)

                    if kind == "currency":
                        v = st.number_input(fld_label, min_value=0.0, value=float(inp.get(f.get("field"), default)), step=50.0, format="%.2f", help=help_txt)
                        ans[f.get("field")] = v

                    elif kind == "boolean":
                        v = st.checkbox(fld_label, value=(str(inp.get(f.get("field"), default)).lower() in {"yes","true","1"}), help=help_txt)
                        ans[f.get("field")] = "Yes" if v else "No"

                    elif kind == "select":
                        v = st.selectbox(fld_label, f.get("options", []), help=help_txt)
                        ans[f.get("field")] = v

                    else:
                        v = st.text_input(fld_label, value=str(inp.get(f.get("field"), default)))
                        ans[f.get("field")] = v

                return ans

        # Map groups by module order from spec
        grouped_answers = {}
        name_map = st.session_state.name_hint

        mod_order = [m["id"] for m in spec.get("modules", [])] or ["income","benefits","home","optional","assets"]
        module_to_groups = {m: [g["id"] for g in spec.get("ui_groups", []) if g["module"] == m] for m in mod_order}

        for mod in mod_order:
            for gid in module_to_groups.get(mod, []):
                ans = render_group(gid, rename=name_map)
                if ans is not None:
                    grouped_answers[gid] = ans
        c1, c2 = st.columns(2)
        if c1.button("← Back"):
            st.session_state.step = 2
            st.experimental_rerun()
        if c2.button("Calculate →", type="primary"):
            ok, msg = validate_basic(st.session_state.inputs)
            if not ok:
                st.error(msg)
            else:
                st.session_state.step = 4
                st.experimental_rerun()

    # ================= Step 4: Results =================
    else:
        st.header("Step 4 · Results")
        results = compute_results(st.session_state.inputs, spec)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Total monthly cost", mfmt(results.get("monthly_cost",0)))
            st.metric("Care cost", mfmt(results.get("care_cost",0)))
        with c2:
            st.metric("Household income", mfmt(results.get("household_income",0)))
            st.metric("Monthly gap", mfmt(results.get("monthly_gap",0)))
        with c3:
            st.metric("Assets total", mfmt(results.get("total_assets",0)))
            y = results.get("years_funded_cap30")
            st.metric("Years funded (cap 30)", "N/A" if y is None else y)

        st.info("This is an estimate. Actual prices vary. Speak with an advisor to review options.")

        st.divider()
        cc1, cc2 = st.columns(2)
        if cc1.button("← Back"):
            st.session_state.step = 3
            st.experimental_rerun()
        if cc2.button("Start over"):
            st.session_state.clear()
            st.session_state.step = 1
            st.experimental_rerun()

    # Finally, draw the live summary in the sidebar for any step
    # Compute cheap preview when enough inputs exist
    try:
        preview_results = compute_results(st.session_state.inputs, spec)
    except Exception:
        preview_results = {}
    sidebar_summary(preview_results, st.session_state.step)

if __name__ == "__main__":
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    main()
