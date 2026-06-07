#!/usr/bin/env python3
"""
pipeline.py — 一鍵：經緯度 → 衛星圖 → 去車銳化 → 產生 Blender 貼地腳本

    python3 pipeline.py --lat 23.026901 --lon 120.249615 --code tainan_yongkang
    python3 pipeline.py --lat ... --lon ... --code ... --size 25
    python3 pipeline.py --code tainan_yongkang --skip-capture   # 重新增強既有 raw
    python3 pipeline.py --code tainan_yongkang --skip-enhance   # 用 raw 直接貼

步驟：
    1. map_capture   → output/{code}/sat_raw.png + meta.json
    2. image_enhance → output/{code}/sat_clean.png（Gemini 去車 + 銳化）
    3. blender_ground→ 印出可貼 Blender 的程式碼路徑

第 3 步「自動貼進正在開的 Blender」由 Claude Code 透過 Blender MCP 的
execute_blender_code 完成（見 README）。本腳本獨立執行時會把貼地程式碼
存成 output/{code}/blender_ground_{code}.py 供手動執行。

key 從環境變數或 satellite_pipeline/.env 讀：GOOGLE_MAPS_KEY、GEMINI_API_KEY
"""
import argparse
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))


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
    ap.add_argument("--code", required=True)
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
        print("\n=== [1/3] 擷取衛星圖（Google Static API）===")
        from map_capture import capture
        capture(args.lat, args.lon, args.code, args.zoom, args.size)

    if not args.skip_enhance:
        print("\n=== [2/3] 去車 + 銳化高清化 ===")
        from image_enhance import enhance
        enhance(args.code, upscale=args.upscale)

    print("\n=== [3/3] Blender 貼地腳本 ===")
    from blender_ground import build_blender_code
    code_str = build_blender_code(args.code)
    out_dir = SCRIPTS_DIR / "output" / args.code
    script_path = out_dir / f"blender_ground_{args.code}.py"
    script_path.write_text(code_str)
    print(f"  已存：{script_path}")
    print("  自動貼進 Blender：請 Claude Code 用 Blender MCP execute_blender_code 執行此檔內容")
    print(f"  手動：Blender Text Editor → Open → {script_path} → Run")

    print(f"\n[pipeline] 完成。輸出在 output/{args.code}/")


if __name__ == "__main__":
    main()
