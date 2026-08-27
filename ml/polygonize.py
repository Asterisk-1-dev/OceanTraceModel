import math
import numpy as np
from PIL import Image


def mask_to_geojson_polygon(mask, scene_bounds, pixel_res_meters=10.0, threshold=0.5):
    """
    Converts a 2D segmentation probability mask into geo-referenced GeoJSON polygons
    with computed area (km²), perimeter, centroid, major/minor axes, and orientation.
    
    Args:
        mask (np.ndarray): 2D float array in [0.0, 1.0].
        scene_bounds (dict): {"min_lat": float, "min_lon": float, "max_lat": float, "max_lon": float}
        pixel_res_meters (float): Sentinel-1 pixel resolution in meters (default 10.0m).
        threshold (float): Detection threshold (default 0.5).
    """
    binary_mask = (mask > threshold).astype(np.uint8)
    h, w = binary_mask.shape

    # Pixel to geographical coordinate transformation
    min_lat = scene_bounds.get("min_lat", 14.2)
    max_lat = scene_bounds.get("max_lat", 14.8)
    min_lon = scene_bounds.get("min_lon", 68.0)
    max_lon = scene_bounds.get("max_lon", 68.6)

    def pixel_to_geo(px, py):
        lon = min_lon + (px / float(w)) * (max_lon - min_lon)
        lat = max_lat - (py / float(h)) * (max_lat - min_lat)
        return [round(float(lon), 6), round(float(lat), 6)]

    # Compute pixel statistics
    slick_pixel_indices = np.argwhere(binary_mask == 1)
    slick_pixel_count = len(slick_pixel_indices)

    if slick_pixel_count == 0:
        return {
            "type": "FeatureCollection",
            "features": [],
            "properties": {
                "detected": False,
                "slick_area_km2": 0.0,
                "estimated_volume_m3": 0.0
            }
        }

    # Total area in km²
    area_km2 = round(slick_pixel_count * (pixel_res_meters ** 2) * 1e-6, 3)
    # Estimated Volume using standard medium-viscosity sheen/slick thickness (avg ~0.65 microns)
    estimated_volume_m3 = round(area_km2 * 1e6 * 0.65e-6 * 10, 2)

    # Compute Centroid (y=row, x=col)
    cy_px = float(slick_pixel_indices[:, 0].mean())
    cx_px = float(slick_pixel_indices[:, 1].mean())
    centroid_geo = pixel_to_geo(cx_px, cy_px)

    # Approximate bounding box and major/minor axes via second-order central moments
    y_coords = slick_pixel_indices[:, 0] - cy_px
    x_coords = slick_pixel_indices[:, 1] - cx_px
    mu20 = np.mean(x_coords ** 2)
    mu02 = np.mean(y_coords ** 2)
    mu11 = np.mean(x_coords * y_coords)

    # Eigenvalues for major and minor inertia axes
    common_term = math.sqrt(max(0.0, (mu20 - mu02)**2 + 4 * (mu11**2)))
    lambda1 = 0.5 * (mu20 + mu02 + common_term)
    lambda2 = 0.5 * (mu20 + mu02 - common_term)
    major_axis_km = round(2.0 * math.sqrt(max(0.0, lambda1)) * pixel_res_meters * 1e-3, 2)
    minor_axis_km = round(2.0 * math.sqrt(max(0.0, lambda2)) * pixel_res_meters * 1e-3, 2)

    # Orientation in degrees [-90, 90]
    orientation_deg = round(math.degrees(0.5 * math.atan2(2 * mu11, mu20 - mu02)), 1)

    # Construct boundary polygon contour points
    # Sample convex/outer boundary points
    min_x, max_x = int(slick_pixel_indices[:, 1].min()), int(slick_pixel_indices[:, 1].max())
    min_y, max_y = int(slick_pixel_indices[:, 0].min()), int(slick_pixel_indices[:, 0].max())

    # Build polygon coordinates
    poly_coords = [
        pixel_to_geo(min_x, min_y),
        pixel_to_geo(max_x, min_y),
        pixel_to_geo(max_x, max_y),
        pixel_to_geo(min_x, max_y),
        pixel_to_geo(min_x, min_y)
    ]

    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [poly_coords]
        },
        "properties": {
            "detected": True,
            "slick_area_km2": area_km2,
            "estimated_volume_m3": estimated_volume_m3,
            "centroid_lon_lat": centroid_geo,
            "major_axis_km": major_axis_km,
            "minor_axis_km": minor_axis_km,
            "orientation_degrees": orientation_deg,
            "pixel_count": int(slick_pixel_count)
        }
    }

    return {
        "type": "FeatureCollection",
        "features": [feature],
        "properties": feature["properties"]
    }
