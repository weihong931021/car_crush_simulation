"""Replay/adapter integration coverage for Haware Task 2.6."""
import ast
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from trafficlab.inference.pifpaf_haware_adapter import TrafficLabReplayImporter  # noqa: E402
from trafficlab.io.haware_observation_replay import (  # noqa: E402
    AcceptedReplayRecord, ObservationReplayReader, ObservationReplayWriter,
    RecordRejection, ReplaySchemaError,
)
from trafficlab.io.haware_track_provenance import (  # noqa: E402
    FRAME_LOCAL_TRACK_ID, finalize_track_provenance,
)
from trafficlab.motion.haware_accuracy.models import ContentIdentity, TrackKind  # noqa: E402
from trafficlab.motion.haware_accuracy.validation import validate_before_read  # noqa: E402
from tests.test_haware_profile_validation import profile, scope  # noqa: E402

FIXTURE = REPOSITORY_ROOT / "scenes" / "taipei-cm" / "trajectory.json"


def representative_payload(*, tracked_id=None):
    """Select two real Apollo-24 rows from the checked-in PifPaf replay."""
    replay = json.loads(FIXTURE.read_text(encoding="utf-8"))
    frames = []
    for frame in replay["frames"]:
        objects = [
            copy.deepcopy(value) for value in frame["objects"]
            if isinstance(value.get("kp_cctv"), list) and len(value["kp_cctv"]) == 24
        ]
        if not objects:
            continue
        if tracked_id is not None:
            objects[0]["tracked_id"] = tracked_id
        frames.append({"frame_index": frame["frame_index"], "objects": objects[:1]})
        if len(frames) == 2:
            break
    assert len(frames) == 2
    replay["frames"] = frames
    return json.dumps(replay, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class HawareReplayAdapterIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.scope = scope()
        self.token = validate_before_read(self.profile, self.scope)
        self.importer = TrafficLabReplayImporter()
        self.reader = ObservationReplayReader()
        self.writer = ObservationReplayWriter()

    def import_fixture(self, site, *, tracked_id=None):
        payload = representative_payload(tracked_id=tracked_id)
        relative = FIXTURE.relative_to(REPOSITORY_ROOT).as_posix()
        results = self.importer.import_payload(
            payload,
            source_repository_relative_path=relative,
            provider_version="representative-checked-in-fixture",
            contract=self.profile.replay_contract,
            source_sequence=f"{site}-stored-keypoints",
            site=site,
        )
        return payload, results

    def test_existing_pifpaf_fixture_imports_for_both_sites_and_round_trips(self):
        records = []
        for site in ("kee-cc", "taoyuan-tc"):
            with self.subTest(site=site):
                payload, results = self.import_fixture(site)
                self.assertTrue(results)
                self.assertTrue(all(isinstance(item, AcceptedReplayRecord) for item in results))
                record = results[0].record
                self.assertEqual(record.site, site)
                self.assertEqual(record.provider.provider_name, "openpifpaf")
                self.assertEqual(record.source.repository_relative_path, "scenes/taipei-cm/trajectory.json")
                self.assertEqual(record.source.source_content_identity, ContentIdentity.for_bytes(payload))
                self.assertTrue(record.observations)
                self.assertTrue(all(len(value.candidate_labels) == 1 for value in record.observations))
                records.append(record)

        canonical = self.writer.canonical_bytes(
            records, token=self.token, profile=self.profile, scope=self.scope,
        )
        compressed = self.writer.compressed_bytes(
            records, token=self.token, profile=self.profile, scope=self.scope,
        )
        self.assertEqual(
            self.reader.read_verified(
                canonical, token=self.token, profile=self.profile, scope=self.scope,
            ),
            self.reader.read_verified(
                compressed, token=self.token, profile=self.profile, scope=self.scope,
            ),
        )
        self.assertTrue(all(
            isinstance(item, AcceptedReplayRecord)
            for item in self.reader.read_verified(
                compressed, token=self.token, profile=self.profile, scope=self.scope,
            )
        ))

    def test_legacy_500_display_ids_finalize_as_pseudo(self):
        _, results = self.import_fixture("kee-cc", tracked_id=503)
        records = tuple(item.record for item in results if isinstance(item, AcceptedReplayRecord))
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record.track.kind is TrackKind.PSEUDO for record in records))
        replay = finalize_track_provenance(records)
        self.assertEqual(replay.real_track_records, ())
        entries = replay.frame_local_diagnostic(
            diagnostic_name="legacy-pifpaf-display-id-audit",
        ).entries
        self.assertEqual({entry.reason for entry in entries}, {FRAME_LOCAL_TRACK_ID})
        self.assertTrue(all(entry.record.track.kind is TrackKind.PSEUDO for entry in entries))

    def test_malformed_and_round_trip_mismatch_records_are_isolated(self):
        records = [
            self.import_fixture(site)[1][0].record
            for site in ("kee-cc", "taoyuan-tc")
        ]
        payload = self.writer.canonical_bytes(
            records, token=self.token, profile=self.profile, scope=self.scope,
        )
        envelope = json.loads(payload)
        self.assertGreater(len(envelope["records"][0]["observations"]), 1)
        envelope["records"][0]["observations"].reverse()
        malformed = copy.deepcopy(envelope["records"][1])
        malformed.pop("source")
        envelope["records"].append(malformed)
        altered = json.dumps(
            envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8") + b"\n"

        results = self.reader.read_verified(
            altered, token=self.token, profile=self.profile, scope=self.scope,
        )
        self.assertEqual(results[0], RecordRejection(
            record_index=0, reason="replay_round_trip_mismatch",
        ))
        self.assertIsInstance(results[1], AcceptedReplayRecord)
        self.assertEqual(results[2], RecordRejection(
            record_index=2, reason="record_missing_required_field",
        ))

    def test_replay_path_neither_imports_nor_invokes_openpifpaf(self):
        script = """
import builtins, json, pathlib
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'openpifpaf' or name.startswith('openpifpaf.'):
        raise AssertionError('stored replay attempted provider inference')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from trafficlab.inference.pifpaf_haware_adapter import TrafficLabReplayImporter
from tests.test_haware_profile_validation import profile
fixture = pathlib.Path('../scenes/taipei-cm/trajectory.json')
data = json.loads(fixture.read_text())
frame = next(f for f in data['frames'] if any(len(o.get('kp_cctv', [])) == 24 for o in f['objects']))
data['frames'] = [{'frame_index': frame['frame_index'], 'objects': [next(o for o in frame['objects'] if len(o.get('kp_cctv', [])) == 24)]}]
payload = json.dumps(data).encode()
items = TrafficLabReplayImporter().import_payload(payload, source_repository_relative_path='scenes/taipei-cm/trajectory.json', provider_version='fixture', contract=profile().replay_contract, site='kee-cc', source_sequence='stored')
assert items and items[0].record.observations
"""
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_has_no_root_legacy_imports_or_replay_writes(self):
        forbidden_imports = []
        hard_coded_writes = []
        production = tuple((PROJECT_ROOT / "trafficlab").rglob("*.py")) + tuple(
            (PROJECT_ROOT / "scripts").rglob("*.py")
        )
        write_calls = {"open", "write", "write_bytes", "write_text", "GzipFile"}
        for path in production:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module]
                else:
                    modules = []
                if any(name == "pifpaf" or name.startswith("pifpaf.")
                       or name == "location" or name.startswith("location.")
                       for name in modules):
                    forbidden_imports.append(path.relative_to(PROJECT_ROOT).as_posix())
                if isinstance(node, ast.Call) and node.args:
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                        node.func.id if isinstance(node.func, ast.Name) else ""
                    )
                    target = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
                    if name in write_calls and isinstance(target, str):
                        normalized = target.replace("\\", "/").lstrip("./")
                        if normalized.startswith(("pifpaf/", "location/")):
                            hard_coded_writes.append(path.relative_to(PROJECT_ROOT).as_posix())
        self.assertEqual(forbidden_imports, [])
        self.assertEqual(hard_coded_writes, [])

        record = self.import_fixture("kee-cc")[1][0].record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for legacy_tree in ("pifpaf", "location"):
                destination = root / legacy_tree / "forbidden.replay"
                destination.parent.mkdir(parents=True)
                with self.subTest(legacy_tree=legacy_tree), self.assertRaisesRegex(
                    ReplaySchemaError, "legacy_input_tree_is_read_only",
                ):
                    self.writer.write(
                        destination, (record,), token=self.token, profile=self.profile,
                        scope=self.scope, repository_root=root,
                    )
                self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
