#!/usr/bin/env python3
"""
pipeline.py — 一鍵：經緯度 → 衛星圖 → 去車銳化

    python3 pipeline.py --lat 23.026901 --lon 120.249615 --code tainan_yongkang
    python3 pipeline.py --lat ... --lon ... --code ... --size 25
    python3 pipeline.py --code tainan_yongkang --skip-capture   # 重新增強既有 raw

步驟：
    1. map_capture   → output/{code}/sat_raw.png + meta.json
    2. image_enhance → output/{code}/sat_clean.png（Gemini 去車 + 銳化）

產出的 sat_*.png + meta.json 供 tools/build_scene.py 以 --sat-dir 取用，
產生場景包的 ground.png（見專案根 README「新增場景」）。

key 從環境變數或 backend/.env 讀：GOOGLE_MAPS_KEY、GEMINI_API_KEY
"""
import argparse
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from common import validate_code  # noqa: E402


def load_env():
    env = SCRIPTS_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def main():
    ap = argparse.ArgumentParser(description="衛星底圖自動化一鍵流程")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--code", required=True, type=validate_code)
    ap.add_argument("--zoom", type=int, default=21)
    ap.add_argument("--size", type=float, default=25.0, help="裁切邊長（公尺），預設 25")
    ap.add_argument("--upscale", type=int, default=2)
    ap.add_argument("--skip-capture", action="store_true")
    ap.add_argument("--skip-enhance", action="store_true")
    args = ap.parse_args()
    load_env()

    print(f"[pipeline] code={args.code} lat={args.lat} lon={args.lon} zoom={args.zoom}")

    if not args.skip_capture:
        if args.lat is None or args.lon is None:
            sys.exit("ERROR: 擷取需要 --lat / --lon（或用 --skip-capture）")
        print("\n=== [1/2] 擷取衛星圖（Google Static API）===")
        from map_capture import capture
        capture(args.lat, args.lon, args.code, args.zoom, args.size)

    if not args.skip_enhance:
        print("\n=== [2/2] 去車 + 銳化高清化 ===")
        from image_enhance import enhance
        enhance(args.code, upscale=args.upscale)

    print(f"\n[pipeline] 完成。輸出在 output/{args.code}/")
    print(f"  接場景包：tools/build_scene.py --sat-dir backend/output/{args.code} ...")


if __name__ == "__main__":
    main()
