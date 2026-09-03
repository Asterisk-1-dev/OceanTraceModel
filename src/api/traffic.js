/**
 * Traffic API - Fetches traffic filtering data
 */
import { api, withFallback } from "./client";
import { trafficStages as demoTrafficStages } from "../demoData";

/**
 * Get traffic data for a specific stage
 */
export async function getTraffic(stage = "Suspects") {
  return withFallback(
    () => api.traffic.get(stage).then(transformTrafficResponse),
    () => transformTrafficResponse(getDemoTrafficResponse(stage)),
  );
}

/**
 * Get all available traffic stages
 */
export async function getTrafficStages() {
  return withFallback(
    async () => {
      const response = await api.traffic.get("All Traffic");
      return response.available_stages.map((stage) => ({
        label: stage.label,
        count: stage.count,
      }));
    },
    () => demoTrafficStages,
  );
}

/**
 * Transform backend traffic response to frontend format
 */
function transformTrafficResponse(backendResponse) {
  return {
    stage: backendResponse.stage || "Suspects",
    count: backendResponse.count,
    availableStages: (backendResponse.available_stages || []).map((stage) => ({
      label: stage.label,
      count: stage.count,
    })),
  };
}

/**
 * Get demo traffic response for a stage
 */
function getDemoTrafficResponse(stage) {
  const foundStage = demoTrafficStages.find((s) => s.label === stage);
  if (!foundStage) {
    return {
      stage: "Suspects",
      count: 3,
      available_stages: demoTrafficStages,
    };
  }

  return {
    stage: foundStage.label,
    count: foundStage.count,
    available_stages: demoTrafficStages,
  };
}

export default {
  getTraffic,
  getTrafficStages,
};
