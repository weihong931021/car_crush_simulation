"""Property 11: provider-neutral replay round trips are canonical."""
from __future__ import annotations

import copy
from dataclasses import replace
import json
import unittest

from hypothesis import given, strategies as st

from trafficlab.io.haware_observation_replay import (
    AcceptedReplayRecord,
    ObservationReplayReader,
    ObservationReplayWriter,
    RecordRejection,
)
from trafficlab.motion.haware_accuracy.models import (
    ContentIdentity,
    ObservationRecord,
    ProviderProvenance,
    SourceProvenance,
    canonical_bytes,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read
from tests.property_support.config import deterministic_property, record_failure_metadata
from tests.property_support.strategies import IDENTIFIERS, SITES, observations, track_provenance
from tests.test_haware_profile_validation import profile, scope


@st.composite
def bounded_replay_records(draw):
    """Generate small valid replays with all required provenance surfaces."""
    count = draw(st.integers(min_value=2, max_value=4))
    records = []
    for index in range(count):
        site = draw(SITES)
        sequence = f"{site}:sequence-{index}"
        generated_observations = draw(st.lists(
            observations(), min_size=2, max_size=6,
            unique_by=lambda item: item.observation_id,
        ))
        track = draw(st.one_of(st.none(), track_provenance()))
        if track is not None:
            track = replace(track, source_sequence=sequence)
        source_digest = draw(st.binary(min_size=32, max_size=32)).hex()
        source_leaf = draw(IDENTIFIERS)
        records.append(ObservationRecord(
            schema_version="replay-v1",
            site=site,
            source_sequence=sequence,
            frame_id=f"frame-{index}-{draw(IDENTIFIERS)}",
            detection_id=f"detection-{index}-{draw(IDENTIFIERS)}",
            image_size_px=(1920, 1080),
            observations=tuple(generated_observations),
            provider=ProviderProvenance(
                provider_name=f"provider-{draw(IDENTIFIERS)}",
                provider_version=draw(IDENTIFIERS),
                adapter_version=draw(IDENTIFIERS),
            ),
            source=SourceProvenance(
                source_id=f"source-{source_leaf}",
                repository_relative_path=f"evidence/{site}/{source_leaf}-{index}.json",
                source_content_identity=ContentIdentity(source_digest),
            ),
            track=track,
        ))
    return tuple(records)


def _decode(payload: bytes) -> dict:
    return json.loads(payload.decode("utf-8"))


def _equivalent_presentations(payload: bytes) -> tuple[bytes, bytes]:
    """Add exact duplicates and permute every schema-defined set-like array."""
    left = _decode(payload)
    right = copy.deepcopy(left)
    for raw in left["records"]:
        raw["observations"].append(copy.deepcopy(raw["observations"][0]))
    for raw in right["records"]:
        raw["observations"].append(copy.deepcopy(raw["observations"][0]))
        raw["observations"].reverse()
        for observation in raw["observations"]:
            observation["candidate_labels"].reverse()
        if raw.get("track") is not None:
            raw["track"]["observed_frames"].reverse()
    right["records"].reverse()
    return canonical_bytes(left), canonical_bytes(right)


def _record_key(record: ObservationRecord) -> tuple[str, str, str, str]:
    return record.site, record.source_sequence, record.frame_id, record.detection_id


def _accepted_by_identity(results):
    accepted = {}
    for item in results:
        assert isinstance(item, AcceptedReplayRecord)
        accepted[_record_key(item.record)] = (
            item.record,
            tuple((exclusion.observation_id, exclusion.reason) for exclusion in item.exclusions),
        )
    return accepted


def _preserved_provenance(record: ObservationRecord):
    return (
        record.provider,
        tuple(
            (observation.observation_id, observation.confidence,
             observation.candidate_labels, observation.provider_key)
            for observation in record.observations
        ),
        record.frame_id,
        record.detection_id,
        record.source,
        record.track,
    )


_MALFORMED_REASONS = {
    "missing_source": "record_missing_required_field",
    "observations_not_list": "invalid_observation_collection",
    "invalid_frame_identity": "invalid_record_identity",
    "invalid_provider": "invalid_record_provenance",
}


def _malform(raw: dict, kind: str) -> None:
    if kind == "missing_source":
        raw.pop("source")
    elif kind == "observations_not_list":
        raw["observations"] = {}
    elif kind == "invalid_frame_identity":
        raw["frame_id"] = ""
    else:
        raw["provider"].pop("provider_version")


@deterministic_property(11)
@given(
    records=bounded_replay_records(),
    malformed_kind=st.sampled_from(tuple(_MALFORMED_REASONS)),
    data=st.data(),
)
def _check_provider_neutral_replay_round_trip_is_canonical(
    records, malformed_kind, data,
):
    """**Validates: Requirements 1.4, 2.5, 2.6, 2.9, 2.13, 2.15, 2.16, 2.17**"""
    profile_value = profile()
    scope_value = scope()
    token = validate_before_read(profile_value, scope_value)
    writer = ObservationReplayWriter()
    reader = ObservationReplayReader()

    canonical = writer.canonical_bytes(
        records, token=token, profile=profile_value, scope=scope_value,
    )
    canonical_reordered = writer.canonical_bytes(
        tuple(reversed(records)), token=token, profile=profile_value, scope=scope_value,
    )
    compressed = writer.compressed_bytes(
        records, token=token, profile=profile_value, scope=scope_value,
    )
    compressed_reordered = writer.compressed_bytes(
        tuple(reversed(records)), token=token, profile=profile_value, scope=scope_value,
    )
    assert canonical == canonical_reordered
    assert compressed == compressed_reordered

    record_failure_metadata(
        replay_identity=ContentIdentity.for_bytes(canonical),
        profile_identity=profile_value,
        run_identity=ContentIdentity.for_bytes(compressed),
    )

    expected = {_record_key(record): record for record in records}
    round_trip = _accepted_by_identity(
        reader.read(canonical, token=token, profile=profile_value, scope=scope_value)
    )
    compressed_round_trip = _accepted_by_identity(
        reader.read(compressed, token=token, profile=profile_value, scope=scope_value)
    )
    assert {key: value[0] for key, value in round_trip.items()} == expected
    assert compressed_round_trip == round_trip
    assert all(not exclusions for _, exclusions in round_trip.values())

    left_payload, right_payload = _equivalent_presentations(canonical)
    left = _accepted_by_identity(
        reader.read(left_payload, token=token, profile=profile_value, scope=scope_value)
    )
    right = _accepted_by_identity(
        reader.read(right_payload, token=token, profile=profile_value, scope=scope_value)
    )
    assert left == right
    assert {key: value[0] for key, value in left.items()} == expected
    assert all(exclusions == ((record.observations[0].observation_id,
                               "duplicate_observation_exact"),)
               for record, exclusions in left.values())
    assert {_record_key(record): _preserved_provenance(record) for record in records} == {
        key: _preserved_provenance(value[0]) for key, value in left.items()
    }

    normalized_bytes = writer.canonical_bytes(
        (value[0] for value in right.values()),
        token=token, profile=profile_value, scope=scope_value,
    )
    assert normalized_bytes == canonical

    malformed_envelope = _decode(left_payload)
    malformed = copy.deepcopy(malformed_envelope["records"][0])
    _malform(malformed, malformed_kind)
    insertion = data.draw(
        st.integers(min_value=0, max_value=len(malformed_envelope["records"])),
        label="malformed_record_index",
    )
    malformed_envelope["records"].insert(insertion, malformed)
    isolated = reader.read(
        canonical_bytes(malformed_envelope),
        token=token, profile=profile_value, scope=scope_value,
    )
    assert isolated[insertion] == RecordRejection(
        record_index=insertion, reason=_MALFORMED_REASONS[malformed_kind],
    )
    assert sum(isinstance(item, RecordRejection) for item in isolated) == 1
    surviving = _accepted_by_identity(
        tuple(item for item in isolated if isinstance(item, AcceptedReplayRecord))
    )
    assert {key: value[0] for key, value in surviving.items()} == expected


class ProviderNeutralReplayPropertyTest(unittest.TestCase):
    def test_provider_neutral_replay_round_trip_is_canonical(self):
        _check_provider_neutral_replay_round_trip_is_canonical()


if __name__ == "__main__":
    unittest.main()
