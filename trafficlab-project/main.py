import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from trafficlab.gui.main_window import MainWindow


def apply_dark_theme(app) -> None:
    """套用深色佈景，取不到就安靜略過。

    qdarktheme 在 2.x 把 API 從 `load_stylesheet()` 改名成 `setup_theme()`，
    而 2.x 要求 Python <3.12——這台是 3.14，pip 只裝得到 0.1.x。
    佈景主題純屬外觀，不該擋住標定流程（③ 是整條鏈唯一沒有非 GUI 入口的一段）。
    """
    try:
        import qdarktheme
    except ImportError:
        print("提示：未安裝 qdarktheme，使用系統預設外觀")
        return
    try:
        if hasattr(qdarktheme, "setup_theme"):            # 2.x
            qdarktheme.setup_theme()                      # ← 不是 apply_dark_theme()：那會無限遞迴
        elif hasattr(qdarktheme, "load_stylesheet"):      # 0.1.x / 1.x
            app.setStyleSheet(qdarktheme.load_stylesheet("dark"))
    except Exception as e:                                # noqa: BLE001 — 外觀不該擋住標定流程
        print(f"提示：套用深色佈景失敗（{type(e).__name__}: {e}），使用系統預設外觀")


def main():
    app = QApplication(sys.argv)
    primary_screen = app.primaryScreen()
    if primary_screen is None:
        print("TrafficLab GUI requires an active display. No screen is currently available.")
        return 1

    app.setWindowIcon(QIcon("./media/icon.png"))

    apply_dark_theme(app)

    win = MainWindow()
    win.show()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
