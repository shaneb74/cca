
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
        if overlay.get("modules"):
            spec["modules"] = overlay["modules"]
        overrides = overlay.get("ui_group_overrides", {})
        gid_to_group = {g["id"]: g for g in spec.get("ui_groups", [])}
        for gid, ov in overrides.items():
            g = gid_to_group.get(gid)
            if not g:
                continue
            if "module" in ov:
                g["module"] = ov["module"]
            field_ovs = ov.get("field_overrides", {})
            wildcard = field_ovs.get("*", {})
            for f in g.get("fields", []):
                label = f.get("label", f["field"])
                this_ov = field_ovs.get(label, {})
                for k, v in wildcard.items():
                    f.setdefault(k, v)
                for k, v in this_ov.items():
                    f[k] = v
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
            return money(hourly * settings["days_per_month"] + mobility_home + chronic_add)
        elif care_type in ["Assisted Living (or Adult Family Home)", "Memory Care"]:
            room_type = inputs.get(f"room_type_person_{person}")
            base_room = lookups["room_type"].get(room_type, 0)
            if care_type == "Memory Care":
                base_room *= settings["memory_care_multiplier"]
            return money(base_room + care_level_add + mobility_fac + chronic_add)
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
    care_cost_total = money(a_selected + b_selected - shared_unit_adjustment())
    optional_fields = ["optional_rx","optional_personal_care","optional_phone_internet","optional_life_insurance",
                       "optional_transportation","optional_family_travel","optional_auto","optional_auto_insurance","optional_other"]
    optional_sum = sum(inputs.get(k, 0.0) for k in optional_fields)
    home_fields = ["mortgage","taxes","insurance","hoa","utilities"]
    home_sum = sum(inputs.get(k, 0.0) for k in home_fields)
    house_cost_total = home_sum if inputs.get("maintain_home_household") else 0.0
    va_total = inputs.get("va_benefit_person_a", 0.0) + inputs.get("va_benefit_person_b", 0.0)
    ltc_total = (settings["ltc_monthly_add"] if inputs.get("ltc_insurance_person_a") == "Yes" else 0) + \
                (settings["ltc_monthly_add"] if inputs.get("ltc_insurance_person_b") == "Yes" else 0)
    household_income = sum([inputs.get("social_security_person_a", 0.0),
                            inputs.get("social_security_person_b", 0.0),
                            inputs.get("pension_person_a", 0.0),
                            inputs.get("pension_person_b", 0.0),
                            inputs.get("re_investment_income", 0.0)]) + va_total + ltc_total
    monthly_cost_full = care_cost_total + house_cost_total + optional_sum
    monthly_gap = max(0.0, monthly_cost_full - household_income)
    total_assets = inputs.get("home_equity", 0.0) + inputs.get("other_assets", 0.0)
    if monthly_gap <= 0:
        display_years = settings["display_cap_years_funded"]
    else:
        years_funded = total_assets / (monthly_gap * 12) if (monthly_gap * 12) > 0 else float("inf")
        display_years = min(years_funded, settings["display_cap_years_funded"])
    return {"care_cost_total": money(care_cost_total),
            "monthly_cost": money(monthly_cost_full),
            "household_income": money(household_income),
            "monthly_gap": money(monthly_gap),
            "total_assets": money(total_assets),
            "years_funded_cap30": (None if display_years in (None, float("inf")) else round(display_years,2))}

# ---------- UI ----------
st.set_page_config(page_title="Senior Care Cost Wizard", page_icon="🧭", layout="centered")
spec = load_spec_with_overlay(JSON_PATH, OVERLAY_PATH)
# (Rest of UI unchanged from previous expanded version with spouse logic improvements...)
