"""網頁標註（③）：CCTV ↔ 衛星圖對應點 → 單應性 → G_projection_<code>.json。

原本這一步只能開 trafficlab 的 PyQt5 GUI 手動點。這裡把「算 H、算重投影誤差、
寫成 trafficlab 認得的 JSON」搬到網頁後端，schema 對齊 trafficlab_config.default_config()：
homography.H / anchors_list、parallax.px_per_meter（由 ② 鎖定的底圖直接帶入）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import cv2  # noqa: F401
    import numpy as np
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "需要 cv2 / numpy")
class HomographyTest(unittest.TestCase):

    # 一組已知的仿射對應：cctv 座標 ×2 再平移 (10, 20) 就是 sat 座標
    PAIRS = [
        {"coords_cctv": [0, 0],     "coords_sat": [10, 20]},
        {"coords_cctv": [100, 0],   "coords_sat": [210, 20]},
        {"coords_cctv": [100, 50],  "coords_sat": [210, 120]},
        {"coords_cctv": [0, 50],    "coords_sat": [10, 120]},
    ]

    def test_四點求出正確的H(self):
        import annotate
        H, err = annotate.solve_homography(self.PAIRS)
        self.assertLess(err["rms_px"], 1e-6)
        pt = np.array([50.0, 25.0, 1.0])
        out = np.array(H) @ pt
        out = out[:2] / out[2]
        np.testing.assert_allclose(out, [110.0, 70.0], atol=1e-6)

    def test_H左下角正規化為1(self):
        """trafficlab 的 haware_forward 會檢查 H[2,2] ≈ 1。"""
        import annotate
        H, _ = annotate.solve_homography(self.PAIRS)
        self.assertAlmostEqual(H[2][2], 1.0, places=9)

    def test_少於四點要報錯(self):
        import annotate
        with self.assertRaises(ValueError):
            annotate.solve_homography(self.PAIRS[:3])

    def test_退化點位要報錯(self):
        """四點共線求不出單應性，不能靜默回一個垃圾矩陣。"""
        import annotate
        collinear = [{"coords_cctv": [i, i], "coords_sat": [2*i, 2*i]} for i in range(4)]
        with self.assertRaises(ValueError):
            annotate.solve_homography(collinear)

    def test_剛好四點的誤差恆為零_且要標示為不可信(self):
        """陷阱：單應性 8 個自由度，4 組點剛好把它解死——**再怎麼標歪 RMS 都是 0**。

        介面若照樣顯示「誤差 0.00 px」會給人「標得很準」的錯覺。所以誤差字典帶
        overdetermined=False，由前端據此說明「至少 5 點才看得出誤差」。
        """
        import annotate
        noisy = [dict(p) for p in self.PAIRS]
        noisy[2] = {"coords_cctv": [100, 50], "coords_sat": [215, 120]}   # 故意偏 5px
        _, err = annotate.solve_homography(noisy)
        self.assertLess(err["rms_px"], 1e-6)          # 仍然是 0——這就是陷阱本身
        self.assertFalse(err["overdetermined"])

    def test_五點以上才量得出標歪(self):
        import annotate
        pairs = self.PAIRS + [{"coords_cctv": [50, 25], "coords_sat": [115, 70]}]  # 偏 5px
        _, err = annotate.solve_homography(pairs)
        self.assertTrue(err["overdetermined"])
        self.assertEqual(len(err["per_point_px"]), 5)
        self.assertGreater(err["max_px"], 0.5)
        self.assertEqual(err["worst_index"], 4)


@unittest.skipUnless(HAVE_DEPS, "需要 cv2 / numpy")
class BuildGProjectionTest(unittest.TestCase):

    PAIRS = HomographyTest.PAIRS

    def test_產出符合trafficlab_schema(self):
        import annotate
        obj = annotate.build_g_projection("abc", self.PAIRS, px_per_meter=29.11,
                                          cctv_path="cctv_abc.png", sat_path="sat_abc.png")
        for key in ("meta", "inputs", "undistort", "homography", "parallax",
                    "use_svg", "layout_svg", "use_roi", "roi_method", "ref_method", "proj_method"):
            self.assertIn(key, obj)
        self.assertEqual(obj["meta"]["location_code"], "abc")
        self.assertEqual(len(obj["homography"]["H"]), 3)
        self.assertEqual(len(obj["homography"]["anchors_list"]), 4)
        self.assertAlmostEqual(obj["parallax"]["px_per_meter"], 29.11)
        self.assertEqual(obj["inputs"]["sat_path"], "sat_abc.png")

    def test_錨點帶id與名稱(self):
        import annotate
        obj = annotate.build_g_projection("abc", self.PAIRS, px_per_meter=1.0)
        a = obj["homography"]["anchors_list"][0]
        self.assertEqual(a["id"], 0)
        self.assertIn("name", a)
        self.assertIn("coords_cctv", a)
        self.assertIn("coords_sat", a)

    def test_寫檔到location目錄(self):
        import annotate
        with tempfile.TemporaryDirectory() as d:
            loc = Path(d) / "abc"
            loc.mkdir()
            path = annotate.save_g_projection(loc, "abc", self.PAIRS, px_per_meter=29.11)
            obj = json.loads(Path(path).read_text())
        self.assertTrue(str(path).endswith("G_projection_abc.json"))
        self.assertEqual(obj["meta"]["location_code"], "abc")


if __name__ == "__main__":
    unittest.main()
