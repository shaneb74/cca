# Changelog

## 2025-09-03
- Updated Step 1 with yes/no buttons: "Yes, plan for my spouse" / "No, just me" and "Yes, keep the home" / "No, not keeping it" instead of checkboxes.
- Added sell-home option in Step 1: "Yes, plan to sell" / "No, keep it" after maintain-home, auto-including home equity in assets if sold.
- Enhanced Step 2 with context for care levels: Low (occasional checks, meals/meds), Medium (daily help, bathing), High (full-time care) as tooltips.
- Updated mobility options: Gets around fine-no help, Uses cane or walker, Needs wheelchair.
- Revised chronic conditions: None, Some (like diabetes or heart issues), Multiple/Complex (multiple serious conditions).
- Reintroduced multiple home modifications in Step 3: grab bars, stair lift, ramp, widened doors with monthly cost spread.
- Removed sidebar Help & Resources, moved VA link to Benefits expander.
- Fixed expander titles in Step 3 to show names (e.g., Income - Mom).
- Switched to st.number_input for currency fields, auto-clearing 0.00 on focus.
- Updated `APP_VERSION` to `v2025-09-03-rb21`.
- Retained `NoneType` error fixes: initialized `st.session_state.inputs` with float defaults.
- Simplified `currency_input` function to handle `None` and non-numeric values.
- Fixed `senior_care_calculator_v5_full_with_instructions_ui.json` to use `false` for boolean defaults.
- Removed `reportlab` and CSS dependencies.
- Fixed `requirements_streamlit.txt` to use one dependency per line.
- Updated `README.md` and `CHANGELOG.md` for clarity.