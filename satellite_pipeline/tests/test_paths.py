"""路徑集中在 paths.py：以前每支腳本各自 `Path(__file__).resolve().parent / "output"`，
搬檔案或有人從別的 cwd 執行就會各自算出不同答案。這裡釘住「大家算出同一組路徑」，
以及 location_dir()/output_dir() 會擋掉不合法代號（它們直接變成目錄名）。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paths  # noqa: E402


class PathsTest(unittest.TestCase):

    def test_全部路徑都掛在專案根底下(self):
        self.assertTrue(paths.PKG_DIR.is_dir())
        self.assertEqual(paths.OUTPUT_DIR.parent, paths.PKG_DIR)
        self.assertEqual(paths.WEB_DIR, paths.PKG_DIR / "web")
        self.assertEqual(paths.UPLOAD_DIR.parent, paths.OUTPUT_DIR)
        self.assertEqual(paths.TRAFFICLAB_DIR.parent, paths.REPO_ROOT)
        self.assertEqual(paths.LOCATION_ROOT, paths.TRAFFICLAB_DIR / "location")

    def test_各模組拿到的是同一組路徑(self):
        import image_enhance
        import map_capture
        import webapp
        for mod in (map_capture, image_enhance, webapp):
            with self.subTest(module=mod.__name__):
                self.assertEqual(mod.OUTPUT_DIR, paths.OUTPUT_DIR)

    def test_代號組路徑前會驗證(self):
        self.assertEqual(paths.output_dir("abc-1_2"), paths.OUTPUT_DIR / "abc-1_2")
        self.assertEqual(paths.location_dir("abc"), paths.LOCATION_ROOT / "abc")
        for bad in ("../etc", "a/b", "", "a b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                paths.output_dir(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                paths.location_dir(bad)

    def test_trafficlab存在時_repo結構符合預期(self):
        """給別人 clone 用：這兩個目錄的相對關係是 handoff 的前提。"""
        if paths.TRAFFICLAB_DIR.exists():
            self.assertTrue((paths.TRAFFICLAB_DIR / "main.py").is_file())


if __name__ == "__main__":
    unittest.main()
