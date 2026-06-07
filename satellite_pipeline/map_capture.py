#!/usr/bin/env python3
"""
map_capture.py — 經緯度 → 衛星圖（Google Maps Static API）

圖源鎖定 Google Maps Static API（zoom=21, scale=2 → 29 px/m，一般地點上限）。
純 HTTP，免 playwright、免瀏覽器。決策見 README.md。

用法：
    python3 map_capture.py --lat 23.026901 --lon 120.249615 --code tainan_yongkang
    python3 map_capture.py --lat ... --lon ... --code ... --size 30 --zoom 21

輸出：output/{code}/sat_raw.png + output/{code}/meta.json
"""
import argparse
import io
import json
import math
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPTS_DIR / "output"


def load_google_key() -> str:
    """從 GOOGLE_MAPS_KEY 環境變數或 .env 讀 Google Static API key。"""
    key = os.environ.get("GOOGLE_MAPS_KEY", "").strip()
    if key:
        return key
    env = SCRIPTS_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("GOOGLE_MAPS_KEY=") and "=" in line:
                return line.split("=", 1)[1].strip()
    sys.exit("ERROR: 找不到 GOOGLE_MAPS_KEY（設環境變數或寫進 satellite_pipeline/.env）")


def px_per_meter(lat: float, zoom: int, scale: int = 2) -> float:
    """Web Mercator 在給定緯度/zoom/scale 下的 像素/公尺。"""
    meters_per_css_px = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
    return scale / meters_per_css_px


def capture(lat: float, lon: float, code: str, zoom: int = 21,
            size_m: float | None = None, key: str | None = None) -> dict:
    """抓 Static API 衛星圖；size_m 給定則裁中心 size_m×size_m，否則存整張 1280²。"""
    key = key or load_google_key()
    scale = 2

    url = (
        "https://maps.googleapis.com/maps/api/staticmap"
        f"?center={lat},{lon}&zoom={zoom}&size=640x640&scale={scale}"
        f"&maptype=satellite&key={key}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        ct = resp.headers.get("content-type", "")
        data = resp.read()
    if "image" not in ct:
        sys.exit(f"ERROR: Static API 沒回傳圖片（{ct}）：{data[:300]!r}")

    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    ppm = px_per_meter(lat, zoom, scale)

    if size_m:
        side = round(size_m * ppm)
        w, h = img.size
        half = side // 2
        cx, cy = w // 2, h // 2
        img = img.crop((cx - half, cy - half, cx + half, cy + half))

    out_dir = OUTPUT_DIR / code
    out_dir.mkdir(parents=True, exist_ok=True)
    img_path = out_dir / "sat_raw.png"
    img.save(img_path)

    # 重抓新 raw 後，舊的衍生圖已過時 → 刪除，避免新地形誤用舊 sat_clean/sat_genai
    for stale in ("sat_clean.png", "sat_genai.png"):
        sp = out_dir / stale
        if sp.exists():
            sp.unlink()
            print(f"  清除過時衍生圖：{stale}")

    meta = {
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
        "scale": scale,
        "px_per_meter": round(ppm, 4),
        "img_w": img.size[0],
        "img_h": img.size[1],
        "size_m": size_m,
        "source": "google_maps_static_api",
        "timestamp": datetime.now().isoformat(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    print(f"  Saved: {img_path}  ({img.size[0]}x{img.size[1]})")
    print(f"  px_per_meter: {ppm:.2f}  → {img.size[0]/ppm:.1f} x {img.size[1]/ppm:.1f} m")
    return meta


def main():
    ap = argparse.ArgumentParser(description="Google Static API 衛星圖擷取")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--code", required=True, help="地點代號（輸出資料夾名）")
    ap.add_argument("--zoom", type=int, default=21, help="預設 21（此地點上限）")
    ap.add_argument("--size", type=float, default=None, help="裁切邊長（公尺）；省略=整張1280²")
    args = ap.parse_args()

    print(f"[map_capture] lat={args.lat} lon={args.lon} zoom={args.zoom} code={args.code}")
    capture(args.lat, args.lon, args.code, args.zoom, args.size)
    print("[map_capture] Done.")


if __name__ == "__main__":
    main()
