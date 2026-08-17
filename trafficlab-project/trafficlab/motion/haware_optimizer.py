"""Deterministic bounded image-space refinement for Haware pose seeds.

This task-level module consumes direct image hypotheses and returns only
non-authoritative refinement diagnostics. Scoring, observability, selection,
and coordinate authority are deliberately left to their dedicated stages.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
import math
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
import scipy
from scipy.optimize import least_squares

from trafficlab.motion.haware_accuracy.models import (
    AcceptanceProfile,
    CanonicalModel,
    ClosedInterval,
    CueFamily,
    HypothesisPath,
    HypothesisState,
    LocalizationDiagnostics,
    LocalizationResult,
    LocalizationStatus,
    NuisanceTreatmentDiagnostics,
    NuisanceVector,
    ObservationRecord,
    ObservabilityDiagnostics,
    ObservabilitySettings,
    Pose2D,
    ProjectionPrediction,
    ResidualDiagnostic,
    VehicleTemplate,
)
from trafficlab.motion.haware_accuracy.validation import (
    MvpScopeGuard,
    ValidatedProfile,
    require_validated_profile,
)
from trafficlab.motion.haware_hypotheses import (
    HypothesisGenerationResult,
    SeededHypothesis,
)
from trafficlab.projection.haware_forward import (
    ForwardProjectionError,
    ForwardProjector,
    ParameterSpec,
    ScaledPoseNuisanceParameterization,
)

try:
    from threadpoolctl import threadpool_limits
except ImportError:  # pragma: no cover - validated single-thread fallback
    threadpool_limits = None


_RETENTION_KEY = ("seed_residual_rms_px", "path_id")
_TR_SOLVER = "exact"
_RESIDUAL_SCHEME = "pixel_component_divided_by_frozen_scale_v1"
_ELLIPSE_CHI_SQUARE_95_DOF2 = 5.991464547107979
_DERIVATIVE_SCHEMES = frozenset(("central", "forward", "backward", "fixed"))


class RefinementContractError(ValueError):
    """Raised before record processing when the frozen contract is inconsistent."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class ObservabilityCalculationError(ValueError):
    """A typed non-finite or inconsistent frozen-curvature calculation."""

    def __init__(self, detail: str) -> None:
        self.code = "non_finite_optimization"
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")


@dataclass(frozen=True, kw_only=True)
class ObservabilityEvaluation(CanonicalModel):
    """Diagnostics plus all per-hypothesis observability gate failures."""

    diagnostics: ObservabilityDiagnostics
    gate_failures: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_failures", tuple(self.gate_failures))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class RefinementBounds(CanonicalModel):
    """Finite local pose bounds and the explicit pixel residual scale."""

    position_delta_x_m: ClosedInterval
    position_delta_y_m: ClosedInterval
    heading_delta_rad: ClosedInterval
    residual_scale_px: float

    def __post_init__(self) -> None:
        intervals = (
            self.position_delta_x_m,
            self.position_delta_y_m,
            self.heading_delta_rad,
        )
        if any(interval.lower >= interval.upper for interval in intervals):
            raise RefinementContractError(
                "invalid_refinement_bounds", "local pose intervals must have finite positive width"
            )
        if not math.isfinite(self.residual_scale_px) or self.residual_scale_px <= 0.0:
            raise RefinementContractError(
                "invalid_residual_scale", "residual_scale_px must be finite and positive"
            )
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class FrozenRefinementSettings(CanonicalModel):
    """Complete replay-visible settings passed to the numerical solver."""

    method: str
    loss: str
    loss_scale: float
    residual_scale_px: float
    residual_scheme: str
    jacobian_method: str
    finite_difference_step: float
    ftol: float
    xtol: float
    gtol: float
    x_scale: tuple[float, ...]
    max_evaluations: int
    sampled_candidate_budget: int
    retained_candidate_count: int
    retention_key: tuple[str, ...]
    parameter_names: tuple[str, ...]
    parameter_units: tuple[str, ...]
    parameter_scales: tuple[float, ...]
    deterministic_seed: int
    scipy_version: str
    numeric_threads: int
    trust_region_solver: str

    def __post_init__(self) -> None:
        for name in ("x_scale", "parameter_names", "parameter_units", "parameter_scales"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "retention_key", tuple(self.retention_key))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class RefinedCandidate(CanonicalModel):
    """A converged candidate which remains diagnostic until later gates pass."""

    path: HypothesisPath
    pose: Pose2D
    nuisance: NuisanceVector
    predictions: tuple[ProjectionPrediction, ...]
    parameter_values: tuple[tuple[str, float], ...]
    pixel_residual_components: tuple[float, ...]
    robust_cost: float
    optimality: float
    evaluations: int
    solver_status: int
    settings: FrozenRefinementSettings
    observability: ObservabilityDiagnostics
    observability_failures: tuple[str, ...] = ()
    authoritative: bool = False

    def __post_init__(self) -> None:
        if self.authoritative:
            raise RefinementContractError(
                "premature_coordinate_authority", "refinement candidates are diagnostic-only"
            )
        object.__setattr__(self, "predictions", tuple(self.predictions))
        object.__setattr__(self, "parameter_values", tuple(self.parameter_values))
        object.__setattr__(self, "pixel_residual_components", tuple(self.pixel_residual_components))
        object.__setattr__(self, "observability_failures", tuple(self.observability_failures))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class RefinementFailure(CanonicalModel):
    """Typed, serializable, non-authoritative candidate failure."""

    path: HypothesisPath
    reason: str
    detail: str
    exception_type: Optional[str]
    settings: Optional[FrozenRefinementSettings]
    authoritative: bool = False

    def __post_init__(self) -> None:
        if self.authoritative or not self.reason.strip() or not self.detail.strip():
            raise RefinementContractError(
                "invalid_refinement_failure", "failures must be typed and non-authoritative"
            )
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class RefinementReport(CanonicalModel):
    """Deterministically retained candidates and complete attempted accounting."""

    generation: HypothesisGenerationResult
    sampled_path_ids: tuple[str, ...]
    retained_path_ids: tuple[str, ...]
    refined: tuple[RefinedCandidate, ...]
    failures: tuple[RefinementFailure, ...]
    skipped_path_ids: tuple[str, ...]
    deterministic_seed: int

    def __post_init__(self) -> None:
        for name in ("sampled_path_ids", "retained_path_ids", "skipped_path_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "refined", tuple(self.refined))
        object.__setattr__(self, "failures", tuple(self.failures))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class CommonScoreComponents(CanonicalModel):
    """Replay-visible terms of the one frozen hypothesis comparison score."""

    robust_residual_loss: float
    outlier_penalty_cost: float
    bounded_nuisance_prior_cost: float
    weighted_nuisance_prior_cost: float
    total: float

    def __post_init__(self) -> None:
        terms = (
            self.robust_residual_loss,
            self.outlier_penalty_cost,
            self.bounded_nuisance_prior_cost,
            self.weighted_nuisance_prior_cost,
            self.total,
        )
        if any(value < 0.0 for value in terms):
            raise RefinementContractError(
                "invalid_common_score", "common score terms must be nonnegative"
            )
        expected = (
            self.robust_residual_loss
            + self.outlier_penalty_cost
            + self.weighted_nuisance_prior_cost
        )
        if not math.isclose(self.total, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise RefinementContractError(
                "invalid_common_score", "common score total does not equal its frozen terms"
            )
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class SupportDiagnostics(CanonicalModel):
    """Complete residual/support accounting for one converged hypothesis."""

    residuals: tuple[ResidualDiagnostic, ...]
    support_observation_ids: tuple[str, ...]
    outlier_observation_ids: tuple[str, ...]
    authorized_observation_count: int
    minimum_support: int
    support_boundary_px: float
    support_includes_equality: bool
    visible_wheel_count: int

    def __post_init__(self) -> None:
        residuals = tuple(sorted(self.residuals, key=lambda item: item.observation_id))
        support = tuple(sorted(self.support_observation_ids))
        outliers = tuple(sorted(self.outlier_observation_ids))
        object.__setattr__(self, "residuals", residuals)
        object.__setattr__(self, "support_observation_ids", support)
        object.__setattr__(self, "outlier_observation_ids", outliers)
        residual_ids = tuple(item.observation_id for item in residuals)
        if len(residual_ids) != self.authorized_observation_count:
            raise RefinementContractError(
                "incomplete_residual_diagnostics", "every authorized observation needs one residual"
            )
        if len(set(residual_ids)) != len(residual_ids):
            raise RefinementContractError(
                "duplicate_residual_diagnostics", "observation residual identities must be unique"
            )
        if set(support).intersection(outliers) or set(support).union(outliers) != set(residual_ids):
            raise RefinementContractError(
                "invalid_support_partition", "support and outliers must partition all residuals"
            )
        if self.minimum_support <= 0 or self.visible_wheel_count < 0:
            raise RefinementContractError(
                "invalid_support_diagnostics", "support minimum and wheel diagnostic are invalid"
            )
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ScoredCandidate(CanonicalModel):
    """A commonly scored candidate, still non-authoritative before later gates."""

    refinement: RefinedCandidate
    path: HypothesisPath
    support: SupportDiagnostics
    score_components: CommonScoreComponents
    support_accepted: bool
    rejection_reason: Optional[str]
    minimum_configuration_id: str
    authoritative: bool = False

    def __post_init__(self) -> None:
        if self.authoritative:
            raise RefinementContractError(
                "premature_coordinate_authority", "scored candidates are diagnostic-only"
            )
        expected_acceptance = (
            len(self.support.support_observation_ids) >= self.support.minimum_support
        )
        if self.support_accepted != expected_acceptance:
            raise RefinementContractError(
                "invalid_support_acceptance", "support acceptance disagrees with the frozen minimum"
            )
        expected_reason = None if self.support_accepted else "insufficient_support"
        if self.rejection_reason != expected_reason:
            raise RefinementContractError(
                "invalid_support_rejection", "insufficient support requires its exact rejection reason"
            )
        expected_state = (
            HypothesisState.SCORED if self.support_accepted else HypothesisState.REJECTED
        )
        if self.path.terminal_state is not expected_state:
            raise RefinementContractError(
                "invalid_scored_terminal_state", "terminal state must reflect support acceptance"
            )
        if not self.minimum_configuration_id.strip():
            raise RefinementContractError(
                "missing_minimum_configuration", "support diagnostics require a configuration id"
            )
        super().__post_init__()

    @property
    def score(self) -> float:
        return self.score_components.total


@dataclass(frozen=True, kw_only=True)
class SupportScoringReport(CanonicalModel):
    """Canonical common-score results for every converged refinement candidate."""

    refinement: RefinementReport
    evaluated: tuple[ScoredCandidate, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.evaluated, key=lambda item: item.path.path_id))
        object.__setattr__(self, "evaluated", ordered)
        expected = {item.path.path_id for item in self.refinement.refined}
        actual = {item.path.path_id for item in ordered}
        if expected != actual or len(actual) != len(ordered):
            raise RefinementContractError(
                "incomplete_scoring_accounting",
                "every converged candidate must have exactly one common-score result",
            )
        super().__post_init__()

    @property
    def supported(self) -> tuple[ScoredCandidate, ...]:
        return tuple(item for item in self.evaluated if item.support_accepted)

    @property
    def rejected(self) -> tuple[ScoredCandidate, ...]:
        return tuple(item for item in self.evaluated if not item.support_accepted)


def _retention_key(candidate: SeededHypothesis) -> tuple[float, str]:
    return (candidate.residual_rms_px, candidate.path.path_id)


def _retain_candidates(
    candidates: Sequence[SeededHypothesis], count: int
) -> tuple[SeededHypothesis, ...]:
    """Reserve each present seed class, then fill solely by the frozen key."""
    ordered = tuple(sorted(candidates, key=_retention_key))
    classes = tuple(dict.fromkeys(item.path.seed_class for item in candidates))
    if len(classes) > count:
        raise RefinementContractError(
            "insufficient_retention_budget",
            "retention count cannot preserve every eligible seed class",
        )
    selected: list[SeededHypothesis] = []
    selected_ids: set[str] = set()
    for seed_class in classes:
        item = min(
            (candidate for candidate in ordered if candidate.path.seed_class is seed_class),
            key=_retention_key,
        )
        selected.append(item)
        selected_ids.add(item.path.path_id)
    for item in ordered:
        if len(selected) >= count:
            break
        if item.path.path_id not in selected_ids:
            selected.append(item)
            selected_ids.add(item.path.path_id)
    return tuple(sorted(selected, key=_retention_key))


def _parameterization(
    candidate: SeededHypothesis,
    template: VehicleTemplate,
    profile: AcceptanceProfile,
    bounds: RefinementBounds,
) -> ScaledPoseNuisanceParameterization:
    point_by_id = {point.semantic_id: point for point in template.points}
    try:
        points = tuple(
            point_by_id[item.template_semantic_id]
            for item in candidate.path.correspondence
        )
    except KeyError as error:
        raise ForwardProjectionError(
            "unknown_template_correspondence", f"template point {error.args[0]!r} is absent"
        ) from error
    if not points:
        raise ForwardProjectionError(
            "empty_refinement_correspondence", "refinement requires image correspondences"
        )
    scales = profile.optimizer.optimizer.parameter_scale
    parameterization = ScaledPoseNuisanceParameterization(
        seed_pose=candidate.seed.pose,
        template_points=np.asarray(tuple(point.position_m for point in points), dtype=np.float64),
        template_cue_families=tuple(point.cue_family for point in points),
        calibration_profile=profile.calibration,
        nuisance_profile=profile.nuisance,
        cue_evidence=profile.cue_evidence,
        position_delta_bounds_m=(
            bounds.position_delta_x_m,
            bounds.position_delta_y_m,
        ),
        heading_delta_bounds_rad=bounds.heading_delta_rad,
        pose_scales=(scales[0], scales[1], scales[2]),
    )
    if not np.array_equal(parameterization.x_scale, np.asarray(scales, dtype=np.float64)):
        raise RefinementContractError(
            "parameter_scale_mismatch",
            "optimizer parameter_scale must equal pose and nuisance field scales",
        )
    return parameterization


def _settings(
    parameterization: ScaledPoseNuisanceParameterization,
    profile: AcceptanceProfile,
    scope: MvpScopeGuard,
    bounds: RefinementBounds,
) -> FrozenRefinementSettings:
    solver = profile.optimizer.optimizer
    specs = parameterization.parameter_specs
    return FrozenRefinementSettings(
        method=solver.method,
        loss=profile.optimizer.robust.loss,
        loss_scale=profile.optimizer.robust.loss_scale,
        residual_scale_px=bounds.residual_scale_px,
        residual_scheme=_RESIDUAL_SCHEME,
        jacobian_method=scope.jacobian_method,
        finite_difference_step=solver.finite_difference_step,
        ftol=solver.ftol,
        xtol=solver.xtol,
        gtol=solver.gtol,
        x_scale=tuple(solver.parameter_scale),
        max_evaluations=solver.max_evaluations,
        sampled_candidate_budget=profile.optimizer.sampled_candidate_budget,
        retained_candidate_count=profile.optimizer.retained_candidate_count,
        retention_key=_RETENTION_KEY,
        parameter_names=tuple(spec.name for spec in specs),
        parameter_units=tuple(spec.unit for spec in specs),
        parameter_scales=tuple(spec.scale for spec in specs),
        deterministic_seed=profile.optimizer.deterministic_seed,
        scipy_version=scope.scipy_version,
        numeric_threads=scope.numeric_threads,
        trust_region_solver=_TR_SOLVER,
    )


def _failure(
    candidate: SeededHypothesis,
    reason: str,
    detail: str,
    settings: Optional[FrozenRefinementSettings],
    error: Optional[BaseException] = None,
) -> RefinementFailure:
    return RefinementFailure(
        path=replace(
            candidate.path,
            terminal_state=HypothesisState.REJECTED,
            terminal_reason=reason,
        ),
        reason=reason,
        detail=detail,
        exception_type=None if error is None else type(error).__name__,
        settings=settings,
    )


def _prior_residuals(
    full_values: np.ndarray, profile: AcceptanceProfile
) -> np.ndarray:
    weight = profile.optimizer.robust.nuisance_penalty
    if weight == 0.0:
        return np.empty(0, dtype=np.float64)
    residuals = []
    for index, field in enumerate(profile.nuisance.fields, start=3):
        if field.prior is not None:
            residuals.append(
                math.sqrt(weight)
                * (full_values[index] - field.prior.mean)
                / field.prior.standard_deviation
            )
    return np.asarray(residuals, dtype=np.float64)


def _robust_weights(residuals: np.ndarray, loss: str, loss_scale: float) -> np.ndarray:
    """Return ``rho'(r**2 / f_scale**2)`` for the frozen SciPy loss."""
    if loss_scale <= 0.0 or not math.isfinite(loss_scale):
        raise ObservabilityCalculationError("robust loss scale is not finite and positive")
    z = np.square(residuals / loss_scale)
    if loss == "linear":
        weights = np.ones_like(z)
    elif loss == "huber":
        weights = np.ones_like(z)
        outside = z > 1.0
        weights[outside] = 1.0 / np.sqrt(z[outside])
    elif loss == "soft_l1":
        weights = 1.0 / np.sqrt(1.0 + z)
    elif loss == "cauchy":
        weights = 1.0 / (1.0 + z)
    elif loss == "arctan":
        weights = 1.0 / (1.0 + np.square(z))
    else:
        raise ObservabilityCalculationError(f"unsupported robust loss {loss!r}")
    if not np.isfinite(weights).all() or np.any(weights < 0.0):
        raise ObservabilityCalculationError("robust weights are non-finite or negative")
    return weights


def _symmetric_pseudoinverse(matrix: np.ndarray, tolerance: float) -> np.ndarray:
    """Absolute-tolerance pseudoinverse used by both frozen Schur operations."""
    symmetric = 0.5 * (matrix + matrix.T)
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    if not np.isfinite(eigenvalues).all():
        raise ObservabilityCalculationError("information eigendecomposition is non-finite")
    if np.any(eigenvalues < -tolerance):
        raise ObservabilityCalculationError("local information is not positive semidefinite")
    retained = eigenvalues > tolerance
    inverse_values = np.zeros_like(eigenvalues)
    inverse_values[retained] = 1.0 / eigenvalues[retained]
    result = (eigenvectors * inverse_values) @ eigenvectors.T
    return 0.5 * (result + result.T)


def _matrix_tuple(matrix: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in matrix)


def compute_observability_from_linearization(
    *,
    image_residual_jacobian_scaled: np.ndarray,
    image_residuals: np.ndarray,
    parameter_names: Sequence[str],
    parameter_units: Sequence[str],
    parameter_scales: Sequence[float],
    nuisance_prior_precision_scaled: Sequence[float],
    nuisance_treatments: Sequence[NuisanceTreatmentDiagnostics] = (),
    settings: ObservabilitySettings,
    robust_loss: str,
    robust_loss_scale: float,
    active_bounds: Sequence[str] = (),
    derivative_schemes: Optional[Sequence[tuple[str, str]]] = None,
) -> ObservabilityEvaluation:
    """Apply the frozen robust information, Schur, covariance, and gate rules.

    The supplied Jacobian is with respect to scaled coordinates
    ``z_j = q_j / parameter_scale_j`` and contains image residual rows only.
    Nuisance priors enter once through their explicit diagonal precision.
    """
    jacobian = np.asarray(image_residual_jacobian_scaled, dtype=np.float64)
    residuals = np.asarray(image_residuals, dtype=np.float64)
    names = tuple(parameter_names)
    units = tuple(parameter_units)
    scales = np.asarray(tuple(parameter_scales), dtype=np.float64)
    prior_precision = np.asarray(tuple(nuisance_prior_precision_scaled), dtype=np.float64)
    parameter_count = len(names)
    if parameter_count < 3 or jacobian.ndim != 2 or jacobian.shape[1] != parameter_count:
        raise ObservabilityCalculationError("Jacobian must have three pose columns and all nuisance columns")
    if residuals.shape != (jacobian.shape[0],):
        raise ObservabilityCalculationError("image residuals must align with Jacobian rows")
    if len(units) != parameter_count or scales.shape != (parameter_count,) or prior_precision.shape != (parameter_count,):
        raise ObservabilityCalculationError("parameter metadata and prior precision must align")
    numeric = (jacobian, residuals, scales, prior_precision)
    if any(not value.size or not np.isfinite(value).all() for value in numeric):
        raise ObservabilityCalculationError("linearization contains an empty or non-finite numeric value")
    if np.any(scales <= 0.0) or np.any(prior_precision < 0.0):
        raise ObservabilityCalculationError("parameter scales and prior precision are invalid")
    if settings.rank_tolerance <= 0.0:
        raise ObservabilityCalculationError("rank tolerance must be positive")

    if derivative_schemes is None:
        schemes = tuple((name, "central") for name in names)
    else:
        schemes = tuple((str(name), str(scheme)) for name, scheme in derivative_schemes)
    if tuple(name for name, _scheme in schemes) != names or any(
        scheme not in _DERIVATIVE_SCHEMES for _name, scheme in schemes
    ):
        raise ObservabilityCalculationError("derivative schemes must align with frozen parameter order")

    weights = _robust_weights(residuals, robust_loss, robust_loss_scale)
    information = jacobian.T @ (weights[:, None] * jacobian)
    information += np.diag(prior_precision)
    information = 0.5 * (information + information.T)
    if not np.isfinite(information).all():
        raise ObservabilityCalculationError("weighted information matrix is non-finite")

    information_pp = information[:3, :3]
    if parameter_count == 3:
        information_pose = information_pp
    else:
        information_pn = information[:3, 3:]
        information_nn = information[3:, 3:]
        nuisance_inverse = _symmetric_pseudoinverse(
            information_nn, settings.rank_tolerance
        )
        information_pose = information_pp - information_pn @ nuisance_inverse @ information_pn.T
    information_pose = 0.5 * (information_pose + information_pose.T)
    pose_eigenvalues = np.linalg.eigvalsh(information_pose)
    if np.any(pose_eigenvalues < -settings.rank_tolerance):
        raise ObservabilityCalculationError("marginalized pose information is not positive semidefinite")
    singular_values = np.linalg.svd(information_pose, compute_uv=False)
    if not np.isfinite(singular_values).all():
        raise ObservabilityCalculationError("pose information singular values are non-finite")
    retained = singular_values > settings.rank_tolerance
    rank = int(np.count_nonzero(retained))
    if rank:
        condition = float(singular_values[0] / singular_values[retained][-1])
    else:
        # No retained direction has no finite ratio, and a sentinel equal to the
        # rejection boundary would fire `ill_conditioned_pose` unconditionally
        # and could never be cleared by raising the boundary (Requirement 6.34).
        condition = None

    degrees_of_freedom = max(int(residuals.size) - rank, 1)
    residual_variance = float(np.dot(weights, np.square(residuals)) / degrees_of_freedom)
    covariance_scaled = residual_variance * _symmetric_pseudoinverse(
        information_pose, settings.rank_tolerance
    )
    pose_scale = np.diag(scales[:3])
    covariance_pose = pose_scale @ covariance_scaled @ pose_scale
    covariance_pose = 0.5 * (covariance_pose + covariance_pose.T)
    position_eigenvalues = np.linalg.eigvalsh(covariance_pose[:2, :2])
    if np.any(position_eigenvalues < -settings.rank_tolerance):
        raise ObservabilityCalculationError("pose covariance is not positive semidefinite")
    position_eigenvalues = np.maximum(position_eigenvalues, 0.0)
    ellipse_axes = np.sqrt(_ELLIPSE_CHI_SQUARE_95_DOF2 * position_eigenvalues)[::-1]
    heading_variance = float(covariance_pose[2, 2])
    if heading_variance < -settings.rank_tolerance:
        raise ObservabilityCalculationError("heading covariance is negative")
    heading_uncertainty = math.sqrt(max(heading_variance, 0.0))
    outputs = (
        information, information_pose, covariance_pose, singular_values,
        ellipse_axes,
        np.asarray(
            (residual_variance, heading_uncertainty)
            if condition is None
            else (condition, residual_variance, heading_uncertainty)
        ),
    )
    if any(not np.isfinite(value).all() for value in outputs):
        raise ObservabilityCalculationError("covariance or uncertainty calculation is non-finite")

    failures: list[str] = []
    if rank < settings.minimum_rank:
        failures.append("unobservable_pose")
    if condition is not None and condition >= settings.condition_rejection_boundary:
        failures.append("ill_conditioned_pose")
    if (
        float(ellipse_axes[0]) >= settings.position_uncertainty_boundary_m
        or heading_uncertainty >= settings.heading_uncertainty_boundary_rad
    ):
        failures.append("pose_uncertainty_exceeded")

    diagnostics = ObservabilityDiagnostics(
        jacobian_version=settings.jacobian_version,
        curvature_version=settings.curvature_version,
        parameter_names=names,
        parameter_units=units,
        parameter_scales=tuple(float(value) for value in scales),
        image_residual_jacobian_scaled=_matrix_tuple(jacobian),
        robust_weights=tuple(float(value) for value in weights),
        information_scaled=_matrix_tuple(information),
        nuisance_prior_precision_scaled=tuple(float(value) for value in prior_precision),
        nuisance_treatments=tuple(nuisance_treatments),
        singular_values=tuple(float(value) for value in singular_values),
        rank=rank,
        condition=condition,
        information_pose=_matrix_tuple(information_pose),
        covariance_pose=_matrix_tuple(covariance_pose),
        position_ellipse_95_m=(float(ellipse_axes[0]), float(ellipse_axes[1])),
        heading_uncertainty_rad=heading_uncertainty,
        active_bounds=tuple(active_bounds),
        residual_variance=residual_variance,
        residual_degrees_of_freedom=degrees_of_freedom,
        derivative_schemes=schemes,
    )
    return ObservabilityEvaluation(diagnostics=diagnostics, gate_failures=tuple(failures))


def _finite_difference_image_jacobian(
    *,
    image_residual: Callable[[np.ndarray], np.ndarray],
    values: np.ndarray,
    specs: Sequence[ParameterSpec],
    active_mask: np.ndarray,
    step_scaled: float,
) -> tuple[np.ndarray, tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Differentiate every pose/nuisance coordinate with frozen bound handling."""
    base = image_residual(values)
    if not np.isfinite(base).all():
        raise ObservabilityCalculationError("base image residual is non-finite")
    jacobian = np.zeros((base.size, len(specs)), dtype=np.float64)
    active_bounds: list[str] = []
    schemes: list[tuple[str, str]] = []
    for index, spec in enumerate(specs):
        lower_room = (values[index] - spec.bounds.lower) / spec.scale
        upper_room = (spec.bounds.upper - values[index]) / spec.scale
        marker = int(active_mask[index])
        if spec.bounds.lower == spec.bounds.upper:
            scheme = "fixed"
            active_bounds.append(f"{spec.name}=fixed")
        elif marker < 0:
            scheme = "forward"
            active_bounds.append(f"{spec.name}=lower")
        elif marker > 0:
            scheme = "backward"
            active_bounds.append(f"{spec.name}=upper")
        elif lower_room >= step_scaled and upper_room >= step_scaled:
            scheme = "central"
        elif upper_room > 0.0 and upper_room >= lower_room:
            scheme = "forward"
        elif lower_room > 0.0:
            scheme = "backward"
        else:
            raise ObservabilityCalculationError(f"no finite derivative step for {spec.name}")

        if scheme == "fixed":
            schemes.append((spec.name, scheme))
            continue
        room = upper_room if scheme == "forward" else lower_room
        actual_step_scaled = min(step_scaled, float(room))
        if actual_step_scaled <= 0.0 or not math.isfinite(actual_step_scaled):
            raise ObservabilityCalculationError(f"invalid one-sided derivative step for {spec.name}")
        physical_step = actual_step_scaled * spec.scale
        plus = np.array(values, copy=True)
        minus = np.array(values, copy=True)
        plus[index] += physical_step
        minus[index] -= physical_step
        if scheme == "central":
            column = (image_residual(plus) - image_residual(minus)) / (2.0 * actual_step_scaled)
        elif scheme == "forward":
            column = (image_residual(plus) - base) / actual_step_scaled
        else:
            column = (base - image_residual(minus)) / actual_step_scaled
        if column.shape != base.shape or not np.isfinite(column).all():
            raise ObservabilityCalculationError(f"non-finite derivative for {spec.name}")
        jacobian[:, index] = column
        schemes.append((spec.name, scheme))
    return jacobian, tuple(active_bounds), tuple(schemes)


def _nuisance_prior_precision_scaled(
    profile: AcceptanceProfile, specs: Sequence[ParameterSpec]
) -> np.ndarray:
    precision = np.zeros(len(specs), dtype=np.float64)
    weight = profile.optimizer.robust.nuisance_penalty
    for index, field in enumerate(profile.nuisance.fields, start=3):
        if field.prior is not None and weight > 0.0:
            precision[index] = weight * (specs[index].scale / field.prior.standard_deviation) ** 2
    return precision


def _nuisance_treatment_diagnostics(
    profile: AcceptanceProfile,
    specs: Sequence[ParameterSpec],
    prior_precision: Sequence[float],
) -> tuple[NuisanceTreatmentDiagnostics, ...]:
    """Freeze interval, prior, and marginalization policy for every varied nuisance."""
    precision = tuple(float(value) for value in prior_precision)
    if len(specs) != len(precision) or len(specs) != 3 + len(profile.nuisance.fields):
        raise RefinementContractError(
            "nuisance_diagnostics_mismatch",
            "nuisance treatment metadata must align with the frozen parameter order",
        )
    treatments = []
    weight = profile.optimizer.robust.nuisance_penalty
    for index, (field, spec) in enumerate(
        zip(profile.nuisance.fields, specs[3:]), start=3
    ):
        if field.name != spec.name or field.bounds != spec.bounds:
            raise RefinementContractError(
                "nuisance_diagnostics_mismatch",
                "nuisance profile and parameter specifications disagree",
            )
        if spec.bounds.lower == spec.bounds.upper:
            continue
        if field.prior is None:
            prior_treatment = "none"
        elif weight > 0.0:
            prior_treatment = "gaussian_quadratic"
        else:
            prior_treatment = "disabled_zero_weight"
        treatments.append(NuisanceTreatmentDiagnostics(
            name=field.name,
            role=spec.role,
            unit=spec.unit,
            bounds=spec.bounds,
            prior=field.prior,
            interval_treatment="finite_closed_interval",
            prior_treatment=prior_treatment,
            uncertainty_propagation="jacobian_schur_marginalized",
            prior_precision_scaled=precision[index],
        ))
    return tuple(treatments)


def _runtime_context(thread_count: int):
    if threadpool_limits is None:
        if thread_count != 1:
            raise RefinementContractError(
                "unsupported_numeric_threads", "only the frozen single-thread runtime is supported"
            )
        return nullcontext()
    return threadpool_limits(limits=thread_count)


def _refine_one(
    candidate: SeededHypothesis,
    record: ObservationRecord,
    template: VehicleTemplate,
    profile: AcceptanceProfile,
    scope: MvpScopeGuard,
    bounds: RefinementBounds,
    projector: ForwardProjector,
) -> RefinedCandidate | RefinementFailure:
    settings: Optional[FrozenRefinementSettings] = None
    try:
        parameterization = _parameterization(candidate, template, profile, bounds)
        settings = _settings(parameterization, profile, scope, bounds)
    except (ForwardProjectionError, RefinementContractError, ValueError) as error:
        return _failure(candidate, "invalid_refinement_parameterization", str(error), settings, error)

    observation_by_id = {item.observation_id: item for item in record.observations}
    try:
        observed = np.asarray(
            tuple(observation_by_id[item.observation_id].pixel for item in candidate.path.correspondence),
            dtype=np.float64,
        )
    except KeyError as error:
        return _failure(
            candidate,
            "missing_refinement_observation",
            f"observation {error.args[0]!r} is absent from the normalized record",
            settings,
            error,
        )

    initial = parameterization.initial_values
    lower = parameterization.lower_bounds
    upper = parameterization.upper_bounds
    fixed = lower == upper
    free_indices = np.flatnonzero(~fixed)
    fixed_values = np.where(fixed, lower, initial)
    invalid_size = observed.size + len(_prior_residuals(initial, profile))
    invalid_residual = np.full(invalid_size, 1.0e12, dtype=np.float64)
    projection_error: list[tuple[str, str, Optional[BaseException]]] = []

    def expand(free_values: Sequence[float]) -> np.ndarray:
        full = np.array(fixed_values, copy=True)
        full[free_indices] = np.asarray(free_values, dtype=np.float64)
        return full

    def project(full: np.ndarray):
        decoded = parameterization.decode(full)
        prediction = projector.predict_pixels(
            decoded.pose, decoded.template_points, decoded.local_calibration
        )
        if not prediction.valid.all():
            reason = next(
                item for item in prediction.failure_reasons if item is not None
            )
            raise ForwardProjectionError("invalid_projection", reason)
        if not np.isfinite(prediction.pixels).all():
            raise ForwardProjectionError(
                "non_finite_projection", "projector returned non-finite pixels"
            )
        return decoded, prediction

    def image_residual_full(full: np.ndarray) -> np.ndarray:
        _decoded, prediction = project(full)
        pixel = ((prediction.pixels - observed) / bounds.residual_scale_px).reshape(-1)
        if not np.isfinite(pixel).all():
            raise FloatingPointError("image residual contains non-finite values")
        return pixel

    def residual(free_values: np.ndarray) -> np.ndarray:
        full = expand(free_values)
        try:
            pixel = image_residual_full(full)
            result = np.concatenate((pixel, _prior_residuals(full, profile)))
            if not np.isfinite(result).all():
                raise FloatingPointError("residual contains non-finite values")
            return result
        except ForwardProjectionError as error:
            projection_error[:] = [(error.code, error.detail, error)]
            return invalid_residual
        except (ArithmeticError, ValueError, np.linalg.LinAlgError) as error:
            projection_error[:] = [("numerical_optimization_failure", str(error), error)]
            return invalid_residual

    solver = profile.optimizer.optimizer
    try:
        with _runtime_context(scope.numeric_threads):
            fit = least_squares(
                residual,
                initial[free_indices],
                jac=scope.jacobian_method,
                bounds=(lower[free_indices], upper[free_indices]),
                method=solver.method,
                loss=profile.optimizer.robust.loss,
                f_scale=profile.optimizer.robust.loss_scale,
                diff_step=solver.finite_difference_step,
                x_scale=np.asarray(solver.parameter_scale, dtype=np.float64)[free_indices],
                ftol=solver.ftol,
                xtol=solver.xtol,
                gtol=solver.gtol,
                max_nfev=solver.max_evaluations,
                tr_solver=_TR_SOLVER,
                verbose=0,
            )
    except Exception as error:
        return _failure(
            candidate, "numerical_optimization_failure", str(error), settings, error
        )

    final_values = expand(fit.x)
    try:
        decoded, prediction = project(final_values)
        final_residual = residual(fit.x)
    except ForwardProjectionError as error:
        return _failure(candidate, "invalid_projection", error.detail, settings, error)
    except (ArithmeticError, ValueError, np.linalg.LinAlgError) as error:
        return _failure(
            candidate, "numerical_optimization_failure", str(error), settings, error
        )

    numeric_outputs = (
        final_values,
        final_residual,
        np.asarray(fit.fun),
        np.asarray(fit.jac),
        np.asarray((fit.cost, fit.optimality), dtype=np.float64),
    )
    if any(not np.isfinite(value).all() for value in numeric_outputs):
        return _failure(
            candidate,
            "non_finite_optimization",
            "solver returned a non-finite parameter, prediction, residual, derivative, or cost",
            settings,
        )
    if not fit.success or int(fit.status) <= 0:
        detail = str(fit.message).strip() or "frozen convergence rule was not met"
        return _failure(candidate, "optimization_not_converged", detail, settings)
    if np.array_equal(final_residual, invalid_residual):
        reason, detail, error = projection_error[-1]
        return _failure(candidate, reason, detail, settings, error)

    predictions = tuple(
        ProjectionPrediction(
            observation_id=correspondence.observation_id,
            template_semantic_id=correspondence.template_semantic_id,
            pixel=(float(pixel[0]), float(pixel[1])),
            valid=True,
        )
        for correspondence, pixel in zip(candidate.path.correspondence, prediction.pixels)
    )
    try:
        active_mask = np.zeros(len(parameterization.parameter_specs), dtype=np.int8)
        active_mask[fixed] = 2
        active_mask[free_indices] = np.asarray(fit.active_mask, dtype=np.int8)
        image_jacobian, active_bounds, derivative_schemes = _finite_difference_image_jacobian(
            image_residual=image_residual_full,
            values=final_values,
            specs=parameterization.parameter_specs,
            active_mask=active_mask,
            step_scaled=solver.finite_difference_step,
        )
        prior_precision = _nuisance_prior_precision_scaled(
            profile, parameterization.parameter_specs
        )
        observability = compute_observability_from_linearization(
            image_residual_jacobian_scaled=image_jacobian,
            image_residuals=final_residual[: observed.size],
            parameter_names=tuple(spec.name for spec in parameterization.parameter_specs),
            parameter_units=tuple(spec.unit for spec in parameterization.parameter_specs),
            parameter_scales=tuple(spec.scale for spec in parameterization.parameter_specs),
            nuisance_prior_precision_scaled=prior_precision,
            nuisance_treatments=_nuisance_treatment_diagnostics(
                profile, parameterization.parameter_specs, prior_precision
            ),
            settings=profile.optimizer.observability,
            robust_loss=profile.optimizer.robust.loss,
            robust_loss_scale=profile.optimizer.robust.loss_scale,
            active_bounds=active_bounds,
            derivative_schemes=derivative_schemes,
        )
    except (ObservabilityCalculationError, ForwardProjectionError, ArithmeticError, ValueError, np.linalg.LinAlgError) as error:
        return _failure(
            candidate,
            "non_finite_optimization",
            f"frozen observability calculation failed: {error}",
            settings,
            error,
        )

    return RefinedCandidate(
        path=replace(
            candidate.path,
            terminal_state=HypothesisState.REFINED,
            terminal_reason=None,
        ),
        pose=decoded.pose,
        nuisance=decoded.published_nuisance,
        predictions=predictions,
        parameter_values=tuple(
            (spec.name, float(value))
            for spec, value in zip(parameterization.parameter_specs, final_values)
        ),
        pixel_residual_components=tuple(float(value) for value in final_residual[: observed.size]),
        robust_cost=float(fit.cost),
        optimality=float(fit.optimality),
        evaluations=int(fit.nfev),
        solver_status=int(fit.status),
        settings=settings,
        observability=observability.diagnostics,
        observability_failures=observability.gate_failures,
    )


def _robust_rho(loss: str, normalized_squared: float) -> float:
    """Return the frozen SciPy-compatible rho(z) value for one 2D residual."""
    if normalized_squared < 0.0 or not math.isfinite(normalized_squared):
        raise RefinementContractError(
            "invalid_residual_loss_input", "robust loss input must be finite and nonnegative"
        )
    if loss == "linear":
        return normalized_squared
    if loss == "soft_l1":
        return 2.0 * (math.sqrt(1.0 + normalized_squared) - 1.0)
    if loss == "huber":
        if normalized_squared <= 1.0:
            return normalized_squared
        return 2.0 * math.sqrt(normalized_squared) - 1.0
    if loss == "cauchy":
        return math.log1p(normalized_squared)
    if loss == "arctan":
        return math.atan(normalized_squared)
    raise RefinementContractError(
        "unsupported_robust_loss", f"unsupported robust loss {loss!r}"
    )


def _robust_observation_loss(
    residual_px: tuple[float, float], settings: FrozenRefinementSettings
) -> float:
    scaled_squared = (
        (residual_px[0] / settings.residual_scale_px) ** 2
        + (residual_px[1] / settings.residual_scale_px) ** 2
    )
    loss_scale_squared = settings.loss_scale ** 2
    return loss_scale_squared * _robust_rho(
        settings.loss, scaled_squared / loss_scale_squared
    )


def _minimum_support_for_path(
    path: HypothesisPath, profile: AcceptanceProfile
) -> tuple[str, int]:
    prefix = "direct_cctv_minimal:"
    method = path.initialization_source.method
    if not method.startswith(prefix):
        raise RefinementContractError(
            "unknown_minimum_configuration",
            f"initialization method {method!r} does not identify a frozen configuration",
        )
    configuration_id = method[len(prefix):]
    matches = tuple(
        item for item in profile.optimizer.minimal_configurations
        if item.configuration_id == configuration_id
    )
    if len(matches) != 1:
        raise RefinementContractError(
            "unknown_minimum_configuration",
            f"configuration {configuration_id!r} is not uniquely present in the profile",
        )
    return configuration_id, matches[0].minimum_support


def _bounded_nuisance_prior_cost(
    candidate: RefinedCandidate, profile: AcceptanceProfile
) -> float:
    parameter_values = dict(candidate.parameter_values)
    published_values = dict(candidate.nuisance.values)
    expected_names = {field.name for field in profile.nuisance.fields}
    if not expected_names.issubset(parameter_values):
        raise RefinementContractError(
            "incomplete_nuisance_values",
            "scoring requires every frozen nuisance parameter value",
        )
    if not set(published_values).issubset(expected_names):
        raise RefinementContractError(
            "unknown_nuisance_value", "candidate published an unknown nuisance field"
        )
    cost = 0.0
    for field in profile.nuisance.fields:
        value = parameter_values[field.name]
        if field.name in published_values and not math.isclose(
            published_values[field.name], value, rel_tol=0.0, abs_tol=1e-12
        ):
            raise RefinementContractError(
                "inconsistent_nuisance_value",
                f"published {field.name} differs from its fitted parameter value",
            )
        if not field.bounds.contains(value):
            raise RefinementContractError(
                "nuisance_out_of_bounds",
                f"{field.name}={value!r} is outside its frozen closed interval",
            )
        if field.prior is not None:
            cost += (
                (value - field.prior.mean) / field.prior.standard_deviation
            ) ** 2
    if not math.isfinite(cost):
        raise RefinementContractError(
            "non_finite_nuisance_prior", "bounded nuisance prior cost is non-finite"
        )
    return cost


def _score_one(
    candidate: RefinedCandidate,
    record: ObservationRecord,
    template: VehicleTemplate,
    profile: AcceptanceProfile,
) -> ScoredCandidate:
    if (
        candidate.settings.loss != profile.optimizer.robust.loss
        or candidate.settings.loss_scale != profile.optimizer.robust.loss_scale
    ):
        raise RefinementContractError(
            "refinement_score_setting_mismatch",
            "candidate loss settings differ from the frozen common-score profile",
        )
    observation_by_id = {item.observation_id: item for item in record.observations}
    prediction_by_id = {item.observation_id: item for item in candidate.predictions}
    template_by_id = {item.semantic_id: item for item in template.points}
    correspondence_ids = tuple(
        item.observation_id for item in candidate.path.correspondence
    )
    if set(prediction_by_id) != set(correspondence_ids) or len(prediction_by_id) != len(correspondence_ids):
        raise RefinementContractError(
            "incomplete_scoring_predictions",
            "predictions must correspond exactly once to every authorized observation",
        )

    residuals: list[ResidualDiagnostic] = []
    robust_residual_loss = 0.0
    visible_wheel_count = 0
    boundary = profile.optimizer.robust.support_boundary_px
    includes_equality = profile.optimizer.robust.support_includes_equality
    for correspondence in candidate.path.correspondence:
        try:
            observation = observation_by_id[correspondence.observation_id]
            prediction = prediction_by_id[correspondence.observation_id]
            template_point = template_by_id[correspondence.template_semantic_id]
        except KeyError as error:
            raise RefinementContractError(
                "missing_scoring_input", f"scoring input {error.args[0]!r} is absent"
            ) from error
        if prediction.template_semantic_id != correspondence.template_semantic_id:
            raise RefinementContractError(
                "scoring_correspondence_mismatch",
                "prediction template identity differs from the authorized correspondence",
            )
        residual_px = (
            prediction.pixel[0] - observation.pixel[0],
            prediction.pixel[1] - observation.pixel[1],
        )
        magnitude = math.hypot(*residual_px)
        in_support = magnitude <= boundary if includes_equality else magnitude < boundary
        residuals.append(ResidualDiagnostic(
            observation_id=correspondence.observation_id,
            residual_px=residual_px,
            magnitude_px=magnitude,
            in_support=in_support,
        ))
        robust_residual_loss += _robust_observation_loss(
            residual_px, candidate.settings
        )
        if template_point.cue_family in {CueFamily.WHEEL, CueFamily.GROUND_CONTACT}:
            visible_wheel_count += 1

    support_ids = tuple(
        item.observation_id for item in residuals if item.in_support
    )
    outlier_ids = tuple(
        item.observation_id for item in residuals if not item.in_support
    )
    configuration_id, minimum_support = _minimum_support_for_path(
        candidate.path, profile
    )
    support_accepted = len(support_ids) >= minimum_support
    nuisance_prior_cost = _bounded_nuisance_prior_cost(candidate, profile)
    outlier_penalty_cost = profile.optimizer.robust.outlier_penalty * len(outlier_ids)
    weighted_nuisance_cost = (
        profile.optimizer.robust.nuisance_penalty * nuisance_prior_cost
    )
    total = robust_residual_loss + outlier_penalty_cost + weighted_nuisance_cost
    rejection_reason = None if support_accepted else "insufficient_support"
    path = replace(
        candidate.path,
        terminal_state=(
            HypothesisState.SCORED if support_accepted else HypothesisState.REJECTED
        ),
        terminal_reason=rejection_reason,
    )
    return ScoredCandidate(
        refinement=candidate,
        path=path,
        support=SupportDiagnostics(
            residuals=tuple(residuals),
            support_observation_ids=support_ids,
            outlier_observation_ids=outlier_ids,
            authorized_observation_count=len(residuals),
            minimum_support=minimum_support,
            support_boundary_px=boundary,
            support_includes_equality=includes_equality,
            visible_wheel_count=visible_wheel_count,
        ),
        score_components=CommonScoreComponents(
            robust_residual_loss=robust_residual_loss,
            outlier_penalty_cost=outlier_penalty_cost,
            bounded_nuisance_prior_cost=nuisance_prior_cost,
            weighted_nuisance_prior_cost=weighted_nuisance_cost,
            total=total,
        ),
        support_accepted=support_accepted,
        rejection_reason=rejection_reason,
        minimum_configuration_id=configuration_id,
    )


class CommonSupportScorer:
    """Apply frozen support and one common score without selecting a winner."""

    def evaluate(
        self,
        refinement: RefinementReport,
        record: ObservationRecord,
        template: VehicleTemplate,
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
    ) -> SupportScoringReport:
        require_validated_profile(token, profile, scope)
        evaluated = tuple(
            _score_one(candidate, record, template, profile)
            for candidate in refinement.refined
        )
        return SupportScoringReport(refinement=refinement, evaluated=evaluated)


@dataclass(frozen=True)
class EqualScorePositionVerdict:
    """Whether tied hypotheses disagree only about heading."""

    position_equivalent: bool
    dispersion_m: float


def resolve_equal_score_positions(
    *,
    positions: Sequence[tuple[float, float]],
    px_per_meter: float,
    tolerance_m: float,
) -> EqualScorePositionVerdict:
    """Decide whether an equal-score tie is a heading-only ambiguity.

    Requirements 5.19-5.21. A front/rear swap can move the fitted centre by
    roughly half a wheelbase, and the handedness decision record documents
    same-side wheel pairs landing a full track width away, so position
    agreement is proven here rather than assumed from the heading tie.

    The dispersion is the maximum pairwise distance in metres; the boundary is
    inclusive.
    """
    if px_per_meter <= 0.0 or not math.isfinite(px_per_meter):
        raise ObservabilityCalculationError("px_per_meter must be finite and positive")
    if len(positions) < 2:
        return EqualScorePositionVerdict(position_equivalent=True, dispersion_m=0.0)
    dispersion_px = max(
        math.dist(first, second)
        for index, first in enumerate(positions)
        for second in positions[index + 1:]
    )
    dispersion_m = dispersion_px / px_per_meter
    return EqualScorePositionVerdict(
        position_equivalent=dispersion_m <= tolerance_m,
        dispersion_m=dispersion_m,
    )


class OrderedGateSelector:
    """Deduplicate scored poses, apply ordered gates, and finalize authority.

    Equivalence is the connected-component closure of the complete pair graph,
    not a greedy clustering pass.  Margin necessity is latched from that
    initial deduplicated support-valid set before observability and spread gates
    are interpreted for the selected representative.
    """

    def select(
        self,
        scoring: SupportScoringReport,
        record: ObservationRecord,
        template: VehicleTemplate,
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
        spread_m_by_path: Optional[Mapping[str, float]] = None,
    ) -> LocalizationResult:
        require_validated_profile(token, profile, scope)
        components = _equivalence_components(scoring.supported, profile)
        representatives = tuple(
            sorted(
                (_component_representative(component) for component in components),
                key=_representative_key,
            )
        )
        margin_required = len(representatives) >= 2
        selected = representatives[0] if representatives else None
        margin = (
            representatives[1].score - selected.score
            if margin_required and selected is not None
            else None
        )

        retained_failures = _all_recorded_gate_failures(scoring)
        decisive_failures: list[str] = []
        position_equivalent = False
        position_dispersion_m: Optional[float] = None
        if selected is None:
            decisive_failures.extend(retained_failures)
            decisive_failures.append("insufficient_valid_hypothesis")
            retained_failures = tuple(
                dict.fromkeys((*retained_failures, "insufficient_valid_hypothesis"))
            )
        else:
            decisive_failures.extend(selected.refinement.observability_failures)
            spread_m = _selected_spread_m(
                selected, template, spread_m_by_path
            )
            boundary = profile.optimizer.spread_rejection_boundary_m
            if boundary is not None and (
                not math.isfinite(spread_m) or spread_m >= boundary
            ):
                decisive_failures.append("spread_rejected")

            if margin_required:
                second = representatives[1]
                tied = tuple(
                    item for item in representatives
                    if abs(item.score - selected.score)
                    <= profile.optimizer.ambiguity.equal_score_tolerance
                )
                # Requirements 5.19-5.21: when every tied pose puts the vehicle in
                # the same place, the ambiguity is about heading alone, and this
                # repository consumes only the position half. Position agreement
                # is proven, never inferred from the heading tie: a front/rear
                # swap can move the fitted centre by half a wheelbase.
                if len(tied) >= 2:
                    verdict = resolve_equal_score_positions(
                        positions=tuple(item.refinement.pose.center_sat_px for item in tied),
                        px_per_meter=profile.calibration.snapshot.pixels_per_metre,
                        tolerance_m=profile.pilot_policy.position_ambiguity_tolerance_m,
                    )
                    position_equivalent = verdict.position_equivalent
                    position_dispersion_m = verdict.dispersion_m
                else:
                    position_equivalent = False
                if len(tied) >= 2 and not position_equivalent:
                    decisive_failures.append("ambiguous_equal_score")
                if not position_equivalent and not _margin_passes(
                    selected.score, second.score, profile
                ):
                    decisive_failures.append("ambiguous_hypotheses")
            retained_failures = tuple(
                dict.fromkeys((*retained_failures, *decisive_failures))
            )

        decisive = _decisive_reason(decisive_failures, profile)
        accepted = selected is not None and decisive is None
        selected_path_id = None if selected is None else selected.path.path_id
        finalized_paths = _finalized_paths(
            scoring,
            components,
            selected_path_id=selected_path_id,
            accepted=accepted,
            decisive_reason=decisive,
        )
        component_ids = tuple(
            tuple(item.path.path_id for item in component)
            for component in components
        )
        selected_spread = (
            None if selected is None
            else _selected_spread_m(selected, template, spread_m_by_path)
        )
        diagnostics = LocalizationDiagnostics(
            normalized_observations=record.observations,
            exclusions=tuple(
                failure.reason for failure in scoring.refinement.failures
            ),
            paths=finalized_paths,
            merged_components=component_ids,
            selected_path=selected_path_id,
            hypothesis_margin=margin,
            spread_m=selected_spread,
            gate_failures=retained_failures,
        )
        if accepted:
            assert selected is not None
            return LocalizationResult(
                status=LocalizationStatus.ACCEPTED,
                usable=True,
                authoritative_position_sat_px=selected.refinement.pose.center_sat_px,
                diagnostic_position_sat_px=None,
                heading_deg=None if position_equivalent else math.degrees(
                    selected.refinement.pose.heading_rad_unwrapped
                ) % 360.0,
                heading_status="ambiguous" if position_equivalent else None,
                decisive_gate="accepted",
                reason=None,
                diagnostics=diagnostics,
            )

        diagnostic_position = (
            None if selected is None else selected.refinement.pose.center_sat_px
        )
        diagnostic_heading = (
            None if selected is None
            else math.degrees(selected.refinement.pose.heading_rad_unwrapped) % 360.0
        )
        rejection = decisive or "insufficient_valid_hypothesis"
        return LocalizationResult(
            status=LocalizationStatus.REJECTED,
            usable=False,
            authoritative_position_sat_px=None,
            diagnostic_position_sat_px=diagnostic_position,
            heading_deg=diagnostic_heading,
            decisive_gate=rejection,
            reason=rejection,
            diagnostics=diagnostics,
        )


def _canonical_pose_key(candidate: ScoredCandidate) -> tuple[float, float, float, bytes]:
    pose = candidate.refinement.pose
    return (
        pose.center_sat_px[0],
        pose.center_sat_px[1],
        pose.heading_rad_unwrapped % (2.0 * math.pi),
        candidate.path.canonical_bytes(),
    )


def _representative_key(candidate: ScoredCandidate) -> tuple[float, float, float, float, bytes]:
    return (candidate.score, *_canonical_pose_key(candidate))


def _component_representative(
    component: Sequence[ScoredCandidate],
) -> ScoredCandidate:
    return min(component, key=_representative_key)


def _circular_distance(left: float, right: float) -> float:
    return abs((left - right + math.pi) % (2.0 * math.pi) - math.pi)


def _prediction_map(candidate: ScoredCandidate) -> dict[tuple[str, str], tuple[float, float]]:
    return {
        (item.template_semantic_id, item.observation_id): item.pixel
        for item in candidate.refinement.predictions
    }


def _equivalent(
    left: ScoredCandidate,
    right: ScoredCandidate,
    profile: AcceptanceProfile,
) -> bool:
    settings = profile.optimizer.equivalence
    pixel_scale = profile.calibration.snapshot.pixels_per_metre
    position_m = math.hypot(
        left.refinement.pose.center_sat_px[0] - right.refinement.pose.center_sat_px[0],
        left.refinement.pose.center_sat_px[1] - right.refinement.pose.center_sat_px[1],
    ) / pixel_scale
    if position_m > settings.position_tolerance_m:
        return False
    if _circular_distance(
        left.refinement.pose.heading_rad_unwrapped,
        right.refinement.pose.heading_rad_unwrapped,
    ) > settings.heading_tolerance_rad:
        return False
    left_predictions = _prediction_map(left)
    right_predictions = _prediction_map(right)
    if left_predictions.keys() != right_predictions.keys():
        return False
    return all(
        math.hypot(
            left_predictions[key][0] - right_predictions[key][0],
            left_predictions[key][1] - right_predictions[key][1],
        ) <= settings.prediction_tolerance_px
        for key in left_predictions
    )


def _equivalence_components(
    candidates: Sequence[ScoredCandidate],
    profile: AcceptanceProfile,
) -> tuple[tuple[ScoredCandidate, ...], ...]:
    ordered = tuple(sorted(candidates, key=_canonical_pose_key))
    parents = list(range(len(ordered)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    for left in range(len(ordered)):
        for right in range(left + 1, len(ordered)):
            if _equivalent(ordered[left], ordered[right], profile):
                union(left, right)

    grouped: dict[int, list[ScoredCandidate]] = {}
    for index, candidate in enumerate(ordered):
        grouped.setdefault(root(index), []).append(candidate)
    components = tuple(
        tuple(sorted(component, key=_canonical_pose_key))
        for component in grouped.values()
    )
    return tuple(
        sorted(
            components,
            key=lambda component: _canonical_pose_key(
                _component_representative(component)
            ),
        )
    )


def _margin_passes(
    best_score: float,
    second_score: float,
    profile: AcceptanceProfile,
) -> bool:
    settings = profile.optimizer.ambiguity
    difference = second_score - best_score
    if difference < settings.margin_absolute:
        return False
    if settings.margin_ratio is None:
        return True
    denominator = max(
        abs(best_score), settings.equal_score_tolerance, np.finfo(np.float64).eps
    )
    return second_score / denominator >= settings.margin_ratio


def _selected_spread_m(
    candidate: ScoredCandidate,
    template: VehicleTemplate,
    supplied: Optional[Mapping[str, float]],
) -> float:
    if supplied is not None and candidate.path.path_id in supplied:
        return float(supplied[candidate.path.path_id])
    point_by_id = {item.semantic_id: item for item in template.points}
    points = np.asarray(
        tuple(
            (
                point_by_id[item.template_semantic_id].position_m[0],
                point_by_id[item.template_semantic_id].position_m[2],
            )
            for item in candidate.path.correspondence
        ),
        dtype=np.float64,
    )
    if len(points) < 2:
        return 0.0
    distances = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=-1)
    return float(np.max(distances))


def _normalized_gate_reason(reason: str) -> str:
    if reason in {
        "numerical_optimization_failure",
        "invalid_projection",
    }:
        return "non_finite_optimization"
    return reason


def _all_recorded_gate_failures(
    scoring: SupportScoringReport,
) -> tuple[str, ...]:
    failures = [
        _normalized_gate_reason(item.reason)
        for item in scoring.refinement.failures
    ]
    failures.extend(
        item.rejection_reason
        for item in scoring.evaluated
        if item.rejection_reason is not None
    )
    for item in scoring.supported:
        failures.extend(item.refinement.observability_failures)
    return tuple(dict.fromkeys(failures))


def _decisive_reason(
    failures: Sequence[str], profile: AcceptanceProfile
) -> Optional[str]:
    failed = set(failures)
    for reason in profile.optimizer.rejection_precedence:
        if reason in failed:
            return reason
    return None


def _finalized_paths(
    scoring: SupportScoringReport,
    components: Sequence[Sequence[ScoredCandidate]],
    *,
    selected_path_id: Optional[str],
    accepted: bool,
    decisive_reason: Optional[str],
) -> tuple[HypothesisPath, ...]:
    generation = scoring.refinement.generation
    paths = {item.path_id: item for item in generation.report.authorized_paths}
    for item in generation.report.budget_exclusions:
        paths[item.path_id] = item
    for item in generation.invalid_paths:
        paths[item.path_id] = item
    for path_id in scoring.refinement.skipped_path_ids:
        if path_id in paths:
            paths[path_id] = replace(
                paths[path_id],
                terminal_state=HypothesisState.REJECTED,
                terminal_reason="candidate_not_retained",
            )
    for item in scoring.refinement.failures:
        paths[item.path.path_id] = item.path
    for item in scoring.evaluated:
        paths[item.path.path_id] = item.path

    representative_ids = {
        _component_representative(component).path.path_id
        for component in components
    }
    for component in components:
        representative = _component_representative(component)
        representative_id = representative.path.path_id
        for item in component:
            if item.path.path_id != representative_id:
                paths[item.path.path_id] = replace(
                    item.path,
                    terminal_state=HypothesisState.MERGED,
                    terminal_reason=f"merged_into:{representative_id}",
                )
    for representative_id in representative_ids:
        representative = paths[representative_id]
        if representative_id == selected_path_id:
            state = HypothesisState.SELECTED if accepted else HypothesisState.REJECTED
            reason = None if accepted else decisive_reason
        else:
            state = HypothesisState.REJECTED
            reason = decisive_reason if decisive_reason in {
                "ambiguous_equal_score", "ambiguous_hypotheses"
            } else "not_selected"
        paths[representative_id] = replace(
            representative, terminal_state=state, terminal_reason=reason
        )
    return tuple(paths.values())


class BoundedScipyRefiner:
    """Refine retained direct-image seeds with a fully explicit TRF contract."""

    def __init__(self, projector: ForwardProjector) -> None:
        self._projector = projector

    def refine(
        self,
        generation: HypothesisGenerationResult,
        record: ObservationRecord,
        template: VehicleTemplate,
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
        bounds: RefinementBounds,
    ) -> RefinementReport:
        require_validated_profile(token, profile, scope)
        if scipy.__version__ != scope.scipy_version:
            raise RefinementContractError(
                "scipy_runtime_mismatch",
                f"frozen SciPy {scope.scipy_version!r} does not match runtime {scipy.__version__!r}",
            )
        if scope.numeric_threads != 1:
            raise RefinementContractError(
                "unsupported_numeric_threads", "bounded refinement requires one numeric thread"
            )
        if scope.jacobian_method not in {"2-point", "3-point", "cs"}:
            raise RefinementContractError(
                "unsupported_derivative_method", f"unsupported Jacobian method {scope.jacobian_method!r}"
            )

        sampled = tuple(generation.hypotheses[: profile.optimizer.sampled_candidate_budget])
        retained = _retain_candidates(sampled, profile.optimizer.retained_candidate_count)
        retained_ids = {item.path.path_id for item in retained}
        refined: list[RefinedCandidate] = []
        failures: list[RefinementFailure] = []
        for candidate in retained:
            outcome = _refine_one(
                candidate, record, template, profile, scope, bounds, self._projector
            )
            if isinstance(outcome, RefinementFailure):
                failures.append(outcome)
            else:
                refined.append(outcome)
        return RefinementReport(
            generation=generation,
            sampled_path_ids=tuple(item.path.path_id for item in sampled),
            retained_path_ids=tuple(item.path.path_id for item in retained),
            refined=tuple(refined),
            failures=tuple(failures),
            skipped_path_ids=tuple(
                item.path.path_id for item in generation.hypotheses
                if item.path.path_id not in retained_ids
            ),
            deterministic_seed=profile.optimizer.deterministic_seed,
        )


__all__ = [
    "BoundedScipyRefiner",
    "CommonScoreComponents",
    "CommonSupportScorer",
    "FrozenRefinementSettings",
    "ObservabilityCalculationError",
    "ObservabilityEvaluation",
    "OrderedGateSelector",
    "RefinedCandidate",
    "RefinementBounds",
    "RefinementContractError",
    "RefinementFailure",
    "RefinementReport",
    "ScoredCandidate",
    "SupportDiagnostics",
    "SupportScoringReport",
    "compute_observability_from_linearization",
]
