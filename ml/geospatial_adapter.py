"""
OceanTrace — Geospatial Output Adapter
Bridges Model 1 segmentation output with geospatial reference frames and constructs canonical SpillDetection objects.

Preserves:
- Affine transform / bounding box mapping
- Raster dimensions and spatial resolution
- Source scene identifier
- UTC detection timestamp
- Area (km²), perimeter, orientation, and moment-based centroid calculation
- GeoJSON geometry formatting and strict SpillDetection validation
"""

import math
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List
import numpy as np

from ml.drift_types import SpillDetection, parse_utc_iso


class GeospatialAdapter:
    """
    Converts 2D segmentation probability masks from Sentinel-1 SAR scenes
    into geo-referenced GeoJSON polygons and canonical SpillDetection instances.
    """

    def __init__(
        self,
        default_pixel_res_meters: float = 10.0,
        detection_threshold: float = 0.28
    ):
        self.pixel_res_meters = default_pixel_res_meters
        self.threshold = detection_threshold

    def mask_to_spill_detection(
        self,
        prob_mask: np.ndarray,
        scene_bounds: Dict[str, float],
        source_scene_id: str,
        detection_timestamp: str,
        threshold: Optional[float] = None,
        detection_id: Optional[str] = None,
        scene_classification: str = "Oil Spill",
        confidence: Optional[float] = None
    ) -> Optional[SpillDetection]:
        """
        Extracts geographic slick geometry from a 2D probability mask and constructs
        a canonical SpillDetection.

        Args:
            prob_mask: 2D numpy array [H, W] with probabilities in [0.0, 1.0].
            scene_bounds: Dict with keys 'min_lat', 'max_lat', 'min_lon', 'max_lon'.
            source_scene_id: Sentinel-1 scene identifier.
            detection_timestamp: ISO8601 UTC timestamp string.
            threshold: Optional custom threshold (default 0.28).
            detection_id: Optional unique identifier.
            scene_classification: "Oil Spill", "Lookalike", or "Clean Sea".
            confidence: Optional explicit confidence score in [0.0, 1.0].

        Returns:
            SpillDetection if oil slick detected above threshold; None if no oil detected.
        """
        # Validate inputs
        if prob_mask.ndim != 2:
            raise ValueError(f"prob_mask must be 2D [H, W], got shape {prob_mask.shape}")
        
        req_keys = ["min_lat", "max_lat", "min_lon", "max_lon"]
        for k in req_keys:
            if k not in scene_bounds:
                raise ValueError(f"Missing required scene_bound key '{k}'. Required: {req_keys}")

        min_lat = float(scene_bounds["min_lat"])
        max_lat = float(scene_bounds["max_lat"])
        min_lon = float(scene_bounds["min_lon"])
        max_lon = float(scene_bounds["max_lon"])

        if min_lat >= max_lat or min_lon >= max_lon:
            raise ValueError(f"Invalid scene bounds: lat [{min_lat}, {max_lat}], lon [{min_lon}, {max_lon}]")

        thresh = self.threshold if threshold is None else threshold
        binary_mask = (prob_mask > thresh).astype(np.uint8)
        h, w = binary_mask.shape

        slick_indices = np.argwhere(binary_mask == 1)
        slick_count = len(slick_indices)

        if slick_count == 0:
            return None

        # Coordinate transformation helper (WGS84)
        def pixel_to_geo(px: float, py: float) -> List[float]:
            lon = min_lon + (px / float(w)) * (max_lon - min_lon)
            lat = max_lat - (py / float(h)) * (max_lat - min_lat)
            return [round(float(lon), 6), round(float(lat), 6)]

        # Area in km²
        area_km2 = round(slick_count * (self.pixel_res_meters ** 2) * 1e-6, 4)
        if area_km2 < 0.001:
            area_km2 = 0.001

        # Estimated Volume (m³) using standard sheen/slick thickness ~0.65 microns
        estimated_volume_m3 = round(area_km2 * 1e6 * 0.65e-6 * 10.0, 2)

        # Centroid calculation (y = row, x = col)
        cy_px = float(slick_indices[:, 0].mean())
        cx_px = float(slick_indices[:, 1].mean())
        centroid_lon_lat = pixel_to_geo(cx_px, cy_px)
        c_lon, c_lat = centroid_lon_lat[0], centroid_lon_lat[1]

        # Second-order central moments for orientation & major/minor axes
        y_coords = slick_indices[:, 0] - cy_px
        x_coords = slick_indices[:, 1] - cx_px
        mu20 = np.mean(x_coords ** 2)
        mu02 = np.mean(y_coords ** 2)
        mu11 = np.mean(x_coords * y_coords)

        common_term = math.sqrt(max(0.0, (mu20 - mu02) ** 2 + 4.0 * (mu11 ** 2)))
        lambda1 = 0.5 * (mu20 + mu02 + common_term)
        lambda2 = 0.5 * (mu20 + mu02 - common_term)

        major_axis_km = round(2.0 * math.sqrt(max(0.0, lambda1)) * self.pixel_res_meters * 1e-3, 3)
        minor_axis_km = round(2.0 * math.sqrt(max(0.0, lambda2)) * self.pixel_res_meters * 1e-3, 3)
        orientation_deg = round(math.degrees(0.5 * math.atan2(2.0 * mu11, mu20 - mu02)), 1)

        # Convex/Bounding polygon coordinates in GeoJSON WGS84 format: [[lon, lat], ...]
        min_x, max_x = int(slick_indices[:, 1].min()), int(slick_indices[:, 1].max())
        min_y, max_y = int(slick_indices[:, 0].min()), int(slick_indices[:, 0].max())

        poly_ring = [
            pixel_to_geo(min_x, min_y),
            pixel_to_geo(max_x, min_y),
            pixel_to_geo(max_x, max_y),
            pixel_to_geo(min_x, max_y),
            pixel_to_geo(min_x, min_y)
        ]

        polygon_geojson = {
            "type": "Polygon",
            "coordinates": [poly_ring]
        }

        # Determine detection confidence
        if confidence is None:
            # Derived from peak and mean probability inside mask
            slick_probs = prob_mask[binary_mask == 1]
            calculated_confidence = float(np.clip(float(np.mean(slick_probs)), 0.0, 1.0))
        else:
            calculated_confidence = float(np.clip(confidence, 0.0, 1.0))

        det_id = detection_id or f"det_{source_scene_id}_{int(datetime.now(timezone.utc).timestamp())}"

        detection = SpillDetection(
            detection_id=det_id,
            source_scene_id=source_scene_id,
            detection_timestamp=detection_timestamp,
            centroid_lat=c_lat,
            centroid_lon=c_lon,
            area_km2=area_km2,
            confidence=calculated_confidence,
            scene_classification=scene_classification,
            polygon_geojson=polygon_geojson,
            estimated_volume_m3=estimated_volume_m3,
            metadata={
                "pixel_count": int(slick_count),
                "threshold_used": thresh,
                "major_axis_km": major_axis_km,
                "minor_axis_km": minor_axis_km,
                "orientation_deg": orientation_deg,
                "pixel_res_meters": self.pixel_res_meters,
                "scene_bounds": scene_bounds
            }
        )
        return detection
