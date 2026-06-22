const state = {
  config: null,
  overview: null,
  map: null,
  provider: null,
  layers: [],
  liveLayers: [],
};

const $ = (id) => document.getElementById(id);

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits);
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

function setPredictionEnabled(enabled) {
  const button = $("predictButton");
  button.disabled = !enabled;
}

async function waitForMappls() {
  const deadline = Date.now() + 12000;
  while (Date.now() < deadline) {
    if (window.mappls?.Map && window.mappls?.Marker && window.mappls?.Polyline) {
      return window.mappls;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Mappls SDK loaded, but map classes were not available");
}

async function initMappls() {
  const key = state.config?.mappls_sdk_key;
  if (!key) throw new Error("M7_MAPPLS_SDK_KEY is required");

  await new Promise((resolve, reject) => {
    window.__m7MapplsReady = resolve;
    const script = document.createElement("script");
    script.src = `https://apis.mappls.com/advancedmaps/api/${encodeURIComponent(key)}/map_sdk?layer=vector&v=3.0&callback=__m7MapplsReady`;
    script.async = true;
    script.onerror = reject;
    document.head.appendChild(script);
    setTimeout(() => reject(new Error("Mappls SDK timed out")), 9000);
  });

  const mapplsApi = await waitForMappls();
  state.provider = "mappls";
  state.map = new mapplsApi.Map("map", {
    center: [12.9716, 77.5946],
    zoom: 11,
    zoomControl: true,
    location: true,
  });
  $("mapProvider").textContent = "Mappls SDK";
  $("mapStatus").textContent = "MapMyIndia/Mappls SDK active.";
}

async function initMap() {
  await initMappls();
}

function clearLayers(group = "layers") {
  const layers = state[group];
  while (layers.length) {
    const layer = layers.pop();
    try {
      if (layer?.remove) {
        layer.remove();
      } else if (layer?.setMap) {
        layer.setMap(null);
      }
    } catch (err) {
      console.warn("Layer cleanup failed", err);
    }
  }
}

function addMapplsMarker(lat, lng, html, group = "liveLayers") {
  const mapplsApi = window.mappls;
  if (!mapplsApi?.Marker) throw new Error("Mappls SDK is not ready");
  const marker = new mapplsApi.Marker({
    map: state.map,
    position: { lat, lng },
    popupHtml: html || "",
  });
  state[group].push(marker);
  return marker;
}

function addMapplsPolyline(points, options, html, group = "layers") {
  const mapplsApi = window.mappls;
  if (!mapplsApi?.Polyline) throw new Error("Mappls SDK is not ready");
  const polyline = new mapplsApi.Polyline({
    map: state.map,
    path: points.map(([lat, lng]) => ({ lat, lng })),
    strokeColor: options.color || "#2563eb",
    strokeOpacity: options.opacity ?? 0.85,
    strokeWeight: options.weight || 4,
    popupHtml: html || "",
  });
  state[group].push(polyline);
  return polyline;
}

function addCircle(lat, lng, options, html, group = "layers") {
  return addMapplsMarker(lat, lng, html, group);
}

function addPolyline(points, options, html, group = "layers") {
  return addMapplsPolyline(points, options, html, group);
}

function addMarker(lat, lng, html, className, group = "liveLayers") {
  return addMapplsMarker(lat, lng, html, group);
}

function fitTo(points) {
  if (!points.length || !state.map) return;
  const lats = points.map((p) => Number(p[0])).filter(Number.isFinite);
  const lngs = points.map((p) => Number(p[1])).filter(Number.isFinite);
  if (!lats.length || !lngs.length) return;
  const center = [
    (Math.min(...lats) + Math.max(...lats)) / 2,
    (Math.min(...lngs) + Math.max(...lngs)) / 2,
  ];
  if (state.map.setCenter) state.map.setCenter(center);
}

function renderOverviewPanels(data) {
  $("pipelinePath").textContent = data.pipeline_dir;
  $("incidentCount").textContent = data.summary.incidents.toLocaleString();
  $("closureRate").textContent = pct(data.summary.closure_rate);
  $("corridorCount").textContent = data.summary.corridors ?? "--";

  const closure = data.metrics.closure || {};
  const cis = data.metrics.cis || {};
  $("modelReadout").innerHTML = [
    ["Closure ROC-AUC", fmt(closure.roc_auc, 3)],
    ["Precision / Recall", `${fmt(closure.precision, 3)} / ${fmt(closure.recall, 3)}`],
    ["Closure threshold", fmt(closure.threshold, 3)],
    ["CIS MAE", fmt(cis.mae, 3)],
    ["CIS R2", fmt(cis.r2, 3)],
  ].map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("");

  $("forecastList").innerHTML = data.forecast_hotspots.slice(0, 8).map((row) => (
    `<div><span>${escapeHtml(row.corridor)}</span><b>${fmt(row.predicted_incidents, 1)}</b></div>`
  )).join("");

  $("corridorList").innerHTML = data.top_corridors.slice(0, 8).map((row) => (
    `<div><span>${escapeHtml(row.corridor)}</span><b>${Number(row.count).toLocaleString()}</b></div>`
  )).join("");

  $("causeList").innerHTML = data.top_causes.slice(0, 8).map((row) => (
    `<div><span>${escapeHtml(row.cause)}</span><b>${Number(row.count).toLocaleString()}</b></div>`
  )).join("");

  const causeSelect = $("causeSelect");
  const existing = new Set([...causeSelect.options].map((o) => o.value));
  data.top_causes.forEach((row) => {
    if (!existing.has(row.cause)) {
      const option = document.createElement("option");
      option.value = row.cause;
      option.textContent = row.cause;
      causeSelect.appendChild(option);
    }
  });
}

function drawOverviewMap(data) {
  clearLayers("layers");
  const points = [];

  data.corridor_segments.forEach((seg) => {
    const forecast = Number(seg.forecast || 0);
    const color = forecast >= 60 ? "#dc2626" : forecast >= 25 ? "#f97316" : "#2563eb";
    addPolyline([seg.origin, seg.destination], { color, weight: 3, opacity: 0.58 }, `
      <b>${escapeHtml(seg.corridor)}</b><br>
      Forecast: ${fmt(forecast, 1)} incidents<br>
      Confidence: ${escapeHtml(seg.confidence)}
    `);
    points.push(seg.origin, seg.destination);
  });

  data.heat_points.forEach((p) => {
    if (!p.lat || !p.lng) return;
    const high = Number(p.cis || 0) >= 7;
    const closure = Boolean(p.closure);
    const color = closure ? "#dc2626" : high ? "#f97316" : "#0f766e";
    addCircle(p.lat, p.lng, {
      radius: closure ? 5 : high ? 4 : 3,
      color,
      fillColor: color,
      fillOpacity: closure ? 0.36 : 0.20,
      weight: 0.8,
    }, `
      <b>${escapeHtml(p.cause)}</b><br>
      Corridor: ${escapeHtml(p.corridor || "Unknown")}<br>
      CIS: ${fmt(p.cis, 2)}<br>
      Closure: ${p.closure ? "Yes" : "No"}
    `);
  });

  data.forecast_hotspots.slice(0, 8).forEach((hotspot) => {
    const seg = data.corridor_segments.find((s) => s.corridor === hotspot.corridor);
    if (!seg) return;
    const lat = (seg.origin[0] + seg.destination[0]) / 2;
    const lng = (seg.origin[1] + seg.destination[1]) / 2;
    addCircle(lat, lng, {
      radius: Math.min(18, 7 + Number(hotspot.predicted_incidents || 0) / 12),
      color: "#7c3aed",
      fillColor: "#7c3aed",
      fillOpacity: 0.28,
      weight: 2,
    }, `
      <b>${escapeHtml(hotspot.corridor)}</b><br>
      Next forecast: ${fmt(hotspot.predicted_incidents, 1)} incidents<br>
      Historical avg: ${fmt(hotspot.avg_weekly_incidents_historical, 1)}
    `);
  });

  fitTo(points);
}

function eventFromForm() {
  const form = $("eventForm");
  const data = new FormData(form);
  const localTs = data.get("timestamp");
  return {
    latitude: Number(data.get("latitude")),
    longitude: Number(data.get("longitude")),
    event_cause: data.get("event_cause"),
    event_type: data.get("event_type"),
    priority: data.get("priority"),
    timestamp: localTs ? new Date(localTs).toISOString() : new Date().toISOString(),
    was_escalated: data.get("was_escalated") === "on",
    authenticated: data.get("authenticated") === "on",
    description: data.get("description") || "",
    address: data.get("address") || "",
  };
}

function renderPrediction(result) {
  const prediction = result.prediction;
  const plan = result.resource_plan;
  const closure = prediction.closure_prediction;
  const cis = prediction.congestion_impact_score;
  const loc = prediction.resolved_location;

  $("closureProbability").textContent = pct(closure.closure_probability);
  $("cisScore").textContent = fmt(cis.cis_ml_based, 2);
  $("finalTier").textContent = plan.final_tier;
  $("officerCount").textContent = plan.officer_count;
  $("barricadeCount").textContent = plan.barricade_count;
  $("diversionPriority").textContent = plan.diversion_priority;
  $("resourceRationale").textContent = plan.rationale;

  $("liveDetails").innerHTML = [
    ["Corridor", loc.corridor_final],
    ["Corridor confidence", fmt(loc.corridor_confidence, 3)],
    ["RF/KNN agreement", loc.corridor_agreement ? "yes" : "no"],
    ["Police station", loc.police_station],
    ["Closure threshold", fmt(closure.decision_threshold, 3)],
    ["Text used", closure.text_available ? "yes" : "no"],
  ].map(([k, v]) => `<div><span>${k}</span><b>${escapeHtml(v)}</b></div>`).join("");
}

function drawPrediction(result) {
  clearLayers("liveLayers");
  const input = result.prediction.input;
  const loc = result.prediction.resolved_location;
  const plan = result.resource_plan;
  const lat = Number(input.latitude);
  const lng = Number(input.longitude);
  const points = [[lat, lng]];

  addMarker(lat, lng, `
    <b>Live event</b><br>
    ${escapeHtml(input.event_cause)}<br>
    Closure: ${result.prediction.closure_prediction.requires_road_closure_predicted ? "Yes" : "No"}<br>
    Tier: ${escapeHtml(plan.final_tier)}
  `, "marker-live");

  const routeColors = ["#2563eb", "#0f766e", "#9333ea"];
  try {
    result.diversion_routes.forEach((route, index) => {
    addPolyline(route.polyline, {
      color: routeColors[index % routeColors.length],
      weight: index === 0 ? 6 : 4,
      opacity: 0.9,
      dashArray: index === 0 ? null : "8 7",
    }, `
      <b>Diversion ${index + 1}: ${escapeHtml(route.name)}</b><br>
      Source: ${escapeHtml(route.source)}<br>
      Forecast incidents: ${fmt(route.forecast_incidents, 1)}
    `, "liveLayers");
    route.polyline.forEach((p) => points.push(p));
    });
  } catch (err) {
    console.warn("Route overlay failed", err);
  }

  result.resource_pins.forEach((pin) => {
    addMarker(pin.lat, pin.lng, `<b>${escapeHtml(pin.label)}</b>`, `marker-resource ${pin.type}`, "liveLayers");
    points.push([pin.lat, pin.lng]);
  });

  addCircle(lat, lng, {
    radius: loc.corridor_source === "predicted" ? 10 : 12,
    color: loc.corridor_source === "predicted" ? "#0f766e" : "#b45309",
    fillColor: loc.corridor_source === "predicted" ? "#0f766e" : "#f97316",
    fillOpacity: 0.12,
    weight: 2,
  }, `Resolved corridor: ${escapeHtml(loc.corridor_final)}`, "liveLayers");

  fitTo(points);
}

async function runPrediction() {
  const button = $("predictButton");
  if (!state.map || !window.mappls) {
    $("mapStatus").textContent = "Mappls is still loading. Try again after the map is ready.";
    return;
  }
  button.disabled = true;
  button.textContent = "Running...";
  $("mapStatus").textContent = "Running M5 inference and M6 resource rules...";
  try {
    const result = await api("/api/predict", {
      method: "POST",
      body: JSON.stringify(eventFromForm()),
    });
    renderPrediction(result);
    drawPrediction(result);
    $("mapStatus").textContent = "Live prediction rendered.";
  } catch (err) {
    console.error(err);
    $("mapStatus").textContent = `Prediction failed: ${err.message}`;
  } finally {
    button.disabled = false;
    button.textContent = "Run M5 + M6";
  }
}

function setDefaultTime() {
  const input = document.querySelector('input[name="timestamp"]');
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  input.value = now.toISOString().slice(0, 16);
}

function installHandlers() {
  $("eventForm").addEventListener("submit", (event) => {
    event.preventDefault();
    runPrediction();
  });

  $("sampleHigh").addEventListener("click", () => {
    const form = $("eventForm");
    form.latitude.value = "13.0050";
    form.longitude.value = "77.5700";
    form.event_cause.value = "vip_movement";
    form.event_type.value = "planned";
    form.priority.value = "HIGH";
    form.description.value = "traffic diverted and road closed for convoy movement";
    form.address.value = "Bellary Road, Bengaluru";
    form.was_escalated.checked = true;
  });
}

async function main() {
  setPredictionEnabled(false);
  setDefaultTime();
  installHandlers();
  state.config = await api("/api/config");
  state.overview = await api("/api/overview");
  await initMap();
  renderOverviewPanels(state.overview);
  drawOverviewMap(state.overview);
  $("mapStatus").textContent = "Historical heat, corridors, and forecast hotspots loaded.";
  setPredictionEnabled(true);
}

main().catch((err) => {
  console.error(err);
  $("mapStatus").textContent = `Dashboard failed to start: ${err.message}`;
  setPredictionEnabled(false);
});
