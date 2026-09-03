"""
OceanTrace Model 2 — Lagrangian Drift Engine & Physics Advection
Implements polygon-aware particle seeding, vectorized 2nd-order Runge-Kutta (RK2 Midpoint) advection,
Coriolis deflection, turbulent diffusion, and 95% uncertainty covariance ellipse estimation.
"""

import math
import random
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone, timedelta
import numpy as np

from ml.drift_types import (
    SpillDetection,
    ParticleState,
    SearchEllipse,
    TrajectoryStep,
    TrajectoryPackage,
    parse_utc_iso
)
from ml.environmental_provider import EnvironmentalProvider


# Earth Radius in meters (WGS84 spherical approximation)
EARTH_RADIUS_M = 6371000.0


def meters_to_lat_deg(delta_y_m: float) -> float:
    """Converts a north-south displacement in meters to latitude degrees."""
    return (delta_y_m / EARTH_RADIUS_M) * (180.0 / math.pi)


def meters_to_lon_deg(delta_x_m: float, lat_deg: float) -> float:
    """Converts an east-west displacement in meters to longitude degrees at a given latitude."""
    lat_rad = math.radians(lat_deg)
    cos_lat = max(1e-6, math.cos(lat_rad))
    return (delta_x_m / (EARTH_RADIUS_M * cos_lat)) * (180.0 / math.pi)


def lat_lon_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two geographic coordinates using the Haversine formula."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians((lon2 - lon1 + 180.0) % 360.0 - 180.0)

    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return (EARTH_RADIUS_M * c) * 1e-3


def compute_coriolis_deflection(lat_deg: float) -> float:
    """
    Computes the standard empirical surface wind deflection angle (Ekman layer deflection).
    Northern Hemisphere (>5°N): +10° to the right.
    Southern Hemisphere (<-5°S): -10° to the left.
    Equatorial Band ([-5°N, 5°S]): Linearly attenuated toward 0°.
    """
    if lat_deg > 5.0:
        return math.radians(10.0)
    elif lat_deg < -5.0:
        return math.radians(-10.0)
    else:
        return math.radians(2.0 * lat_deg)


def rotate_vector_2d(u: float, v: float, angle_rad: float) -> Tuple[float, float]:
    """Rotates a 2D Cartesian velocity vector by angle_rad counter-clockwise."""
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    u_rot = u * cos_a - v * sin_a
    v_rot = u * sin_a + v * cos_a
    return u_rot, v_rot


def point_in_polygon(px: float, py: float, poly_coords: List[List[float]]) -> bool:
    """Ray-casting algorithm to test if a point (lon, lat) is strictly inside a polygon ring."""
    n = len(poly_coords)
    inside = False
    p1x, p1y = poly_coords[0]
    for i in range(n + 1):
        p2x, p2y = poly_coords[i % n]
        if py > min(p1y, p2y):
            if py <= max(p1y, p2y):
                if px <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (py - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or px <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


class DriftEngine:
    """
    Core Lagrangian Particle Tracking & Advection Engine.
    Configurable physical constants, numerical integrator, and deterministic seeding.
    """

    def __init__(
        self,
        env_provider: EnvironmentalProvider,
        default_particle_count: int = 250,
        base_windage_factor: float = 0.030,
        windage_std: float = 0.003,
        horizontal_diffusion_m2s: float = 5.0,
        timestep_seconds: float = 900.0,  # 15 minutes
        seed: Optional[int] = 42
    ):
        self.env = env_provider
        self.num_particles = default_particle_count
        self.base_windage = base_windage_factor
        self.windage_std = windage_std
        self.Kh = horizontal_diffusion_m2s
        self.dt = timestep_seconds
        self.seed = seed

    def seed_particles(self, detection: SpillDetection) -> List[ParticleState]:
        """
        Initializes N Lagrangian particles sampled from the detected spill geometry.
        If polygon GeoJSON is available, performs rejection sampling inside the boundary;
        otherwise generates a Gaussian cluster around the centroid proportional to area.
        """
        if self.seed is not None:
            random.seed(self.seed)
            np.random.seed(self.seed)

        particles = []
        poly_geojson = detection.polygon_geojson

        polygon_ring = None
        if poly_geojson and isinstance(poly_geojson, dict):
            geom_type = poly_geojson.get("type", "")
            coords = poly_geojson.get("coordinates", [])
            if geom_type == "Polygon" and len(coords) > 0:
                polygon_ring = coords[0]
            elif geom_type == "Feature" and "geometry" in poly_geojson:
                g = poly_geojson["geometry"]
                if g.get("type") == "Polygon" and len(g.get("coordinates", [])) > 0:
                    polygon_ring = g["coordinates"][0]

        if polygon_ring and len(polygon_ring) >= 3:
            lons = [pt[0] for pt in polygon_ring]
            lats = [pt[1] for pt in polygon_ring]
            min_lon, max_lon = min(lons), max(lons)
            min_lat, max_lat = min(lats), max(lats)

            samples_collected = 0
            max_attempts = self.num_particles * 20
            attempts = 0

            while samples_collected < self.num_particles and attempts < max_attempts:
                attempts += 1
                cand_lon = random.uniform(min_lon, max_lon)
                cand_lat = random.uniform(min_lat, max_lat)
                if point_in_polygon(cand_lon, cand_lat, polygon_ring):
                    w_factor = max(0.015, min(0.045, random.gauss(self.base_windage, self.windage_std)))
                    particles.append(ParticleState(
                        lat=cand_lat,
                        lon=cand_lon,
                        weight=1.0 / self.num_particles,
                        windage_factor=w_factor
                    ))
                    samples_collected += 1

        if len(particles) < self.num_particles:
            needed = self.num_particles - len(particles)
            radius_km = math.sqrt(max(0.1, detection.area_km2) / math.pi)
            sigma_lat = meters_to_lat_deg(radius_km * 1000.0 / 2.0)
            sigma_lon = meters_to_lon_deg(radius_km * 1000.0 / 2.0, detection.centroid_lat)

            for _ in range(needed):
                p_lat = random.gauss(detection.centroid_lat, max(1e-5, sigma_lat))
                p_lon = random.gauss(detection.centroid_lon, max(1e-5, sigma_lon))
                w_factor = max(0.015, min(0.045, random.gauss(self.base_windage, self.windage_std)))
                particles.append(ParticleState(
                    lat=p_lat,
                    lon=p_lon,
                    weight=1.0 / self.num_particles,
                    windage_factor=w_factor
                ))

        return particles

    def _get_particle_velocity(
        self,
        lat: float,
        lon: float,
        timestamp_utc: datetime,
        windage: float
    ) -> Tuple[float, float, float, float]:
        u_curr, v_curr, u_wind, v_wind = self.env.get_forcing(lat, lon, timestamp_utc)
        theta_coriolis = compute_coriolis_deflection(lat)
        
        u_wind_rot, v_wind_rot = rotate_vector_2d(u_wind, v_wind, theta_coriolis)
        u_total = u_curr + windage * u_wind_rot
        v_total = v_curr + windage * v_wind_rot

        return u_total, v_total, u_curr, v_curr

    def step_particles_rk2(
        self,
        particles: List[ParticleState],
        current_time_utc: datetime,
        dt_seconds: float,
        apply_diffusion: bool = True
    ) -> Tuple[List[ParticleState], Tuple[float, float], Tuple[float, float]]:
        updated_particles = []
        diffusion_scale = math.sqrt(2.0 * self.Kh * abs(dt_seconds)) if apply_diffusion else 0.0

        u_curr_accum, v_curr_accum = 0.0, 0.0

        for p in particles:
            if p.is_beached:
                updated_particles.append(p)
                continue

            u1, v1, uc1, vc1 = self._get_particle_velocity(p.lat, p.lon, current_time_utc, p.windage_factor)
            u_curr_accum += uc1
            v_curr_accum += vc1

            mid_lat = p.lat + meters_to_lat_deg(v1 * (dt_seconds / 2.0))
            mid_lon = p.lon + meters_to_lon_deg(u1 * (dt_seconds / 2.0), p.lat)
            mid_time = current_time_utc + timedelta(seconds=(dt_seconds / 2.0))

            u2, v2, _, _ = self._get_particle_velocity(mid_lat, mid_lon, mid_time, p.windage_factor)

            disp_x_m = u2 * dt_seconds
            disp_y_m = v2 * dt_seconds

            if apply_diffusion:
                disp_x_m += random.gauss(0.0, diffusion_scale)
                disp_y_m += random.gauss(0.0, diffusion_scale)

            new_lat = p.lat + meters_to_lat_deg(disp_y_m)
            new_lon = p.lon + meters_to_lon_deg(disp_x_m, new_lat)

            new_lat = max(-89.9, min(89.9, new_lat))
            new_lon = (new_lon + 180.0) % 360.0 - 180.0

            updated_particles.append(ParticleState(
                lat=new_lat,
                lon=new_lon,
                weight=p.weight,
                windage_factor=p.windage_factor,
                is_beached=p.is_beached
            ))

        n = max(1, len(particles))
        avg_current = (u_curr_accum / n, v_curr_accum / n)
        return updated_particles, avg_current, (0.0, 0.0)

    @staticmethod
    def calculate_uncertainty_ellipse(
        particles: List[ParticleState],
        min_radius_km: float = 0.50
    ) -> Tuple[float, float, SearchEllipse]:
        if not particles:
            return 0.0, 0.0, SearchEllipse(min_radius_km, min_radius_km, 0.0, min_radius_km)

        lats = np.array([p.lat for p in particles], dtype=np.float64)
        lons = np.array([p.lon for p in particles], dtype=np.float64)

        mean_lat = float(np.mean(lats))
        mean_lon = float(np.mean(lons))

        if len(particles) < 3:
            return mean_lat, mean_lon, SearchEllipse(min_radius_km, min_radius_km, 0.0, min_radius_km)

        lat_rad = math.radians(mean_lat)
        dy_km = (lats - mean_lat) * (math.pi / 180.0) * (EARTH_RADIUS_M * 1e-3)
        dx_km = (lons - mean_lon) * (math.pi / 180.0) * (EARTH_RADIUS_M * 1e-3) * math.cos(lat_rad)

        coords_km = np.column_stack([dx_km, dy_km])
        cov = np.cov(coords_km, rowvar=False)

        if not np.all(np.isfinite(cov)):
            return mean_lat, mean_lon, SearchEllipse(min_radius_km, min_radius_km, 0.0, min_radius_km)

        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        order = eigenvalues.argsort()[::-1]
        eigenvalues = eigenvalues[order]
        eigenvectors = eigenvectors[:, order]

        semi_major_km = max(min_radius_km, 2.0 * math.sqrt(max(1e-6, float(eigenvalues[0]))))
        semi_minor_km = max(min_radius_km, 2.0 * math.sqrt(max(1e-6, float(eigenvalues[1]))))

        vx, vy = float(eigenvectors[0, 0]), float(eigenvectors[1, 0])
        orientation_deg = math.degrees(math.atan2(vx, vy))
        equiv_radius_km = math.sqrt(semi_major_km * semi_minor_km)

        ellipse = SearchEllipse(
            semi_major_km=round(semi_major_km, 3),
            semi_minor_km=round(semi_minor_km, 3),
            orientation_deg=round(orientation_deg, 1),
            uncertainty_radius_km=round(equiv_radius_km, 3)
        )

        return mean_lat, mean_lon, ellipse
