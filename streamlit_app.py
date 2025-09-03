# streamlit_app.py
# Senior Care Cost Planner – reactive steps, tooltips, descriptive options, home mods
# New in this build:
# - VA rules baked-in (MAPR minus countable income plus deductible medical), household logic
# - Clear consumer tooltips for VA Category and VA Benefit (auto)
# - Home modifications ONE-TIME costs in their own collapsible drawer on Step 3
# - Keeps all the working behavior you approved

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import streamlit as st

APP_VERSION = "v2025-09-03-va-rules-tooltips-homemods"

JSON_PATH = "senior_care_calculator_v5_full_with_instructions_ui.json"
OVERLAY_PATH = "senior_care_modular_overlay.json"

# ===== Built-in VA category monthly presets (effective Dec 1, 2024) =====
# If your JSON has lookups.va_categories, that overrides these.
DEFAULT_VA_CATEGORIES = {
    "None": 0.0,
    "Veteran only (A&A)": 2358.33,                       # MAPR 28,300 / 12
    "Veteran with spouse (A&A)": 2795.67,                # MAPR 33,548 / 12
    "Two veterans married, both A&A (household ceiling)": 3740.50,  # MAPR 44,886 / 12
    "Surviving spouse (A&A)": 1515.58,                   # MAPR 18,187 / 12
    "Surviving spouse + 1 child (A&A)": 1808.00          # MAPR 21,696 / 12
}

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

    # Ensure VA categories; seed with built-in defaults if missing
    lookups = spec.setdefault("lookups", {})
    vac = lookups.get("va_categories")
    if not isinstance(vac, dict) or not vac:
        lookups["va_categories"] = dict(DEFAULT_VA_CATEGORIES)

    return spec

# -------------------------- calculations ----------------------------------
def compute_results(inputs: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    settings = spec.get("settings", {})
    lookups = spec.get("lookups", {})

    mem_mult = float(settings.get("memory_care_multiplier", 1.25))
    second_person_discount = float(settings.get("second_person_cost", 1200.0))
    years_cap = int(settings.get("display_cap_years_funded", 30))
    ltc_monthly_add = float(settings.get("ltc_monthly_add", 1800.0))

    state = inputs.get("state", "National")
    state_mult = float(lookups.get("state_multipliers", {"National": 1.0}).get(state, 1.0))
    room_type_prices = {k: float(v) for k, v in lookups.get("room_type", {}).items()}
    care_level_adders = {k: float(v) for k, v in lookups.get("care_level_adders", {}).items()}
    mobility_adders_fac = {k: float(v) for k, v in lookups.get("mobility_adders", {}).get("facility", {}).items()}
    mobility_adders_home = {k: float(v) for k, v in lookups.get("mobility_adders", {}).get("in_home", {}).items()}
    chronic_adders = {k: float(v) for k, v in lookups.get("chronic_adders", {}).items()}
    in_home_matrix = {int(k): float(v) for k, v in lookups.get("in_home_care_matrix", {}).items()}

    # ---------- helper: in-home daily interpolation ----------
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

    # ---------- per-person care cost ----------
    def per_person_cost(tag_letter: str) -> float:
        care_type = inputs.get(f"care_type_person_{tag_letter}")
        level = inputs.get(f"care_level_person_{tag_letter}", "Medium")
        mobility = inputs.get(f"mobility_person_{tag_letter}", "Medium")
        chronic = inputs.get(f"chronic_person_{tag_letter}", "None")

        level_add = care_level_adders.get(level, 0.0)
        chronic_add = chronic_adders.get(chronic, 0.0)

        if care_type and care_type.startswith("In-Home Care"):
            hours = max(0, min(24, int(inputs.get(f"hours_per_day_person_{tag_letter}", 4) or 4)))
            days = max(0, min(31, int(inputs.get(f"days_per_month_person_{tag_letter}", 20) or 20)))
            daily_cost_for_hours = interp_in_home_daily(hours)
            mob_home = mobility_adders_home.get(mobility, 0.0)
            base = (daily_cost_for_hours + mob_home + chronic_add) * days
            return money(base * state_mult)

        if care_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room = inputs.get(f"room_type_person_{tag_letter}")
            base_room = room_type_prices.get(room, 0.0)
            mob_fac = mobility_adders_fac.get(mobility, 0.0)
            base = base_room + level_add + mob_fac + chronic_add
            if care_type == "Memory Care":
                base *= mem_mult
            return money(base * state_mult)

        return 0.0

    def shared_unit_discount() -> float:
        a_type = inputs.get("care_type_person_a")
        b_type = inputs.get("care_type_person_b")
        if not (a_type and b_type):
            return 0.0
        in_fac_a = a_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]
        in_fac_b = b_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]
        if in_fac_a and in_fac_b:
            return money(second_person_discount * state_mult)
        return 0.0

    care_cost = per_person_cost("a") + per_person_cost("b") - shared_unit_discount()

    # ---------- monthly non-care household costs ----------
    home_sum = 0.0
    if inputs.get("maintain_home_household"):
        for k in ["mortgage", "taxes", "insurance", "hoa", "utilities"]:
            home_sum += float(inputs.get(k, 0.0))
    home_sum = money(home_sum)

    optional_fields = [
        "medicare_premiums","dental_vision_hearing","home_modifications_monthly","other_debts_monthly",
        "pet_care","entertainment_hobbies","optional_rx","optional_personal_care","optional_phone_internet",
        "optional_life_insurance","optional_transportation","optional_family_travel","optional_auto",
        "optional_auto_insurance","optional_other","heloc_payment_monthly"
    ]
    optional_sum = money(sum(float(inputs.get(k, 0.0)) for k in optional_fields))

    # ---------- VA rules baked in ----------
    va_categories: Dict[str, float] = lookups.get("va_categories", {})
    cat_a = st.session_state.get("va_category_person_a", "None")
    cat_b = st.session_state.get("va_category_person_b", "None")

    # Compute household MAPR (annual) based on categories
    def mapr_from_categories(cat_a: str, cat_b: str) -> float:
        if "Two veterans married" in cat_a or "Two veterans married" in cat_b:
            return float(DEFAULT_VA_CATEGORIES.get("Two veterans married, both A&A (household ceiling)", 0.0)) * 12
        if "Veteran with spouse" in cat_a or "Veteran with spouse" in cat_b:
            return float(va_categories.get("Veteran with spouse (A&A)", DEFAULT_VA_CATEGORIES["Veteran with spouse (A&A)"])) * 12
        if "Veteran only" in cat_a or "Veteran only" in cat_b:
            return float(va_categories.get("Veteran only (A&A)", DEFAULT_VA_CATEGORIES["Veteran only (A&A)"])) * 12
        if "Surviving spouse + 1 child" in cat_a or "Surviving spouse + 1 child" in cat_b:
            return float(va_categories.get("Surviving spouse + 1 child (A&A)", DEFAULT_VA_CATEGORIES["Surviving spouse + 1 child (A&A)"])) * 12
        if "Surviving spouse" in cat_a or "Surviving spouse" in cat_b:
            return float(va_categories.get("Surviving spouse (A&A)", DEFAULT_VA_CATEGORIES["Surviving spouse (A&A)"])) * 12
        return 0.0

    household_mapr_annual = mapr_from_categories(cat_a, cat_b)

    # Countable income (annual): baseline incomes (exclude VA itself and asset-draw knobs)
    monthly_income_countable = sum([
        float(inputs.get("social_security_person_a", 0.0)),
        float(inputs.get("pension_person_a", 0.0)),
        float(inputs.get("social_security_person_b", 0.0)),
        float(inputs.get("pension_person_b", 0.0)),
        float(inputs.get("disability_income", 0.0)),
        float(inputs.get("rental_income", 0.0)),
        float(inputs.get("dividends_interest", 0.0)),
        float(inputs.get("wages_part_time", 0.0)),
        float(inputs.get("other_income_monthly", 0.0)),
    ])
    countable_income_annual = monthly_income_countable * 12.0

    # Deductible medical (annual): care_cost + core medical items
    monthly_deductible_medical = money(
        care_cost
        + float(inputs.get("medicare_premiums", 0.0))
        + float(inputs.get("dental_vision_hearing", 0.0))
        + float(inputs.get("optional_rx", 0.0))
        + float(inputs.get("optional_personal_care", 0.0))
    )
    deductible_medical_annual = monthly_deductible_medical * 12.0

    # VA award annual (clamped at 0..MAPR)
    va_award_annual = max(0.0, household_mapr_annual - max(0.0, countable_income_annual - deductible_medical_annual))
    va_award_monthly = money(va_award_annual / 12.0)

    # Assign VA award to persons, respecting categories; allow manual override flags
    override_a = bool(st.session_state.get("va_override_person_a", False))
    override_b = bool(st.session_state.get("va_override_person_b", False))
    manual_a = float(inputs.get("va_benefit_person_a", 0.0)) if override_a else None
    manual_b = float(inputs.get("va_benefit_person_b", 0.0)) if override_b else None

    va_a = 0.0
    va_b = 0.0
    if manual_a is not None or manual_b is not None:
        va_a = money(manual_a or 0.0)
        va_b = money(manual_b or 0.0)
    else:
        if "Two veterans married" in cat_a or "Two veterans married" in cat_b:
            va_a = money(va_award_monthly / 2.0)
            va_b = money(va_award_monthly / 2.0)
        elif "Veteran with spouse" in cat_a or "Veteran only" in cat_a:
            va_a = money(va_award_monthly)
            va_b = 0.0
        elif "Veteran with spouse" in cat_b or "Veteran only" in cat_b:
            va_b = money(va_award_monthly)
            va_a = 0.0
        elif "Surviving spouse" in cat_a:
            va_a = money(va_award_monthly)
            va_b = 0.0
        elif "Surviving spouse" in cat_b:
            va_b = money(va_award_monthly)
            va_a = 0.0
        else:
            va_a = 0.0
            va_b = 0.0

    # ---------- household income (monthly) ----------
    hecm = float(inputs.get("hecm_draw_monthly", 0.0))
    heloc_draw = float(inputs.get("heloc_draw_monthly", 0.0))
    re_inv = float(inputs.get("re_investment_income", 0.0))

    ltc_total = 0.0
    if str(inputs.get("ltc_insurance_person_a", "No")).lower() in {"yes","true","1"}:
        ltc_total += ltc_monthly_add
    if str(inputs.get("ltc_insurance_person_b", "No")).lower() in {"yes","true","1"}:
        ltc_total += ltc_monthly_add

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
        va_a, va_b, hecm, heloc_draw, re_inv, ltc_total
    ]))

    monthly_cost = money(care_cost + optional_sum + home_sum)

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
        "home_mods_one_time_total": money(float(inputs.get("home_mods_one_time_total", 0.0))),
        "va_a": va_a,
        "va_b": va_b,
        "va_household_mapr_monthly": money(household_mapr_annual / 12.0)
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
    st.sidebar.metric(("RED" if gap > 0 else "GREEN") + " Monthly gap", mfmt(gap))
    st.sidebar.metric("One-time home mods", mfmt(results.get("home_mods_one_time_total", 0)))
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

def build_descriptive_options(keys: List[str], desc_map: Dict[str, str]) -> Tuple[List[str], Dict[str, str]]:
    labels = []
    mapping = {}
    for k in keys:
        desc = desc_map.get(k)
        label = f"{k} ({desc})" if desc else k
        labels.append(label)
        mapping[label] = k
    return labels, mapping

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

    # ---------------- Step 1 (your approved flow)
    if step == 1:
        c1, c2 = st.columns([2,1])
        with c1:
            st.header("Step 1 · Who are we planning for?")
            options = [
                "I'm planning for myself",
                "I'm planning for my spouse/partner",
                "I'm planning for my parent/parent-in-law",
                "I'm planning for a couple (both parents/partners)",
                "I'm planning for a relative or POA",
                "I'm planning for a friend or someone else"
            ]
            who = st.radio("Select the situation", options, index=st.session_state.get("who_idx", 0), key="who_choice")
            st.session_state.who_idx = options.index(who)

            # Flags for downstream defaults
            st.session_state.audience_spouse_mode = (who == "I'm planning for my spouse/partner")
            st.session_state.audience_parent_second_mode = (who == "I'm planning for my parent/parent-in-law")

            if who == "I'm planning for myself":
                cols = st.columns(2)
                with cols[0]:
                    your_name = st.text_input("Your name", placeholder="e.g., Alex", key="name_self_you")
                st.session_state.include_b = False
                st.session_state.name_hint = {"A": your_name or "You", "B": "Partner"}

            elif who == "I'm planning for my spouse/partner":
                cols = st.columns(2)
                with cols[0]:
                    recip = st.text_input("Care recipient's name", placeholder="e.g., Mary", key="name_spouse_recipient")
                with cols[1]:
                    your_name = st.text_input("Your name", placeholder="e.g., Alex", key="name_spouse_you")
                include_you = st.checkbox("Include you for household costs", value=True, key="chk_include_you")
                st.session_state.include_b = include_you
                st.session_state.name_hint = {"A": recip or "Care Recipient", "B": your_name or "You"}

            elif who == "I'm planning for my parent/parent-in-law":
                cols = st.columns(2)
                with cols[0]:
                    a_name = st.text_input("Care recipient's name", placeholder="e.g., Teresa", key="name_parent_a")
                with cols[1]:
                    b_name = st.text_input("Second parent's name (optional)", placeholder="e.g., Shane", key="name_parent_b")
                include_other = st.checkbox("Include the second parent for household costs", value=True, key="chk_include_other_parent")
                st.session_state.include_b = include_other and bool((b_name or "").strip())
                st.session_state.name_hint = {"A": a_name or "Parent 1", "B": (b_name or "Parent 2") if st.session_state.include_b else "Parent 2"}

            elif who == "I'm planning for a couple (both parents/partners)":
                cols = st.columns(2)
                with cols[0]:
                    a_name = st.text_input("First person's name", placeholder="e.g., Teresa", key="name_couple_a")
                with cols[1]:
                    b_name = st.text_input("Second person's name", placeholder="e.g., Shane", key="name_couple_b")
                st.session_state.include_b = True
                st.session_state.name_hint = {"A": a_name or "Person 1", "B": b_name or "Person 2"}

            else:
                cols = st.columns(2)
                with cols[0]:
                    a_name = st.text_input("Care recipient's name", placeholder="e.g., Mary", key="name_other_a")
                with cols[1]:
                    b_name = st.text_input("Spouse/partner name (optional)", placeholder="e.g., Sam", key="name_other_b")
                include_spouse = st.checkbox("Include the spouse/partner for household costs", value=False, key="chk_include_spouse_other")
                st.session_state.include_b = include_spouse and bool((b_name or "").strip())
                st.session_state.name_hint = {"A": a_name or "Person A", "B": (b_name or "Partner") if st.session_state.include_b else "Partner"}

            # Location
            states = list(lookups.get("state_multipliers", {"National": 1.0}).keys())
            states = (["National"] if "National" in states else []) + sorted([s for s in states if s != "National"])
            s_idx = states.index("National") if "National" in states else 0
            state = st.selectbox("Location for cost estimates", states, index=s_idx, key="sel_state")
            st.session_state.inputs["state"] = state

            # Home plan
            st.markdown("**Home & funding approach**")
            home_plan = st.radio("How will the home factor into paying for care?", [
                "Keep living in the home (don't tap equity)",
                "Sell the home (use net proceeds)",
                "Use reverse mortgage (HECM)",
                "Consider a HELOC (home equity line)"
            ], index=0, key="home_plan")
            inp = st.session_state.inputs
            inp["maintain_home_household"] = (home_plan == "Keep living in the home (don't tap equity)")
            inp["home_to_assets"] = (home_plan == "Sell the home (use net proceeds)")
            inp["expect_hecm"] = (home_plan == "Use reverse mortgage (HECM)")
            inp["expect_heloc"] = (home_plan == "Consider a HELOC (home equity line)")

            if inp["home_to_assets"]:
                st.markdown("**Home sale estimate**")
                cols2 = st.columns(3)
                with cols2[0]:
                    sell_price = st.number_input("Estimated sale price", min_value=0.0, value=float(inp.get("sell_price", 0.0)), step=1000.0, format="%.2f", key="sell_price")
                with cols2[1]:
                    mortgage_payoff = st.number_input("Est. mortgage payoff", min_value=0.0, value=float(inp.get("mortgage_payoff", 0.0)), step=1000.0, format="%.2f", key="mortgage_payoff")
                with cols2[2]:
                    fees = st.number_input("Selling costs (fees, repairs, etc.)", min_value=0.0, value=float(inp.get("selling_fees", 0.0)), step=500.0, format="%.2f", key="selling_fees")
                net = max(0.0, sell_price - mortgage_payoff - fees)
                st.info(f"Estimated net proceeds: {mfmt(net)} (auto-added to Assets)")
                inp.update({"sell_price": sell_price, "mortgage_payoff": mortgage_payoff, "selling_fees": fees, "home_equity": net})

        with c2:
            st.info("Tip: Save or load a plan from the sidebar at any time.")

        if st.button("Continue →", type="primary", key="btn_step1_continue"):
            st.session_state.step = 2
            st.rerun()

    # ---------------- Step 2 (care plans)
    elif step == 2:
        st.header("Step 2 · Choose care plans")
        inp = st.session_state.inputs

        care_level_desc = {"Low":"help with a few daily tasks","Medium":"daily support with several tasks","High":"extensive supervision and care"}
        mobility_desc_preferred = {"No support needed":"independent","Walker":"needs walker or similar","Wheelchair":"primarily wheelchair"}
        mobility_desc_alt = {"Low":"no mobility support","Medium":"walker or cane","High":"wheelchair or total assist"}
        chronic_desc = {"None":"no chronic conditions","Some":"one or two managed conditions","Multiple/Complex":"multiple conditions or complex care"}

        def care_options_for(tag_key: str) -> List[str]:
            base = [
                "Stay at Home (no paid care)",
                "In-Home Care (professional staff such as nurses, CNAs, or aides)",
                "Assisted Living (or Adult Family Home)",
                "Memory Care",
            ]
            include_b = st.session_state.include_b
            person_idx = tag_key[-1]
            if not include_b:
                return [c for c in base if not c.startswith("Stay")]
            if person_idx == "a":
                return [c for c in base if not c.startswith("Stay")]
            return base

        def build_default_index(choices: List[str], tag_key: str) -> int:
            default_idx = 0
            for i, c in enumerate(choices):
                if c.startswith("In-Home Care"):
                    default_idx = i
                    break
            if (
                tag_key.endswith("b")
                and st.session_state.include_b
                and "Stay at Home (no paid care)" in choices
                and (st.session_state.get("audience_spouse_mode") or st.session_state.get("audience_parent_second_mode"))
            ):
                default_idx = choices.index("Stay at Home (no paid care)")
            return default_idx

        def build_descriptive_options(keys: List[str], desc_map: Dict[str, str]) -> Tuple[List[str], Dict[str, str]]:
            labels, mapping = [], {}
            for k in keys:
                desc = desc_map.get(k)
                label = f"{k} ({desc})" if desc else k
                labels.append(label)
                mapping[label] = k
            return labels, mapping

        def render_person(tag_key: str, display_name: str):
            choices = care_options_for(tag_key)
            care = st.selectbox(
                f"Care type for {display_name}",
                choices, index=build_default_index(choices, tag_key), key=f"care_type_{tag_key}",
                help="Choose the general setting for care. In-home is care where the person lives now; Assisted Living/Memory Care are residential communities."
            )
            inp[f"care_type_person_{tag_key[-1]}"] = care
            inp[f"person_{tag_key[-1]}_in_care"] = (care != "Stay at Home (no paid care)")

            hide_common_selectors = False
            if care == "Stay at Home (no paid care)":
                hide_common_selectors = True
                inp[f"care_level_person_{tag_key[-1]}"] = "None"
                inp[f"mobility_person_{tag_key[-1]}"] = "None"
                inp[f"chronic_person_{tag_key[-1]}"] = "None"
                inp[f"hours_per_day_person_{tag_key[-1]}"] = 0
                inp[f"days_per_month_person_{tag_key[-1]}"] = 0

            if care.startswith("In-Home Care"):
                hours_val = max(0, min(24, int(inp.get(f"hours_per_day_person_{tag_key[-1]}", 4) or 4)))
                hours = st.slider("Hours of paid care per day (0–24)", 0, 24, hours_val, 1,
                                  key=f"hours_slider_{tag_key}", help="Typical starter plans are 2–4 hours per day.")
                inp[f"hours_per_day_person_{tag_key[-1]}"] = int(hours)

                days_val = max(0, min(31, int(inp.get(f"days_per_month_person_{tag_key[-1]}", 20) or 20)))
                days = st.slider("Days of paid care per month (0–31)", 0, 31, days_val, 1,
                                 key=f"days_slider_{tag_key}", help="Most families schedule care 15–25 days each month.")
                inp[f"days_per_month_person_{tag_key[-1]}"] = int(days)

            elif care in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
                room_types = list(spec.get("lookups", {}).get("room_type", {}).keys()) or ["Studio", "1 Bedroom", "Shared"]
                room = st.selectbox("Room type", room_types, index=0, key=f"room_{tag_key}",
                                    help="Typical options are Studio, 1 Bedroom, or Shared.")
                inp[f"room_type_person_{tag_key[-1]}"] = room

            if not hide_common_selectors:
                level_keys = ["Low", "Medium", "High"]
                level_labels, level_map = build_descriptive_options(level_keys, care_level_desc)
                level_display = st.selectbox("Care level", level_labels,
                                             index=level_labels.index([l for l in level_labels if l.startswith("Medium")][0]),
                                             key=f"level_{tag_key}", help="How much day-to-day help is needed.")
                inp[f"care_level_person_{tag_key[-1]}"] = level_map[level_display]

                mobility_keys_lookup = list(spec.get("lookups", {}).get("mobility_adders", {}).get("facility", {}).keys()) or ["Low","Medium","High"]
                if set(mobility_keys_lookup) >= {"No support needed","Walker","Wheelchair"}:
                    mob_labels, mob_map = build_descriptive_options(mobility_keys_lookup, mobility_desc_preferred)
                else:
                    mob_labels, mob_map = build_descriptive_options(mobility_keys_lookup, mobility_desc_alt)
                default_mob_label = next((lbl for lbl in mob_labels if "walker" in lbl.lower() or "medium" in lbl.lower()), mob_labels[0])
                mob_display = st.selectbox("Mobility", mob_labels, index=mob_labels.index(default_mob_label),
                                           key=f"mob_{tag_key}", help="Select equipment or assistance typically used for getting around.")
                inp[f"mobility_person_{tag_key[-1]}"] = mob_map[mob_display]

                cc_keys = list(spec.get("lookups", {}).get("chronic_adders", {}).keys()) or ["None","Some","Multiple/Complex"]
                cc_labels, cc_map = build_descriptive_options(cc_keys, chronic_desc)
                cc_display = st.selectbox("Chronic conditions", cc_labels,
                                          index=cc_labels.index([l for l in cc_labels if l.startswith("None")][0]) if any(l.startswith("None") for l in cc_labels) else 0,
                                          key=f"cc_{tag_key}", help="General health complexity. Choose 'Some' for one or two managed conditions; 'Multiple/Complex' for several or advanced.")
                inp[f"chronic_person_{tag_key[-1]}"] = cc_map[cc_display]

        render_person("person_a", st.session_state.name_hint.get("A", "Person A"))
        if st.session_state.include_b:
            st.divider()
            st.subheader("Spouse / Partner / Second Parent")
            render_person("person_b", st.session_state.name_hint.get("B", "Person B"))

        c1, c2 = st.columns(2)
        if c1.button("← Back", key="btn_step2_back"):
            st.session_state.step = 1
            st.rerun()
        if c2.button("Continue to finances →", type="primary", key="btn_step2_next"):
            st.session_state.step = 3
            st.rerun()

    # ---------------- Step 3 (live inputs + VA blocks + Home mods one-time)
    elif step == 3:
        st.header("Step 3 · Enter financial details")
        st.caption("Enter monthly income and asset balances. The summary updates live.")
        inp = st.session_state.inputs
        spec_groups = {g["id"]: g for g in spec.get("ui_groups", [])}

        if inp.get("home_to_assets"):
            st.info("Home plan: Sell the home — net proceeds auto-populate in Assets.")
        elif inp.get("expect_hecm"):
            st.info("Home plan: Reverse mortgage (HECM) — add expected monthly draw in Assets.")
        elif inp.get("expect_heloc"):
            st.info("Home plan: Consider a HELOC — optional draw and payment in Assets.")
        else:
            st.info("Home plan: Keep living in the home — mortgage/taxes/insurance/utilities are included below.")

        def _rename(text: str, mapping: Dict[str, str]) -> str:
            return text.replace("Person A", mapping.get("A", "Person A")).replace("Person B", mapping.get("B", "Person B"))

        va_categories: Dict[str, float] = spec.get("lookups", {}).get("va_categories", DEFAULT_VA_CATEGORIES)

        def va_block(person_key: str, person_label: str):
            cats = list(va_categories.keys())
            prev_choice = st.session_state.get(f"va_category_{person_key}", "None")
            if prev_choice not in cats:
                prev_choice = "None"
            display = [f"{c} ({mfmt(va_categories[c])})" for c in cats]
            sel = st.selectbox(
                f"VA category — {person_label}",
                display, index=display.index(f"{prev_choice} ({mfmt(va_categories[prev_choice])})"),
                key=f"va_category_select_{person_key}",
                help=("Pick the VA category that applies (Veteran, Veteran with spouse, Surviving spouse, etc.). "
                      "This sets the maximum annual pension rate (MAPR). The planner then calculates your actual "
                      "monthly benefit based on your household income and deductible medical expenses. "
                      "The amount you see below in 'VA benefit (auto)' is that computed result.")
            )
            chosen = sel.split(" (")[0]
            st.session_state[f"va_category_{person_key}"] = chosen

            # Manual override checkbox
            override = st.checkbox(
                f"Override amount manually — {person_label}",
                value=st.session_state.get(f"va_override_{person_key}", False),
                key=f"va_override_chk_{person_key}"
            )
            st.session_state[f"va_override_{person_key}"] = override

            if override:
                amt = st.number_input(f"VA benefit — {person_label} (monthly)",
                                      min_value=0.0,
                                      value=float(inp.get(f"va_benefit_{person_key}", 0.0)),
                                      step=50.0, format="%.2f", key=f"va_amount_{person_key}")
                inp[f"va_benefit_{person_key}"] = amt
            else:
                st.text_input(
                    f"VA benefit — {person_label} (auto)",
                    value=mfmt(0.0),
                    key=f"va_display_{person_key}",
                    disabled=True,
                    help=("This shows the monthly VA benefit calculated automatically from your VA category, "
                          "household income, and medical expenses. Use the 'Override manually' option if you need "
                          "to match an official VA award letter.")
                )

        name_map = st.session_state.name_hint

        def render_group_live(gid: str):
            g = spec_groups.get(gid)
            if not g:
                return
            if gid == "group_home_carry" and not inp.get("maintain_home_household"):
                return
            label = _rename(g.get("label", gid), name_map)
            prompt = _rename(g.get("prompt", ""), name_map)

            expanded = gid.startswith("group_income") or gid.startswith("group_benefits")
            with st.expander(f"{label} — {prompt}", expanded=expanded):
                # VA section gets category dropdowns + tooltips
                if "benefit" in gid or "benefits" in gid:
                    va_block("person_a", name_map.get("A", "Person A"))
                    if st.session_state.include_b:
                        va_block("person_b", name_map.get("B", "Person B"))

                # Render the rest of the fields live
                for f in g.get("fields", []):
                    key = f.get("field")
                    if not key or key.startswith("va_benefit_"):
                        continue
                    if not st.session_state.include_b and key.endswith("_person_b"):
                        continue
                    fld_label = _rename(f.get("label", key), name_map)
                    kind = f.get("kind", "currency")
                    default = f.get("default", 0)
                    help_txt = f.get("tooltip")
                    if kind == "currency":
                        val = st.number_input(fld_label, min_value=0.0, value=float(inp.get(key, default)), step=50.0, format="%.2f", help=help_txt, key=f"cur_{key}")
                        inp[key] = val
                    elif kind == "boolean":
                        v_bool = str(inp.get(key, default)).lower() in {"yes","true","1"}
                        val = st.checkbox(fld_label, value=v_bool, help=help_txt, key=f"bool_{key}")
                        inp[key] = "Yes" if val else "No"
                    elif kind == "select":
                        opts = f.get("options", [])
                        idx = 0
                        if isinstance(default, str) and default in opts:
                            idx = opts.index(default)
                        val = st.selectbox(fld_label, opts, index=idx if idx < len(opts) else 0, help=help_txt, key=f"sel_{key}")
                        inp[key] = val
                    else:
                        val = st.text_input(fld_label, value=str(inp.get(key, default)), help=help_txt, key=f"txt_{key}")
                        inp[key] = val

        # Module ordering from spec
        mod_order = [m["id"] for m in spec.get("modules", [])] or ["income","benefits","home","optional","assets"]
        module_to_groups = {m: [g["id"] for g in spec.get("ui_groups", []) if g.get("module") == m] for m in mod_order}
        for mod in mod_order:
            for gid in module_to_groups.get(mod, []):
                render_group_live(gid)

        # Home modifications ONE-TIME drawer (separate from monthly)
        with st.expander("Home modifications (one-time costs)", expanded=False):
            st.caption("Select or enter the expected one-time expenses for making the home safer or more accessible.")
            home_mod_items = [
                ("grab_bars", "Grab bars and rails"),
                ("ramps", "Wheelchair ramps"),
                ("bath_mods", "Bathroom modifications"),
                ("stair_lift", "Stair lift"),
                ("widen_doors", "Widening doors"),
                ("other_home_mods", "Other modifications"),
            ]
            total = 0.0
            for key, label in home_mod_items:
                val = st.number_input(label, min_value=0.0, value=float(inp.get(key, 0.0)), step=100.0, format="%.2f", key=f"hm_{key}")
                inp[key] = val
                total += val
            inp["home_mods_one_time_total"] = total
            st.info(f"Estimated total one-time home modifications: {mfmt(total)}")

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("← Back"):
            st.session_state.step = 2
            st.rerun()
        if c2.button("Calculate →", type="primary"):
            st.session_state.step = 4
            st.rerun()

    # ---------------- Step 4 (Results)
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
            st.metric("One-time home mods", mfmt(results.get("home_mods_one_time_total",0)))
        st.metric("VA benefit (Person A)", mfmt(results.get("va_a", 0.0)))
        st.metric("VA benefit (Person B)", mfmt(results.get("va_b", 0.0)))
        st.caption(f"Household VA MAPR ceiling used: {mfmt(results.get('va_household_mapr_monthly', 0.0))}/mo")

        st.info("This is an estimate. Actual VA awards depend on VA rules and verified countable income and medical deductions.")
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