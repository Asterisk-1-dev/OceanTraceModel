/**
 * Incidents API - Fetches incident data with fallback to demo data
 */
import { api, withFallback } from "./client";
import { incident as demoIncident, vessels as demoVessels } from "../demoData";

function sanitizeString(str) {
  if (!str) return str;
  return str.replace(/Â·/g, '·').replace(/\uFFFD/g, '·');
}

/**
 * Transform backend incident format to frontend format
 */
function transformIncident(backendIncident) {
  return {
    id: backendIncident.id,
    scene: backendIncident.scene_id,
    coordinates: formatCoordinates(
      backendIncident.latitude,
      backendIncident.longitude,
    ),
    decimal: [backendIncident.longitude, backendIncident.latitude],
    detected: formatDateTime(backendIncident.detected_at),
    source: sanitizeString(backendIncident.source),
    slick: {
      age: backendIncident.slick.age,
      area: `${backendIncident.slick.area_km2} km²`,
      perimeter: `${backendIncident.slick.perimeter_km} km`,
      length: `${backendIncident.slick.length_km} km`,
      width: `${backendIncident.slick.width_km} km`,
      aspect: String(backendIncident.slick.aspect_ratio),
      volume: `${backendIncident.slick.estimated_volume_m3} m³`,
      confidence: backendIncident.slick.confidence,
      geometry: backendIncident.slick.geometry,
    },
    impact: {
      severity: backendIncident.severity,
      score: backendIncident.impact_score,
      coast: backendIncident.impact_coast,
      eta: `${backendIncident.impact_eta_hours} hours`,
    },
    forecast: backendIncident.forecast_summary,
  };
}

/**
 * Format coordinates from lat/lon to human-readable string
 */
function formatCoordinates(lat, lon) {
  const latStr = `${Math.abs(lat).toFixed(0)}° ${((Math.abs(lat) % 1) * 60).toFixed(0)}' ${lat >= 0 ? "N" : "S"}`;
  const lonStr = `${Math.abs(lon).toFixed(0)}° ${((Math.abs(lon) % 1) * 60).toFixed(0)}' ${lon >= 0 ? "E" : "W"}`;
  return `${latStr}, ${lonStr}`;
}

/**
 * Format ISO datetime string
 */
function formatDateTime(isoString) {
  const date = new Date(isoString);
  const monthNames = [
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
  ];
  const day = date.getUTCDate();
  const month = monthNames[date.getUTCMonth()];
  const year = date.getUTCFullYear();
  const time = date.toISOString().split("T")[1].split(".")[0];
  return `${day} ${month} ${year} · ${time} UTC`;
}

/**
 * Get primary incident with fallback to demo data
 */
export async function getIncident(incidentId = "INC-240824-01") {
  return withFallback(
    () => api.incidents.get(incidentId).then(transformIncident),
    () => demoIncident,
  );
}

/**
 * List all incidents
 */
export async function listIncidents() {
  return withFallback(
    () =>
      api.incidents
        .list()
        .then((incidents) => incidents.map(transformIncident)),
    () => [demoIncident],
  );
}

/**
 * Get vessels for an incident
 */
export async function getIncidentVessels(incidentId = "INC-240824-01") {
  return withFallback(
    () =>
      api.incidents
        .getVessels(incidentId)
        .then((vessels) => vessels.map(transformVessel)),
    () => demoVessels,
  );
}

/**
 * Transform backend vessel format to frontend format
 */
function transformVessel(backendVessel) {
  const scoreValue = backendVessel.score;
  let color = "yellow";
  if (scoreValue >= 85) color = "red";
  else if (scoreValue >= 70) color = "amber";

  return {
    name: backendVessel.name,
    mmsi: backendVessel.mmsi,
    flag: backendVessel.flag,
    score: scoreValue,
    color,
    origin: backendVessel.origin,
    destination: backendVessel.destination,
    dark: backendVessel.dark_ship ? "Confirmed" : "No",
    reasons: backendVessel.reasons,
    breakdown: backendVessel.breakdown,
  };
}

/**
 * Get recommendations for an incident
 */
export async function getRecommendations(incidentId = "INC-240824-01") {
  return withFallback(
    () =>
      api.incidents.getRecommendations(incidentId).then((r) => r.items || []),
    () => [
      "Increase satellite revisit monitoring to every 6 hours",
      "Prioritize response asset nearest to the Lakshadweep marine zone",
      "Review SEA ORCHID voyage records and AIS gap evidence",
      "Recalculate impact zone after the next current-model update",
    ],
  );
}

/**
 * Get evidence chain for an incident
 */
export async function getEvidence(incidentId = "INC-240824-01") {
  return withFallback(
    () =>
      api.incidents
        .getEvidence(incidentId)
        .then((evidence) =>
          evidence.chain.map((step) => [
            step.stage,
            "",
            step.current_hash.slice(-10),
          ]),
        ),
    () => [
      ["Raw Scene", "08:41:02", "a18f...93c2"],
      ["Processing", "08:41:18", "c30a...118e"],
      ["Detection", "08:42:04", "f2d1...7a06"],
      ["Vessel Correlation", "08:42:22", "8b91...d113"],
      ["Forecast", "08:43:01", "4e70...29bc"],
      ["Attribution", "08:43:18", "e6af...c801"],
      ["Report", "08:44:12", "91cd...4b7e"],
    ],
  );
}

export default {
  getIncident,
  listIncidents,
  getIncidentVessels,
  transformVessel,
  getRecommendations,
  getEvidence,
};
