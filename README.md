# Senior Care Cost Calculator (Streamlit) - Refactored Version

## Improvements
- **UX:** Step-by-step wizard, personalized names, tooltips, visuals (charts).
- **New Features:** Inflation/tax adjustments, state cost multipliers, overlooked costs (health extras, debts, home mods).
- **Files Unchanged in Name:** Upload to existing repo root.

## Files
- `streamlit_app.py` → Updated Streamlit UI with wizard and visuals.
- `senior_care_calculator_v5_full_with_instructions_ui.json` → Extended with new groups/fields.
- `senior_care_modular_overlay.json` → Added overrides and lookups.
- `requirements_streamlit.txt` → Added viz libs.

## Run Locally
```bash
pip install -r requirements_streamlit.txt
streamlit run streamlit_app.py