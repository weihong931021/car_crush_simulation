#!/usr/bin/env python3
"""
image_enhance.py — 衛星圖去車 + 銳化/高清化

做法（避免 Gemini 重畫整張會幻想假道路的問題）：
    1. Gemini 只「偵測車輛框」回傳 JSON bbox（不重畫圖）
    2. cv2.inpaint 依 bbox 填補車輛區域（只填車，不動其他）
    3. PIL UnsharpMask 銳化 + 2x 放大高清化

Gemini 失敗（無 key / 配額不足）時 fallback：只銳化，不去車。

兩支 API、兩個 key，分工不同：
    GEMINI_API_KEY  → 去車偵測（gemini-2.5-flash 只回 bbox JSON，**不生圖**）
    OPENAI_API_KEY  → `--genai` 生圖 HD 化（gpt-image-2），2026-08-17 起從 Gemini 換過來

用法：
    python3 image_enhance.py --code tainan_yongkang
    python3 image_enhance.py --code tainan_yongkang --genai --genai-quality low
輸出：output/{code}/sat_clean.png（忠實）、sat_genai.png（--genai，重畫）
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPTS_DIR))
from common import validate_code  # noqa: E402
from paths import OUTPUT_DIR      # noqa: E402  路徑集中在 paths.py

GEMINI_MODEL = "gemini-2.5-flash"   # 視覺偵測用；2.0 已停用
DETECT_PROMPT = (
    "This is an aerial satellite top-down view of a road intersection. "
    "Identify ALL vehicles (cars, trucks, motorcycles, buses, vans, scooters). "
    'Return ONLY a JSON array, no other text: '
    '[{{"x1":int,"y1":int,"x2":int,"y2":int,"type":"car"}}]. '
    "Coordinates are pixel positions in the image. Image size: {w}x{h} pixels."
)


def _load_key(name: str) -> str | None:
    """環境變數優先，其次 satellite_pipeline/.env。"""
    key = os.environ.get(name, "").strip()
    if key:
        return key
    env = SCRIPTS_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return None


def load_gemini_key() -> str | None:
    """去車偵測用（gemini-2.5-flash 只回 bbox JSON，不生圖）。"""
    return _load_key("GEMINI_API_KEY")


def load_openai_key() -> str | None:
    """生圖用（gpt-image-2）。"""
    return _load_key("OPENAI_API_KEY")


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


# --- 生圖（HD 化）：兩家並存，用 --genai-provider 切換 ------------------------
# 2026-08-17 實測（同一張 tainan_yongkang sat_raw.png、同 prompt、分塊相位相關）：
#
#   | 路徑                        | 位移中位數      | >10px | 全域相關 |
#   | sat_clean（不生圖）          | 0.0 px = 0.00 m |   0%  |  0.968  |
#   | gemini-3.1-flash-image      | 5.7 px = 0.20 m |  37%  |  0.876  |
#   | gpt-image-2                 | 8.6 px = 0.30 m |  47%  |  0.746  |
#
# **Gemini 比較忠於原圖**（使用者早先的印象「路不會被亂砍亂生」有數據支持），
# 所以預設仍是 Gemini；OpenAI 是可選路徑。兩者都會重寫幾何，只是程度不同——
# 承載座標的地面圖一律走 sat_clean，不要走這裡任何一條。
GENAI_PROVIDERS = ("gemini", "openai")
GENAI_PROVIDER_DEFAULT = "gemini"

GEMINI_GENAI_MODEL = "gemini-3.1-flash-image"
GEMINI_GENAI_TEMPERATURE = 0.4   # ≥0.5 會幻想假道路/廣場/公園

# 為何 OpenAI 這邊是 gpt-image-2 而不是更便宜的 gpt-image-1-mini：**只有它能指定任意輸出尺寸**
# （邊長 16 倍數、長邊 ≤3840、比例 ≤3:1、總像素 655,360–8,294,400）。
# gpt-image-1 / -mini 只吐 1024x1024、1024x1536、1536x1024 三種比例，衛星圖不是這三種，
# 送進去必被壓扁——而長寬比一變，px_per_meter 就失效。選型由這條約束決定，不是價格。
OPENAI_GENAI_MODEL = "gpt-image-2"
GENAI_QUALITY = "medium"        # OpenAI 專用：low 試 prompt、medium 預設、high 定稿
# gpt-image-2 token 單價（USD / 1M tokens），用來估每次花費
GENAI_PRICE_TEXT_IN = 5.00
GENAI_PRICE_IMAGE_IN = 8.00
GENAI_PRICE_IMAGE_OUT = 30.00
# gpt-image-2 的 size 硬限制
IMAGE_SIZE_MULTIPLE = 16
IMAGE_MAX_EDGE = 3840
IMAGE_MIN_PIXELS = 655_360
IMAGE_MAX_PIXELS = 8_294_400
IMAGE_MAX_ASPECT = 3.0

# 兩套 prompt，**預設 sharp**（2026-08-20 使用者看過對照後拍板：舊版最清楚，就用舊版）。
# 這是觀感決定，不是量測決定——量測站在 faithful 那邊，兩邊的代價都列在這裡：
#
#   （taipei_sogo 同一張 sat_raw，measure_genai_drift.py tile=128）
#   sharp    + gemini  0.15 m / >10px 39% / 全域相關 0.915   ← 現行預設，最「乾淨清楚」
#   sharp    + gpt-2   0.56 m / >10px 75% / 全域相關 0.345   ← 最差，勿用
#   faithful + gemini  0.11 m / >10px 21% / 全域相關 0.960   ← 像照片，但受 1024 天花板拖累
#   faithful + gpt-2   0.09 m / >10px 10% / 全域相關 0.952   ← 幾何最佳、質感偏版畫
#
# sharp 的已知代價（都是實測，不是推測；換 prompt 前先看懂你在買什麼）：
#   1. 標線被重畫成等寬純白向量色塊，還會無中生有（sogo 多出一個雙箭頭 ↔）
#   2. 只清路面 → 路面銳利而建物維持糊，兩者之間出現硬邊界
#   3. 非道路鋪面會被當成路：kaohsiung_wufu 的行人徒步區整片被改畫成柏油＋新斑馬線
#   4. 會刪東西：嘉義的攤販糊成斑塊、永康整排停放車輛消失、Google 浮水印被抹掉
#   5. 配 gpt-image-2 時標線會被誤讀成實體：sogo 的路面箭頭被畫成一排停放車輛
# 所以 sharp 產物只當**展示底圖**。座標一律走 enhance_file()／sat_clean（實測 0.00 m）。
#
# faithful 保留的理由：來源 >1024 時 Gemini 會先降到 1024 再放大回去（細節能量
# sogo 214→53、五福 318→56），那個情境下 faithful + gpt-image-2 才是唯一又清楚又不亂改的路。
# ⚠ faithful 有驗收漏洞：最後那句「寧可糊也不要改」讓「什麼都不做」在漂移指標上滿分，
#   指標分不出「忠實」與「沒動」（實測 temp 0.2 有一次幾乎沒動卻拿到最高相關）。
GENAI_PROMPT_SHARP = (
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

GENAI_PROMPT_FAITHFUL = (
    "This is a low-resolution satellite PHOTOGRAPH. Perform PHOTOGRAPHIC RESTORATION only: "
    "reduce blur and compression artefacts so that detail ALREADY PRESENT becomes legible.\n"
    "THIS IS NOT AN ILLUSTRATION TASK. The output must still read as a photograph of this "
    "exact place, from the same camera at the same moment.\n"
    "RULES:\n"
    "- Apply the SAME treatment to the whole frame. Do NOT single out the road for special "
    "treatment while leaving buildings, vegetation or pavement untouched — a visible boundary "
    "between a sharp region and a blurry region is a failure. (This does NOT mean making "
    "everything equally sharp: regions that were soft in the input stay relatively soft.)\n"
    "- Preserve every surface exactly as photographed: keep stains, patches, tyre marks, "
    "colour variation and wear. That is real detail, not noise to be cleaned away.\n"
    "- Do NOT draw outlines, kerb lines or edges that are not already visible as pixels.\n"
    "- Do NOT regularise road markings. If a stripe is uneven, faded, chipped or partly "
    "occluded in the input, it must stay uneven, faded, chipped and partly occluded in the "
    "output. Do not make stripes equal width, equal spacing or pure white.\n"
    "- Do NOT change the position, shape or size of anything.\n"
    "- Keep any watermark or attribution text exactly where it is. If such text is blurry, "
    "LEAVE IT BLURRY — do not re-typeset, sharpen or complete it into legible letters.\n"
    "If you cannot recover detail in a region, leave that region exactly as it is. "
    "A slightly blurry faithful result is CORRECT; a sharp reinterpreted result is WRONG."
)

GENAI_PROMPTS = {"sharp": GENAI_PROMPT_SHARP, "faithful": GENAI_PROMPT_FAITHFUL}
GENAI_PROMPT_DEFAULT = "sharp"
# 舊呼叫端相容：GENAI_PROMPT 一律指向現行預設
GENAI_PROMPT = GENAI_PROMPTS[GENAI_PROMPT_DEFAULT]

# 風格參考圖：sharp 需要它才是使用者驗收過的那個效果（那組對照就是帶 ref 跑的）；
# faithful 反而**不能**帶——它要求整張同一處理、完全保留原表面，與「把參考圖的柏油
# 質感套到道路」直接矛盾，會把硬邊界裝回來。genai_enhance() 會在 faithful 時自動丟棄。
STYLE_REF_DEFAULT = "refs/road_style_ref.png"

STYLE_REF_NOTE = (
    "STYLE REFERENCE: The SECOND image is a real high-quality drone photo of a road. "
    "Borrow ONLY its ASPHALT MATERIAL look — the dark, rough, grainy asphalt surface "
    "texture and drone-photo sharpness — and apply that to the road in the FIRST image. "
    "Do NOT copy the reference's markings, layout, shapes or content. Keep the FIRST "
    "image's exact road layout, geometry, buildings and marking positions, and keep its "
    "markings minimal/faithful (do not add bold markings from the reference)."
)


def plan_genai_size(w: int, h: int) -> tuple[int, int]:
    """把來源尺寸換成 gpt-image-2 允許的最接近畫布尺寸（長寬比誤差 <1%）。

    gpt-image-2 的 `size` 限制：兩邊都是 16 的倍數、長邊 ≤3840、長寬比 ≤3:1、
    總像素落在 655,360–8,294,400。回傳的只是「送進模型的畫布」——`genai_enhance()`
    拿回圖後會縮回來源原尺寸，所以下游的 px_per_meter 換算不受這個 snap 影響。
    """
    import math

    if w <= 0 or h <= 0:
        raise ValueError(f"來源尺寸無效 {w}x{h}")
    aspect = max(w, h) / min(w, h)
    if aspect > IMAGE_MAX_ASPECT:
        raise ValueError(f"來源長寬比 {aspect:.2f}:1 超過 gpt-image-2 上限 "
                         f"{IMAGE_MAX_ASPECT:g}:1——送進去會被裁掉或壓扁，請先自行裁圖")

    def snap(v: float) -> int:
        return max(IMAGE_SIZE_MULTIPLE,
                   int(round(v / IMAGE_SIZE_MULTIPLE)) * IMAGE_SIZE_MULTIPLE)

    px = w * h
    scale = 1.0
    if px < IMAGE_MIN_PIXELS:
        scale = math.sqrt(IMAGE_MIN_PIXELS / px)
    elif px > IMAGE_MAX_PIXELS:
        scale = math.sqrt(IMAGE_MAX_PIXELS / px)

    tw, th = snap(w * scale), snap(h * scale)
    for _ in range(200):          # snap 到 16 倍數後可能又掉出範圍，等比進退到合法為止
        if (IMAGE_MIN_PIXELS <= tw * th <= IMAGE_MAX_PIXELS
                and max(tw, th) <= IMAGE_MAX_EDGE):
            return tw, th
        scale *= 1.01 if tw * th < IMAGE_MIN_PIXELS else 0.99
        tw, th = snap(w * scale), snap(h * scale)
    raise ValueError(f"找不到 {w}x{h} 對應的合法 gpt-image-2 尺寸（最後嘗試 {tw}x{th}）")


def genai_usage_cost(usage) -> dict:
    """依 gpt-image-2 的 token 單價拆解這一次的花費。

    拆解而非只回總價，是因為兩者的成本行為不同：**輸入那份幾乎固定**
    （來源圖＋風格參考圖，gpt-image-2 一律以 high fidelity 讀），
    只有輸出那份隨 quality 變。看不到拆解就會誤以為調 quality 能等比省錢。
    """
    details = getattr(usage, "input_tokens_details", None)
    text_in = getattr(details, "text_tokens", 0) or 0
    image_in = getattr(details, "image_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    in_usd = (text_in * GENAI_PRICE_TEXT_IN + image_in * GENAI_PRICE_IMAGE_IN) / 1_000_000
    out_usd = out * GENAI_PRICE_IMAGE_OUT / 1_000_000
    return {"text_in_tok": text_in, "image_in_tok": image_in, "out_tok": out,
            "in_usd": in_usd, "out_usd": out_usd, "total_usd": in_usd + out_usd}


def _resolve_genai_source(code: str, src_name: str) -> tuple[Path, Path]:
    validate_code(code)   # code 會變成 output/<code> 路徑
    out_dir = OUTPUT_DIR / code
    src = out_dir / src_name
    if not src.exists():
        src = out_dir / "sat_raw.png"
    if not src.exists():
        sys.exit("ERROR: 找不到來源圖（先跑 map_capture / enhance）")
    return out_dir, src


def _resolve_style_ref(style_ref: str | None) -> Path | None:
    if not style_ref:
        return None
    ref = Path(style_ref)
    if not ref.is_absolute():
        ref = SCRIPTS_DIR / style_ref
    if ref.exists():
        print(f"  風格參考圖：{ref.name}")
        return ref
    print(f"  警告：風格參考圖不存在 {ref}，忽略")
    return None


def _genai_gemini(src: Path, ref: Path | None, prompt: str) -> tuple[bytes, dict]:
    """gemini-3.1-flash-image。實測比 gpt-image-2 忠於原圖（見上方常數區的對照表）。"""
    from google import genai
    from google.genai import types

    key = load_gemini_key()
    if not key:
        sys.exit("ERROR: genai --genai-provider gemini 需要 GEMINI_API_KEY")

    parts = [types.Part(inline_data=types.Blob(data=src.read_bytes(), mime_type="image/png"))]
    if ref:
        parts.append(types.Part(inline_data=types.Blob(
            data=ref.read_bytes(), mime_type="image/png")))
    # client 必須綁在區域變數上：寫成臨時物件會在請求發完前被 GC 關掉底層 httpx，
    # 拋 "Cannot send a request, as the client has been closed."
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=GEMINI_GENAI_MODEL,
        contents=[types.Content(parts=parts + [types.Part(text=prompt)])],
        config=types.GenerateContentConfig(
            response_modalities=["image", "text"],
            temperature=GEMINI_GENAI_TEMPERATURE,
        ),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image"):
            return part.inline_data.data, {"model": GEMINI_GENAI_MODEL,
                                           "temperature": GEMINI_GENAI_TEMPERATURE}
    sys.exit(f"ERROR: {GEMINI_GENAI_MODEL} 沒回傳圖片")


def _genai_openai(src: Path, ref: Path | None, prompt: str,
                  quality: str) -> tuple[bytes, dict]:
    """gpt-image-2。尺寸受限於 16 倍數，由 plan_genai_size() 協商後再縮回原尺寸。"""
    import base64
    import urllib.request

    from openai import OpenAI
    from PIL import Image

    key = load_openai_key()
    if not key:
        sys.exit("ERROR: genai --genai-provider openai 需要 OPENAI_API_KEY")

    src_w, src_h = Image.open(src).size
    tw, th = plan_genai_size(src_w, src_h)
    images = [("source.png", src.read_bytes(), "image/png")]
    if ref:
        images.append(("style_ref.png", ref.read_bytes(), "image/png"))

    client = OpenAI(api_key=key)          # 同上，不要寫成臨時物件
    resp = client.images.edit(
        model=OPENAI_GENAI_MODEL, image=images, prompt=prompt,
        size=f"{tw}x{th}", quality=quality,
    )
    item = resp.data[0] if resp.data else None
    if item is None:
        sys.exit(f"ERROR: {OPENAI_GENAI_MODEL} 沒回傳圖片")
    if getattr(item, "b64_json", None):
        raw = base64.b64decode(item.b64_json)
    elif getattr(item, "url", None):
        with urllib.request.urlopen(item.url) as r:
            raw = r.read()
    else:
        sys.exit(f"ERROR: {OPENAI_GENAI_MODEL} 沒回傳圖片")

    info = {"model": OPENAI_GENAI_MODEL, "quality": quality, "canvas": [tw, th]}
    if (u := genai_usage_cost(resp.usage) if getattr(resp, "usage", None) else None):
        print(f"  花費 ${u['total_usd']:.4f} = 輸入 ${u['in_usd']:.4f}"
              f"（圖 {u['image_in_tok']} + 文字 {u['text_in_tok']} tok）"
              f" + 輸出 ${u['out_usd']:.4f}（{u['out_tok']} tok）")
        info["cost_usd"] = round(u["total_usd"], 4)
    return raw, info


def genai_enhance(code: str, key: str | None = None,
                  src_name: str = "sat_raw.png",
                  provider: str = GENAI_PROVIDER_DEFAULT,
                  quality: str = GENAI_QUALITY,
                  style_ref: str | None = STYLE_REF_DEFAULT,
                  temperature: float | None = None,
                  prompt_style: str = GENAI_PROMPT_DEFAULT) -> Path:
    """生圖 HD 化（已去車的）衛星圖，輸出 sat_genai.png。

    provider：`gemini`（預設）或 `openai`（gpt-image-2）。
    quality：僅 openai 有效（low / medium / high / auto）。
    prompt_style：`sharp`（預設，乾淨清楚但會重畫標線與鋪面）或 `faithful`
        （像照片、保留髒污與浮水印）。兩者的代價對照見上方常數區。
    style_ref：風格參考圖，只借它的柏油材質質感，不借標線/佈局；faithful 會自動丟棄。

    ⚠ 兩家都是**重畫**不是修圖：實測位移中位數 Gemini 0.20m / gpt-image-2 0.30m。
    承載座標的地面圖請走 `enhance_file()`（sat_clean，實測 0.00m）。

    key／temperature 只為相容舊呼叫端保留：key 現在由各 provider 自己讀，
    temperature 是 OpenAI images API 沒有的旋鈕（Gemini 端固定 0.4）。
    """
    import io

    from PIL import Image

    if provider not in GENAI_PROVIDERS:
        sys.exit(f"ERROR: 未知的 --genai-provider {provider!r}（可選 {GENAI_PROVIDERS}）")
    if prompt_style not in GENAI_PROMPTS:
        sys.exit(f"ERROR: 未知的 --genai-prompt {prompt_style!r}"
                 f"（可選 {tuple(GENAI_PROMPTS)}）")
    if temperature is not None:
        print(f"  警告：temperature 已不由呼叫端控制（收到 {temperature}），忽略")

    out_dir, src = _resolve_genai_source(code, src_name)
    if prompt_style == "faithful" and style_ref:
        print("  風格參考圖與 faithful prompt 矛盾（會裝回硬邊界），本次忽略")
        style_ref = None
    ref = _resolve_style_ref(style_ref)
    prompt = GENAI_PROMPTS[prompt_style] + ("\n\n" + STYLE_REF_NOTE if ref else "")
    print(f"  prompt={prompt_style}"
          f"{'（現行預設：乾淨清楚，但會重畫標線與鋪面）' if prompt_style == 'sharp' else ''}")

    src_w, src_h = Image.open(src).size
    if provider == "gemini":
        raw, info = _genai_gemini(src, ref, prompt)
    else:
        raw, info = _genai_openai(src, ref, prompt, quality)

    img = Image.open(io.BytesIO(raw))
    # 縮回來源原尺寸，讓 sat_genai.png 與 sat_raw.png 共用同一組 px_per_meter
    if img.size != (src_w, src_h):
        print(f"  產出 {img.size[0]}x{img.size[1]} → 縮回來源尺寸 {src_w}x{src_h}")
        img = img.resize((src_w, src_h), Image.LANCZOS)

    out_path = out_dir / "sat_genai.png"
    img.save(out_path)
    print(f"  {info['model']} HD 生成（來源={src.name}）→ {out_path} {img.size}")

    # 回寫 meta：不寫的話「這張 HD 圖是誰產的、尺度對不對」查無實據
    meta_path = out_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["genai_provider"] = provider
        meta["genai_prompt"] = prompt_style      # 沒有這欄就查不出這張是哪套 prompt 產的
        meta["genai_size"] = [img.size[0], img.size[1]]
        meta["genai_matches_raw_size"] = (img.size == (src_w, src_h))
        meta["genai_src"] = src.name
        for k, v in info.items():
            meta[f"genai_{k}"] = v
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    return out_path


def enhance_file(src, dst, key: str | None = None, upscale: int = 2,
                 decar: bool = True) -> dict:
    """對**任意一張圖**去車 + 銳化 + 等比放大，回傳增強資訊 dict。

    **座標安全保證（這是本函式存在的理由）**：輸出必然是輸入的精確整數倍等比放大——
    去車是局部 inpaint、放大是 LANCZOS 整數倍、UnsharpMask 不動幾何。所以呼叫端只要
    把 px_per_meter 乘上 `px_per_meter_factor`（＝upscale），座標就仍然正確。

    這個保證讓它可以直接套在 **G-projection 校正參考圖**（`location/<code>/sat_<code>.png`）
    上——真實影片的 position_m 活在那張圖的平面，換一張取景不同的圖就整個錯位，
    所以「原地變好看」是唯一安全的做法。

    ⚠ `genai_enhance()` **不能**用於此用途：兩家生圖模型都是重畫整張，路面內容會被改寫
    （實測位移中位數 Gemini 0.20m、gpt-image-2 0.30m；本函式 0.00m）。

    key=None 會去讀環境變數／.env；key="" 則明確跳過去車（只銳化），測試與離線時用。
    """
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter

    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"找不到輸入圖 {src}")
    if not isinstance(upscale, int) or isinstance(upscale, bool) or upscale < 1:
        raise ValueError(f"upscale 必須是 >=1 的整數（目前 {upscale!r}）——"
                         f"非整數倍放大會破壞 px_per_meter 的換算")

    if key is None:
        key = load_gemini_key()
    pil = Image.open(src).convert("RGB")
    w, h = pil.size
    bgr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    # --- Step 1+2: Gemini 偵測 + cv2 inpaint 去車（只動局部像素，不動幾何）---
    # decar_status 是給自動化編排看的機器可讀狀態：降級（no_key/failed）不能再與
    # 「真的沒車」（no_vehicles）同值，否則批次跑完看起來全成功、實際地面圖烙著車。
    n_removed = 0
    decar_status = "no_key"
    if not decar:
        decar_status = "skipped"        # 使用者主動不要去車：不是降級，前端不警示
        key = ""
    if key:
        try:
            boxes = detect_vehicles(src.read_bytes(), w, h, key)
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
                decar_status = "ok"
                print(f"  Gemini 偵測 {n_removed} 台車 → cv2 inpaint 去除")
            else:
                decar_status = "no_vehicles"
                print("  Gemini 未偵測到車輛（或回傳空），跳過去車")
        except Exception as e:
            decar_status = "failed"
            print(f"  Gemini 去車失敗（{type(e).__name__}），fallback 只銳化：{e}")
    elif decar_status == "skipped":
        print("  略過去車（使用者設定），只銳化")
    else:
        print("  未提供 GEMINI_API_KEY，只銳化不去車")

    # --- Step 3: 銳化 + 高清化（整數倍 LANCZOS，長寬比必然保留）---
    out = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    if upscale > 1:
        out = out.resize((w * upscale, h * upscale), Image.LANCZOS)
    out = out.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=2))

    # 座標安全的最後一道防線：幾何若真的被動到，寧可炸掉也不要產出會讓車錯位的圖
    if out.size != (w * upscale, h * upscale):
        raise RuntimeError(f"增強後尺寸 {out.size} 不是 {(w, h)} 的 {upscale} 倍——"
                           f"幾何被改動，px_per_meter 將無法換算")

    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    print(f"  Saved: {dst}  ({out.size[0]}x{out.size[1]})")
    return {"out_size": out.size, "in_size": (w, h), "upscale": upscale,
            "px_per_meter_factor": upscale, "vehicles_removed": n_removed,
            "decar_status": decar_status}


def enhance(code: str, key: str | None = None, upscale: int = 2,
            out_dir: Path | None = None, decar: bool = True) -> Path:
    """satellite_pipeline 的標準路徑：output/<code>/sat_raw.png → sat_clean.png。

    out_dir 預設 output/<code>；可注入（webapp／測試用）。
    """
    validate_code(code)   # code 會變成 output/<code> 路徑
    out_dir = Path(out_dir) if out_dir else OUTPUT_DIR / code
    raw_path = out_dir / "sat_raw.png"
    if not raw_path.exists():
        sys.exit(f"ERROR: 找不到 {raw_path}（先跑 map_capture.py）")

    clean_path = out_dir / "sat_clean.png"
    info = enhance_file(raw_path, clean_path, key=key, upscale=upscale, decar=decar)

    # 更新 meta：記錄去車數 + 增強後尺寸
    meta_path = out_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["vehicles_removed"] = info["vehicles_removed"]
        meta["decar_status"] = info["decar_status"]
        meta["enhanced_px"] = info["out_size"][0]
        meta["upscale"] = upscale
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    return clean_path


def main():
    ap = argparse.ArgumentParser(description="衛星圖去車 + 銳化高清化")
    ap.add_argument("--code", type=validate_code,
                    help="satellite_pipeline 標準路徑：output/<code>/sat_raw.png → sat_clean.png")
    ap.add_argument("--input", help="任意輸入圖（與 --output 併用）。用於把 G-projection "
                                    "校正參考圖原地變好看——等比放大，座標仍然有效")
    ap.add_argument("--output", help="與 --input 併用的輸出路徑")
    ap.add_argument("--upscale", type=int, default=2, help="放大倍率（必須是整數），預設 2")
    ap.add_argument("--genai", action="store_true",
                    help="額外用生圖模型做 HD 化（在去車結果上），輸出 sat_genai.png")
    ap.add_argument("--genai-provider", choices=GENAI_PROVIDERS,
                    default=GENAI_PROVIDER_DEFAULT,
                    help="生圖供應商：gemini 預設（實測較忠於原圖）、openai 用 gpt-image-2")
    ap.add_argument("--genai-quality", choices=("low", "medium", "high", "auto"),
                    default=GENAI_QUALITY,
                    help="生圖品質，僅 --genai-provider openai 有效："
                         "low 試 prompt、medium 預設、high 定稿")
    ap.add_argument("--genai-temp", type=float, default=None,
                    help="（已棄用）OpenAI images API 無 temperature，傳了會被忽略")
    ap.add_argument("--genai-prompt", choices=tuple(GENAI_PROMPTS),
                    default=GENAI_PROMPT_DEFAULT,
                    help="sharp 預設（乾淨清楚，代價是重畫標線與鋪面）、"
                         "faithful（像照片、保留髒污與浮水印）")
    ap.add_argument("--style-ref", default=STYLE_REF_DEFAULT,
                    help="風格參考圖（真實空拍馬路），只借柏油質感；設空字串關閉。"
                         "faithful prompt 會自動忽略")
    args = ap.parse_args()

    if args.input or args.output:
        if not (args.input and args.output):
            ap.error("--input 與 --output 必須併用")
        if args.genai:
            ap.error("--genai 會重畫整張圖、內容可能改變，"
                     "不可用於 --input 路徑（該路徑的存在理由就是保住座標）")
        print(f"[image_enhance] {args.input} → {args.output}")
        info = enhance_file(args.input, args.output, upscale=args.upscale)
        print(f"[image_enhance] 尺寸 {info['in_size']} → {info['out_size']}；"
              f"px_per_meter 需乘以 {info['px_per_meter_factor']}")
        print("[image_enhance] Done.")
        return

    if not args.code:
        ap.error("需要 --code，或（--input + --output）")
    print(f"[image_enhance] code={args.code}")
    enhance(args.code, upscale=args.upscale)
    if args.genai:
        print(f"[image_enhance] 生圖 HD 化（provider={args.genai_provider}）…")
        genai_enhance(args.code, provider=args.genai_provider,
                      quality=args.genai_quality,
                      temperature=args.genai_temp,
                      prompt_style=args.genai_prompt,
                      style_ref=args.style_ref or None)
    print("[image_enhance] Done.")


if __name__ == "__main__":
    main()
