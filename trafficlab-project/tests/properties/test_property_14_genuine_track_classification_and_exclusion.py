"""Property 14: genuine track classification and downstream exclusion."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from hypothesis import given, strategies as st

from trafficlab.io.haware_track_provenance import (
    FRAME_LOCAL_TRACK_ID,
    INCOMPLETE_TRACK_PROVENANCE,
    INCONSISTENT_TRACK_PROVENANCE,
    UNVERIFIED_TRACK_IDENTITY,
    finalize_track_provenance,
)
from trafficlab.measurement.haware_pilot import (
    SOURCE_GROUP,
    TRACK_GROUP,
    GroundTruthEvidence,
    GroundTruthValidationPolicy,
    IndependentViewMembership,
    PartitionAssignment,
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
from tests.property_support.config import (
    deterministic_property,
    record_failure_metadata,
)


CALIBRATION_ID = ContentIdentity("a" * 64)
SOURCE_ID = ContentIdentity("b" * 64)
SITES = ("kee-cc", "taoyuan-tc")
TRACK_FIELDS = (
    "tracker_name",
    "tracker_version",
    "source_sequence",
    "association_provenance",
)

@dataclass(frozen=True)
class TrackReplayCase:
    genuine_records: tuple[ObservationRecord, ...]
    pseudo_records: tuple[ObservationRecord, ...]
    ground_truth: tuple[GroundTruthEvidence, ...]
    assignments: tuple[PartitionAssignment, ...]
    views: tuple[IndependentViewMembership, ...]
    partitions: tuple[PartitionKind, PartitionKind]


def _source(source_id: str) -> SourceProvenance:
    return SourceProvenance(
        source_id=source_id,
        repository_relative_path=None,
        source_content_identity=SOURCE_ID,
    )


def _claim(
    claimed_id: str,
    sequence: str | None,
    *,
    tracker_name: str | None = "tracker",
    tracker_version: str | None = "1.0",
    association: str | None = "tracker-output",
    observed_frames: tuple[str, ...] = ("untrusted-1", "untrusted-2"),
    input_kind: TrackKind = TrackKind.REAL,
) -> TrackProvenance:
    return TrackProvenance(
        claimed_id=claimed_id,
        tracker_name=tracker_name,
        tracker_version=tracker_version,
        source_sequence=sequence,
        association_provenance=association,
        observed_frames=observed_frames,
        kind=input_kind,
        reason="untrusted-input-kind",
    )


def _record(
    site: str,
    sequence: str,
    frame_id: str,
    detection_id: str,
    track: TrackProvenance,
) -> ObservationRecord:
    observation = ImageObservation(
        observation_id=f"observation-{detection_id}",
        pixel=(100.0, 200.0),
        confidence=0.9,
        candidate_labels=("wheel",),
        provider_key=f"generated:{detection_id}",
    )
    return ObservationRecord(
        site=site,
        source_sequence=sequence,
        frame_id=frame_id,
        detection_id=detection_id,
        image_size_px=(1280, 720),
        observations=(observation,),
        provider=ProviderProvenance(
            provider_name="generated",
            provider_version="1.0",
            adapter_version="1.0",
        ),
        source=_source(f"replay:{site}"),
        track=track,
    )


def _ground_truth(record: ObservationRecord, ordinal: int) -> GroundTruthEvidence:
    assert record.track is not None
    value = GroundTruthRecord(
        site=record.site,
        frame_id=record.frame_id,
        detection_id=record.detection_id,
        real_track_id=record.track.claimed_id,
        reference_point="vehicle_ground_center",
        metric_coordinate_m=(float(ordinal), float(ordinal + 1)),
        calibration_identity=CALIBRATION_ID,
        source=_source(f"independent-gt:{record.site}"),
        annotator_provenance="independent-team-v1",
        independence_attestation="independent_no_haware_access",
        uncertainty_m=0.25,
    )
    return GroundTruthEvidence(
        record=value,
        matching_group_id=f"group-{record.site}-{record.frame_id}",
        units="metre",
        creation_inputs=("raw_video",),
        source_lineage=("manual_annotation",),
    )


def _view(record: ObservationRecord) -> IndependentViewMembership:
    return IndependentViewMembership(
        site=record.site,
        frame_id=record.frame_id,
        detection_id=record.detection_id,
        view_id=f"view-{record.site}",
        camera_id=f"camera-{record.site}",
        scene_region_id="road-center",
        source_video_id=record.source_sequence,
    )


def _policy(site: str) -> GroundTruthValidationPolicy:
    return GroundTruthValidationPolicy(
        site=site,
        calibration_identity=CALIBRATION_ID,
        reference_point="vehicle_ground_center",
        coordinate_x_m=ClosedInterval(lower=0.0, upper=100.0),
        coordinate_y_m=ClosedInterval(lower=0.0, upper=100.0),
        uncertainty_m=ClosedInterval(lower=0.0, upper=1.0),
    )


def _assignment(
    site: str, group_kind: str, group_id: str, partition: PartitionKind
) -> PartitionAssignment:
    return PartitionAssignment(
        site=site,
        group_kind=group_kind,
        group_id=group_id,
        partition=partition,
    )


@st.composite
def track_replay_cases(draw) -> TrackReplayCase:
    """Generate complete and every required pseudo provenance shape."""
    real_numeric_id = str(draw(st.integers(min_value=1000, max_value=9999)))
    frame_local_id = str(draw(st.integers(min_value=500, max_value=999)))
    missing_field = draw(st.sampled_from(TRACK_FIELDS))
    inconsistent_field = draw(st.sampled_from(TRACK_FIELDS))
    input_kind = draw(st.sampled_from(tuple(TrackKind)))
    partitions = (
        draw(st.sampled_from(tuple(PartitionKind))),
        draw(st.sampled_from(tuple(PartitionKind))),
    )

    genuine: list[ObservationRecord] = []
    pseudo: list[ObservationRecord] = []
    assignments: list[PartitionAssignment] = []
    for site_index, (site, partition) in enumerate(zip(SITES, partitions)):
        sequence = f"sequence-{site}"
        real_claim = _claim(real_numeric_id, sequence, input_kind=input_kind)
        for frame_index in range(2):
            genuine.append(_record(
                site,
                sequence,
                f"real-frame-{frame_index}",
                f"real-detection-{frame_index}",
                real_claim,
            ))
        assignments.extend((
            _assignment(site, TRACK_GROUP, real_numeric_id, partition),
            _assignment(site, SOURCE_GROUP, sequence, partition),
        ))

        incomplete_values = {
            "tracker_name": "tracker",
            "tracker_version": "1.0",
            "source_sequence": sequence,
            "association": "tracker-output",
        }
        incomplete_values[
            "association" if missing_field == "association_provenance" else missing_field
        ] = None
        incomplete = _claim(
            f"incomplete-{site_index}",
            incomplete_values["source_sequence"],
            tracker_name=incomplete_values["tracker_name"],
            tracker_version=incomplete_values["tracker_version"],
            association=incomplete_values["association"],
            input_kind=input_kind,
        )
        pseudo.extend(
            _record(site, sequence, f"incomplete-{index}", f"inc-{index}", incomplete)
            for index in range(2)
        )

        consistent = _claim(f"inconsistent-{site_index}", sequence, input_kind=input_kind)
        changed = {
            "tracker_name": consistent.tracker_name,
            "tracker_version": consistent.tracker_version,
            "source_sequence": consistent.source_sequence,
            "association": consistent.association_provenance,
        }
        key = "association" if inconsistent_field == "association_provenance" else inconsistent_field
        changed[key] = f"changed-{site_index}"
        conflicting = _claim(
            consistent.claimed_id,
            changed["source_sequence"],
            tracker_name=changed["tracker_name"],
            tracker_version=changed["tracker_version"],
            association=changed["association"],
            input_kind=input_kind,
        )
        pseudo.extend((
            _record(site, sequence, "inconsistent-0", "bad-0", consistent),
            _record(site, sequence, "inconsistent-1", "bad-1", conflicting),
        ))

        one_frame = _claim(
            f"one-frame-{site_index}",
            sequence,
            observed_frames=("claimed-a", "claimed-b"),
            input_kind=input_kind,
        )
        pseudo.append(_record(site, sequence, "only-frame", "one-0", one_frame))

        frame_local = _claim(
            frame_local_id,
            sequence,
            association="frame-local-detection-index",
            input_kind=input_kind,
        )
        pseudo.extend(
            _record(site, sequence, f"display-{index}", f"display-{index}", frame_local)
            for index in range(2)
        )

    pseudo_records = tuple(draw(st.permutations(tuple(pseudo))))
    genuine_records = tuple(draw(st.permutations(tuple(genuine))))
    return TrackReplayCase(
        genuine_records=genuine_records,
        pseudo_records=pseudo_records,
        ground_truth=tuple(_ground_truth(value, index + 1) for index, value in enumerate(genuine)),
        assignments=tuple(assignments),
        views=tuple(_view(value) for value in genuine),
        partitions=partitions,
    )


def _freeze(case: TrackReplayCase, records: tuple[ObservationRecord, ...]):
    return PilotPopulationFreezer().freeze(
        replay_records=records,
        ground_truth=case.ground_truth,
        policies=tuple(_policy(site) for site in SITES),
        partition_assignments=case.assignments,
        independent_views=case.views,
    )


def _downstream_evidence_surfaces(frozen):
    """Project every genuine-track-only input surface named by Property 14.

    Metric/interval/power implementations are later tasks. Their authoritative
    inputs are frozen here, so equality proves pseudo claims cannot influence
    those calculations without bypassing the production population boundary.
    """
    result = []
    for site in frozen.sites:
        eligible = site.eligible_detections
        clustered = tuple(
            (track_id, tuple(item.eligible_detection_id for item in values))
            for track_id, values_iter in groupby(
                sorted(eligible, key=lambda item: item.real_track_id),
                key=lambda item: item.real_track_id,
            )
            for values in (tuple(values_iter),)
        )
        result.append((
            site.site,
            # Acceptance metric inputs: denominator, detections, and metric GT.
            (site.denominator, tuple(
                (item.eligible_detection_id, item.ground_truth.metric_coordinate_m)
                for item in eligible
            )),
            # Track-clustered interval/bootstrap inputs.
            clustered,
            # Power inputs: genuine clusters, views, and GT uncertainty.
            (
                site.population.real_track_ids,
                site.population.independent_views,
                tuple(item.ground_truth.uncertainty_m for item in eligible),
            ),
            # Whole-track/source partition evidence.
            site.population.partitions,
            # Motion diagnostic inputs, strictly grouped by validated real track.
            tuple(
                (track_id, tuple(
                    (item.record.frame_id, item.ground_truth.metric_coordinate_m)
                    for item in values
                ))
                for track_id, values_iter in groupby(
                    sorted(eligible, key=lambda item: (item.real_track_id, item.record.frame_id)),
                    key=lambda item: item.real_track_id,
                )
                for values in (tuple(values_iter),)
            ),
        ))
    return tuple(result)


@deterministic_property(14)
@given(case=track_replay_cases())
def test_genuine_track_classification_and_exclusion(case: TrackReplayCase) -> None:
    # **Validates: Requirements 8.1-8.8, 8.10, 8.13, 10.32**
    baseline_finalized = finalize_track_provenance(case.genuine_records)
    augmented_finalized = finalize_track_provenance(
        case.genuine_records + case.pseudo_records
    )

    # Complete consistent claims are genuine even with numeric IDs above 500.
    assert augmented_finalized.real_track_records == baseline_finalized.real_track_records
    assert len(augmented_finalized.real_track_records) == 4
    assert all(
        record.track is not None
        and record.track.kind is TrackKind.REAL
        and record.track.reason is None
        and len(record.track.observed_frames) == 2
        for record in augmented_finalized.real_track_records
    )

    diagnostic = augmented_finalized.frame_local_diagnostic(
        diagnostic_name="property-14-frame-local-audit"
    )
    assert len(diagnostic.entries) == len(case.pseudo_records)
    assert {entry.reason for entry in diagnostic.entries} == {
        INCOMPLETE_TRACK_PROVENANCE,
        INCONSISTENT_TRACK_PROVENANCE,
        UNVERIFIED_TRACK_IDENTITY,
        FRAME_LOCAL_TRACK_ID,
    }
    assert all(
        entry.record.track is not None
        and entry.record.track.kind is TrackKind.PSEUDO
        for entry in diagnostic.entries
    )
    assert not hasattr(augmented_finalized, "records")

    baseline = _freeze(case, case.genuine_records)
    augmented = _freeze(case, case.genuine_records + case.pseudo_records)
    record_failure_metadata(
        replay_identity=augmented.outcome_access,
        profile_identity=CALIBRATION_ID,
        run_identity=baseline.outcome_access,
    )

    # Production partitions and every downstream genuine-only evidence surface
    # are byte-for-byte value equal after arbitrary pseudo-claim changes.
    assert augmented == baseline
    assert _downstream_evidence_surfaces(augmented) == _downstream_evidence_surfaces(
        baseline
    )
    assert tuple(site.denominator for site in augmented.sites) == (2, 2)
    assert tuple(
        next(
            partition.kind
            for partition in site.population.partitions
            if partition.eligible_detection_ids
        )
        for site in augmented.sites
    ) == case.partitions


from unittest import TestCase


class GenuineTrackClassificationAndExclusionPropertyTest(TestCase):
    def test_property_14(self) -> None:
        test_genuine_track_classification_and_exclusion()
