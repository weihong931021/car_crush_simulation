"""enhance_file 的座標安全測試。

背景：真實影片的 `position_m` 活在 G-projection 校正參考圖（`location/<code>/sat_<code>.png`）
的平面上。要讓那張圖變好看又不破壞座標，增強**必須是精確整數倍的等比放大**——
只要長寬比或取景改變，px_per_meter 就無法用單一係數換算，車輛位置整個錯位。

所以這裡釘住的不是「畫質有沒有變好」（那要人眼），而是**幾何有沒有被動到**。
（`genai_enhance()` 讓 Gemini 重畫整張，長寬比與內容都可能改變，不可用於此用途。）
"""
import unittest
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PIL import Image
    import numpy  # noqa: F401  （image_enhance 內部需要）
    import cv2    # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class EnhanceFileGeometryTest(unittest.TestCase):
    """增強後的幾何必須是輸入的精確整數倍。"""

    def _make(self, d, w, h):
        p = Path(d) / "src.png"
        Image.new("RGB", (w, h), (90, 90, 95)).save(p)
        return p

    def _run(self, src, dst, **kw):
        import image_enhance
        # 不帶 key → 走「只銳化不去車」的降級路徑，測試不需要網路
        return image_enhance.enhance_file(src, dst, key="", **kw)

    def test_非正方形輸入的長寬比原樣保留(self):
        """校正參考圖幾乎都不是正方（taipei-cm 1190×1258、kee-cc 1812×1264）。"""
        for w, h in ((1190, 1258), (1812, 1264), (914, 1246)):
            with tempfile.TemporaryDirectory() as d:
                src = self._make(d, w, h)
                dst = Path(d) / "out.png"
                info = self._run(src, dst, upscale=2)
                self.assertEqual(Image.open(dst).size, (w * 2, h * 2),
                                 f"{w}×{h} 放大 2 倍後尺寸不對")
                self.assertEqual(info["out_size"], (w * 2, h * 2))
                self.assertEqual(info["upscale"], 2)

    def test_upscale為1時尺寸完全不變(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._make(d, 640, 480)
            dst = Path(d) / "out.png"
            self._run(src, dst, upscale=1)
            self.assertEqual(Image.open(dst).size, (640, 480))

    def test_各種放大倍率都是精確整數倍(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._make(d, 300, 200)
            for k in (1, 2, 3):
                dst = Path(d) / f"out{k}.png"
                self._run(src, dst, upscale=k)
                self.assertEqual(Image.open(dst).size, (300 * k, 200 * k))

    def test_回報的px_per_meter換算係數等於upscale(self):
        """呼叫端要靠這個係數換算 ground.px_per_meter，錯了車就會偏。"""
        with tempfile.TemporaryDirectory() as d:
            src = self._make(d, 500, 400)
            info = self._run(src, Path(d) / "o.png", upscale=3)
            self.assertEqual(info["px_per_meter_factor"], 3)

    def test_輸入不存在時給清楚錯誤(self):
        import image_enhance
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                image_enhance.enhance_file(Path(d) / "nope.png", Path(d) / "o.png", key="")

    def test_不合法的放大倍率被拒(self):
        import image_enhance
        with tempfile.TemporaryDirectory() as d:
            src = self._make(d, 100, 100)
            for bad in (0, -1, 1.5):
                with self.assertRaises(ValueError, msg=f"upscale={bad} 應被拒"):
                    image_enhance.enhance_file(src, Path(d) / "o.png", key="", upscale=bad)


if __name__ == "__main__":
    unittest.main()
