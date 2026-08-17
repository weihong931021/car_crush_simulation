"""Immutable held-out access, final decisions, and default-off evidence.

This module is the sole held-out outcome boundary. It verifies a complete
pilot-derived freeze before invoking an outcome loader, permits one attempt per
final-decision identity, and permanently records every exposed partition.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable, Iterable, Mapping, Optional

from trafficlab.measurement.haware_pilot import (
    ACCEPTANCE_SITES,
    MEDIAN_ERROR_EFFECT,
    P90_ERROR_EFFECT,
    USABLE_COVERAGE_EFFECT,
    CandidateThresholds,
    ClusteredEffectInterval,
    FrozenEligibleDetection,
    FrozenPilotEvidence,
    FrozenPilotRuns,
    FrozenPilotStatistics,
    FrozenSiteStatisticsMethod,
    PilotArm,
    PilotCandidateConfiguration,
    PilotConfigurationStatistics,
    PilotEvidenceError,
    PilotRunIdentity,
    RequiredViewCoverage,
    ViewCoverage,
    _effect_interval,
    _metric_values,
    _outcome_view,
    _signed_effect,
    _support_identity,
    decide_pilot_feasibility,
)
from trafficlab.motion.haware_accuracy.models import (
    AcceptanceProfile,
    CanonicalModel,
    ContentIdentity,
    DecisionStatus,
    PartitionKind,
    PilotDecision,
    PopulationPartition,
    SiteDecision,
    canonical_order,
)
from trafficlab.motion.haware_accuracy.validation import (
    DispatchAuthorization,
    MvpScopeGuard,
    ValidatedProfile,
    require_validated_profile,
)

HELD_OUT_ACCESS_DENIED = "held_out_access_denied"


class HeldOutAccessError(PilotEvidenceError):
    """Deterministic held-out access or identity failure."""


@dataclass(frozen=True, kw_only=True)
class HeldOutCandidateManifest(CanonicalModel):
    site: str
    candidate_configuration: PilotCandidateConfiguration
    profile_snapshot: AcceptanceProfile
    pilot_run_identity: PilotRunIdentity

    def __post_init__(self) -> None:
        run = self.pilot_run_identity
        profile = self.profile_snapshot
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError("held_out_candidate_site_invalid")
        if run.site != self.site or profile.cue_evidence.site != self.site:
            raise ValueError("held_out_candidate_site_mismatch")
        if run.arm is not PilotArm.FULL_OPTIMIZER:
            raise ValueError("held_out_candidate_must_be_full_optimizer")
        if run.candidate_configuration != self.candidate_configuration:
            raise ValueError("held_out_candidate_configuration_mismatch")
        if self.candidate_configuration.optimizer_profile != profile.optimizer.content_identity:
            raise ValueError("held_out_optimizer_profile_identity_mismatch")
        if run.run.profile != profile.content_identity:
            raise ValueError("held_out_profile_identity_mismatch")
        if run.run.calibration != profile.calibration.content_identity:
            raise ValueError("held_out_calibration_identity_mismatch")
        if run.run.cue_evidence != profile.cue_evidence.content_identity:
            raise ValueError("held_out_cue_identity_mismatch")
        if run.run.nuisance != profile.nuisance.content_identity:
            raise ValueError("held_out_nuisance_identity_mismatch")
        if run.scoring != profile.optimizer.robust.content_identity:
            raise ValueError("held_out_scoring_identity_mismatch")
        if run.support_rules != _support_identity(profile):
            raise ValueError("held_out_support_identity_mismatch")
        if run.gates != profile.optimizer.content_identity:
            raise ValueError("held_out_gate_identity_mismatch")
        if run.metric_definitions != profile.pilot_policy.content_identity:
            raise ValueError("held_out_metric_identity_mismatch")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class HeldOutCandidateIdentity(CanonicalModel):
    sites: tuple[HeldOutCandidateManifest, ...]

    def __post_init__(self) -> None:
        by_site = {value.site: value for value in self.sites}
        if len(by_site) != len(self.sites) or set(by_site) != set(ACCEPTANCE_SITES):
            raise ValueError("held_out_candidate_sites_incomplete")
        object.__setattr__(self, "sites", tuple(by_site[site] for site in ACCEPTANCE_SITES))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class HeldOutPartitionSnapshot(CanonicalModel):
    site: str
    population_identity: ContentIdentity
    partition: PopulationPartition
    ordered_eligible_ids: tuple[str, ...]
    real_track_ids: tuple[str, ...]
    independent_view_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError("held_out_partition_site_invalid")
        if self.partition.kind is not PartitionKind.HELD_OUT:
            raise ValueError("held_out_partition_kind_invalid")
        object.__setattr__(self, "ordered_eligible_ids", tuple(self.ordered_eligible_ids))
        object.__setattr__(self, "real_track_ids", canonical_order(self.real_track_ids, unique=True))
        object.__setattr__(self, "independent_view_ids", canonical_order(self.independent_view_ids, unique=True))
        if self.ordered_eligible_ids != self.partition.eligible_detection_ids:
            raise ValueError("held_out_partition_order_mismatch")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class FrozenHeldOutSitePolicy(CanonicalModel):
    site: str
    thresholds: CandidateThresholds
    effect_interval_rules: tuple[tuple[str, str], ...]
    required_sample_count: int
    required_genuine_track_count: int
    required_view_coverage: tuple[RequiredViewCoverage, ...]
    pilot_threshold_evidence: PilotConfigurationStatistics
    decision_rationale: tuple[str, ...]
    source_partition: PartitionKind = PartitionKind.PILOT

    def __post_init__(self) -> None:
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError("held_out_policy_site_invalid")
        if self.source_partition is not PartitionKind.PILOT:
            raise ValueError("held_out_threshold_rationale_leak")
        evidence = self.pilot_threshold_evidence
        if evidence.site != self.site:
            raise ValueError("held_out_threshold_evidence_site_mismatch")
        if evidence.arm is not PilotArm.FULL_OPTIMIZER:
            raise ValueError("held_out_threshold_evidence_arm_invalid")
        thresholds = self.thresholds
        if any(value is None for value in (
            thresholds.maximum_median_error_m,
            thresholds.maximum_p90_error_m,
            thresholds.minimum_usable_coverage,
        )):
            raise ValueError("held_out_thresholds_incomplete")
        if self.required_sample_count <= 0 or self.required_genuine_track_count <= 0:
            raise ValueError("held_out_sufficiency_incomplete")
        object.__setattr__(self, "effect_interval_rules", tuple(self.effect_interval_rules))
        object.__setattr__(self, "required_view_coverage", canonical_order(self.required_view_coverage))
        object.__setattr__(self, "decision_rationale", canonical_order(self.decision_rationale, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class FrozenHeldOutAcceptanceProfile(CanonicalModel):
    candidate: HeldOutCandidateIdentity
    pilot_decision_identity: ContentIdentity
    statistics_method_identity: ContentIdentity
    candidates: tuple[HeldOutCandidateManifest, ...]
    partitions: tuple[HeldOutPartitionSnapshot, ...]
    site_policies: tuple[FrozenHeldOutSitePolicy, ...]

    def __post_init__(self) -> None:
        def ordered(values: tuple[Any, ...]) -> tuple[Any, ...]:
            by_site = {value.site: value for value in values}
            if len(by_site) != len(values) or set(by_site) != set(ACCEPTANCE_SITES):
                raise ValueError("held_out_freeze_sites_incomplete")
            return tuple(by_site[site] for site in ACCEPTANCE_SITES)
        object.__setattr__(self, "candidates", ordered(self.candidates))
        object.__setattr__(self, "partitions", ordered(self.partitions))
        object.__setattr__(self, "site_policies", ordered(self.site_policies))
        if self.candidate.sites != self.candidates:
            raise ValueError("held_out_candidate_identity_mismatch")
        super().__post_init__()

    def for_site(self, site: str) -> FrozenHeldOutSitePolicy:
        if site not in ACCEPTANCE_SITES:
            raise KeyError(site)
        return next(value for value in self.site_policies if value.site == site)

    def partition_for_site(self, site: str) -> HeldOutPartitionSnapshot:
        if site not in ACCEPTANCE_SITES:
            raise KeyError(site)
        return next(value for value in self.partitions if value.site == site)


@dataclass(frozen=True, kw_only=True)
class HeldOutAccessGrant(CanonicalModel):
    acceptance_profile: FrozenHeldOutAcceptanceProfile
    final_decision_identity: ContentIdentity

    def __post_init__(self) -> None:
        if self.final_decision_identity != self.acceptance_profile.content_identity:
            raise ValueError("final_decision_identity_mismatch")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class HeldOutOutcomeBatch:
    site: str
    final_decision_identity: ContentIdentity
    partition_identity: ContentIdentity
    ordered_eligible_ids: tuple[str, ...]
    baseline_outcomes: tuple[Any, ...]
    candidate_outcomes: tuple[Any, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordered_eligible_ids", tuple(self.ordered_eligible_ids))
        object.__setattr__(self, "baseline_outcomes", tuple(self.baseline_outcomes))
        object.__setattr__(self, "candidate_outcomes", tuple(self.candidate_outcomes))


@dataclass(frozen=True, kw_only=True)
class HeldOutSiteReport(CanonicalModel):
    site: str
    status: DecisionStatus
    denominator: int
    accepted_count: int
    rejected_count: int
    median_error_m: Optional[float]
    p90_error_m: Optional[float]
    usable_coverage: float
    signed_effects: tuple[tuple[str, Optional[float]], ...]
    effect_intervals: tuple[tuple[str, ClusteredEffectInterval], ...]
    genuine_track_count: int
    independent_view_coverage: tuple[ViewCoverage, ...]
    evidence_gaps: tuple[str, ...]
    failed_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError("held_out_report_site_invalid")
        object.__setattr__(self, "signed_effects", tuple(self.signed_effects))
        object.__setattr__(self, "effect_intervals", tuple(self.effect_intervals))
        object.__setattr__(self, "independent_view_coverage", canonical_order(self.independent_view_coverage))
        object.__setattr__(self, "evidence_gaps", canonical_order(self.evidence_gaps, unique=True))
        object.__setattr__(self, "failed_conditions", canonical_order(self.failed_conditions, unique=True))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class HeldOutFinalDecision(CanonicalModel):
    final_decision_identity: ContentIdentity
    candidate_identity: ContentIdentity
    kee_cc: HeldOutSiteReport
    taoyuan_tc: HeldOutSiteReport
    overall: DecisionStatus
    evidence_gaps: tuple[str, ...]
    failed_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        if (self.kee_cc.site, self.taoyuan_tc.site) != ACCEPTANCE_SITES:
            raise ValueError("held_out_decision_sites_incomplete")
        object.__setattr__(self, "evidence_gaps", canonical_order(self.evidence_gaps, unique=True))
        object.__setattr__(self, "failed_conditions", canonical_order(self.failed_conditions, unique=True))
        super().__post_init__()


def _site_full_run(frozen_runs: FrozenPilotRuns, site: str):
    return next(
        value for value in frozen_runs.for_site(site).arms
        if value.identity.arm is PilotArm.FULL_OPTIMIZER
    )


def _held_out_detections(
    frozen_evidence: FrozenPilotEvidence, site: str
) -> tuple[FrozenEligibleDetection, ...]:
    return tuple(
        value for value in frozen_evidence.for_site(site).eligible_detections
        if value.partition is PartitionKind.HELD_OUT
    )


def freeze_held_out_acceptance(
    *,
    pilot_decision: PilotDecision,
    statistics: FrozenPilotStatistics,
    frozen_runs: FrozenPilotRuns,
    frozen_evidence: FrozenPilotEvidence,
    profiles: Mapping[str, AcceptanceProfile],
    validated_profiles: Mapping[str, ValidatedProfile],
    scope: MvpScopeGuard,
) -> HeldOutAccessGrant:
    """Freeze all pilot-derived identity and policy content before outcomes."""
    if set(profiles) != set(ACCEPTANCE_SITES) or set(validated_profiles) != set(ACCEPTANCE_SITES):
        raise HeldOutAccessError("held_out_profile_sites_invalid")
    if statistics.method != frozen_runs.statistics_method:
        raise HeldOutAccessError("held_out_statistics_method_mismatch")
    expected_decision = decide_pilot_feasibility(
        statistics=statistics, frozen_runs=frozen_runs
    )
    if expected_decision != pilot_decision:
        raise HeldOutAccessError("pilot_decision_identity_mismatch")
    if (
        pilot_decision.overall is not DecisionStatus.GO
        or pilot_decision.kee_cc.status is not DecisionStatus.GO
        or pilot_decision.taoyuan_tc.status is not DecisionStatus.GO
    ):
        raise HeldOutAccessError("pilot_dual_site_go_required")

    candidates: list[HeldOutCandidateManifest] = []
    partitions: list[HeldOutPartitionSnapshot] = []
    policies: list[FrozenHeldOutSitePolicy] = []
    for site in ACCEPTANCE_SITES:
        profile = profiles[site]
        try:
            require_validated_profile(validated_profiles[site], profile, scope)
        except (ValueError, TypeError) as error:
            raise HeldOutAccessError("held_out_identity_verification_incomplete", site=site) from error
        if profile.cue_evidence.site != site:
            raise HeldOutAccessError("held_out_profile_site_mismatch", site=site)
        full = _site_full_run(frozen_runs, site)
        candidates.append(
            HeldOutCandidateManifest(
                site=site,
                candidate_configuration=full.identity.candidate_configuration,
                profile_snapshot=profile,
                pilot_run_identity=full.identity,
            )
        )

        evidence = frozen_evidence.for_site(site)
        held_partition = next(
            (value for value in evidence.population.partitions if value.kind is PartitionKind.HELD_OUT),
            None,
        )
        if held_partition is None:
            raise HeldOutAccessError("held_out_partition_identity_incomplete", site=site)
        held = _held_out_detections(frozen_evidence, site)
        held_ids = tuple(value.eligible_detection_id for value in held)
        if held_ids != held_partition.eligible_detection_ids:
            raise HeldOutAccessError("held_out_partition_identity_mismatch", site=site)
        pilot_ids = {
            value.eligible_detection_id
            for value in evidence.eligible_detections
            if value.partition is PartitionKind.PILOT
        }
        if pilot_ids.intersection(held_ids):
            raise HeldOutAccessError("pilot_held_out_partition_overlap", site=site)
        partitions.append(
            HeldOutPartitionSnapshot(
                site=site,
                population_identity=evidence.population.content_identity,
                partition=held_partition,
                ordered_eligible_ids=held_ids,
                real_track_ids=tuple(value.real_track_id for value in held),
                independent_view_ids=tuple(value.independent_view_id for value in held),
            )
        )

        report = statistics.for_site(site).for_arm(PilotArm.FULL_OPTIMIZER)
        thresholds = report.candidate_thresholds
        power = report.power_sufficiency
        if thresholds is None:
            raise HeldOutAccessError("held_out_thresholds_incomplete", site=site)
        if (
            power is None
            or power.required_sample_count is None
            or power.required_genuine_track_count is None
        ):
            raise HeldOutAccessError("held_out_sufficiency_freeze_incomplete", site=site)
        policies.append(
            FrozenHeldOutSitePolicy(
                site=site,
                thresholds=thresholds,
                effect_interval_rules=statistics.method.for_site(site).feasibility_rules,
                required_sample_count=power.required_sample_count,
                required_genuine_track_count=power.required_genuine_track_count,
                required_view_coverage=power.required_view_coverage,
                pilot_threshold_evidence=report,
                decision_rationale=(
                    "pilot_dual_site_go",
                    f"pilot_site_status:{DecisionStatus.GO.value}",
                    f"threshold_derivation:{thresholds.derivation}",
                    f"power_method:{power.method}",
                ),
            )
        )

    candidate = HeldOutCandidateIdentity(sites=tuple(candidates))
    acceptance = FrozenHeldOutAcceptanceProfile(
        candidate=candidate,
        pilot_decision_identity=pilot_decision.content_identity,
        statistics_method_identity=statistics.method.content_identity,
        candidates=tuple(candidates),
        partitions=tuple(partitions),
        site_policies=tuple(policies),
    )
    return HeldOutAccessGrant(
        acceptance_profile=acceptance,
        final_decision_identity=acceptance.content_identity,
    )


def verify_held_out_access(
    *,
    grant: HeldOutAccessGrant,
    pilot_decision: PilotDecision,
    statistics: FrozenPilotStatistics,
    frozen_runs: FrozenPilotRuns,
    frozen_evidence: FrozenPilotEvidence,
    profiles: Mapping[str, AcceptanceProfile],
    validated_profiles: Mapping[str, ValidatedProfile],
    scope: MvpScopeGuard,
) -> None:
    try:
        expected = freeze_held_out_acceptance(
            pilot_decision=pilot_decision,
            statistics=statistics,
            frozen_runs=frozen_runs,
            frozen_evidence=frozen_evidence,
            profiles=profiles,
            validated_profiles=validated_profiles,
            scope=scope,
        )
    except HeldOutAccessError:
        raise
    except (ValueError, TypeError) as error:
        raise HeldOutAccessError("held_out_identity_verification_incomplete") from error
    if expected != grant:
        raise HeldOutAccessError("held_out_identity_verification_failed")


def _batch_map(
    grant: HeldOutAccessGrant, values: Iterable[HeldOutOutcomeBatch]
) -> dict[str, HeldOutOutcomeBatch]:
    batches = tuple(values)
    if tuple(sorted(value.site for value in batches)) != ACCEPTANCE_SITES:
        raise HeldOutAccessError("held_out_outcome_sites_invalid")
    result: dict[str, HeldOutOutcomeBatch] = {}
    for batch in batches:
        if batch.site in result:
            raise HeldOutAccessError("held_out_outcome_sites_invalid")
        partition = grant.acceptance_profile.partition_for_site(batch.site)
        if batch.final_decision_identity != grant.final_decision_identity:
            raise HeldOutAccessError("held_out_outcome_decision_identity_mismatch", site=batch.site)
        if batch.partition_identity != partition.partition.content_identity:
            raise HeldOutAccessError("held_out_outcome_partition_identity_mismatch", site=batch.site)
        if batch.ordered_eligible_ids != partition.ordered_eligible_ids:
            raise HeldOutAccessError("held_out_outcome_order_mismatch", site=batch.site)
        count = len(partition.ordered_eligible_ids)
        if len(batch.baseline_outcomes) != count or len(batch.candidate_outcomes) != count:
            raise HeldOutAccessError("held_out_outcome_count_mismatch", site=batch.site)
        result[batch.site] = batch
    return result


def _rule_failure(
    name: str, rule: str, interval: ClusteredEffectInterval
) -> Optional[str]:
    if rule == "estimate_gte_0_and_interval_lower_gte_0":
        if interval.estimate is None or interval.estimate < 0.0:
            return f"{name}:estimate_degrades_coverage"
        if interval.lower is None or interval.lower < 0.0:
            return f"{name}:interval_allows_coverage_degradation"
        return None
    if rule == "estimate_lt_0_and_interval_upper_lt_0":
        if interval.estimate is None or interval.estimate >= 0.0:
            return f"{name}:estimate_not_improved"
        if interval.upper is None or interval.upper >= 0.0:
            return f"{name}:interval_does_not_support_improvement"
        return None
    raise HeldOutAccessError("unsupported_held_out_effect_rule")


def _site_report(
    *,
    grant: HeldOutAccessGrant,
    site: str,
    batch: HeldOutOutcomeBatch,
    evidence: FrozenPilotEvidence,
    method: FrozenSiteStatisticsMethod,
) -> HeldOutSiteReport:
    policy = grant.acceptance_profile.for_site(site)
    manifest = next(value for value in grant.acceptance_profile.candidates if value.site == site)
    profile = manifest.profile_snapshot
    detections = _held_out_detections(evidence, site)
    indices = tuple(range(len(detections)))
    baseline = tuple(
        _outcome_view(value, arm=PilotArm.CORRECTED_BASELINE, profile=profile)
        for value in batch.baseline_outcomes
    )
    candidate = tuple(
        _outcome_view(value, arm=PilotArm.FULL_OPTIMIZER, profile=profile)
        for value in batch.candidate_outcomes
    )
    scale = profile.calibration.snapshot.pixels_per_metre
    baseline_metrics = _metric_values(indices, baseline, detections, scale)
    candidate_metrics = _metric_values(indices, candidate, detections, scale)
    effects = {
        name: _signed_effect(candidate_metrics, baseline_metrics, name)
        for name in (MEDIAN_ERROR_EFFECT, P90_ERROR_EFFECT, USABLE_COVERAGE_EFFECT)
    }
    intervals = {
        name: _effect_interval(
            effect_name=name,
            estimate=effects[name],
            candidate=candidate,
            baseline=baseline,
            detections=detections,
            pilot_indices=indices,
            pixels_per_metre=scale,
            method=method,
        )
        for name in (MEDIAN_ERROR_EFFECT, P90_ERROR_EFFECT, USABLE_COVERAGE_EFFECT)
    }

    failures: list[str] = []
    gaps: list[str] = []
    thresholds = policy.thresholds
    for name, value, boundary, direction in (
        (MEDIAN_ERROR_EFFECT, candidate_metrics.median_error, thresholds.maximum_median_error_m, "maximum"),
        (P90_ERROR_EFFECT, candidate_metrics.p90_error, thresholds.maximum_p90_error_m, "maximum"),
        (USABLE_COVERAGE_EFFECT, candidate_metrics.coverage, thresholds.minimum_usable_coverage, "minimum"),
    ):
        if value is None:
            gaps.append(f"{name}:held_out_metric_unavailable")
        elif boundary is None:
            gaps.append(f"{name}:frozen_threshold_unavailable")
        elif direction == "maximum" and value > boundary:
            failures.append(f"{name}:frozen_threshold_failed")
        elif direction == "minimum" and value < boundary:
            failures.append(f"{name}:frozen_threshold_failed")

    for name, rule in policy.effect_interval_rules:
        interval = intervals[name]
        if interval.status is not DecisionStatus.GO:
            gaps.append(f"{name}:held_out_effect_interval_insufficient_data")
            continue
        failure = _rule_failure(name, rule, interval)
        if failure is not None:
            failures.append(failure)

    track_count = len({value.real_track_id for value in detections})
    if len(detections) < policy.required_sample_count:
        gaps.append("eligible_sample_coverage_below_frozen_requirement")
    if track_count < policy.required_genuine_track_count:
        gaps.append("genuine_track_coverage_below_frozen_requirement")
    view_counts: dict[str, int] = {}
    accepted_by_view: dict[str, int] = {}
    for index, detection in enumerate(detections):
        view = detection.independent_view_id
        view_counts[view] = view_counts.get(view, 0) + 1
        accepted_by_view.setdefault(view, 0)
        if candidate[index].accepted:
            accepted_by_view[view] += 1
    for required in policy.required_view_coverage:
        if view_counts.get(required.view_id, 0) < required.required_count:
            gaps.append(f"independent_view_coverage_below_frozen_requirement:{required.view_id}")
    view_coverage = tuple(
        ViewCoverage(
            view_id=view,
            eligible_count=count,
            accepted_count=accepted_by_view[view],
            usable_coverage=accepted_by_view[view] / count,
        )
        for view, count in sorted(view_counts.items())
    )
    status = (
        DecisionStatus.NO_GO
        if failures
        else DecisionStatus.INSUFFICIENT_DATA
        if gaps
        else DecisionStatus.GO
    )
    return HeldOutSiteReport(
        site=site,
        status=status,
        denominator=len(detections),
        accepted_count=candidate_metrics.accepted_count,
        rejected_count=len(detections) - candidate_metrics.accepted_count,
        median_error_m=candidate_metrics.median_error,
        p90_error_m=candidate_metrics.p90_error,
        usable_coverage=candidate_metrics.coverage,
        signed_effects=tuple((name, effects[name]) for name in effects),
        effect_intervals=tuple((name, intervals[name]) for name in intervals),
        genuine_track_count=track_count,
        independent_view_coverage=view_coverage,
        evidence_gaps=tuple(gaps),
        failed_conditions=tuple(failures),
    )


class HeldOutDecisionController:
    """Thread-safe one-decision and never-reuse exposure controller."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempted: set[ContentIdentity] = set()
        self._exposed_partitions: set[ContentIdentity] = set()
        self._decisions: dict[ContentIdentity, HeldOutFinalDecision] = {}

    def evaluate(
        self,
        *,
        grant: HeldOutAccessGrant,
        pilot_decision: PilotDecision,
        statistics: FrozenPilotStatistics,
        frozen_runs: FrozenPilotRuns,
        frozen_evidence: FrozenPilotEvidence,
        profiles: Mapping[str, AcceptanceProfile],
        validated_profiles: Mapping[str, ValidatedProfile],
        scope: MvpScopeGuard,
        outcome_loader: Callable[[HeldOutAccessGrant], Iterable[HeldOutOutcomeBatch]],
        diagnostic_values: Optional[Mapping[str, Any]] = None,
    ) -> HeldOutFinalDecision:
        """Verify atomically, expose once, then apply site-local precedence."""
        del diagnostic_values
        verify_held_out_access(
            grant=grant,
            pilot_decision=pilot_decision,
            statistics=statistics,
            frozen_runs=frozen_runs,
            frozen_evidence=frozen_evidence,
            profiles=profiles,
            validated_profiles=validated_profiles,
            scope=scope,
        )
        partition_ids = tuple(
            value.partition.content_identity
            for value in grant.acceptance_profile.partitions
        )
        with self._lock:
            if grant.final_decision_identity in self._attempted:
                raise HeldOutAccessError("final_decision_identity_already_evaluated")
            reused = next(
                (value for value in grant.acceptance_profile.partitions
                 if value.partition.content_identity in self._exposed_partitions),
                None,
            )
            if reused is not None:
                raise HeldOutAccessError("held_out_partition_previously_exposed", site=reused.site)
            # Exposure begins at loader invocation. Burn both the identity and
            # partitions before invoking external outcome code, even on failure.
            self._attempted.add(grant.final_decision_identity)
            self._exposed_partitions.update(partition_ids)

        try:
            batches = _batch_map(grant, outcome_loader(grant))
            reports = {
                site: _site_report(
                    grant=grant,
                    site=site,
                    batch=batches[site],
                    evidence=frozen_evidence,
                    method=statistics.method.for_site(site),
                )
                for site in ACCEPTANCE_SITES
            }
        except HeldOutAccessError:
            raise
        except Exception as error:
            raise HeldOutAccessError("held_out_outcome_evaluation_failed") from error

        statuses = tuple(reports[site].status for site in ACCEPTANCE_SITES)
        overall = (
            DecisionStatus.NO_GO
            if DecisionStatus.NO_GO in statuses
            else DecisionStatus.INSUFFICIENT_DATA
            if DecisionStatus.INSUFFICIENT_DATA in statuses
            else DecisionStatus.GO
        )
        decision = HeldOutFinalDecision(
            final_decision_identity=grant.final_decision_identity,
            candidate_identity=grant.acceptance_profile.candidate.content_identity,
            kee_cc=reports["kee-cc"],
            taoyuan_tc=reports["taoyuan-tc"],
            overall=overall,
            evidence_gaps=tuple(
                f"{site}:{gap}"
                for site in ACCEPTANCE_SITES
                for gap in reports[site].evidence_gaps
            ),
            failed_conditions=tuple(
                f"{site}:{failure}"
                for site in ACCEPTANCE_SITES
                for failure in reports[site].failed_conditions
            ),
        )
        with self._lock:
            self._decisions[grant.final_decision_identity] = decision
        return decision

    def decision_for(
        self, final_decision_identity: ContentIdentity
    ) -> Optional[HeldOutFinalDecision]:
        with self._lock:
            return self._decisions.get(final_decision_identity)


def default_off_dispatch_evidence(
    decision: HeldOutFinalDecision,
) -> Optional[DispatchAuthorization]:
    reports = (decision.kee_cc, decision.taoyuan_tc)
    if decision.overall is not DecisionStatus.GO or any(
        value.status is not DecisionStatus.GO for value in reports
    ):
        return None
    return DispatchAuthorization(
        candidate_identity=decision.candidate_identity,
        held_out_site_decisions=tuple(
            SiteDecision(site=value.site, status=value.status) for value in reports
        ),
        hardening_reviewed=False,
        hardening_authorized=False,
        hardening_candidate_identity=None,
        hardening_scope=(),
    )