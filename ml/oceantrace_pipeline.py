"""
OceanTrace — End-to-End Maritime Oil Spill Intelligence Pipeline Orchestrator
Connects all subsystem stages:
1. SATELLITE RASTER (Sentinel-1 SAR dual-pol)
2. FROZEN V6 E21 MODEL 1 (SARDeepLabV3Plus_MultiTask_scSE)
3. GEOSPATIAL ADAPTER (WGS84 projection & moment analysis)
4. CANONICAL SPILLDETECTION
5. MODEL 2 P-LDHE DRIFT & HINDCAST (RK2 Midpoint, 48h search cone)
6. AIS PROVIDER QUERY (Synthetic / Historical / Local SQLite)
7. PHASE C AIS CORRIDOR CORRELATION (Two-stage spatial/temporal filter + dynamic CPA)
8. PHASE D ATTRIBUTION SCORING (Composite evidence scoring 0-100, confidence, reason codes)
9. RANKED VESSEL CANDIDATES & FORENSIC DOSSIER
"""

import os
import math
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field, asdict
import numpy as np

# PyTorch
import torch
import torch.nn as nn
import torch.nn.functional as F

# Model 1 & Geospatial
from ml.models import SARDeepLabV3Plus
from ml.geospatial_adapter import GeospatialAdapter
from ml.drift_types import (
    SpillDetection,
    SearchEllipse,
    TrajectoryStep,
    TrajectoryPackage,
    DriftResult
)

# Model 2 Drift & Hindcast
from ml.environmental_provider import EnvironmentalProvider, SyntheticClimatologyProvider
from ml.drift_engine import DriftEngine
from ml.hindcast import BackwardHindcaster
from ml.forecast import ForwardForecaster

# AIS Subsystem
from ml.ais_types import AISQuery, VesselTrack
from ml.ais_provider import AISProvider
from ml.synthetic_ais_provider import SyntheticAISProvider
from ml.ais_corridor import AISCorridorCorrelator
from ml.ais_correlation_types import VesselCorridorCorrelation
from ml.vessel_attribution import VesselAttributionEngine
from ml.ais_attribution_types import AttributionResult, AttributionScore, AttributionCategory, ConfidenceLevel


# --- Multi-Task scSE Sub-modules for Frozen V6 E21 Checkpoint ---
class DoubleConv(nn.Module):
    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True)
        )
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(x)


class ASPPConv(nn.Sequential):
    def __init__(self, in_channels: int, out_channels: int, dilation: int):
        super().__init__(
            nn.Conv2d(in_channels, out_channels, 3, padding=dilation, dilation=dilation, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )


class ASPPPooling(nn.Sequential):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__(
            nn.AdaptiveAvgPool2d(1),
            nn.Conv2d(in_channels, out_channels, 1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        size = x.shape[-2:]
        for mod in self:
            x = mod(x)
        return F.interpolate(x, size=size, mode="bilinear", align_corners=False)


class ASPP(nn.Module):
    def __init__(self, in_channels: int, atrous_rates: List[int] = [6, 12, 18], out_channels: int = 128):
        super().__init__()
        modules = [nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )]
        for rate in atrous_rates:
            modules.append(ASPPConv(in_channels, out_channels, rate))
        modules.append(ASPPPooling(in_channels, out_channels))
        self.convs = nn.ModuleList(modules)
        self.project = nn.Sequential(
            nn.Conv2d(len(modules) * out_channels, out_channels, 1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3)
        )
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        res = [conv(x) for conv in self.convs]
        cat_feat = torch.cat(res, dim=1)
        return self.project(cat_feat)


class SCSEBlock(nn.Module):
    def __init__(self, in_channels: int, reduction: int = 16):
        super().__init__()
        self.cSE = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Conv2d(in_channels, max(1, in_channels // reduction), 1, bias=True),
            nn.ReLU(inplace=True),
            nn.Conv2d(max(1, in_channels // reduction), in_channels, 1, bias=True),
            nn.Sigmoid()
        )
        self.sSE = nn.Sequential(
            nn.Conv2d(in_channels, 1, 1, bias=True),
            nn.Sigmoid()
        )
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x * self.cSE(x) + x * self.sSE(x)


class SceneClassifier(nn.Module):
    def __init__(self, in_channels: int = 256, num_classes: int = 3):
        super().__init__()
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.mlp = nn.Sequential(
            nn.Linear(in_channels, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(128, num_classes)
        )
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.pool(x).flatten(1)
        return self.mlp(feat)


class SARDeepLabV3Plus_MultiTask_scSE(nn.Module):
    """
    Exact Model 1 V6 E21 architecture matching checkpoint:
    V6_E21_FINAL/oceantrace_v6_E21_final.pth
    """
    def __init__(self, in_channels: int = 3, num_classes: int = 1, num_scene_classes: int = 3, base_filters: int = 32):
        super().__init__()
        self.initial = DoubleConv(in_channels, base_filters)
        self.layer1 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters, base_filters * 2))
        self.layer2 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters * 2, base_filters * 4))
        self.layer3 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters * 4, base_filters * 8))

        self.aspp = ASPP(in_channels=base_filters * 8, atrous_rates=[6, 12, 18], out_channels=base_filters * 4)
        self.aspp_scse = SCSEBlock(in_channels=base_filters * 4, reduction=8)
        self.scene_classifier = SceneClassifier(in_channels=base_filters * 8, num_classes=num_scene_classes)

        self.low_level_proj = nn.Sequential(
            nn.Conv2d(base_filters * 2, base_filters, 1, bias=False),
            nn.BatchNorm2d(base_filters),
            nn.ReLU(inplace=True)
        )
        self.decoder = nn.Sequential(
            DoubleConv(base_filters * 4 + base_filters, base_filters * 2),
            nn.Conv2d(base_filters * 2, num_classes, 1)
        )

    def forward(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        size = x.shape[-2:]
        x0 = self.initial(x)
        low = self.layer1(x0)
        x2 = self.layer2(low)
        x3 = self.layer3(x2)

        scene_logits = self.scene_classifier(x3)
        aspp_out = self.aspp(x3)
        aspp_scse_out = self.aspp_scse(aspp_out)

        aspp_up = F.interpolate(aspp_scse_out, size=low.shape[-2:], mode="bilinear", align_corners=False)
        low_proj = self.low_level_proj(low)

        dec_in = torch.cat([aspp_up, low_proj], dim=1)
        logits_low = self.decoder(dec_in)
        seg_logits = F.interpolate(logits_low, size=size, mode="bilinear", align_corners=False)

        return {
            "seg_logits": seg_logits,
            "scene_logits": scene_logits
        }


@dataclass
class OceanTracePipelineResult:
    """
    Structured End-to-End Execution Result for OceanTrace.
    """
    incident_id: str
    spill_detection: Optional[SpillDetection]
    model1_summary: Dict[str, Any]
    drift_result: Optional[DriftResult]
    ais_correlations: List[VesselCorridorCorrelation]
    attributions: Optional[AttributionResult]
    timings_ms: Dict[str, float]
    providers: Dict[str, str]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "spill_detected": self.spill_detection is not None,
            "spill_detection": self.spill_detection.to_dict() if self.spill_detection else None,
            "model1_summary": self.model1_summary,
            "drift_result": self.drift_result.to_dict() if self.drift_result else None,
            "candidate_count": len(self.ais_correlations),
            "attributions": self.attributions.to_dict() if self.attributions else None,
            "timings_ms": self.timings_ms,
            "providers": self.providers,
            "warnings": self.warnings
        }


class OceanTracePipeline:
    """
    Orchestrates the complete OceanTrace detection, tracking, correlation, and attribution workflow.
    """

    def __init__(
        self,
        checkpoint_path: str = "V6_E21_FINAL/oceantrace_v6_E21_final.pth",
        detection_threshold: float = 0.28,
        device: str = "cpu",
        env_provider: Optional[EnvironmentalProvider] = None,
        ais_provider: Optional[AISProvider] = None,
        attribution_engine: Optional[VesselAttributionEngine] = None
    ):
        self.checkpoint_path = checkpoint_path
        self.detection_threshold = detection_threshold
        self.device = torch.device(device)

        # 1. Load Model 1
        self.model, self.norm_stats = self._load_model1(checkpoint_path)

        # 2. Geospatial Adapter
        self.geo_adapter = GeospatialAdapter(detection_threshold=detection_threshold)

        # 3. Environmental & Drift Providers
        self.env_provider = env_provider or SyntheticClimatologyProvider()
        self.drift_engine = DriftEngine(env_provider=self.env_provider, default_particle_count=250, seed=42)
        self.hindcaster = BackwardHindcaster(drift_engine=self.drift_engine, horizon_hours=48.0, output_interval_hours=6.0)
        self.forecaster = ForwardForecaster(drift_engine=self.drift_engine, horizon_hours=48.0, output_interval_hours=6.0)

        # 4. AIS Subsystem
        self.ais_provider = ais_provider or SyntheticAISProvider()
        self.correlator = AISCorridorCorrelator()
        self.attribution_engine = attribution_engine or VesselAttributionEngine()

    def _load_model1(self, ckpt_path: str) -> Tuple[nn.Module, Dict[str, float]]:
        """Loads frozen V6 E21 checkpoint into SARDeepLabV3Plus_MultiTask_scSE."""
        if not os.path.exists(ckpt_path):
            raise FileNotFoundError(f"Model 1 checkpoint not found at: {ckpt_path}")

        ckpt = torch.load(ckpt_path, map_location=self.device)
        model = SARDeepLabV3Plus_MultiTask_scSE().to(self.device)
        model.load_state_dict(ckpt["model_state"])
        model.eval()

        norm_stats = ckpt.get("norm_stats", {
            "vv_min": -43.991, "vv_max": 0.0,
            "vh_min": -29.299, "vh_max": 0.0,
            "diff_min": -25.275, "diff_max": 0.0
        })
        return model, norm_stats

    def preprocess_sar_raster(
        self,
        raster: np.ndarray,
        crop_size: Tuple[int, int] = (512, 512)
    ) -> Tuple[torch.Tensor, Tuple[int, int, int, int]]:
        """
        Normalizes a dual-pol SAR raster [H, W, 2] (VV, VH in dB) into a 3-channel
        normalized PyTorch tensor [1, 3, 512, 512].
        Returns (tensor, (y0, x0, ch, cw)).
        """
        if raster.ndim == 2:
            raster = np.stack([raster, raster - 7.0], axis=-1)

        h, w = raster.shape[:2]
        ch, cw = crop_size
        ch = min(h, ch)
        cw = min(w, cw)

        y0 = (h - ch) // 2
        x0 = (w - cw) // 2
        patch = raster[y0:y0+ch, x0:x0+cw]

        vv_raw = patch[:, :, 0]
        vh_raw = patch[:, :, 1]
        diff_raw = vv_raw - vh_raw

        vv_norm = np.clip((vv_raw - self.norm_stats["vv_min"]) / max(1e-5, self.norm_stats["vv_max"] - self.norm_stats["vv_min"]), 0.0, 1.0)
        vh_norm = np.clip((vh_raw - self.norm_stats["vh_min"]) / max(1e-5, self.norm_stats["vh_max"] - self.norm_stats["vh_min"]), 0.0, 1.0)
        diff_norm = np.clip((diff_raw - self.norm_stats["diff_min"]) / max(1e-5, self.norm_stats["diff_max"] - self.norm_stats["diff_min"]), 0.0, 1.0)

        inp_3ch = np.stack([vv_norm, vh_norm, diff_norm], axis=0).astype(np.float32)
        tensor = torch.from_numpy(inp_3ch).unsqueeze(0).to(self.device)
        return tensor, (y0, x0, ch, cw)

    def run_pipeline(
        self,
        raster_input: np.ndarray,
        scene_bounds: Dict[str, float],
        source_scene_id: str,
        detection_timestamp_utc: str,
        incident_id: Optional[str] = None
    ) -> OceanTracePipelineResult:
        """
        Executes end-to-end OceanTrace pipeline from raster input to ranked vessel candidates.
        """
        inc_id = incident_id or f"inc_{source_scene_id}_{int(datetime.now(timezone.utc).timestamp())}"
        timings: Dict[str, float] = {}
        warnings: List[str] = []

        providers = {
            "model_1": "SARDeepLabV3Plus_MultiTask_scSE (V6 E21 Final)",
            "environmental": getattr(self.env_provider, "__class__", type(self.env_provider)).__name__,
            "ais": getattr(self.ais_provider, "provider_id", "ais_provider")
        }

        if isinstance(self.ais_provider, SyntheticAISProvider):
            warnings.append("SYNTHETIC AIS — NOT REAL VESSEL EVIDENCE")
        if isinstance(self.env_provider, SyntheticClimatologyProvider):
            warnings.append("SYNTHETIC ENVIRONMENT — OFFLINE TEST ONLY")

        # -------------------------------------------------------------
        # STEP 1 & 2: Model 1 Inference
        # -------------------------------------------------------------
        t_start = time.perf_counter()
        inp_tensor, crop_coords = self.preprocess_sar_raster(raster_input)

        with torch.no_grad():
            m1_out = self.model(inp_tensor)
            prob_patch = torch.sigmoid(m1_out["seg_logits"]).squeeze().cpu().numpy()
            scene_logits = m1_out["scene_logits"].squeeze().cpu().numpy()

        timings["model1_ms"] = round((time.perf_counter() - t_start) * 1000.0, 2)

        scene_cls_idx = int(np.argmax(scene_logits))
        scene_classes = ["Clean Sea", "Oil Spill", "Lookalike"]
        detected_scene_cls = scene_classes[scene_cls_idx] if scene_cls_idx < len(scene_classes) else "Unknown"

        model1_summary = {
            "checkpoint": self.checkpoint_path,
            "threshold": self.detection_threshold,
            "scene_classification": detected_scene_cls,
            "scene_logits": [round(float(v), 4) for v in scene_logits],
            "peak_probability": round(float(np.max(prob_patch)), 4),
            "mean_probability": round(float(np.mean(prob_patch)), 4)
        }

        # -------------------------------------------------------------
        # STEP 3 & 4: Geospatial Conversion & SpillDetection
        # -------------------------------------------------------------
        t_geo = time.perf_counter()
        detection = self.geo_adapter.mask_to_spill_detection(
            prob_mask=prob_patch,
            scene_bounds=scene_bounds,
            source_scene_id=source_scene_id,
            detection_timestamp=detection_timestamp_utc,
            detection_id=f"det_{inc_id}",
            scene_classification=detected_scene_cls
        )
        timings["geospatial_ms"] = round((time.perf_counter() - t_geo) * 1000.0, 2)

        if detection is None:
            warnings.append("NO_OIL_DETECTED_ABOVE_THRESHOLD")
            return OceanTracePipelineResult(
                incident_id=inc_id,
                spill_detection=None,
                model1_summary=model1_summary,
                drift_result=None,
                ais_correlations=[],
                attributions=None,
                timings_ms=timings,
                providers=providers,
                warnings=warnings
            )

        # -------------------------------------------------------------
        # STEP 5 & 6: Model 2 P-LDHE Hindcast & Forecast
        # -------------------------------------------------------------
        t_drift = time.perf_counter()
        hindcast_pkg = self.hindcaster.hindcast(detection)
        forecast_pkg = self.forecaster.forecast(detection)

        drift_result = DriftResult(
            incident_id=inc_id,
            detection=detection,
            hindcast=hindcast_pkg,
            forecast=forecast_pkg,
            metadata={
                "engine": "P-LDHE (RK2 Midpoint)",
                "particles": self.drift_engine.num_particles,
                "windage_factor": self.drift_engine.base_windage,
                "diffusion_Kh": self.drift_engine.Kh
            }
        )
        timings["model2_drift_ms"] = round((time.perf_counter() - t_drift) * 1000.0, 2)

        # -------------------------------------------------------------
        # STEP 7 & 8: AIS Track Query & Phase C Corridor Correlation
        # -------------------------------------------------------------
        t_ais = time.perf_counter()
        # Compute hindcast temporal and spatial query envelope
        t_end = detection.utc_datetime
        t_start_ais = t_end - timedelta(hours=hindcast_pkg.horizon_hours)

        lats = [s.centroid_lat for s in hindcast_pkg.steps]
        lons = [s.centroid_lon for s in hindcast_pkg.steps]
        max_r_km = max(s.ellipse.uncertainty_radius_km for s in hindcast_pkg.steps)
        pad_deg = (max_r_km + 30.0) / 111.0

        ais_query = AISQuery(
            start_time=t_start_ais,
            end_time=t_end,
            min_lat=min(lats) - pad_deg,
            max_lat=max(lats) + pad_deg,
            min_lon=min(lons) - pad_deg,
            max_lon=max(lons) + pad_deg
        )

        candidate_tracks = self.ais_provider.query_tracks(ais_query)
        correlations = self.correlator.correlate_fleet(candidate_tracks, hindcast_pkg)
        timings["ais_query_and_correlate_ms"] = round((time.perf_counter() - t_ais) * 1000.0, 2)

        # -------------------------------------------------------------
        # STEP 9 & 10: Phase D Attribution & Candidate Ranking
        # -------------------------------------------------------------
        t_attr = time.perf_counter()
        attributions: Optional[AttributionResult] = None
        if correlations:
            # Estimate general corridor heading from first and last hindcast step
            c0 = hindcast_pkg.steps[0]
            cend = hindcast_pkg.steps[-1]
            dlat = cend.centroid_lat - c0.centroid_lat
            dlon = (cend.centroid_lon - c0.centroid_lon) * math.cos(math.radians(c0.centroid_lat))
            corridor_heading = (math.degrees(math.atan2(dlon, dlat)) + 360.0) % 360.0

            attributions = self.attribution_engine.evaluate_and_rank_fleet(
                correlations=correlations,
                corridor_heading=corridor_heading,
                incident_id=inc_id
            )
        timings["attribution_ms"] = round((time.perf_counter() - t_attr) * 1000.0, 2)

        timings["total_pipeline_ms"] = round(
            timings["model1_ms"] + timings["geospatial_ms"] +
            timings["model2_drift_ms"] + timings["ais_query_and_correlate_ms"] +
            timings["attribution_ms"],
            2
        )

        return OceanTracePipelineResult(
            incident_id=inc_id,
            spill_detection=detection,
            model1_summary=model1_summary,
            drift_result=drift_result,
            ais_correlations=correlations,
            attributions=attributions,
            timings_ms=timings,
            providers=providers,
            warnings=warnings
        )
