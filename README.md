# M7 Streamlit Traffic Operations Dashboard

This version presents the M7 pipeline as a Streamlit dashboard for hackathon demos. It keeps the existing M5/M6 Python logic and replaces the HTML/CSS/JS UI with a Streamlit interface.

## Run

```powershell
cd C:\Users\user\Downloads\m7_dynamic_dashboard_mappls_only\m7_dynamic_dashboard_mappls_only

# Optional if your pipeline artifacts are in a different folder:
$env:THEME2_PIPELINE_DIR = "C:\Users\user\Downloads\flipkart-20260621T143502Z-3-001\flipkart"

pip install -r requirements.txt
streamlit run .\streamlit_app.py
```

The dashboard asks for the MapMyIndia/Mappls Web SDK key in the sidebar at runtime. The key is not hardcoded into the source.

## What It Shows

- Historical incident KPIs and closure rate.
- MapMyIndia/Mappls operations map with corridor, hotspot, historical, diversion, and resource layers.
- Live M5 prediction form for closure probability and CIS.
- M6 resource plan with officers, barricades, diversion priority, and rationale.
- Forecast hotspots, top corridors, top causes, and model readout metrics.

## Required Pipeline Files

The app expects the same pipeline artifacts used by the original dashboard, including:

- `m5_inference_engine.py`
- `m6_resource_rule_engine.py`
- `clean_incidents.csv`
- `cis_scores.csv`
- `feature_matrix.csv`
- `forecast.json`
- `corridor_endpoints.json`
- model pickle/joblib artifacts

By default, the app uses:

```text
C:\Users\user\Downloads\flipkart-20260621T143502Z-3-001\flipkart
```

Set `THEME2_PIPELINE_DIR` before running Streamlit if your artifacts are somewhere else.

## Legacy Files

The old `web/` folder and `m7_dashboard_server.py` are kept for reference, but the recommended hackathon UI is:

```powershell
streamlit run .\streamlit_app.py
```
