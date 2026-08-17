"""Focused tests for complete-replay track provenance finalization."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.io.haware_track_provenance import (  # noqa: E402
    FRAME_LOCAL_TRACK_ID,
    INCOMPLETE_TRACK_PROVENANCE,
    INCONSISTENT_TRACK_PROVENANCE,
    NO_TRACK_IDENTITY,
    UNVERIFIED_TRACK_IDENTITY,
    finalize_track_provenance,
)
from trafficlab.motion.haware_accuracy.models import (  # noqa: E402
    TrackKind,
    TrackProvenance,
)
from tests.test_haware_observation_replay import record  # noqa: E402


def claim(
    claimed_id="42",
    *,
    tracker_name="bytetrack",
    tracker_version="1.0",
    source_sequence="sequence-1",
    association_provenance="iou-association-v1",
    observed_frames=("untrusted-a", "untrusted-b"),
):
    return TrackProvenance(
        claimed_id=claimed_id,
        tracker_name=tracker_name,
        tracker_version=tracker_version,
        source_sequence=source_sequence,
        association_provenance=association_provenance,
        observed_frames=observed_frames,
        kind=TrackKind.PSEUDO,
        reason="untrusted_input_classification",
    )


def tracked_record(frame_id, detection_id, track):
    return replace(record(), frame_id=frame_id, detection_id=detection_id, track=track)


class TrackProvenanceFinalizationTest(unittest.TestCase):
    def test_complete_consistent_multiframe_claim_is_real_and_uses_actual_frames(self):
        track = claim(claimed_id="700")
        replay = finalize_track_provenance((
            tracked_record("frame-2", "d2", track),
            tracked_record("frame-1", "d1", track),
        ))

        self.assertEqual(len(replay.real_track_records), 2)
        for value in replay.real_track_records:
            self.assertEqual(value.track.kind, TrackKind.REAL)
            self.assertIsNone(value.track.reason)
            self.assertEqual(value.track.observed_frames, ("frame-1", "frame-2"))
        self.assertEqual(replay.frame_local_diagnostic(diagnostic_name="track-audit").entries, ())

    def test_frame_local_500_identity_remains_pseudo_even_when_repeated(self):
        track = claim(
            claimed_id="500",
            association_provenance="frame-local-detection-index",
        )
        replay = finalize_track_provenance((
            tracked_record("frame-1", "d1", track),
            tracked_record("frame-2", "d2", track),
        ))

        self.assertEqual(replay.real_track_records, ())
        entries = replay.frame_local_diagnostic(diagnostic_name="legacy-display-id-review").entries
        self.assertEqual({entry.reason for entry in entries}, {FRAME_LOCAL_TRACK_ID})
        self.assertTrue(all(entry.record.track.kind is TrackKind.PSEUDO for entry in entries))

    def test_one_actual_frame_is_unverified_despite_claimed_cross_frame_list(self):
        replay = finalize_track_provenance((
            tracked_record("only-frame", "d1", claim()),
        ))
        entry = replay.frame_local_diagnostic(diagnostic_name="single-frame-review").entries[0]
        self.assertEqual(entry.reason, UNVERIFIED_TRACK_IDENTITY)
        self.assertEqual(entry.record.track.observed_frames, ("only-frame",))

    def test_missing_and_inconsistent_provenance_have_stable_reasons(self):
        for field in ("tracker_name", "tracker_version", "source_sequence", "association_provenance"):
            with self.subTest(missing=field):
                incomplete = replace(claim(), **{field: None})
                replay = finalize_track_provenance((
                    tracked_record("frame-1", "d1", incomplete),
                    tracked_record("frame-2", "d2", incomplete),
                ))
                reasons = {
                    entry.reason
                    for entry in replay.frame_local_diagnostic(diagnostic_name="incomplete-review").entries
                }
                self.assertEqual(reasons, {INCOMPLETE_TRACK_PROVENANCE})

        replay = finalize_track_provenance((
            tracked_record("frame-1", "d1", claim(tracker_version="1.0")),
            tracked_record("frame-2", "d2", claim(tracker_version="2.0")),
        ))
        reasons = {
            entry.reason
            for entry in replay.frame_local_diagnostic(diagnostic_name="conflict-review").entries
        }
        self.assertEqual(reasons, {INCONSISTENT_TRACK_PROVENANCE})

    def test_claim_sequence_must_match_record_and_be_consistent(self):
        mismatch = claim(source_sequence="other-sequence")
        replay = finalize_track_provenance((
            tracked_record("frame-1", "d1", mismatch),
            tracked_record("frame-2", "d2", mismatch),
        ))
        entries = replay.frame_local_diagnostic(diagnostic_name="sequence-review").entries
        self.assertEqual({entry.reason for entry in entries}, {INCONSISTENT_TRACK_PROVENANCE})

    def test_pseudo_and_no_track_records_require_named_frame_local_diagnostic(self):
        pseudo = tracked_record("frame-1", "d1", claim())
        no_track = replace(record(), frame_id="frame-2", detection_id="d2", track=None)
        replay = finalize_track_provenance((pseudo, no_track))

        self.assertEqual(replay.real_track_records, ())
        self.assertFalse(hasattr(replay, "records"))
        with self.assertRaisesRegex(ValueError, "frame_local_diagnostic_name_required"):
            replay.frame_local_diagnostic(diagnostic_name=" ")
        report = replay.frame_local_diagnostic(diagnostic_name="frame-local-provenance-audit")
        self.assertEqual(report.diagnostic_name, "frame-local-provenance-audit")
        self.assertEqual(
            {entry.reason for entry in report.entries},
            {NO_TRACK_IDENTITY, UNVERIFIED_TRACK_IDENTITY},
        )

    def test_finalization_is_deterministic_under_complete_replay_permutation(self):
        track = claim()
        left = finalize_track_provenance((
            tracked_record("frame-2", "d2", track),
            tracked_record("frame-1", "d1", track),
        ))
        right = finalize_track_provenance((
            tracked_record("frame-1", "d1", track),
            tracked_record("frame-2", "d2", track),
        ))
        self.assertEqual(left.real_track_records, right.real_track_records)
        self.assertEqual(
            left.frame_local_diagnostic(diagnostic_name="audit"),
            right.frame_local_diagnostic(diagnostic_name="audit"),
        )


if __name__ == "__main__":
    unittest.main()
