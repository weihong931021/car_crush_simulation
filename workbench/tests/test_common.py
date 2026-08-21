"""地點代號驗證測試（2026-07-24 審查）。

code 被拿來當 output/<code> 路徑。未驗證時 `../` 可寫到 output 之外。
這裡鎖住「只接受 [A-Za-z0-9_-]」這條界線，與 player/scene-loader.js 的場景代號規則一致。
"""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import validate_code


class ValidateCodeTest(unittest.TestCase):
    def test_合法代號原樣回傳(self):
        for code in ("test1", "tainan_yongkang", "taipei_sogo", "a-b_C9", "1"):
            self.assertEqual(validate_code(code), code)

    def test_路徑逃逸字元一律拒絕(self):
        for bad in ("../evil", "a/b", "/abs/path", "..", ".", "a\\b", "~/x"):
            with self.assertRaises(ValueError, msg=f"{bad!r} 應被拒絕"):
                validate_code(bad)

    def test_引號換行等非白名單字元一律拒絕(self):
        # 路徑分隔以外的可疑字元（引號、換行、空白、分號、大括號）也一併擋在白名單外
        for bad in ('x"; rm -rf /', "a'b", 'a"b', "a\nb", "a b", "a;b", "{x}"):
            with self.assertRaises(ValueError, msg=f"{bad!r} 應被拒絕"):
                validate_code(bad)

    def test_空值與非字串拒絕(self):
        for bad in ("", None, 123):
            with self.assertRaises(ValueError, msg=f"{bad!r} 應被拒絕"):
                validate_code(bad)


if __name__ == "__main__":
    unittest.main()
