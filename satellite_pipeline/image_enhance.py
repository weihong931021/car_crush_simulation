#!/usr/bin/env python3
"""
image_enhance.py — 衛星圖去車 + 銳化/高清化

做法（避免 Gemini 重畫整張會幻想假道路的問題）：
    1. Gemini 只「偵測車輛框」回傳 JSON bbox（不重畫圖）
    2. cv2.inpaint 依 bbox 填補車輛區域（只填車，不動其他）
    3. PIL UnsharpMask 銳化 + 2x 放大高清化

Gemini 失敗（無 key / 配額不足）時 fallback：只銳化，不去車。

用法：
    python3 image_enhance.py --code tainan_yongkang
輸出：output/{code}/sat_clean.png
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPTS_DIR / "output"

GEMINI_MODEL = "gemini-2.5-flash"   # 視覺偵測用；2.0 已停用
DETECT_PROMPT = (
    "This is an aerial satellite top-down view of a road intersection. "
    "Identify ALL vehicles (cars, trucks, motorcycles, buses, vans, scooters). "
    'Return ONLY a JSON array, no other text: '
    '[{{"x1":int,"y1":int,"x2":int,"y2":int,"type":"car"}}]. '
    "Coordinates are pixel positions in the image. Image size: {w}x{h} pixels."
)


def load_gemini_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    env = SCRIPTS_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY=") and "=" in line:
                return line.split("=", 1)[1].strip()
    return None


def detect_vehicles(img_bytes: bytes, w: int, h: int, key: str) -> list[dict]:
    """用 Gemini 偵測車輛 bbox，回傳 list of {x1,y1,x2,y2,type}。失敗回 []。"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Content(parts=[
            types.Part(inline_data=types.Blob(data=img_bytes, mime_type="image/png")),
            types.Part(text=DETECT_PROMPT.format(w=w, h=h)),
        ])],
    )
    text = resp.text or ""
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        boxes = json.loads(m.group(0))
        return [b for b in boxes if all(k in b for k in ("x1", "y1", "x2", "y2"))]
    except json.JSONDecodeError:
        return []


GENAI_MODEL = "gemini-3.1-flash-image"
GENAI_PROMPT = (
    "Clean up and sharpen this aerial/satellite top-down photo of a road.\n"
    "GOALS:\n"
    "1. Render the road surface as REALISTIC ASPHALT: a dark grey asphalt colour like "
    "a real city road, with a clearly ROUGH, grainy, coarse asphalt texture (visible "
    "aggregate / gritty surface) — NOT smooth, NOT a flat solid shape or cut-out. "
    "Make the whole road one consistent asphalt material/tone, but clean: remove stains, "
    "oil patches, tyre marks and repair scars while keeping the rough natural asphalt "
    "look (photorealistic, matte, top-down).\n"
    "2. Make the ROAD EDGES (kerb lines / road outline) crisp and well defined.\n"
    "3. Markings: be MINIMAL and restrained. Keep ONLY the markings that are clearly and "
    "unmistakably present, rendered plain white. Do NOT bold, brighten, thicken, multiply, "
    "extend or invent any marking. When in doubt, leave it out. Fewer markings is better.\n"
    "HARD CONSTRAINTS — do NOT violate:\n"
    "- If a marking is blurry or ambiguous (motorcycle waiting box, an unreadable "
    "arrow), leave it faint or omit it. NEVER guess, invent, duplicate or redraw.\n"
    "- Keep the EXACT same road layout, shapes and positions of every road, kerb, "
    "building, tree and structure. Do not add roundabouts, plazas, parks or buildings.\n"
    "- Only the road/asphalt area is cleaned; do NOT repaint buildings, vegetation "
    "or pavement.\n"
    "Treat this as a clean-up + deblur pass on the existing image, not a redraw."
)

STYLE_REF_NOTE = (
    "STYLE REFERENCE: The SECOND image is a real high-quality drone photo of a road. "
    "Borrow ONLY its ASPHALT MATERIAL look — the dark, rough, grainy asphalt surface "
    "texture and drone-photo sharpness — and apply that to the road in the FIRST image. "
    "Do NOT copy the reference's markings, layout, shapes or content. Keep the FIRST "
    "image's exact road layout, geometry, buildings and marking positions, and keep its "
    "markings minimal/faithful (do not add bold markings from the reference)."
)


def genai_enhance(code: str, key: str | None = None,
                  src_name: str = "sat_raw.png", temperature: float = 0.4,
                  style_ref: str | None = None) -> Path:
    """用 Gemini 圖像生成對（已去車的）衛星圖做 HD 化，輸出 sat_genai.png。

    style_ref：可選的風格參考圖路徑（例如真實空拍馬路），會一起餵給 Gemini，
    要它把路面材質/標線質感做成參考圖那種風格（但保留衛星圖的佈局）。
    """
    import io
    from google import genai
    from google.genai import types
    from PIL import Image

    out_dir = OUTPUT_DIR / code
    src = out_dir / src_name
    if not src.exists():
        src = out_dir / "sat_raw.png"
    if not src.exists():
        sys.exit(f"ERROR: 找不到來源圖（先跑 map_capture / enhance）")

    key = key or load_gemini_key()
    if not key:
        sys.exit("ERROR: genai 需要 GEMINI_API_KEY")

    parts = [types.Part(inline_data=types.Blob(data=src.read_bytes(), mime_type="image/png"))]
    prompt = GENAI_PROMPT
    if style_ref:
        ref_path = Path(style_ref)
        if not ref_path.is_absolute():
            ref_path = SCRIPTS_DIR / style_ref
        if ref_path.exists():
            parts.append(types.Part(inline_data=types.Blob(
                data=ref_path.read_bytes(), mime_type="image/png")))
            prompt = GENAI_PROMPT + "\n\n" + STYLE_REF_NOTE
            print(f"  風格參考圖：{ref_path.name}")
        else:
            print(f"  警告：風格參考圖不存在 {ref_path}，忽略")

    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=GENAI_MODEL,
        contents=[types.Content(parts=parts + [types.Part(text=prompt)])],
        config=types.GenerateContentConfig(
            response_modalities=["image", "text"],
            temperature=temperature,
        ),
    )

    out_path = out_dir / "sat_genai.png"
    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image"):
            img = Image.open(io.BytesIO(part.inline_data.data))
            img.save(out_path)
            print(f"  Gemini HD 生成（temp={temperature}, 來源={src.name}）→ {out_path} {img.size}")
            return out_path
    sys.exit("ERROR: Gemini 沒回傳圖片")


def enhance(code: str, key: str | None = None, upscale: int = 2) -> Path:
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter

    out_dir = OUTPUT_DIR / code
    raw_path = out_dir / "sat_raw.png"
    if not raw_path.exists():
        sys.exit(f"ERROR: 找不到 {raw_path}（先跑 map_capture.py）")

    key = key or load_gemini_key()
    pil = Image.open(raw_path).convert("RGB")
    w, h = pil.size
    bgr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    # --- Step 1+2: Gemini 偵測 + cv2 inpaint 去車 ---
    n_removed = 0
    if key:
        try:
            boxes = detect_vehicles(raw_path.read_bytes(), w, h, key)
            if boxes:
                mask = np.zeros((h, w), dtype=np.uint8)
                pad = 8
                for b in boxes:
                    x1 = max(0, int(b["x1"]) - pad)
                    y1 = max(0, int(b["y1"]) - pad)
                    x2 = min(w, int(b["x2"]) + pad)
                    y2 = min(h, int(b["y2"]) + pad)
                    mask[y1:y2, x1:x2] = 255
                bgr = cv2.inpaint(bgr, mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)
                n_removed = len(boxes)
                print(f"  Gemini 偵測 {n_removed} 台車 → cv2 inpaint 去除")
            else:
                print("  Gemini 未偵測到車輛（或回傳空），跳過去車")
        except Exception as e:
            print(f"  Gemini 去車失敗（{type(e).__name__}），fallback 只銳化：{e}")
    else:
        print("  無 GEMINI_API_KEY，fallback 只銳化（不去車）")

    # --- Step 3: 銳化 + 高清化 ---
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    out = Image.fromarray(rgb)
    if upscale > 1:
        out = out.resize((w * upscale, h * upscale), Image.LANCZOS)
    out = out.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=2))

    clean_path = out_dir / "sat_clean.png"
    out.save(clean_path)

    # 更新 meta：記錄去車數 + 增強後尺寸
    meta_path = out_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["vehicles_removed"] = n_removed
        meta["enhanced_px"] = out.size[0]
        meta["upscale"] = upscale
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    print(f"  Saved: {clean_path}  ({out.size[0]}x{out.size[1]})")
    return clean_path


def main():
    ap = argparse.ArgumentParser(description="衛星圖去車 + 銳化高清化")
    ap.add_argument("--code", required=True)
    ap.add_argument("--upscale", type=int, default=2, help="放大倍率，預設 2")
    ap.add_argument("--genai", action="store_true",
                    help="額外用 Gemini 圖像生成做 HD 化（在去車結果上），輸出 sat_genai.png")
    ap.add_argument("--genai-temp", type=float, default=0.4, help="genai temperature，預設 0.4")
    ap.add_argument("--style-ref", default="refs/road_style_ref.png",
                    help="風格參考圖（真實空拍馬路）；設空字串關閉")
    args = ap.parse_args()
    print(f"[image_enhance] code={args.code}")
    enhance(args.code, upscale=args.upscale)
    if args.genai:
        print("[image_enhance] Gemini HD 生成…")
        genai_enhance(args.code, temperature=args.genai_temp,
                      style_ref=args.style_ref or None)
    print("[image_enhance] Done.")


if __name__ == "__main__":
    main()
