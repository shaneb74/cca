# Senior Care Cost Planner — Fresh Build

## Run
```bash
pip install -r requirements_streamlit.txt
streamlit run streamlit_app.py
```

## What’s in this build
- Progress bar & step pills (4 steps)
- Person A always has a care plan (no “do they need care?” prompt)
- 24-hour sliders for in-home hours (1-hr steps) with rate interpolation
- Tooltips for hours, care level, mobility, chronic, room type, VA
- Room type tooltip + “Share one unit” inline caption
- Home strategy banner (Keep / Sell / HECM / HELOC)
- Assets: home equity hidden if keeping; HELOC optional inside Assets
- Optional monthly costs: inline calculator to monthly-ize home mods
- VA Aid & Attendance: dropdown tiers + eligibility + spouse logic
- JSON label alignment: “Other savings & investments”
