"""Deterministic semantic paths and direct CCTV-pixel pose seeds.

Generation consumes normalized observations and the pure forward projector only.
The finite budget is reserved across every eligible semantic path and seed class,
then filled round-robin across canonical cue strata. Wheel/ground-contact seeds
are emitted first with exact zero height, but cannot consume non-wheel reserves.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from itertools import combinations, product
import math
from typing import Optional, Protocol, Sequence

import numpy as np
from scipy.optimize import least_squares

from trafficlab.motion.haware_accuracy.models import (
    AcceptanceProfile,
    CanonicalModel,
    ClosedInterval,
    Correspondence,
    CueFamily,
    HypothesisGenerationReport,
    HypothesisPath,
    HypothesisState,
    ImageObservation,
    InitializationSource,
    MinimalConfiguration,
    NuisanceVector,
    ObservationRecord,
    Pose2D,
    PoseSeed,
    SeedClass,
    SemanticPath,
    SemanticPathSpec,
    VehicleTemplate,
    canonical_bytes,
    canonical_order,
)
from trafficlab.motion.haware_accuracy.validation import (
    MvpScopeGuard,
    ValidatedProfile,
    require_validated_profile,
)
from trafficlab.projection.haware_forward import ForwardProjectionError, ForwardProjector


_GROUND_FAMILIES = frozenset((CueFamily.WHEEL, CueFamily.GROUND_CONTACT))
_SEMANTIC_ORDER = {
    SemanticPath.NORMAL: 0,
    SemanticPath.REVERSED: 1,
    SemanticPath.HEADING_PI: 2,
}


class HypothesisGenerationError(ValueError):
    """A deterministic generator contract or input failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, kw_only=True)
class SeedSearchCell(CanonicalModel):
    """One frozen bounded satellite-space start cell."""

    cell_id: str
    center_x_px: ClosedInterval
    center_y_px: ClosedInterval
    initial_center_sat_px: tuple[float, float]

    def __post_init__(self) -> None:
        center = tuple(self.initial_center_sat_px)
        if len(center) != 2:
            raise HypothesisGenerationError("invalid_seed_cell", "initial center must have two values")
        if not self.cell_id.strip():
            raise HypothesisGenerationError("invalid_seed_cell", "cell id must be non-empty")
        if not self.center_x_px.contains(center[0]) or not self.center_y_px.contains(center[1]):
            raise HypothesisGenerationError("invalid_seed_cell", "initial center must lie inside closed cell bounds")
        object.__setattr__(self, "initial_center_sat_px", center)
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class DirectSeedProfile(CanonicalModel):
    """Frozen finite starts and numerical settings for minimal equations."""

    search_cells: tuple[SeedSearchCell, ...]
    heading_starts_rad: tuple[float, ...]
    max_evaluations: int
    ftol: float
    xtol: float
    gtol: float
    finite_difference_step: float
    parameter_scale: tuple[float, float, float]

    def __post_init__(self) -> None:
        cells = tuple(sorted(self.search_cells, key=lambda item: item.cell_id))
        headings = tuple(self.heading_starts_rad)
        scales = tuple(self.parameter_scale)
        if not cells or len({cell.cell_id for cell in cells}) != len(cells):
            raise HypothesisGenerationError("invalid_direct_seed_profile", "search cells must be non-empty and uniquely named")
        if not headings or any(not math.isfinite(value) for value in headings):
            raise HypothesisGenerationError("invalid_direct_seed_profile", "heading starts must be finite and non-empty")
        if len(scales) != 3 or any(not math.isfinite(value) or value <= 0.0 for value in scales):
            raise HypothesisGenerationError("invalid_direct_seed_profile", "three finite positive parameter scales are required")
        numeric = (self.ftol, self.xtol, self.gtol, self.finite_difference_step)
        if self.max_evaluations <= 0 or any(not math.isfinite(value) or value <= 0.0 for value in numeric):
            raise HypothesisGenerationError("invalid_direct_seed_profile", "solver limits and tolerances must be explicit and positive")
        object.__setattr__(self, "search_cells", cells)
        object.__setattr__(self, "heading_starts_rad", headings)
        object.__setattr__(self, "parameter_scale", scales)
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class SeededHypothesis(CanonicalModel):
    """A path and finite pose produced from its direct minimal equations."""

    path: HypothesisPath
    seed: PoseSeed
    cue_heights_m: tuple[tuple[str, float], ...]
    residual_rms_px: float

    def __post_init__(self) -> None:
        heights = canonical_order(self.cue_heights_m)
        if self.seed.path_id != self.path.path_id:
            raise HypothesisGenerationError("seed_path_mismatch", "seed and path ids differ")
        if {identity for identity, _ in heights} != set(self.path.minimal_observations):
            raise HypothesisGenerationError("seed_height_mismatch", "every minimal observation requires one seed height")
        object.__setattr__(self, "cue_heights_m", heights)
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class HypothesisGenerationResult(CanonicalModel):
    """Budgeted seeds plus complete aggregate and attempted-path accounting."""

    report: HypothesisGenerationReport
    hypotheses: tuple[SeededHypothesis, ...]
    invalid_paths: tuple[HypothesisPath, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "hypotheses", tuple(self.hypotheses))
        object.__setattr__(self, "invalid_paths", canonical_order(self.invalid_paths))
        super().__post_init__()


class HypothesisGenerator(Protocol):
    def generate(
        self,
        observations: ObservationRecord,
        template: VehicleTemplate,
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
        seed_profile: DirectSeedProfile,
    ) -> HypothesisGenerationResult: ...


@dataclass(frozen=True)
class _Assignment:
    observations: tuple[ImageObservation, ...]
    semantic_ids: tuple[str, ...]
    cue_families: tuple[CueFamily, ...]


@dataclass(frozen=True)
class _Attempt:
    path: HypothesisPath
    observations: tuple[ImageObservation, ...]
    semantic_ids: tuple[str, ...]
    cue_families: tuple[CueFamily, ...]
    heights_m: tuple[float, ...]
    cell: SeedSearchCell
    start_heading_rad: float


def _semantic_specs(profile: AcceptanceProfile) -> tuple[SemanticPathSpec, ...]:
    return tuple(sorted(
        profile.optimizer.semantic_paths,
        key=lambda item: (_SEMANTIC_ORDER[item.semantic_path], item.canonical_bytes()),
    ))


def _label_mapping(profile: AcceptanceProfile) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, set[str]] = {}
    for candidate_label, template_semantic_id in profile.cue_evidence.semantic_mappings:
        grouped.setdefault(candidate_label, set()).add(template_semantic_id)
    return {
        label: tuple(sorted(semantic_ids))
        for label, semantic_ids in grouped.items()
    }


def _reversal_mapping(spec: SemanticPathSpec) -> dict[str, str]:
    result: dict[str, str] = {}
    for source, target in spec.front_rear_mapping:
        existing = result.get(source)
        if existing is not None and existing != target:
            raise HypothesisGenerationError(
                "ambiguous_reversal_mapping", f"{source!r} maps to multiple semantics"
            )
        result[source] = target
    return result


def _eligible_options(
    record: ObservationRecord,
    template: VehicleTemplate,
    profile: AcceptanceProfile,
    semantic_spec: SemanticPathSpec,
    configuration: MinimalConfiguration,
    seed_class: SeedClass,
) -> tuple[tuple[ImageObservation, tuple[str, ...]], ...]:
    template_by_id = {point.semantic_id: point for point in template.points}
    candidate_map = _label_mapping(profile)
    reversal = _reversal_mapping(semantic_spec)
    allowed_families = set(configuration.cue_families)
    result: list[tuple[ImageObservation, tuple[str, ...]]] = []
    for observation in record.observations:
        semantic_ids: set[str] = set()
        for label in observation.candidate_labels:
            for normal_semantic in candidate_map.get(label, ()):
                semantic_id = (
                    reversal.get(normal_semantic, normal_semantic)
                    if semantic_spec.semantic_path is SemanticPath.REVERSED
                    else normal_semantic
                )
                point = template_by_id.get(semantic_id)
                if point is None or point.cue_family not in allowed_families:
                    continue
                is_ground = point.cue_family in _GROUND_FAMILIES
                if (seed_class is SeedClass.WHEEL) != is_ground:
                    continue
                semantic_ids.add(semantic_id)
        if semantic_ids:
            result.append((observation, tuple(sorted(semantic_ids))))
    return tuple(result)


def _assignments(
    options: Sequence[tuple[ImageObservation, tuple[str, ...]]],
    minimum_support: int,
    template: VehicleTemplate,
) -> tuple[_Assignment, ...]:
    template_by_id = {point.semantic_id: point for point in template.points}
    assignments: list[_Assignment] = []
    for selected in combinations(options, minimum_support):
        observations = tuple(item[0] for item in selected)
        for semantic_ids in product(*(item[1] for item in selected)):
            if len(set(semantic_ids)) != len(semantic_ids):
                continue
            families = tuple(template_by_id[identity].cue_family for identity in semantic_ids)
            assignments.append(_Assignment(observations, tuple(semantic_ids), families))
    return tuple(sorted(
        assignments,
        key=lambda item: tuple(
            (observation.observation_id, semantic_id)
            for observation, semantic_id in zip(item.observations, item.semantic_ids)
        ),
    ))


def _height_for_family(profile: AcceptanceProfile, family: CueFamily) -> float:
    intervals = {
        spec.cue_family: spec.height_m for spec in profile.cue_evidence.height_specs
    }
    interval = intervals.get(family)
    if interval is None:
        raise HypothesisGenerationError(
            "missing_cue_height_evidence", f"no height evidence for {family.value}"
        )
    if family in _GROUND_FAMILIES:
        if interval.lower != 0.0 or interval.upper != 0.0:
            raise HypothesisGenerationError(
                "invalid_ground_contact_height", f"{family.value} must use exact [0,0]"
            )
        return 0.0
    return 0.5 * (interval.lower + interval.upper)


def _path_id(payload: object) -> str:
    return "hyp-" + hashlib.sha256(canonical_bytes(payload)).hexdigest()[:20]


def _attempts_for_class(
    record: ObservationRecord,
    template: VehicleTemplate,
    profile: AcceptanceProfile,
    seed_profile: DirectSeedProfile,
    seed_class: SeedClass,
) -> tuple[_Attempt, ...]:
    result: list[_Attempt] = []
    for semantic_spec in _semantic_specs(profile):
        for configuration in profile.optimizer.minimal_configurations:
            options = _eligible_options(
                record, template, profile, semantic_spec, configuration, seed_class
            )
            if len(options) < configuration.minimum_support:
                continue
            for assignment in _assignments(
                options, configuration.minimum_support, template
            ):
                cue_subset = canonical_order(assignment.cue_families, unique=True)
                heights = tuple(
                    _height_for_family(profile, family)
                    for family in assignment.cue_families
                )
                correspondences = tuple(
                    Correspondence(
                        observation_id=observation.observation_id,
                        template_semantic_id=semantic_id,
                        candidate_label_provenance=observation.candidate_labels,
                    )
                    for observation, semantic_id in zip(
                        assignment.observations, assignment.semantic_ids
                    )
                )
                for cell in seed_profile.search_cells:
                    for base_heading in seed_profile.heading_starts_rad:
                        start_heading = base_heading + (
                            math.pi
                            if semantic_spec.semantic_path is SemanticPath.HEADING_PI
                            else 0.0
                        )
                        identity_payload = {
                            "semantic_path": semantic_spec.semantic_path.value,
                            "configuration": configuration.configuration_id,
                            "seed_class": seed_class.value,
                            "correspondence": tuple(
                                (item.observation_id, item.template_semantic_id)
                                for item in correspondences
                            ),
                            "cue_subset": tuple(family.value for family in cue_subset),
                            "cell": cell.cell_id,
                            "start_heading": start_heading,
                        }
                        path_id = _path_id(identity_payload)
                        path = HypothesisPath(
                            path_id=path_id,
                            semantic_path=semantic_spec.semantic_path,
                            correspondence=correspondences,
                            cue_subset=cue_subset,
                            seed_class=seed_class,
                            minimal_observations=tuple(
                                observation.observation_id
                                for observation in assignment.observations
                            ),
                            initialization_source=InitializationSource(
                                method=f"direct_cctv_minimal:{configuration.configuration_id}",
                                observation_ids=tuple(
                                    observation.observation_id
                                    for observation in assignment.observations
                                ),
                                source_cell=cell.cell_id,
                                start_heading_rad=start_heading,
                            ),
                        )
                        result.append(_Attempt(
                            path=path,
                            observations=assignment.observations,
                            semantic_ids=assignment.semantic_ids,
                            cue_families=assignment.cue_families,
                            heights_m=heights,
                            cell=cell,
                            start_heading_rad=start_heading,
                        ))
    return tuple(result)


def _combination_key(attempt: _Attempt) -> tuple[int, tuple[str, ...], int]:
    """Canonical semantic/cue/seed stratum represented by one terminal state."""
    return (
        _SEMANTIC_ORDER[attempt.path.semantic_path],
        tuple(family.value for family in attempt.path.cue_subset),
        0 if attempt.path.seed_class is SeedClass.WHEEL else 1,
    )


def _attempt_key(attempt: _Attempt) -> tuple[object, ...]:
    source = attempt.path.initialization_source
    return (
        *_combination_key(attempt),
        attempt.path.minimal_observations,
        source.source_cell or "",
        source.start_heading_rad if source.start_heading_rad is not None else -math.inf,
        attempt.path.path_id,
    )


def _emission_key(attempt: _Attempt) -> tuple[object, ...]:
    """Wheel precedence is deliberately isolated to emission order."""
    return (
        0 if attempt.path.seed_class is SeedClass.WHEEL else 1,
        _attempt_key(attempt),
    )


def _allocate_attempts(
    attempts: Sequence[_Attempt], budget: int
) -> tuple[tuple[_Attempt, ...], dict[tuple[int, tuple[str, ...], int], tuple[_Attempt, ...]]]:
    """Reserve semantic/seed strata, then round-robin canonical cue strata."""
    groups: dict[tuple[int, tuple[str, ...], int], list[_Attempt]] = {}
    for attempt in sorted(attempts, key=_attempt_key):
        groups.setdefault(_combination_key(attempt), []).append(attempt)
    frozen_groups = {key: tuple(value) for key, value in groups.items()}

    selected_ids: set[str] = set()
    selected: list[_Attempt] = []

    # Profile validation reserves two slots per configured semantic path. At
    # record scope only eligible strata participate, so absent evidence does
    # not waste a slot. Selection order is semantic then seed class; wheel-first
    # is applied separately when the selected attempts are emitted.
    semantic_values = sorted({key[0] for key in frozen_groups})
    for semantic_value in semantic_values:
        for seed_value in (0, 1):
            candidates = tuple(
                attempt
                for key in sorted(frozen_groups)
                if key[0] == semantic_value and key[2] == seed_value
                for attempt in frozen_groups[key]
            )
            if not candidates:
                continue
            attempt = candidates[0]
            selected.append(attempt)
            selected_ids.add(attempt.path.path_id)

    if len(selected) > budget:
        raise HypothesisGenerationError(
            "insufficient_hypothesis_budget",
            "eligible semantic and seed-class reserves exceed the frozen budget",
        )

    queues = {
        key: [
            attempt for attempt in values
            if attempt.path.path_id not in selected_ids
        ]
        for key, values in frozen_groups.items()
    }
    remaining = budget - len(selected)
    while remaining > 0:
        progressed = False
        for key in sorted(queues):
            if remaining == 0:
                break
            if not queues[key]:
                continue
            attempt = queues[key].pop(0)
            selected.append(attempt)
            selected_ids.add(attempt.path.path_id)
            remaining -= 1
            progressed = True
        if not progressed:
            break

    return tuple(sorted(selected, key=_emission_key)), frozen_groups


def _solve_attempt(
    attempt: _Attempt,
    template: VehicleTemplate,
    calibration,
    projector: ForwardProjector,
    settings: DirectSeedProfile,
) -> tuple[Optional[Pose2D], float, Optional[str]]:
    template_by_id = {point.semantic_id: point for point in template.points}
    points = np.asarray(
        [
            (
                template_by_id[semantic_id].position_m[0],
                height,
                template_by_id[semantic_id].position_m[2],
            )
            for semantic_id, height in zip(attempt.semantic_ids, attempt.heights_m)
        ],
        dtype=np.float64,
    )
    observed = np.asarray(
        [observation.pixel for observation in attempt.observations], dtype=np.float64
    )
    invalid_residual = np.full(observed.size, 1.0e12, dtype=np.float64)

    def residual(values: np.ndarray) -> np.ndarray:
        pose = Pose2D(
            center_sat_px=(float(values[0]), float(values[1])),
            heading_rad_unwrapped=float(values[2]),
        )
        try:
            prediction = projector.predict_pixels(pose, points, calibration)
        except (ForwardProjectionError, ValueError, FloatingPointError):
            return invalid_residual
        if not prediction.valid.all() or not np.isfinite(prediction.pixels).all():
            return invalid_residual
        return (prediction.pixels - observed).reshape(-1)

    lower = np.asarray((
        attempt.cell.center_x_px.lower,
        attempt.cell.center_y_px.lower,
        attempt.start_heading_rad - math.pi,
    ))
    upper = np.asarray((
        attempt.cell.center_x_px.upper,
        attempt.cell.center_y_px.upper,
        attempt.start_heading_rad + math.pi,
    ))
    initial = np.asarray((
        attempt.cell.initial_center_sat_px[0],
        attempt.cell.initial_center_sat_px[1],
        attempt.start_heading_rad,
    ))
    try:
        fit = least_squares(
            residual,
            initial,
            bounds=(lower, upper),
            method="trf",
            ftol=settings.ftol,
            xtol=settings.xtol,
            gtol=settings.gtol,
            diff_step=settings.finite_difference_step,
            x_scale=np.asarray(settings.parameter_scale),
            max_nfev=settings.max_evaluations,
        )
    except (ValueError, FloatingPointError, np.linalg.LinAlgError) as error:
        return None, math.inf, f"direct_seed_solver_error:{type(error).__name__}"
    final_residual = residual(fit.x)
    if (
        not fit.success
        or not np.isfinite(fit.x).all()
        or not np.isfinite(final_residual).all()
        or np.array_equal(final_residual, invalid_residual)
    ):
        return None, math.inf, "direct_seed_not_converged"
    pose = Pose2D(
        center_sat_px=(float(fit.x[0]), float(fit.x[1])),
        heading_rad_unwrapped=float(fit.x[2]),
    )
    rms = float(np.sqrt(np.mean(final_residual * final_residual)))
    return pose, rms, None


class DirectImageHypothesisGenerator:
    """Generate deterministically budgeted paths in wheel-first emission order."""

    def __init__(self, projector: ForwardProjector) -> None:
        self._projector = projector

    def generate(
        self,
        observations: ObservationRecord,
        template: VehicleTemplate,
        *,
        token: ValidatedProfile,
        profile: AcceptanceProfile,
        scope: MvpScopeGuard,
        seed_profile: DirectSeedProfile,
    ) -> HypothesisGenerationResult:
        require_validated_profile(token, profile, scope)
        if observations.site != profile.cue_evidence.site:
            raise HypothesisGenerationError(
                "cue_evidence_site_mismatch",
                f"record site {observations.site!r} does not match cue evidence",
            )
        if not template.points:
            raise HypothesisGenerationError("empty_vehicle_template", "template has no points")

        all_attempts = (
            _attempts_for_class(
                observations, template, profile, seed_profile, SeedClass.WHEEL
            )
            + _attempts_for_class(
                observations, template, profile, seed_profile, SeedClass.NON_WHEEL
            )
        )
        attempts, combination_groups = _allocate_attempts(
            all_attempts, profile.optimizer.hypothesis_budget
        )

        generated: list[HypothesisPath] = []
        invalid: list[HypothesisPath] = []
        hypotheses: list[SeededHypothesis] = []
        stable_order: list[str] = []
        terminal_by_path_id: dict[str, HypothesisPath] = {}
        ordinal = 0
        for attempt in attempts:
            pose, rms, reason = _solve_attempt(
                attempt,
                template,
                profile.calibration.snapshot,
                self._projector,
                seed_profile,
            )
            stable_order.append(attempt.path.path_id)
            if pose is None:
                invalid_path = replace(
                    attempt.path,
                    terminal_state=HypothesisState.INVALID,
                    terminal_reason=reason,
                )
                invalid.append(invalid_path)
                terminal_by_path_id[attempt.path.path_id] = invalid_path
                continue
            seed = PoseSeed(
                pose=pose,
                nuisance=NuisanceVector(values=()),
                path_id=attempt.path.path_id,
                generation_ordinal=ordinal,
            )
            ordinal += 1
            generated.append(attempt.path)
            terminal_by_path_id[attempt.path.path_id] = attempt.path
            hypotheses.append(SeededHypothesis(
                path=attempt.path,
                seed=seed,
                cue_heights_m=tuple(
                    (observation.observation_id, height)
                    for observation, height in zip(
                        attempt.observations, attempt.heights_m
                    )
                ),
                residual_rms_px=rms,
            ))

        selected_ids = set(stable_order)
        authorized: list[HypothesisPath] = []
        budget_exclusions: list[HypothesisPath] = []
        for key in sorted(combination_groups):
            group = combination_groups[key]
            selected_group = tuple(
                attempt for attempt in group
                if attempt.path.path_id in selected_ids
            )
            if not selected_group:
                excluded = replace(
                    group[0].path,
                    terminal_state=HypothesisState.BUDGET_EXCLUDED,
                    terminal_reason="hypothesis_budget_exceeded",
                )
                authorized.append(excluded)
                budget_exclusions.append(excluded)
                continue

            successful = tuple(
                attempt for attempt in selected_group
                if terminal_by_path_id[attempt.path.path_id].terminal_state
                is HypothesisState.GENERATED
            )
            representative = successful[0] if successful else selected_group[0]
            authorized.append(terminal_by_path_id[representative.path.path_id])

        report = HypothesisGenerationReport(
            authorized_paths=tuple(authorized),
            generated_paths=tuple(generated),
            budget_exclusions=tuple(budget_exclusions),
            stable_order=tuple(stable_order),
        )
        return HypothesisGenerationResult(
            report=report,
            hypotheses=tuple(hypotheses),
            invalid_paths=tuple(invalid),
        )


__all__ = [
    "DirectImageHypothesisGenerator",
    "DirectSeedProfile",
    "HypothesisGenerationError",
    "HypothesisGenerationResult",
    "HypothesisGenerator",
    "SeedSearchCell",
    "SeededHypothesis",
]
