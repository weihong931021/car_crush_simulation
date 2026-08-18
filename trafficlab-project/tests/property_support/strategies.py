"""Bounded reusable strategies for Haware's numbered design properties."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Optional

from hypothesis import strategies as st

from trafficlab.motion.haware_accuracy.models import (
    CalibrationSnapshot, ClosedInterval, ContentIdentity, DecisionStatus,
    EvidenceGateDecision, ImageObservation, NuisanceField, NuisanceProfile,
    NuisanceVector, ObservationRecord, PartitionKind, PilotDecision, PilotPopulation,
    PopulationPartition, Pose2D, ProviderProvenance, SemanticPath, SemanticPathSpec,
    SiteDecision, SourceProvenance, TrackKind, TrackProvenance,
)


ZERO_IDENTITY = ContentIdentity("0" * 64)
_SAFE_TEXT = "abcdefghijklmnopqrstuvwxyz0123456789-_"
IDENTIFIERS = st.text(alphabet=_SAFE_TEXT, min_size=1, max_size=16)
SITES = st.sampled_from(("kee-cc", "taoyuan-tc"))
CUE_LABELS = st.sampled_from(("wheel", "ground_contact", "roof", "glass", "mirror"))


@dataclass(frozen=True)
class NuisanceCase:
    profile: NuisanceProfile
    values: NuisanceVector


@dataclass(frozen=True)
class SupportBoundaryCase:
    boundary_px: float
    immediately_below_px: float
    equal_px: float
    immediately_above_px: float


def bounded_floats(lower: float, upper: float):
    """Finite bounded floats with both closed endpoints explicitly reachable."""
    return st.one_of(
        st.just(float(lower)),
        st.just(float(upper)),
        st.floats(min_value=lower, max_value=upper, allow_nan=False, allow_infinity=False),
    )


def _source(source_id: str = "generated") -> SourceProvenance:
    return SourceProvenance(
        source_id=source_id,
        repository_relative_path=None,
        source_content_identity=ZERO_IDENTITY,
    )

@st.composite
def valid_calibrations(draw):
    """Generate finite calibrations with an analytically invertible homography."""
    sx = draw(bounded_floats(0.5, 2.0))
    sy = draw(bounded_floats(0.5, 2.0))
    tx = draw(bounded_floats(-500.0, 500.0))
    ty = draw(bounded_floats(-500.0, 500.0))
    fx = draw(bounded_floats(200.0, 2000.0))
    fy = draw(bounded_floats(200.0, 2000.0))
    cx = draw(bounded_floats(0.0, 1920.0))
    cy = draw(bounded_floats(0.0, 1080.0))
    distortion = tuple(draw(st.lists(
        bounded_floats(-0.25, 0.25), min_size=5, max_size=5
    )))
    return CalibrationSnapshot(
        version="generated-v1",
        camera_matrix=((fx, 0.0, cx), (0.0, fy, cy), (0.0, 0.0, 1.0)),
        distortion=distortion,
        homography=((sx, 0.0, tx), (0.0, sy, ty), (0.0, 0.0, 1.0)),
        inverse_homography=(
            (1.0 / sx, 0.0, -tx / sx),
            (0.0, 1.0 / sy, -ty / sy),
            (0.0, 0.0, 1.0),
        ),
        camera_sat_px=(draw(bounded_floats(-4096.0, 4096.0)), draw(bounded_floats(-4096.0, 4096.0))),
        camera_height_m=draw(bounded_floats(2.0, 30.0)),
        pixels_per_metre=draw(bounded_floats(1.0, 100.0)),
        provenance=_source("generated-calibration"),
    )


@st.composite
def degenerate_calibrations(draw):
    """Generate structurally finite snapshots that projection validation must reject."""
    calibration = draw(valid_calibrations())
    degeneration = draw(st.sampled_from(("singular_homography", "unsupported_distortion", "inverse_mismatch")))
    if degeneration == "singular_homography":
        return replace(calibration, homography=((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    if degeneration == "unsupported_distortion":
        return replace(calibration, distortion=(0.0, 0.0, 0.0))
    return replace(calibration, inverse_homography=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))


def poses():
    """Generate bounded centers and unwrapped circular headings, including cardinals."""
    headings = st.one_of(
        st.sampled_from((-2.0 * math.pi, -math.pi, -math.pi / 2.0, 0.0, math.pi / 2.0, math.pi, 2.0 * math.pi)),
        bounded_floats(-4.0 * math.pi, 4.0 * math.pi),
    )
    return st.builds(Pose2D, center_sat_px=st.tuples(
        bounded_floats(-4096.0, 4096.0), bounded_floats(-4096.0, 4096.0)
    ), heading_rad_unwrapped=headings)

@st.composite
def nuisance_cases(draw):
    """Generate finite closed nuisance profiles with values inside bounds/endpoints."""
    names = draw(st.lists(
        st.sampled_from(("length_m", "width_m", "roof_height_m", "delta_z_cam_m")),
        min_size=1,
        max_size=4,
        unique=True,
    ))
    fields = []
    values = []
    for name in names:
        lower = draw(bounded_floats(-2.0, 0.0))
        upper = draw(bounded_floats(max(lower, 0.0), 3.0))
        bounds = ClosedInterval(lower=lower, upper=upper)
        fields.append(NuisanceField(name=name, unit="m", bounds=bounds, scale=1.0))
        values.append((name, draw(bounded_floats(lower, upper))))
    return NuisanceCase(
        profile=NuisanceProfile(version="generated-v1", fields=tuple(fields)),
        values=NuisanceVector(values=tuple(values)),
    )


def nuisance_profiles():
    return nuisance_cases().map(lambda case: case.profile)


def nuisance_vectors():
    return nuisance_cases().map(lambda case: case.values)


@st.composite
def observations(draw, *, image_width: int = 1920, image_height: int = 1080):
    """Generate finite, bounded provider-neutral image observations."""
    labels = draw(st.lists(CUE_LABELS, min_size=1, max_size=4, unique=True))
    observation_id = draw(IDENTIFIERS)
    return ImageObservation(
        observation_id=observation_id,
        pixel=(
            draw(bounded_floats(0.0, float(image_width - 1))),
            draw(bounded_floats(0.0, float(image_height - 1))),
        ),
        confidence=draw(bounded_floats(0.0, 1.0)),
        candidate_labels=tuple(labels),
        provider_key=f"generated:{observation_id}",
    )


def semantic_alternatives():
    """Generate all authorized normal/reversed/heading-pi path combinations."""
    normal = SemanticPathSpec(semantic_path=SemanticPath.NORMAL)
    reversed_path = SemanticPathSpec(
        semantic_path=SemanticPath.REVERSED,
        front_rear_mapping=(("front", "rear"), ("rear", "front")),
    )
    heading_pi = SemanticPathSpec(semantic_path=SemanticPath.HEADING_PI)
    return st.sampled_from((
        (normal,),
        (normal, reversed_path),
        (normal, heading_pi),
        (normal, reversed_path, heading_pi),
    ))


@st.composite
def support_boundaries(draw):
    """Generate exact adjacent values around a positive pixel support boundary."""
    boundary = draw(bounded_floats(1e-3, 100.0))
    return SupportBoundaryCase(
        boundary_px=boundary,
        immediately_below_px=math.nextafter(boundary, -math.inf),
        equal_px=boundary,
        immediately_above_px=math.nextafter(boundary, math.inf),
    )

@st.composite
def track_provenance(draw, *, kind: Optional[TrackKind] = None):
    """Generate bounded genuine or representative pseudo-track provenance."""
    selected_kind = kind or draw(st.sampled_from((TrackKind.REAL, TrackKind.PSEUDO)))
    claimed_id = draw(IDENTIFIERS)
    if selected_kind is TrackKind.REAL:
        frame_count = draw(st.integers(min_value=2, max_value=8))
        return TrackProvenance(
            claimed_id=claimed_id,
            tracker_name="bytetrack",
            tracker_version="1.0",
            source_sequence="sequence-1",
            association_provenance="tracker-output",
            observed_frames=tuple(f"frame-{index}" for index in range(frame_count)),
            kind=TrackKind.REAL,
        )
    pseudo_case = draw(st.sampled_from(("frame_local_500", "missing_tracker", "one_frame")))
    if pseudo_case == "frame_local_500":
        claimed_id = str(draw(st.integers(min_value=500, max_value=999)))
    return TrackProvenance(
        claimed_id=claimed_id,
        tracker_name=None if pseudo_case == "missing_tracker" else "bytetrack",
        tracker_version=None if pseudo_case == "missing_tracker" else "1.0",
        source_sequence="sequence-1",
        association_provenance="frame-local" if pseudo_case == "frame_local_500" else "tracker-output",
        observed_frames=("frame-0",),
        kind=TrackKind.PSEUDO,
        reason=pseudo_case,
    )


@st.composite
def populations(draw):
    """Generate small site-isolated populations with whole deterministic partitions."""
    site = draw(SITES)
    count = draw(st.integers(min_value=1, max_value=12))
    eligible_ids = tuple(f"{site}:detection-{index}" for index in range(count))
    split = draw(st.integers(min_value=0, max_value=count))
    partitions = (
        PopulationPartition(
            partition_id=f"{site}:pilot",
            kind=PartitionKind.PILOT,
            eligible_detection_ids=eligible_ids[:split],
        ),
        PopulationPartition(
            partition_id=f"{site}:held-out",
            kind=PartitionKind.HELD_OUT,
            eligible_detection_ids=eligible_ids[split:],
        ),
    )
    return PilotPopulation(
        site=site,
        frozen_eligible_ids=eligible_ids,
        ground_truth_group_ids=tuple(f"{site}:gt-{index}" for index in range(count)),
        real_track_ids=tuple(f"{site}:track-{index}" for index in range(max(1, count // 2))),
        source_sequences=(f"{site}:sequence-0",),
        independent_views=(f"{site}:view-0",),
        partitions=partitions,
    )


def _site_decision(site: str, status: DecisionStatus) -> SiteDecision:
    return SiteDecision(
        site=site,
        status=status,
        evidence_gaps=("insufficient_tracks",) if status is DecisionStatus.INSUFFICIENT_DATA else (),
        failed_conditions=("threshold_failed",) if status is DecisionStatus.NO_GO else (),
    )

@st.composite
def decisions(draw):
    """Generate all dual-site statuses with frozen no-go/insufficient/go precedence."""
    kee_status = draw(st.sampled_from(tuple(DecisionStatus)))
    taoyuan_status = draw(st.sampled_from(tuple(DecisionStatus)))
    statuses = (kee_status, taoyuan_status)
    if DecisionStatus.NO_GO in statuses:
        overall = DecisionStatus.NO_GO
    elif DecisionStatus.INSUFFICIENT_DATA in statuses:
        overall = DecisionStatus.INSUFFICIENT_DATA
    else:
        overall = DecisionStatus.GO
    kee = _site_decision("kee-cc", kee_status)
    taoyuan = _site_decision("taoyuan-tc", taoyuan_status)
    return PilotDecision(
        kee_cc=kee,
        taoyuan_tc=taoyuan,
        overall=overall,
        evidence_gaps=kee.evidence_gaps + taoyuan.evidence_gaps,
        failed_conditions=kee.failed_conditions + taoyuan.failed_conditions,
        profile_identity=ZERO_IDENTITY,
        run_identities=(),
    )


@st.composite
def evidence_gate_decisions(draw):
    """Generate bounded decisions for one explicitly named deferred capability."""
    return EvidenceGateDecision(
        capability=draw(st.sampled_from(("detector_retraining", "calibration_identification", "temporal_fusion"))),
        status=draw(st.sampled_from(tuple(DecisionStatus))),
        measured_limitation=draw(IDENTIFIERS),
        expected_benefit=draw(IDENTIFIERS),
        estimated_cost=draw(IDENTIFIERS),
        safety_risk=draw(IDENTIFIERS),
        acceptance_changes=tuple(draw(st.lists(IDENTIFIERS, min_size=0, max_size=3, unique=True))),
    )


@st.composite
def observation_records(draw):
    """Generate bounded normalized records with unique observation identities."""
    generated = draw(st.lists(
        observations(),
        min_size=1,
        max_size=12,
        unique_by=lambda item: item.observation_id,
    ))
    site = draw(SITES)
    return ObservationRecord(
        site=site,
        source_sequence=f"{site}:sequence-0",
        frame_id=draw(IDENTIFIERS),
        detection_id=draw(IDENTIFIERS),
        image_size_px=(1920, 1080),
        observations=tuple(generated),
        provider=ProviderProvenance(
            provider_name="generated",
            provider_version="1.0",
            adapter_version="1.0",
        ),
        source=_source("generated-observation-record"),
        track=draw(st.one_of(st.none(), track_provenance())),
    )
