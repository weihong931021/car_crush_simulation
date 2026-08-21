#!/usr/bin/env python3
"""backend 的所有路徑，集中一處。

每支腳本各自寫 `Path(__file__).resolve().parent / "output"` 的時候，搬檔案、改目錄層級、
或有人從別的 cwd 執行，就會各自算出不同答案而且沒人發現。這裡是唯一事實來源：

    repo/
    ├── backend/                     PKG_DIR
    │   └── output/<code>/           OUTPUT_DIR   底圖與 meta（gitignore）
    │       └── _uploads/<code>/     UPLOAD_DIR   使用者上傳的影片／截圖暫存
    ├── frontend/
    │   ├── onboarding/              WEB_DIR      進場流程 ①②③④ 的頁面
    │   └── player/                  3D 播放器（走 ../../scenes/）
    └── trafficlab-project/          TRAFFICLAB_DIR
        └── location/<code>/         LOCATION_ROOT  交付給標註 GUI 的成品

`output_dir()` / `location_dir()` 一律先驗代號再組路徑——代號直接變成目錄名，
放行 `..` 或 `/` 會寫到預期之外的地方。
"""
from pathlib import Path

from common import validate_code

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent

WEB_DIR = REPO_ROOT / "frontend" / "onboarding"
OUTPUT_DIR = PKG_DIR / "output"
UPLOAD_DIR = OUTPUT_DIR / "_uploads"
REFS_DIR = PKG_DIR / "refs"

TRAFFICLAB_DIR = REPO_ROOT / "trafficlab-project"
LOCATION_ROOT = TRAFFICLAB_DIR / "location"


def output_dir(code: str) -> Path:
    """backend 產出目錄 output/<code>/。"""
    return OUTPUT_DIR / validate_code(code)


def location_dir(code: str) -> Path:
    """trafficlab 標註輸入目錄 trafficlab-project/location/<code>/。"""
    return LOCATION_ROOT / validate_code(code)
