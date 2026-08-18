"""Fail-fast acceptance-profile and MVP scope validation.

Validation in this module is deliberately outcome-blind.  Replay readers and
pilot outcome loaders receive a :class:`ValidatedProfile` only after all
configuration, geometry, determinism, and scope checks have succeeded.
"""
from __future__ import annotations

from dataclasses import fields as dc_fields, is_dataclass, dataclass
import math
from typing import Any, Mapping, Optional, Sequence

from .models import (
    AcceptanceProfile,
    CanonicalModel,
    ContentIdentity,
    CueFamily,
    DecisionStatus,
    SiteDecision,
    canonical_order,
)


ACCEPTANCE_SITES = ("kee-cc", "taoyuan-tc")
DIAGNOSTIC_SITES = ("taipei-cm",)
SUPPORTED_DISTORTION_LENGTHS = frozenset((0, 4, 5, 8, 12, 14))
REQUIRED_GATE_PRECEDENCE = (
    "insufficient_support",
    "non_finite_optimization",
    "optimization_not_converged",
    "unobservable_pose",
    "ill_conditioned_pose",
    "pose_uncertainty_exceeded",
    "spread_rejected",
    "ambiguous_equal_score",
    "ambiguous_hypotheses",
)
REQUIRED_DECISIVE_GATES = frozenset((*REQUIRED_GATE_PRECEDENCE, "insufficient_valid_hypothesis", "inconsistent_coordinate_state"))
OBSERVATION_STABLE_ORDER = ("source_sequence", "frame_id", "detection_id", "observation_id")
HYPOTHESIS_STABLE_ORDER = (
    "semantic_path", "cue_subset", "seed_class", "minimal_observation_ids",
    "start_cell", "start_heading",
)

# The one place `wheel_weighted` may legally appear: the frozen name of the pilot
# diagnostic-candidate arm (Requirement 12.4). It is matched exactly, so a bare
# `wheel_weighted` mode or a version string embedding it is still rejected.
ALLOWED_ESTIMATOR_TERMS = ("wheel_weighted_procrustes",)

PROHIBITED_ESTIMATOR_TERMS = (
    "wheel_only",
    "wheel_weighted",
    "projected-point procrustes",
    "projected_point_procrustes",
    "roleconstraintgraph",
    "role_constraint_graph",
    "inverse-lifted target",
    "inverse_lifted_target",
)
DEFERRED_CAPABILITIES = frozenset(
    (
        "detector_replacement",
        "detector_retraining",
        "generalized_learned_reliability",
        "full_multi_provider_schema_platform",
        "exhaustive_artifact_management",
        "calibration_identification",
        "calibration_re_estimation",
        "temporal_fusion",
        "multi_sensor_fusion",
        "selective_risk_acceptance",
    )
)
HARDENING_ALLOWED_SCOPE = frozenset(
    (
        "accepted_mvp_input_validation",
        "output_validation",
        "reproducible_configuration_loading",
        "failure_observability",
        "coordinate_authority_safety",
        "optimizer_disabled_mode_parity",
    )
)


class ProfileValidationError(ValueError):
    """A deterministic, machine-readable profile rejection."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _reject(code: str, detail: str) -> None:
    raise ProfileValidationError(code, detail)


@dataclass(frozen=True, kw_only=True)
class AcceptanceSiteNamespace(CanonicalModel):
    """Independent evidence namespace roots for one acceptance site."""

    site: str
    ground_truth: str
    track: str
    source_sequence: str
    view: str
    partition: str
    metric: str
    decision: str


@dataclass(frozen=True, kw_only=True)
class MvpScopeGuard(CanonicalModel):
    """Explicit runtime and feature-scope declarations validated pre-read."""

    acceptance_namespaces: tuple[AcceptanceSiteNamespace, ...]
    diagnostic_sites: tuple[str, ...]
    observation_stable_order: tuple[str, ...]
    hypothesis_stable_order: tuple[str, ...]
    scipy_version: str
    jacobian_method: str
    numeric_threads: int
    production_imports: tuple[str, ...]
    estimator_contract_terms: tuple[str, ...]
    calibration_variation_scope: str
    publish_fitted_calibration: bool
    feed_back_fitted_calibration: bool
    enabled_deferred_capabilities: tuple[str, ...]
    selective_risk_role: str
    pooled_cross_site_override: bool
    diagnostic_site_decision_input: bool
    current_evidence_status: DecisionStatus
    proven_improvement_claim_allowed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "acceptance_namespaces", canonical_order(self.acceptance_namespaces))
        object.__setattr__(self, "diagnostic_sites", canonical_order(self.diagnostic_sites, unique=True))
        object.__setattr__(self, "production_imports", canonical_order(self.production_imports, unique=True))
        object.__setattr__(self, "estimator_contract_terms", canonical_order(self.estimator_contract_terms, unique=True))
        object.__setattr__(self, "enabled_deferred_capabilities", canonical_order(self.enabled_deferred_capabilities, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ValidatedProfile(CanonicalModel):
    """Outcome-blind capability token required by record/outcome readers."""

    profile_identity: ContentIdentity
    scope_identity: ContentIdentity
    acceptance_sites: tuple[str, ...] = ACCEPTANCE_SITES
    diagnostic_sites: tuple[str, ...] = DIAGNOSTIC_SITES


@dataclass(frozen=True, kw_only=True)
class DispatchAuthorization(CanonicalModel):
    """Separately reviewed evidence that may authorize optimizer dispatch."""

    candidate_identity: ContentIdentity
    held_out_site_decisions: tuple[SiteDecision, ...]
    hardening_reviewed: bool
    hardening_authorized: bool
    hardening_candidate_identity: Optional[ContentIdentity]
    hardening_scope: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "held_out_site_decisions", canonical_order(self.held_out_site_decisions))
        object.__setattr__(self, "hardening_scope", canonical_order(self.hardening_scope, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class DispatchGuardResult(CanonicalModel):
    optimizer_enabled: bool
    production_path: str
    optimizer_output_role: str
    reason: str


def _determinant3(matrix: Sequence[Sequence[float]]) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _product3(left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(sum(left[row][k] * right[k][column] for k in range(3)) for column in range(3))
        for row in range(3)
    )


def _validate_calibration(profile: AcceptanceProfile) -> None:
    snapshot = profile.calibration.snapshot
    if len(snapshot.distortion) not in SUPPORTED_DISTORTION_LENGTHS:
        _reject("unsupported_distortion_layout", f"distortion length {len(snapshot.distortion)} is unsupported")
    camera = snapshot.camera_matrix
    if camera[0][0] <= 0 or camera[1][1] <= 0 or camera[2] != (0.0, 0.0, 1.0):
        _reject("invalid_camera_matrix", "camera intrinsics require positive focal lengths and canonical homogeneous scale")
    if abs(snapshot.homography[2][2] - 1.0) > 1e-12:
        _reject("invalid_homography_scale", "homography H[2,2] must be fixed at 1")
    if abs(_determinant3(snapshot.homography)) <= 1e-12 or abs(_determinant3(snapshot.inverse_homography)) <= 1e-12:
        _reject("singular_homography", "homography and inverse must both be nonsingular")
    for product in (_product3(snapshot.homography, snapshot.inverse_homography), _product3(snapshot.inverse_homography, snapshot.homography)):
        if any(abs(product[row][column] - (1.0 if row == column else 0.0)) > 1e-8 for row in range(3) for column in range(3)):
            _reject("inconsistent_homography_inverse", "stored homography inverse does not invert the homography")


def _validate_nuisance_and_cues(profile: AcceptanceProfile) -> None:
    fields = profile.nuisance.fields
    field_names = {field.name for field in fields}
    for field in fields:
        bounds = field.bounds
        if not math.isfinite(bounds.lower) or not math.isfinite(bounds.upper) or bounds.lower > bounds.upper:
            _reject("invalid_nuisance_bounds", f"{field.name} does not have finite closed bounds")
        normalized = field.name.casefold()
        if ("ground" in normalized or "wheel" in normalized) and ("height" in normalized or normalized.startswith("h_")):
            _reject("ground_height_must_be_constant", f"{field.name} attempts to vary ground-contact height")
        if any(term in normalized for term in ("length", "width", "wheelbase", "track")) and bounds.lower <= 0:
            _reject("invalid_dimension_bounds", f"{field.name} must remain positive")
        if field.prior is not None and not bounds.contains(field.prior.mean):
            _reject("nuisance_prior_out_of_bounds", f"{field.name} prior mean lies outside its closed interval")

    authorized = set(profile.calibration.authorized_nuisance_fields)
    if not authorized.issubset(field_names):
        missing = sorted(authorized - field_names)
        _reject("unknown_calibration_nuisance", f"authorized calibration nuisance fields are absent: {missing}")
    if any(name.casefold() in {"h22", "delta_h22", "homography_22"} for name in authorized):
        _reject("variable_homography_scale", "homography scale H[2,2] cannot vary")

    specs = profile.cue_evidence.height_specs
    if not specs:
        _reject("missing_cue_height_evidence", "at least one cue-height specification is required")
    families = [spec.cue_family for spec in specs]
    if len(families) != len(set(families)):
        _reject("duplicate_cue_height_evidence", "each cue family requires exactly one height interval")
    ground_found = False
    for spec in specs:
        bounds = spec.height_m
        if spec.cue_family in (CueFamily.GROUND_CONTACT, CueFamily.WHEEL):
            ground_found = True
            if bounds.lower != 0.0 or bounds.upper != 0.0:
                _reject("invalid_ground_contact_height", f"{spec.cue_family.value} must use [0,0]")
        else:
            if bounds.lower < 0 or bounds.upper >= profile.calibration.snapshot.camera_height_m:
                _reject("unsupported_cue_height", f"{spec.cue_family.value} height must be physical and below the camera")
    if not ground_found:
        _reject("missing_ground_contact_height", "wheel or ground-contact evidence at [0,0] is required")


def _validate_optimizer(profile: AcceptanceProfile) -> None:
    optimizer = profile.optimizer
    configurations = optimizer.minimal_configurations
    if not configurations:
        _reject("missing_minimal_configuration", "one or more minimal observation configurations are required")
    if configurations != profile.cue_evidence.minimal_configurations:
        _reject("minimal_configuration_mismatch", "optimizer and cue-evidence minimal configurations must be identical")
    ids = [item.configuration_id for item in configurations]
    if len(ids) != len(set(ids)):
        _reject("duplicate_minimal_configuration", "minimal configuration ids must be unique")
    has_ground = any(any(family in (CueFamily.WHEEL, CueFamily.GROUND_CONTACT) for family in item.cue_families) for item in configurations)
    has_non_ground = any(any(family not in (CueFamily.WHEEL, CueFamily.GROUND_CONTACT) for family in item.cue_families) for item in configurations)
    if not has_ground or not has_non_ground:
        _reject("missing_seed_stratum", "both wheel and non-wheel minimal configurations are required")

    path_values = [item.semantic_path.value for item in optimizer.semantic_paths]
    if not path_values or "normal" not in path_values or len(path_values) != len(set(path_values)):
        _reject("invalid_semantic_paths", "semantic paths must be unique and include normal")
    required_hypothesis_reserve = len(path_values) * 2
    if optimizer.hypothesis_budget < required_hypothesis_reserve:
        _reject("insufficient_hypothesis_budget", f"budget must reserve {required_hypothesis_reserve} wheel/non-wheel semantic strata")
    if optimizer.sampled_candidate_budget <= 0 or optimizer.retained_candidate_count <= 0:
        _reject("invalid_candidate_budget", "candidate and retention budgets must be positive")
    if optimizer.retained_candidate_count > optimizer.sampled_candidate_budget:
        _reject("invalid_candidate_budget", "retained candidates cannot exceed sampled candidates")

    robust = optimizer.robust
    if robust.loss not in {"linear", "huber", "soft_l1", "cauchy", "arctan"}:
        _reject("unsupported_robust_loss", f"unsupported robust loss {robust.loss!r}")
    if robust.loss_scale <= 0 or robust.support_boundary_px <= 0 or robust.outlier_penalty < 0 or robust.nuisance_penalty < 0:
        _reject("invalid_robust_settings", "loss/support scales must be positive and penalties nonnegative")

    settings = optimizer.optimizer
    if settings.method != "trf":
        _reject("unsupported_scipy_method", "bounded MVP refinement requires scipy method='trf'")
    numeric_settings = (settings.ftol, settings.xtol, settings.gtol, settings.finite_difference_step)
    if settings.max_evaluations <= 0 or any(value <= 0 for value in numeric_settings):
        _reject("implicit_scipy_setting", "iteration limit, tolerances, and finite-difference step must be explicit and positive")
    expected_scale_count = 3 + len(profile.nuisance.fields)
    if len(settings.parameter_scale) != expected_scale_count or any(value <= 0 for value in settings.parameter_scale):
        _reject("invalid_parameter_scale", f"parameter_scale requires {expected_scale_count} positive pose/nuisance entries")

    observability = optimizer.observability
    if not observability.jacobian_version.strip() or not observability.curvature_version.strip():
        _reject("implicit_observability_setting", "jacobian and curvature definitions must be versioned")
    if (observability.rank_tolerance <= 0 or observability.minimum_rank <= 0
            or observability.condition_rejection_boundary <= 0
            or observability.position_uncertainty_boundary_m <= 0
            or observability.heading_uncertainty_boundary_rad <= 0):
        _reject("invalid_observability_setting", "all observability boundaries must be explicit and positive")

    if optimizer.rejection_precedence[:len(REQUIRED_GATE_PRECEDENCE)] != REQUIRED_GATE_PRECEDENCE:
        _reject("invalid_gate_precedence", "mandatory decisive-gate prefix is absent or reordered")
    if len(optimizer.rejection_precedence) != len(set(optimizer.rejection_precedence)):
        _reject("invalid_gate_precedence", "decisive-gate precedence contains duplicates")
    missing_gates = REQUIRED_DECISIVE_GATES - set(optimizer.rejection_precedence)
    if missing_gates:
        _reject("incomplete_gate_precedence", f"decisive gates are missing: {sorted(missing_gates)}")


def _validate_replay_and_policy(profile: AcceptanceProfile) -> None:
    contract = profile.replay_contract
    if (contract.maximum_observations <= 0 or contract.maximum_labels_per_observation <= 0
            or contract.maximum_string_length <= 0):
        _reject("invalid_replay_bounds", "replay collection and string bounds must be positive")
    if contract.maximum_labels_per_observation > contract.maximum_observations:
        _reject("invalid_replay_bounds", "label bound cannot exceed the per-record observation bound")
    if contract.confidence_bounds.lower != 0.0 or contract.confidence_bounds.upper != 1.0:
        _reject("invalid_replay_confidence_bounds", "confidence bounds must be the closed interval [0,1]")
    pilot = profile.pilot_policy
    if not 0.0 < pilot.confidence_level < 1.0:
        _reject("invalid_pilot_policy", "confidence level must lie strictly between zero and one")
    if not all(value.strip() for value in (pilot.cluster_unit, pilot.power_method, pilot.sufficiency_rule_version, pilot.metric_definition_version)):
        _reject("implicit_pilot_policy", "power, clustering, sufficiency, and metrics must be explicit and versioned")


def _normalized_term(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").split())


def validate_estimator_contract(value: Any) -> None:
    """Reject prohibited estimator concepts in nested candidate configuration."""

    def walk(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                walk(str(key), f"{path}.key")
                walk(nested, f"{path}.{key}")
        elif isinstance(item, (tuple, list, set, frozenset)):
            for index, nested in enumerate(item):
                walk(nested, f"{path}[{index}]")
        elif is_dataclass(item) and not isinstance(item, type):
            for field_info in dc_fields(item):
                walk(getattr(item, field_info.name), f"{path}.{field_info.name}")
        elif isinstance(item, str):
            collapsed = item.casefold().replace("-", "_").replace(" ", "_")
            if collapsed in ALLOWED_ESTIMATOR_TERMS:
                return
            compact = collapsed.replace("_", "")
            for prohibited in PROHIBITED_ESTIMATOR_TERMS:
                candidate = prohibited.casefold().replace("-", "_").replace(" ", "_")
                if candidate in collapsed or candidate.replace("_", "") in compact:
                    _reject("prohibited_estimator_contract", f"{path} references {prohibited!r}")

    walk(value, "estimator_contract")


def _validate_scope(profile: AcceptanceProfile, scope: MvpScopeGuard) -> None:
    sites = tuple(namespace.site for namespace in scope.acceptance_namespaces)
    if sites != ACCEPTANCE_SITES:
        _reject("invalid_acceptance_site_namespace", f"acceptance namespaces must be exactly {ACCEPTANCE_SITES}")
    values_by_kind = tuple(
        getattr(namespace, field)
        for field in ("ground_truth", "track", "source_sequence", "view", "partition", "metric", "decision")
        for namespace in scope.acceptance_namespaces
    )
    if any(not value.strip() for value in values_by_kind) or len(values_by_kind) != len(set(values_by_kind)):
        _reject("non_isolated_acceptance_namespace", "every site/evidence namespace must be non-empty and globally distinct")
    if scope.diagnostic_sites != DIAGNOSTIC_SITES:
        _reject("invalid_diagnostic_sites", "taipei-cm must be the sole diagnostic-only site")
    if profile.cue_evidence.site not in ACCEPTANCE_SITES:
        _reject("diagnostic_site_profile", "acceptance profiles cannot be built from diagnostic-site cue evidence")
    if scope.observation_stable_order != OBSERVATION_STABLE_ORDER or scope.hypothesis_stable_order != HYPOTHESIS_STABLE_ORDER:
        _reject("invalid_stable_order", "observation and hypothesis order must match the frozen canonical order")
    if not scope.scipy_version.strip() or not scope.jacobian_method.strip() or scope.numeric_threads != 1:
        _reject("implicit_runtime_setting", "SciPy identity, Jacobian method, and single-thread runtime must be explicit")

    for module in scope.production_imports:
        normalized = module.replace("/", ".").lstrip(".")
        if normalized == "pifpaf" or normalized.startswith("pifpaf.") or normalized == "location" or normalized.startswith("location."):
            _reject("prohibited_production_import", f"legacy production import {module!r} is forbidden")
    validate_estimator_contract(scope.estimator_contract_terms)
    validate_estimator_contract(scope.production_imports)
    # Requirement 4.15-4.16: the prohibition governs the estimator contract, which
    # is the OptimizerProfile itself — scanning only the scope guard's declared
    # terms let a prohibited mode ride in on the profile it was meant to police.
    validate_estimator_contract(profile.optimizer)

    if scope.calibration_variation_scope != "fit_local" or scope.publish_fitted_calibration or scope.feed_back_fitted_calibration:
        _reject("nonlocal_calibration_variation", "calibration variation must remain local to one fit and cannot be published or fed back")
    if scope.enabled_deferred_capabilities:
        unknown = set(scope.enabled_deferred_capabilities) - DEFERRED_CAPABILITIES
        detail = f"deferred capabilities are outside MVP scope: {scope.enabled_deferred_capabilities}"
        if unknown:
            detail += f" (unknown declarations: {sorted(unknown)})"
        _reject("deferred_capability_enabled", detail)
    declared_scope = tuple((*scope.estimator_contract_terms, *scope.production_imports))
    for declaration in declared_scope:
        normalized = declaration.casefold().replace("-", "_").replace(".", "_").replace(" ", "_")
        if any(capability in normalized for capability in DEFERRED_CAPABILITIES):
            _reject("deferred_capability_configured", f"deferred capability declaration {declaration!r} is outside the MVP")
    if scope.selective_risk_role != "diagnostic_only":
        _reject("selective_risk_not_diagnostic", "selective-risk analysis must remain diagnostic-only")
    if scope.pooled_cross_site_override or scope.diagnostic_site_decision_input:
        _reject("non_isolated_site_decision", "pooled and diagnostic-site evidence cannot override acceptance-site decisions")
    if scope.current_evidence_status is not DecisionStatus.INSUFFICIENT_DATA or scope.proven_improvement_claim_allowed:
        _reject("unsupported_current_evidence_claim", "checked-in evidence must remain insufficient_data with no proven-improvement claim")


def validate_before_read(profile: AcceptanceProfile, scope: MvpScopeGuard) -> ValidatedProfile:
    """Validate the complete outcome-blind profile before any data is read."""
    if not profile.profile_id.strip():
        _reject("missing_profile_identity", "profile_id must be non-empty")
    _validate_calibration(profile)
    _validate_nuisance_and_cues(profile)
    _validate_optimizer(profile)
    _validate_replay_and_policy(profile)
    _validate_scope(profile, scope)
    return ValidatedProfile(
        profile_identity=profile.content_identity,
        scope_identity=scope.content_identity,
    )


def require_validated_profile(token: ValidatedProfile, profile: AcceptanceProfile, scope: MvpScopeGuard) -> None:
    """Refuse record/outcome access when validated identities no longer match."""
    if token.profile_identity != profile.content_identity or token.scope_identity != scope.content_identity:
        _reject("profile_changed_after_validation", "profile or scope changed after pre-read validation")


def resolve_optimizer_dispatch(
    candidate_identity: ContentIdentity,
    authorization: Optional[DispatchAuthorization] = None,
) -> DispatchGuardResult:
    """Return the production dispatch decision; default is always baseline."""
    disabled = lambda reason: DispatchGuardResult(
        optimizer_enabled=False,
        production_path="corrected_legacy_baseline",
        optimizer_output_role="diagnostic_only",
        reason=reason,
    )
    if authorization is None:
        return disabled("optimizer_default_off")
    if authorization.candidate_identity != candidate_identity:
        return disabled("candidate_identity_mismatch")

    decisions = authorization.held_out_site_decisions
    sites = tuple(decision.site for decision in decisions)
    if sites != ACCEPTANCE_SITES or len(sites) != len(set(sites)):
        if any(site in DIAGNOSTIC_SITES for site in sites):
            _reject("diagnostic_site_authorization", "taipei-cm cannot contribute to optimizer authorization")
        return disabled("dual_site_held_out_go_missing")
    if any(decision.status is not DecisionStatus.GO for decision in decisions):
        return disabled("dual_site_held_out_go_missing")
    if not authorization.hardening_reviewed or not authorization.hardening_authorized:
        return disabled("hardening_authorization_incomplete")
    if authorization.hardening_candidate_identity != candidate_identity:
        return disabled("hardening_candidate_identity_mismatch")
    if not authorization.hardening_scope or not set(authorization.hardening_scope).issubset(HARDENING_ALLOWED_SCOPE):
        _reject("invalid_hardening_scope", "hardening review contains work outside accepted-MVP validation, reproducibility, observability, parity, or safety")
    return DispatchGuardResult(
        optimizer_enabled=True,
        production_path="pose_optimizer",
        optimizer_output_role="authoritative_when_accepted",
        reason="dual_site_go_and_hardening_authorized",
    )
