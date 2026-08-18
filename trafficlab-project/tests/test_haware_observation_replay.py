"""Focused tests for the narrow deterministic Haware observation replay."""
from dataclasses import replace
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.io.haware_observation_replay import (  # noqa: E402
    AcceptedReplayRecord,
    COMPRESSION_METADATA,
    ObservationReplayReader,
    ObservationReplayWriter,
    RecordRejection,
    ReplaySchemaError,
    read_legacy_input,
)
from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    ContentIdentity,
    ImageObservation,
    ObservationRecord,
    ProviderProvenance,
    SourceProvenance,
    canonical_bytes,
)
from trafficlab.motion.haware_accuracy.validation import (  # noqa: E402
    ProfileValidationError,
    validate_before_read,
)
from tests.test_haware_profile_validation import profile, scope  # noqa: E402


IDENTITY = ContentIdentity("a" * 64)


def observation(identity="o1", *, pixel=(10.0, 20.0), confidence=0.8, labels=("wheel", "front")):
    return ImageObservation(
        observation_id=identity,
        pixel=pixel,
        confidence=confidence,
        candidate_labels=labels,
        provider_key=f"apollo:{identity}",
    )


def record(*observations):
    return ObservationRecord(
        schema_version="replay-v1",
        site="kee-cc",
        source_sequence="sequence-1",
        frame_id="frame-0001",
        detection_id="detection-7",
        image_size_px=(1280, 720),
        observations=tuple(observations or (observation(),)),
        provider=ProviderProvenance(
            provider_name="provider-neutral-fixture",
            provider_version="1.0",
            adapter_version="adapter-1",
        ),
        source=SourceProvenance(
            source_id="fixture-source",
            repository_relative_path="evidence/kee-cc/replay.json",
            source_content_identity=IDENTITY,
        ),
    )


class ObservationReplayTest(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.scope = scope()
        self.token = validate_before_read(self.profile, self.scope)
        self.reader = ObservationReplayReader()
        self.writer = ObservationReplayWriter()

    def decode(self, payload):
        if payload.startswith(b"\x1f\x8b"):
            payload = gzip.decompress(payload)
        return json.loads(payload.decode("utf-8"))

    def encode(self, envelope):
        return canonical_bytes(envelope)

    def test_canonical_utf8_and_gzip_are_deterministic_and_round_trip(self):
        value = record(observation("觀測-1", labels=("front", "wheel")))
        first = self.writer.canonical_bytes((value,), token=self.token, profile=self.profile, scope=self.scope)
        second = self.writer.canonical_bytes((value,), token=self.token, profile=self.profile, scope=self.scope)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertEqual(self.decode(first)["compression"], COMPRESSION_METADATA)

        compressed_first = self.writer.compressed_bytes((value,), token=self.token, profile=self.profile, scope=self.scope)
        compressed_second = self.writer.compressed_bytes((value,), token=self.token, profile=self.profile, scope=self.scope)
        self.assertEqual(compressed_first, compressed_second)
        self.assertEqual(compressed_first[4:8], b"\x00\x00\x00\x00")
        self.assertEqual(gzip.decompress(compressed_first), first)

        result = self.reader.read(compressed_first, token=self.token, profile=self.profile, scope=self.scope)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AcceptedReplayRecord)
        self.assertEqual(result[0].record, value)
        self.assertEqual(result[0].record.observations[0].candidate_labels, ("front", "wheel"))

    def test_invalid_observation_is_excluded_but_invalid_record_is_isolated(self):
        valid_payload = self.writer.canonical_bytes((record(),), token=self.token, profile=self.profile, scope=self.scope)
        envelope = self.decode(valid_payload)
        valid_raw = envelope["records"][0]
        invalid_observation = copy.deepcopy(valid_raw["observations"][0])
        invalid_observation["pixel"] = [-1.0, 20.0]
        valid_raw["observations"].append(invalid_observation)
        invalid_record = copy.deepcopy(valid_raw)
        invalid_record.pop("source")
        envelope["records"].append(invalid_record)

        results = self.reader.read(self.encode(envelope), token=self.token, profile=self.profile, scope=self.scope)
        self.assertIsInstance(results[0], AcceptedReplayRecord)
        self.assertEqual(len(results[0].record.observations), 1)
        self.assertEqual(tuple(item.reason for item in results[0].exclusions), ("observation_coordinate_out_of_bounds",))
        self.assertEqual(results[0].exclusions[0].observation_id, "o1")
        self.assertEqual(results[1], RecordRejection(record_index=1, reason="record_missing_required_field"))

    def test_duplicate_resolution_and_writer_bytes_ignore_input_permutation(self):
        low_key = observation("same", pixel=(10.0, 20.0), labels=("wheel", "front"))
        other = observation("same", pixel=(11.0, 20.0), labels=("rear",))
        left = record(low_key, other, low_key)
        right = record(low_key, low_key, other)
        left_bytes = self.writer.canonical_bytes((left,), token=self.token, profile=self.profile, scope=self.scope)
        right_bytes = self.writer.canonical_bytes((right,), token=self.token, profile=self.profile, scope=self.scope)
        self.assertEqual(left_bytes, right_bytes)

        raw = self.decode(left_bytes)["records"][0]
        raw["observations"] = [
            self.decode(self.writer.canonical_bytes((record(low_key),), token=self.token, profile=self.profile, scope=self.scope))["records"][0]["observations"][0],
            self.decode(self.writer.canonical_bytes((record(other),), token=self.token, profile=self.profile, scope=self.scope))["records"][0]["observations"][0],
        ]
        envelope = self.decode(left_bytes)
        envelope["records"][0] = raw
        result = self.reader.read(self.encode(envelope), token=self.token, profile=self.profile, scope=self.scope)[0]
        self.assertIsInstance(result, AcceptedReplayRecord)
        self.assertEqual(len(result.record.observations), 1)
        self.assertEqual(tuple(item.reason for item in result.exclusions), ("duplicate_observation_conflict_discarded",))

    def test_required_types_string_collection_and_numeric_bounds_have_stable_scope(self):
        payload = self.writer.canonical_bytes((record(),), token=self.token, profile=self.profile, scope=self.scope)
        base = self.decode(payload)
        cases = []

        bad_identity = copy.deepcopy(base["records"][0])
        bad_identity["frame_id"] = "x" * (self.profile.replay_contract.maximum_string_length + 1)
        cases.append((bad_identity, "invalid_record_identity"))

        bad_count = copy.deepcopy(base["records"][0])
        bad_count["observations"] *= self.profile.replay_contract.maximum_observations + 1
        cases.append((bad_count, "observation_count_out_of_bounds"))

        bad_provenance = copy.deepcopy(base["records"][0])
        bad_provenance["source"]["source_content_identity"]["digest"] = "bad"
        cases.append((bad_provenance, "invalid_record_provenance"))

        for raw, reason in cases:
            with self.subTest(reason=reason):
                envelope = copy.deepcopy(base)
                envelope["records"] = [raw]
                result = self.reader.read(self.encode(envelope), token=self.token, profile=self.profile, scope=self.scope)
                self.assertEqual(result, (RecordRejection(record_index=0, reason=reason),))

    def test_validated_profile_token_is_required_and_identity_bound(self):
        payload = self.writer.canonical_bytes((record(),), token=self.token, profile=self.profile, scope=self.scope)
        changed = replace(self.profile, profile_id="changed-after-validation")
        with self.assertRaisesRegex(ProfileValidationError, "profile_changed_after_validation"):
            self.reader.read(payload, token=self.token, profile=changed, scope=self.scope)
        with self.assertRaises(TypeError):
            self.reader.read(payload, profile=self.profile, scope=self.scope)

    def test_legacy_read_records_path_and_content_identity_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_path = root / "pifpaf" / "stored" / "record.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_bytes(b"legacy evidence\n")
            imported = read_legacy_input(
                root, "pifpaf/stored/record.json",
                token=self.token, profile=self.profile, scope=self.scope,
            )
            self.assertEqual(imported.payload, b"legacy evidence\n")
            self.assertEqual(imported.provenance.repository_relative_path, "pifpaf/stored/record.json")
            self.assertEqual(imported.provenance.source_content_identity, ContentIdentity.for_bytes(imported.payload))
            self.assertEqual(legacy_path.read_bytes(), imported.payload)
            with self.assertRaisesRegex(ReplaySchemaError, "legacy_input_tree_is_read_only"):
                self.writer.write(
                    legacy_path, (record(),), token=self.token, profile=self.profile,
                    scope=self.scope, repository_root=root,
                )
            self.assertEqual(legacy_path.read_bytes(), imported.payload)

            nonlegacy = root / "trafficlab-project" / "location" / "record.json"
            nonlegacy.parent.mkdir(parents=True)
            nonlegacy.write_bytes(b"not root legacy")
            with self.assertRaisesRegex(ReplaySchemaError, "not_legacy_input_tree"):
                read_legacy_input(
                    root, nonlegacy,
                    token=self.token, profile=self.profile, scope=self.scope,
                )

    def test_envelope_failures_are_stable_payload_level_rejections(self):
        result = self.reader.read(b"not json", token=self.token, profile=self.profile, scope=self.scope)
        self.assertEqual(result, (RecordRejection(record_index=-1, reason="invalid_replay_payload"),))
        envelope = self.decode(
            self.writer.canonical_bytes((record(),), token=self.token, profile=self.profile, scope=self.scope)
        )
        envelope["compression"] = {**COMPRESSION_METADATA, "mtime": 1}
        result = self.reader.read(self.encode(envelope), token=self.token, profile=self.profile, scope=self.scope)
        self.assertEqual(result, (RecordRejection(record_index=-1, reason="compression_metadata_mismatch"),))


if __name__ == "__main__":
    unittest.main()
