#!/usr/bin/env python3
"""
webapp.py — 底圖自動化的網頁前端（spec docs/specs/2026-08-16-web-onboarding-flow-design.md ①②）

    python3 satellite_pipeline/webapp.py            # http://127.0.0.1:8765/
    python3 satellite_pipeline/webapp.py --port 9000

流程：
    輸入 lat/lon/code → POST /api/capture：探測可用 zoom、抓整張 1280² 原圖（不去車，1 秒）
    → 前端預覽＋滑桿調大小（≤ 涵蓋範圍純前端裁中央、零延遲；超過就降 zoom 重抓）
    → POST /api/lock：raw 裁中央到 size_m、meta 鎖定，**再**對裁好的圖去車銳化（選配 genai）
      → 使用者檢視品質。這組 meta 就是後續標註的座標系來源（鎖定後不可再改）。

去車放在鎖定之後是實測結果：Gemini 對 1280² 整張只偵測到 7 台車、對 728² 裁切圖偵測到
38 台——小圖偵測準得多，所以先裁再去車。

零依賴（stdlib http.server），與 tools/verify_scenes.mjs 同路線。輸出仍在 output/<code>/，
與 CLI 完全相容（build_scene --sat-dir 直接吃）。
"""
import argparse
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPTS_DIR / "output"
WEB_DIR = SCRIPTS_DIR / "web"
sys.path.insert(0, str(SCRIPTS_DIR))

from common import validate_code  # noqa: E402

VARIANTS = ("sat_raw.png", "sat_clean.png", "sat_genai.png")
BLANK_STD_THRESHOLD = 6.0     # 灰階標準差低於此值視為「無影像的空白圖磚」
ZOOM_CANDIDATES = (21, 20, 19)


# ---------- 純函式（可離線測） ----------

def is_blank(img) -> bool:
    """Google 在該 zoom 沒影像時回傳近乎均勻的灰底磚；用灰階標準差判斷。"""
    import numpy as np
    g = np.asarray(img.convert("L"), dtype=np.float32)
    return float(g.std()) < BLANK_STD_THRESHOLD


def lock_size(out_dir, size_m: float) -> dict:
    """確認鎖定：把 out_dir 內所有變體裁中央到 size_m×size_m，更新並鎖定 meta.json。

    不同變體像素密度不同（clean 是 raw 的 2x），所以裁切邊長依各自實際寬度**按比例**算，
    保證每個變體涵蓋同一個公尺範圍。鎖定後 meta.locked=True，再鎖或再改都拒絕——
    這組 size_m/px_per_meter 是後續標註（G-projection）的座標系，改了座標全跑掉。
    """
    from PIL import Image
    out_dir = Path(out_dir)
    meta_path = out_dir / "meta.json"
    meta = json.loads(meta_path.read_text())
    if meta.get("locked"):
        raise ValueError("此地點已鎖定，要改大小請重新擷取")
    ppm = float(meta["px_per_meter"])
    raw_w = int(meta["img_w"])
    coverage = raw_w / ppm
    if not (0 < size_m <= coverage + 1e-6):
        raise ValueError(f"size_m 必須在 (0, {coverage:.1f}] 公尺內（目前 {size_m}）；"
                         f"更大要降 zoom 重抓")

    side_raw = round(size_m * ppm)
    for name in VARIANTS:
        p = out_dir / name
        if not p.exists():
            continue
        img = Image.open(p).convert("RGB")
        w, h = img.size
        # 按此變體與 raw 的像素比例換算邊長；genai 若改了長寬比就無法保證，直接拒絕
        if abs(w / h - raw_w / meta["img_h"]) > 1e-3:
            raise ValueError(f"{name} 長寬比與 raw 不符（{w}×{h}），無法安全裁切")
        side = round(side_raw * w / raw_w)
        cx, cy = w // 2, h // 2
        half = side // 2
        img.crop((cx - half, cy - half, cx - half + side, cy - half + side)).save(p)

    meta.update({
        "size_m": float(size_m),
        "img_w": side_raw,
        "img_h": side_raw,
        "locked": True,
    })
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


# ---------- 抓圖編排 ----------

def capture_best_zoom(lat: float, lon: float, code: str, want_zoom: int | None = None) -> dict:
    """由高到低試 zoom，跳過空白圖磚；整張 1280² 不裁（大小之後由使用者在前端決定）。"""
    import io
    import urllib.request
    from PIL import Image
    import map_capture

    key = map_capture.load_google_key()
    zooms = (want_zoom,) if want_zoom else ZOOM_CANDIDATES
    last_err = None
    for z in zooms:
        url = ("https://maps.googleapis.com/maps/api/staticmap"
               f"?center={lat},{lon}&zoom={z}&size=640x640&scale=2&maptype=satellite&key={key}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            ct = resp.headers.get("content-type", "")
            data = resp.read()
        if "image" not in ct:
            last_err = f"Static API 沒回傳圖片（{ct}）：{data[:200]!r}"
            continue
        img = Image.open(io.BytesIO(data)).convert("RGB")
        if is_blank(img):
            last_err = f"zoom {z} 無影像（空白圖磚）"
            print(f"  {last_err}，降一級")
            continue
        meta = map_capture.finish_capture(img, lat, lon, code, z, 2, size_m=None)
        skipped = [zz for zz in zooms if zz > z]
        meta["zoom_probe"] = (f"zoom {skipped} 無影像，採用 {z}" if skipped else f"zoom {z}")
        return meta
    raise RuntimeError(last_err or "所有 zoom 都失敗")


def run_capture(lat, lon, code, want_zoom=None) -> dict:
    validate_code(code)
    capture_best_zoom(lat, lon, code, want_zoom)
    return read_state(code)


def run_enhance(code, genai=False, upscale=2) -> dict:
    """對目前的 raw 去車銳化（＋選配 genai）。Gemini 偵測有隨機性，可重跑到滿意為止。"""
    import image_enhance
    validate_code(code)
    image_enhance.enhance(code, upscale=upscale)      # 會把 decar_status 寫進 meta、保留 locked
    if genai:
        try:
            image_enhance.genai_enhance(code, style_ref="refs/road_style_ref.png")
        except SystemExit as e:      # genai_enhance 用 sys.exit 報錯，不能讓它殺掉 server
            print(f"  genai 失敗：{e}")
    return read_state(code)


def run_lock(code, size_m, genai=False, upscale=2) -> dict:
    """鎖定大小 → 對裁好的 raw 去車銳化 → 選配 genai HD。"""
    validate_code(code)
    lock_size(OUTPUT_DIR / code, size_m)
    return run_enhance(code, genai=genai, upscale=upscale)


def read_state(code: str) -> dict:
    out_dir = OUTPUT_DIR / code
    meta = json.loads((out_dir / "meta.json").read_text())
    from PIL import Image
    variants = {}
    for name in VARIANTS:
        p = out_dir / name
        if p.exists():
            w, h = Image.open(p).size
            variants[name] = {"url": f"/output/{code}/{name}?v={p.stat().st_mtime_ns}",
                              "w": w, "h": h}
    return {"code": code, "meta": meta, "variants": variants,
            "coverage_m": meta["img_w"] / meta["px_per_meter"]}


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  [http] " + fmt % args + "\n")

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, ctype: str):
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        if path.startswith("/output/"):
            parts = path[len("/output/"):].split("/")
            if len(parts) == 2:
                try:
                    validate_code(parts[0])
                except ValueError:
                    return self.send_error(400)
                if parts[1] in VARIANTS:
                    return self._file(OUTPUT_DIR / parts[0] / parts[1], "image/png")
            return self.send_error(404)
        if path.startswith("/api/state/"):
            code = path[len("/api/state/"):]
            try:
                validate_code(code)
                return self._json(read_state(code))
            except (ValueError, FileNotFoundError) as e:
                return self._json({"error": str(e)}, 404)
        self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        try:
            if self.path == "/api/capture":
                st = run_capture(float(body["lat"]), float(body["lon"]), body["code"],
                                 want_zoom=body.get("zoom"))
                return self._json(st)
            if self.path == "/api/enhance":
                return self._json(run_enhance(body["code"], genai=bool(body.get("genai"))))
            if self.path == "/api/lock":
                return self._json(run_lock(body["code"], float(body["size_m"]),
                                           genai=bool(body.get("genai"))))
            return self._json({"error": "unknown endpoint"}, 404)
        except (ValueError, KeyError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:      # noqa: BLE001 — server 不能因單次請求死掉
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def main():
    ap = argparse.ArgumentParser(description="底圖自動化網頁")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    import pipeline
    pipeline.load_env()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[webapp] http://{args.host}:{args.port}/   (Ctrl-C 結束)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
