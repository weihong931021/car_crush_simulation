"""Property 15: independent evidence and partitions are leak-free and site-isolated."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import unittest

from hypothesis import given, strategies as st

from tests.property_support.config import deterministic_property, record_failure_metadata
from trafficlab.measurement.haware_pilot import (
    ACCEPTANCE_SITES,
    GROUND_TRUTH_CONTAMINATION,
    GROUND_TRUTH_CONTAMINATION_EXCLUSION_FAILED,
    GROUND_TRUTH_COORDINATE_INVALID,
    GROUND_TRUTH_DUPLICATE_GROUP,
    GROUND_TRUTH_INDEPENDENCE_UNVERIFIED,
    GROUND_TRUTH_MATCH_COUNT_INVALID,
    GROUND_TRUTH_UNCERTAINTY_INVALID,
    PARTITION_ASSIGNMENT_CONFLICT,
    POPULATION_NOT_FROZEN,
    SOURCE_GROUP,
    TRACK_GROUP,
    GroundTruthEvidence,
    GroundTruthValidationPolicy,
    IndependentViewMembership,
    PartitionAssignment,
    PilotEvidenceError,
    PilotPopulationFreezer,
)
from trafficlab.motion.haware_accuracy.models import (
    ClosedInterval,
    ContentIdentity,
    GroundTruthRecord,
    ImageObservation,
    ObservationRecord,
    PartitionKind,
    ProviderProvenance,
    SourceProvenance,
    TrackKind,
    TrackProvenance,
)

CALIBRATION_ID = ContentIdentity("a" * 64)
SOURCE_ID = ContentIdentity("b" * 64)
PROHIBITED_INPUTS = (
    "baseline_output",
    "candidate_output",
    "derived_localization_artifact",
    "haware_coordinate",
    "haware_overlay",
)


@dataclass(frozen=True)
class SiteShape:
    track_counts: tuple[int, ...]
    partitions: tuple[PartitionKind, ...]
    contaminated_input: str
    invalid_kind: str


@dataclass(frozen=True)
class EvidenceCase:
    shapes: tuple[SiteShape, SiteShape]
    changed_site: str
    presentation_salts: tuple[int, int]


@dataclass(frozen=True)
class EvidenceFixture:
    records: tuple[ObservationRecord, ...]
    ground_truth: tuple[GroundTruthEvidence, ...]
    assignments: tuple[PartitionAssignment, ...]
    views: tuple[IndependentViewMembership, ...]
    expected_denominators: tuple[tuple[str, int], ...]
    expected_group_reasons: tuple[tuple[str, str, str], ...]


@st.composite
def evidence_cases(draw) -> EvidenceCase:
    shapes = []
    for _site in ACCEPTANCE_SITES:
        source_count = draw(st.integers(min_value=1, max_value=2))
        shapes.append(
            SiteShape(
                track_counts=tuple(
                    draw(st.lists(st.integers(1, 2), min_size=source_count, max_size=source_count))
                ),
                partitions=tuple(
                    draw(st.lists(st.sampled_from(tuple(PartitionKind)), min_size=source_count, max_size=source_count))
                ),
                contaminated_input=draw(st.sampled_from(PROHIBITED_INPUTS)),
                invalid_kind=draw(st.sampled_from(("coordinate", "uncertainty"))),
            )
        )
    return EvidenceCase(
        shapes=(shapes[0], shapes[1]),
        changed_site=draw(st.sampled_from(ACCEPTANCE_SITES)),
        presentation_salts=(
            draw(st.integers(min_value=0, max_value=2**32 - 1)),
            draw(st.integers(min_value=0, max_value=2**32 - 1)),
        ),
    )


def _source(source_id: str) -> SourceProvenance:
    return SourceProvenance(
        source_id=source_id,
        repository_relative_path=None,
        source_content_identity=SOURCE_ID,
    )


def _record(site: str, sequence: str, frame: str, detection: str, track_id: str) -> ObservationRecord:
    return ObservationRecord(
        site=site,
        source_sequence=sequence,
        frame_id=frame,
        detection_id=detection,
        image_size_px=(1280, 720),
        observations=(
            ImageObservation(
                observation_id=f"observation-{detection}",
                pixel=(100.0, 200.0),
                confidence=0.9,
                candidate_labels=("wheel",),
                provider_key=f"generated:{detection}",
            ),
        ),
        provider=ProviderProvenance(
            provider_name="generated",
            provider_version="1.0",
            adapter_version="1.0",
        ),
        source=_source(f"replay:{site}"),
        track=TrackProvenance(
            claimed_id=track_id,
            tracker_name="tracker",
            tracker_version="1.0",
            source_sequence=sequence,
            association_provenance="tracker-output",
            observed_frames=("untrusted-a", "untrusted-b"),
            kind=TrackKind.REAL,
            reason="untrusted-input-classification",
        ),
    )


def _ground_truth(
    record: ObservationRecord,
    group_id: str,
    *,
    creation_inputs: tuple[str, ...] = ("raw_video",),
    source_lineage: tuple[str, ...] = ("manual_annotation",),
    coordinate: tuple[float, float] = (10.0, 20.0),
    uncertainty: float = 0.25,
) -> GroundTruthEvidence:
    assert record.track is not None
    return GroundTruthEvidence(
        record=GroundTruthRecord(
            site=record.site,
            frame_id=record.frame_id,
            detection_id=record.detection_id,
            real_track_id=record.track.claimed_id,
            reference_point="vehicle_ground_center",
            metric_coordinate_m=coordinate,
            calibration_identity=CALIBRATION_ID,
            source=_source(f"independent-gt:{record.site}"),
            annotator_provenance="independent-team-v1",
            independence_attestation="independent_no_haware_access",
            uncertainty_m=uncertainty,
        ),
        matching_group_id=group_id,
        units="metre",
        creation_inputs=creation_inputs,
        source_lineage=source_lineage,
    )


def _view(record: ObservationRecord) -> IndependentViewMembership:
    return IndependentViewMembership(
        site=record.site,
        frame_id=record.frame_id,
        detection_id=record.detection_id,
        view_id=f"view-{record.site}-{record.source_sequence}",
        camera_id=f"camera-{record.site}",
        scene_region_id="road-center",
        source_video_id=record.source_sequence,
    )


def _assignment(
    site: str, kind: str, group_id: str, partition: PartitionKind
) -> PartitionAssignment:
    return PartitionAssignment(
        site=site,
        group_kind=kind,
        group_id=group_id,
        partition=partition,
    )


def _policy(site: str) -> GroundTruthValidationPolicy:
    return GroundTruthValidationPolicy(
        site=site,
        calibration_identity=CALIBRATION_ID,
        reference_point="vehicle_ground_center",
        coordinate_x_m=ClosedInterval(lower=0.0, upper=100.0),
        coordinate_y_m=ClosedInterval(lower=0.0, upper=100.0),
        uncertainty_m=ClosedInterval(lower=0.0, upper=5.0),
    )


def _append_track(
    *,
    records: list[ObservationRecord],
    assignments: list[PartitionAssignment],
    views: list[IndependentViewMembership],
    site: str,
    category: str,
    sequence: str,
    track_id: str,
    partition: PartitionKind,
) -> tuple[ObservationRecord, ObservationRecord]:
    assignments.append(_assignment(site, TRACK_GROUP, track_id, partition))
    pair = tuple(
        _record(
            site,
            sequence,
            f"{category}-frame-{index}",
            f"{category}-detection-{index}",
            track_id,
        )
        for index in range(2)
    )
    records.extend(pair)
    views.extend(_view(value) for value in pair)
    return pair  # type: ignore[return-value]


def _build_fixture(case: EvidenceCase) -> EvidenceFixture:
    records: list[ObservationRecord] = []
    ground_truth: list[GroundTruthEvidence] = []
    assignments: list[PartitionAssignment] = []
    views: list[IndependentViewMembership] = []
    denominators: list[tuple[str, int]] = []
    group_reasons: list[tuple[str, str, str]] = []

    for site, shape in zip(ACCEPTANCE_SITES, case.shapes):
        base_record_count = 0
        for source_index, (track_count, partition) in enumerate(
            zip(shape.track_counts, shape.partitions)
        ):
            sequence = f"{site}-source-{source_index}"
            assignments.append(_assignment(site, SOURCE_GROUP, sequence, partition))
            for track_index in range(track_count):
                category = f"{site}-base-{source_index}-{track_index}"
                pair = _append_track(
                    records=records,
                    assignments=assignments,
                    views=views,
                    site=site,
                    category=category,
                    sequence=sequence,
                    track_id=f"{site}-track-{source_index}-{track_index}",
                    partition=partition,
                )
                base_record_count += len(pair)
                ground_truth.extend(
                    _ground_truth(value, f"valid-{value.detection_id}") for value in pair
                )

        special_specs = (
            ("contaminated", PartitionKind.PILOT),
            ("unverified", PartitionKind.HELD_OUT),
            ("invalid", PartitionKind.PILOT),
            ("duplicate", PartitionKind.HELD_OUT),
        )
        special_pairs: dict[str, tuple[ObservationRecord, ObservationRecord]] = {}
        for category, partition in special_specs:
            sequence = f"{site}-{category}-source"
            assignments.append(_assignment(site, SOURCE_GROUP, sequence, partition))
            special_pairs[category] = _append_track(
                records=records,
                assignments=assignments,
                views=views,
                site=site,
                category=f"{site}-{category}",
                sequence=sequence,
                track_id=f"{site}-{category}-track",
                partition=partition,
            )

        contaminated_group = f"{site}-contaminated-group"
        contaminated = special_pairs["contaminated"]
        ground_truth.extend(
            _ground_truth(
                value,
                contaminated_group,
                creation_inputs=(shape.contaminated_input,) if index == 0 else ("raw_video",),
            )
            for index, value in enumerate(contaminated)
        )
        group_reasons.append((site, contaminated_group, GROUND_TRUTH_CONTAMINATION))

        unverified_group = f"{site}-unverified-group"
        ground_truth.extend(
            _ground_truth(value, unverified_group, source_lineage=())
            for value in special_pairs["unverified"]
        )
        group_reasons.append((site, unverified_group, GROUND_TRUTH_INDEPENDENCE_UNVERIFIED))

        invalid_group = f"{site}-invalid-group"
        invalid_reason = (
            GROUND_TRUTH_COORDINATE_INVALID
            if shape.invalid_kind == "coordinate"
            else GROUND_TRUTH_UNCERTAINTY_INVALID
        )
        ground_truth.extend(
            _ground_truth(
                value,
                invalid_group,
                coordinate=(101.0, 20.0) if shape.invalid_kind == "coordinate" else (10.0, 20.0),
                uncertainty=6.0 if shape.invalid_kind == "uncertainty" else 0.25,
            )
            for value in special_pairs["invalid"]
        )
        group_reasons.append((site, invalid_group, invalid_reason))

        duplicate_pair = special_pairs["duplicate"]
        original_group = f"{site}-duplicate-original"
        duplicate_group = f"{site}-duplicate-copy"
        ground_truth.extend(
            _ground_truth(value, original_group if index == 0 else f"valid-{value.detection_id}")
            for index, value in enumerate(duplicate_pair)
        )
        ground_truth.append(_ground_truth(duplicate_pair[0], duplicate_group))
        group_reasons.extend((
            (site, original_group, GROUND_TRUTH_DUPLICATE_GROUP),
            (site, duplicate_group, GROUND_TRUTH_DUPLICATE_GROUP),
        ))
        denominators.append((site, base_record_count + 1))

    return EvidenceFixture(
        records=tuple(records),
        ground_truth=tuple(ground_truth),
        assignments=tuple(assignments),
        views=tuple(views),
        expected_denominators=tuple(denominators),
        expected_group_reasons=tuple(group_reasons),
    )


def _present(values: tuple, salt: int) -> tuple:
    """Create a deterministic generated presentation order without altering values."""
    return tuple(sorted(
        values,
        key=lambda value: hashlib.sha256(
            f"{salt}:{value.content_identity.digest}".encode("ascii")
        ).digest(),
    ))


def _freeze(fixture: EvidenceFixture, salt: int):
    freezer = PilotPopulationFreezer()
    try:
        _ = freezer.outcome_access
    except PilotEvidenceError as error:
        assert error.code == POPULATION_NOT_FROZEN
    else:  # pragma: no cover - a capability leak is the property failure
        raise AssertionError("outcomes were accessible before population freeze")
    frozen = freezer.freeze(
        replay_records=_present(fixture.records, salt),
        ground_truth=_present(fixture.ground_truth, salt + 1),
        policies=tuple(_policy(site) for site in ACCEPTANCE_SITES),
        partition_assignments=_present(fixture.assignments, salt + 2),
        independent_views=_present(fixture.views, salt + 3),
    )
    assert freezer.outcome_access == frozen.outcome_access
    return frozen


def _site_of(value) -> str:
    record = getattr(value, "record", None)
    return record.site if record is not None else value.site


def _without_site(fixture: EvidenceFixture, removed_site: str) -> EvidenceFixture:
    return EvidenceFixture(
        records=tuple(value for value in fixture.records if _site_of(value) != removed_site),
        ground_truth=tuple(value for value in fixture.ground_truth if _site_of(value) != removed_site),
        assignments=tuple(value for value in fixture.assignments if value.site != removed_site),
        views=tuple(value for value in fixture.views if value.site != removed_site),
        expected_denominators=fixture.expected_denominators,
        expected_group_reasons=fixture.expected_group_reasons,
    )


def _with_diagnostic_site(fixture: EvidenceFixture) -> EvidenceFixture:
    diagnostic_records = tuple(
        _record("taipei-cm", "taipei-source", f"taipei-frame-{index}", f"taipei-detection-{index}", "taipei-track")
        for index in range(2)
    )
    diagnostic_gt = tuple(
        _ground_truth(value, f"taipei-group-{index}")
        for index, value in enumerate(diagnostic_records)
    )
    return replace(
        fixture,
        records=fixture.records + diagnostic_records,
        ground_truth=fixture.ground_truth + diagnostic_gt,
        views=fixture.views + tuple(_view(value) for value in diagnostic_records),
    )


def _conflicting_fixture(fixture: EvidenceFixture) -> tuple[EvidenceFixture, str]:
    selected = next(
        value for value in fixture.assignments if value.group_kind == TRACK_GROUP
    )
    opposite = (
        PartitionKind.HELD_OUT
        if selected.partition is PartitionKind.PILOT
        else PartitionKind.PILOT
    )
    assignments = tuple(
        replace(value, partition=opposite) if value == selected else value
        for value in fixture.assignments
    )
    return replace(fixture, assignments=assignments), selected.site


def _unsafe_contamination_fixture(fixture: EvidenceFixture) -> tuple[EvidenceFixture, str]:
    contamination_groups = {
        (site, group_id)
        for site, group_id, reason in fixture.expected_group_reasons
        if reason == GROUND_TRUTH_CONTAMINATION
    }
    selected = next(
        value
        for value in fixture.ground_truth
        if (value.record.site, value.matching_group_id) in contamination_groups
        and set(value.creation_inputs).intersection(PROHIBITED_INPUTS)
    )
    ground_truth = tuple(
        replace(value, matching_group_complete=False) if value == selected else value
        for value in fixture.ground_truth
    )
    return replace(fixture, ground_truth=ground_truth), selected.record.site


def _fatal_code_and_site(fixture: EvidenceFixture, salt: int) -> tuple[str, str | None]:
    freezer = PilotPopulationFreezer()
    try:
        freezer.freeze(
            replay_records=_present(fixture.records, salt),
            ground_truth=_present(fixture.ground_truth, salt + 1),
            policies=tuple(_policy(site) for site in reversed(ACCEPTANCE_SITES)),
            partition_assignments=_present(fixture.assignments, salt + 2),
            independent_views=_present(fixture.views, salt + 3),
        )
    except PilotEvidenceError as error:
        try:
            _ = freezer.outcome_access
        except PilotEvidenceError as access_error:
            assert access_error.code == POPULATION_NOT_FROZEN
        else:  # pragma: no cover
            raise AssertionError("failed freeze exposed outcome access")
        return error.code, error.site
    raise AssertionError("invalid evidence unexpectedly froze")


def _assert_whole_group_assignments(site_evidence, fixture: EvidenceFixture) -> None:
    assignment_map = {
        (value.site, value.group_kind, value.group_id): value.partition
        for value in fixture.assignments
    }
    by_track: dict[str, set[PartitionKind]] = {}
    by_source: dict[str, set[PartitionKind]] = {}
    for eligible in site_evidence.eligible_detections:
        record = eligible.record
        assert record.track is not None and record.track.kind is TrackKind.REAL
        expected_track = assignment_map[(record.site, TRACK_GROUP, record.track.claimed_id)]
        expected_source = assignment_map[(record.site, SOURCE_GROUP, record.source_sequence)]
        assert expected_track is expected_source is eligible.partition
        by_track.setdefault(eligible.real_track_id, set()).add(eligible.partition)
        by_source.setdefault(eligible.source_sequence, set()).add(eligible.partition)
        assert eligible.real_track_id.startswith(f"{record.site}:")
        assert eligible.source_sequence.startswith(f"{record.site}:")
        assert eligible.independent_view_id.startswith(f"{record.site}:")
        assert eligible.ground_truth_group_id.startswith(f"{record.site}:")
        assert eligible.ground_truth.site == record.site
        assert eligible.ground_truth.frame_id == record.frame_id
        assert eligible.ground_truth.detection_id == record.detection_id
        assert eligible.ground_truth.real_track_id == record.track.claimed_id
    assert all(len(partitions) == 1 for partitions in by_track.values())
    assert all(len(partitions) == 1 for partitions in by_source.values())

    memberships = [
        eligible_id
        for partition in site_evidence.population.partitions
        for eligible_id in partition.eligible_detection_ids
    ]
    assert len(memberships) == len(set(memberships))
    assert set(memberships) == set(site_evidence.population.frozen_eligible_ids)


@deterministic_property(15)
@given(case=evidence_cases())
def test_independent_evidence_and_partitions_are_leak_free_and_site_isolated(
    case: EvidenceCase,
) -> None:
    """**Validates: Requirements 9.1, 9.4-9.18**"""
    fixture = _build_fixture(case)
    left = _freeze(fixture, case.presentation_salts[0])
    right = _freeze(fixture, case.presentation_salts[1])
    record_failure_metadata(
        replay_identity=left.outcome_access,
        profile_identity=CALIBRATION_ID,
        run_identity=right.outcome_access,
    )

    # Every presentation freezes to the same exclusions, groups, memberships,
    # denominators, and capability identity.
    assert left == right
    assert dict(left.outcome_access.denominators) == dict(fixture.expected_denominators)
    for site in ACCEPTANCE_SITES:
        site_evidence = left.for_site(site)
        _assert_whole_group_assignments(site_evidence, fixture)
        assert site_evidence.denominator == dict(fixture.expected_denominators)[site]
        assert len(site_evidence.population.frozen_eligible_ids) == len(
            set(site_evidence.population.frozen_eligible_ids)
        )
        assert GROUND_TRUTH_MATCH_COUNT_INVALID in {
            value.reason for value in site_evidence.exclusions
        }

    for site, group_id, expected_reason in fixture.expected_group_reasons:
        exclusions = tuple(
            value
            for value in left.for_site(site).exclusions
            if value.matching_group_id == group_id
        )
        assert exclusions
        assert {value.reason for value in exclusions} == {expected_reason}

    # A track/source incidence disagreement fails atomically and identically
    # under arbitrary presentation order.
    conflicting, conflict_site = _conflicting_fixture(fixture)
    conflict_results = {
        _fatal_code_and_site(conflicting, salt) for salt in case.presentation_salts
    }
    assert conflict_results == {(PARTITION_ASSIGNMENT_CONFLICT, conflict_site)}

    # Contamination whose whole matching group cannot be excluded is a fatal,
    # site-scoped error rather than partial population evidence.
    unsafe, unsafe_site = _unsafe_contamination_fixture(fixture)
    unsafe_results = {
        _fatal_code_and_site(unsafe, salt) for salt in case.presentation_salts
    }
    assert unsafe_results == {
        (GROUND_TRUTH_CONTAMINATION_EXCLUSION_FAILED, unsafe_site)
    }

    # Diagnostic evidence is incapable of entering either acceptance namespace.
    diagnostic = _freeze(_with_diagnostic_site(fixture), case.presentation_salts[1])
    assert diagnostic == left
    try:
        diagnostic.for_site("taipei-cm")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("diagnostic site exposed an acceptance population")

    # Removing either acceptance namespace may change only that namespace. The
    # other site's complete pre-decision evidence remains byte-for-byte equal,
    # so neither pooled nor cross-site evidence can rescue or override it.
    changed = _freeze(
        _without_site(fixture, case.changed_site), case.presentation_salts[0]
    )
    unaffected_site = next(
        site for site in ACCEPTANCE_SITES if site != case.changed_site
    )
    assert changed.for_site(unaffected_site) == left.for_site(unaffected_site)
    assert changed.for_site(case.changed_site).denominator == 0


class LeakFreeSiteIsolatedEvidencePropertyTest(unittest.TestCase):
    def test_property_15(self) -> None:
        test_independent_evidence_and_partitions_are_leak_free_and_site_isolated()
