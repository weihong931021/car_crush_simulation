#!/opt/homebrew/Caskroom/miniconda/base/bin/python3
"""
Capture a top-down satellite screenshot using Leaflet + Esri World Imagery.
Always overhead (no tilt), free, no API key required.

Usage:
    python3 map_capture.py --lat 25.05 --lon 121.52 --code test1 [--zoom 20]

Output: location/{code}/sat_raw_{code}.png
        location/{code}/sat_capture_meta.json
"""
import argparse
import json
import math
import time
import tempfile
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRIPTS_DIR = Path(__file__).parent
LOCATION_DIR = SCRIPTS_DIR.parent / "location"

# Esri World Imagery — always top-down, free, up to native zoom 20
ESRI_TILE_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {W}px; height: {H}px; overflow: hidden; }}
  #map {{ width: {W}px; height: {H}px; }}
</style>
</head>
<body>
<div id="map"></div>
<script>
  var map = L.map('map', {{
    center: [{lat}, {lon}],
    zoom: {zoom},
    zoomControl: false,
    attributionControl: false,
    fadeAnimation: false,
    zoomAnimation: false
  }});

  var layer = L.tileLayer('{tile_url}', {{
    maxZoom: 23,
    maxNativeZoom: 20,
    crossOrigin: true
  }});

  window._tilesLoaded = 0;
  window._tilesTotal = 0;
  layer.on('tileloadstart', function() {{ window._tilesTotal++; }});
  layer.on('tileload',      function() {{ window._tilesLoaded++; }});
  layer.addTo(map);
</script>
</body>
</html>
"""


def calc_px_per_meter(lat: float, zoom: int) -> float:
    earth_circumference = 2 * math.pi * 6378137
    meters_per_pixel = earth_circumference * math.cos(math.radians(lat)) / (2**zoom * 256)
    return 1.0 / meters_per_pixel


def capture(lat: float, lon: float, code: str, zoom: int = 20,
            width: int = 1024, height: int = 1024) -> dict:
    out_dir = LOCATION_DIR / code
    out_dir.mkdir(parents=True, exist_ok=True)

    img_path = out_dir / f"sat_raw_{code}.png"
    meta_path = out_dir / f"sat_capture_meta.json"

    html = HTML_TEMPLATE.format(
        lat=lat, lon=lon, zoom=zoom,
        tile_url=ESRI_TILE_URL,
        W=width, H=height,
    )

    with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                     delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp_html = Path(f.name)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})

            print(f"  Loading Leaflet map (lat={lat}, lon={lon}, zoom={zoom})...")
            page.goto(f"file://{tmp_html}", wait_until="load", timeout=15000)

            # wait until all tiles are loaded
            for _ in range(30):  # max 15s
                loaded = page.evaluate("window._tilesLoaded")
                total = page.evaluate("window._tilesTotal")
                if total > 0 and loaded >= total:
                    break
                time.sleep(0.5)
            else:
                print("  Warning: tiles may not be fully loaded, proceeding anyway")

            time.sleep(0.5)  # final settle
            page.screenshot(path=str(img_path), full_page=False)
            browser.close()
    finally:
        tmp_html.unlink(missing_ok=True)

    px_per_meter = calc_px_per_meter(lat, zoom)
    meta = {
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
        "tile_source": "esri_world_imagery",
        "px_per_meter": round(px_per_meter, 4),
        "img_w": width,
        "img_h": height,
        "timestamp": datetime.now().isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"  Saved: {img_path}")
    print(f"  px_per_meter: {px_per_meter:.2f}  ({width/px_per_meter:.1f} x {height/px_per_meter:.1f} m)")
    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Capture top-down satellite image via Leaflet+Esri"
    )
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--code", type=str, required=True, help="location_code, e.g. test1")
    parser.add_argument("--zoom", type=int, default=20,
                        help="Zoom level 18-20 (default 20, Esri max native zoom is 20)")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    args = parser.parse_args()

    print(f"[map_capture] lat={args.lat} lon={args.lon} zoom={args.zoom} code={args.code}")
    capture(args.lat, args.lon, args.code, args.zoom, args.width, args.height)
    print("[map_capture] Done.")


if __name__ == "__main__":
    main()
