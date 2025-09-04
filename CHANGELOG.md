Changelog
2025-09-03

Refactored streamlit_app.py to fix NoneType errors in Step 3 by initializing st.session_state.inputs with float defaults for all currency fields.
Simplified currency_input function to handle None and non-numeric values robustly.
Updated APP_VERSION to v2025-09-03-rb14.
Fixed senior_care_calculator_v5_full_with_instructions_ui.json to use false for boolean defaults (ltc_insurance_person_a, ltc_insurance_person_b).
Removed reportlab and CSS dependencies to avoid past errors.
Fixed requirements_streamlit.txt to use one dependency per line.
Updated README.md and CHANGELOG.md for clarity and deployment instructions.
