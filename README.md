Senior Care Cost Planner
A Streamlit app that guides families through estimating monthly care costs and affordability, designed for seniors with a focus on clear, empathetic UX.
Features

4-step wizard with clear labels and intuitive inputs
Progress bar and empathetic messaging for ease of use
Live sidebar with help resources and key summaries
Couple/parent/spouse scenarios with personalized name labels
Overlay-driven schema for income and assets (common buckets + catch-all)
Sliders for intuitive care hours/days input
Visual asset runway chart
Save/Load plan to/from JSON
No deprecated Streamlit APIs; compatible with Streamlit 1.31+

Deploy

Commit all files to your GitHub repo (cca, branch Grok-Dev).
Ensure requirements.txt, senior_care_calculator_v5_full_with_instructions_ui.json, and senior_care_modular_overlay.json are in the repo root.
Point Streamlit Cloud to your branch and streamlit_app.py.
Verify the sidebar footer shows App v2025-09-03-rb19.
If deployment fails, check Streamlit Cloud logs. Ensure requirements.txt is present, correctly formatted (Unix line endings, no extra whitespace), and includes streamlit>=1.31,<2 and altair>=5.0.1. Verify both JSON schema files are present and correctly formatted.

File overview

streamlit_app.py: App code with enhanced UX (progress bar, sliders, runway chart) and robust error handling, updated for empathetic Step 1 and Step 2 flow
senior_care_calculator_v5_full_with_instructions_ui.json: Base schema
senior_care_modular_overlay.json: Overlay for income/assets
requirements_streamlit.txt: Pinned dependencies for reference
requirements.txt: Streamlit Cloud-specific dependencies
CHANGELOG.md: Notable changes

Notes

Ensure senior_care_calculator_v5_full_with_instructions_ui.json and senior_care_modular_overlay.json are in the repo root for full functionality.
Test on mobile devices for responsiveness.
If deployment issues persist, verify file presence in the GitHub repo (cca, branch Grok-Dev) and contact Streamlit support with deployment logs.
