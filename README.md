# M7 Dynamic Dashboard

This dashboard turns the pipeline artifacts into an interactive judge-facing UI.

## Run

```powershell
cd C:\Users\Hp\Documents\Codex\2026-06-21\files-mentioned-by-the-user-data\outputs\m7_dynamic_dashboard
$env:THEME2_PIPELINE_DIR = "C:\Users\Hp\Downloads\flipkart-20260621T143502Z-3-001\flipkart"
$env:M7_MAPPLS_SDK_KEY = "your_mappls_web_sdk_key"
python .\m7_dashboard_server.py
```

Open:

```text
http://127.0.0.1:8057
```

`M7_MAPPLS_SDK_KEY` is required. The dashboard uses only the MapMyIndia/Mappls Web SDK for the map.

If `xgboost` is not installed, the dashboard keeps running with a clearly named `HistoricalCISMeanFallback` for the CIS regressor. Install the same `xgboost` version used to create `scorer_model.pkl` if you want M5 to load the exact saved XGBoost artifact.

## What It Uses

- `m5_inference_engine.py` for live closure and CIS prediction.
- `m6_resource_rule_engine.py` for officers, barricades, and diversion priority.
- `clean_incidents.csv`, `cis_scores.csv`, and `feature_matrix.csv` for historical heat and summaries.
- `forecast.json` for hotspot highlights.
- `corridor_endpoints.json` for corridor and diversion polylines.
- MapMyIndia/Mappls Web SDK.

## API

- `GET /api/config`
- `GET /api/overview`
- `POST /api/predict`

Example payload:

```json
{
  "latitude": 13.005,
  "longitude": 77.57,
  "event_cause": "vip_movement",
  "event_type": "planned",
  "priority": "HIGH",
  "timestamp": "2026-06-20T09:00:00",
  "description": "traffic diverted and road closed for convoy movement",
  "address": "Bellary Road, Bengaluru",
  "was_escalated": true
}
```
