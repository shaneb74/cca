# Senior Care Cost Planner

A Streamlit app that guides families through estimating monthly care costs and affordability.

## Features
- 4-step wizard with clear labels and larger, high-contrast UI
- Live sidebar summary of key numbers
- Couple/parent/spouse scenarios with real-name labels
- Overlay-driven schema for income and assets (common buckets + catch‑all)
- Save/Load plan to/from JSON
- No deprecated Streamlit APIs; compatible with Streamlit 1.31+

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate  # or use your shell's variant
pip install -r requirements_streamlit.txt
streamlit run streamlit_app.py
```

## Deploy
Commit these files to your repo and point Streamlit Cloud at the branch and `streamlit_app.py` path.
If you see the sidebar footer `App v2025-09-03-clean`, you’re on this build.

## File overview
- `streamlit_app.py` app code
- `senior_care_calculator_v5_full_with_instructions_ui.json` base schema
- `senior_care_modular_overlay.json` overlay (adds household income group, replaces asset fields)
- `requirements_streamlit.txt` pinned dependencies
- `CHANGELOG.md` notable changes
