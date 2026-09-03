"""
OceanTrace Model 2 — Backward Drift Hindcasting & Source Estimation Engine
Performs time-reversed advection (t0 -> t0 - 48h) to reconstruct the candidate spill origin corridor
and generates expanding spatial uncertainty search cones for forensic AIS vessel attribution.
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
from ml.forecast import generate_ellipse_geojson_ring


class BackwardHindcaster:
    """
    Reconstructs candidate release locations backward in time.
    Uses deterministic reverse advection combined with time-expanding uncertainty growth.
    """

    def __init__(
        self,
        drift_engine: DriftEngine,
        horizon_hours: float = 48.0,
        output_interval_hours: float = 6.0,
        env_error_growth_rate_km_per_hour: float = 0.15  # Environmental model spatial divergence rate
    ):
        self.engine = drift_engine
        self.horizon_hours = horizon_hours
        self.output_interval_hours = output_interval_hours
        self.env_growth_rate = env_error_growth_rate_km_per_hour

    def hindcast(
        self,
        detection: SpillDetection,
        initial_particles: Optional[List[ParticleState]] = None
    ) -> TrajectoryPackage:
        """
        Executes backward integration from detection_timestamp to -horizon_hours.
        """
        t0 = detection.utc_datetime
        particles = initial_particles or self.engine.seed_particles(detection)

        # Backward timestep is negative
        dt_sec = -abs(self.engine.dt)  # standard -900s (-15 min)
        total_seconds = self.horizon_hours * 3600.0
        num_steps = int(math.ceil(total_seconds / abs(dt_sec)))

        report_interval_sec = self.output_interval_hours * 3600.0
        next_report_sec = report_interval_sec

        steps: List[TrajectoryStep] = []
        current_particles = copy.deepcopy(particles)
        current_time = t0

        # Step 0: Record initial detection state at t0
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

        elapsed_backward_sec = 0.0
        for step_idx in range(1, num_steps + 1):
            # Deterministic reverse advection along inverse velocity streamlines
            current_particles, u_curr, _ = self.engine.step_particles_rk2(
                particles=current_particles,
                current_time_utc=current_time,
                dt_seconds=dt_sec,
                apply_diffusion=False  # Diffusion is physically irreversible; handled via expanding variance
            )
            elapsed_backward_sec += abs(dt_sec)
            current_time = t0 - timedelta(seconds=elapsed_backward_sec)

            # Record state at discrete backward horizons
            if elapsed_backward_sec >= (next_report_sec - 1.0) or step_idx == num_steps:
                c_lat, c_lon, raw_ellipse = self.engine.calculate_uncertainty_ellipse(current_particles)
                h_offset = -(elapsed_backward_sec / 3600.0)

                # Time-expanding uncertainty radius: sigma_tot(tau) = sigma_particle + alpha_env * tau + sqrt(2 Kh tau)
                tau_hours = elapsed_backward_sec / 3600.0
                diffusion_growth_km = math.sqrt(2.0 * self.engine.Kh * elapsed_backward_sec) * 1e-3
                env_growth_km = self.env_growth_rate * tau_hours
                total_expansion_km = env_growth_km + diffusion_growth_km

                expanded_ellipse = SearchEllipse(
                    semi_major_km=round(raw_ellipse.semi_major_km + total_expansion_km, 3),
                    semi_minor_km=round(raw_ellipse.semi_minor_km + total_expansion_km * 0.75, 3),
                    orientation_deg=raw_ellipse.orientation_deg,
                    uncertainty_radius_km=round(raw_ellipse.uncertainty_radius_km + total_expansion_km, 3)
                )

                steps.append(TrajectoryStep(
                    hours_offset=h_offset,
                    timestamp=current_time.isoformat(),
                    centroid_lat=c_lat,
                    centroid_lon=c_lon,
                    ellipse=expanded_ellipse,
                    particle_count=len(current_particles),
                    particles_sample=[(round(p.lat, 5), round(p.lon, 5)) for p in current_particles[:30]],
                    water_velocity_ms=(round(u_curr[0], 3), round(u_curr[1], 3))
                ))
                next_report_sec += report_interval_sec

        # Construct GeoJSON LineString for Backward Path
        line_coords = [[s.centroid_lon, s.centroid_lat] for s in steps]
        trajectory_geojson = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": line_coords
            },
            "properties": {
                "description": f"OceanTrace {self.horizon_hours}h Backward Source Hindcast Path",
                "start_time": steps[0].timestamp,
                "end_time": steps[-1].timestamp,
                "total_steps": len(steps)
            }
        }

        # Construct GeoJSON MultiPolygon for Expanding Search Cones
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
                "description": "Backward Probabilistic Source Search Cones (95% Confidence)"
            }
        }

        return TrajectoryPackage(
            horizon_hours=self.horizon_hours,
            direction="hindcast",
            steps=steps,
            trajectory_geojson=trajectory_geojson,
            uncertainty_cone_geojson=uncertainty_cone_geojson
        )
