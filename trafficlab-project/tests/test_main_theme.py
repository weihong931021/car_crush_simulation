"""main.py 的深色佈景：qdarktheme 2.x 有 setup_theme，舊版只有 load_stylesheet。

原本 2.x 分支寫成 `apply_dark_theme(app)`（呼叫自己）→ 無限遞迴，GUI 一開就 RecursionError。
這台的 .venv-pifpaf 正好裝 2.x，所以標註 GUI 實際上是開不起來的。
佈景純屬外觀，不該擋住標定流程——這裡釘住「不遞迴、且套用失敗要安靜略過」。
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_main():
    spec = importlib.util.spec_from_file_location("tl_main", ROOT / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ApplyDarkThemeTest(unittest.TestCase):

    def setUp(self):
        self._saved = sys.modules.get("qdarktheme")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            sys.modules.pop("qdarktheme", None)
        else:
            sys.modules["qdarktheme"] = self._saved

    def test_2x用setup_theme且不遞迴(self):
        calls = []
        stub = types.ModuleType("qdarktheme")
        stub.setup_theme = lambda *a, **k: calls.append(("setup_theme", a, k))
        stub.load_stylesheet = lambda *a, **k: calls.append(("load_stylesheet", a, k))
        sys.modules["qdarktheme"] = stub
        _load_main().apply_dark_theme(object())          # 遞迴的話這行會 RecursionError
        self.assertEqual([c[0] for c in calls], ["setup_theme"])

    def test_舊版走load_stylesheet(self):
        applied = []
        stub = types.ModuleType("qdarktheme")
        stub.load_stylesheet = lambda theme="dark": f"QSS::{theme}"
        sys.modules["qdarktheme"] = stub

        class FakeApp:
            def setStyleSheet(self, qss): applied.append(qss)

        _load_main().apply_dark_theme(FakeApp())
        self.assertEqual(applied, ["QSS::dark"])

    def test_套用失敗不可中斷啟動(self):
        stub = types.ModuleType("qdarktheme")
        def boom(*a, **k): raise RuntimeError("theme engine exploded")
        stub.setup_theme = boom
        sys.modules["qdarktheme"] = stub
        _load_main().apply_dark_theme(object())          # 不該往外拋

    def test_未安裝時安靜略過(self):
        sys.modules["qdarktheme"] = None                 # import 會 ImportError
        _load_main().apply_dark_theme(object())


if __name__ == "__main__":
    unittest.main()
