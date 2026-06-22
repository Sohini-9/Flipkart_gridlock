r"""
M7 - Dynamic dashboard server
=============================

Runs a no-extra-dependency dashboard API over your existing pipeline outputs.
It serves the frontend from ./web and exposes:

  GET  /api/config    Map SDK/runtime config
  GET  /api/overview  Historical incidents, forecasts, model metrics
  POST /api/predict   Live event -> M5 prediction -> M6 resource plan

Usage:
  set THEME2_PIPELINE_DIR=C:\Users\Hp\Downloads\flipkart-20260621T143502Z-3-001\flipkart
  set M7_MAPPLS_SDK_KEY=your_mappls_or_mapmyindia_web_sdk_key
  python m7_dashboard_server.py
"""

from __future__ import annotations

import json
import math
import os
import pickle
import sys
import traceback
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import joblib


HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
DEFAULT_PIPELINE_DIR = Path(r"C:\Users\user\Downloads\flipkart-20260621T143502Z-3-001\flipkart")
PIPELINE_DIR = Path(os.environ.get("THEME2_PIPELINE_DIR", str(DEFAULT_PIPELINE_DIR))).resolve()
HOST = os.environ.get("M7_HOST", "127.0.0.1")
PORT = int(os.environ.get("M7_PORT", "8057"))
MAPPLS_SDK_KEY = (os.environ.get("M7_MAPPLS_SDK_KEY") or os.environ.get("MAPPLS_API_KEY") or "").strip()

if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

os.environ.setdefault("THEME2_PIPELINE_DIR", str(PIPELINE_DIR))


ARTIFACTS = None
M5_MODULE = None
M6_MODULE = None
OVERVIEW_CACHE = None
USING_FALLBACK_SCORER = False


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def finite_float(value, default=None):
    try:
        value = float(value)
        if math.isfinite(value):
            return value
    except Exception:
        pass
    return default


def to_jsonable(value: Any):
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def load_pipeline_modules():
    global ARTIFACTS, M5_MODULE, M6_MODULE, USING_FALLBACK_SCORER
    if ARTIFACTS is not None:
        return M5_MODULE, M6_MODULE, ARTIFACTS

    import importlib

    M5_MODULE = importlib.import_module("m5_inference_engine")
    M6_MODULE = importlib.import_module("m6_resource_rule_engine")
    try:
        ARTIFACTS = M5_MODULE.PipelineArtifacts()
    except ModuleNotFoundError as exc:
        if exc.name != "xgboost":
            raise
        print("[M7] xgboost is not installed; using dashboard fallback CIS scorer.")
        ARTIFACTS = build_dashboard_artifacts_without_xgboost()
        USING_FALLBACK_SCORER = True
    return M5_MODULE, M6_MODULE, ARTIFACTS


def load_pickle_or_joblib(path: Path):
    try:
        with path.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return joblib.load(path)


class FallbackCISScorer:
    """Small dashboard fallback when xgboost is unavailable locally.

    It uses historical CIS means from cis_scores.csv by cause, corridor, and
    hour. This keeps the dashboard runnable, while environments with xgboost
    still use the real scorer_model.pkl through M5's normal path.
    """

    def __init__(self, encoding_maps: dict, cis_scores: pd.DataFrame):
        self.inverse_maps = {
            col: {int(code): cat for cat, code in mapping.items()}
            for col, mapping in encoding_maps.items()
        }
        self.global_mean = float(pd.to_numeric(cis_scores["CIS"], errors="coerce").mean())
        self.by_cause = cis_scores.groupby("event_cause")["CIS"].mean().to_dict()
        self.by_corridor = cis_scores.groupby("corridor_final")["CIS"].mean().to_dict()
        self.by_hour = cis_scores.groupby("hour")["CIS"].mean().to_dict()

    def predict(self, X):
        rows = X.to_dict(orient="records") if hasattr(X, "to_dict") else list(X)
        preds = []
        for row in rows:
            cause = self.inverse_maps.get("event_cause", {}).get(int(row.get("event_cause_code", -1)))
            corridor = self.inverse_maps.get("corridor_final", {}).get(int(row.get("corridor_final_code", -1)))
            hour = row.get("hour")
            values = [
                self.by_cause.get(cause),
                self.by_corridor.get(corridor),
                self.by_hour.get(hour),
                self.global_mean,
            ]
            values = [float(v) for v in values if v is not None and math.isfinite(float(v))]
            preds.append(sum(values) / len(values))
        return preds


class DashboardArtifacts:
    pass


def build_dashboard_artifacts_without_xgboost():
    artifacts = DashboardArtifacts()
    with (PIPELINE_DIR / "category_encoding_maps.json").open("r", encoding="utf-8") as f:
        artifacts.encoding_maps = json.load(f)

    artifacts.corridor_model = load_pickle_or_joblib(PIPELINE_DIR / "corridor_model.pkl")

    with (PIPELINE_DIR / "nearest_corridor_nn.pkl").open("rb") as f:
        d = pickle.load(f)
        artifacts.corridor_nn_model = d["model"]
        artifacts.corridor_nn_labels = d["labels"]

    with (PIPELINE_DIR / "police_station_nn.pkl").open("rb") as f:
        d = pickle.load(f)
        artifacts.police_station_nn_model = d["model"]
        artifacts.police_station_nn_labels = d["labels"]

    with (PIPELINE_DIR / "cis_signal_tables.json").open("r", encoding="utf-8") as f:
        artifacts.cis_signal_tables = json.load(f)

    with (PIPELINE_DIR / "eta_baselines.json").open("r", encoding="utf-8") as f:
        artifacts.eta_baselines = json.load(f)

    artifacts.closure_bundle = joblib.load(PIPELINE_DIR / "closure_model_bundle.pkl")
    artifacts.closure_metrics = read_json(PIPELINE_DIR / "closure_eval_metrics.json", {})
    artifacts.scorer_metrics = read_json(PIPELINE_DIR / "scorer_eval_metrics.json", {})
    cis_scores = pd.read_csv(PIPELINE_DIR / "cis_scores.csv")
    artifacts.scorer_model = FallbackCISScorer(artifacts.encoding_maps, cis_scores)
    artifacts.scorer_model_class = "HistoricalCISMeanFallback"
    artifacts.forecast = read_json(PIPELINE_DIR / "forecast.json", {})
    return artifacts


def top_forecast_hotspots(forecast: dict, limit=12):
    rows = []
    for corridor, payload in (forecast or {}).items():
        next_forecast = (payload.get("next_weeks_forecast") or [{}])[0]
        predicted = finite_float(next_forecast.get("predicted_incidents"), 0.0)
        rows.append({
            "corridor": corridor,
            "predicted_incidents": round(predicted, 2),
            "confidence": payload.get("confidence", "UNKNOWN"),
            "avg_weekly_incidents_historical": round(
                finite_float(payload.get("avg_weekly_incidents_historical"), 0.0), 2
            ),
            "week_start": next_forecast.get("week_start"),
        })
    return sorted(rows, key=lambda r: r["predicted_incidents"], reverse=True)[:limit]


def endpoint_segments(endpoints: dict, forecast: dict):
    segments = []
    for corridor, points in (endpoints or {}).items():
        origin = points.get("origin")
        destination = points.get("destination")
        if not origin or not destination:
            continue
        forecast_payload = (forecast or {}).get(corridor, {})
        next_forecast = (forecast_payload.get("next_weeks_forecast") or [{}])[0]
        segments.append({
            "corridor": corridor,
            "origin": origin,
            "destination": destination,
            "forecast": finite_float(next_forecast.get("predicted_incidents"), 0.0),
            "confidence": forecast_payload.get("confidence", "UNKNOWN"),
        })
    return segments


def historical_heat_points(clean_df: pd.DataFrame, cis_df: pd.DataFrame | None, limit=1600):
    cols = ["id", "latitude", "longitude", "event_cause", "corridor", "requires_road_closure", "start_datetime"]
    df = clean_df[[c for c in cols if c in clean_df.columns]].copy()
    if cis_df is not None and {"id", "CIS"}.issubset(cis_df.columns):
        df = df.merge(cis_df[["id", "CIS"]], on="id", how="left")
    else:
        df["CIS"] = 0.0

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["CIS"] = pd.to_numeric(df["CIS"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["latitude", "longitude"])
    if len(df) > limit:
        high = df.sort_values("CIS", ascending=False).head(limit // 2)
        rest = df.drop(high.index).sample(limit - len(high), random_state=42)
        df = pd.concat([high, rest], ignore_index=True)

    out = []
    for row in df.itertuples(index=False):
        item = row._asdict()
        closed = str(item.get("requires_road_closure", "")).lower() in {"true", "1", "yes"}
        out.append({
            "id": item.get("id"),
            "lat": finite_float(item.get("latitude")),
            "lng": finite_float(item.get("longitude")),
            "cause": item.get("event_cause"),
            "corridor": item.get("corridor"),
            "closure": closed,
            "cis": round(finite_float(item.get("CIS"), 0.0), 3),
            "start": str(item.get("start_datetime", "")),
        })
    return out


def model_metric_cards():
    closure = read_json(PIPELINE_DIR / "closure_eval_metrics.json", {})
    scorer = read_json(PIPELINE_DIR / "scorer_eval_metrics.json", {})
    forecaster = read_json(PIPELINE_DIR / "forecaster_eval_metrics.json", {})

    closure_metrics = closure.get("metrics", closure)
    return {
        "closure": {
            "model": closure.get("model_name"),
            "roc_auc": closure_metrics.get("roc_auc"),
            "precision": closure_metrics.get("precision"),
            "recall": closure_metrics.get("recall"),
            "f1": closure_metrics.get("f1"),
            "threshold": closure.get("decision_threshold"),
        },
        "cis": {
            "model": scorer.get("model_name") or scorer.get("model"),
            "mae": scorer.get("mae"),
            "r2": scorer.get("r2"),
            "max_possible_95th_pct": scorer.get("max_possible_95th_pct"),
        },
        "forecast": {
            "summary": forecaster.get("summary") or forecaster.get("model_summary"),
            "generated_rows": forecaster.get("generated_rows"),
        },
    }


def build_overview():
    global OVERVIEW_CACHE
    if OVERVIEW_CACHE is not None:
        return OVERVIEW_CACHE

    clean_path = PIPELINE_DIR / "clean_incidents.csv"
    feature_path = PIPELINE_DIR / "feature_matrix.csv"
    cis_path = PIPELINE_DIR / "cis_scores.csv"

    clean = pd.read_csv(clean_path)
    feature = pd.read_csv(feature_path) if feature_path.exists() else None
    cis = pd.read_csv(cis_path) if cis_path.exists() else None
    forecast = read_json(PIPELINE_DIR / "forecast.json", {})
    endpoints = read_json(PIPELINE_DIR / "corridor_endpoints.json", {})
    resource_plan = read_json(PIPELINE_DIR / "resource_plan.json", [])

    closure_rate = (
        clean["requires_road_closure"].astype(str).str.lower().isin(["true", "1", "yes"]).mean()
        if "requires_road_closure" in clean.columns else 0.0
    )
    top_causes = (
        clean["event_cause"].fillna("UNKNOWN").value_counts().head(10).rename_axis("cause")
        .reset_index(name="count").to_dict(orient="records")
    )

    if feature is not None and "corridor_final" in feature.columns:
        top_corridors = (
            feature["corridor_final"].fillna("UNKNOWN").value_counts().head(12)
            .rename_axis("corridor").reset_index(name="count").to_dict(orient="records")
        )
    else:
        top_corridors = (
            clean["corridor"].fillna("UNKNOWN").value_counts().head(12)
            .rename_axis("corridor").reset_index(name="count").to_dict(orient="records")
        )

    OVERVIEW_CACHE = {
        "pipeline_dir": str(PIPELINE_DIR),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "incidents": int(len(clean)),
            "closure_rate": round(float(closure_rate), 4),
            "corridors": int(clean["corridor"].nunique()) if "corridor" in clean.columns else None,
            "causes": int(clean["event_cause"].nunique()) if "event_cause" in clean.columns else None,
        },
        "metrics": model_metric_cards(),
        "top_causes": top_causes,
        "top_corridors": top_corridors,
        "heat_points": historical_heat_points(clean, cis),
        "forecast_hotspots": top_forecast_hotspots(forecast),
        "corridor_segments": endpoint_segments(endpoints, forecast),
        "resource_examples": resource_plan[:3] if isinstance(resource_plan, list) else [],
    }
    return OVERVIEW_CACHE


def nearest_corridor_segments(corridor: str, event_lat: float, event_lng: float, limit=3):
    endpoints = read_json(PIPELINE_DIR / "corridor_endpoints.json", {})
    forecast = read_json(PIPELINE_DIR / "forecast.json", {})
    rows = []
    for name, points in endpoints.items():
        origin = points.get("origin")
        destination = points.get("destination")
        if not origin or not destination:
            continue
        mid_lat = (origin[0] + destination[0]) / 2
        mid_lng = (origin[1] + destination[1]) / 2
        dist = math.hypot(mid_lat - event_lat, mid_lng - event_lng)
        priority = 0 if name == corridor else 1
        next_forecast = ((forecast.get(name, {}) or {}).get("next_weeks_forecast") or [{}])[0]
        rows.append((priority, dist, {
            "name": name,
            "origin": origin,
            "destination": destination,
            "polyline": [[event_lat, event_lng], origin, destination],
            "forecast_incidents": finite_float(next_forecast.get("predicted_incidents"), 0.0),
            "source": "corridor_endpoints",
        }))
    return [r[2] for r in sorted(rows, key=lambda x: (x[0], x[1]))[:limit]]


def resource_pins(event_lat: float, event_lng: float, plan: dict):
    pins = []
    officer_count = int(plan.get("officer_count", 0) or 0)
    barricade_count = int(plan.get("barricade_count", 0) or 0)
    offsets = [
        (0.0014, 0.0008), (-0.0013, 0.0010), (0.0011, -0.0012), (-0.0012, -0.0009),
        (0.0020, 0.0), (0.0, 0.0020), (-0.0020, 0.0), (0.0, -0.0020),
    ]
    for i in range(officer_count):
        off = offsets[i % len(offsets)]
        pins.append({"type": "officer", "label": f"Officer {i + 1}", "lat": event_lat + off[0], "lng": event_lng + off[1]})
    for i in range(barricade_count):
        angle = (2 * math.pi * i) / max(barricade_count, 1)
        pins.append({
            "type": "barricade",
            "label": f"Barricade {i + 1}",
            "lat": event_lat + math.sin(angle) * 0.0018,
            "lng": event_lng + math.cos(angle) * 0.0018,
        })
    return pins


def predict_live_event(event: dict):
    m5, m6, artifacts = load_pipeline_modules()
    prediction = m5.predict_event(event, artifacts)
    plan = m6.build_resource_plan(prediction)
    lat = finite_float(prediction["input"]["latitude"], 12.9716)
    lng = finite_float(prediction["input"]["longitude"], 77.5946)
    corridor = prediction["resolved_location"].get("corridor_final", "Non-corridor")
    diversions = nearest_corridor_segments(corridor, lat, lng, limit=3)
    return {
        "prediction": prediction,
        "resource_plan": plan,
        "diversion_routes": diversions,
        "resource_pins": resource_pins(lat, lng, plan),
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/config":
            if not MAPPLS_SDK_KEY:
                return self.write_error(500, "M7_MAPPLS_SDK_KEY is required for the MapMyIndia/Mappls map.")
            return self.write_json({
                "pipeline_dir": str(PIPELINE_DIR),
                "mappls_sdk_key": MAPPLS_SDK_KEY,
                "map_provider": "mappls",
                "using_fallback_scorer": USING_FALLBACK_SCORER,
            })
        if path == "/api/overview":
            try:
                return self.write_json(build_overview())
            except Exception as exc:
                return self.write_error(500, exc)
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/predict":
            return self.write_error(404, "Unknown endpoint")
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length).decode("utf-8")
            event = json.loads(body or "{}")
            return self.write_json(predict_live_event(event))
        except Exception as exc:
            return self.write_error(500, exc)

    def write_json(self, payload: Any, status=200):
        body = json.dumps(to_jsonable(payload), indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_error(self, status: int, exc: Any):
        payload = {
            "error": str(exc),
            "traceback": traceback.format_exc(limit=5),
        }
        return self.write_json(payload, status=status)


def main():
    if not PIPELINE_DIR.exists():
        raise FileNotFoundError(f"Pipeline directory not found: {PIPELINE_DIR}")
    if not MAPPLS_SDK_KEY:
        raise RuntimeError("M7_MAPPLS_SDK_KEY is required for the MapMyIndia/Mappls map.")
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    url = f"http://{HOST}:{PORT}"
    print(f"[M7] Serving dashboard at {url}")
    print(f"[M7] Pipeline artifacts: {PIPELINE_DIR}")
    print("[M7] Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
