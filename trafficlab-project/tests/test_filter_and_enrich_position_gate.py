"""缺 position_m 不可以靜默——它會偽裝成「collider 不存在」。

背景（2026-08-18 驗證）：`scripts/run_inference.py` 走的是 YOLO bbox 路徑，
每筆物件寫出 `sat_coords` 但**沒有 `status` 欄位**（`trafficlab/inference/pipeline.py`
的 obj_data）。而 `localization_authority` 的 legacy 政策是
`accepted_statuses=("ok",)`，沒有 status ＝ unknown ＝ 證據不足 ＝ 拒絕。

結果：`authoritative_position()` 回 None → `enrich_object` 把 `position_m` 設成 None，
而原本的統計只數 heading／speed 缺失，**不數 position**。下游 `build_scene.py` 會把
「缺 position_m」併進「collider 不存在」的訊息，使用者看到的是誤導的錯誤。

真正的產出者是 haware 那條路（`scripts/eval_haware_replay.py`，會寫 status/kp_sat/
spread_m/n_wheel_kp）。這組測試釘住：**選到的 track 全無位置時要明確報錯並指名原因**，
而不是產出一份每格 position_m 都是 null 的 filtered_output。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import filter_and_enrich_output as fae  # noqa: E402


def _frame(frame_index, objs):
    return {"frame_index": frame_index, "objects": objs}


def _yolo_obj(tid, x=100.0, y=200.0):
    """純 run_inference 的形狀：有 sat_coords，沒有 status。"""
    return {"id": 0, "tracked_id": tid, "class": "car", "confidence": 0.9,
            "bbox_2d": [0, 0, 10, 10], "sat_coords": [x, y],
            "have_heading": True, "have_measurements": True,
            "default_heading": False, "heading": 90.0, "speed_kmh": 30.0}


def _haware_obj(tid, x=100.0, y=200.0):
    """haware 路徑的形狀：帶 status='ok'。"""
    o = _yolo_obj(tid, x, y)
    o["status"] = "ok"
    return o


def _bbox_fallback_obj(tid, x=100.0, y=200.0):
    """eval_haware_replay --bbox-fallback 的形狀：權威欄位空、座標走旁路欄位。"""
    return {"id": 0, "tracked_id": tid, "class": "motor", "confidence": None,
            "bbox_2d": [0, 0, 10, 10], "sat_coords": None,
            "bbox_fallback_sat_coords": [x, y],
            "have_heading": False, "have_measurements": True,
            "default_heading": False, "heading": None, "speed_kmh": 0.0,
            "status": "bbox_fallback", "method": "bbox_homography",
            "spread_m": None, "n_wheel_kp": 0}


class BboxFallbackOptInTest(unittest.TestCase):
    """備援位置必須**明示**才採用——預設行為與 authority 的凍結政策一字不差。

    為什麼走旁路欄位而不是把 'bbox_fallback' 加進 accepted_statuses：
    政策被 test_localization_authority 釘死為 ("ok",)（downstream safety property）。
    備援座標放 bbox_fallback_sat_coords、sanitize 之後才注入 position_m，
    authority 模組零改動，任何一層都能拒收。
    """

    def _run(self, frames, ids, accept):
        data = {"meta": {"fps": 30}, "frames": frames}
        return fae.filter_and_enrich(data, ids, px_per_meter=29.113, prior_map={},
                                     accept_bbox_fallback=accept)

    def test_不帶旗標時備援記錄的position維持null(self):
        out = self._run([_frame(0, [_bbox_fallback_obj(21)])], [21], accept=False)
        obj = out["frames"][0]["objects"][0]
        self.assertIsNone(obj["position_m"])
        self.assertNotIn("position_source", obj)
        self.assertEqual(out["bbox_fallback_position_count"], 0)

    def test_帶旗標時備援位置以像素除以ppm注入並標明來源(self):
        out = self._run([_frame(0, [_bbox_fallback_obj(21, x=291.13, y=582.26)])],
                        [21], accept=True)
        obj = out["frames"][0]["objects"][0]
        self.assertAlmostEqual(obj["position_m"][0], 10.0, places=3)
        self.assertAlmostEqual(obj["position_m"][1], 20.0, places=3)
        self.assertEqual(obj["position_source"], "bbox_homography")
        self.assertEqual(out["bbox_fallback_position_count"], 1)

    def test_帶旗標也絕不碰權威欄位(self):
        """sat_coords 是 authority 的，備援只准動 position_m。"""
        out = self._run([_frame(0, [_bbox_fallback_obj(21)])], [21], accept=True)
        obj = out["frames"][0]["objects"][0]
        self.assertIsNone(obj["sat_coords"])

    def test_旗標不影響status_ok的正常記錄(self):
        out = self._run([_frame(0, [_haware_obj(7, 291.13, 291.13)])], [7], accept=True)
        obj = out["frames"][0]["objects"][0]
        self.assertIsNotNone(obj["position_m"])
        self.assertNotIn("position_source", obj)
        self.assertEqual(out["bbox_fallback_position_count"], 0)

    def test_帶旗標後全備援的track能通過缺位置閘門(self):
        frames = [_frame(i, [_bbox_fallback_obj(21, 100.0 + i, 200.0)]) for i in range(3)]
        out = self._run(frames, [21], accept=True)
        self.assertEqual(fae.tracks_without_position(out, [21]), [])


class MissingPositionIsNotSilentTest(unittest.TestCase):

    def _run(self, frames, ids):
        data = {"meta": {"fps": 30}, "frames": frames}
        return fae.filter_and_enrich(data, ids, px_per_meter=29.113, prior_map={})

    def test_純yolo輸入的位置確實會被判成null(self):
        """先釘住現況——這是問題的根源，不是我們想要的行為。"""
        out = self._run([_frame(0, [_yolo_obj(7)]), _frame(1, [_yolo_obj(7, 110.0)])], [7])
        positions = [o["position_m"] for f in out["frames"] for o in f["objects"]]
        self.assertTrue(all(p is None for p in positions),
                        "若這條斷言失敗，代表上游契約變了，本測試的前提要重新確認")

    def test_選到的track全無位置時要在統計中現形(self):
        out = self._run([_frame(0, [_yolo_obj(7)]), _frame(1, [_yolo_obj(7, 110.0)])], [7])
        stats = out["selected_track_stats"][7]
        self.assertEqual(stats["frames_present"], 2)
        self.assertEqual(stats["missing_position_count"], 2,
                         "缺 position 必須被數出來，否則只會在下游偽裝成『collider 不存在』")

    def test_haware輸入的位置正常算出且缺失數為零(self):
        out = self._run([_frame(0, [_haware_obj(7)]), _frame(1, [_haware_obj(7, 110.0)])], [7])
        stats = out["selected_track_stats"][7]
        self.assertEqual(stats["missing_position_count"], 0)
        positions = [o["position_m"] for f in out["frames"] for o in f["objects"]]
        self.assertTrue(all(p is not None for p in positions))

    def test_全無位置要能被一個明確的檢查攔下並指名原因(self):
        out = self._run([_frame(0, [_yolo_obj(7)])], [7])
        problems = fae.tracks_without_position(out, [7])
        self.assertEqual(problems, [7])
        msg = fae.describe_missing_position(problems)
        self.assertIn("7", msg)
        self.assertIn("status", msg, "訊息要指名根因（缺 status），不是只說『沒有位置』")
        self.assertIn("eval_haware_replay", msg, "訊息要指出正確的產出者")

    def test_部分幀有位置不算失敗(self):
        """真實資料本來就會有零星漏偵測，只有『整條 track 全無』才是走錯路徑。"""
        out = self._run([_frame(0, [_haware_obj(7)]), _frame(1, [_yolo_obj(7, 110.0)])], [7])
        self.assertEqual(fae.tracks_without_position(out, [7]), [])
        self.assertEqual(out["selected_track_stats"][7]["missing_position_count"], 1)


if __name__ == "__main__":
    unittest.main()
