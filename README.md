# Senior Care Cost Planner — Refactor (with Progress Bar)

## Quick start
```bash
pip install -r requirements_streamlit.txt
streamlit run streamlit_app.py
```
Open the app (usually http://localhost:8501).

## Highlights
- Progress bar + step pills for Steps 1–4
- 24‑hour slider for in‑home hours (1‑hour steps) with smooth pricing (interpolation)
- Clear flows for Myself / Spouse / Parent/POA/Friend / Couple
- Home strategy drives UI (Keep / Sell / HECM / HELOC)
- Spouse income capture safeguarded
- VA A&A tier dropdown (always enabled), eligibility gate, inline explainer, spouse logic to avoid double counting
- Assets: sale auto‑proceeds, HELOC in Assets, home equity hidden if keeping home
- Optional monthly costs: **Home modifications** calculator inline (one‑time → monthly)
