"""Canonical immutable value models for the Haware localization MVP.

This module intentionally provides only values, validation, and deterministic
serialization.  Replay I/O, optimization, artifact storage, and policy
validation belong to later tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import PurePosixPath
from typing import Any, Mapping, Optional, Sequence


Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Matrix2 = tuple[tuple[float, float], tuple[float, float]]
Matrix3 = tuple[tuple[float, float, float], ...]


class ModelValidationError(ValueError):
    """Raised when an immutable model violates a structural invariant."""


class CueFamily(str, Enum):
    GROUND_CONTACT = "ground_contact"
    WHEEL = "wheel"
    GLASS = "glass"
    WINDSHIELD = "windshield"
    ROOF = "roof"
    MIRROR = "mirror"
    OTHER = "other"


class SemanticPath(str, Enum):
    NORMAL = "normal"
    REVERSED = "reversed"
    HEADING_PI = "heading_pi"


class SeedClass(str, Enum):
    WHEEL = "wheel"
    NON_WHEEL = "non_wheel"


class HypothesisState(str, Enum):
    GENERATED = "generated"
    INVALID = "invalid"
    REFINED = "refined"
    SCORED = "scored"
    MERGED = "merged"
    REJECTED = "rejected"
    SELECTED = "selected"
    BUDGET_EXCLUDED = "budget_excluded"


class LocalizationStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TrackKind(str, Enum):
    REAL = "real"
    PSEUDO = "pseudo"


class PartitionKind(str, Enum):
    PILOT = "pilot"
    HELD_OUT = "held_out"


class DecisionStatus(str, Enum):
    GO = "go"
    NO_GO = "no_go"
    INSUFFICIENT_DATA = "insufficient_data"


def _as_tuple(value: Sequence[Any]) -> tuple[Any, ...]:
    return value if isinstance(value, tuple) else tuple(value)


def _as_vec2(value: Sequence[float], name: str) -> Vec2:
    result = tuple(value)
    if len(result) != 2:
        raise ModelValidationError(f"{name} must contain exactly two values")
    return result  # type: ignore[return-value]


def _as_vec3(value: Sequence[float], name: str) -> Vec3:
    result = tuple(value)
    if len(result) != 3:
        raise ModelValidationError(f"{name} must contain exactly three values")
    return result  # type: ignore[return-value]


def _as_matrix(value: Sequence[Sequence[float]], rows: int, cols: int, name: str) -> tuple[tuple[float, ...], ...]:
    result = tuple(tuple(row) for row in value)
    if len(result) != rows or any(len(row) != cols for row in result):
        raise ModelValidationError(f"{name} must have shape {rows}x{cols}")
    return result


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _primitive(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ModelValidationError("canonical mappings require string keys")
        return {key: _primitive(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_primitive(item) for item in value), key=_canonical_sort_key)
    return value


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(_primitive(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_order(values: Sequence[Any], *, unique: bool = False) -> tuple[Any, ...]:
    """Sort a set-like collection by its canonical JSON value.

    Semantic arrays must not call this helper; their caller-provided order is
    intentionally retained.
    """
    ordered = sorted(tuple(values), key=_canonical_sort_key)
    if not unique:
        return tuple(ordered)
    result: list[Any] = []
    previous: Optional[str] = None
    for item in ordered:
        key = _canonical_sort_key(item)
        if key != previous:
            result.append(item)
            previous = key
    return tuple(result)


def _validate_finite(value: Any, path: str = "value") -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ModelValidationError(f"{path} must be finite")
        return
    if isinstance(value, Enum) or value is None or isinstance(value, (str, bytes, bool, int)):
        return
    if is_dataclass(value):
        for item in fields(value):
            _validate_finite(getattr(value, item.name), f"{path}.{item.name}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_finite(item, f"{path}.{key}")
        return
    if isinstance(value, (tuple, list, set, frozenset)):
        for index, item in enumerate(value):
            _validate_finite(item, f"{path}[{index}]")


def canonical_bytes(value: Any) -> bytes:
    """Return canonical finite UTF-8 JSON with exactly one trailing LF."""
    _validate_finite(value)
    return (json.dumps(_primitive(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


@dataclass(frozen=True)
class ContentIdentity:
    digest: str
    algorithm: str = "sha256"

    def __post_init__(self) -> None:
        if self.algorithm != "sha256":
            raise ModelValidationError("only sha256 content identities are supported")
        if len(self.digest) != 64 or any(char not in "0123456789abcdef" for char in self.digest):
            raise ModelValidationError("digest must be 64 lowercase hexadecimal characters")

    @classmethod
    def for_bytes(cls, payload: bytes) -> "ContentIdentity":
        return cls(hashlib.sha256(payload).hexdigest())


@dataclass(frozen=True, kw_only=True)
class CanonicalModel:
    """Base for finite versioned values with deterministic content identity."""

    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.schema_version.strip():
            raise ModelValidationError("schema_version must be non-empty")
        _validate_finite(self)

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self)

    @property
    def content_identity(self) -> ContentIdentity:
        return ContentIdentity.for_bytes(self.canonical_bytes())

    def canonical_envelope(self) -> dict[str, Any]:
        """Return the persisted value alongside its non-self-referential identity."""
        return {
            "content_identity": _primitive(self.content_identity),
            "value": _primitive(self),
        }


@dataclass(frozen=True, kw_only=True)
class ClosedInterval(CanonicalModel):
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ModelValidationError("closed interval lower bound exceeds upper bound")
        super().__post_init__()

    def contains(self, value: float) -> bool:
        return math.isfinite(value) and self.lower <= value <= self.upper


@dataclass(frozen=True, kw_only=True)
class GaussianPrior(CanonicalModel):
    mean: float
    standard_deviation: float

    def __post_init__(self) -> None:
        if self.standard_deviation <= 0:
            raise ModelValidationError("prior standard deviation must be positive")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ProviderProvenance(CanonicalModel):
    provider_name: str
    provider_version: str
    adapter_version: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.provider_name, self.provider_version, self.adapter_version)):
            raise ModelValidationError("provider provenance fields must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class SourceProvenance(CanonicalModel):
    source_id: str
    repository_relative_path: Optional[str]
    source_content_identity: ContentIdentity

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ModelValidationError("source_id must be non-empty")
        if self.repository_relative_path is not None:
            path = PurePosixPath(self.repository_relative_path)
            if path.is_absolute() or ".." in path.parts or str(path) in ("", "."):
                raise ModelValidationError("source path must be repository-relative and normalized")
            if str(path) != self.repository_relative_path:
                raise ModelValidationError("source path must use normalized POSIX form")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class TrackProvenance(CanonicalModel):
    claimed_id: str
    tracker_name: Optional[str]
    tracker_version: Optional[str]
    source_sequence: Optional[str]
    association_provenance: Optional[str]
    observed_frames: tuple[str, ...]
    kind: TrackKind
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_frames", canonical_order(self.observed_frames, unique=True))
        if not self.claimed_id.strip():
            raise ModelValidationError("claimed track id must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ImageObservation(CanonicalModel):
    observation_id: str
    pixel: Vec2
    confidence: float
    candidate_labels: tuple[str, ...]
    provider_key: str
    covariance_px2: Optional[Matrix2] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "pixel", _as_vec2(self.pixel, "pixel"))
        object.__setattr__(self, "candidate_labels", canonical_order(self.candidate_labels, unique=True))
        if self.covariance_px2 is not None:
            object.__setattr__(self, "covariance_px2", _as_matrix(self.covariance_px2, 2, 2, "covariance_px2"))
        if not self.observation_id.strip() or not self.provider_key.strip():
            raise ModelValidationError("observation identities must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ModelValidationError("confidence must be in [0, 1]")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ObservationRecord(CanonicalModel):
    site: str
    source_sequence: str
    frame_id: str
    detection_id: str
    image_size_px: tuple[int, int]
    observations: tuple[ImageObservation, ...]
    provider: ProviderProvenance
    source: SourceProvenance
    track: Optional[TrackProvenance] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "image_size_px", tuple(self.image_size_px))
        object.__setattr__(self, "observations", canonical_order(self.observations))
        if len(self.image_size_px) != 2 or any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in self.image_size_px):
            raise ModelValidationError("image_size_px must contain two positive integers")
        if not all(value.strip() for value in (self.site, self.source_sequence, self.frame_id, self.detection_id)):
            raise ModelValidationError("record identity fields must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class CalibrationSnapshot(CanonicalModel):
    version: str
    camera_matrix: Matrix3
    distortion: tuple[float, ...]
    homography: Matrix3
    inverse_homography: Matrix3
    camera_sat_px: Vec2
    camera_height_m: float
    pixels_per_metre: float
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "camera_matrix", _as_matrix(self.camera_matrix, 3, 3, "camera_matrix"))
        object.__setattr__(self, "distortion", tuple(self.distortion))
        object.__setattr__(self, "homography", _as_matrix(self.homography, 3, 3, "homography"))
        object.__setattr__(self, "inverse_homography", _as_matrix(self.inverse_homography, 3, 3, "inverse_homography"))
        object.__setattr__(self, "camera_sat_px", _as_vec2(self.camera_sat_px, "camera_sat_px"))
        if not self.version.strip():
            raise ModelValidationError("calibration version must be non-empty")
        if self.camera_height_m <= 0 or self.pixels_per_metre <= 0:
            raise ModelValidationError("camera height and pixel scale must be positive")
        super().__post_init__()

    @classmethod
    def from_g_projection(
        cls,
        projection: Any,
        *,
        version: Optional[str] = None,
        provenance: Optional[SourceProvenance] = None,
    ) -> "CalibrationSnapshot":
        """Copy a validated immutable snapshot from a mutable GProjection."""
        from trafficlab.projection.haware_forward import calibration_snapshot_from_g_projection

        return calibration_snapshot_from_g_projection(
            projection, version=version, provenance=provenance
        )


@dataclass(frozen=True, kw_only=True)
class VehicleTemplatePoint(CanonicalModel):
    semantic_id: str
    position_m: Vec3
    cue_family: CueFamily

    def __post_init__(self) -> None:
        object.__setattr__(self, "position_m", _as_vec3(self.position_m, "position_m"))
        if not self.semantic_id.strip():
            raise ModelValidationError("template semantic id must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class VehicleTemplate(CanonicalModel):
    version: str
    points: tuple[VehicleTemplatePoint, ...]
    axis_convention: str = "+x=vehicle_left,+y=up,+z=rear"

    def __post_init__(self) -> None:
        object.__setattr__(self, "points", tuple(self.points))  # semantic Apollo order is preserved
        semantic_ids = tuple(point.semantic_id for point in self.points)
        if len(set(semantic_ids)) != len(semantic_ids):
            raise ModelValidationError("template semantic ids must be unique")
        if not self.version.strip() or not self.axis_convention.strip():
            raise ModelValidationError("template version and axis convention must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class Pose2D(CanonicalModel):
    center_sat_px: Vec2
    heading_rad_unwrapped: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "center_sat_px", _as_vec2(self.center_sat_px, "center_sat_px"))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class NuisanceField(CanonicalModel):
    name: str
    unit: str
    bounds: ClosedInterval
    scale: float
    prior: Optional[GaussianPrior] = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.unit.strip():
            raise ModelValidationError("nuisance name and unit must be non-empty")
        if self.scale <= 0:
            raise ModelValidationError("nuisance scale must be positive")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class NuisanceProfile(CanonicalModel):
    version: str
    fields: tuple[NuisanceField, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))  # optimization parameter order is semantic
        names = tuple(item.name for item in self.fields)
        if len(set(names)) != len(names):
            raise ModelValidationError("nuisance field names must be unique")
        if not self.version.strip():
            raise ModelValidationError("nuisance profile version must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class NuisanceVector(CanonicalModel):
    values: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        ordered = canonical_order(tuple((str(name), value) for name, value in self.values))
        if len({name for name, _ in ordered}) != len(ordered):
            raise ModelValidationError("nuisance value names must be unique")
        object.__setattr__(self, "values", ordered)
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class CalibrationProfile(CanonicalModel):
    version: str
    snapshot: CalibrationSnapshot
    authorized_nuisance_fields: tuple[str, ...] = ()
    pre_gate: Optional["PreGateBound"] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorized_nuisance_fields", canonical_order(self.authorized_nuisance_fields, unique=True))
        if not self.version.strip():
            raise ModelValidationError("calibration profile version must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class CueHeightSpec(CanonicalModel):
    cue_family: CueFamily
    height_m: ClosedInterval
    evidence: SourceProvenance


@dataclass(frozen=True, kw_only=True)
class MinimalConfiguration(CanonicalModel):
    configuration_id: str
    cue_families: tuple[CueFamily, ...]
    minimum_support: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "cue_families", canonical_order(self.cue_families, unique=True))
        if not self.configuration_id.strip() or self.minimum_support <= 0:
            raise ModelValidationError("minimal configuration requires an id and positive support")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class CueEvidenceProfile(CanonicalModel):
    version: str
    site: str
    view: str
    semantic_mappings: tuple[tuple[str, str], ...]
    height_specs: tuple[CueHeightSpec, ...]
    minimal_configurations: tuple[MinimalConfiguration, ...]
    provenance: tuple[SourceProvenance, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_mappings", canonical_order(self.semantic_mappings, unique=True))
        object.__setattr__(self, "height_specs", canonical_order(self.height_specs))
        object.__setattr__(self, "minimal_configurations", canonical_order(self.minimal_configurations))
        object.__setattr__(self, "provenance", canonical_order(self.provenance, unique=True))
        if not all(value.strip() for value in (self.version, self.site, self.view)):
            raise ModelValidationError("cue evidence identity fields must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class SemanticPathSpec(CanonicalModel):
    semantic_path: SemanticPath
    front_rear_mapping: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "front_rear_mapping", canonical_order(self.front_rear_mapping, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class RobustSettings(CanonicalModel):
    loss: str
    loss_scale: float
    support_boundary_px: float
    support_includes_equality: bool
    outlier_penalty: float
    nuisance_penalty: float


@dataclass(frozen=True, kw_only=True)
class LeastSquaresSettings(CanonicalModel):
    method: str
    max_evaluations: int
    ftol: float
    xtol: float
    gtol: float
    finite_difference_step: float
    parameter_scale: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_scale", tuple(self.parameter_scale))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ObservabilitySettings(CanonicalModel):
    jacobian_version: str
    curvature_version: str
    rank_tolerance: float
    minimum_rank: int
    condition_rejection_boundary: float
    position_uncertainty_boundary_m: float
    heading_uncertainty_boundary_rad: float


@dataclass(frozen=True, kw_only=True)
class PoseEquivalenceSettings(CanonicalModel):
    position_tolerance_m: float
    heading_tolerance_rad: float
    prediction_tolerance_px: float


@dataclass(frozen=True, kw_only=True)
class AmbiguitySettings(CanonicalModel):
    equal_score_tolerance: float
    margin_absolute: float
    margin_ratio: Optional[float]


@dataclass(frozen=True, kw_only=True)
class OptimizerProfile(CanonicalModel):
    version: str
    hypothesis_budget: int
    sampled_candidate_budget: int
    retained_candidate_count: int
    minimal_configurations: tuple[MinimalConfiguration, ...]
    semantic_paths: tuple[SemanticPathSpec, ...]
    robust: RobustSettings
    optimizer: LeastSquaresSettings
    observability: ObservabilitySettings
    equivalence: PoseEquivalenceSettings
    ambiguity: AmbiguitySettings
    rejection_precedence: tuple[str, ...]
    deterministic_seed: int
    spread_rejection_boundary_m: Optional[float] = 8.0
    validity_gate_set: tuple[str, ...] = ("support", "non_finite", "convergence")
    wheel_seeded_enabled: bool = True
    non_wheel_seeded_enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimal_configurations", canonical_order(self.minimal_configurations))
        object.__setattr__(self, "semantic_paths", canonical_order(self.semantic_paths))
        object.__setattr__(self, "rejection_precedence", tuple(self.rejection_precedence))  # precedence is semantic
        object.__setattr__(self, "validity_gate_set", tuple(self.validity_gate_set))  # order is semantic
        if not self.version.strip():
            raise ModelValidationError("optimizer profile version must be non-empty")
        if not self.validity_gate_set:
            raise ModelValidationError("validity_gate_set must name at least one gate")
        if not (self.wheel_seeded_enabled or self.non_wheel_seeded_enabled):
            raise ModelValidationError("at least one seed class must stay enabled")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ReplayContract(CanonicalModel):
    version: str
    maximum_observations: int
    maximum_labels_per_observation: int
    maximum_string_length: int
    confidence_bounds: ClosedInterval


@dataclass(frozen=True, kw_only=True)
class PreGateBound(CanonicalModel):
    """A frozen pre-localization observability bound (Requirement 1.23).

    ``1/k = z_cam / (z_cam - h)`` is a function of keypoint HEIGHT, not image
    position, so a near-horizon bound is either an image-row cut or a
    magnification cut; it has no spatial maximum over a region.
    """

    kind: str
    bound: float

    def __post_init__(self) -> None:
        if self.kind not in ("image_row", "inv_k"):
            raise ModelValidationError("pre-gate kind must be 'image_row' or 'inv_k'")
        if not math.isfinite(self.bound) or self.bound <= 0.0:
            raise ModelValidationError("pre-gate bound must be finite and positive")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class SceneExportSettings(CanonicalModel):
    """Bounds the scene builder applies (Requirements 7.18-7.19)."""

    max_gap_frames: int = 5
    min_accepted_share: float = 0.5

    def __post_init__(self) -> None:
        if self.max_gap_frames < 0:
            raise ModelValidationError("max_gap_frames must be non-negative")
        if not 0.0 <= self.min_accepted_share <= 1.0:
            raise ModelValidationError("min_accepted_share must lie in [0, 1]")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ReferenceMachine(CanonicalModel):
    """Enough identity to reproduce a runtime measurement (Requirement 13.1)."""

    cpu_model: str
    cores: int
    ram_gb: float
    os_version: str
    python_version: str
    numpy_version: str
    scipy_version: str
    blas: str
    thread_env: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "thread_env", canonical_order(tuple(tuple(pair) for pair in self.thread_env), unique=True))
        if self.cores <= 0 or self.ram_gb <= 0:
            raise ModelValidationError("reference machine cores and RAM must be positive")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class LegacyStatusPolicy(CanonicalModel):
    version: str
    accepted_statuses: tuple[str, ...]
    rejected_statuses: tuple[str, ...]
    unknown_status_reason: str = "legacy_status_evidence_insufficient"
    rejection_reasons: tuple[tuple[str, str], ...] = ()
    null_diagnostic_statuses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_statuses", canonical_order(self.accepted_statuses, unique=True))
        object.__setattr__(self, "rejected_statuses", canonical_order(self.rejected_statuses, unique=True))
        object.__setattr__(self, "rejection_reasons", canonical_order(tuple(tuple(pair) for pair in self.rejection_reasons), unique=True))
        object.__setattr__(self, "null_diagnostic_statuses", canonical_order(self.null_diagnostic_statuses, unique=True))
        if not self.unknown_status_reason.strip():
            raise ModelValidationError("unknown_status_reason must be non-empty")
        seen: set[str] = set()
        for pair in self.rejection_reasons:
            if len(pair) != 2 or not all(isinstance(item, str) and item.strip() for item in pair):
                raise ModelValidationError("rejection_reasons must be (status, reason) string pairs")
            if pair[0] in seen:
                raise ModelValidationError(f"rejection_reasons maps {pair[0]!r} more than once")
            seen.add(pair[0])
        super().__post_init__()

    def rejection_reason_for(self, status: Any) -> str:
        """Return the frozen decisive reason for a legacy status.

        The record's own ``reason`` never participates: an upstream string must
        not be able to rename a frozen gate.
        """
        for mapped_status, reason in self.rejection_reasons:
            if mapped_status == status:
                return reason
        if isinstance(status, str) and status in self.rejected_statuses:
            return status
        return self.unknown_status_reason

    def retains_diagnostic_position(self, status: Any) -> bool:
        return status not in self.null_diagnostic_statuses


@dataclass(frozen=True, kw_only=True)
class PilotPolicy(CanonicalModel):
    version: str
    confidence_level: float
    cluster_unit: str
    power_method: str
    sufficiency_rule_version: str
    metric_definition_version: str
    diagnostic_candidates: tuple[str, ...] = ()
    # Tuple-of-pairs rather than a Mapping: a dict field makes the frozen model
    # unhashable and _primitive() only canonicalizes string-keyed mappings.
    diagnostic_candidate_params: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = ()
    interval_method: str = "whole_track_cluster_bootstrap_v1"
    minimum_valid_clusters: int = 8
    resample_budget: int = 4096
    alpha: float = 0.05
    target_power: float = 0.80
    minimum_effect_of_interest: tuple[tuple[str, float], ...] = (
        ("coverage", 0.05),
        ("median_error_m", 0.5),
        ("p90_error_m", 1.0),
    )
    position_ambiguity_tolerance_m: float = 0.25
    scene_region_bands_m: tuple[float, ...] = (15.0, 30.0)
    source_sequence_buffer_frames: int = 60
    calibration_perturbation_set: str = "nominal+endpoints+sobol256_v1"
    held_out_threshold_rule: str = "pilot_upper_bound_v1"
    health_kp_conf: float = 0.20
    calibration_health: tuple[tuple[str, float], ...] = (
        ("max_inv_k", 1.6),
        ("max_zcam_rel_inconsistency", 0.25),
        ("min_in_band_fraction", 0.40),
        ("track_width_hi_m", 3.2),
        ("track_width_lo_m", 2.0),
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum_effect_of_interest", canonical_order(tuple((k, float(v)) for k, v in self.minimum_effect_of_interest), unique=True))
        object.__setattr__(self, "calibration_health", canonical_order(tuple((k, float(v)) for k, v in self.calibration_health), unique=True))
        object.__setattr__(self, "scene_region_bands_m", tuple(float(edge) for edge in self.scene_region_bands_m))  # order is semantic
        object.__setattr__(self, "diagnostic_candidates", canonical_order(self.diagnostic_candidates, unique=True))
        normalized = tuple(
            (name, tuple((key, float(value)) for key, value in canonical_order(params, unique=True)))
            for name, params in self.diagnostic_candidate_params
        )
        object.__setattr__(self, "diagnostic_candidate_params", canonical_order(normalized, unique=True))
        named = {name for name, _ in self.diagnostic_candidate_params}
        missing = set(self.diagnostic_candidates) - named
        if missing:
            raise ModelValidationError(f"diagnostic candidates lack frozen parameters: {sorted(missing)}")
        unknown = named - set(self.diagnostic_candidates)
        if unknown:
            raise ModelValidationError(f"parameters declared for unnamed candidates: {sorted(unknown)}")
        # `pilot-stats-v1` is one method: exact sign-flip was removed because
        # inverting it into an interval is undefined (design section 8).
        if self.interval_method != "whole_track_cluster_bootstrap_v1":
            raise ModelValidationError("the frozen interval method is whole_track_cluster_bootstrap_v1")
        if self.minimum_valid_clusters < 8:
            raise ModelValidationError("the cluster-bootstrap validity floor is 8 clusters per effect")
        if self.resample_budget < 1000:
            raise ModelValidationError("resample budget must be at least 1000")
        median_mei = self.minimum_effect_of_interest_for("median_error_m")
        if self.position_ambiguity_tolerance_m > median_mei / 2.0:
            raise ModelValidationError("position ambiguity tolerance must not exceed half the median-error MEI")
        if list(self.scene_region_bands_m) != sorted(self.scene_region_bands_m):
            raise ModelValidationError("scene_region band edges must ascend")
        super().__post_init__()

    def minimum_effect_of_interest_for(self, effect: str) -> float:
        for name, value in self.minimum_effect_of_interest:
            if name == effect:
                return value
        raise KeyError(effect)

    def parameters_for(self, candidate: str) -> dict[str, float]:
        for name, params in self.diagnostic_candidate_params:
            if name == candidate:
                return {key: value for key, value in params}
        raise KeyError(candidate)


@dataclass(frozen=True, kw_only=True)
class AcceptanceProfile(CanonicalModel):
    profile_id: str
    calibration: CalibrationProfile
    cue_evidence: CueEvidenceProfile
    nuisance: NuisanceProfile
    optimizer: OptimizerProfile
    replay_contract: ReplayContract
    legacy_status_policy: LegacyStatusPolicy
    pilot_policy: PilotPolicy
    acceptance_sites: tuple[str, ...] = ("kee-cc", "taoyuan-tc")
    candidate_site_pool: tuple[str, ...] = ("kee-cc", "taoyuan-tc")
    scene_export: SceneExportSettings = field(default_factory=SceneExportSettings)
    batch_runtime_envelope_s_per_s: float = 10.0
    reference_machine: Optional[ReferenceMachine] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.batch_runtime_envelope_s_per_s) or self.batch_runtime_envelope_s_per_s <= 0:
            raise ModelValidationError("the batch runtime envelope must be finite and positive")
        object.__setattr__(self, "acceptance_sites", canonical_order(self.acceptance_sites, unique=True))
        object.__setattr__(self, "candidate_site_pool", canonical_order(self.candidate_site_pool, unique=True))
        if len(self.acceptance_sites) != 2:
            raise ModelValidationError("exactly two acceptance sites must be named")
        outside = set(self.acceptance_sites) - set(self.candidate_site_pool)
        if outside:
            raise ModelValidationError(f"acceptance sites outside the frozen pool: {sorted(outside)}")
        if "taipei-cm" in self.candidate_site_pool:
            raise ModelValidationError("taipei-cm is permanently ineligible as an acceptance site")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class Correspondence(CanonicalModel):
    observation_id: str
    template_semantic_id: str
    candidate_label_provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_label_provenance", canonical_order(self.candidate_label_provenance, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class InitializationSource(CanonicalModel):
    method: str
    observation_ids: tuple[str, ...]
    source_cell: Optional[str] = None
    start_heading_rad: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_ids", canonical_order(self.observation_ids, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class HypothesisPath(CanonicalModel):
    path_id: str
    semantic_path: SemanticPath
    correspondence: tuple[Correspondence, ...]
    cue_subset: tuple[CueFamily, ...]
    seed_class: SeedClass
    minimal_observations: tuple[str, ...]
    initialization_source: InitializationSource
    terminal_state: HypothesisState = HypothesisState.GENERATED
    terminal_reason: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "correspondence", canonical_order(self.correspondence))
        object.__setattr__(self, "cue_subset", canonical_order(self.cue_subset, unique=True))
        object.__setattr__(self, "minimal_observations", canonical_order(self.minimal_observations, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PoseSeed(CanonicalModel):
    pose: Pose2D
    nuisance: NuisanceVector
    path_id: str
    generation_ordinal: int


@dataclass(frozen=True, kw_only=True)
class ProjectionPrediction(CanonicalModel):
    observation_id: str
    template_semantic_id: str
    pixel: Vec2
    valid: bool
    failure_reason: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "pixel", _as_vec2(self.pixel, "pixel"))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ResidualDiagnostic(CanonicalModel):
    observation_id: str
    residual_px: Vec2
    magnitude_px: float
    in_support: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "residual_px", _as_vec2(self.residual_px, "residual_px"))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class NuisanceTreatmentDiagnostics(CanonicalModel):
    """Frozen bound/prior treatment for one varied nuisance coordinate."""

    name: str
    role: str
    unit: str
    bounds: ClosedInterval
    prior: Optional[GaussianPrior]
    interval_treatment: str
    prior_treatment: str
    uncertainty_propagation: str
    prior_precision_scaled: float

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.unit.strip():
            raise ModelValidationError("nuisance treatment identity must be non-empty")
        if self.role not in {"height", "dimension", "calibration"}:
            raise ModelValidationError("nuisance treatment role is unsupported")
        if self.interval_treatment != "finite_closed_interval":
            raise ModelValidationError("nuisance interval treatment must remain frozen")
        if self.prior_treatment not in {
            "none", "gaussian_quadratic", "disabled_zero_weight"
        }:
            raise ModelValidationError("nuisance prior treatment is unsupported")
        if self.uncertainty_propagation != "jacobian_schur_marginalized":
            raise ModelValidationError("nuisance uncertainty propagation must remain frozen")
        if self.prior is None and self.prior_treatment != "none":
            raise ModelValidationError("prior-free nuisance must report no prior treatment")
        if self.prior is not None and self.prior_treatment == "none":
            raise ModelValidationError("configured nuisance prior requires explicit treatment")
        if self.prior_precision_scaled < 0.0:
            raise ModelValidationError("nuisance prior precision must be nonnegative")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ObservabilityDiagnostics(CanonicalModel):
    """Frozen robust local-curvature diagnostics for one converged fit.

    Jacobian and information values use the profile's scaled parameter
    coordinates. Pose covariance and its derived uncertainty values are
    converted back to physical ``(metres, metres, radians)`` units.
    """

    jacobian_version: str
    singular_values: tuple[float, ...]
    rank: int
    # None at rank zero: with no retained direction there is no ratio to report,
    # and a sentinel equal to the rejection boundary would make the conditioning
    # gate self-fulfilling (Requirement 6.34).
    condition: Optional[float]
    information_pose: Matrix3
    covariance_pose: Matrix3
    position_ellipse_95_m: Vec2
    heading_uncertainty_rad: float
    active_bounds: tuple[str, ...] = ()
    curvature_version: str = ""
    parameter_names: tuple[str, ...] = ()
    parameter_units: tuple[str, ...] = ()
    parameter_scales: tuple[float, ...] = ()
    image_residual_jacobian_scaled: tuple[tuple[float, ...], ...] = ()
    robust_weights: tuple[float, ...] = ()
    information_scaled: tuple[tuple[float, ...], ...] = ()
    nuisance_prior_precision_scaled: tuple[float, ...] = ()
    nuisance_treatments: tuple[NuisanceTreatmentDiagnostics, ...] = ()
    residual_variance: float = 0.0
    residual_degrees_of_freedom: int = 0
    derivative_schemes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "singular_values", tuple(self.singular_values))
        object.__setattr__(self, "information_pose", _as_matrix(self.information_pose, 3, 3, "information_pose"))
        object.__setattr__(self, "covariance_pose", _as_matrix(self.covariance_pose, 3, 3, "covariance_pose"))
        object.__setattr__(self, "position_ellipse_95_m", _as_vec2(self.position_ellipse_95_m, "position_ellipse_95_m"))
        object.__setattr__(self, "active_bounds", canonical_order(self.active_bounds, unique=True))
        object.__setattr__(self, "parameter_names", tuple(self.parameter_names))
        object.__setattr__(self, "parameter_units", tuple(self.parameter_units))
        object.__setattr__(self, "parameter_scales", tuple(self.parameter_scales))
        object.__setattr__(self, "image_residual_jacobian_scaled", tuple(tuple(row) for row in self.image_residual_jacobian_scaled))
        object.__setattr__(self, "robust_weights", tuple(self.robust_weights))
        object.__setattr__(self, "information_scaled", tuple(tuple(row) for row in self.information_scaled))
        object.__setattr__(self, "nuisance_prior_precision_scaled", tuple(self.nuisance_prior_precision_scaled))
        object.__setattr__(self, "nuisance_treatments", tuple(self.nuisance_treatments))
        object.__setattr__(self, "derivative_schemes", tuple(tuple(item) for item in self.derivative_schemes))
        count = len(self.parameter_names)
        if self.rank < 0 or self.residual_degrees_of_freedom < 0:
            raise ModelValidationError("observability ranks and degrees of freedom must be nonnegative")
        if count:
            aligned = (
                len(self.parameter_units), len(self.parameter_scales),
                len(self.nuisance_prior_precision_scaled), len(self.information_scaled),
                len(self.derivative_schemes),
            )
            if any(value != count for value in aligned):
                raise ModelValidationError("observability parameter diagnostics must align")
            if len(set(self.parameter_names)) != count or any(scale <= 0.0 for scale in self.parameter_scales):
                raise ModelValidationError("observability parameter names and scales are invalid")
            if any(len(row) != count for row in self.image_residual_jacobian_scaled):
                raise ModelValidationError("image residual Jacobian has the wrong column count")
            if len(self.robust_weights) != len(self.image_residual_jacobian_scaled):
                raise ModelValidationError("robust weights must align with image residual rows")
            if any(len(row) != count for row in self.information_scaled):
                raise ModelValidationError("scaled information matrix must be square")
            if tuple(name for name, _scheme in self.derivative_schemes) != self.parameter_names:
                raise ModelValidationError("derivative diagnostics must preserve parameter order")
            treatment_names = tuple(item.name for item in self.nuisance_treatments)
            if len(set(treatment_names)) != len(treatment_names):
                raise ModelValidationError("nuisance treatment names must be unique")
            if any(name not in self.parameter_names[3:] for name in treatment_names):
                raise ModelValidationError("nuisance treatment must identify a nuisance parameter")
            precision_by_name = dict(zip(self.parameter_names, self.nuisance_prior_precision_scaled))
            if any(
                not math.isclose(
                    item.prior_precision_scaled,
                    precision_by_name[item.name],
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
                for item in self.nuisance_treatments
            ):
                raise ModelValidationError("nuisance treatment prior precision is inconsistent")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class RefinedHypothesis(CanonicalModel):
    path: HypothesisPath
    pose: Pose2D
    nuisance: NuisanceVector
    predictions: tuple[ProjectionPrediction, ...]
    residuals: tuple[ResidualDiagnostic, ...]
    support_observation_ids: tuple[str, ...]
    score: float
    converged: bool
    observability: Optional[ObservabilityDiagnostics]
    failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "predictions", canonical_order(self.predictions))
        object.__setattr__(self, "residuals", canonical_order(self.residuals))
        object.__setattr__(self, "support_observation_ids", canonical_order(self.support_observation_ids, unique=True))
        object.__setattr__(self, "failures", canonical_order(self.failures, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class HypothesisGenerationReport(CanonicalModel):
    authorized_paths: tuple[HypothesisPath, ...]
    generated_paths: tuple[HypothesisPath, ...]
    budget_exclusions: tuple[HypothesisPath, ...]
    stable_order: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorized_paths", canonical_order(self.authorized_paths))
        object.__setattr__(self, "generated_paths", tuple(self.generated_paths))  # generation order is semantic
        object.__setattr__(self, "budget_exclusions", canonical_order(self.budget_exclusions))
        object.__setattr__(self, "stable_order", tuple(self.stable_order))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class RunIdentity(CanonicalModel):
    replay: ContentIdentity
    profile: ContentIdentity
    template: ContentIdentity
    calibration: ContentIdentity
    cue_evidence: ContentIdentity
    nuisance: ContentIdentity
    code_revision: str
    runtime_dependencies: tuple[ContentIdentity, ...]
    deterministic_seed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_dependencies", canonical_order(self.runtime_dependencies, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class LocalizationDiagnostics(CanonicalModel):
    normalized_observations: tuple[ImageObservation, ...] = ()
    exclusions: tuple[str, ...] = ()
    paths: tuple[HypothesisPath, ...] = ()
    merged_components: tuple[tuple[str, ...], ...] = ()
    selected_path: Optional[str] = None
    hypothesis_margin: Optional[float] = None
    spread_m: Optional[float] = None
    gate_failures: tuple[str, ...] = ()
    run_identity: Optional[RunIdentity] = None
    legacy_policy_version: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_observations", canonical_order(self.normalized_observations))
        object.__setattr__(self, "exclusions", canonical_order(self.exclusions, unique=True))
        object.__setattr__(self, "paths", canonical_order(self.paths))
        components = tuple(canonical_order(component, unique=True) for component in self.merged_components)
        object.__setattr__(self, "merged_components", canonical_order(components, unique=True))
        object.__setattr__(self, "gate_failures", canonical_order(self.gate_failures, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class LocalizationResult(CanonicalModel):
    status: LocalizationStatus
    usable: bool
    authoritative_position_sat_px: Optional[Vec2]
    diagnostic_position_sat_px: Optional[Vec2]
    heading_deg: Optional[float]
    decisive_gate: str
    reason: Optional[str]
    heading_status: Optional[str] = None
    diagnostics: LocalizationDiagnostics = field(default_factory=LocalizationDiagnostics)

    def __post_init__(self) -> None:
        if self.authoritative_position_sat_px is not None:
            object.__setattr__(self, "authoritative_position_sat_px", _as_vec2(self.authoritative_position_sat_px, "authoritative_position_sat_px"))
        if self.diagnostic_position_sat_px is not None:
            object.__setattr__(self, "diagnostic_position_sat_px", _as_vec2(self.diagnostic_position_sat_px, "diagnostic_position_sat_px"))
        accepted = self.status is LocalizationStatus.ACCEPTED
        if accepted:
            if not self.usable or self.authoritative_position_sat_px is None or self.diagnostic_position_sat_px is not None:
                raise ModelValidationError("accepted results require usable finite authority with no diagnostic position")
            if self.heading_deg is None and self.heading_status is None:
                raise ModelValidationError("an accepted result without a heading must record a heading_status")
            if self.reason is not None:
                raise ModelValidationError("accepted results cannot have a rejection reason")
        else:
            if self.usable or self.authoritative_position_sat_px is not None:
                raise ModelValidationError("rejected results must be unusable and have no authoritative position")
            if not self.reason:
                raise ModelValidationError("rejected results require a machine-readable reason")
        if not self.decisive_gate.strip():
            raise ModelValidationError("decisive_gate must be non-empty")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class GroundTruthRecord(CanonicalModel):
    site: str
    frame_id: str
    detection_id: str
    real_track_id: str
    reference_point: str
    metric_coordinate_m: Vec2
    calibration_identity: ContentIdentity
    source: SourceProvenance
    annotator_provenance: str
    independence_attestation: str
    uncertainty_m: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_coordinate_m", _as_vec2(self.metric_coordinate_m, "metric_coordinate_m"))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PopulationPartition(CanonicalModel):
    partition_id: str
    kind: PartitionKind
    eligible_detection_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "eligible_detection_ids", canonical_order(self.eligible_detection_ids, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PilotPopulation(CanonicalModel):
    site: str
    frozen_eligible_ids: tuple[str, ...]
    ground_truth_group_ids: tuple[str, ...]
    real_track_ids: tuple[str, ...]
    source_sequences: tuple[str, ...]
    independent_views: tuple[str, ...]
    partitions: tuple[PopulationPartition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "frozen_eligible_ids", canonical_order(self.frozen_eligible_ids, unique=True))
        object.__setattr__(self, "ground_truth_group_ids", canonical_order(self.ground_truth_group_ids, unique=True))
        object.__setattr__(self, "real_track_ids", canonical_order(self.real_track_ids, unique=True))
        object.__setattr__(self, "source_sequences", canonical_order(self.source_sequences, unique=True))
        object.__setattr__(self, "independent_views", canonical_order(self.independent_views, unique=True))
        object.__setattr__(self, "partitions", canonical_order(self.partitions))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class EffectInterval(CanonicalModel):
    lower: float
    upper: float
    confidence_level: float
    method: str


@dataclass(frozen=True, kw_only=True)
class PilotSiteReport(CanonicalModel):
    site: str
    configuration: str
    accepted_count: int
    rejected_count: int
    median_error_m: Optional[float]
    p90_error_m: Optional[float]
    usable_coverage: float
    signed_effects: tuple[tuple[str, float], ...]
    effect_intervals: tuple[tuple[str, EffectInterval], ...]
    genuine_track_count: int
    view_coverage: tuple[tuple[str, float], ...]
    ground_truth_uncertainty_m: tuple[float, ...]
    sufficiency: DecisionStatus
    power: Optional[float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "signed_effects", canonical_order(self.signed_effects))
        object.__setattr__(self, "effect_intervals", canonical_order(self.effect_intervals))
        object.__setattr__(self, "view_coverage", canonical_order(self.view_coverage))
        object.__setattr__(self, "ground_truth_uncertainty_m", tuple(self.ground_truth_uncertainty_m))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class SiteDecision(CanonicalModel):
    site: str
    status: DecisionStatus
    evidence_gaps: tuple[str, ...] = ()
    failed_conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_gaps", canonical_order(self.evidence_gaps, unique=True))
        object.__setattr__(self, "failed_conditions", canonical_order(self.failed_conditions, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PilotDecision(CanonicalModel):
    kee_cc: SiteDecision
    taoyuan_tc: SiteDecision
    overall: DecisionStatus
    evidence_gaps: tuple[str, ...]
    failed_conditions: tuple[str, ...]
    profile_identity: ContentIdentity
    run_identities: tuple[RunIdentity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_gaps", canonical_order(self.evidence_gaps, unique=True))
        object.__setattr__(self, "failed_conditions", canonical_order(self.failed_conditions, unique=True))
        object.__setattr__(self, "run_identities", canonical_order(self.run_identities, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class EvidenceGateDecision(CanonicalModel):
    capability: str
    status: DecisionStatus
    measured_limitation: str
    expected_benefit: str
    estimated_cost: str
    safety_risk: str
    acceptance_changes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "acceptance_changes", canonical_order(self.acceptance_changes, unique=True))
        super().__post_init__()
