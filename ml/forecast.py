"""
OceanTrace Model 2 — Forward Drift Forecasting Engine
Advects Lagrangian particles forward in time (t0 -> t0 + 48h) to forecast spill trajectory,
dispersion envelope, and shoreline encounter probability.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import math
import copy

from ml.drift_types import (
    SpillDetection,
    ParticleState,
    TrajectoryStep,
    TrajectoryPackage,
    SearchEllipse,
    parse_utc_iso
)
from ml.drift_engine import DriftEngine, meters_to_lat_deg, meters_to_lon_deg


def generate_ellipse_geojson_ring(
    center_lat: float,
    center_lon: float,
    semi_major_km: float,
    semi_minor_km: float,
    angle_deg: float,
    num_points: int = 36
) -> List[List[float]]:
    """Generates a closed WGS84 GeoJSON polygon ring representing the 95% confidence ellipse."""
    coords = []
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    for i in range(num_points + 1):
        theta = (2.0 * math.pi * i) / num_points
        # Local unrotated ellipse coordinates in km
        x_local = semi_major_km * math.cos(theta)
        y_local = semi_minor_km * math.sin(theta)

        # Rotate by orientation angle
        dx_km = x_local * cos_a - y_local * sin_a
        dy_km = x_local * sin_a + y_local * cos_a

        # Convert to lat/lon degrees
        pt_lat = center_lat + meters_to_lat_deg(dy_km * 1000.0)
        pt_lon = center_lon + meters_to_lon_deg(dx_km * 1000.0, pt_lat)
        pt_lon = (pt_lon + 180.0) % 360.0 - 180.0

        coords.append([round(pt_lon, 6), round(pt_lat, 6)])

    return coords


class ForwardForecaster:
    """
    Simulates forward spill dispersion and advection out to the specified forecast horizon.
    """

    def __init__(
        self,
        drift_engine: DriftEngine,
        horizon_hours: float = 48.0,
        output_interval_hours: float = 6.0
    ):
        self.engine = drift_engine
        self.horizon_hours = horizon_hours
        self.output_interval_hours = output_interval_hours

    def forecast(
        self,
        detection: SpillDetection,
        initial_particles: Optional[List[ParticleState]] = None
    ) -> TrajectoryPackage:
        """
        Executes forward integration from detection_timestamp out to +horizon_hours.
        """
        t0 = detection.utc_datetime
        particles = initial_particles or self.engine.seed_particles(detection)

        dt_sec = self.engine.dt  # standard 900s (15 min)
        total_seconds = self.horizon_hours * 3600.0
        num_steps = int(math.ceil(total_seconds / dt_sec))

        report_interval_sec = self.output_interval_hours * 3600.0
        next_report_sec = report_interval_sec

        steps: List[TrajectoryStep] = []
        current_particles = copy.deepcopy(particles)
        current_time = t0

        # Step 0: Record initial state at t0
        c_lat, c_lon, init_ellipse = self.engine.calculate_uncertainty_ellipse(current_particles)
        steps.append(TrajectoryStep(
            hours_offset=0.0,
            timestamp=current_time.isoformat(),
            centroid_lat=c_lat,
            centroid_lon=c_lon,
            ellipse=init_ellipse,
            particle_count=len(current_particles),
            particles_sample=[(round(p.lat, 5), round(p.lon, 5)) for p in current_particles[:30]]
        ))

        elapsed_sec = 0.0
        for step_idx in range(1, num_steps + 1):
            current_particles, u_curr, u_wind = self.engine.step_particles_rk2(
                particles=current_particles,
                current_time_utc=current_time,
                dt_seconds=dt_sec,
                apply_diffusion=True
            )
            elapsed_sec += dt_sec
            current_time = t0 + timedelta(seconds=elapsed_sec)

            # Record state at discrete output horizons
            if elapsed_sec >= (next_report_sec - 1.0) or step_idx == num_steps:
                c_lat, c_lon, ellipse = self.engine.calculate_uncertainty_ellipse(current_particles)
                h_offset = elapsed_sec / 3600.0

                steps.append(TrajectoryStep(
                    hours_offset=h_offset,
                    timestamp=current_time.isoformat(),
                    centroid_lat=c_lat,
                    centroid_lon=c_lon,
                    ellipse=ellipse,
                    particle_count=len(current_particles),
                    particles_sample=[(round(p.lat, 5), round(p.lon, 5)) for p in current_particles[:30]],
                    water_velocity_ms=(round(u_curr[0], 3), round(u_curr[1], 3))
                ))
                next_report_sec += report_interval_sec

        # Construct GeoJSON LineString for Centroid Path
        line_coords = [[s.centroid_lon, s.centroid_lat] for s in steps]
        trajectory_geojson = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": line_coords
            },
            "properties": {
                "description": f"OceanTrace {self.horizon_hours}h Forward Spill Drift Forecast",
                "start_time": steps[0].timestamp,
                "end_time": steps[-1].timestamp,
                "total_steps": len(steps)
            }
        }

        # Construct GeoJSON MultiPolygon for 95% Confidence Ellipses
        ellipse_polys = []
        for s in steps:
            ring = generate_ellipse_geojson_ring(
                s.centroid_lat, s.centroid_lon,
                s.ellipse.semi_major_km, s.ellipse.semi_minor_km,
                s.ellipse.orientation_deg
            )
            ellipse_polys.append([ring])

        uncertainty_cone_geojson = {
            "type": "Feature",
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": ellipse_polys
            },
            "properties": {
                "description": "Forward Dispersion 95% Confidence Envelopes"
            }
        }

        return TrajectoryPackage(
            horizon_hours=self.horizon_hours,
            direction="forecast",
            steps=steps,
            trajectory_geojson=trajectory_geojson,
            uncertainty_cone_geojson=uncertainty_cone_geojson
        )
