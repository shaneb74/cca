Changelog
2025-09-03

Updated Step 1 with empathetic tone: "Helping you understand senior care costs" and "Let's start with who you're caring for" prompt, using radio options Myself, One parent, Both parents, Loved one.
Enhanced Step 2 with context: "With {name} heading into care, is {partner/spouse} okay staying home alone? Or might they need help too?" with a dropdown for the second person's care needs (Staying home alone, Needs in-home help, Maybe assisted living?, Same as {name}, He's okay, no change).
Added dynamic name capture in Step 1: auto-suggests names (e.g., Me, Mom, Dad) and includes spouse/partner name for One parent if applicable.
Updated APP_VERSION to v2025-09-03-rb19.
Retained NoneType error fixes: initialized st.session_state.inputs with float defaults for all currency fields.
Simplified currency_input function to handle None and non-numeric values robustly.
Fixed senior_care_calculator_v5_full_with_instructions_ui.json to use false for boolean defaults (ltc_insurance_person_a, ltc_insurance_person_b).
Removed reportlab and CSS dependencies to avoid past errors.
Fixed requirements_streamlit.txt to use one dependency per line.
Updated README.md and CHANGELOG.md for clarity and deployment instructions.
