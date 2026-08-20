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

    def test_validate_catches_degenerate_frames(self):
        cfg = build_scene.build(
            trajectory=json.loads(self.traj.read_text()), code="synth",
            ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
            colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=40)
        cfg["frames"]["source_collision"] = cfg["frames"]["source_start"]
        errs = build_scene.validate_scene(cfg)
        self.assertTrue(any("source" in e for e in errs), errs)

    def test_build_rejects_collision_at_boundary(self):
        traj = json.loads(self.traj.read_text())
        with self.assertRaises(build_scene.SceneBuildError):
            build_scene.build(trajectory=traj, code="synth", ground_image="ground.png",
                              px_per_meter=30.0, size_m=[25.0, 25.0],
                              colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=1)

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

    def test_vehicle_has_real_dimensions(self):
        cfg = build_scene.build(
            trajectory=json.loads(self.traj.read_text()), code="synth",
            ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
            colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=40)
        car, moto = cfg["vehicles"]
        self.assertAlmostEqual(car["length_m"], 4.69)
        self.assertAlmostEqual(car["width_m"], 1.85)
        self.assertAlmostEqual(moto["length_m"], 1.85)
        self.assertAlmostEqual(moto["width_m"], 0.70)

    def test_validate_requires_width(self):
        cfg = build_scene.build(
            trajectory=json.loads(self.traj.read_text()), code="synth",
            ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
            colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=40)
        del cfg["vehicles"][0]["width_m"]
        self.assertTrue(any("width_m" in e for e in build_scene.validate_scene(cfg)))

    def _fake_png(self, path, w, h):
        """寫一張只有 IHDR 的假 PNG——pick_sat 只讀尺寸，不需要真影像資料。"""
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00"
        path.write_bytes(sig + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00\x00\x00\x00")

    def _sat_dir(self, size_m=25.0):
        d = self.tmp / "sat_output"
        d.mkdir(exist_ok=True)
        (d / "meta.json").write_text(json.dumps({"px_per_meter": 29.113, "size_m": size_m}))
        return d

    def test_pick_sat_recomputes_px(self):
        """pick_sat 應根據實際 PNG 寬度重新計算 px_per_meter。"""
        sat_dir = self._sat_dir()
        self._fake_png(sat_dir / "sat_clean.png", 1000, 1000)

        img_path, returned_meta, px_per_meter = build_scene.pick_sat(sat_dir)
        # 應基於 PNG 寬度重算：1000 / 25.0 == 40.0
        self.assertAlmostEqual(px_per_meter, 40.0, places=5)
        self.assertEqual(str(img_path), str(sat_dir / "sat_clean.png"))

    def test_pick_sat_在合成軌跡路徑上以畫質優先挑生圖版(self):
        """`--sat-dir` 這條路上 genai 優先是**對的**，這個測試存在是為了擋住「好心的修正」。

        2026-08-18 我把它改成 clean 優先，理由是「genai 有 0.20 m 位移、地面圖承載座標」。
        那個理由套錯了 code path：`pick_sat()` 只有 `--sat-dir` 呼叫，而 --sat-dir 只用於
        **在衛星座標系合成的軌跡**——position_m 是直接以公尺編出來的名目座標，不是從這張圖
        量出來的，所以重畫位移不影響任何結論。真實影片走 `from_location_dir()`，genai
        從來就不在那條路上。

        改壞的實測後果：tainan_yongkang 的 sat_clean 帶 38 個去車 inpaint 塗抹（多為斑馬線
        誤報），渲染出來路口糊成一片、Google 浮水印跑出來；另外 5 個地點沒有 sat_clean，
        會靜默掉到 sat_raw——車還留在路面上。
        """
        sat_dir = self._sat_dir()
        self._fake_png(sat_dir / "sat_genai.png", 1000, 1000)
        self._fake_png(sat_dir / "sat_clean.png", 1456, 1456)
        self._fake_png(sat_dir / "sat_raw.png", 728, 728)

        img_path, _, px_per_meter = build_scene.pick_sat(sat_dir)
        self.assertEqual(img_path.name, "sat_genai.png")
        self.assertAlmostEqual(px_per_meter, 1000 / 25.0, places=5)

    def test_pick_sat_沒有生圖版時退回_clean(self):
        sat_dir = self._sat_dir()
        self._fake_png(sat_dir / "sat_clean.png", 1456, 1456)
        self._fake_png(sat_dir / "sat_raw.png", 728, 728)

        img_path, _, _ = build_scene.pick_sat(sat_dir)
        self.assertEqual(img_path.name, "sat_clean.png")

    def test_pick_sat_只剩_raw_時仍可用(self):
        """repo 內確實有這種地點（tainan_yonkang、webtest_claude2 只有 raw）。"""
        sat_dir = self._sat_dir()
        self._fake_png(sat_dir / "sat_raw.png", 728, 728)

        img_path, _, _ = build_scene.pick_sat(sat_dir)
        self.assertEqual(img_path.name, "sat_raw.png")



class PositionBoundsTest(unittest.TestCase):
    """位置出界檢查——目前唯一能分辨「標定標好了」與「標壞了但跑完了」的東西。

    2026-08-19 稽核實測：用一份捏造的 G_projection 跑完整條鏈，331 個位置點有 276 個
    （83%）落在地面圖之外、143 m 的路徑塞進 37.5×26 m 的平面，而 build_scene 照樣產包、
    播放器照樣回報 collided=true，全程零示警。

    門檻由實測資料訂：既有的 scenes/tainan_yongkang 有 14/532（2.6%）點在圖外（合成軌跡
    尾端超出，無害），所以少量出界只警告；大量出界（>20%）幾乎只有一個原因——標定壞了。
    """

    def _traj(self, pts_by_track, size_m=(25.0, 25.0)):
        frames = []
        n = max(len(v) for v in pts_by_track.values())
        for i in range(n):
            objs = []
            for tid, pts in pts_by_track.items():
                if i < len(pts):
                    objs.append({"tracked_id": tid, "class": "car", "position_m": list(pts[i])})
            frames.append({"frame_index": i, "objects": objs})
        return {"meta": {"fps": 30}, "frames": frames}

    def test_全部在界內時沒有問題(self):
        traj = self._traj({1: [(5.0, 5.0), (10.0, 10.0), (20.0, 20.0)]})
        report = build_scene.check_positions_in_bounds(traj, [25.0, 25.0], [(1, "Car")])
        self.assertEqual(report["out_of_bounds"], {})
        self.assertEqual(report["severity"], "ok")

    def test_少量出界只警告不擋(self):
        """合成軌跡尾端超出是既有現象（tainan_yongkang 2.6%），不該擋住產包。"""
        pts = [(5.0, 5.0)] * 39 + [(30.0, 5.0)]      # 40 點中 1 點出界 = 2.5%
        report = build_scene.check_positions_in_bounds(self._traj({1: pts}), [25.0, 25.0], [(1, "Car")])
        self.assertEqual(report["severity"], "warn")
        self.assertAlmostEqual(report["out_of_bounds"][1]["frac"], 0.025, places=3)

    def test_大量出界要判定為標定壞掉(self):
        pts = [(100.0, 100.0)] * 8 + [(5.0, 5.0)] * 2   # 80% 出界
        report = build_scene.check_positions_in_bounds(self._traj({1: pts}), [25.0, 25.0], [(1, "Car")])
        self.assertEqual(report["severity"], "error")
        self.assertIn(1, report["out_of_bounds"])

    def test_報告要帶實際範圍讓人看出錯多遠(self):
        pts = [(-12.6, 5.0), (0.3, 5.0)]
        report = build_scene.check_positions_in_bounds(self._traj({1: pts}), [25.0, 25.0], [(1, "Car")])
        rng = report["out_of_bounds"][1]
        self.assertAlmostEqual(rng["x_range"][0], -12.6, places=2)
        self.assertAlmostEqual(rng["x_range"][1], 0.3, places=2)
        self.assertEqual(rng["bounds"], [25.0, 25.0])

    def test_只看_collider_不看路人車(self):
        """extras 出界不影響碰撞結論，不該因此擋下整包。"""
        traj = self._traj({1: [(5.0, 5.0)] * 10, 9: [(999.0, 999.0)] * 10})
        report = build_scene.check_positions_in_bounds(traj, [25.0, 25.0], [(1, "Car")])
        self.assertEqual(report["severity"], "ok")

    def test_build_在大量出界時直接報錯(self):
        pts = [(500.0, 500.0)] * 10
        traj = self._traj({1: pts, 2: pts})
        with self.assertRaises(build_scene.SceneBuildError) as cm:
            build_scene.build(traj, code="x", ground_image="g.png", px_per_meter=30.0,
                              size_m=[25.0, 25.0], colliders=[(1, "Car"), (2, "Two_Wheeler")],
                              source_collision=5)
        self.assertIn("出界", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
