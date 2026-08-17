"""Focused downstream authority, gap-segmentation, and export tests."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.filter_and_enrich_output import filter_and_enrich  # noqa: E402
from trafficlab.io.replay_writer import ReplayWriter  # noqa: E402
from trafficlab.motion.localization_authority import (  # noqa: E402
    authoritative_extent,
    collider_footprint,
    diagnostic_visualization_position,
    sanitize_spatial_record_for_export,
)
from trafficlab.trajectory.plotting import TrajectoryPlotter  # noqa: E402
from trafficlab.trajectory.smoothing import smooth_trajectories  # noqa: E402


def accepted(track_id, x, *, real=True, sat_coords=None):
    return {
        "tracked_id": track_id,
        "track": {"kind": "real" if real else "pseudo"},
        "class": "car",
        "status": "accepted",
        "usable": True,
        "authoritative_position_sat_px": [float(x), 20.0],
        "diagnostic_position_sat_px": None,
        "heading_deg": 0.0,
        "heading": 0.0,
        "decisive_gate": "accepted",
        "reason": None,
        "sat_coords": sat_coords if sat_coords is not None else [float(x), 20.0],
        "have_heading": True,
    }


def rejected(track_id, diagnostic_x=900.0):
    return {
        "tracked_id": track_id,
        "track": {"kind": "real"},
        "class": "car",
        "status": "rejected",
        "usable": False,
        "authoritative_position_sat_px": None,
        "diagnostic_position_sat_px": [diagnostic_x, 20.0],
        "heading_deg": 0.0,
        "heading": 0.0,
        "decisive_gate": "spread_rejected",
        "reason": "spread_rejected",
        "sat_coords": [diagnostic_x, 20.0],
        "sat_floor_box": [[diagnostic_x, 20.0]],
        "position_m": [diagnostic_x, 20.0],
        "velocity_mps": [99.0, 0.0],
    }


class DownstreamLocalizationAuthorityTest(unittest.TestCase):
    def test_enrichment_segments_rejected_missing_and_pseudo_tracks(self):
        frames = [
            {"frame_index": 0, "objects": [accepted(1, 0), accepted(2, 0, real=False)]},
            {"frame_index": 1, "objects": [accepted(1, 10), accepted(2, 10, real=False)]},
            {"frame_index": 2, "objects": [rejected(1), accepted(2, 20, real=False)]},
            {"frame_index": 3, "objects": [accepted(1, 30)]},
            {"frame_index": 4, "objects": []},
            {"frame_index": 5, "objects": [accepted(1, 50)]},
        ]
        data = {"meta": {"fps": 1.0}, "frames": frames}
        priors = {"car": {"length": 4.0, "width": 2.0}}

        output = filter_and_enrich(data, [1, 2], 10.0, priors)
        by_frame = {
            frame["frame_index"]: {obj["tracked_id"]: obj for obj in frame["objects"]}
            for frame in output["frames"]
        }
        self.assertIsNone(by_frame[0][1]["velocity_mps"])
        self.assertEqual(by_frame[1][1]["velocity_mps"], [1.0, 0.0])
        self.assertIsNone(by_frame[2][1]["position_m"])
        self.assertIsNone(by_frame[2][1]["collider_sat_floor_box"])
        self.assertIsNone(by_frame[3][1]["velocity_mps"])
        self.assertIsNone(by_frame[5][1]["velocity_mps"])
        self.assertTrue(all(by_frame[i][2]["velocity_mps"] is None for i in (0, 1, 2)))
        self.assertEqual(output["scene_extent_sat_px"], (0.0, 20.0, 50.0, 20.0))
        self.assertEqual(
            output["localization_counts"]["rejected"], {"spread_rejected": 1}
        )
        self.assertEqual(list(output["localization_counts"]), sorted(output["localization_counts"]))

    def test_smoothing_uses_separate_authoritative_real_track_segments(self):
        objects = [
            accepted(1, 0, sat_coords=[700, 20]),
            accepted(1, 100, sat_coords=[700, 20]),
            accepted(1, 0, sat_coords=[700, 20]),
            rejected(1, diagnostic_x=5000),
            accepted(1, 10, sat_coords=[700, 20]),
            accepted(1, 110, sat_coords=[700, 20]),
            accepted(1, 10, sat_coords=[700, 20]),
        ]
        pseudo = [accepted(2, x, real=False) for x in (0, 100, 0)]
        frames = [{"frame_index": i, "objects": [obj]} for i, obj in enumerate(objects)]
        for i, obj in enumerate(pseudo):
            frames[i]["objects"].append(obj)

        output, stats = smooth_trajectories(
            {"frames": frames}, window_length=3, polyorder=1
        )
        track_one = [
            next(obj for obj in frame["objects"] if obj["tracked_id"] == 1)
            for frame in output["frames"]
        ]
        self.assertAlmostEqual(track_one[1]["smoothed_position_sat_px"][0], 100.0 / 3.0)
        self.assertNotIn("smoothed_position_sat_px", track_one[3])
        self.assertAlmostEqual(track_one[5]["smoothed_position_sat_px"][0], 130.0 / 3.0)
        self.assertTrue(all(obj["sat_coords"] == [700, 20] for obj in track_one if obj["status"] == "accepted"))
        self.assertEqual(stats.smoothed_tracks, 2)
        self.assertTrue(all("smoothed_position_sat_px" not in obj for obj in pseudo))

    def test_diagnostics_are_display_only_and_never_change_spatial_adapters(self):
        good = accepted(7, 10, sat_coords=[999, 999])
        bad = rejected(7, diagnostic_x=2000)
        self.assertEqual(authoritative_extent([good, bad]), (10.0, 20.0, 10.0, 20.0))
        self.assertEqual(diagnostic_visualization_position(bad), (2000.0, 20.0))
        self.assertIsNone(collider_footprint(bad, length_m=4, width_m=2, px_per_meter=10))
        footprint = collider_footprint(good, length_m=4, width_m=2, px_per_meter=10)
        self.assertEqual(footprint[0], [30.0, 30.0])

        exported = sanitize_spatial_record_for_export(bad)
        self.assertIsNone(exported["sat_coords"])
        self.assertIsNone(exported["sat_floor_box"])
        self.assertIsNone(exported["position_m"])
        self.assertIsNone(exported["velocity_mps"])
        self.assertEqual(bad["sat_coords"], [2000, 20.0])

        plotter = object.__new__(TrajectoryPlotter)
        plotter.frames = [{"objects": [good, bad]}]
        self.assertEqual(plotter.extract_trajectories(min_points=1), {7: [(10.0, 20.0)]})
        self.assertEqual(
            plotter.extract_trajectories(min_points=1, include_diagnostics=True),
            {7: [(10.0, 20.0), (2000.0, 20.0)]},
        )

    def test_replay_writer_sanitizes_new_records_but_preserves_legacy_schema(self):
        authority_record = rejected(1)
        legacy_record = {"tracked_id": 2, "status": "ok", "sat_coords": [3.0, 4.0]}
        payload = {"frames": [{"frame_index": 0, "objects": [authority_record, legacy_record]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json.gz"
            ReplayWriter.write(path, payload)
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                written = json.load(stream)
        first, second = written["frames"][0]["objects"]
        self.assertIsNone(first["sat_coords"])
        self.assertIsNone(first["sat_floor_box"])
        self.assertEqual(second, legacy_record)
        self.assertEqual(authority_record["sat_coords"], [900.0, 20.0])


class DownstreamAuthorityIntegrationTest(unittest.TestCase):
    """Exercise one authority fixture through every spatial consumer boundary."""

    @staticmethod
    def _mixed_output(diagnostic_x):
        frames = [
            {"frame_index": 0, "objects": [accepted(1, 0), accepted(2, 100)]},
            {"frame_index": 1, "objects": [accepted(1, 10), accepted(2, 110)]},
            {
                "frame_index": 2,
                "objects": [
                    rejected(1, diagnostic_x=diagnostic_x),
                    accepted(2, 120),
                    rejected(3, diagnostic_x=diagnostic_x + 100),
                ],
            },
            {"frame_index": 3, "objects": [accepted(1, 30), accepted(2, 130)]},
            {"frame_index": 4, "objects": [accepted(2, 140)]},
            {"frame_index": 5, "objects": [accepted(1, 50), accepted(2, 150)]},
        ]
        return filter_and_enrich(
            {"meta": {"fps": 1.0}, "frames": frames},
            [1, 2, 3],
            10.0,
            {"car": {"length": 4.0, "width": 2.0}},
        )

    @staticmethod
    def _load_scene_builder():
        import importlib.util

        path = Path(__file__).resolve().parents[2] / "tools" / "build_scene.py"
        spec = importlib.util.spec_from_file_location("authority_test_build_scene", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _spatial_projection(output):
        fields = (
            "sat_coords",
            "position_m",
            "velocity_mps",
            "collider_sat_floor_box",
            "smoothed_position_sat_px",
            "postprocessed_position_sat_px",
        )
        return [
            (
                frame["frame_index"],
                obj["tracked_id"],
                tuple((field, obj.get(field)) for field in fields),
            )
            for frame in output["frames"]
            for obj in frame["objects"]
        ]

    def test_mixed_fixture_keeps_diagnostics_out_of_scene_collider_and_export(self):
        first = self._mixed_output(900.0)
        mutated = self._mixed_output(9000.0)
        by_frame = {
            frame["frame_index"]: {obj["tracked_id"]: obj for obj in frame["objects"]}
            for frame in first["frames"]
        }

        self.assertEqual(by_frame[1][1]["velocity_mps"], [1.0, 0.0])
        self.assertIsNone(by_frame[2][1]["sat_coords"])
        self.assertIsNone(by_frame[2][1]["position_m"])
        self.assertIsNone(by_frame[2][1]["velocity_mps"])
        self.assertIsNone(by_frame[2][1]["sat_floor_box"])
        self.assertIsNone(by_frame[2][1]["collider_sat_floor_box"])
        self.assertIsNone(by_frame[3][1]["velocity_mps"])
        self.assertIsNone(by_frame[5][1]["velocity_mps"])
        self.assertEqual(first["scene_extent_sat_px"], (0.0, 20.0, 150.0, 20.0))
        self.assertEqual(first["localization_counts"]["rejected"], {"spread_rejected": 2})
        self.assertEqual(self._spatial_projection(first), self._spatial_projection(mutated))

        scene_builder = self._load_scene_builder()
        tracks = {row["track_id"]: row for row in scene_builder.list_tracks(first)}
        self.assertEqual(tracks[1]["frames_present"], 4)
        self.assertEqual(tracks[2]["frames_present"], 6)
        self.assertNotIn(3, tracks)
        scene = scene_builder.build(
            trajectory=first,
            code="authority-integration",
            ground_image="ground.png",
            px_per_meter=10.0,
            size_m=[20.0, 20.0],
            colliders=[(1, "car"), (2, "car")],
            source_collision=2,
        )
        self.assertEqual([vehicle["track_id"] for vehicle in scene["vehicles"]], [1, 2])
        self.assertEqual(
            scene,
            scene_builder.build(
                trajectory=mutated,
                code="authority-integration",
                ground_image="ground.png",
                px_per_meter=10.0,
                size_m=[20.0, 20.0],
                colliders=[(1, "car"), (2, "car")],
                source_collision=2,
            ),
        )

        plotter = object.__new__(TrajectoryPlotter)
        plotter.frames = first["frames"]
        spatial = plotter.extract_trajectories(min_points=1)
        diagnostic = plotter.extract_trajectories(min_points=1, include_diagnostics=True)
        self.assertNotIn((900.0, 20.0), spatial[1])
        self.assertIn((900.0, 20.0), diagnostic[1])
        self.assertNotIn(3, spatial)
        self.assertEqual(diagnostic[3], [(1000.0, 20.0)])

        with tempfile.TemporaryDirectory() as directory:
            plain_path = Path(directory) / "enriched.json"
            from scripts.filter_and_enrich_output import write_json

            write_json(plain_path, first)
            plain = json.loads(plain_path.read_text(encoding="utf-8"))
            gzip_path = Path(directory) / "replay.json.gz"
            ReplayWriter.write(gzip_path, first)
            with gzip.open(gzip_path, "rt", encoding="utf-8") as stream:
                replay = json.load(stream)

        for exported in (plain, replay):
            rejected_export = exported["frames"][2]["objects"][0]
            self.assertEqual(rejected_export["diagnostic_position_sat_px"], [900.0, 20.0])
            self.assertIsNone(rejected_export["sat_coords"])
            self.assertIsNone(rejected_export["sat_floor_box"])
            self.assertIsNone(rejected_export["position_m"])
            self.assertIsNone(rejected_export["velocity_mps"])
            self.assertIsNone(rejected_export["collider_sat_floor_box"])

    def test_velocity_and_postprocess_interpolation_start_new_segments_after_gaps(self):
        from types import SimpleNamespace
        import postprocess as trajectory_postprocess

        frames = []
        positions = {0: 0, 1: 100, 2: 0, 4: 10, 5: 110, 6: 10, 8: 20, 9: 120, 10: 20}
        for frame_index in range(11):
            if frame_index == 3:
                obj = rejected(1, diagnostic_x=5000)
                obj["class"] = "motorcycle"
                objects = [obj]
            elif frame_index == 7:
                objects = []
            else:
                obj = accepted(1, positions[frame_index])
                obj["class"] = "motorcycle"
                objects = [obj]
            frames.append({"frame_index": frame_index, "objects": objects})

        enriched = filter_and_enrich(
            {"meta": {"fps": 1.0}, "frames": frames},
            [1],
            10.0,
            {"motorcycle": {"length": 2.0, "width": 0.7}},
        )
        by_frame = {frame["frame_index"]: frame["objects"] for frame in enriched["frames"]}
        self.assertIsNone(by_frame[3][0]["sat_coords"])
        self.assertIsNone(by_frame[4][0]["velocity_mps"])
        self.assertIsNone(by_frame[8][0]["velocity_mps"])

        args = SimpleNamespace(
            target_class=["motorcycle"],
            direction_correction=False,
            direction_centerline_mode="global_pca",
            direction_window_size=5,
            direction_min_points=3,
            direction_max_angle_deg=30.0,
            direction_max_lateral_offset_px=20.0,
            direction_lateral_retention=1.0,
            direction_preserve_longitudinal_progress=True,
            direction_max_correction_px=100.0,
            min_track_points=3,
            sharp_turn_angle_deg=90.0,
            min_step_px=1.0,
            min_lateral_deviation_px=1.0,
            bridge_gap=0,
            max_bad_segment_len=1,
            dry_run=False,
            visual_bspline=False,
            visual_bspline_min_points=3,
            visual_bspline_degree=2,
            visual_bspline_smooth_px=0.0,
            visual_bspline_preserve_endpoints=True,
        )
        summary = trajectory_postprocess.postprocess(enriched, args)

        self.assertEqual(set(summary["per_track"]), {"1:0", "1:1", "1:2"})
        self.assertEqual(summary["tracks_seen"], 3)
        self.assertEqual(summary["corrected_points"], 3)
        self.assertEqual(by_frame[1][0]["postprocessed_position_sat_px"], [0.0, 20.0])
        self.assertEqual(by_frame[5][0]["postprocessed_position_sat_px"], [10.0, 20.0])
        self.assertEqual(by_frame[9][0]["postprocessed_position_sat_px"], [20.0, 20.0])
        self.assertNotIn("postprocessed_position_sat_px", by_frame[3][0])
        self.assertEqual(by_frame[3][0]["diagnostic_position_sat_px"], [5000, 20.0])


if __name__ == "__main__":
    unittest.main()


class RealLegacyReplayEnrichmentTest(unittest.TestCase):
    """The production path is `eval_haware_replay.py` -> filter_and_enrich -> build_scene.

    Those records carry only the legacy schema (sat_coords/heading/status), so
    before the frozen `legacy-localize-v1` default they read as "missing
    localization" and every scene bundle silently lost its geometry.
    """

    @staticmethod
    def _legacy_object(x, status):
        return {
            "id": 1,
            "tracked_id": 1,
            "track": {"kind": "real"},
            "class": "car",
            "confidence": 0.9,
            "sat_coords": [float(x), 20.0],
            "have_heading": True,
            "heading": 90.0,
            "n_keypoints": 12,
            "status": status,
            "method": "geometric",
            "spread_m": 1.2,
            "n_wheel_kp": 2,
        }

    def _enriched(self):
        data = {
            "meta": {"fps": 1.0},
            "frames": [
                {"frame_index": index, "objects": [self._legacy_object(index * 10, status)]}
                for index, status in enumerate(("ok", "ok", "ok", "extrapolated"))
            ],
        }
        return filter_and_enrich(data, [1], 10.0, {"car": {"length": 4.0, "width": 2.0}})

    def test_legacy_ok_records_recover_position_and_velocity(self):
        frames = self._enriched()["frames"]
        positions = [frames[i]["objects"][0]["position_m"] for i in range(3)]
        self.assertEqual(positions, [[0.0, 2.0], [1.0, 2.0], [2.0, 2.0]])
        self.assertIsNotNone(frames[1]["objects"][0]["velocity_mps"])
        self.assertIsNotNone(frames[0]["objects"][0]["collider_sat_floor_box"])

    def test_legacy_extrapolated_record_is_stripped_of_its_coordinate(self):
        extrapolated = self._enriched()["frames"][3]["objects"][0]
        self.assertIsNone(extrapolated["position_m"])
        self.assertIsNone(extrapolated["sat_coords"])

    def test_localization_counts_report_the_frozen_reasons(self):
        counts = self._enriched()["localization_counts"]
        self.assertEqual(counts.get("accepted", {}).get("legacy_status_policy"), 3)
        self.assertEqual(counts.get("rejected", {}).get("spread_rejected"), 1)
        self.assertNotIn("missing", counts)
