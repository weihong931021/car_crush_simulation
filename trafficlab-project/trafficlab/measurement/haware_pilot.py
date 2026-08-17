"""Outcome-blind evidence freezing, orchestration, and Haware pilot statistics.

Complete replay records, independent ground truth, view strata, and
leakage-control assignments are frozen before outcomes.  The run boundary also
materializes the versioned clustered interval/power method before invoking any
localizer; statistics are then computed only from the frozen pilot partition.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import Enum
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
from statistics import NormalDist
from typing import Any, Callable, Iterable, Mapping, Optional

from trafficlab.io.haware_track_provenance import finalize_track_provenance
from trafficlab.motion.haware_accuracy.models import (
    AcceptanceProfile,
    CanonicalModel,
    ClosedInterval,
    ContentIdentity,
    DecisionStatus,
    GroundTruthRecord,
    LocalizationResult,
    LocalizationStatus,
    ObservationRecord,
    PartitionKind,
    PilotDecision,
    PilotPopulation,
    PopulationPartition,
    RunIdentity,
    SeedClass,
    SiteDecision,
    TrackKind,
    canonical_order,
)
from trafficlab.motion.haware_accuracy.validation import (
    MvpScopeGuard,
    ValidatedProfile,
    require_validated_profile,
    resolve_optimizer_dispatch,
)
from trafficlab.motion.haware_baseline_dispatch import FrozenBaselineIdentity


ACCEPTANCE_SITES = ("kee-cc", "taoyuan-tc")
DIAGNOSTIC_SITE = "taipei-cm"
TRACK_GROUP = "real_track"
SOURCE_GROUP = "source_sequence"

GROUND_TRUTH_CONTAMINATION = "ground_truth_contamination"
GROUND_TRUTH_INDEPENDENCE_UNVERIFIED = "ground_truth_independence_unverified"
GROUND_TRUTH_COORDINATE_INVALID = "ground_truth_coordinate_invalid"
GROUND_TRUTH_UNCERTAINTY_INVALID = "ground_truth_uncertainty_invalid"
GROUND_TRUTH_REFERENCE_POINT_INVALID = "ground_truth_reference_point_invalid"
GROUND_TRUTH_COORDINATE_FRAME_MISMATCH = "ground_truth_coordinate_frame_mismatch"
GROUND_TRUTH_UNITS_INVALID = "ground_truth_units_invalid"
GROUND_TRUTH_DUPLICATE_GROUP = "ground_truth_duplicate_group"
GROUND_TRUTH_MATCH_COUNT_INVALID = "ground_truth_match_count_invalid"
GROUND_TRUTH_TRACK_MISMATCH = "ground_truth_track_mismatch"
GROUND_TRUTH_CONTAMINATION_EXCLUSION_FAILED = (
    "ground_truth_contamination_exclusion_failed"
)
PARTITION_ASSIGNMENT_CONFLICT = "partition_assignment_conflict"
INDEPENDENT_VIEW_MEMBERSHIP_INVALID = "independent_view_membership_invalid"
DUPLICATE_DETECTION_IDENTITY = "duplicate_detection_identity"
POPULATION_NOT_FROZEN = "population_not_frozen"
NON_ACCEPTANCE_SITE = "non_acceptance_site"
PSEUDO_OR_NO_TRACK = "pseudo_or_no_track"

DEFAULT_PROHIBITED_CREATION_INPUTS = (
    "baseline_output",
    "candidate_output",
    "derived_localization_artifact",
    "haware_coordinate",
    "haware_overlay",
)


class PilotEvidenceError(ValueError):
    """Deterministic fatal evidence or population-freeze failure."""

    def __init__(self, code: str, *, site: Optional[str] = None) -> None:
        self.code = code
        self.site = site
        super().__init__(f"{code}:{site}" if site is not None else code)


@dataclass(frozen=True, kw_only=True)
class GroundTruthEvidence(CanonicalModel):
    """Audit information not represented by the narrow GT coordinate model."""

    record: GroundTruthRecord
    matching_group_id: str
    units: str
    creation_inputs: tuple[str, ...]
    source_lineage: tuple[str, ...]
    matching_group_complete: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "creation_inputs", canonical_order(self.creation_inputs, unique=True)
        )
        object.__setattr__(
            self, "source_lineage", canonical_order(self.source_lineage, unique=True)
        )
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class GroundTruthValidationPolicy(CanonicalModel):
    """Pre-outcome, site-specific independent-GT eligibility rules."""

    site: str
    calibration_identity: ContentIdentity
    reference_point: str
    coordinate_x_m: ClosedInterval
    coordinate_y_m: ClosedInterval
    uncertainty_m: ClosedInterval
    units: str = "metre"
    independence_attestation: str = "independent_no_haware_access"
    prohibited_creation_inputs: tuple[str, ...] = DEFAULT_PROHIBITED_CREATION_INPUTS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prohibited_creation_inputs",
            canonical_order(self.prohibited_creation_inputs, unique=True),
        )
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError("ground_truth_policy_site_invalid")
        if not self.reference_point.strip() or not self.units.strip():
            raise ValueError("ground_truth_policy_identity_invalid")
        if not self.independence_attestation.strip():
            raise ValueError("ground_truth_policy_attestation_invalid")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PartitionAssignment(CanonicalModel):
    site: str
    group_kind: str
    group_id: str
    partition: PartitionKind

    def __post_init__(self) -> None:
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError("partition_assignment_site_invalid")
        if self.group_kind not in (TRACK_GROUP, SOURCE_GROUP):
            raise ValueError("partition_assignment_group_kind_invalid")
        if not self.group_id.strip():
            raise ValueError("partition_assignment_group_id_invalid")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class IndependentViewMembership(CanonicalModel):
    site: str
    frame_id: str
    detection_id: str
    view_id: str
    camera_id: str
    scene_region_id: str
    source_video_id: str

    def __post_init__(self) -> None:
        values = (
            self.site,
            self.frame_id,
            self.detection_id,
            self.view_id,
            self.camera_id,
            self.scene_region_id,
            self.source_video_id,
        )
        if not all(value.strip() for value in values):
            raise ValueError(INDEPENDENT_VIEW_MEMBERSHIP_INVALID)
        super().__post_init__()

@dataclass(frozen=True, kw_only=True)
class EvidenceExclusion(CanonicalModel):
    site: str
    reason: str
    frame_id: Optional[str] = None
    detection_id: Optional[str] = None
    matching_group_id: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class FrozenEligibleDetection(CanonicalModel):
    eligible_detection_id: str
    record: ObservationRecord
    ground_truth: GroundTruthRecord
    ground_truth_group_id: str
    real_track_id: str
    source_sequence: str
    independent_view_id: str
    partition: PartitionKind


@dataclass(frozen=True, kw_only=True)
class FrozenSiteEvidence(CanonicalModel):
    site: str
    population: PilotPopulation
    eligible_detections: tuple[FrozenEligibleDetection, ...]
    exclusions: tuple[EvidenceExclusion, ...]
    denominator: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "eligible_detections", canonical_order(self.eligible_detections)
        )
        object.__setattr__(self, "exclusions", canonical_order(self.exclusions))
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError("frozen_site_invalid")
        if self.population.site != self.site:
            raise ValueError("frozen_population_site_mismatch")
        if self.denominator != len(self.eligible_detections):
            raise ValueError("frozen_denominator_mismatch")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class OutcomeAccessToken(CanonicalModel):
    """Capability proving both site populations were frozen outcome-blind."""

    population_identities: tuple[tuple[str, ContentIdentity], ...]
    denominators: tuple[tuple[str, int], ...]
    ordered_eligible_ids: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "population_identities", canonical_order(self.population_identities)
        )
        object.__setattr__(self, "denominators", canonical_order(self.denominators))
        object.__setattr__(
            self, "ordered_eligible_ids", canonical_order(self.ordered_eligible_ids)
        )
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class FrozenPilotEvidence(CanonicalModel):
    sites: tuple[FrozenSiteEvidence, ...]
    outcome_access: OutcomeAccessToken

    def __post_init__(self) -> None:
        # Site tuples are semantic arrays, not set-like collections.  Normalize
        # explicitly to the frozen acceptance-site order so reconstruction from
        # asymmetric fixtures cannot let content hashes reorder the namespaces.
        by_site = {value.site: value for value in self.sites}
        if len(by_site) != len(self.sites) or set(by_site) != set(ACCEPTANCE_SITES):
            raise ValueError("acceptance_site_namespaces_incomplete")
        object.__setattr__(self, "sites", tuple(by_site[site] for site in ACCEPTANCE_SITES))
        super().__post_init__()

    def for_site(self, site: str) -> FrozenSiteEvidence:
        if site not in ACCEPTANCE_SITES:
            raise KeyError(site)
        return next(value for value in self.sites if value.site == site)


def _identity(record: ObservationRecord) -> tuple[str, str, str]:
    return record.site, record.frame_id, record.detection_id


def _eligible_id(record: ObservationRecord) -> str:
    return f"{record.site}:{record.frame_id}:{record.detection_id}"


def _namespaced(site: str, value: str) -> str:
    return f"{site}:{value}"


def _assignment_map(
    assignments: tuple[PartitionAssignment, ...],
) -> dict[tuple[str, str, str], PartitionKind]:
    result: dict[tuple[str, str, str], PartitionKind] = {}
    for assignment in canonical_order(assignments):
        key = (assignment.site, assignment.group_kind, assignment.group_id)
        previous = result.get(key)
        if previous is not None and previous is not assignment.partition:
            raise PilotEvidenceError(PARTITION_ASSIGNMENT_CONFLICT, site=assignment.site)
        result[key] = assignment.partition
    return result


def _view_map(
    memberships: tuple[IndependentViewMembership, ...],
) -> tuple[
    dict[tuple[str, str, str], IndependentViewMembership],
    set[tuple[str, str, str]],
]:
    result: dict[tuple[str, str, str], IndependentViewMembership] = {}
    conflicts: set[tuple[str, str, str]] = set()
    for membership in canonical_order(memberships):
        if membership.site not in ACCEPTANCE_SITES:
            continue
        key = (membership.site, membership.frame_id, membership.detection_id)
        previous = result.get(key)
        if previous is not None and previous != membership:
            conflicts.add(key)
        else:
            result[key] = membership
    return result, conflicts


def _group_validation_reason(
    group: tuple[GroundTruthEvidence, ...], policy: GroundTruthValidationPolicy
) -> Optional[str]:
    prohibited = set(policy.prohibited_creation_inputs)
    if any(prohibited.intersection(value.creation_inputs) for value in group):
        if any(not value.matching_group_complete for value in group):
            raise PilotEvidenceError(
                GROUND_TRUTH_CONTAMINATION_EXCLUSION_FAILED, site=policy.site
            )
        return GROUND_TRUTH_CONTAMINATION

    def independence_value(value: GroundTruthEvidence) -> tuple[object, ...]:
        record = value.record
        return (
            record.source.source_id,
            record.source.source_content_identity,
            record.annotator_provenance,
            record.independence_attestation,
            value.source_lineage,
        )

    if any(
        not value.matching_group_id.strip()
        or not value.source_lineage
        or any(not item.strip() for item in value.source_lineage)
        or not value.record.annotator_provenance.strip()
        or value.record.independence_attestation != policy.independence_attestation
        or not value.record.source.source_id.strip()
        for value in group
    ):
        return GROUND_TRUTH_INDEPENDENCE_UNVERIFIED
    if len({independence_value(value) for value in group}) != 1:
        return GROUND_TRUTH_INDEPENDENCE_UNVERIFIED
    for value in group:
        record = value.record
        if record.reference_point != policy.reference_point:
            return GROUND_TRUTH_REFERENCE_POINT_INVALID
        if value.units != policy.units:
            return GROUND_TRUTH_UNITS_INVALID
        if record.calibration_identity != policy.calibration_identity:
            return GROUND_TRUTH_COORDINATE_FRAME_MISMATCH
        x_m, y_m = record.metric_coordinate_m
        if not policy.coordinate_x_m.contains(x_m) or not policy.coordinate_y_m.contains(y_m):
            return GROUND_TRUTH_COORDINATE_INVALID
        if not policy.uncertainty_m.contains(record.uncertainty_m):
            return GROUND_TRUTH_UNCERTAINTY_INVALID
        if not record.real_track_id.strip():
            return GROUND_TRUTH_TRACK_MISMATCH
    return None

def _validated_gt_by_site(
    evidence: tuple[GroundTruthEvidence, ...],
    policies: dict[str, GroundTruthValidationPolicy],
) -> tuple[
    dict[str, dict[tuple[str, str, str], tuple[GroundTruthEvidence, ...]]],
    dict[str, list[EvidenceExclusion]],
]:
    groups: dict[tuple[str, str], list[GroundTruthEvidence]] = {}
    exclusions = {site: [] for site in ACCEPTANCE_SITES}
    for value in evidence:
        site = value.record.site
        if site not in ACCEPTANCE_SITES:
            continue
        groups.setdefault((site, value.matching_group_id), []).append(value)

    group_reasons: dict[tuple[str, str], str] = {}
    for (site, group_id), values in sorted(groups.items()):
        group = tuple(canonical_order(values))
        reason = _group_validation_reason(group, policies[site])
        if reason is not None:
            group_reasons[(site, group_id)] = reason

    identity_groups: dict[tuple[str, str, str], set[str]] = {}
    identity_counts: dict[tuple[str, str, str], int] = {}
    for (site, group_id), values in groups.items():
        if (site, group_id) in group_reasons:
            continue
        for value in values:
            identity = (
                value.record.site,
                value.record.frame_id,
                value.record.detection_id,
            )
            identity_groups.setdefault(identity, set()).add(group_id)
            identity_counts[identity] = identity_counts.get(identity, 0) + 1
    for identity, count in identity_counts.items():
        if count > 1:
            for group_id in identity_groups[identity]:
                group_reasons[(identity[0], group_id)] = GROUND_TRUTH_DUPLICATE_GROUP

    valid = {site: {} for site in ACCEPTANCE_SITES}
    for (site, group_id), values in sorted(groups.items()):
        reason = group_reasons.get((site, group_id))
        if reason is not None:
            for value in canonical_order(values):
                exclusions[site].append(
                    EvidenceExclusion(
                        site=site,
                        frame_id=value.record.frame_id,
                        detection_id=value.record.detection_id,
                        matching_group_id=group_id,
                        reason=reason,
                    )
                )
            continue
        for value in canonical_order(values):
            key = (site, value.record.frame_id, value.record.detection_id)
            valid[site].setdefault(key, tuple())
            valid[site][key] = valid[site][key] + (value,)
    return valid, exclusions


def _partitions(
    site: str, detections: tuple[FrozenEligibleDetection, ...]
) -> tuple[PopulationPartition, ...]:
    return tuple(
        PopulationPartition(
            partition_id=f"{site}:{kind.value}",
            kind=kind,
            eligible_detection_ids=tuple(
                item.eligible_detection_id
                for item in detections
                if item.partition is kind
            ),
        )
        for kind in (PartitionKind.PILOT, PartitionKind.HELD_OUT)
    )


class PilotPopulationFreezer:
    """One-shot boundary that cannot expose outcomes before an atomic freeze."""

    __slots__ = ("_frozen",)

    def __init__(self) -> None:
        self._frozen: Optional[FrozenPilotEvidence] = None

    @property
    def outcome_access(self) -> OutcomeAccessToken:
        if self._frozen is None:
            raise PilotEvidenceError(POPULATION_NOT_FROZEN)
        return self._frozen.outcome_access

    @property
    def frozen_evidence(self) -> FrozenPilotEvidence:
        if self._frozen is None:
            raise PilotEvidenceError(POPULATION_NOT_FROZEN)
        return self._frozen

    def freeze(
        self,
        *,
        replay_records: Iterable[ObservationRecord],
        ground_truth: Iterable[GroundTruthEvidence],
        policies: Iterable[GroundTruthValidationPolicy],
        partition_assignments: Iterable[PartitionAssignment],
        independent_views: Iterable[IndependentViewMembership],
    ) -> FrozenPilotEvidence:
        """Validate and atomically freeze both site populations without outcomes."""
        if self._frozen is not None:
            raise PilotEvidenceError("population_already_frozen")
        records = tuple(replay_records)
        evidence = tuple(ground_truth)
        policy_values = tuple(policies)
        assignments = tuple(partition_assignments)
        views = tuple(independent_views)
        if any(not isinstance(value, GroundTruthEvidence) for value in evidence):
            raise TypeError("ground_truth_requires_GroundTruthEvidence")
        policy_map = {value.site: value for value in policy_values}
        if len(policy_map) != len(policy_values) or set(policy_map) != set(ACCEPTANCE_SITES):
            raise PilotEvidenceError("acceptance_site_policies_invalid")

        finalized = finalize_track_provenance(records)
        real_records = tuple(
            record
            for record in finalized.real_track_records
            if record.site in ACCEPTANCE_SITES
        )
        assignment_map = _assignment_map(assignments)
        view_map, view_conflicts = _view_map(views)
        gt_by_site, gt_exclusions = _validated_gt_by_site(evidence, policy_map)

        # Every genuine track and source group is assigned whole before eligibility.
        record_partitions: dict[tuple[str, str, str], PartitionKind] = {}
        for record in real_records:
            assert record.track is not None and record.track.kind is TrackKind.REAL
            track_partition = assignment_map.get(
                (record.site, TRACK_GROUP, record.track.claimed_id)
            )
            source_partition = assignment_map.get(
                (record.site, SOURCE_GROUP, record.source_sequence)
            )
            if track_partition is None or source_partition is None or track_partition is not source_partition:
                raise PilotEvidenceError(PARTITION_ASSIGNMENT_CONFLICT, site=record.site)
            record_partitions[_identity(record)] = track_partition

        duplicate_records: set[tuple[str, str, str]] = set()
        counts: dict[tuple[str, str, str], int] = {}
        for record in real_records:
            key = _identity(record)
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > 1:
                duplicate_records.add(key)

        site_values: list[FrozenSiteEvidence] = []
        for site in ACCEPTANCE_SITES:
            exclusions = list(gt_exclusions[site])
            eligible: list[FrozenEligibleDetection] = []
            for record in canonical_order(
                tuple(value for value in real_records if value.site == site)
            ):
                key = _identity(record)
                if key in duplicate_records:
                    exclusions.append(
                        EvidenceExclusion(
                            site=site,
                            frame_id=record.frame_id,
                            detection_id=record.detection_id,
                            reason=DUPLICATE_DETECTION_IDENTITY,
                        )
                    )
                    continue
                matches = gt_by_site[site].get(key, ())
                if len(matches) != 1:
                    exclusions.append(
                        EvidenceExclusion(
                            site=site,
                            frame_id=record.frame_id,
                            detection_id=record.detection_id,
                            reason=GROUND_TRUTH_MATCH_COUNT_INVALID,
                        )
                    )
                    continue
                match = matches[0]
                assert record.track is not None
                if match.record.real_track_id != record.track.claimed_id:
                    exclusions.append(
                        EvidenceExclusion(
                            site=site,
                            frame_id=record.frame_id,
                            detection_id=record.detection_id,
                            matching_group_id=match.matching_group_id,
                            reason=GROUND_TRUTH_TRACK_MISMATCH,
                        )
                    )
                    continue
                membership = view_map.get(key)
                if (
                    membership is None
                    or key in view_conflicts
                    or membership.source_video_id != record.source_sequence
                ):
                    exclusions.append(
                        EvidenceExclusion(
                            site=site,
                            frame_id=record.frame_id,
                            detection_id=record.detection_id,
                            reason=INDEPENDENT_VIEW_MEMBERSHIP_INVALID,
                        )
                    )
                    continue
                eligible.append(
                    FrozenEligibleDetection(
                        eligible_detection_id=_eligible_id(record),
                        record=record,
                        ground_truth=match.record,
                        ground_truth_group_id=_namespaced(site, match.matching_group_id),
                        real_track_id=_namespaced(site, record.track.claimed_id),
                        source_sequence=_namespaced(site, record.source_sequence),
                        independent_view_id=_namespaced(site, membership.view_id),
                        partition=record_partitions[key],
                    )
                )
            frozen_eligible = tuple(canonical_order(eligible))
            population = PilotPopulation(
                site=site,
                frozen_eligible_ids=tuple(
                    value.eligible_detection_id for value in frozen_eligible
                ),
                ground_truth_group_ids=tuple(
                    value.ground_truth_group_id for value in frozen_eligible
                ),
                real_track_ids=tuple(value.real_track_id for value in frozen_eligible),
                source_sequences=tuple(
                    value.source_sequence for value in frozen_eligible
                ),
                independent_views=tuple(
                    value.independent_view_id for value in frozen_eligible
                ),
                partitions=_partitions(site, frozen_eligible),
            )
            site_values.append(
                FrozenSiteEvidence(
                    site=site,
                    population=population,
                    eligible_detections=frozen_eligible,
                    exclusions=tuple(exclusions),
                    denominator=len(frozen_eligible),
                )
            )

        frozen_sites = tuple(site_values)
        token = OutcomeAccessToken(
            population_identities=tuple(
                (value.site, value.population.content_identity) for value in frozen_sites
            ),
            denominators=tuple(
                (value.site, value.denominator) for value in frozen_sites
            ),
            ordered_eligible_ids=tuple(
                (value.site, value.population.frozen_eligible_ids)
                for value in frozen_sites
            ),
        )
        frozen = FrozenPilotEvidence(sites=frozen_sites, outcome_access=token)
        self._frozen = frozen
        return frozen


class PilotArm(str, Enum):
    CORRECTED_BASELINE = "corrected_baseline"
    FULL_OPTIMIZER = "full_optimizer"
    WHEEL_INITIALIZATION_DISABLED = "wheel_initialization_disabled"
    NON_WHEEL_INITIALIZATION_DISABLED = "non_wheel_initialization_disabled"


@dataclass(frozen=True, kw_only=True)
class PilotCandidateConfiguration(CanonicalModel):
    """Pilot-only selector; all estimator parameters remain in one frozen profile."""

    architecture: str
    optimizer_profile: ContentIdentity
    wheel_seeded_initialization_enabled: bool
    non_wheel_seeded_initialization_enabled: bool

    def __post_init__(self) -> None:
        if self.architecture not in {"corrected_legacy_baseline", "image_space_optimizer"}:
            raise ValueError("pilot_candidate_architecture_invalid")
        flags = (
            self.wheel_seeded_initialization_enabled,
            self.non_wheel_seeded_initialization_enabled,
        )
        if any(type(value) is not bool for value in flags):
            raise TypeError("pilot initialization enable flags must be bool")
        if self.architecture == "image_space_optimizer" and not any(flags):
            raise ValueError("pilot_optimizer_requires_initialization_class")
        if self.architecture == "corrected_legacy_baseline" and any(flags):
            raise ValueError("baseline_cannot_enable_optimizer_initialization")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PilotSupportRuleEvidence(CanonicalModel):
    support_boundary_px: float
    support_includes_equality: bool
    minimal_configurations: tuple[ContentIdentity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "minimal_configurations",
            canonical_order(self.minimal_configurations, unique=True),
        )
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class EligibleOrderingEvidence(CanonicalModel):
    site: str
    population: ContentIdentity
    ordered_eligible_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError(NON_ACCEPTANCE_SITE)
        # This tuple is semantic: never sort the frozen execution order.
        object.__setattr__(self, "ordered_eligible_ids", tuple(self.ordered_eligible_ids))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PilotRunIdentity(CanonicalModel):
    """Complete immutable identity for exactly one site and pilot arm."""

    site: str
    arm: PilotArm
    candidate_configuration: PilotCandidateConfiguration
    eligible_ordering: ContentIdentity
    run: RunIdentity
    baseline_identity: FrozenBaselineIdentity
    scoring: ContentIdentity
    support_rules: ContentIdentity
    gates: ContentIdentity
    metric_definitions: ContentIdentity

    def __post_init__(self) -> None:
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError(NON_ACCEPTANCE_SITE)
        if self.baseline_identity is not FrozenBaselineIdentity.CORRECTED_LOCALIZE:
            raise ValueError("pilot_baseline_identity_invalid")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PilotArmRun:
    identity: PilotRunIdentity
    ordered_eligible_ids: tuple[str, ...]
    outcomes: tuple[Any, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordered_eligible_ids", tuple(self.ordered_eligible_ids))
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        if len(self.ordered_eligible_ids) != len(self.outcomes):
            raise ValueError("pilot_outcome_count_mismatch")


@dataclass(frozen=True, kw_only=True)
class PilotSiteRuns:
    site: str
    denominator: int
    arms: tuple[PilotArmRun, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "arms", tuple(self.arms))
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError(NON_ACCEPTANCE_SITE)
        if tuple(value.identity.arm for value in self.arms) != tuple(PilotArm):
            raise ValueError("pilot_arm_set_invalid")
        if any(len(value.outcomes) != self.denominator for value in self.arms):
            raise ValueError("pilot_denominator_changed")
        orderings = {value.ordered_eligible_ids for value in self.arms}
        if len(orderings) != 1:
            raise ValueError("pilot_eligible_order_changed")


@dataclass(frozen=True, kw_only=True)
class FrozenPilotRuns:
    sites: tuple[PilotSiteRuns, ...]
    statistics_method: "FrozenPilotStatisticsMethod"
    current_evidence_status: DecisionStatus = DecisionStatus.INSUFFICIENT_DATA
    proven_improvement_claim_allowed: bool = False
    optimizer_default_off_outside_pilot: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "sites", tuple(self.sites))
        if tuple(value.site for value in self.sites) != ACCEPTANCE_SITES:
            raise ValueError("pilot_run_site_namespaces_incomplete")
        if self.current_evidence_status is not DecisionStatus.INSUFFICIENT_DATA:
            raise ValueError("unsupported_current_evidence_claim")
        if self.proven_improvement_claim_allowed:
            raise ValueError("unsupported_current_evidence_claim")
        if not self.optimizer_default_off_outside_pilot:
            raise ValueError("optimizer_must_remain_default_off")

    def for_site(self, site: str) -> PilotSiteRuns:
        if site not in ACCEPTANCE_SITES:
            raise KeyError(site)
        return next(value for value in self.sites if value.site == site)


def _candidate_configurations(
    profile: AcceptanceProfile,
) -> tuple[tuple[PilotArm, PilotCandidateConfiguration], ...]:
    optimizer_identity = profile.optimizer.content_identity
    baseline = PilotCandidateConfiguration(
        architecture="corrected_legacy_baseline",
        optimizer_profile=optimizer_identity,
        wheel_seeded_initialization_enabled=False,
        non_wheel_seeded_initialization_enabled=False,
    )
    full = PilotCandidateConfiguration(
        architecture="image_space_optimizer",
        optimizer_profile=optimizer_identity,
        wheel_seeded_initialization_enabled=True,
        non_wheel_seeded_initialization_enabled=True,
    )
    wheel_disabled = replace(full, wheel_seeded_initialization_enabled=False)
    non_wheel_disabled = replace(
        full, non_wheel_seeded_initialization_enabled=False
    )
    _require_single_flag_ablation(
        full, wheel_disabled, "wheel_seeded_initialization_enabled"
    )
    _require_single_flag_ablation(
        full, non_wheel_disabled, "non_wheel_seeded_initialization_enabled"
    )
    return (
        (PilotArm.CORRECTED_BASELINE, baseline),
        (PilotArm.FULL_OPTIMIZER, full),
        (PilotArm.WHEEL_INITIALIZATION_DISABLED, wheel_disabled),
        (PilotArm.NON_WHEEL_INITIALIZATION_DISABLED, non_wheel_disabled),
    )


def _require_single_flag_ablation(
    full: PilotCandidateConfiguration,
    ablation: PilotCandidateConfiguration,
    expected_field: str,
) -> None:
    changed = {
        item.name
        for item in fields(PilotCandidateConfiguration)
        if getattr(full, item.name) != getattr(ablation, item.name)
    }
    if changed != {expected_field}:
        raise PilotEvidenceError("pilot_ablation_not_isolated")


def _support_identity(profile: AcceptanceProfile) -> ContentIdentity:
    robust = profile.optimizer.robust
    return PilotSupportRuleEvidence(
        support_boundary_px=robust.support_boundary_px,
        support_includes_equality=robust.support_includes_equality,
        minimal_configurations=tuple(
            value.content_identity
            for value in profile.optimizer.minimal_configurations
        ),
    ).content_identity


def _run_identity(
    *,
    site: str,
    arm: PilotArm,
    configuration: PilotCandidateConfiguration,
    ordering: EligibleOrderingEvidence,
    replay_identity: ContentIdentity,
    profile: AcceptanceProfile,
    template_identity: ContentIdentity,
    baseline_identity: FrozenBaselineIdentity,
    code_revision: str,
    runtime_dependencies: tuple[ContentIdentity, ...],
) -> PilotRunIdentity:
    optimizer = profile.optimizer
    return PilotRunIdentity(
        site=site,
        arm=arm,
        candidate_configuration=configuration,
        eligible_ordering=ordering.content_identity,
        run=RunIdentity(
            replay=replay_identity,
            profile=profile.content_identity,
            template=template_identity,
            calibration=profile.calibration.content_identity,
            cue_evidence=profile.cue_evidence.content_identity,
            nuisance=profile.nuisance.content_identity,
            code_revision=code_revision,
            runtime_dependencies=runtime_dependencies,
            deterministic_seed=optimizer.deterministic_seed,
        ),
        baseline_identity=baseline_identity,
        scoring=optimizer.robust.content_identity,
        support_rules=_support_identity(profile),
        gates=optimizer.content_identity,
        metric_definitions=profile.pilot_policy.content_identity,
    )


def run_frozen_pilot_arms(
    *,
    frozen_evidence: FrozenPilotEvidence,
    outcome_access: OutcomeAccessToken,
    profiles: Mapping[str, AcceptanceProfile],
    validated_profiles: Mapping[str, ValidatedProfile],
    scope: MvpScopeGuard,
    replay_identities: Mapping[str, ContentIdentity],
    template_identity: ContentIdentity,
    code_revision: str,
    runtime_dependencies: Iterable[ContentIdentity],
    baseline_localize: Callable[[ObservationRecord], Any],
    optimizer_localize: Callable[
        [ObservationRecord, AcceptanceProfile, PilotCandidateConfiguration, PilotRunIdentity],
        Any,
    ],
    baseline_identity: FrozenBaselineIdentity = FrozenBaselineIdentity.CORRECTED_LOCALIZE,
) -> FrozenPilotRuns:
    """Run four isolated arms over each site's exact frozen eligible ordering.

    Optimizer arms call only ``optimizer_localize``. The corrected baseline is
    an independently identified arm and is never used as optimizer fallback.
    """
    if outcome_access != frozen_evidence.outcome_access:
        raise PilotEvidenceError("outcome_access_identity_mismatch")
    expected_sites = set(ACCEPTANCE_SITES)
    if set(profiles) != expected_sites or set(validated_profiles) != expected_sites:
        raise PilotEvidenceError("pilot_profile_sites_invalid")
    if set(replay_identities) != expected_sites:
        raise PilotEvidenceError("pilot_replay_identity_sites_invalid")
    if baseline_identity is not FrozenBaselineIdentity.CORRECTED_LOCALIZE:
        raise PilotEvidenceError("pilot_baseline_identity_invalid")
    if not code_revision.strip():
        raise PilotEvidenceError("pilot_code_revision_missing")
    runtime_values = canonical_order(tuple(runtime_dependencies), unique=True)
    if not runtime_values:
        raise PilotEvidenceError("pilot_runtime_identity_missing")

    # A pilot may invoke optimizer arms directly, but production dispatch must
    # remain baseline/default-off while checked-in evidence is insufficient.
    if scope.current_evidence_status is not DecisionStatus.INSUFFICIENT_DATA:
        raise PilotEvidenceError("unsupported_current_evidence_claim")
    if scope.proven_improvement_claim_allowed:
        raise PilotEvidenceError("unsupported_current_evidence_claim")

    # Validate and freeze the complete statistical procedure before the first
    # outcome callback.  No required evidence count or candidate threshold is
    # stored in this token; those are derived from pilot evidence below.
    for site in ACCEPTANCE_SITES:
        profile = profiles[site]
        require_validated_profile(validated_profiles[site], profile, scope)
        if profile.cue_evidence.site != site:
            raise PilotEvidenceError("pilot_profile_site_mismatch", site=site)
    statistics_method = freeze_pilot_statistics_method(
        frozen_evidence=frozen_evidence,
        profiles=profiles,
    )

    site_runs: list[PilotSiteRuns] = []
    for site in ACCEPTANCE_SITES:
        site_evidence = frozen_evidence.for_site(site)
        profile = profiles[site]
        require_validated_profile(validated_profiles[site], profile, scope)
        if profile.cue_evidence.site != site:
            raise PilotEvidenceError("pilot_profile_site_mismatch", site=site)
        dispatch = resolve_optimizer_dispatch(profile.content_identity)
        if dispatch.optimizer_enabled or dispatch.reason != "optimizer_default_off":
            raise PilotEvidenceError("optimizer_not_default_off", site=site)

        pilot_detections = tuple(
            value
            for value in site_evidence.eligible_detections
            if value.partition is PartitionKind.PILOT
        )
        ordered_ids = tuple(value.eligible_detection_id for value in pilot_detections)
        pilot_partition = next(
            value
            for value in site_evidence.population.partitions
            if value.kind is PartitionKind.PILOT
        )
        if ordered_ids != pilot_partition.eligible_detection_ids:
            raise PilotEvidenceError("frozen_pilot_order_mismatch", site=site)
        ordering = EligibleOrderingEvidence(
            site=site,
            population=site_evidence.population.content_identity,
            ordered_eligible_ids=ordered_ids,
        )

        arms: list[PilotArmRun] = []
        for arm, configuration in _candidate_configurations(profile):
            identity = _run_identity(
                site=site,
                arm=arm,
                configuration=configuration,
                ordering=ordering,
                replay_identity=replay_identities[site],
                profile=profile,
                template_identity=template_identity,
                baseline_identity=baseline_identity,
                code_revision=code_revision,
                runtime_dependencies=runtime_values,
            )
            if arm is PilotArm.CORRECTED_BASELINE:
                outcomes = tuple(
                    baseline_localize(value.record) for value in pilot_detections
                )
            else:
                outcomes = tuple(
                    optimizer_localize(value.record, profile, configuration, identity)
                    for value in pilot_detections
                )
            arms.append(
                PilotArmRun(
                    identity=identity,
                    ordered_eligible_ids=ordered_ids,
                    outcomes=outcomes,
                )
            )
        site_runs.append(
            PilotSiteRuns(site=site, denominator=len(pilot_detections), arms=tuple(arms))
        )

    return FrozenPilotRuns(
        sites=tuple(site_runs), statistics_method=statistics_method
    )


# Frozen Task 8.1 statistics methods.  Method constants are algorithm
# parameters, not claimed evidence requirements; required coverage is derived
# from each site's pilot observations by ``_power_sufficiency``.
MEDIAN_ERROR_EFFECT = "median_error_m"
P90_ERROR_EFFECT = "p90_error_m"
USABLE_COVERAGE_EFFECT = "usable_coverage"
_REQUIRED_EFFECTS = (
    MEDIAN_ERROR_EFFECT,
    P90_ERROR_EFFECT,
    USABLE_COVERAGE_EFFECT,
)


@dataclass(frozen=True, kw_only=True)
class FrozenSiteStatisticsMethod(CanonicalModel):
    site: str
    pilot_policy: ContentIdentity
    confidence_level: float
    cluster_unit: str
    interval_method: str
    power_method: str
    variance_method: str
    sufficiency_rule_version: str
    metric_definition_version: str
    effect_definitions: tuple[tuple[str, str], ...]
    bootstrap_replicates: int
    target_power: float
    minimum_analyzable_clusters: int
    deterministic_seed: int
    feasibility_rules: tuple[tuple[str, str], ...] = (
        (MEDIAN_ERROR_EFFECT, "estimate_lt_0_and_interval_upper_lt_0"),
        (P90_ERROR_EFFECT, "estimate_lt_0_and_interval_upper_lt_0"),
        (USABLE_COVERAGE_EFFECT, "estimate_gte_0_and_interval_lower_gte_0"),
    )

    def __post_init__(self) -> None:
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError(NON_ACCEPTANCE_SITE)
        if self.cluster_unit != TRACK_GROUP:
            raise ValueError("pilot_cluster_unit_invalid")
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError("pilot_confidence_level_invalid")
        if not 0.0 < self.target_power < 1.0:
            raise ValueError("pilot_target_power_invalid")
        if self.bootstrap_replicates <= 0 or self.minimum_analyzable_clusters < 2:
            raise ValueError("pilot_statistics_method_invalid")
        object.__setattr__(self, "effect_definitions", tuple(self.effect_definitions))
        object.__setattr__(self, "feasibility_rules", tuple(self.feasibility_rules))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class FrozenPilotStatisticsMethod(CanonicalModel):
    population_identities: tuple[tuple[str, ContentIdentity], ...]
    sites: tuple[FrozenSiteStatisticsMethod, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "population_identities", canonical_order(self.population_identities)
        )
        object.__setattr__(self, "sites", canonical_order(self.sites))
        if tuple(value.site for value in self.sites) != ACCEPTANCE_SITES:
            raise ValueError("pilot_statistics_site_namespaces_incomplete")
        super().__post_init__()

    def for_site(self, site: str) -> FrozenSiteStatisticsMethod:
        if site not in ACCEPTANCE_SITES:
            raise KeyError(site)
        return next(value for value in self.sites if value.site == site)


def freeze_pilot_statistics_method(
    *,
    frozen_evidence: FrozenPilotEvidence,
    profiles: Mapping[str, AcceptanceProfile],
) -> FrozenPilotStatisticsMethod:
    """Materialize the complete method without inspecting any outcome.

    ``cluster-bootstrap-v1`` is a deterministic whole-real-track percentile
    bootstrap. ``sufficiency-v1`` uses normal-approximation design power with
    bootstrap variance and observed GT uncertainty/view incidence.  In
    particular, this token deliberately contains no required sample, track, or
    per-view counts and no candidate thresholds.
    """
    if set(profiles) != set(ACCEPTANCE_SITES):
        raise PilotEvidenceError("pilot_profile_sites_invalid")
    methods: list[FrozenSiteStatisticsMethod] = []
    for site in ACCEPTANCE_SITES:
        policy = profiles[site].pilot_policy
        if policy.cluster_unit != TRACK_GROUP:
            raise PilotEvidenceError("unsupported_cluster_unit", site=site)
        if policy.power_method != "cluster-bootstrap-v1":
            raise PilotEvidenceError("unsupported_power_method", site=site)
        if policy.sufficiency_rule_version != "sufficiency-v1":
            raise PilotEvidenceError("unsupported_sufficiency_rule", site=site)
        if policy.metric_definition_version != "metrics-v1":
            raise PilotEvidenceError("unsupported_metric_definition", site=site)
        methods.append(
            FrozenSiteStatisticsMethod(
                site=site,
                pilot_policy=policy.content_identity,
                confidence_level=policy.confidence_level,
                cluster_unit=policy.cluster_unit,
                interval_method="whole-real-track-percentile-bootstrap-v1",
                power_method=policy.power_method,
                variance_method="whole-real-track-bootstrap-variance-v1",
                sufficiency_rule_version=policy.sufficiency_rule_version,
                metric_definition_version=policy.metric_definition_version,
                effect_definitions=(
                    (MEDIAN_ERROR_EFFECT, "candidate_minus_corrected_baseline"),
                    (P90_ERROR_EFFECT, "candidate_minus_corrected_baseline"),
                    (USABLE_COVERAGE_EFFECT, "candidate_minus_corrected_baseline"),
                ),
                bootstrap_replicates=4096,
                target_power=0.80,
                minimum_analyzable_clusters=2,
                deterministic_seed=profiles[site].optimizer.deterministic_seed,
            )
        )
    return FrozenPilotStatisticsMethod(
        population_identities=frozen_evidence.outcome_access.population_identities,
        sites=tuple(methods),
    )


@dataclass(frozen=True, kw_only=True)
class DistributionSummary(CanonicalModel):
    values: tuple[float, ...]
    median: Optional[float]
    p90: Optional[float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(sorted(self.values)))
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class ViewCoverage(CanonicalModel):
    view_id: str
    eligible_count: int
    accepted_count: int
    usable_coverage: float


@dataclass(frozen=True, kw_only=True)
class SelectedSeedProvenance(CanonicalModel):
    wheel: int
    non_wheel: int
    unavailable: int


@dataclass(frozen=True, kw_only=True)
class ClusteredEffectInterval(CanonicalModel):
    status: DecisionStatus
    estimate: Optional[float]
    lower: Optional[float]
    upper: Optional[float]
    bootstrap_variance: Optional[float]
    confidence_level: float
    method: str
    cluster_count: int
    replicate_count: int


@dataclass(frozen=True, kw_only=True)
class RequiredViewCoverage(CanonicalModel):
    view_id: str
    observed_count: int
    required_count: int


@dataclass(frozen=True, kw_only=True)
class PowerSufficiency(CanonicalModel):
    status: DecisionStatus
    achieved_power: Optional[float]
    required_sample_count: Optional[int]
    required_genuine_track_count: Optional[int]
    required_view_coverage: tuple[RequiredViewCoverage, ...]
    evidence_gaps: tuple[str, ...]
    method: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "required_view_coverage", canonical_order(self.required_view_coverage)
        )
        object.__setattr__(
            self, "evidence_gaps", canonical_order(self.evidence_gaps, unique=True)
        )
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class CandidateThresholds(CanonicalModel):
    maximum_median_error_m: Optional[float]
    maximum_p90_error_m: Optional[float]
    minimum_usable_coverage: Optional[float]
    derivation: str = "pilot_baseline_plus_whole_track_effect_interval_boundary"


@dataclass(frozen=True, kw_only=True)
class PilotConfigurationStatistics(CanonicalModel):
    site: str
    arm: PilotArm
    pilot_denominator: int
    accepted_count: int
    rejected_count: int
    unrounded_planar_errors_m: tuple[float, ...]
    median_error_m: Optional[float]
    p90_error_m: Optional[float]
    usable_coverage: float
    signed_effects: tuple[tuple[str, Optional[float]], ...]
    effect_intervals: tuple[tuple[str, ClusteredEffectInterval], ...]
    selected_seed_provenance: SelectedSeedProvenance
    genuine_track_count: int
    independent_view_coverage: tuple[ViewCoverage, ...]
    ground_truth_uncertainty: DistributionSummary
    power_sufficiency: Optional[PowerSufficiency]
    candidate_thresholds: Optional[CandidateThresholds]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "unrounded_planar_errors_m", tuple(self.unrounded_planar_errors_m)
        )
        object.__setattr__(self, "signed_effects", tuple(self.signed_effects))
        object.__setattr__(self, "effect_intervals", tuple(self.effect_intervals))
        object.__setattr__(
            self, "independent_view_coverage", canonical_order(self.independent_view_coverage)
        )
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError(NON_ACCEPTANCE_SITE)
        if self.accepted_count + self.rejected_count != self.pilot_denominator:
            raise ValueError("pilot_metric_denominator_changed")
        super().__post_init__()


@dataclass(frozen=True, kw_only=True)
class PilotSiteStatistics(CanonicalModel):
    site: str
    reports: tuple[PilotConfigurationStatistics, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "reports", tuple(self.reports))
        if self.site not in ACCEPTANCE_SITES:
            raise ValueError(NON_ACCEPTANCE_SITE)
        if tuple(report.arm for report in self.reports) != tuple(PilotArm):
            raise ValueError("pilot_statistics_arm_set_invalid")
        super().__post_init__()

    def for_arm(self, arm: PilotArm) -> PilotConfigurationStatistics:
        return next(value for value in self.reports if value.arm is arm)


@dataclass(frozen=True, kw_only=True)
class FrozenPilotStatistics(CanonicalModel):
    method: FrozenPilotStatisticsMethod
    sites: tuple[PilotSiteStatistics, ...]
    current_evidence_status: DecisionStatus = DecisionStatus.INSUFFICIENT_DATA
    proven_improvement_claim_allowed: bool = False
    held_out_acceptance_claim_allowed: bool = False

    def __post_init__(self) -> None:
        # Site statistics are a semantic array.  Rebuild them in the frozen
        # acceptance-site order instead of allowing content hashes to reorder
        # asymmetric site outcomes.
        by_site = {value.site: value for value in self.sites}
        if len(by_site) != len(self.sites) or set(by_site) != set(ACCEPTANCE_SITES):
            raise ValueError("pilot_statistics_site_namespaces_incomplete")
        object.__setattr__(self, "sites", tuple(by_site[site] for site in ACCEPTANCE_SITES))
        if self.current_evidence_status is not DecisionStatus.INSUFFICIENT_DATA:
            raise ValueError("unsupported_current_evidence_claim")
        if self.proven_improvement_claim_allowed or self.held_out_acceptance_claim_allowed:
            raise ValueError("unsupported_current_evidence_claim")
        super().__post_init__()

    def for_site(self, site: str) -> PilotSiteStatistics:
        if site not in ACCEPTANCE_SITES:
            raise KeyError(site)
        return next(value for value in self.sites if value.site == site)


@dataclass(frozen=True)
class _OutcomeView:
    accepted: bool
    position_sat_px: Optional[tuple[float, float]]
    seed_class: Optional[SeedClass]


@dataclass(frozen=True)
class _MetricValues:
    accepted_count: int
    errors: tuple[float, ...]
    median_error: Optional[float]
    p90_error: Optional[float]
    coverage: float


def nearest_rank(values: Iterable[float], probability: float) -> Optional[float]:
    """Return the un-interpolated nearest-rank quantile."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0.0 < probability <= 1.0:
        raise ValueError("nearest_rank_probability_invalid")
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def _median(values: tuple[float, ...]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _finite_position(value: Any) -> Optional[tuple[float, float]]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        return None
    result = (float(value[0]), float(value[1]))
    return result if all(math.isfinite(item) for item in result) else None


def _selected_seed(result: LocalizationResult) -> Optional[SeedClass]:
    selected = result.diagnostics.selected_path
    if selected is None:
        return None
    matches = tuple(path for path in result.diagnostics.paths if path.path_id == selected)
    if len(matches) != 1:
        return None
    return matches[0].seed_class


def _outcome_view(
    outcome: Any,
    *,
    arm: PilotArm,
    profile: AcceptanceProfile,
) -> _OutcomeView:
    if arm is not PilotArm.CORRECTED_BASELINE:
        if not isinstance(outcome, LocalizationResult):
            raise PilotEvidenceError("pilot_optimizer_outcome_contract_invalid")
        accepted = outcome.status is LocalizationStatus.ACCEPTED and outcome.usable
        return _OutcomeView(
            accepted=accepted,
            position_sat_px=(
                outcome.authoritative_position_sat_px if accepted else None
            ),
            seed_class=_selected_seed(outcome),
        )

    if isinstance(outcome, Mapping):
        status = outcome.get("status")
        position = _finite_position(outcome.get("sat_coords"))
        heading = outcome.get("heading")
    else:
        status = getattr(outcome, "status", None)
        position = _finite_position(getattr(outcome, "sat_coords", None))
        heading = getattr(outcome, "heading", None)
    heading_valid = (
        not isinstance(heading, bool)
        and isinstance(heading, (int, float))
        and math.isfinite(float(heading))
    )
    accepted = (
        isinstance(status, str)
        and status in profile.legacy_status_policy.accepted_statuses
        and position is not None
        and heading_valid
    )
    return _OutcomeView(accepted=accepted, position_sat_px=position if accepted else None, seed_class=None)


def _metric_values(
    indices: tuple[int, ...],
    outcomes: tuple[_OutcomeView, ...],
    detections: tuple[FrozenEligibleDetection, ...],
    pixels_per_metre: float,
) -> _MetricValues:
    errors: list[float] = []
    accepted = 0
    for index in indices:
        outcome = outcomes[index]
        if not outcome.accepted or outcome.position_sat_px is None:
            continue
        accepted += 1
        x_px, y_px = outcome.position_sat_px
        gt_x_m, gt_y_m = detections[index].ground_truth.metric_coordinate_m
        x_m, y_m = x_px / pixels_per_metre, y_px / pixels_per_metre
        errors.append(math.hypot(x_m - gt_x_m, y_m - gt_y_m))
    denominator = len(indices)
    error_values = tuple(errors)
    return _MetricValues(
        accepted_count=accepted,
        errors=error_values,
        median_error=_median(error_values),
        p90_error=nearest_rank(error_values, 0.90),
        coverage=accepted / denominator if denominator else 0.0,
    )


def _signed_effect(
    candidate: _MetricValues, baseline: _MetricValues, name: str
) -> Optional[float]:
    if name == MEDIAN_ERROR_EFFECT:
        if candidate.median_error is None or baseline.median_error is None:
            return None
        return candidate.median_error - baseline.median_error
    if name == P90_ERROR_EFFECT:
        if candidate.p90_error is None or baseline.p90_error is None:
            return None
        return candidate.p90_error - baseline.p90_error
    if name == USABLE_COVERAGE_EFFECT:
        return candidate.coverage - baseline.coverage
    raise KeyError(name)


def _cluster_resamples(
    tracks: tuple[str, ...], method: FrozenSiteStatisticsMethod
) -> tuple[tuple[str, ...], ...]:
    cluster_count = len(tracks)
    exhaustive_count = cluster_count ** cluster_count
    if exhaustive_count <= method.bootstrap_replicates:
        return tuple(itertools.product(tracks, repeat=cluster_count))
    rng = random.Random(method.deterministic_seed)
    return tuple(
        tuple(rng.choice(tracks) for _ in range(cluster_count))
        for _ in range(method.bootstrap_replicates)
    )


def _sample_indices(
    sample: tuple[str, ...], indices_by_track: Mapping[str, tuple[int, ...]]
) -> tuple[int, ...]:
    return tuple(index for track in sample for index in indices_by_track[track])


def _sample_variance(values: tuple[float, ...]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _effect_interval(
    *,
    effect_name: str,
    estimate: Optional[float],
    candidate: tuple[_OutcomeView, ...],
    baseline: tuple[_OutcomeView, ...],
    detections: tuple[FrozenEligibleDetection, ...],
    pilot_indices: tuple[int, ...],
    pixels_per_metre: float,
    method: FrozenSiteStatisticsMethod,
) -> ClusteredEffectInterval:
    indices_by_track: dict[str, tuple[int, ...]] = {}
    for index in pilot_indices:
        track = detections[index].real_track_id
        indices_by_track[track] = indices_by_track.get(track, ()) + (index,)
    tracks = tuple(sorted(indices_by_track))
    if len(tracks) < method.minimum_analyzable_clusters or estimate is None:
        return ClusteredEffectInterval(
            status=DecisionStatus.INSUFFICIENT_DATA,
            estimate=estimate,
            lower=None,
            upper=None,
            bootstrap_variance=None,
            confidence_level=method.confidence_level,
            method=method.interval_method,
            cluster_count=len(tracks),
            replicate_count=0,
        )
    values: list[float] = []
    for sample in _cluster_resamples(tracks, method):
        indices = _sample_indices(sample, indices_by_track)
        candidate_metrics = _metric_values(indices, candidate, detections, pixels_per_metre)
        baseline_metrics = _metric_values(indices, baseline, detections, pixels_per_metre)
        value = _signed_effect(candidate_metrics, baseline_metrics, effect_name)
        if value is not None:
            values.append(value)
    samples = tuple(values)
    if len(samples) < 2:
        return ClusteredEffectInterval(
            status=DecisionStatus.INSUFFICIENT_DATA,
            estimate=estimate,
            lower=None,
            upper=None,
            bootstrap_variance=None,
            confidence_level=method.confidence_level,
            method=method.interval_method,
            cluster_count=len(tracks),
            replicate_count=len(samples),
        )
    tail = (1.0 - method.confidence_level) / 2.0
    return ClusteredEffectInterval(
        status=DecisionStatus.GO,
        estimate=estimate,
        lower=nearest_rank(samples, tail),
        upper=nearest_rank(samples, 1.0 - tail),
        bootstrap_variance=_sample_variance(samples),
        confidence_level=method.confidence_level,
        method=method.interval_method,
        cluster_count=len(tracks),
        replicate_count=len(samples),
    )


def _power_sufficiency(
    *,
    effects: Mapping[str, Optional[float]],
    intervals: Mapping[str, ClusteredEffectInterval],
    pilot_detections: tuple[FrozenEligibleDetection, ...],
    view_counts: Mapping[str, int],
    method: FrozenSiteStatisticsMethod,
) -> PowerSufficiency:
    observed_tracks = len({value.real_track_id for value in pilot_detections})
    observed_samples = len(pilot_detections)
    gt_noise = (
        sum(value.ground_truth.uncertainty_m ** 2 for value in pilot_detections)
        / observed_samples
        if observed_samples
        else 0.0
    )
    alpha = 1.0 - method.confidence_level
    z_alpha = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    z_power = NormalDist().inv_cdf(method.target_power)
    required_tracks: list[int] = []
    achieved_powers: list[float] = []
    gaps: list[str] = []
    for name in _REQUIRED_EFFECTS:
        interval = intervals[name]
        effect = effects[name]
        directional_signal = (
            max(0.0, -effect) if effect is not None and name != USABLE_COVERAGE_EFFECT
            else max(0.0, effect or 0.0)
        )
        variance = interval.bootstrap_variance
        if interval.status is not DecisionStatus.GO or variance is None:
            gaps.append(f"{name}:clustered_interval_unavailable")
            continue
        if name != USABLE_COVERAGE_EFFECT:
            variance += gt_noise
        if directional_signal <= 0.0:
            gaps.append(f"{name}:no_observed_directional_effect")
            continue
        if variance <= 0.0:
            required = method.minimum_analyzable_clusters
            achieved = 1.0
        else:
            required = max(
                method.minimum_analyzable_clusters,
                math.ceil(((z_alpha + z_power) ** 2) * variance / directional_signal ** 2),
            )
            achieved = NormalDist().cdf(
                math.sqrt(observed_tracks) * directional_signal / math.sqrt(variance)
                - z_alpha
            )
        required_tracks.append(required)
        achieved_powers.append(achieved)
    if len(required_tracks) != len(_REQUIRED_EFFECTS):
        return PowerSufficiency(
            status=DecisionStatus.INSUFFICIENT_DATA,
            achieved_power=min(achieved_powers) if achieved_powers else None,
            required_sample_count=None,
            required_genuine_track_count=None,
            required_view_coverage=tuple(
                RequiredViewCoverage(view_id=view, observed_count=count, required_count=0)
                for view, count in sorted(view_counts.items())
            ),
            evidence_gaps=tuple(gaps),
            method=method.sufficiency_rule_version,
        )
    required_track_count = max(required_tracks)
    required_sample_count = math.ceil(
        observed_samples * required_track_count / observed_tracks
    ) if observed_tracks else None
    required_views: list[RequiredViewCoverage] = []
    if required_sample_count is not None and observed_samples:
        for view, count in sorted(view_counts.items()):
            required_views.append(
                RequiredViewCoverage(
                    view_id=view,
                    observed_count=count,
                    required_count=math.ceil(required_sample_count * count / observed_samples),
                )
            )
    if observed_tracks < required_track_count:
        gaps.append("genuine_track_coverage_below_power_requirement")
    if required_sample_count is None or observed_samples < required_sample_count:
        gaps.append("eligible_sample_coverage_below_power_requirement")
    if any(value.observed_count < value.required_count for value in required_views):
        gaps.append("independent_view_coverage_below_power_requirement")
    achieved_power = min(achieved_powers)
    if achieved_power < method.target_power:
        gaps.append("achieved_power_below_frozen_target")
    return PowerSufficiency(
        status=DecisionStatus.GO if not gaps else DecisionStatus.INSUFFICIENT_DATA,
        achieved_power=achieved_power,
        required_sample_count=required_sample_count,
        required_genuine_track_count=required_track_count,
        required_view_coverage=tuple(required_views),
        evidence_gaps=tuple(gaps),
        method=method.sufficiency_rule_version,
    )


def _candidate_thresholds(
    baseline: _MetricValues,
    intervals: Mapping[str, ClusteredEffectInterval],
) -> CandidateThresholds:
    median = intervals[MEDIAN_ERROR_EFFECT]
    p90 = intervals[P90_ERROR_EFFECT]
    coverage = intervals[USABLE_COVERAGE_EFFECT]
    return CandidateThresholds(
        maximum_median_error_m=(
            baseline.median_error + median.upper
            if baseline.median_error is not None and median.upper is not None
            else None
        ),
        maximum_p90_error_m=(
            baseline.p90_error + p90.upper
            if baseline.p90_error is not None and p90.upper is not None
            else None
        ),
        minimum_usable_coverage=(
            min(1.0, max(0.0, baseline.coverage + coverage.lower))
            if coverage.lower is not None
            else None
        ),
    )


def compute_pilot_statistics(
    *,
    frozen_evidence: FrozenPilotEvidence,
    frozen_runs: FrozenPilotRuns,
    profiles: Mapping[str, AcceptanceProfile],
) -> FrozenPilotStatistics:
    """Compute site-isolated Task 8.1 statistics from pilot evidence only."""
    expected_method = freeze_pilot_statistics_method(
        frozen_evidence=frozen_evidence, profiles=profiles
    )
    if frozen_runs.statistics_method != expected_method:
        raise PilotEvidenceError("pilot_statistics_method_identity_mismatch")
    if frozen_runs.current_evidence_status is not DecisionStatus.INSUFFICIENT_DATA:
        raise PilotEvidenceError("unsupported_current_evidence_claim")

    site_statistics: list[PilotSiteStatistics] = []
    for site in ACCEPTANCE_SITES:
        evidence = frozen_evidence.for_site(site)
        runs = frozen_runs.for_site(site)
        profile = profiles[site]
        method = expected_method.for_site(site)
        pilot_detections = tuple(
            value
            for value in evidence.eligible_detections
            if value.partition is PartitionKind.PILOT
        )
        ordered_ids = tuple(value.eligible_detection_id for value in pilot_detections)
        if runs.denominator != len(pilot_detections):
            raise PilotEvidenceError("pilot_denominator_changed", site=site)
        if any(run.ordered_eligible_ids != ordered_ids for run in runs.arms):
            raise PilotEvidenceError("frozen_pilot_order_mismatch", site=site)
        pilot_indices = tuple(range(len(pilot_detections)))
        pixels_per_metre = profile.calibration.snapshot.pixels_per_metre
        normalized: dict[PilotArm, tuple[_OutcomeView, ...]] = {}
        metrics: dict[PilotArm, _MetricValues] = {}
        for arm_run in runs.arms:
            views = tuple(
                _outcome_view(outcome, arm=arm_run.identity.arm, profile=profile)
                for outcome in arm_run.outcomes
            )
            normalized[arm_run.identity.arm] = views
            metrics[arm_run.identity.arm] = _metric_values(
                pilot_indices, views, pilot_detections, pixels_per_metre
            )
        baseline = metrics[PilotArm.CORRECTED_BASELINE]
        uncertainty_values = tuple(
            value.ground_truth.uncertainty_m for value in pilot_detections
        )
        uncertainty = DistributionSummary(
            values=uncertainty_values,
            median=_median(uncertainty_values),
            p90=nearest_rank(uncertainty_values, 0.90),
        )
        view_counts: dict[str, int] = {}
        for value in pilot_detections:
            view_counts[value.independent_view_id] = view_counts.get(value.independent_view_id, 0) + 1
        reports: list[PilotConfigurationStatistics] = []
        for arm_run in runs.arms:
            arm = arm_run.identity.arm
            arm_metrics = metrics[arm]
            arm_views = normalized[arm]
            effects = {
                name: _signed_effect(arm_metrics, baseline, name)
                for name in _REQUIRED_EFFECTS
            }
            intervals = {
                name: _effect_interval(
                    effect_name=name,
                    estimate=effects[name],
                    candidate=arm_views,
                    baseline=normalized[PilotArm.CORRECTED_BASELINE],
                    detections=pilot_detections,
                    pilot_indices=pilot_indices,
                    pixels_per_metre=pixels_per_metre,
                    method=method,
                )
                for name in _REQUIRED_EFFECTS
            }
            accepted_by_view: dict[str, int] = {view: 0 for view in view_counts}
            for index in pilot_indices:
                if arm_views[index].accepted:
                    view_id = pilot_detections[index].independent_view_id
                    accepted_by_view[view_id] += 1
            selected = [arm_views[index].seed_class for index in pilot_indices]
            provenance = SelectedSeedProvenance(
                wheel=sum(value is SeedClass.WHEEL for value in selected),
                non_wheel=sum(value is SeedClass.NON_WHEEL for value in selected),
                unavailable=sum(value is None for value in selected),
            )
            view_coverage = tuple(
                ViewCoverage(
                    view_id=view,
                    eligible_count=count,
                    accepted_count=accepted_by_view[view],
                    usable_coverage=accepted_by_view[view] / count,
                )
                for view, count in sorted(view_counts.items())
            )
            power = None
            thresholds = None
            if arm is not PilotArm.CORRECTED_BASELINE:
                power = _power_sufficiency(
                    effects=effects,
                    intervals=intervals,
                    pilot_detections=pilot_detections,
                    view_counts=view_counts,
                    method=method,
                )
                thresholds = _candidate_thresholds(baseline, intervals)
            reports.append(
                PilotConfigurationStatistics(
                    site=site,
                    arm=arm,
                    pilot_denominator=len(pilot_indices),
                    accepted_count=arm_metrics.accepted_count,
                    rejected_count=len(pilot_indices) - arm_metrics.accepted_count,
                    unrounded_planar_errors_m=arm_metrics.errors,
                    median_error_m=arm_metrics.median_error,
                    p90_error_m=arm_metrics.p90_error,
                    usable_coverage=arm_metrics.coverage,
                    signed_effects=tuple((name, effects[name]) for name in _REQUIRED_EFFECTS),
                    effect_intervals=tuple((name, intervals[name]) for name in _REQUIRED_EFFECTS),
                    selected_seed_provenance=provenance,
                    genuine_track_count=len({value.real_track_id for value in pilot_detections}),
                    independent_view_coverage=view_coverage,
                    ground_truth_uncertainty=uncertainty,
                    power_sufficiency=power,
                    candidate_thresholds=thresholds,
                )
            )
        site_statistics.append(PilotSiteStatistics(site=site, reports=tuple(reports)))
    return FrozenPilotStatistics(method=expected_method, sites=tuple(site_statistics))


# Task 8.2: site-isolated pilot feasibility and checked-in evidence reporting.
def _pilot_rule_failure(
    name: str, rule: str, interval: ClusteredEffectInterval
) -> tuple[str, ...]:
    failures: list[str] = []
    if rule == "estimate_lt_0_and_interval_upper_lt_0":
        if interval.estimate is None or interval.estimate >= 0.0:
            failures.append(f"{name}:estimate_not_improved")
        if interval.upper is None or interval.upper >= 0.0:
            failures.append(f"{name}:interval_does_not_support_improvement")
    elif rule == "estimate_gte_0_and_interval_lower_gte_0":
        if interval.estimate is None or interval.estimate < 0.0:
            failures.append(f"{name}:estimate_degrades_coverage")
        if interval.lower is None or interval.lower < 0.0:
            failures.append(f"{name}:interval_allows_coverage_degradation")
    else:
        raise PilotEvidenceError("unsupported_pilot_feasibility_rule")
    return tuple(failures)


def decide_pilot_feasibility(
    *,
    statistics: FrozenPilotStatistics,
    frozen_runs: FrozenPilotRuns,
    diagnostic_values: Optional[Mapping[str, Any]] = None,
) -> PilotDecision:
    """Apply frozen feasibility rules independently at both acceptance sites."""
    del diagnostic_values  # Diagnostic, pooled, proxy, and selective-risk values never decide.
    if statistics.method != frozen_runs.statistics_method:
        raise PilotEvidenceError("pilot_statistics_method_identity_mismatch")

    site_decisions: list[SiteDecision] = []
    for site in ACCEPTANCE_SITES:
        report = statistics.for_site(site).for_arm(PilotArm.FULL_OPTIMIZER)
        method = statistics.method.for_site(site)
        if report.power_sufficiency is None:
            gaps = ("power_sufficiency_unavailable",)
        else:
            gaps = tuple(report.power_sufficiency.evidence_gaps)
            if report.power_sufficiency.status is not DecisionStatus.GO and not gaps:
                gaps = ("power_sufficiency_not_satisfied",)
        intervals = dict(report.effect_intervals)
        failures: list[str] = []
        for name, rule in method.feasibility_rules:
            interval = intervals.get(name)
            if interval is None:
                failures.append(f"{name}:effect_interval_unavailable")
            else:
                failures.extend(_pilot_rule_failure(name, rule, interval))
        status = DecisionStatus.GO if not gaps and not failures else DecisionStatus.NO_GO
        site_decisions.append(
            SiteDecision(
                site=site,
                status=status,
                evidence_gaps=gaps,
                failed_conditions=tuple(failures),
            )
        )

    by_site = {value.site: value for value in site_decisions}
    overall = (
        DecisionStatus.GO
        if all(by_site[site].status is DecisionStatus.GO for site in ACCEPTANCE_SITES)
        else DecisionStatus.NO_GO
    )
    all_gaps = tuple(
        f"{site}:{gap}"
        for site in ACCEPTANCE_SITES
        for gap in by_site[site].evidence_gaps
    )
    all_failures = tuple(
        f"{site}:{failure}"
        for site in ACCEPTANCE_SITES
        for failure in by_site[site].failed_conditions
    )
    candidate_runs = tuple(
        frozen_runs.for_site(site)
        .arms[tuple(PilotArm).index(PilotArm.FULL_OPTIMIZER)]
        .identity.run
        for site in ACCEPTANCE_SITES
    )
    return PilotDecision(
        kee_cc=by_site["kee-cc"],
        taoyuan_tc=by_site["taoyuan-tc"],
        overall=overall,
        evidence_gaps=all_gaps,
        failed_conditions=all_failures,
        profile_identity=statistics.content_identity,
        run_identities=candidate_runs,
    )


@dataclass(frozen=True, kw_only=True)
class CurrentEvidenceReport(CanonicalModel):
    final_evidence_status: DecisionStatus
    proven_improvement_claim_allowed: bool
    held_out_acceptance_claim_allowed: bool
    optimizer_authoritative_dispatch_allowed: bool
    diagnostic_inputs_role: str
    per_site_evidence_gaps: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        by_site = {site: tuple(gaps) for site, gaps in self.per_site_evidence_gaps}
        if set(by_site) != set(ACCEPTANCE_SITES):
            raise ValueError("current_evidence_site_namespaces_incomplete")
        object.__setattr__(
            self,
            "per_site_evidence_gaps",
            tuple((site, by_site[site]) for site in ACCEPTANCE_SITES),
        )
        if self.final_evidence_status is not DecisionStatus.INSUFFICIENT_DATA:
            raise ValueError("unsupported_current_evidence_claim")
        if (
            self.proven_improvement_claim_allowed
            or self.held_out_acceptance_claim_allowed
            or self.optimizer_authoritative_dispatch_allowed
        ):
            raise ValueError("unsupported_current_evidence_claim")
        if self.diagnostic_inputs_role != "diagnostic_only":
            raise ValueError("current_evidence_must_be_diagnostic_only")
        super().__post_init__()


_CURRENT_EVIDENCE_INVENTORY = (
    Path(__file__).resolve().parents[2]
    / "evidence"
    / "haware"
    / "current_evidence_inventory.json"
)
_CURRENT_EVIDENCE_REPORT_PATH = "evidence/haware/current_evidence_report.json"
_CURRENT_EVIDENCE_GAP_FIELDS = (
    ("independent_ground_truth", "independent_ground_truth_unavailable"),
    ("genuine_track_evidence", "genuine_track_coverage_unavailable"),
    ("pilot_power_evidence", "pilot_power_unavailable"),
    ("untouched_held_out_partitions", "untouched_held_out_partition_unavailable"),
)


def _read_current_evidence_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("current_evidence_duplicate_key")
            result[key] = value
        return result

    try:
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("current_evidence_artifact_invalid") from error
    if not isinstance(value, dict):
        raise ValueError("current_evidence_artifact_invalid")
    return payload, value


def load_current_evidence_report() -> CurrentEvidenceReport:
    """Read and validate the mandatory checked-in insufficient-evidence artifacts."""
    _, inventory = _read_current_evidence_json(_CURRENT_EVIDENCE_INVENTORY)
    if set(inventory) != {
        "schema_version",
        "diagnostic_inputs_role",
        "per_site_inputs",
        "report_path",
        "report_sha256",
    }:
        raise ValueError("current_evidence_inventory_schema_invalid")
    if inventory["schema_version"] != "haware-current-evidence-inventory-v1":
        raise ValueError("current_evidence_inventory_schema_invalid")
    if inventory["diagnostic_inputs_role"] != "diagnostic_only":
        raise ValueError("current_evidence_must_be_diagnostic_only")
    if inventory["report_path"] != _CURRENT_EVIDENCE_REPORT_PATH:
        raise ValueError("current_evidence_report_path_invalid")

    site_inputs = inventory["per_site_inputs"]
    if not isinstance(site_inputs, list):
        raise ValueError("current_evidence_inventory_schema_invalid")
    by_site: dict[str, dict[str, Any]] = {}
    required_site_keys = {"site", *(field for field, _ in _CURRENT_EVIDENCE_GAP_FIELDS)}
    for value in site_inputs:
        if not isinstance(value, dict) or set(value) != required_site_keys:
            raise ValueError("current_evidence_inventory_schema_invalid")
        site = value["site"]
        if site in by_site or site not in ACCEPTANCE_SITES:
            raise ValueError("current_evidence_site_namespaces_incomplete")
        for field, _ in _CURRENT_EVIDENCE_GAP_FIELDS:
            artifacts = value[field]
            if not isinstance(artifacts, list) or any(
                not isinstance(item, str) or not item.strip() for item in artifacts
            ):
                raise ValueError("current_evidence_inventory_schema_invalid")
        by_site[site] = value
    if set(by_site) != set(ACCEPTANCE_SITES):
        raise ValueError("current_evidence_site_namespaces_incomplete")

    report_path = Path(__file__).resolve().parents[2] / inventory["report_path"]
    report_payload, report = _read_current_evidence_json(report_path)
    if hashlib.sha256(report_payload).hexdigest() != inventory["report_sha256"]:
        raise ValueError("current_evidence_report_identity_mismatch")
    if set(report) != {
        "schema_version",
        "final_evidence_status",
        "proven_improvement_claim_allowed",
        "held_out_acceptance_claim_allowed",
        "optimizer_authoritative_dispatch_allowed",
        "diagnostic_inputs_role",
        "per_site_evidence_gaps",
    } or report["schema_version"] != "haware-current-evidence-report-v1":
        raise ValueError("current_evidence_report_schema_invalid")

    gap_values = report["per_site_evidence_gaps"]
    if not isinstance(gap_values, list):
        raise ValueError("current_evidence_report_schema_invalid")
    reported_by_site: dict[str, tuple[str, ...]] = {}
    for value in gap_values:
        if not isinstance(value, dict) or set(value) != {"site", "evidence_gaps"}:
            raise ValueError("current_evidence_report_schema_invalid")
        site = value["site"]
        gaps = value["evidence_gaps"]
        if (
            site in reported_by_site
            or site not in ACCEPTANCE_SITES
            or not isinstance(gaps, list)
            or any(not isinstance(gap, str) or not gap.strip() for gap in gaps)
        ):
            raise ValueError("current_evidence_report_schema_invalid")
        reported_by_site[site] = tuple(gaps)
    expected_gaps = {
        site: tuple(
            gap
            for field, gap in _CURRENT_EVIDENCE_GAP_FIELDS
            if not by_site[site][field]
        )
        for site in ACCEPTANCE_SITES
    }
    if reported_by_site != expected_gaps or any(not gaps for gaps in expected_gaps.values()):
        raise ValueError("current_evidence_report_inventory_mismatch")
    boolean_fields = (
        "proven_improvement_claim_allowed",
        "held_out_acceptance_claim_allowed",
        "optimizer_authoritative_dispatch_allowed",
    )
    if any(type(report[field]) is not bool for field in boolean_fields):
        raise ValueError("current_evidence_report_schema_invalid")
    try:
        status = DecisionStatus(report["final_evidence_status"])
    except (TypeError, ValueError) as error:
        raise ValueError("current_evidence_report_schema_invalid") from error
    return CurrentEvidenceReport(
        final_evidence_status=status,
        proven_improvement_claim_allowed=report["proven_improvement_claim_allowed"],
        held_out_acceptance_claim_allowed=report["held_out_acceptance_claim_allowed"],
        optimizer_authoritative_dispatch_allowed=report[
            "optimizer_authoritative_dispatch_allowed"
        ],
        diagnostic_inputs_role=report["diagnostic_inputs_role"],
        per_site_evidence_gaps=tuple(
            (site, reported_by_site[site]) for site in ACCEPTANCE_SITES
        ),
    )