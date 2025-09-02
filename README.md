# Senior Care Cost Calculator (Streamlit)

## Files
- `streamlit_app.py` → Streamlit UI (with robust JSON guards & upload fallback)
- `senior_care_calculator_v5_full_with_instructions_ui.json` → Base calculator spec
- `senior_care_modular_overlay.json` → Optional overlay (category + item gating)
- `requirements_streamlit.txt` → Python dependencies

## Run locally
```bash
pip install -r requirements_streamlit.txt
streamlit run streamlit_app.py
```

## Deploy to Streamlit Cloud
- Push all files to your GitHub repo **root**.
- In Streamlit Cloud, point the app to `streamlit_app.py`.
- It auto-installs from `requirements_streamlit.txt` and loads the JSON files.
