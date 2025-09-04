# Changelog

## 2025-09-03
- Replace deprecated `st.experimental_rerun` with safe `st_rerun()` helper; only used for file upload.
- Add explicit couple scenario and restore spouse/parent naming; always include second person for couple.
- Move common/aggregate Income and Assets to overlay-driven schema.
- Keep UI groups modular: overlay can replace or append fields; new groups can be added without Python edits.
- Improve readability: larger base font, clearer section prompts.
- **New**: Added progress bar, sliders for care hours/days, inline currency validation, empathetic messaging, Altair chart for runway, PDF export, and custom CSS for accessibility.
- **New**: Added `reportlab` and `altair` to requirements.
- **New**: Added `static/style.css` for WCAG-compliant styling.
- **Fix**: Refactored Altair chart data to use list of dicts instead of pandas DataFrame to avoid dependency and runtime errors.