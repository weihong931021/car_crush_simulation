"""Focused tests for the sole PifPaf adapter and one-way replay import."""
import ast
import gzip
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.inference.pifpaf_haware_adapter import (  # noqa: E402
    ADAPTER_VERSION,
    APOLLO_24_LABELS,
    PifPafObservationAdapter,
    PifPafProviderRecord,
    TrafficLabReplayImporter,
)
from trafficlab.io.haware_observation_replay import (  # noqa: E402
    AcceptedReplayRecord,
    ObservationReplayReader,
    ObservationReplayWriter,
    RecordRejection,
)
from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    ContentIdentity,
    SourceProvenance,
    TrackKind,
)
from trafficlab.motion.haware_accuracy.validation import validate_before_read  # noqa: E402
from tests.test_haware_profile_validation import profile, scope  # noqa: E402


SOURCE_BYTES = b"source replay bytes"
SOURCE = SourceProvenance(
    source_id="pifpaf-fixture",
    repository_relative_path="pifpaf/stored/fixture.json",
    source_content_identity=ContentIdentity.for_bytes(SOURCE_BYTES),
)


def keypoints(*, valid_index=7, confidence=0.91):
    rows = [[0.0, -4.0, 0.0] for _ in APOLLO_24_LABELS]
    rows[valid_index] = [320.5, 240.25, confidence]
    return rows


def provider_record(rows=None):
    return PifPafProviderRecord(
        site="kee-cc",
        source_sequence="sequence-1",
        frame_id="12",
        detection_id="4",
        image_size_px=(1280, 720),
        keypoints=keypoints() if rows is None else rows,
        provider_version="0.13.11",
        source=SOURCE,
    )


class PifPafHawareAdapterTest(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.scope = scope()
        self.token = validate_before_read(self.profile, self.scope)
        self.adapter = PifPafObservationAdapter()

    def test_apollo24_maps_to_candidate_evidence_and_preserves_confidence(self):
        result = self.adapter.normalize(provider_record(), self.profile.replay_contract)
        self.assertIsInstance(result, AcceptedReplayRecord)
        self.assertEqual(len(result.record.observations), 1)
        observation = result.record.observations[0]
        self.assertEqual(observation.observation_id, "apollo24:07")
        self.assertEqual(observation.provider_key, "apollo24:07")
        self.assertEqual(observation.candidate_labels, ("front_wheel_left",))
        self.assertEqual(observation.confidence, 0.91)
        self.assertEqual(result.record.provider.provider_name, "openpifpaf")
        self.assertEqual(result.record.provider.adapter_version, ADAPTER_VERSION)
        self.assertFalse(hasattr(observation, "confirmed_label"))
        self.assertFalse(hasattr(observation, "correspondence"))
        self.assertEqual(len(result.exclusions), 23)

    def test_invalid_provider_observation_is_excluded_without_rejecting_record(self):
        rows = keypoints(valid_index=8)
        rows[7] = [100.0, 200.0, float("nan")]
        result = self.adapter.normalize(provider_record(rows), self.profile.replay_contract)
        self.assertIsInstance(result, AcceptedReplayRecord)
        self.assertEqual(tuple(item.observation_id for item in result.record.observations), ("apollo24:08",))
        reasons = {(item.observation_id, item.reason) for item in result.exclusions}
        self.assertIn(("apollo24:07", "observation_non_finite_confidence"), reasons)

    def test_wrong_apollo_count_rejects_complete_provider_record(self):
        result = self.adapter.normalize(provider_record(keypoints()[:-1]), self.profile.replay_contract)
        self.assertEqual(result, RecordRejection(
            record_index=0, reason="pifpaf_apollo24_keypoint_count_invalid"
        ))

    def test_one_way_import_records_source_provider_and_emits_replay_schema(self):
        legacy = {
            "mp4_path": "location/kee-cc/footage/clip.mp4",
            "meta": {"resolution": [1280, 720], "fps": 30.0},
            "location_code": "kee-cc",
            "frames": [{
                "frame_index": 12,
                "objects": [{
                    "id": 4,
                    "tracked_id": 503,
                    "confidence": 0.99,
                    "sat_coords": [999.0, 888.0],
                    "kp_sat": [[1.0, 2.0]],
                    "kp_cctv": keypoints(valid_index=19, confidence=1.0),
                }],
            }],
        }
        payload = gzip.compress(json.dumps(legacy).encode("utf-8"), mtime=0)
        result = TrafficLabReplayImporter().import_payload(
            payload,
            source_repository_relative_path="trafficlab-project/output/haware/kee-cc/clip.json.gz",
            provider_version="0.13.11",
            contract=self.profile.replay_contract,
        )
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AcceptedReplayRecord)
        record = result[0].record
        self.assertEqual(record.source.repository_relative_path, "trafficlab-project/output/haware/kee-cc/clip.json.gz")
        self.assertEqual(record.source.source_content_identity, ContentIdentity.for_bytes(payload))
        self.assertEqual(record.provider.provider_name, "openpifpaf")
        self.assertEqual(record.observations[0].candidate_labels, ("front_wheel_right",))
        self.assertEqual(record.track.kind, TrackKind.PSEUDO)
        self.assertEqual(record.track.claimed_id, "503")
        self.assertEqual(record.track.reason, "frame_local_track_identity")
        self.assertEqual(record.track.association_provenance, "frame-local-detection-index")

        writer = ObservationReplayWriter()
        replay = writer.canonical_bytes(
            (record,), token=self.token, profile=self.profile, scope=self.scope,
        )
        round_trip = ObservationReplayReader().read(
            replay, token=self.token, profile=self.profile, scope=self.scope,
        )
        self.assertEqual(round_trip[0].record, record)

    def test_legacy_object_failure_is_isolated(self):
        legacy = {
            "mp4_path": "location/kee-cc/clip.mp4",
            "meta": {"resolution": [1280, 720]},
            "location_code": "kee-cc",
            "frames": [{"frame_index": 1, "objects": [
                {"id": 1, "tracked_id": None, "kp_cctv": keypoints()},
                {"id": 2, "tracked_id": None, "kp_cctv": keypoints()[:-1]},
            ]}],
        }
        payload = json.dumps(legacy).encode("utf-8")
        results = TrafficLabReplayImporter().import_payload(
            payload,
            source_repository_relative_path="trafficlab-project/output/legacy.json",
            provider_version="0.13.11",
            contract=self.profile.replay_contract,
        )
        self.assertIsInstance(results[0], AcceptedReplayRecord)
        self.assertEqual(results[0].record_index, 0)
        self.assertEqual(results[1], RecordRejection(
            record_index=1, reason="pifpaf_apollo24_keypoint_count_invalid"
        ))

    def test_importing_adapter_does_not_import_openpifpaf(self):
        project = Path(__file__).resolve().parents[1]
        script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'openpifpaf' or name.startswith('openpifpaf.'):
        raise AssertionError('provider imported at adapter module import time')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import trafficlab.inference.pifpaf_haware_adapter
"""
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=project,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_openpifpaf_imports_exist_only_in_adapter_and_motion_is_provider_neutral(self):
        project = Path(__file__).resolve().parents[1]
        provider_import_files = set()
        for root in (project / "trafficlab", project / "scripts"):
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    if any(name == "openpifpaf" or name.startswith("openpifpaf.") for name in names):
                        provider_import_files.add(path.relative_to(project).as_posix())
        self.assertEqual(provider_import_files, {
            "trafficlab/inference/pifpaf_haware_adapter.py"
        })
        for path in (project / "trafficlab" / "motion").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("pifpaf_haware_adapter", text)
            self.assertNotIn("openpifpaf", text.lower())


if __name__ == "__main__":
    unittest.main()
