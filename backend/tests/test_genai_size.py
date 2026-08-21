"""plan_genai_size 的尺寸協商測試。

背景：生圖那半（`genai_enhance()`）2026-08-17 從 Gemini 換成 OpenAI gpt-image-2。
換供應商帶進一條 Gemini 沒有的硬限制——**輸出尺寸不能任意指定**：兩邊必須是 16 的
倍數、長邊 ≤3840、長寬比 ≤3:1、總像素落在 655,360–8,294,400。

（選 gpt-image-2 而不是更便宜的 gpt-image-1-mini 正是為了這條：mini 只吐
1024x1024 / 1024x1536 / 1536x1024 三種比例，衛星圖送進去必被壓扁。）

所以這裡釘住的是「協商出來的畫布仍然貼著來源長寬比」——比例一歪，
拿回來縮回原尺寸時就會扭曲，路面幾何跟著錯。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from image_enhance import (  # noqa: E402
    IMAGE_MAX_EDGE, IMAGE_MAX_PIXELS, IMAGE_MIN_PIXELS, IMAGE_SIZE_MULTIPLE,
    plan_genai_size,
)

# repo 內真實出現過的校正參考圖尺寸 + backend 常見輸出
REAL_SIZES = ((1676, 1148), (1190, 1258), (1812, 1264), (914, 1246),
              (1515, 1038), (1024, 1024), (2560, 2560))


class PlanGenaiSizeTest(unittest.TestCase):

    def test_回傳尺寸全部滿足_gpt_image_2_的硬限制(self):
        for w, h in REAL_SIZES:
            with self.subTest(src=(w, h)):
                tw, th = plan_genai_size(w, h)
                self.assertEqual(tw % IMAGE_SIZE_MULTIPLE, 0, f"{tw} 不是 16 的倍數")
                self.assertEqual(th % IMAGE_SIZE_MULTIPLE, 0, f"{th} 不是 16 的倍數")
                self.assertLessEqual(max(tw, th), IMAGE_MAX_EDGE)
                self.assertGreaterEqual(tw * th, IMAGE_MIN_PIXELS)
                self.assertLessEqual(tw * th, IMAGE_MAX_PIXELS)

    def test_長寬比誤差小於百分之一(self):
        """比例是這個函式唯一真正要守住的東西：歪掉＝路面幾何被扭曲。"""
        for w, h in REAL_SIZES:
            with self.subTest(src=(w, h)):
                tw, th = plan_genai_size(w, h)
                self.assertAlmostEqual(tw / th, w / h, delta=0.01 * (w / h),
                                       msg=f"{w}x{h} → {tw}x{th} 比例跑掉")

    def test_像素過少的小圖會被放大到下限以上(self):
        tw, th = plan_genai_size(320, 240)          # 76,800 px，遠低於 655,360
        self.assertGreaterEqual(tw * th, IMAGE_MIN_PIXELS)
        self.assertAlmostEqual(tw / th, 320 / 240, delta=0.01 * (320 / 240))

    def test_像素過多的大圖會被縮到上限以下(self):
        tw, th = plan_genai_size(8000, 6000)        # 48M px，遠高於 8.29M
        self.assertLessEqual(tw * th, IMAGE_MAX_PIXELS)
        self.assertLessEqual(max(tw, th), IMAGE_MAX_EDGE)

    def test_超過三比一的細長圖直接報錯而不是默默壓扁(self):
        """壓扁是靜默給出錯誤結論的那種失敗，寧可炸掉。"""
        with self.assertRaises(ValueError):
            plan_genai_size(4000, 800)              # 5:1
        with self.assertRaises(ValueError):
            plan_genai_size(800, 4000)              # 1:5

    def test_無效尺寸報錯(self):
        for w, h in ((0, 100), (100, 0), (-10, 100)):
            with self.subTest(src=(w, h)), self.assertRaises(ValueError):
                plan_genai_size(w, h)


if __name__ == "__main__":
    unittest.main()
