Senior Care Cost Planner
A Streamlit app that guides families through estimating monthly care costs and affordability, designed for seniors with a focus on clear, empathetic UX.
Features

4-step wizard with clear labels, larger fonts, and high-contrast UI
Progress bar and empathetic messaging for ease of use
Live sidebar with help resources and key summaries
Couple/parent/spouse scenarios with personalized name labels
Overlay-driven schema for income and assets (common buckets + catch-all)
Sliders for intuitive care hours/days input
Visual asset runway chart and PDF export
Save/Load plan to/from JSON
No deprecated Streamlit APIs; compatible with Streamlit 1.31+

Run locally
python -m venv .venv && source .venv/bin/activate  # or use your shell's variant
pip install -r requirements_streamlit.txt
streamlit run streamlit_app.py

Deploy

Commit all files to your GitHub repo.
Ensure static/style.css is in the static folder and requirements.txt is in the repo root.
Point Streamlit Cloud to your branch and streamlit_app.py.
Verify the sidebar footer shows App v2025-09-03-rb13.
If deployment fails (e.g., missing dependencies like reportlab), check Streamlit Cloud logs. Ensure requirements.txt is present, correctly formatted (Unix line endings, no extra whitespace), and includes reportlab==4.2.5.

File overview

streamlit_app.py: App code with enhanced UX (progress bar, sliders, PDF export)
senior_care_calculator_v5_full_with_instructions_ui.json: Base schema
senior_care_modular_overlay.json: Overlay for income/assets
requirements_streamlit.txt: Pinned dependencies for local development
requirements.txt: Streamlit Cloud-specific dependencies (mirrors requirements_streamlit.txt)
static/style.css: Custom styling for accessibility
CHANGELOG.md: Notable changes

Notes

Ensure static/style.css is in the repo’s static folder and requirements.txt is in the repo root for Streamlit Cloud.
PDF export uses reportlab for lightweight summary generation.
Test on mobile devices for responsiveness.
If reportlab fails to install, verify requirements.txt is correctly formatted. Contact Streamlit support if the issue persists.
