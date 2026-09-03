"""
OceanTrace — AIS Vessel Attribution Scoring & Evidence Synthesis Engine
Converts Phase C VesselCorridorCorrelation into bounded evidence features,
transparent composite Attribution Evidence Scores (0-100), independent confidence levels,
and explainable natural language evidence narratives.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
import math

from ml.ais_types import VesselIdentity
from ml.ais_correlation_types import VesselCorridorCorrelation
from ml.ais_attribution_types import (
    AttributionCategory,
    ConfidenceLevel,
    ReasonCode,
    AttributionEvidence,
    AttributionScore,
    AttributionResult
)


def compute_course_alignment(vessel_cog: Optional[float], corridor_heading: Optional[float]) -> Tuple[float, bool]:
    """
    Computes circular angular difference between vessel COG and corridor heading.
    Returns (score, is_valid):
    - 0° difference -> 1.0 (parallel alignment)
    - 90° difference -> 0.5 (orthogonal cross-traffic)
    - 180° difference -> 0.0 (anti-parallel / opposing course)
    """
    if vessel_cog is None or corridor_heading is None:
        return 0.0, False
    if math.isnan(vessel_cog) or math.isnan(corridor_heading):
        return 0.0, False

    diff = abs((vessel_cog - corridor_heading + 180.0) % 360.0 - 180.0)
    score = max(0.0, min(1.0, 1.0 - (diff / 180.0)))
    return score, True


def compute_speed_consistency(vessel_sog: Optional[float]) -> Tuple[float, bool]:
    """
    Evaluates vessel Speed Over Ground (SOG) consistency with standard underway transit.
    En-route cruising speeds receive full consistency; anchored/dead-in-water speeds receive low score.
    Returns (score, is_valid).
    """
    if vessel_sog is None or math.isnan(vessel_sog):
        return 0.0, False

    if 8.0 <= vessel_sog <= 18.0:
        return 1.00, True  # Standard cruising underway
    elif (4.0 <= vessel_sog < 8.0) or (18.0 < vessel_sog <= 24.0):
        return 0.65, True  # Moderate steaming / fast transit
    elif 0.5 <= vessel_sog < 4.0:
        return 0.20, True  # Slow steaming / maneuvering
    else:
        return 0.05, True  # Stationary / anchored (< 0.5 kts)


class VesselAttributionEngine:
    """
    Evaluates candidate vessel correlations against transparent physical evidence rules.
    Computes Attribution Evidence Score, Confidence Level, Reason Codes, and Explanations.
    """

    def __init__(
        self,
        w_spatial: float = 0.50,
        w_corridor: float = 0.20,
        w_course: float = 0.15,
        w_speed: float = 0.15,
        corridor_heading_deg: float = 45.0  # Default regional transit axis
    ):
        self.w_spatial = w_spatial
        self.w_corridor = w_corridor
        self.w_course = w_course
        self.w_speed = w_speed
        self.corridor_heading = corridor_heading_deg

    def extract_evidence(
        self,
        corr: VesselCorridorCorrelation,
        corridor_heading: Optional[float] = None,
        custom_prior: float = 1.00
    ) -> AttributionEvidence:
        """Extracts bounded [0.0, 1.0] physical evidence features from correlation metrics."""
        heading_ref = corridor_heading if corridor_heading is not None else self.corridor_heading
        missing_fields = []

        # A) Spatial score S_dist
        # Normalized distance d_norm = distance / uncertainty_radius
        d_norm = corr.min_cpa_normalized_distance
        if d_norm <= 1.0:
            # Inside the 95% uncertainty ellipse: smooth Gaussian core
            s_dist = math.exp(-0.5 * (d_norm ** 2))
        elif d_norm <= 2.0:
            # Between 1.0 and 2.0 sigma: linear decline to zero
            s_dist = max(0.0, math.exp(-0.5) * (2.0 - d_norm))
        else:
            # Outside 2-sigma boundary: zero spatial compatibility
            s_dist = 0.0

        # B) Corridor overlap score S_overlap
        s_overlap = max(0.0, min(1.0, corr.corridor_overlap_fraction))

        # C) Temporal score S_time
        # Penalizes unobserved data gaps or non-overlapping encounters
        if not corr.has_temporal_overlap or not corr.is_cpa_valid:
            s_time = 0.0
        elif corr.has_gap_near_cpa:
            # Large data gap (>60 min) occurred near CPA -> degrade temporal alignment
            s_time = 0.50
        elif corr.is_cpa_interpolated:
            s_time = 0.85
        else:
            s_time = 1.00

        # D) Course alignment S_cog
        s_cog, cog_valid = compute_course_alignment(corr.vessel_cog_at_cpa, heading_ref)
        if not cog_valid:
            missing_fields.append("cog")

        # E) Speed consistency S_sog
        s_sog, sog_valid = compute_speed_consistency(corr.vessel_sog_at_cpa)
        if not sog_valid:
            missing_fields.append("sog")

        return AttributionEvidence(
            mmsi=corr.mmsi,
            identity=corr.identity,
            s_dist=s_dist,
            s_overlap=s_overlap,
            s_cog=s_cog,
            s_sog=s_sog,
            s_time=s_time,
            w_spatial=self.w_spatial,
            w_corridor=self.w_corridor,
            w_course=self.w_course,
            w_speed=self.w_speed,
            w_prior=custom_prior,
            min_cpa_distance_km=corr.min_cpa_distance_km,
            min_cpa_normalized_distance=corr.min_cpa_normalized_distance,
            min_cpa_time=corr.min_cpa_time,
            min_cpa_hours_offset=corr.min_cpa_hours_offset,
            corridor_overlap_fraction=corr.corridor_overlap_fraction,
            corridor_dwell_steps=corr.corridor_dwell_steps,
            vessel_sog_at_cpa=corr.vessel_sog_at_cpa,
            vessel_cog_at_cpa=corr.vessel_cog_at_cpa,
            closest_hindcast_ellipse=corr.closest_hindcast_ellipse,
            is_cpa_interpolated=corr.is_cpa_interpolated,
            is_cpa_valid=corr.is_cpa_valid,
            has_gap_near_cpa=corr.has_gap_near_cpa,
            missing_fields=missing_fields,
            data_quality=corr.data_quality
        )

    def calculate_score(self, evidence: AttributionEvidence) -> float:
        """
        Calculates composite Attribution Evidence Score (0-100 scale).
        Spatial gating rule: If a vessel never intersected the corridor (s_dist == 0.0 and s_overlap == 0.0),
        supporting features (course/speed) cannot create artificial guilt; score is 0.0.
        """
        # Spatial gating: Course and speed are supporting evidence only.
        # If the vessel was nowhere near the spill corridor (s_dist == 0 and s_overlap == 0),
        # its normal underway cruising elsewhere cannot generate an attribution score.
        if evidence.s_dist <= 0.0 and evidence.s_overlap <= 0.0:
            return 0.0

        active_w_spatial = evidence.w_spatial
        active_w_corridor = evidence.w_corridor
        active_w_course = evidence.w_course if "cog" not in evidence.missing_fields else 0.0
        active_w_speed = evidence.w_speed if "sog" not in evidence.missing_fields else 0.0

        total_weight = active_w_spatial + active_w_corridor + active_w_course + active_w_speed
        if total_weight <= 0.0:
            return 0.0

        base_score = (
            active_w_spatial * evidence.s_dist +
            active_w_corridor * evidence.s_overlap +
            active_w_course * evidence.s_cog +
            active_w_speed * evidence.s_sog
        ) / total_weight

        # Final score scaling: BaseScore * S_time * w_prior * 100
        raw_score = base_score * evidence.s_time * evidence.w_prior * 100.0
        return max(0.0, min(100.0, raw_score))

    def determine_confidence(self, evidence: AttributionEvidence) -> ConfidenceLevel:
        """
        Evaluates data confidence separately from the raw score.
        Considers observation density, absence of gaps, and valid temporal alignment.
        """
        q = evidence.data_quality
        obs_count = q.observation_count if q else 0
        max_gap = q.max_temporal_gap_hours if q else 999.0

        # High Confidence: dense observations (>= 15), no large gaps (< 1.5h), valid CPA timing
        if obs_count >= 15 and max_gap <= 1.5 and not evidence.has_gap_near_cpa and evidence.is_cpa_valid:
            return ConfidenceLevel.HIGH

        # Low Confidence: very sparse (< 4 pings), or large unobserved gap near CPA, or invalid CPA
        if obs_count < 4 or evidence.has_gap_near_cpa or not evidence.is_cpa_valid or max_gap > 6.0:
            return ConfidenceLevel.LOW

        # Medium Confidence: default moderate coverage
        return ConfidenceLevel.MEDIUM

    def categorize_score(self, score: float) -> AttributionCategory:
        """Assigns heuristic score band categories."""
        if score >= 75.0:
            return AttributionCategory.STRONG
        elif score >= 45.0:
            return AttributionCategory.MODERATE
        elif score >= 15.0:
            return AttributionCategory.WEAK
        else:
            return AttributionCategory.INSUFFICIENT_EVIDENCE

    def generate_explanation(
        self,
        evidence: AttributionEvidence,
        score: float,
        category: AttributionCategory,
        confidence: ConfidenceLevel
    ) -> Tuple[List[ReasonCode], str]:
        """Generates structured reason codes and transparent natural-language evidence narrative."""
        reasons: List[ReasonCode] = []
        narrative_parts: List[str] = []

        # 1. Spatial evidence
        if evidence.min_cpa_normalized_distance <= 1.0:
            reasons.append(ReasonCode.CLOSE_SPATIAL_MATCH)
            narrative_parts.append(
                f"Close spatial proximity (CPA {evidence.min_cpa_distance_km:.2f} km, normalized {evidence.min_cpa_normalized_distance:.2f} "
                f"inside modeled 95% uncertainty envelope)"
            )
        else:
            reasons.append(ReasonCode.WEAK_SPATIAL_MATCH)
            narrative_parts.append(
                f"Distant spatial approach (CPA {evidence.min_cpa_distance_km:.2f} km, normalized {evidence.min_cpa_normalized_distance:.2f} "
                f"outside uncertainty envelope)"
            )

        # 2. Corridor dwell
        if evidence.corridor_overlap_fraction > 0.0:
            reasons.append(ReasonCode.CORRIDOR_OVERLAP)
            narrative_parts.append(f"{evidence.corridor_overlap_fraction * 100:.1f}% corridor overlap ({evidence.corridor_dwell_steps} steps)")

        # 3. Timing and gaps
        if evidence.has_gap_near_cpa:
            reasons.append(ReasonCode.LARGE_AIS_GAP)
            narrative_parts.append("an unobserved AIS data gap >60 min occurred near the closest point of approach")
        elif evidence.s_time >= 0.85:
            reasons.append(ReasonCode.STRONG_TEMPORAL_ALIGNMENT)
            narrative_parts.append(f"strong temporal alignment at t0{evidence.min_cpa_hours_offset:+.1f}h")
        else:
            reasons.append(ReasonCode.WEAK_TEMPORAL_ALIGNMENT)
            narrative_parts.append(f"weak temporal alignment at t0{evidence.min_cpa_hours_offset:+.1f}h")

        if evidence.is_cpa_interpolated:
            reasons.append(ReasonCode.INTERPOLATION_DEPENDENT)

        # 4. Kinematics
        if "cog" in evidence.missing_fields:
            reasons.append(ReasonCode.MISSING_COG)
        elif evidence.s_cog >= 0.70:
            reasons.append(ReasonCode.COG_ALIGNMENT)
            narrative_parts.append("course aligns with the corridor advection axis")

        if "sog" in evidence.missing_fields:
            reasons.append(ReasonCode.MISSING_SOG)
        elif evidence.s_sog >= 0.70:
            reasons.append(ReasonCode.SPEED_CONSISTENCY)
            narrative_parts.append(f"cruising underway speed ({evidence.vessel_sog_at_cpa:.1f} kts)")

        # 5. Quality context
        if evidence.data_quality and evidence.data_quality.observation_count < 5:
            reasons.append(ReasonCode.SPARSE_AIS)
            narrative_parts.append("sparse AIS reporting history")

        if category == AttributionCategory.INSUFFICIENT_EVIDENCE:
            reasons.append(ReasonCode.INSUFFICIENT_EVIDENCE)

        v_name = evidence.identity.name or f"Vessel MMSI {evidence.mmsi}"
        explanation_text = f"{v_name}: " + "; ".join(narrative_parts) + f". Result: {category.value} ({score:.1f}/100, {confidence.value} confidence)."
        return reasons, explanation_text

    def evaluate_candidate(
        self,
        corr: VesselCorridorCorrelation,
        corridor_heading: Optional[float] = None,
        custom_prior: float = 1.00
    ) -> AttributionScore:
        """Performs full end-to-end evaluation of a single vessel corridor correlation."""
        evidence = self.extract_evidence(corr, corridor_heading, custom_prior)
        score = self.calculate_score(evidence)
        confidence = self.determine_confidence(evidence)
        category = self.categorize_score(score)
        reasons, explanation = self.generate_explanation(evidence, score, category, confidence)

        return AttributionScore(
            mmsi=corr.mmsi,
            identity=corr.identity,
            overall_score=score,
            confidence=confidence,
            category=category,
            evidence=evidence,
            reason_codes=reasons,
            explanation=explanation
        )

    def evaluate_and_rank_fleet(
        self,
        correlations: List[VesselCorridorCorrelation],
        corridor_heading: Optional[float] = None,
        incident_id: str = "incident_investigation"
    ) -> AttributionResult:
        """Evaluates all candidate vessels and produces a ranked, sorted AttributionResult."""
        evaluated = [self.evaluate_candidate(c, corridor_heading) for c in correlations]
        # Sort descending by Attribution Evidence Score
        evaluated.sort(key=lambda s: s.overall_score, reverse=True)

        for rank_idx, cand in enumerate(evaluated, start=1):
            cand.rank = rank_idx

        return AttributionResult(
            incident_id=incident_id,
            scoring_timestamp=datetime.now(timezone.utc),
            scoring_version="Phase_D_v1.0",
            candidate_count=len(evaluated),
            ranked_candidates=evaluated,
            methodology={
                "weights": {
                    "spatial": self.w_spatial,
                    "corridor": self.w_corridor,
                    "course": self.w_course,
                    "speed": self.w_speed
                },
                "corridor_heading_deg": corridor_heading if corridor_heading is not None else self.corridor_heading,
                "score_range": "0.0 - 100.0 (Attribution Evidence Score)",
                "confidence_levels": ["HIGH", "MEDIUM", "LOW"],
                "categories": ["STRONG", "MODERATE", "WEAK", "INSUFFICIENT_EVIDENCE"]
            }
        )
