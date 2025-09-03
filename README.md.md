# Senior Care Cost Planner — Refactor (with Progress Bar)

## Quick start
```bash
pip install -r requirements_streamlit.txt
streamlit run streamlit_app.py
```
Open the app (usually http://localhost:8501).

## What’s new
- **Progress bar + step pills** for Steps 1–4 (Who & Context → Care Plan(s) → Finances → Results)
- Clear flows for **Myself**, **Spouse/Partner**, **Parent/POA/Friend**, and **Couple**
- **Home strategy** drives UI (Keep / Sell / HECM / HELOC)
- **Stay at Home (no paid care)** vs **In-Home Care** disambiguation
- Guaranteed **spouse income** collection when included
- **VA A&A** tier dropdown with **impact preview**
- **Assets**: HELOC lives here; sale auto-calcs net proceeds; home equity hidden if keeping the home

