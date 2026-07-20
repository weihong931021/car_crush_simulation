import json, tempfile, unittest, struct
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_scene


def synth_trajectory(path):
    frames = []
    for i in range(1, 61):
        objs = [{"tracked_id": 1, "class": "Car", "position_m": [10.0, i * 0.4]}]
        if i >= 20:
            objs.append({"tracked_id": 2, "class": "Two_Wheeler", "position_m": [i * 0.3, 12.0]})
        if i >= 5:
            objs.append({"tracked_id": 9, "class": "Car", "position_m": [20.0, i * 0.2]})
        frames.append({"frame_index": i, "objects": objs})
    data = {"meta": {"px_per_meter": 30.0}, "frames": frames}
    path.write_text(json.dumps(data))
    return data


class BuildSceneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.traj = self.tmp / "traj.json"
        synth_trajectory(self.traj)

    def test_list_tracks(self):
        tracks = build_scene.list_tracks(json.loads(self.traj.read_text()))
        self.assertEqual({t["track_id"] for t in tracks}, {1, 2, 9})
        t1 = next(t for t in tracks if t["track_id"] == 1)
        self.assertEqual(t1["cls"], "Car")
        self.assertEqual(t1["frames_present"], 60)

    def test_build_scene_dict(self):
        cfg = build_scene.build(
            trajectory=json.loads(self.traj.read_text()), code="synth",
            ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
            colliders=[(1, "Car"), (2, "Two_Wheeler")],
            source_collision=40, anim=(1, 32, 89), name=None)
        self.assertEqual(cfg["schema_version"], 1)
        self.assertEqual(cfg["origin_offset_m"], [12.5, 12.5])
        f = cfg["frames"]
        self.assertEqual((f["source_start"], f["source_collision"], f["source_end"]), (1, 40, 60))
        self.assertEqual((f["anim_start"], f["anim_collision"], f["anim_end"]), (1, 32, 89))
        car = cfg["vehicles"][0]
        self.assertEqual((car["track_id"], car["model"], car["mass_kg"]), (1, "car.glb", 1500))
        self.assertEqual(cfg["vehicles"][1]["mass_kg"], 200)

    def test_validate_catches_missing(self):
        cfg = build_scene.build(
            trajectory=json.loads(self.traj.read_text()), code="synth",
            ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
            colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=40)
        self.assertEqual(build_scene.validate_scene(cfg), [])
        del cfg["ground"]
        cfg["vehicles"][0]["role"] = "extra"
        errs = build_scene.validate_scene(cfg)
        self.assertTrue(any("ground" in e for e in errs))
        self.assertTrue(any("collider" in e for e in errs))

    def test_unknown_collider_id_raises(self):
        with self.assertRaises(build_scene.SceneBuildError):
            build_scene.build(
                trajectory=json.loads(self.traj.read_text()), code="synth",
                ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
                colliders=[(99, "Car"), (2, "Two_Wheeler")], source_collision=40)

    def test_png_size(self):
        """讀 PNG 寬高：正確解析 IHDR、非 PNG 應拋例外。"""
        # 建最小合法 PNG：簽名(8) + IHDR chunk(13 data + 12 header/CRC)
        png_path = self.tmp / "test.png"
        png_signature = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">II", 1024, 768) + b"\x08\x02\x00\x00\x00"
        ihdr_chunk_len = struct.pack(">I", 13)
        crc = b"\x00\x00\x00\x00"  # 隨意 CRC（測試只驗 header）
        png_bytes = png_signature + ihdr_chunk_len + b"IHDR" + ihdr_data + crc
        png_path.write_bytes(png_bytes)

        w, h = build_scene.png_size(png_path)
        self.assertEqual((w, h), (1024, 768))

        # 非 PNG 應拋 SceneBuildError
        not_png = self.tmp / "not.png"
        not_png.write_bytes(b"fake data")
        with self.assertRaises(build_scene.SceneBuildError):
            build_scene.png_size(not_png)

    def test_pick_sat_recomputes_px(self):
        """pick_sat 應根據實際 PNG 寬度重新計算 px_per_meter。"""
        sat_dir = self.tmp / "sat_output"
        sat_dir.mkdir()

        # meta.json：原始解析度描述
        meta = {"px_per_meter": 29.113, "size_m": 25.0}
        (sat_dir / "meta.json").write_text(json.dumps(meta))

        # sat_genai.png：1000×1000（與 meta 的原始 px_per_meter 不匹配）
        png_signature = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">II", 1000, 1000) + b"\x08\x02\x00\x00\x00"
        ihdr_chunk_len = struct.pack(">I", 13)
        crc = b"\x00\x00\x00\x00"
        png_bytes = png_signature + ihdr_chunk_len + b"IHDR" + ihdr_data + crc
        (sat_dir / "sat_genai.png").write_bytes(png_bytes)

        img_path, returned_meta, px_per_meter = build_scene.pick_sat(sat_dir)
        # 應基於 PNG 寬度重算：1000 / 25.0 == 40.0
        self.assertAlmostEqual(px_per_meter, 40.0, places=5)
        self.assertEqual(str(img_path), str(sat_dir / "sat_genai.png"))


if __name__ == "__main__":
    unittest.main()
