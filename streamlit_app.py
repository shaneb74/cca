# streamlit_app.py
# Senior Care Cost Planner – production-ready single-file app
# Requires: streamlit (see requirements_streamlit.txt)
# Expects the JSON files next to this file:
#   - senior_care_calculator_v5_full_with_instructions_ui.json
#   - senior_care_modular_overlay.json

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Any, Optional, List
import streamlit as st

APP_VERSION = "v2025-09-03-demofix"

JSON_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"

# ------------------------------ utils -------------------------------------
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
    except Exception:
        return {}

def load_spec(base_path: str, overlay_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load base spec and apply overlay merges:
      - lookups: merged
      - modules: replaced if provided
      - ui_group_overrides: group-level edits
      - ui_group_additions: appended
    """
    spec = _read_json(base_path)
    if not spec:
        return {}
    if overlay_path and Path(overlay_path).exists():
        overlay = _read_json(overlay_path) or {}

        if overlay.get("lookups"):
            spec.setdefault("lookups", {}).update(overlay["lookups"])
        if overlay.get("modules"):
            spec["modules"] = overlay["modules"]

        ov = overlay.get("ui_group_overrides", {})
        by_id = {g["id"]: g for g in spec.get("ui_groups", [])}
        for gid, patch in ov.items():
            g = by_id.get(gid)
            if not g:
                continue
            if "module" in patch:
                g["module"] = patch["module"]
            if "replace_fields" in patch:
                g["fields"] = list(patch["replace_fields"])
            if "append_fields" in patch:
                g.setdefault("fields", []).extend(list(patch["append_fields"]))
            field_ovs = patch.get("field_overrides", {})
            wild = field_ovs.get("*", {})
            for f in g.get("fields", []):
                for k, v in wild.items():
                    f.setdefault(k, v)
                label_key = f.get("label", f.get("field", ""))
                for k, v in field_ovs.get(label_key, {}).items():
                    f[k] = v

        adds = overlay.get("ui_group_additions", [])
        if adds:
            ui_groups = spec.get("ui_groups", [])
            existing = {g["id"] for g in ui_groups}
            for g in adds:
                if g.get("id") not in existing:
                    ui_groups.append(g)
            spec["ui_groups"] = ui_groups

    return spec

# -------------------------- core calculations -----------------------------
def compute_results(inputs: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Uses spec lookups/settings to compute monthly cost, income, gap, and years funded.
    Honors per-person in-home Hours/Days sliders when present.
    """
    settings = spec.get("settings", {})
    lookups = spec.get("lookups", {})

    # settings
    default_days_per_month = int(settings.get("days_per_month", 30))
    mem_mult = float(settings.get("memory_care_multiplier", 1.25))
    second_person_discount = float(settings.get("second_person_cost", 1200.0))
    years_cap = int(settings.get("display_cap_years_funded", 30))
    ltc_monthly_add = float(settings.get("ltc_monthly_add", 1800.0))

    # lookups
    state = inputs.get("state", "National")
    state_mult = float(lookups.get("state_multipliers", {"National": 1.0}).get(state, 1.0))
    room_type_prices = {k: float(v) for k, v in lookups.get("room_type", {}).items()}
    care_level_adders = {k: float(v) for k, v in lookups.get("care_level_adders", {}).items()}
    mobility_adders_fac = {k: float(v) for k, v in lookups.get("mobility_adders", {}).get("facility", {}).items()}
    mobility_adders_home = {k: float(v) for k, v in lookups.get("mobility_adders", {}).get("in_home", {}).items()}
    chronic_adders = {k: float(v) for k, v in lookups.get("chronic_adders", {}).items()}
    in_home_matrix = {int(k): float(v) for k, v in lookups.get("in_home_care_matrix", {}).items()}

    def interp_in_home_daily(hours_val: int) -> float:
        if not in_home_matrix:
            return 0.0
        if hours_val in in_home_matrix:
            return in_home_matrix[hours_val]
        keys = sorted(in_home_matrix.keys())
        lo = max([k for k in keys if k <= hours_val], default=keys[0])
        hi = min([k for k in keys if k >= hours_val], default=keys[-1])
        if lo == hi:
            return in_home_matrix[lo]
        frac = (hours_val - lo) / (hi - lo) if hi != lo else 0
        return in_home_matrix[lo] + frac * (in_home_matrix[hi] - in_home_matrix[lo])

    def per_person_cost(tag_letter: str) -> float:
        care_type = inputs.get(f"care_type_person_{tag_letter}")
        level = inputs.get(f"care_level_person_{tag_letter}", "Medium")
        mobility = inputs.get(f"mobility_person_{tag_letter}", "Medium")
        chronic = inputs.get(f"chronic_person_{tag_letter}", "None")

        level_add = care_level_adders.get(level, 0.0)
        chronic_add = chronic_adders.get(chronic, 0.0)

        if care_type and care_type.startswith("In-Home Care"):
            hours = int(inputs.get(f"hours_per_day_person_{tag_letter}", 0) or 0)
            days = int(inputs.get(f"days_per_month_person_{tag_letter}", default_days_per_month) or default_days_per_month)
            daily_cost_for_hours = interp_in_home_daily(hours)  # cost per day given hours
            mob_home = mobility_adders_home.get(mobility, 0.0)
            # daily base is matrix + mobility + chronic
            daily = daily_cost_for_hours + mob_home + chronic_add
            base = daily * max(0, min(31, days))
            return money(base * state_mult)

        if care_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room = inputs.get(f"room_type_person_{tag_letter}")
            base_room = room_type_prices.get(room, 0.0)
            mob_fac = mobility_adders_fac.get(mobility, 0.0)
            base = base_room + level_add + mob_fac + chronic_add
            if care_type == "Memory Care":
                base *= mem_mult
            return money(base * state_mult)

        return 0.0  # Stay at home

    def shared_unit_discount() -> float:
        a_type = inputs.get("care_type_person_a")
        b_type = inputs.get("care_type_person_b")
        if not (a_type and b_type):
            return 0.0
        in_fac_a = a_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]
        in_fac_b = b_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]
        if in_fac_a and in_fac_b:
            # simple flat second-person discount from settings
            return money(second_person_discount * state_mult)
        return 0.0

    care_cost = per_person_cost("a") + per_person_cost("b") - shared_unit_discount()

    # home carry if keeping home
    home_sum = 0.0
    if inputs.get("maintain_home_household"):
        for k in ["mortgage", "taxes", "insurance", "hoa", "utilities"]:
            home_sum += float(inputs.get(k, 0.0))
    home_sum = money(home_sum)

    # optional monthly
    optional_fields = [
        "medicare_premiums","dental_vision_hearing","home_modifications_monthly","other_debts_monthly",
        "pet_care","entertainment_hobbies","optional_rx","optional_personal_care","optional_phone_internet",
        "optional_life_insurance","optional_transportation","optional_family_travel","optional_auto",
        "optional_auto_insurance","optional_other","heloc_payment_monthly"
    ]
    optional_sum = money(sum(float(inputs.get(k, 0.0)) for k in optional_fields))

    # income
    va_total = float(inputs.get("va_benefit_person_a", 0.0)) + float(inputs.get("va_benefit_person_b", 0.0))
    ltc_total = 0.0
    if str(inputs.get("ltc_insurance_person_a", "No")).lower() in {"yes","true","1"}:
        ltc_total += float(settings.get("ltc_monthly_add", 1800.0))
    if str(inputs.get("ltc_insurance_person_b", "No")).lower() in {"yes","true","1"}:
        ltc_total += float(settings.get("ltc_monthly_add", 1800.0))

    hecm = float(inputs.get("hecm_draw_monthly", 0.0))
    heloc_draw = float(inputs.get("heloc_draw_monthly", 0.0))
    re_inv = float(inputs.get("re_investment_income", 0.0))

    household_income = money(sum([
        float(inputs.get("social_security_person_a", 0.0)),
        float(inputs.get("pension_person_a", 0.0)),
        float(inputs.get("social_security_person_b", 0.0)),
        float(inputs.get("pension_person_b", 0.0)),
        float(inputs.get("disability_income", 0.0)),
        float(inputs.get("rental_income", 0.0)),
        float(inputs.get("dividends_interest", 0.0)),
        float(inputs.get("wages_part_time", 0.0)),
        float(inputs.get("other_income_monthly", 0.0)),
        va_total, hecm, heloc_draw, re_inv, ltc_total
    ]))

    monthly_cost = money(care_cost + optional_sum + home_sum)

    # assets
    total_assets = money(sum([
        float(inputs.get("home_equity", 0.0)),
        float(inputs.get("other_assets", 0.0)),
        float(inputs.get("cash_savings", 0.0)),
        float(inputs.get("ira_total", 0.0)),
        float(inputs.get("employer_retirement_total", 0.0)),
        float(inputs.get("brokerage_taxable", 0.0)),
        float(inputs.get("other_assets_grouped", 0.0))
    ]))

    gap = money(monthly_cost - household_income)
    years = None
    if gap > 0 and total_assets > 0:
        years = int((total_assets / gap) / 12)
        years = min(years, years_cap)

    return {
        "care_cost": money(care_cost),
        "home_sum": home_sum,
        "optional_sum": optional_sum,
        "monthly_cost": monthly_cost,
        "household_income": household_income,
        "monthly_gap": gap,
        "total_assets": total_assets,
        "years_funded_cap30": years,
    }

# ------------------------------- UI bits ----------------------------------
THEME_CSS = """
<style>
  :root { --base-font-size: 18px; }
  html, body, [class*="css"] { font-size: var(--base-font-size); line-height: 1.5; }
  h1 { font-size: 1.8rem; font-weight: 700; }
  h2 { font-size: 1.4rem; font-weight: 700; }
  h3 { font-size: 1.2rem; font-weight: 700; }
  .stButton>button { padding: .7rem 1.2rem; border-radius: 12px; font-size: 1rem; }
  [data-testid="stSidebar"] { width: 360px; min-width: 360px; }
  hr { border: 0; height: 1px; background: #e5e7eb; margin: .75rem 0; }
</style>
"""

def sidebar_summary(results: Dict[str, Any]):
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
    st.sidebar.metric(("🔴" if gap > 0 else "🟢") + " Monthly gap", mfmt(gap))
    y = results.get("years_funded_cap30")
    st.sidebar.metric("Years funded (cap 30)", "N/A" if y is None else y)
    st.sidebar.markdown("---")
    with st.sidebar.expander("Save or Load Plan"):
        if st.button("Prepare download", key="save_json_btn"):
            st.session_state["_download_plan"] = json.dumps(st.session_state.get("inputs", {}), indent=2)
        if "_download_plan" in st.session_state:
            st.download_button("Download current plan (JSON)",
                               st.session_state["_download_plan"],
                               file_name="care_plan.json",
                               mime="application/json")
        up = st.file_uploader("Load a saved plan", type=["json"], key="plan_upload")
        if up is not None:
            try:
                st.session_state.inputs = json.loads(up.getvalue().decode("utf-8"))
                st.success("Loaded plan data.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not load plan: {e}")

def progress_header(step: int):
    labels = ["Who & Context", "Care Plan(s)", "Finances", "Results"]
    pct = int((step-1)/3*100)
    st.progress(pct, text=f"Step {step} of 4")
    cols = st.columns(4)
    for i, c in enumerate(cols, start=1):
        with c:
            if i < step:
                st.markdown(f"✅ **{labels[i-1]}**")
            elif i == step:
                st.markdown(f"🟦 **{labels[i-1]}**")
            else:
                st.markdown(f"▫️ {labels[i-1]}")

# ------------------------------- main app ---------------------------------
def main():
    st.set_page_config(page_title="Senior Care Cost Planner", layout="wide")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.title("Senior Care Cost Planner")
    st.caption("Estimate care costs and affordability in a few short steps.")
    st.sidebar.caption(f"App {APP_VERSION} · Streamlit {getattr(st, '__version__', 'unknown')}")

    # session
    if "step" not in st.session_state: st.session_state.step = 1
    if "inputs" not in st.session_state: st.session_state.inputs = {}
    if "name_hint" not in st.session_state: st.session_state.name_hint = {"A": "Person A", "B": "Person B"}
    if "include_b" not in st.session_state: st.session_state.include_b = False

    spec = load_spec(JSON_PATH, OVERLAY_PATH)
    if not spec:
        st.error("Could not load calculator spec. Ensure the JSON files are present.")
        st.stop()

    lookups = spec.get("lookups", {})
    step = st.session_state.step
    progress_header(step)

    # ---------------- Step 1
    if step == 1:
        with st.form("form_step1", clear_on_submit=False):
            c1, c2 = st.columns([2,1])
            with c1:
                st.header("Step 1 · Who are we planning for?")
                who = st.radio("Select the situation", [
                    "I'm planning for myself",
                    "I'm planning for my spouse/partner",
                    "I'm planning for my parent/parent-in-law",
                    "I'm planning for a couple (both parents/partners)",
                    "I'm planning for a relative or POA",
                    "I'm planning for a friend or someone else"
                ], index=0)

                if who == "I'm planning for myself":
                    # No names. A = You. Single-person flow.
                    st.session_state.include_b = False
                    st.session_state.name_hint = {"A": "You", "B": "Partner"}
                elif who == "I'm planning for my spouse/partner":
                    spouse = st.text_input("Spouse/partner's name", placeholder="e.g., Mary")
                    me = st.text_input("Your name", placeholder="e.g., Alex")
                    st.session_state.include_b = True
                    st.session_state.name_hint = {"A": spouse or "Spouse", "B": me or "You"}
                elif who == "I'm planning for my parent/parent-in-law":
                    a_name = st.text_input("First parent's name", placeholder="e.g., Teresa")
                    include_other = st.checkbox("Include the other parent for household costs?", value=True)
                    b_name = st.text_input("Second parent's name", placeholder="e.g., Shane") if include_other else ""
                    _planner = st.text_input("Your name", placeholder="e.g., Alex")
                    st.session_state.include_b = include_other
                    st.session_state.name_hint = {"A": a_name or "Parent 1", "B": b_name or "Parent 2"}
                elif who == "I'm planning for a couple (both parents/partners)":
                    a_name = st.text_input("First person’s name", placeholder="e.g., Teresa")
                    b_name = st.text_input("Second person’s name", placeholder="e.g., Shane")
                    _planner = st.text_input("Your name", placeholder="e.g., Alex")
                    st.session_state.include_b = True
                    st.session_state.name_hint = {"A": a_name or "Person 1", "B": b_name or "Person 2"}
                else:
                    a_name = st.text_input("Care recipient's name", placeholder="e.g., Mary")
                    _planner = st.text_input("Your name", placeholder="e.g., Alex")
                    include_spouse = st.checkbox("Include their spouse/partner for household costs?", value=False)
                    st.session_state.include_b = include_spouse
                    st.session_state.name_hint = {"A": a_name or "Person A", "B": "Partner"}

                # Location select
                states = list(lookups.get("state_multipliers", {"National": 1.0}).keys())
                states = (["National"] if "National" in states else []) + sorted([s for s in states if s != "National"])
                s_idx = states.index("National") if "National" in states else 0
                state = st.selectbox("Location for cost estimates", states, index=s_idx)
                st.session_state.inputs["state"] = state

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
                    inp.update({"sell_price": sell_price, "mortgage_payoff": mortgage_payoff, "selling_fees": fees, "home_equity": net})

            with c2:
                st.info("Tip: Save or load a plan from the sidebar at any time.")

            if st.form_submit_button("Continue →", type="primary"):
                st.session_state.step = 2
                st.rerun()

    # ---------------- Step 2
    elif step == 2:
        st.header("Step 2 · Choose care plans")
        inp = st.session_state.inputs

        def care_options_for(tag_key: str) -> List[str]:
            base = [
                "Stay at Home (no paid care)",
                "In-Home Care (professional staff such as nurses, CNAs, or aides)",
                "Assisted Living (or Adult Family Home)",
                "Memory Care",
            ]
            include_b = st.session_state.include_b
            person_idx = tag_key[-1]  # 'a' or 'b'
            if not include_b:
                return [c for c in base if not c.startswith("Stay")]
            if person_idx == "a":
                return [c for c in base if not c.startswith("Stay")]
            return base

        with st.form("form_step2", clear_on_submit=False):
            def render_person(tag_key: str, display_name: str):
                choices = care_options_for(tag_key)
                # default to in-home if available
                default_idx = 0
                for i, c in enumerate(choices):
                    if c.startswith("In-Home Care"):
                        default_idx = i
                        break

                care = st.selectbox(f"Care type for {display_name}", choices, index=default_idx, key=f"care_type_{tag_key}")
                inp[f"care_type_person_{tag_key[-1]}"] = care
                inp[f"person_{tag_key[-1]}_in_care"] = (care != "Stay at Home (no paid care)")

                if care.startswith("In-Home Care"):
                    hours = st.slider(
                        "Hours of paid care per day (0–24)",
                        min_value=0, max_value=24,
                        value=int(inp.get(f"hours_per_day_person_{tag_key[-1]}", 0)),
                        step=1, key=f"hours_slider_{tag_key}"
                    )
                    inp[f"hours_per_day_person_{tag_key[-1]}"] = int(hours)

                    days = st.slider(
                        "Days of paid care per month (0–31)",
                        min_value=0, max_value=31,
                        value=int(inp.get(f"days_per_month_person_{tag_key[-1]}", spec.get("settings", {}).get("days_per_month", 30))),
                        step=1, key=f"days_slider_{tag_key}"
                    )
                    inp[f"days_per_month_person_{tag_key[-1]}"] = int(days)

                    st.caption("Tip: Many families start with 2–4 hours per day, around 20 days per month.")

                elif care in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
                    room_types = list(spec.get("lookups", {}).get("room_type", {}).keys()) or ["Studio", "1 Bedroom", "Shared"]
                    room = st.selectbox("Room type", room_types, index=0, key=f"room_{tag_key}")
                    inp[f"room_type_person_{tag_key[-1]}"] = room

                level = st.selectbox("Care level", ["Low", "Medium", "High"], index=1, key=f"level_{tag_key}")
                inp[f"care_level_person_{tag_key[-1]}"] = level

                mob_keys = list(spec.get("lookups", {}).get("mobility_adders", {}).get("facility", {}).keys()) or ["Low","Medium","High"]
                mob = st.selectbox("Mobility", mob_keys, index=min(1, len(mob_keys)-1), key=f"mob_{tag_key}")
                inp[f"mobility_person_{tag_key[-1]}"] = mob

                cc_keys = list(spec.get("lookups", {}).get("chronic_adders", {}).keys()) or ["None","Some","Multiple/Complex"]
                cc_default = 0 if "None" in cc_keys else 1
                cc = st.selectbox("Chronic conditions", cc_keys, index=min(cc_default, len(cc_keys)-1), key=f"cc_{tag_key}")
                inp[f"chronic_person_{tag_key[-1]}"] = cc

            render_person("person_a", st.session_state.name_hint.get("A", "Person A"))
            if st.session_state.include_b:
                st.divider()
                st.subheader("Spouse / Partner / Second Parent")
                render_person("person_b", st.session_state.name_hint.get("B", "Person B"))

            c1, c2 = st.columns(2)
            if c1.form_submit_button("← Back"):
                st.session_state.step = 1
                st.rerun()
            if c2.form_submit_button("Continue to finances →", type="primary"):
                st.session_state.step = 3
                st.rerun()

    # ---------------- Step 3
    elif step == 3:
        st.header("Step 3 · Enter financial details")
        st.caption("Enter monthly income and asset balances. If something doesn’t apply, leave it at 0.")
        inp = st.session_state.inputs

        spec_groups = {g["id"]: g for g in spec.get("ui_groups", [])}

        if inp.get("home_to_assets"):
            st.info("Home plan: **Sell the home** — Net proceeds auto-populate in Assets.")
        elif inp.get("expect_hecm"):
            st.info("Home plan: **Reverse mortgage (HECM)** — Add expected monthly draw in Assets.")
        elif inp.get("expect_heloc"):
            st.info("Home plan: **Consider a HELOC** — Optional draw and payment in Assets.")
        else:
            st.info("Home plan: **Keep living in the home** — Mortgage/taxes/insurance/utilities are included below.")

        def render_group(gid: str, rename: Optional[Dict[str,str]] = None) -> Dict[str, Any]:
            g = spec_groups.get(gid)
            if not g:
                return {}
            # hide home carry group if not keeping home
            if gid == "group_home_carry" and not inp.get("maintain_home_household"):
                return {}

            label = g.get("label", gid)
            prompt = g.get("prompt", "")
            if rename:
                label = label.replace("Person A", rename.get("A","Person A")).replace("Person B", rename.get("B","Person B"))

            expanded = gid.startswith("group_income") or gid.startswith("group_benefits")
            with st.expander(f"{label} — {prompt}", expanded=expanded):
                answers = {}
                for f in g.get("fields", []):
                    key = f.get("field")
                    if not key:
                        continue
                    # Suppress Person B fields entirely if include_b == False
                    if not st.session_state.include_b and key.endswith("_person_b"):
                        continue

                    fld_label = f.get("label", key)
                    kind = f.get("kind", "currency")
                    default = f.get("default", 0)
                    help_txt = f.get("tooltip")

                    if kind == "currency":
                        v = st.number_input(fld_label, min_value=0.0, value=float(inp.get(key, default)), step=50.0, format="%.2f", help=help_txt)
                    elif kind == "boolean":
                        v_bool = str(inp.get(key, default)).lower() in {"yes","true","1"}
                        v = st.checkbox(fld_label, value=v_bool, help=help_txt)
                        v = "Yes" if v else "No"
                    elif kind == "select":
                        opts = f.get("options", [])
                        idx = 0
                        if isinstance(default, str) and default in opts:
                            idx = opts.index(default)
                        v = st.selectbox(fld_label, opts, index=idx if idx < len(opts) else 0, help=help_txt)
                    else:
                        v = st.text_input(fld_label, value=str(inp.get(key, default)), help=help_txt)
                    answers[key] = v
                return answers

        name_map = st.session_state.name_hint
        mod_order = [m["id"] for m in spec.get("modules", [])] or ["income","benefits","home","optional","assets"]
        module_to_groups = {m: [g["id"] for g in spec.get("ui_groups", []) if g.get("module") == m] for m in mod_order}
        grouped_answers = {}

        with st.form("form_step3", clear_on_submit=False):
            for mod in mod_order:
                for gid in module_to_groups.get(mod, []):
                    ans = render_group(gid, rename=name_map)
                    if ans:
                        grouped_answers[gid] = ans

            c1, c2 = st.columns(2)
            if c1.form_submit_button("← Back"):
                st.session_state.step = 2
                st.rerun()
            if c2.form_submit_button("Calculate →", type="primary"):
                for _, ans in grouped_answers.items():
                    st.session_state.inputs.update(ans)
                st.session_state.step = 4
                st.rerun()

    # ---------------- Step 4
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
        c1, c2 = st.columns(2)
        if c1.button("← Back"):
            st.session_state.step = 3
            st.rerun()
        if c2.button("Start over"):
            st.session_state.clear()
            st.session_state.step = 1
            st.rerun()

    # sidebar live summary
    try:
        preview_results = compute_results(st.session_state.inputs, spec)
    except Exception:
        preview_results = {}
    sidebar_summary(preview_results)

if __name__ == "__main__":
    main()