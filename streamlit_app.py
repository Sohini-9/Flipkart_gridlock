from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

import m7_dashboard_server as m7


MAP_RUNTIME_DIR = Path(tempfile.gettempdir()) / "m7_streamlit_mappls_runtime"
MAP_RUNTIME_PORT = int(os.environ.get("M7_MAP_RUNTIME_PORT", "8502"))
MAP_SERVER_STARTED = False


st.set_page_config(
    page_title="M7 Traffic Operations Dashboard",
    page_icon="M7",
    layout="wide",
    initial_sidebar_state="expanded",
)


CAUSES = [
    "vehicle_breakdown",
    "vip_movement",
    "water_logging",
    "accident",
    "construction",
    "tree_fall",
    "pot_holes",
]


def css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --m7-ink: #0f172a;
          --m7-muted: #64748b;
          --m7-line: #dbe5f0;
          --m7-panel: #ffffff;
          --m7-soft: #eef5f7;
          --m7-teal: #0f766e;
          --m7-blue: #2563eb;
          --m7-red: #dc2626;
          --m7-orange: #f97316;
        }
        .block-container {
          padding-top: 1.2rem;
          padding-bottom: 2.5rem;
          max-width: 1480px;
        }
        section[data-testid="stSidebar"] {
          background: #f8fafc;
          border-right: 1px solid var(--m7-line);
        }
        h1, h2, h3 {
          color: var(--m7-ink);
          letter-spacing: 0;
        }
        .m7-hero {
          border: 1px solid var(--m7-line);
          background: linear-gradient(135deg, #ffffff 0%, #eef8f6 55%, #e8f0ff 100%);
          border-radius: 8px;
          padding: 18px 20px;
          margin-bottom: 14px;
        }
        .m7-hero h1 {
          font-size: 2rem;
          margin: 0 0 4px;
        }
        .m7-hero p {
          color: var(--m7-muted);
          margin: 0;
        }
        .m7-card {
          border: 1px solid var(--m7-line);
          background: var(--m7-panel);
          border-radius: 8px;
          padding: 14px 16px;
          min-height: 104px;
          box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
        }
        .m7-card span {
          color: var(--m7-muted);
          font-size: 0.83rem;
          font-weight: 700;
          text-transform: uppercase;
        }
        .m7-card strong {
          display: block;
          color: var(--m7-ink);
          font-size: 1.9rem;
          line-height: 1.15;
          margin-top: 8px;
        }
        .m7-card small {
          display: block;
          color: var(--m7-muted);
          margin-top: 6px;
        }
        .m7-section {
          border: 1px solid var(--m7-line);
          border-radius: 8px;
          background: #ffffff;
          padding: 16px;
          margin-bottom: 14px;
        }
        .m7-rank {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 9px 0;
          border-bottom: 1px solid #edf2f7;
        }
        .m7-rank:last-child {
          border-bottom: 0;
        }
        .m7-rank span {
          color: var(--m7-ink);
          font-weight: 650;
          overflow-wrap: anywhere;
        }
        .m7-rank b {
          color: var(--m7-teal);
          white-space: nowrap;
        }
        div[data-testid="stMetric"] {
          border: 1px solid var(--m7-line);
          border-radius: 8px;
          padding: 12px 14px;
          background: #ffffff;
        }
        div[data-testid="stButton"] button,
        div[data-testid="stFormSubmitButton"] button {
          border-radius: 8px;
          border: 1px solid #0f766e;
          background: #0f766e;
          color: white;
          font-weight: 800;
        }
        div[data-testid="stButton"] button:hover,
        div[data-testid="stFormSubmitButton"] button:hover {
          border-color: #115e59;
          background: #115e59;
          color: white;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def html_escape(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )


def fmt(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "--"


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "--"


@st.cache_data(show_spinner=False)
def cached_overview() -> dict:
    return m7.to_jsonable(m7.build_overview())


def card(label: str, value: str, detail: str = "") -> None:
    st.markdown(
        f"""
        <div class="m7-card">
          <span>{html_escape(label)}</span>
          <strong>{html_escape(value)}</strong>
          <small>{html_escape(detail)}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )


def rank_list(rows: list[dict], label_key: str, value_key: str, digits: int | None = None) -> None:
    if not rows:
        st.caption("No data available.")
        return
    html = []
    for row in rows:
        value = row.get(value_key)
        if digits is not None:
            value = fmt(value, digits)
        html.append(
            f"""
            <div class="m7-rank">
              <span>{html_escape(row.get(label_key, "Unknown"))}</span>
              <b>{html_escape(value)}</b>
            </div>
            """
        )
    st.markdown("".join(html), unsafe_allow_html=True)


def build_map_html(mappls_key: str, overview: dict, prediction_result: dict | None) -> str:
    heat_points = (overview.get("heat_points") or [])[:450]
    payload = {
        "heatPoints": heat_points,
        "corridorSegments": overview.get("corridor_segments") or [],
        "forecastHotspots": overview.get("forecast_hotspots") or [],
        "prediction": prediction_result,
    }
    payload_json = json.dumps(payload, ensure_ascii=False)
    key_json = json.dumps(mappls_key)
    return f"""
    <!doctype html>
    <html>
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    </head>
    <body>
    <div id="m7-map-wrap">
      <div id="m7-map"></div>
      <div class="legend">
        <span><i class="dot hist"></i>Historical</span>
        <span><i class="dot close"></i>Closure</span>
        <span><i class="dot hot"></i>Hotspot</span>
        <span><i class="line"></i>Diversion</span>
      </div>
      <div id="m7-map-status">Loading MapMyIndia/Mappls...</div>
    </div>
    <style>
      html, body {{ margin: 0; padding: 0; }}
      #m7-map-wrap {{
        position: relative;
        height: 610px;
        border: 1px solid #dbe5f0;
        border-radius: 8px;
        overflow: hidden;
        background: #e8eef5;
        font-family: Inter, Segoe UI, Arial, sans-serif;
      }}
      #m7-map {{ position: absolute; inset: 0; }}
      .legend, #m7-map-status {{
        position: absolute;
        z-index: 10;
        background: rgba(255, 255, 255, 0.94);
        border: 1px solid rgba(15, 23, 42, 0.08);
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.12);
        border-radius: 8px;
      }}
      .legend {{
        left: 14px;
        bottom: 14px;
        display: flex;
        gap: 12px;
        align-items: center;
        padding: 9px 11px;
        font-size: 12px;
        font-weight: 800;
        color: #0f172a;
      }}
      #m7-map-status {{
        top: 14px;
        left: 14px;
        padding: 9px 11px;
        font-size: 12px;
        color: #334155;
      }}
      .dot {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 5px;
        vertical-align: middle;
      }}
      .hist {{ background: #f97316; }}
      .close {{ background: #dc2626; }}
      .hot {{ background: #7c3aed; }}
      .line {{
        width: 22px;
        height: 3px;
        background: #2563eb;
        display: inline-block;
        margin-right: 5px;
        vertical-align: middle;
      }}
    </style>
    <script>
      const mapplsKey = {key_json};
      const dashboardData = {payload_json};

      function setStatus(text) {{
        const node = document.getElementById("m7-map-status");
        if (node) node.textContent = text;
      }}

      function sdkUrls() {{
        const encoded = encodeURIComponent(mapplsKey);
        return [
          `https://apis.mappls.com/advancedmaps/api/${{encoded}}/map_sdk?layer=vector&v=3.0&callback=__m7StreamlitMapReady`,
          `https://apis.mappls.com/advancedmaps/api/${{encoded}}/map_sdk?layer=vector&v=2.0&callback=__m7StreamlitMapReady`,
          `https://apis.mappls.com/advancedmaps/api/${{encoded}}/map_sdk?v=3.0&callback=__m7StreamlitMapReady`,
        ];
      }}

      function loadScriptOnce(src) {{
        return new Promise((resolve, reject) => {{
          const script = document.createElement("script");
          script.src = src;
          script.async = true;
          script.referrerPolicy = "origin";
          script.onload = resolve;
          script.onerror = () => reject(new Error(`SDK script request failed: ${{src.replace(mapplsKey, "****")}}`));
          document.head.appendChild(script);
          setTimeout(() => reject(new Error(`SDK script timed out: ${{src.replace(mapplsKey, "****")}}`)), 15000);
        }});
      }}

      async function loadMappls() {{
        if (window.mappls && window.mappls.Map) return window.mappls;

        const errors = [];
        for (const src of sdkUrls()) {{
          try {{
            window.__m7StreamlitMapReady = () => window.mappls;
            setStatus("Loading MapMyIndia/Mappls SDK...");
            await loadScriptOnce(src);
            if (window.mappls) return window.mappls;
            errors.push(`Loaded but no window.mappls: ${{src.replace(mapplsKey, "****")}}`);
          }} catch (err) {{
            errors.push(err && err.message ? err.message : String(err));
          }}
        }}

        throw new Error(
          "Mappls SDK could not be loaded. Use a Mappls Web SDK key, check internet access, and allow localhost/127.0.0.1 in the key's web domain settings. " +
          errors.join(" | ")
        );
      }}

      async function waitForClasses(api) {{
        const deadline = Date.now() + 12000;
        while (Date.now() < deadline) {{
          if (api && api.Map && api.Marker && api.Polyline) return api;
          await new Promise((resolve) => setTimeout(resolve, 100));
        }}
        throw new Error("Mappls SDK loaded, but map drawing classes are unavailable.");
      }}

      function marker(api, map, lat, lng, html) {{
        return new api.Marker({{
          map,
          position: {{ lat: Number(lat), lng: Number(lng) }},
          popupHtml: html || ""
        }});
      }}

      function polyline(api, map, path, color, weight, opacity, html) {{
        return new api.Polyline({{
          map,
          path: path.map(([lat, lng]) => ({{ lat: Number(lat), lng: Number(lng) }})),
          strokeColor: color,
          strokeWeight: weight,
          strokeOpacity: opacity,
          popupHtml: html || ""
        }});
      }}

      function esc(value) {{
        return String(value ?? "").replace(/[&<>"']/g, (c) => ({{
          "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
        }}[c]));
      }}

      async function draw() {{
        try {{
          const api = await waitForClasses(await loadMappls());
          const map = new api.Map("m7-map", {{
            center: [12.9716, 77.5946],
            zoom: 11,
            zoomControl: true,
            location: true
          }});

          const points = [];
          dashboardData.corridorSegments.forEach((seg) => {{
            const forecast = Number(seg.forecast || 0);
            const color = forecast >= 60 ? "#dc2626" : forecast >= 25 ? "#f97316" : "#2563eb";
            polyline(api, map, [seg.origin, seg.destination], color, 3, 0.58,
              `<b>${{esc(seg.corridor)}}</b><br>Forecast: ${{forecast.toFixed(1)}} incidents<br>Confidence: ${{esc(seg.confidence)}}`);
            points.push(seg.origin, seg.destination);
          }});

          dashboardData.heatPoints.forEach((p) => {{
            if (!p.lat || !p.lng) return;
            marker(api, map, p.lat, p.lng,
              `<b>${{esc(p.cause)}}</b><br>Corridor: ${{esc(p.corridor || "Unknown")}}<br>CIS: ${{Number(p.cis || 0).toFixed(2)}}<br>Closure: ${{p.closure ? "Yes" : "No"}}`);
          }});

          dashboardData.forecastHotspots.slice(0, 8).forEach((hotspot) => {{
            const seg = dashboardData.corridorSegments.find((item) => item.corridor === hotspot.corridor);
            if (!seg) return;
            const lat = (Number(seg.origin[0]) + Number(seg.destination[0])) / 2;
            const lng = (Number(seg.origin[1]) + Number(seg.destination[1])) / 2;
            marker(api, map, lat, lng,
              `<b>${{esc(hotspot.corridor)}}</b><br>Next forecast: ${{Number(hotspot.predicted_incidents || 0).toFixed(1)}} incidents<br>Historical avg: ${{Number(hotspot.avg_weekly_incidents_historical || 0).toFixed(1)}}`);
            points.push([lat, lng]);
          }});

          if (dashboardData.prediction) {{
            const result = dashboardData.prediction;
            const input = result.prediction.input;
            const plan = result.resource_plan;
            const lat = Number(input.latitude);
            const lng = Number(input.longitude);
            marker(api, map, lat, lng,
              `<b>Live event</b><br>${{esc(input.event_cause)}}<br>Tier: ${{esc(plan.final_tier)}}`);
            points.push([lat, lng]);

            const routeColors = ["#2563eb", "#0f766e", "#9333ea"];
            result.diversion_routes.forEach((route, index) => {{
              polyline(api, map, route.polyline, routeColors[index % routeColors.length], index === 0 ? 6 : 4, 0.9,
                `<b>Diversion ${{index + 1}}: ${{esc(route.name)}}</b><br>Forecast incidents: ${{Number(route.forecast_incidents || 0).toFixed(1)}}`);
              route.polyline.forEach((p) => points.push(p));
            }});

            result.resource_pins.forEach((pin) => {{
              marker(api, map, pin.lat, pin.lng, `<b>${{esc(pin.label)}}</b><br>${{esc(pin.type)}}`);
              points.push([pin.lat, pin.lng]);
            }});
          }}

          if (points.length && map.setCenter) {{
            const lats = points.map((p) => Number(p[0])).filter(Number.isFinite);
            const lngs = points.map((p) => Number(p[1])).filter(Number.isFinite);
            if (lats.length && lngs.length) {{
              map.setCenter([
                (Math.min(...lats) + Math.max(...lats)) / 2,
                (Math.min(...lngs) + Math.max(...lngs)) / 2
              ]);
            }}
          }}
          setStatus(dashboardData.prediction ? "Live prediction and operations layers loaded." : "Historical heat, corridors, and forecast hotspots loaded.");
        }} catch (err) {{
          console.error(err);
          setStatus(`Mappls map failed: ${{err && err.message ? err.message : String(err)}}`);
        }}
      }}
      draw();
    </script>
    </body>
    </html>
    """


def ensure_map_server() -> None:
    global MAP_SERVER_STARTED
    if MAP_SERVER_STARTED:
        return
    MAP_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    def serve() -> None:
        handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(MAP_RUNTIME_DIR), **kwargs)
        try:
            server = ThreadingHTTPServer(("127.0.0.1", MAP_RUNTIME_PORT), handler)
            server.serve_forever()
        except OSError:
            pass

    thread = threading.Thread(target=serve, name="m7-mappls-map-server", daemon=True)
    thread.start()
    MAP_SERVER_STARTED = True


def render_map(mappls_key: str, overview: dict, prediction_result: dict | None) -> None:
    if not mappls_key:
        st.markdown(
            """
            <div class="m7-section" style="height: 610px; display: flex; align-items: center; justify-content: center; text-align: center; background: #e8eef5;">
              <div>
                <h3>Enter a MapMyIndia/Mappls Web SDK key</h3>
                <p style="color: #64748b; margin: 0;">The operations map renders only with a Mappls Web SDK key.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    ensure_map_server()
    map_html = build_map_html(mappls_key, overview, prediction_result)
    map_file = MAP_RUNTIME_DIR / "map.html"
    map_file.write_text(map_html, encoding="utf-8")
    map_url = f"http://localhost:{MAP_RUNTIME_PORT}/map.html?v={datetime.now().timestamp()}"
    if hasattr(st, "iframe"):
        st.iframe(map_url, height=630, scrolling=False)
    else:
        st.components.v1.iframe(map_url, height=630, scrolling=False)


def event_payload(causes: list[str]) -> dict | None:
    with st.form("live_event_form"):
        c1, c2 = st.columns(2)
        with c1:
            latitude = st.number_input("Latitude", value=12.9716, step=0.000001, format="%.6f")
            cause = st.selectbox("Cause", causes, index=0)
            priority = st.selectbox("Priority", ["LOW", "HIGH"], index=0)
        with c2:
            longitude = st.number_input("Longitude", value=77.5573, step=0.000001, format="%.6f")
            event_type = st.selectbox("Event Type", ["unplanned", "planned"], index=0)
            now = datetime.now()
            event_date = st.date_input("Event Date", value=now.date())
            event_time = st.time_input("Event Time", value=now.time().replace(microsecond=0))

        description = st.text_area("Description", value="lorry breakdown on left lane, slow traffic", height=88)
        address = st.text_input("Address", value="Mysore Road, Bengaluru")
        r1, r2, r3 = st.columns([1, 1, 2])
        with r1:
            was_escalated = st.checkbox("Escalated", value=False)
        with r2:
            authenticated = st.checkbox("Authenticated", value=True)
        with r3:
            submitted = st.form_submit_button("Run M5 + M6 Prediction", use_container_width=True)

    if not submitted:
        return None

    return {
        "latitude": latitude,
        "longitude": longitude,
        "event_cause": cause,
        "event_type": event_type,
        "priority": priority,
        "timestamp": datetime.combine(event_date, event_time).isoformat(),
        "was_escalated": was_escalated,
        "authenticated": authenticated,
        "description": description,
        "address": address,
    }


def render_prediction(result: dict | None) -> None:
    if not result:
        st.info("Run a live event to generate closure risk, CIS, and M6 resource planning.")
        return

    prediction = result["prediction"]
    plan = result["resource_plan"]
    closure = prediction["closure_prediction"]
    cis = prediction["congestion_impact_score"]
    loc = prediction["resolved_location"]

    p1, p2, p3 = st.columns(3)
    p1.metric("Closure Probability", pct(closure.get("closure_probability")))
    p2.metric("CIS", fmt(cis.get("cis_ml_based"), 2))
    p3.metric("Final Tier", plan.get("final_tier", "--"))

    r1, r2, r3 = st.columns(3)
    r1.metric("Officers", plan.get("officer_count", "--"))
    r2.metric("Barricades", plan.get("barricade_count", "--"))
    r3.metric("Diversion", plan.get("diversion_priority", "--"))

    st.markdown("#### Location Resolution")
    st.dataframe(
        pd.DataFrame(
            [
                {"Signal": "Corridor", "Value": loc.get("corridor_final")},
                {"Signal": "Corridor confidence", "Value": fmt(loc.get("corridor_confidence"), 3)},
                {"Signal": "RF/KNN agreement", "Value": "yes" if loc.get("corridor_agreement") else "no"},
                {"Signal": "Police station", "Value": loc.get("police_station")},
                {"Signal": "Closure threshold", "Value": fmt(closure.get("decision_threshold"), 3)},
                {"Signal": "Text used", "Value": "yes" if closure.get("text_available") else "no"},
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(plan.get("rationale", ""))


def main() -> None:
    css()

    st.markdown(
        """
        <div class="m7-hero">
          <h1>M7 Traffic Operations Dashboard</h1>
          <p>Live M5 closure/CIS inference, M6 resource planning, corridor forecasts, and MapMyIndia operations map.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Runtime Setup")
        mappls_key = st.text_input(
            "MapMyIndia / Mappls Web SDK key",
            value=os.environ.get("M7_MAPPLS_SDK_KEY") or os.environ.get("MAPPLS_API_KEY") or "",
            type="password",
            help="The key is entered at runtime and is not saved into source code.",
        ).strip()
        st.caption(f"Pipeline: {m7.PIPELINE_DIR}")
        if st.button("Refresh overview cache", use_container_width=True):
            cached_overview.clear()
            st.rerun()

    try:
        overview = cached_overview()
    except Exception as exc:
        st.error(f"Could not load pipeline artifacts: {exc}")
        st.stop()

    causes = sorted({row.get("cause") for row in overview.get("top_causes", []) if row.get("cause")} | set(CAUSES))
    if "prediction_result" not in st.session_state:
        st.session_state.prediction_result = None

    s = overview.get("summary", {})
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        card("Historical Incidents", f"{int(s.get('incidents') or 0):,}", "Clean incident rows")
    with k2:
        card("Closure Rate", pct(s.get("closure_rate")), "Road closure share")
    with k3:
        card("Corridors", str(s.get("corridors") or "--"), "Resolved network coverage")
    with k4:
        card("Causes", str(s.get("causes") or "--"), "Incident categories")

    map_col, side_col = st.columns([1.55, 1], gap="large")
    with map_col:
        render_map(mappls_key, overview, st.session_state.prediction_result)

    with side_col:
        st.markdown("### Live Event")
        event = event_payload(causes)
        if event:
            with st.spinner("Running M5 inference and M6 resource rules..."):
                try:
                    st.session_state.prediction_result = m7.to_jsonable(m7.predict_live_event(event))
                    st.success("Prediction generated.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Prediction failed: {exc}")

    st.markdown("### Live Prediction")
    render_prediction(st.session_state.prediction_result)

    lower_left, lower_mid, lower_right = st.columns(3)
    with lower_left:
        st.markdown('<div class="m7-section"><h3>Forecast Hotspots</h3>', unsafe_allow_html=True)
        rank_list((overview.get("forecast_hotspots") or [])[:8], "corridor", "predicted_incidents", 1)
        st.markdown("</div>", unsafe_allow_html=True)
    with lower_mid:
        st.markdown('<div class="m7-section"><h3>Top Corridors</h3>', unsafe_allow_html=True)
        rank_list((overview.get("top_corridors") or [])[:8], "corridor", "count")
        st.markdown("</div>", unsafe_allow_html=True)
    with lower_right:
        st.markdown('<div class="m7-section"><h3>Top Causes</h3>', unsafe_allow_html=True)
        rank_list((overview.get("top_causes") or [])[:8], "cause", "count")
        st.markdown("</div>", unsafe_allow_html=True)

    metrics = overview.get("metrics", {})
    closure = metrics.get("closure", {})
    cis = metrics.get("cis", {})
    st.markdown("### Model Readout")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Closure ROC-AUC", fmt(closure.get("roc_auc"), 3))
    m2.metric("Precision / Recall", f"{fmt(closure.get('precision'), 3)} / {fmt(closure.get('recall'), 3)}")
    m3.metric("CIS MAE", fmt(cis.get("mae"), 3))
    m4.metric("CIS R2", fmt(cis.get("r2"), 3))


if __name__ == "__main__":
    main()
