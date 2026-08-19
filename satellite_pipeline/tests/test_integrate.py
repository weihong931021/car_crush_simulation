"""最終整合（④）：推論 → 挑當事車 → 標碰撞幀 → 場景包 → Three.js。

這一段是把 trafficlab 既有的三支腳本串起來，不重寫邏輯：

    run_inference.py  →  <video>.json.gz（全部 track）
    filter_and_enrich_output.py --ids <當事車>  →  trajectory.json
    tools/build_scene.py --collider ...  →  scenes/<code>/

釘住的是「串接的契約」而不是那三支的內部行為：
1. 挑車的品質判據要**重用 build_scene 的**（門檻漂移會讓兩邊講出不同答案）
2. 推論 config 的權重必須真的存在——repo 內 7 組 config 全部指向不存在的檔案，
   直接跑必爆，所以要自帶一份
3. 指令組裝（argv）要正確，且路徑一律用絕對路徑（三支腳本各自的 cwd 不同）
"""
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _raw_output(objects_per_frame):
    """組一份最小的推論輸出（frames[].objects[]，帶 sat_coords / kp_sat）。"""
    return {
        "mp4_path": "clip.mp4",
        "location_code": "loc",
        "meta": {"resolution": [1920, 1080], "fps": 30.0, "px_per_meter": 29.0},
        "frames": [{"frame_index": i, "objects": objs}
                   for i, objs in enumerate(objects_per_frame)],
    }


def _obj(tid, cls="car", sat=(100.0, 200.0), kp=None):
    o = {"tracked_id": tid, "class": cls, "sat_coords": list(sat)}
    if kp is not None:
        o["kp_sat"] = kp
    return o


class TrackCandidatesTest(unittest.TestCase):

    def test_依tracked_id彙整出現幀數與首末幀(self):
        import integrate
        raw = _raw_output([
            [_obj(3), _obj(7)],
            [_obj(3)],
            [_obj(3), _obj(7)],
        ])
        rows = {r["track_id"]: r for r in integrate.list_track_candidates(raw)}
        self.assertEqual(rows[3]["frames_present"], 3)
        self.assertEqual((rows[3]["first"], rows[3]["last"]), (0, 2))
        self.assertEqual(rows[7]["frames_present"], 2)
        self.assertEqual((rows[7]["first"], rows[7]["last"]), (0, 2))

    def test_沒有位置的物件不列入(self):
        """sat_coords 是位置的唯一來源；沒有它的 track 根本不能當當事車。"""
        import integrate
        raw = _raw_output([[{"tracked_id": 9, "class": "car"}]])
        self.assertEqual(integrate.list_track_candidates(raw), [])

    def test_品質判據重用build_scene的門檻(self):
        """輪關鍵點 index 與 spread/wheel 門檻都從 build_scene 來，避免兩邊各講一套。"""
        import integrate
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
        import build_scene
        self.assertIs(integrate.kp_quality, build_scene.kp_quality)
        self.assertEqual(integrate.QUALITY_MAX_SPREAD_M, build_scene.QUALITY_MAX_SPREAD_M)
        self.assertEqual(integrate.QUALITY_MIN_WHEEL_KP, build_scene.QUALITY_MIN_WHEEL_KP)

    def test_有輪關鍵點的track標為可用(self):
        import integrate
        # 4 個輪點 + 緊湊分佈（29 px/m 下相距數十像素＝數公尺內）
        kp = [None] * 20
        for i, idx in enumerate((7, 8, 18, 19)):
            kp[idx] = [100.0 + i * 20, 200.0]
        raw = _raw_output([[_obj(3, kp=kp)], [_obj(3, kp=kp)]])
        row = integrate.list_track_candidates(raw)[0]
        self.assertGreaterEqual(row["wheel_med"], integrate.QUALITY_MIN_WHEEL_KP)
        self.assertLessEqual(row["spread_med"], integrate.QUALITY_MAX_SPREAD_M)
        self.assertEqual(row["pass_rate"], 1.0)
        self.assertTrue(row["ok"])

    def test_沒有輪關鍵點的track標為不可用(self):
        """實證：0 個輪點的 track heading 中位誤差約 98°、>50% 災難率。"""
        import integrate
        raw = _raw_output([[_obj(1, kp=[None] * 20)], [_obj(1, kp=[None] * 20)]])
        row = integrate.list_track_candidates(raw)[0]
        self.assertEqual(row["wheel_med"], 0)
        self.assertFalse(row["ok"])

    def test_依出現幀數排序(self):
        import integrate
        raw = _raw_output([[_obj(1)], [_obj(1), _obj(2)], [_obj(1), _obj(2), _obj(3)]])
        self.assertEqual([r["track_id"] for r in integrate.list_track_candidates(raw)],
                         [1, 2, 3])


class InferenceConfigTest(unittest.TestCase):

    def test_產出的config權重必須真的存在(self):
        """repo 內 7 組 config 全部指向不存在的權重，直接跑必爆——所以自帶一份。"""
        import integrate
        with tempfile.TemporaryDirectory() as d:
            weights = Path(d) / "model.pt"
            weights.write_bytes(b"x")
            base = Path(d) / "base.yaml"
            base.write_text("configs:\n  a:\n    model:\n      weights: ./missing.pt\n"
                            "      device: mps\n    frames:\n      fps: 30\n")
            out = integrate.make_inference_config(base, weights, Path(d) / "web.yaml")
            import yaml
            cfg = yaml.safe_load(out.read_text())
            name, body = next(iter(cfg["configs"].items()))
            weights_exists = Path(body["model"]["weights"]).exists()
        self.assertTrue(weights_exists)
        self.assertEqual(body["model"]["device"], "mps")      # 其餘設定原樣保留
        self.assertEqual(body["frames"]["fps"], 30)

    def test_找不到任何權重要明確報錯(self):
        import integrate
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                integrate.find_weights(Path(d))


class CommandTest(unittest.TestCase):

    def test_推論指令帶上自帶config與絕對路徑(self):
        import integrate
        cmd = integrate.inference_cmd(Path("/py"), Path("/cfg.yaml"), "loc", Path("/v.mp4"),
                                      Path("/out"))
        self.assertEqual(cmd[0], "/py")
        self.assertIn("--config-path", cmd)
        self.assertIn("/cfg.yaml", cmd)
        self.assertIn("--location", cmd)
        self.assertIn("loc", cmd)
        self.assertTrue(all(not str(c).startswith("./") for c in cmd))

    def test_enrich指令帶ids與g_projection(self):
        import integrate
        cmd = integrate.enrich_cmd(Path("/py"), Path("/in.json.gz"), Path("/out.json"),
                                   [3, 7], Path("/G.json"))
        self.assertIn("--ids", cmd)
        self.assertIn("3", cmd)
        self.assertIn("7", cmd)
        self.assertIn("--g-projection", cmd)
        self.assertLess(cmd.index("/in.json.gz"), cmd.index("/out.json"))   # 位置參數順序

    def test_build_scene指令帶collider與碰撞幀(self):
        import integrate
        cmd = integrate.build_scene_cmd(
            Path("/py"), "loc", Path("/t.json"), Path("/locdir"),
            [{"track_id": 3, "cls": "Car"}, {"track_id": 7, "cls": "Two_Wheeler"}], 128)
        self.assertIn("3:Car", cmd)
        self.assertIn("7:Two_Wheeler", cmd)
        self.assertIn("--source-collision", cmd)
        self.assertIn("128", cmd)
        self.assertIn("--location-dir", cmd)

    def test_必須剛好兩台當事車(self):
        import integrate
        for bad in ([], [{"track_id": 3, "cls": "Car"}]):
            with self.subTest(n=len(bad)), self.assertRaises(ValueError):
                integrate.build_scene_cmd(Path("/py"), "loc", Path("/t.json"),
                                          Path("/locdir"), bad, 1)


class RawOutputLocateTest(unittest.TestCase):

    def test_找得到推論產出的json_gz(self):
        import integrate
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "model-m_tracker-t" / "web" / "loc"
            out.mkdir(parents=True)
            target = out / "clip.json.gz"
            with gzip.open(target, "wt") as f:
                json.dump({"frames": []}, f)
            self.assertEqual(integrate.find_raw_output(Path(d), "loc", "clip"), target)

    def test_找不到時回None(self):
        import integrate
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(integrate.find_raw_output(Path(d), "loc", "clip"))


if __name__ == "__main__":
    unittest.main()
