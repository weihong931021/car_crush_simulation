"""底圖網頁流程（spec docs/specs/2026-08-16-web-onboarding-flow-design.md ②）的離線測試。

釘的是三件事：
1. 去車降級**要留下機器可讀狀態**（不能再與「真的沒車」同值），前端據此警示
2. 大小由使用者決定、縮小是裁中央、確認才鎖定 meta——鎖定後所有變體同一個涵蓋範圍
3. 空白圖磚（Google 該 zoom 無影像）要能偵測，供 zoom 探測用
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PIL import Image
    import numpy as np
    import cv2  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def _noise_img(w, h, seed=0):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class DecarStatusTest(unittest.TestCase):
    """降級不能靜默：enhance_file 回傳 decar_status，enhance() 寫進 meta。"""

    def test_無key時decar_status為no_key(self):
        import image_enhance
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "s.png"
            _noise_img(64, 48).save(src)
            info = image_enhance.enhance_file(src, Path(d) / "o.png", key="", upscale=1)
        self.assertEqual(info["decar_status"], "no_key")
        self.assertEqual(info["vehicles_removed"], 0)

    def test_enhance把decar_status寫進meta(self):
        import image_enhance
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            out_dir.mkdir()
            _noise_img(64, 48).save(out_dir / "sat_raw.png")
            (out_dir / "meta.json").write_text(json.dumps({"px_per_meter": 29.0}))
            image_enhance.enhance("loc", key="", upscale=1, out_dir=out_dir)
            meta = json.loads((out_dir / "meta.json").read_text())
        self.assertEqual(meta["decar_status"], "no_key")


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class CaptureMetaTest(unittest.TestCase):
    """map_capture 不給 size 時，meta.size_m 必須是實際涵蓋公尺數而不是 null。"""

    def test_不裁切時size_m為整張涵蓋寬度(self):
        import map_capture
        img = _noise_img(1280, 1280)
        with tempfile.TemporaryDirectory() as d:
            meta = map_capture.finish_capture(img, 23.0, 120.0, "loc", 21, 2,
                                              size_m=None, out_dir=Path(d) / "loc")
        self.assertAlmostEqual(meta["size_m"], 1280 / meta["px_per_meter"], places=3)
        self.assertEqual((meta["img_w"], meta["img_h"]), (1280, 1280))

    def test_裁切時size_m原樣且圖為正方(self):
        import map_capture
        img = _noise_img(1280, 1280)
        with tempfile.TemporaryDirectory() as d:
            meta = map_capture.finish_capture(img, 23.0, 120.0, "loc", 21, 2,
                                              size_m=25.0, out_dir=Path(d) / "loc")
            saved = Image.open(Path(d) / "loc" / "sat_raw.png")
        self.assertEqual(meta["size_m"], 25.0)
        self.assertEqual(saved.size[0], saved.size[1])
        self.assertEqual(saved.size[0], round(25.0 * meta["px_per_meter"]))


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class BlankTileTest(unittest.TestCase):
    def test_均勻灰底判為空白(self):
        import webapp
        self.assertTrue(webapp.is_blank(Image.new("RGB", (100, 100), (229, 227, 223))))

    def test_有內容的圖不判為空白(self):
        import webapp
        self.assertFalse(webapp.is_blank(_noise_img(100, 100)))


@unittest.skipUnless(HAVE_DEPS, "需要 PIL / numpy / cv2")
class LockSizeTest(unittest.TestCase):
    """確認鎖定：所有變體裁中央到 size_m、meta 更新，且不同像素密度的變體按比例裁。"""

    def _seed(self, out_dir, ppm=29.0):
        out_dir.mkdir(parents=True)
        _noise_img(1280, 1280, 1).save(out_dir / "sat_raw.png")
        _noise_img(2560, 2560, 2).save(out_dir / "sat_clean.png")   # 2x 增強版
        (out_dir / "meta.json").write_text(json.dumps({
            "px_per_meter": ppm, "img_w": 1280, "img_h": 1280, "size_m": 1280 / ppm}))

    def test_鎖定後各變體涵蓋同一公尺數(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            meta = webapp.lock_size(out_dir, 25.0)
            raw = Image.open(out_dir / "sat_raw.png").size
            clean = Image.open(out_dir / "sat_clean.png").size
        side = round(25.0 * 29.0)
        self.assertEqual(raw, (side, side))
        self.assertEqual(clean, (side * 2, side * 2))
        self.assertEqual(meta["size_m"], 25.0)
        self.assertEqual((meta["img_w"], meta["img_h"]), (side, side))
        self.assertTrue(meta["locked"])

    def test_超過涵蓋範圍拒絕鎖定(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            with self.assertRaises(ValueError):
                webapp.lock_size(out_dir, 60.0)   # 1280/29 ≈ 44m，60m 超出

    def test_鎖定後跑enhance仍保留locked與size(self):
        """新流程是先鎖定再去車：enhance() 回寫 meta 時不能洗掉鎖定資訊。"""
        import image_enhance
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            webapp.lock_size(out_dir, 25.0)
            image_enhance.enhance("loc", key="", upscale=2, out_dir=out_dir)
            meta = json.loads((out_dir / "meta.json").read_text())
        self.assertTrue(meta["locked"])
        self.assertEqual(meta["size_m"], 25.0)
        self.assertEqual(meta["decar_status"], "no_key")
        self.assertEqual(meta["enhanced_px"], round(25.0 * 29.0) * 2)

    def test_已鎖定不可再鎖(self):
        import webapp
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d) / "loc"
            self._seed(out_dir)
            webapp.lock_size(out_dir, 30.0)
            with self.assertRaises(ValueError):
                webapp.lock_size(out_dir, 20.0)


if __name__ == "__main__":
    unittest.main()
