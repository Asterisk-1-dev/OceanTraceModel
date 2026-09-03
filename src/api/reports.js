/**
 * Reports API - Fetches report data for export
 */
import { api, withFallback } from "./client";
import {
  incident as demoIncident,
  vessels as demoVessels,
  evidenceChain as demoEvidence,
} from "../demoData";

/**
 * Get a report by ID
 */
export async function getReport(reportId = "RPT-INC-240824-01") {
  return withFallback(
    () => api.reports.get(reportId).then(transformReport),
    () => getDemoReport(),
  );
}

/**
 * List all reports
 */
export async function listReports() {
  return withFallback(
    () => api.reports.list().then((reports) => reports.map(transformReport)),
    () => [getDemoReport()],
  );
}

/**
 * Get GeoJSON for a report
 */
export async function getReportGeoJSON(reportId = "RPT-INC-240824-01") {
  return withFallback(
    () => api.reports.getGeoJSON(reportId),
    () => ({
      type: "Feature",
      properties: {
        incident: demoIncident.id,
        area_km2: 12.8,
        confidence: 96.4,
      },
      geometry: {
        type: "Point",
        coordinates: demoIncident.decimal,
      },
    }),
  );
}

/**
 * Transform backend report format to frontend format
 */
function transformReport(backendReport) {
  return {
    id: backendReport.id,
    title: backendReport.title,
    status: backendReport.status,
    generatedAt: formatDateTime(backendReport.generated_at),
    incident: {
      id: backendReport.incident.id,
      scene: backendReport.incident.scene_id,
      coordinates: formatCoordinates(
        backendReport.incident.latitude,
        backendReport.incident.longitude,
      ),
      detected: formatDateTime(backendReport.incident.detected_at),
      severity: backendReport.incident.severity,
      score: backendReport.incident.impact_score,
      coast: backendReport.incident.impact_coast,
      slick: {
        area: `${backendReport.incident.slick.area_km2} km²`,
        confidence: backendReport.incident.slick.confidence,
        age: backendReport.incident.slick.age,
        volume: `${backendReport.incident.slick.estimated_volume_m3} m³`,
      },
      impact: {
        eta: `${backendReport.incident.impact_eta_hours} hours`,
        score: backendReport.incident.impact_score,
        severity: backendReport.incident.severity,
      },
    },
    vessels: backendReport.vessels.map((v, idx) => ({
      name: v.name,
      mmsi: v.mmsi,
      flag: v.flag,
      score: v.score,
      reasons: v.reasons,
      dark: v.dark_ship ? "Confirmed" : "No",
    })),
    recommendations: backendReport.recommendations || [],
    evidence: backendReport.evidence
      ? backendReport.evidence.chain.map((step) => [
          step.stage,
          "",
          step.current_hash.slice(-10),
        ])
      : [],
  };
}

/**
 * Get demo report
 */
function getDemoReport() {
  return {
    id: "RPT-INC-240824-01",
    title: "Oil spill intelligence brief",
    status: "READY FOR REVIEW",
    generatedAt: "24 AUG 2026 · 08:44:12 UTC",
    incident: {
      id: demoIncident.id,
      scene: demoIncident.scene,
      coordinates: demoIncident.coordinates,
      detected: demoIncident.detected,
      severity: demoIncident.impact.severity,
      score: demoIncident.impact.score,
      coast: demoIncident.impact.coast,
      slick: {
        area: demoIncident.slick.area,
        confidence: demoIncident.slick.confidence,
        age: demoIncident.slick.age,
        volume: demoIncident.slick.volume,
      },
      impact: {
        eta: demoIncident.impact.eta,
        score: demoIncident.impact.score,
        severity: demoIncident.impact.severity,
      },
    },
    vessels: demoVessels.map((v) => ({
      name: v.name,
      mmsi: v.mmsi,
      flag: v.flag,
      score: v.score,
      reasons: v.reasons,
      dark: v.dark,
    })),
    recommendations: [
      "Increase satellite revisit monitoring to every 6 hours",
      "Prioritize response asset nearest to the Lakshadweep marine zone",
      "Review SEA ORCHID voyage records and AIS gap evidence",
      "Recalculate impact zone after the next current-model update",
    ],
    evidence: demoEvidence,
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

export default {
  getReport,
  listReports,
  getReportGeoJSON,
};
