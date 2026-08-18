"""build_scene 邊界案例測試：壞格式軌跡契約、fps 帶入、真基準行為。

原本以 @unittest.expectedFailure 記錄的 5 個缺口已於 2026-07-28 補實作（全部以
unexpected success 現形後轉正），現在是正式回歸測試。
不重複 test_build_scene.py 既有 10 個測試覆蓋的案例。
"""
import math
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_scene


def synth_trajectory_data(extra_meta=None):
    """與 test_build_scene.synth_trajectory 相同的合成軌跡，但直接回傳 dict（不落地）。"""
    frames = []
    for i in range(1, 61):
        objs = [{"tracked_id": 1, "class": "Car", "position_m": [10.0, i * 0.4]}]
        if i >= 20:
            objs.append({"tracked_id": 2, "class": "Two_Wheeler", "position_m": [i * 0.3, 12.0]})
        if i >= 5:
            objs.append({"tracked_id": 9, "class": "Car", "position_m": [20.0, i * 0.2]})
        frames.append({"frame_index": i, "objects": objs})
    data = {"meta": {"px_per_meter": 30.0}, "frames": frames}
    if extra_meta:
        data["meta"].update(extra_meta)
    return data


def build_with(trajectory, **overrides):
    """帶預設參數呼叫 build_scene.build，各測試只覆寫關心的欄位。"""
    kwargs = dict(trajectory=trajectory, code="synth", ground_image="ground.png",
                  px_per_meter=30.0, size_m=[25.0, 25.0],
                  colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=40)
    kwargs.update(overrides)
    return build_scene.build(**kwargs)


class BuildSceneBadFormatTest(unittest.TestCase):
    """A. 壞格式軌跡（隊友輸出格式契約）：一律乾淨的 SceneBuildError，不可是 raw KeyError。"""

    def test_頂層缺frames應拋SceneBuildError(self):
        traj = {"meta": {"px_per_meter": 30.0}}
        with self.assertRaisesRegex(build_scene.SceneBuildError, "frames"):
            build_with(traj)

    def test_frame缺frame_index應拋SceneBuildError(self):
        traj = synth_trajectory_data()
        for frame in traj["frames"]:
            del frame["frame_index"]
        with self.assertRaisesRegex(build_scene.SceneBuildError, "frame_index"):
            build_with(traj)

    def test_frame缺objects應拋SceneBuildError(self):
        traj = synth_trajectory_data()
        for frame in traj["frames"]:
            del frame["objects"]
        with self.assertRaisesRegex(build_scene.SceneBuildError, "objects"):
            build_with(traj)

    def test_object缺position_m應拋指名position_m的SceneBuildError(self):
        """缺 position_m 的 object 仍會被跳過（部分幀缺是正常的），但錯誤訊息必須指名
        position_m——否則全部都缺時會以誤導的「collider track_id 不存在」浮出。"""
        traj = synth_trajectory_data()
        for frame in traj["frames"]:
            for obj in frame["objects"]:
                del obj["position_m"]
        with self.assertRaisesRegex(build_scene.SceneBuildError, "position_m"):
            build_with(traj)

    def test_frames非陣列應拋SceneBuildError(self):
        traj = {"meta": {"px_per_meter": 30.0}, "frames": {"nope": 1}}
        with self.assertRaisesRegex(build_scene.SceneBuildError, "frames"):
            build_with(traj)


class BuildSceneFpsTest(unittest.TestCase):
    """B. fps 帶入：trajectory.meta.fps 應傳導到 scene.json frames.fps。

    實證沒有一支影片是 30（test1=49.98、taipei-cm=23.0），寫死會讓整條時間軸錯。
    """

    def test_meta_fps帶入frames_fps(self):
        for meta_fps, expected in ((25, 25), (60, 60), (23.0, 23), (49.97997, 49.97997)):
            cfg = build_with(synth_trajectory_data(extra_meta={"fps": meta_fps}))
            self.assertEqual(cfg["frames"]["fps"], expected,
                             f"meta.fps={meta_fps} 應帶入 frames.fps")

    def test_meta_fps缺失時回退30(self):
        cfg = build_with(synth_trajectory_data())
        self.assertEqual(cfg["frames"]["fps"], build_scene.DEFAULT_FPS)

    def test_meta_fps無效時回退30(self):
        """0／負數／NaN／Infinity／字串都不可寫進 scene.json——下游會產生 NaN 時間軸
        或時間軸倒流，而且只有 console.warn。"""
        for bad in (0, -5, float("nan"), float("inf"), "30", True, None):
            cfg = build_with(synth_trajectory_data(extra_meta={"fps": bad}))
            self.assertEqual(cfg["frames"]["fps"], build_scene.DEFAULT_FPS,
                             f"meta.fps={bad!r} 應回退 {build_scene.DEFAULT_FPS}")


class BuildSceneClassCasingTest(unittest.TestCase):
    """D. 車種大小寫正規化：haware 管線輸出小寫 `car`，CLASS_DEFAULTS 是大寫鍵。"""

    def test_小寫車種可被接受並正規化(self):
        cfg = build_with(synth_trajectory_data(),
                         colliders=[(1, "car"), (2, "two_wheeler")])
        classes = [v["class"] for v in cfg["vehicles"]]
        self.assertEqual(classes, ["Car", "Two_Wheeler"],
                         "scene.json 內應寫入正規化後的大寫車種（播放器 registry 精確比對）")

    def test_別名與空白大小寫混雜皆可(self):
        for raw, expect in (("CAR", "Car"), (" Car ", "Car"), ("motorcycle", "Two_Wheeler"),
                            ("two-wheeler", "Two_Wheeler"), ("scooter", "Two_Wheeler")):
            self.assertEqual(build_scene.normalize_class(raw), expect)

    def test_真正未知的車種仍被拒(self):
        self.assertIsNone(build_scene.normalize_class("Bicycle"))
        with self.assertRaisesRegex(build_scene.SceneBuildError, "未知車種"):
            build_with(synth_trajectory_data(),
                       colliders=[(1, "Bicycle"), (2, "Two_Wheeler")])


class BuildSceneBaselineTest(unittest.TestCase):
    """C. 真基準測試（要過的）：照原始碼現況釘住既有防護行為。"""

    def test_source_collision等於source_end被拒(self):
        """source_collision 等於 src_end（=60）應被拒（frame mapper 除以零防護）。
        等於 source_start 的案例已由既有 test_build_rejects_collision_at_boundary 覆蓋。"""
        with self.assertRaises(build_scene.SceneBuildError):
            build_with(synth_trajectory_data(), source_collision=60)

    def test_collider不存在時錯誤訊息列出可用track(self):
        """collider track_id 不存在時：現況是 SceneBuildError，且訊息指名缺的 id
        並列出軌跡內可用的 track id（既有測試只斷言型別，這裡釘住訊息內容）。"""
        with self.assertRaisesRegex(build_scene.SceneBuildError,
                                    r"track_id 99 不存在.*\[1, 2, 9\]"):
            build_with(synth_trajectory_data(),
                       colliders=[(99, "Car"), (2, "Two_Wheeler")])


def with_kp_sat(traj, tid, kp_sat):
    """把指定 track 的每個 object 補上 kp_sat（衛星像素座標，24 元素、缺的為 None）。"""
    for frame in traj["frames"]:
        for obj in frame["objects"]:
            if obj["tracked_id"] == tid:
                obj["kp_sat"] = kp_sat
    return traj


def kp(entries, n=24):
    """把 {索引: (x,y)} 展開成 24 元素的 kp_sat 陣列。"""
    out = [None] * n
    for i, xy in entries.items():
        out[i] = list(xy)
    return out


class TrackQualityTest(unittest.TestCase):
    """E. 品質判據：從 kp_sat 自算 spread_m 與 n_wheel_kp。

    上游定位器現在會直接輸出這兩個欄位，但既有的 trajectory.json 產生於此之前——
    kp_sat 本來就在裡面，所以自己算，不必為了拿判據重跑 pifpaf（1.5–2.5 秒/幀）。
    """

    def test_由kp_sat算出展開度與輪點數(self):
        """展開度＝**最大兩兩距離**（不是第一對），所以測資刻意共線讓答案唯一。
        px_per_meter=30 → 相距 300 px 即 10 m。"""
        obj = {"kp_sat": kp({0: (0, 0), 1: (300, 0), 7: (60, 0), 8: (120, 0)})}
        spread, n_wheel = build_scene.kp_quality(obj, 30.0)
        self.assertAlmostEqual(spread, 10.0, places=6)
        self.assertEqual(n_wheel, 2, "索引 7/8 是輪關鍵點")

    def test_展開度取的是最遠的一對而非第一對(self):
        # (300,0) 與 (0,60) 相距 305.94 px，比 (0,0)–(300,0) 的 300 px 更遠
        obj = {"kp_sat": kp({0: (0, 0), 1: (300, 0), 7: (0, 60)})}
        self.assertAlmostEqual(build_scene.kp_quality(obj, 30.0)[0],
                               math.hypot(300, 60) / 30.0, places=6)

    def test_輪點索引正確(self):
        for idx, expect in ((7, 1), (8, 1), (18, 1), (19, 1), (0, 0), (10, 0)):
            obj = {"kp_sat": kp({idx: (0, 0), 2: (10, 0)})}
            self.assertEqual(build_scene.kp_quality(obj, 30.0)[1], expect,
                             f"索引 {idx} 的輪點判定錯誤")

    def test_物件自帶欄位優先於自算(self):
        """上游若已輸出 spread_m/n_wheel_kp 就直接採用（避免重算與定義漂移）。"""
        obj = {"kp_sat": kp({0: (0, 0), 1: (300, 0)}), "spread_m": 3.21, "n_wheel_kp": 4}
        self.assertEqual(build_scene.kp_quality(obj, 30.0), (3.21, 4))

    def test_沒有kp_sat時回傳None(self):
        self.assertEqual(build_scene.kp_quality({}, 30.0), (None, None))

    def test_track清單帶出品質統計(self):
        traj = synth_trajectory_data(extra_meta={"px_per_meter": 30.0})
        # track 1 給乾淨的點（展開 4 m、2 個輪點）、track 2 給外推的（展開 20 m、無輪點）
        with_kp_sat(traj, 1, kp({0: (0, 0), 1: (90, 0), 7: (30, 0), 8: (60, 0)}))
        with_kp_sat(traj, 2, kp({0: (0, 0), 1: (600, 0)}))
        tracks = {t["track_id"]: t for t in build_scene.list_tracks(traj)}
        self.assertAlmostEqual(tracks[1]["spread_med"], 3.0, places=6)
        self.assertEqual(tracks[1]["wheel_med"], 2)
        self.assertAlmostEqual(tracks[2]["spread_med"], 20.0, places=6)
        self.assertEqual(tracks[2]["wheel_med"], 0)

    def test_品質差的collider會發出警告(self):
        """挑到外推的 track 當 collider 時要明確示警——這是目前唯一的人工判斷點。"""
        traj = synth_trajectory_data(extra_meta={"px_per_meter": 30.0})
        with_kp_sat(traj, 1, kp({0: (0, 0), 1: (600, 0)}))       # 展開 20 m，超過門檻
        with_kp_sat(traj, 2, kp({0: (0, 0), 1: (90, 0), 7: (30, 0), 8: (60, 0)}))
        with self.assertWarns(UserWarning) as cm:
            build_with(traj)
        self.assertIn("track 1", str(cm.warning))

    def test_品質好的collider不發警告(self):
        traj = synth_trajectory_data(extra_meta={"px_per_meter": 30.0})
        good = kp({0: (0, 0), 1: (90, 0), 7: (30, 0), 8: (60, 0)})
        with_kp_sat(traj, 1, good)
        with_kp_sat(traj, 2, good)
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            build_with(traj)
            quality_warnings = [x for x in w if "品質" in str(x.message)]
        self.assertEqual(quality_warnings, [])

    def test_沒有kp_sat的軌跡不誤報(self):
        """舊格式或合成軌跡沒有 kp_sat，不該因此發出品質警告。"""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            build_with(synth_trajectory_data())
            self.assertEqual([x for x in w if "品質" in str(x.message)], [])


def fake_png(path, w, h):
    """寫一個只有 IHDR 的最小合法 PNG（png_size 只讀 header，足夠測試用）。"""
    import struct as _s
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _s.pack(">I", 13) + b"IHDR"
                     + _s.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0) + b"\x00\x00\x00\x00")
    return path


class LocationDirTest(unittest.TestCase):
    """F. --location-dir：座標對位自動化，並優先採用去車銳化過的增強版。

    真實影片的 position_m 活在 G-projection 校正參考圖的平面上，所以地面圖只能是
    **那張圖本身或其等比縮放**。增強版（去車＋銳化＋整數倍放大）符合這個條件，
    但 px_per_meter 必須跟著乘上縮放比，否則車會整體偏掉。
    """

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.d = Path(self.tmpdir.name) / "taipei-cm"
        self.d.mkdir()
        self.traj = synth_trajectory_data(extra_meta={"px_per_meter": 27.85})

    def test_只有原圖時用原圖與原ppm(self):
        fake_png(self.d / "sat_taipei-cm.png", 1190, 1258)
        img, ppm, size = build_scene.from_location_dir(self.d, "taipei-cm", self.traj)
        self.assertEqual(img.name, "sat_taipei-cm.png")
        self.assertAlmostEqual(ppm, 27.85, places=6)
        self.assertAlmostEqual(size[0], 1190 / 27.85, places=6)
        self.assertAlmostEqual(size[1], 1258 / 27.85, places=6)

    def test_有增強版時優先採用且ppm按比例放大(self):
        fake_png(self.d / "sat_taipei-cm.png", 1190, 1258)
        fake_png(self.d / "sat_taipei-cm_hd.png", 2380, 2516)      # 精確 2 倍
        img, ppm, size = build_scene.from_location_dir(self.d, "taipei-cm", self.traj)
        self.assertEqual(img.name, "sat_taipei-cm_hd.png")
        self.assertAlmostEqual(ppm, 27.85 * 2, places=6, msg="ppm 必須跟著放大 2 倍")
        # 實際覆蓋的公尺數不變——這是座標沒被破壞的關鍵性質
        self.assertAlmostEqual(size[0], 1190 / 27.85, places=6)
        self.assertAlmostEqual(size[1], 1258 / 27.85, places=6)

    def test_增強版長寬比不符時拒用並退回原圖(self):
        """長寬比一旦改變就無法用單一係數換算 px_per_meter，寧可退回原圖也不要錯位。"""
        fake_png(self.d / "sat_taipei-cm.png", 1190, 1258)
        fake_png(self.d / "sat_taipei-cm_hd.png", 2380, 2000)      # 比例不符
        with self.assertWarns(UserWarning):
            img, ppm, _ = build_scene.from_location_dir(self.d, "taipei-cm", self.traj)
        self.assertEqual(img.name, "sat_taipei-cm.png")
        self.assertAlmostEqual(ppm, 27.85, places=6)

    def test_場景代號與地點代號不同時仍找得到圖(self):
        """同一個路口可以出多個場景包，--code 不必等於地點代號。"""
        fake_png(self.d / "sat_taipei-cm.png", 1190, 1258)
        img, _, _ = build_scene.from_location_dir(self.d, "taipei-cm-crash2", self.traj)
        self.assertEqual(img.name, "sat_taipei-cm.png")

    def test_meta缺px_per_meter時給清楚錯誤(self):
        fake_png(self.d / "sat_taipei-cm.png", 1190, 1258)
        with self.assertRaisesRegex(build_scene.SceneBuildError, "px_per_meter"):
            build_scene.from_location_dir(self.d, "taipei-cm", {"meta": {}, "frames": []})


if __name__ == "__main__":
    unittest.main()
