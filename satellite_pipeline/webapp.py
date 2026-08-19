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
sys.path.insert(0, str(SCRIPTS_DIR))

from common import validate_code  # noqa: E402
from paths import (               # noqa: E402  所有路徑的唯一事實來源
    LOCATION_ROOT, OUTPUT_DIR, TRAFFICLAB_DIR, UPLOAD_DIR, WEB_DIR,
)

VARIANTS = ("sat_raw.png", "sat_clean.png", "sat_genai.png")
BLANK_STD_THRESHOLD = 6.0     # 灰階標準差低於此值視為「無影像的空白圖磚」
ZOOM_CANDIDATES = (21, 20, 19)

# Laplacian 變異數低於此值＝該 zoom 沒有真實影像（Google 拿低 zoom 的圖放大充數）。
# 實測（2026-08-19）：正常永康路口 z21 = 119；無影像的農田 z21 = 15.6（同點 z20 = 105、
# z18 = 317，證明資訊量其實只到 z18）。合成對照：銳利雜訊 48510、降 1/4 再放大 16.5、純色 0。
# 60 落在 119 與 16 中間，兩邊都有 2× 以上餘裕。
DETAIL_MIN = 60.0


# ---------- 純函式（可離線測） ----------

def is_blank(img) -> bool:
    """Google 在該 zoom 沒影像時回傳近乎均勻的灰底磚；用灰階標準差判斷。"""
    import numpy as np
    g = np.asarray(img.convert("L"), dtype=np.float32)
    return float(g.std()) < BLANK_STD_THRESHOLD


def detail_score(img) -> float:
    """影像的高頻資訊量（Laplacian 變異數）。放大充數的圖沒有高頻，分數會塌掉。"""
    import cv2
    import numpy as np
    g = np.asarray(img.convert("L"), dtype=np.float32)
    return float(cv2.Laplacian(g, cv2.CV_32F).var())


def looks_upsampled(img) -> bool:
    """該 zoom 沒有真實影像嗎？

    這是 `is_blank` 抓不到的失敗模式：Google 不是回空白磚，而是把低 zoom 的圖放大，
    尺寸與 px_per_meter 看起來完全正常、灰階 std 也過關，只是**糊的**。
    實例：使用者把緯度 23.026901 打成 23.062901，落在 4km 外的農田，
    z21 銳利度 15.6（同點 z20 是 105）——舊版靜默給出這張圖當底圖。
    """
    return detail_score(img) < DETAIL_MIN


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


def best_zoom_for_size(lat: float, size_m: float,
                       candidates=ZOOM_CANDIDATES) -> int:
    """能裝下 size_m 的**最高** zoom（＝解析度最好的那個）。

    Static API 單張是 1280px，所以 zoom z 的涵蓋範圍＝1280 / px_per_meter(lat, z)。
    全部都裝不下就回最低的（使用者要的範圍超過單張極限，只能給最大的那張）。
    """
    import map_capture
    for z in sorted(candidates, reverse=True):
        if 1280 / map_capture.px_per_meter(lat, z, 2) >= size_m:
            return z
    return min(candidates)


# ---------- 交付 trafficlab 標註 GUI（③）----------

def extract_first_frame(video: Path, dst_png: Path) -> tuple[int, int]:
    """影片首幀 → PNG（trafficlab 的 cctv_<code>.png）。回傳 (w, h)。"""
    import cv2
    cap = cv2.VideoCapture(str(video))
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise ValueError(f"讀不到影片首幀：{video.name}")
    cv2.imwrite(str(dst_png), frame)
    return frame.shape[1], frame.shape[0]


def resolve_upload(code: str, name, must_exist: bool = False):
    """把用戶端給的檔名解析成上傳目錄內的路徑；跨出目錄就拒絕。

    不能直接 `UPLOAD_DIR / code / name`：
      - `name` 是絕對路徑時 pathlib 會**整個丟掉前綴**（`Path("/a/b") / "/tmp/x"` → `/tmp/x`）
      - `"../"` 一樣跳得出去
    兩者都會讓 `/api/handoff` 把機器上任意檔案複製進 repo（cctv 那條還會轉存成 PNG
    並經 `/location/...` 對外提供）。所以只收「單一檔名」，再用 resolve 覆核一次。
    """
    if not name:
        return None
    validate_code(code)
    base = (UPLOAD_DIR / code).resolve()
    candidate = (base / str(name)).resolve()
    if Path(str(name)).name != str(name) or not candidate.is_relative_to(base):
        raise ValueError(f"檔名不合法：{name!r}（只接受上傳目錄內的單一檔名）")
    # 上傳檔可能已被清掉（換 code、清暫存、重開機）。這裡自己擋下並講人話，
    # 不要讓 shutil/PIL 的 FileNotFoundError 把內部路徑吐到使用者面前。
    if must_exist and not candidate.is_file():
        raise ValueError(f"找不到先前上傳的「{name}」，可能已被清除——請重新選一次檔案")
    return candidate


def _file_stamp(path: Path) -> str:
    """用檔案自己的 mtime 當停用標記，比當下時間更能說明「那份是什麼時候標的」。"""
    from datetime import datetime
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d-%H%M%S")


def handoff_to_trafficlab(out_dir, loc_root, code: str, video=None, cctv_image=None,
                          force: bool = False) -> dict:
    """把 ② 鎖定的底圖擺成 trafficlab 標註 GUI 認得的樣子：

        location/<code>/sat_<code>.png        ← sat_clean（忠實版，位移 0.00m；絕不拿 genai）
        location/<code>/sat_meta_<code>.json  ← 已知 px/m、lat/lon、size_m（DistStage 可直接採用）
        location/<code>/cctv_<code>.png       ← 影片首幀或使用者給的截圖（選配）
        location/<code>/footage/<video>       ← 影片本體（選配，給 Inference 分頁）

    px/m 要乘上 sat_clean 相對 raw 的放大倍率（它是 2x），否則標在它上面的座標會差一倍。
    已有 G_projection_<code>.json 就拒絕（覆蓋 sat 會讓既有標註的座標全失效），force 才放行。
    """
    import shutil
    from PIL import Image

    out_dir, loc_root = Path(out_dir), Path(loc_root)
    validate_code(code)
    meta = json.loads((out_dir / "meta.json").read_text())
    if not meta.get("locked"):
        raise ValueError("底圖尚未鎖定——先按「鎖定」讓 size_m / px_per_meter 定案再交付")
    # 交付順序：有增強版就用（幾何仍忠實），否則用原圖。**永遠不用 sat_genai**——
    # 它是生圖重畫，位移中位數 0.20m，標在上面等於把誤差烙進 G-projection。
    src = next((out_dir / n for n in ("sat_clean.png", "sat_raw.png") if (out_dir / n).exists()), None)
    if src is None:
        raise ValueError("找不到底圖（sat_clean.png / sat_raw.png 都不在）")

    dst_dir = loc_root / code
    gproj = dst_dir / f"G_projection_{code}.json"
    if gproj.exists() and not force:
        raise ValueError(f"{gproj.name} 已存在——這個地點已經標註過，覆蓋底圖會讓既有座標失效。"
                         f"要重來請明示 force")
    dst_dir.mkdir(parents=True, exist_ok=True)
    written = []

    if gproj.exists():
        # force：底圖要被換掉，舊 G_projection 的像素座標就失效了。**不能留在原地**——
        # trafficlab 的 pick_stage 會自動載入同名檔、網頁標註也會把錨點帶回來，
        # 兩邊都會拿舊座標配新底圖而且不報錯。改名保留，讓人還能回頭查。
        stamp = _file_stamp(gproj)
        superseded = gproj.with_suffix(f".json.superseded.{stamp}")
        gproj.rename(superseded)
        written.append(superseded.name)
        print(f"  舊標註已停用：{superseded.name}")

    shutil.copy2(src, dst_dir / f"sat_{code}.png")
    written.append(f"sat_{code}.png")

    factor = Image.open(src).size[0] / meta["img_w"]
    sat_meta = {
        "location_code": code,
        "sat_variant": src.name,
        # 去車狀態要跟著走：sat_clean 可能是「想去車但沒 key／失敗」的產物，
        # 下游只看到一張圖會誤以為路面已經清乾淨
        "decar_status": meta.get("decar_status"),
        "vehicles_removed": meta.get("vehicles_removed"),
        "px_per_meter": meta["px_per_meter"] * factor,
        "px_per_meter_raw": meta["px_per_meter"],
        "upscale_factor": factor,
        "size_m": meta["size_m"],
        "lat": meta["lat"], "lon": meta["lon"], "zoom": meta["zoom"],
        "source": "satellite_pipeline/webapp handoff",
        "note": "px_per_meter 已含 sat_clean 的放大倍率；DistStage 可直接採用，不必再量兩點",
    }
    (dst_dir / f"sat_meta_{code}.json").write_text(json.dumps(sat_meta, indent=2, ensure_ascii=False))
    written.append(f"sat_meta_{code}.json")

    if video:
        video = Path(video)
        (dst_dir / "footage").mkdir(exist_ok=True)
        shutil.copy2(video, dst_dir / "footage" / video.name)
        written.append(f"footage/{video.name}")
        extract_first_frame(video, dst_dir / f"cctv_{code}.png")
        written.append(f"cctv_{code}.png")
    elif cctv_image:
        Image.open(cctv_image).convert("RGB").save(dst_dir / f"cctv_{code}.png")
        written.append(f"cctv_{code}.png")

    has_cctv = (dst_dir / f"cctv_{code}.png").exists()
    return {"location_dir": str(dst_dir), "written": written, "sat_meta": sat_meta,
            "has_cctv": has_cctv,
            # 標註要兩張圖對點；只有底圖是標不了的，先講清楚而不是讓人點進去才發現
            "annotation_ready": has_cctv}


def _qt_works(py: Path) -> bool:
    """這個直譯器能不能真的開視窗。.venv-pifpaf 有 PyQt5 但缺 cocoa platform plugin，
    直接拿它開 GUI 只會靜默失敗（Popen 不會回報）。"""
    import subprocess
    try:
        r = subprocess.run([str(py), "-c",
                            "from PyQt5.QtWidgets import QApplication; QApplication([])"],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def launch_trafficlab_gui() -> dict:
    """開 trafficlab 的 PyQt5 標註 GUI（main.py），挑第一個 Qt 真的能用的直譯器。"""
    import subprocess
    candidates = [Path(sys.executable), TRAFFICLAB_DIR / ".venv-pifpaf" / "bin" / "python"]
    py = next((c for c in candidates if c.exists() and _qt_works(c)), None)
    if py is None:
        raise RuntimeError("找不到能開 Qt 視窗的 python（PyQt5 未裝或缺 platform plugin），"
                           "請在 trafficlab-project 手動跑 python3 main.py")
    proc = subprocess.Popen([str(py), "main.py"], cwd=str(TRAFFICLAB_DIR),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    return {"pid": proc.pid, "python": str(py), "cwd": str(TRAFFICLAB_DIR)}


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

        # 細節不足＝該 zoom 是放大充數。不自動降級（真的平坦的路口會被誤判成一路降到底），
        # 改成寫進 meta 讓 ② 頁面警示，使用者按「降 zoom 重抓」自己決定。
        score = detail_score(img)
        meta["detail_score"] = round(score, 1)
        meta["detail_ok"] = score >= DETAIL_MIN
        if score < DETAIL_MIN:
            print(f"  警告：zoom {z} 細節不足（{score:.1f} < {DETAIL_MIN}），"
                  f"該處可能沒有此 zoom 的影像，是低 zoom 放大充數")
        _write_meta(code, meta)
        return meta
    raise RuntimeError(last_err or "所有 zoom 都失敗")


def _write_meta(code: str, meta: dict) -> None:
    (OUTPUT_DIR / code / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False))


def run_capture(lat, lon, code, want_zoom=None) -> dict:
    validate_code(code)
    capture_best_zoom(lat, lon, code, want_zoom)
    return read_state(code)


def run_enhance(code, genai=False, upscale=2, decar=False) -> dict:
    """對目前的 raw 銳化 2x（選配去車、選配 genai）。

    decar 預設 False（使用者決定：標註對應點不需要乾淨路面，去車反而多一層 Gemini 隨機性）。
    開了去車時 Gemini 偵測有隨機性，可重跑到滿意為止。
    """
    import image_enhance
    validate_code(code)
    image_enhance.enhance(code, upscale=upscale, decar=decar)   # 寫 decar_status、保留 locked
    if genai:
        try:
            image_enhance.genai_enhance(code, style_ref="refs/road_style_ref.png")
        except SystemExit as e:      # genai_enhance 用 sys.exit 報錯，不能讓它殺掉 server
            print(f"  genai 失敗：{e}")
    return read_state(code)


def run_genai(code, provider=None) -> dict:
    """只跑 LLM 生圖高清化，不重跑去車。

    分開的理由：去車每次結果都不同（Gemini 偵測有隨機性），使用者只想要 AI 高清版時
    不該連帶把已經滿意的 sat_clean 重抽一次。
    """
    import image_enhance
    validate_code(code)
    kwargs = {"style_ref": "refs/road_style_ref.png"}
    if provider:
        kwargs["provider"] = provider
    try:
        image_enhance.genai_enhance(code, **kwargs)
    except SystemExit as e:      # genai_enhance 用 sys.exit 報錯，不能讓它殺掉 server
        raise RuntimeError(f"生圖失敗：{e}") from e
    return read_state(code)


def run_lock(code, size_m, genai=False, upscale=2, decar=False) -> dict:
    """鎖定大小 → 對裁好的 raw 去車銳化 → 選配 genai HD。

    鎖定前先確認目前這張是**能裝下 size_m 的最高 zoom**。使用者為了看更大範圍按過
    「降 zoom 重抓」之後，常常最終選的尺寸其實在高 zoom 也放得下——不重抓的話就白白
    損失一半解析度（實例：38m 鎖在 zoom 20 得 553px，zoom 21 是 1106px）。
    """
    validate_code(code)
    out_dir = OUTPUT_DIR / code
    meta = json.loads((out_dir / "meta.json").read_text())
    best = best_zoom_for_size(meta["lat"], size_m)
    upgraded = None
    if best > meta["zoom"]:
        print(f"  {size_m}m 在 zoom {best} 放得下，自動升級（原 zoom {meta['zoom']}）")
        new_meta = capture_best_zoom(meta["lat"], meta["lon"], code, want_zoom=best)
        if new_meta.get("detail_ok", True):
            upgraded = {"from": meta["zoom"], "to": best}
        else:
            # 高 zoom 沒有真實影像（放大充數），退回原本那張
            print(f"  zoom {best} 細節不足，退回 zoom {meta['zoom']}")
            capture_best_zoom(meta["lat"], meta["lon"], code, want_zoom=meta["zoom"])

    lock_size(out_dir, size_m)
    # 鎖定＝裁切定案，不做任何影像加工。去車／銳化／AI 高清都是鎖定後的**選配**動作
    # （使用者決定：標對應點不需要乾淨路面，每多一道加工就多一層隨機性與等待）。
    st = run_enhance(code, genai=genai, upscale=upscale, decar=decar) if (decar or genai) \
        else read_state(code)
    if upgraded:
        st["zoom_upgraded"] = upgraded
    return st


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

    def _upload(self, n: int):
        """影片／截圖以 raw body 上傳（不走 multipart：stdlib 3.13 起沒有 cgi）。"""
        from urllib.parse import parse_qs, urlsplit
        q = parse_qs(urlsplit(self.path).query)
        try:
            code = validate_code(q.get("code", [""])[0])
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        name = Path(q.get("name", [""])[0]).name      # 去路徑，只留檔名
        if not name or not name.lower().endswith((".mp4", ".mov", ".png", ".jpg", ".jpeg")):
            return self._json({"error": "只接受 mp4/mov 影片或 png/jpg 截圖"}, 400)
        dst = UPLOAD_DIR / code / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        remaining = n
        with open(dst, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        kind = "video" if name.lower().endswith((".mp4", ".mov")) else "cctv_image"
        return self._json({"name": name, "bytes": n - remaining, "kind": kind})

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
        if path.startswith("/location/"):
            parts = path[len("/location/"):].split("/")
            if len(parts) == 2:
                try:
                    validate_code(parts[0])
                except ValueError:
                    return self.send_error(400)
                if parts[1] in (f"sat_{parts[0]}.png", f"cctv_{parts[0]}.png"):
                    return self._file(LOCATION_ROOT / parts[0] / parts[1], "image/png")
            return self.send_error(404)
        if path == "/annotate" or path == "/annotate.html":
            return self._file(WEB_DIR / "annotate.html", "text/html; charset=utf-8")
        if path.startswith("/api/annotation/"):
            code = path[len("/api/annotation/"):]
            try:
                validate_code(code)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            loc = LOCATION_ROOT / code
            sm = loc / f"sat_meta_{code}.json"
            gp = loc / f"G_projection_{code}.json"
            if not sm.exists():
                return self._json({"error": f"{code} 尚未交付底圖"}, 404)
            return self._json({
                "code": code,
                "sat_meta": json.loads(sm.read_text()),
                "sat_url": f"/location/{code}/sat_{code}.png",
                "cctv_url": (f"/location/{code}/cctv_{code}.png"
                             if (loc / f"cctv_{code}.png").exists() else None),
                "existing": json.loads(gp.read_text()) if gp.exists() else None,
            })
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
        if self.path.startswith("/api/upload"):
            return self._upload(n)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        try:
            if self.path == "/api/capture":
                st = run_capture(float(body["lat"]), float(body["lon"]), body["code"],
                                 want_zoom=body.get("zoom"))
                return self._json(st)
            if self.path == "/api/solve":
                import annotate
                H, err = annotate.solve_homography(body["pairs"])
                return self._json({"H": H, "error": err})
            if self.path == "/api/save_annotation":
                import annotate
                code = validate_code(body["code"])
                loc = LOCATION_ROOT / code
                if not loc.is_dir():
                    raise ValueError(f"{code} 還沒交付底圖到 location/，先完成鎖定")
                meta = json.loads((OUTPUT_DIR / code / "meta.json").read_text())
                sat_meta_path = loc / f"sat_meta_{code}.json"
                ppm = json.loads(sat_meta_path.read_text())["px_per_meter"] \
                    if sat_meta_path.exists() else meta["px_per_meter"]
                path = annotate.save_g_projection(
                    loc, code, body["pairs"], px_per_meter=ppm,
                    cctv_path=f"cctv_{code}.png", sat_path=f"sat_{code}.png",
                    cctv_size=body.get("cctv_size"), sat_size=body.get("sat_size"))
                return self._json({"path": str(path), "px_per_meter": ppm,
                                   "pairs": len(body["pairs"])})
            if self.path == "/api/handoff":
                code = validate_code(body["code"])
                video = resolve_upload(code, body.get("video"), must_exist=True)
                cctv = resolve_upload(code, body.get("cctv_image"), must_exist=True)
                info = handoff_to_trafficlab(OUTPUT_DIR / code, LOCATION_ROOT, code,
                                             video=video, cctv_image=cctv,
                                             force=bool(body.get("force")))
                if body.get("launch"):
                    info["launched"] = launch_trafficlab_gui()
                return self._json(info)
            if self.path == "/api/launch_gui":
                return self._json(launch_trafficlab_gui())
            if self.path == "/api/genai":
                return self._json(run_genai(body["code"], body.get("provider")))
            if self.path == "/api/enhance":
                return self._json(run_enhance(body["code"], genai=bool(body.get("genai")),
                                              decar=bool(body.get("decar"))))
            if self.path == "/api/lock":
                return self._json(run_lock(body["code"], float(body["size_m"]),
                                           genai=bool(body.get("genai")),
                                           decar=bool(body.get("decar"))))
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
