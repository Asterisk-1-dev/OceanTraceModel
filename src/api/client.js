/**
 * API Configuration and Core HTTP Client
 * Handles all HTTP requests to the backend with automatic fallback to demo data
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const API_V1_PREFIX = "/api/v1";

/**
 * Generic HTTP client with error handling
 */
export async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    return await response.json();
  } catch (error) {
    console.error(`API Error (${endpoint}):`, error.message);
    throw error;
  }
}

/**
 * Health check - verify backend is available
 */
export async function checkHealth() {
  try {
    const response = await request("/health");
    return response.status === "ok";
  } catch {
    return false;
  }
}

/**
 * Safe wrapper for API calls with fallback
 * @param {Function} apiFn - Function that makes the API call
 * @param {Function} fallbackFn - Function that returns fallback data
 * @returns {Promise<any>} - API data or fallback data
 */
export async function withFallback(apiFn, fallbackFn) {
  try {
    return await apiFn();
  } catch (error) {
    console.warn("API call failed, using fallback:", error.message);
    return fallbackFn();
  }
}

/**
 * API namespace utilities
 */
export const api = {
  /**
   * Check if backend is available
   */
  isHealthy: checkHealth,

  /**
   * Incidents endpoints
   */
  incidents: {
    list: () => request(`${API_V1_PREFIX}/incidents`),
    get: (id) => request(`${API_V1_PREFIX}/incidents/${id}`),
    getSlick: (id) => request(`${API_V1_PREFIX}/incidents/${id}/slick`),
    getSlickMetrics: (id) =>
      request(`${API_V1_PREFIX}/incidents/${id}/slick/metrics`),
    getVessels: (id) => request(`${API_V1_PREFIX}/incidents/${id}/vessels`),
    getRecommendations: (id) =>
      request(`${API_V1_PREFIX}/incidents/${id}/recommendations`),
    getEvidence: (id) => request(`${API_V1_PREFIX}/incidents/${id}/evidence`),
  },

  /**
   * Vessels endpoints
   */
  vessels: {
    list: () => request(`${API_V1_PREFIX}/vessels`),
    get: (mmsi) => request(`${API_V1_PREFIX}/vessels/${mmsi}`),
  },

  /**
   * Traffic endpoints
   */
  traffic: {
    get: (stage = "Suspects") =>
      request(`${API_V1_PREFIX}/traffic?stage=${stage}`),
  },

  /**
   * Satellite endpoints
   */
  satellite: {
    listScenes: () => request(`${API_V1_PREFIX}/satellite/scenes`),
    getScene: (sceneId) =>
      request(`${API_V1_PREFIX}/satellite/scenes/${sceneId}`),
    processScene: (sceneId) =>
      request(`${API_V1_PREFIX}/satellite/process`, {
        method: "POST",
        body: JSON.stringify({ scene_id: sceneId }),
      }),
  },

  /**
   * Forecasts endpoints
   */
  forecasts: {
    get: (incidentId) =>
      request(`${API_V1_PREFIX}/incidents/${incidentId}/forecast`),
  },

  /**
   * Alerts endpoints
   */
  alerts: {
    list: () => request(`${API_V1_PREFIX}/alerts`),
    get: (id) => request(`${API_V1_PREFIX}/alerts/${id}`),
  },

  /**
   * Reports endpoints
   */
  reports: {
    list: () => request(`${API_V1_PREFIX}/reports`),
    get: (id) => request(`${API_V1_PREFIX}/reports/${id}`),
    getGeoJSON: (id) => request(`${API_V1_PREFIX}/reports/${id}/geojson`),
  },
};

/**
 * Export default
 */
export default api;
