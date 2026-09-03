export const demoMode = true;

export const incident = {
  id: "INC-240824-01",
  scene: "S1A_20260824_0417",
  coordinates: "14° 32' N, 68° 18' E",
  decimal: [68.3, 14.5333],
  detected: "24 AUG 2026 · 08:42 UTC",
  source: "Sentinel-1 GRD · Demo scene",
  slick: {
    age: "06h 18m",
    area: "12.8 km²",
    perimeter: "18.6 km",
    length: "6.4 km",
    width: "2.1 km",
    aspect: "3.05",
    volume: "8.4 m³",
    confidence: 96.4,
    geometry: "Irregular elongated polygon",
  },
  environment: {
    wind: "18 kn WSW · 247°",
    current: "1.4 kn ENE · 065°",
    waves: "1.8 m · Moderate sea",
  },
  impact: {
    severity: "Warning",
    score: 78,
    coast: "Lakshadweep marine zone",
    distance: "42 km",
    eta: "36 hours",
    confidence: "81%",
  },
  forecast: "Drift vector trending ENE. Coastal impact probability: moderate.",
};

export const vessels = [
  {
    name: "SEA ORCHID",
    mmsi: "477981200",
    flag: "SG",
    score: 92,
    color: "red",
    origin: "Singapore",
    destination: "Mumbai, IN",
    dark: "Confirmed",
    reasons: [
      "18 min AIS dark period",
      "0.8 nm from slick origin",
      "Heading aligns 87% with drift",
    ],
    breakdown: { proximity: 96, trajectory: 91, behavior: 88, aisGap: 94 },
  },
  {
    name: "PACIFIC MERIDIAN",
    mmsi: "636019874",
    flag: "LR",
    score: 76,
    color: "amber",
    origin: "Fujairah, AE",
    destination: "Unknown",
    dark: "No",
    reasons: [
      "Course deviation at 04:10 UTC",
      "2.4 nm from spill envelope",
      "Speed drop below 4 knots",
    ],
    breakdown: { proximity: 74, trajectory: 79, behavior: 81, aisGap: 62 },
  },
  {
    name: "NORDIC STAR",
    mmsi: "311000452",
    flag: "BS",
    score: 54,
    color: "yellow",
    origin: "Unknown",
    destination: "Colombo, LK",
    dark: "No",
    reasons: ["3.2 nm from slick", "Trajectory partially aligned"],
    breakdown: { proximity: 48, trajectory: 64, behavior: 51, aisGap: 42 },
  },
];

export const trafficStages = [
  { label: "All Traffic", count: 184 },
  { label: "Region", count: 63 },
  { label: "Spill Envelope", count: 17 },
  { label: "Temporal", count: 11 },
  { label: "Behavioral", count: 6 },
  { label: "Suspects", count: 3 },
];

export const evidenceChain = [
  ["Raw Scene", "08:41:02", "a18f...93c2"],
  ["Processing", "08:41:18", "c30a...118e"],
  ["Detection", "08:42:04", "f2d1...7a06"],
  ["Vessel Correlation", "08:42:22", "8b91...d113"],
  ["Forecast", "08:43:01", "4e70...29bc"],
  ["Attribution", "08:43:18", "e6af...c801"],
  ["Report", "08:44:12", "91cd...4b7e"],
];

export const recommendations = [
  "Increase satellite revisit monitoring to every 6 hours",
  "Prioritize response asset nearest to the Lakshadweep marine zone",
  "Review SEA ORCHID voyage records and AIS gap evidence",
  "Recalculate impact zone after the next current-model update",
];
