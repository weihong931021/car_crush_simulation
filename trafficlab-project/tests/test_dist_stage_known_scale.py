"""DistStage 的「已知比例尺」：satellite_pipeline webapp 交付時會寫 sat_meta_<code>.json，
裡面的 px_per_meter 是從 Web Mercator 解析算的（29.11 × 放大倍率），比人手在衛星圖上
點兩個錨點量距離準得多。這裡釘住讀取規則：檔案在就回數字，不在／壞掉就回 None，
DistStage 照舊走人工量測——不能因為多了這個入口而讓舊流程壞掉。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trafficlab.gui.tabs.calibration_stage.dist_stage import load_known_scale  # noqa: E402


class LoadKnownScaleTest(unittest.TestCase):

    def test_讀到交付的比例尺(self):
        with tempfile.TemporaryDirectory() as d:
            loc = Path(d) / "location" / "abc"
            loc.mkdir(parents=True)
            (loc / "sat_meta_abc.json").write_text(json.dumps(
                {"px_per_meter": 58.226, "sat_variant": "sat_clean.png", "size_m": 38.0}))
            info = load_known_scale(d, "abc")
        self.assertAlmostEqual(info["px_per_meter"], 58.226)
        self.assertEqual(info["sat_variant"], "sat_clean.png")

    def test_沒有檔案回None(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(load_known_scale(d, "nope"))

    def test_壞檔或無效數值回None(self):
        with tempfile.TemporaryDirectory() as d:
            loc = Path(d) / "location" / "abc"
            loc.mkdir(parents=True)
            (loc / "sat_meta_abc.json").write_text("{not json")
            self.assertIsNone(load_known_scale(d, "abc"))
            (loc / "sat_meta_abc.json").write_text(json.dumps({"px_per_meter": 0}))
            self.assertIsNone(load_known_scale(d, "abc"))

    def test_project_root為None時回None(self):
        self.assertIsNone(load_known_scale(None, "abc"))


if __name__ == "__main__":
    unittest.main()
