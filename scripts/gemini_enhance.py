"""
用 Gemini 圖像生成模型增強衛星圖
用法: GEMINI_KEY=xxx python3 scripts/gemini_enhance.py
"""
import os, sys
from pathlib import Path
from google import genai
from google.genai import types

KEY = os.environ["GEMINI_KEY"]
client = genai.Client(api_key=KEY)

SRC  = "/Users/weihong/Documents/blender_crash_project/images/sat_notxt_raw.png"
OUT  = "/Users/weihong/Documents/blender_crash_project/images/sat_gemini.png"
FINAL = "/Users/weihong/Documents/blender_crash_project/images/sat_25m_final.png"

# --- Step 1: 確認配額（用最便宜的 text call 測試）---
print("Step 1: checking quota...")
try:
    r = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="reply ok"
    )
    print(f"  quota OK: {r.text.strip()[:30]}")
except Exception as e:
    print(f"  quota FAIL: {e}")
    sys.exit(1)

# --- Step 2: 找可用的圖像生成模型 ---
print("\nStep 2: finding image generation models...")
img_models = []
for m in client.models.list():
    name = m.name
    if any(x in name.lower() for x in ['image', 'imagen']):
        img_models.append(name)
        print(f"  {name}")
if not img_models:
    print("  No image models found!")
    sys.exit(1)

# --- Step 3: 讀入衛星圖 ---
with open(SRC, "rb") as f:
    img_bytes = f.read()
print(f"\nStep 3: source image loaded, {len(img_bytes)//1024}KB")

# --- Step 4: 試各個圖像模型 ---
PROMPT = (
    "This is an aerial/satellite top-down photograph of a road intersection in Taiwan. "
    "Please enhance this image: improve clarity and sharpness, enhance contrast to make "
    "road markings, zebra crossings, lane lines and road surfaces very clear and crisp. "
    "Keep the exact same viewpoint, same road layout, same buildings — only improve the "
    "visual quality. Make it look like a professional high-resolution aerial photograph. "
    "Do not add or remove any roads, buildings, or structural elements."
)

MODELS_TO_TRY = [
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image-preview",
    "gemini-2.0-flash-preview-image-generation",
]

saved = False
for model_short in MODELS_TO_TRY:
    model_full = model_short if model_short.startswith("models/") else f"models/{model_short}"
    # 跳過不在清單的
    if model_full not in img_models and model_short not in img_models:
        continue

    print(f"\nStep 4: trying {model_short}...")
    try:
        response = client.models.generate_content(
            model=model_short,
            contents=[
                types.Content(parts=[
                    types.Part(inline_data=types.Blob(data=img_bytes, mime_type="image/png")),
                    types.Part(text=PROMPT)
                ])
            ],
            config=types.GenerateContentConfig(
                response_modalities=["image", "text"]
            )
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image"):
                with open(OUT, "wb") as f:
                    f.write(part.inline_data.data)
                print(f"  Image saved: {OUT}")
                saved = True
                break
            elif hasattr(part, "text") and part.text:
                print(f"  Text: {part.text[:150]}")

        if saved:
            break

    except Exception as e:
        print(f"  {model_short} failed: {e}")

if not saved:
    print("\nNo image models worked. Check available models list above.")
    sys.exit(1)

# --- Step 5: 4x 放大 ---
print("\nStep 5: 4x upscale + sharpen...")
from PIL import Image, ImageFilter, ImageEnhance
import numpy as np

img = Image.open(OUT)
print(f"  Gemini output size: {img.size}")

# 如果 Gemini 輸出已夠大就只銳化，否則放大
if img.width < 1000:
    up = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
else:
    up = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

up = up.filter(ImageFilter.UnsharpMask(radius=0.8, percent=100, threshold=3))
up = ImageEnhance.Contrast(up).enhance(1.08)
up.save(FINAL)
print(f"  Final saved: {FINAL}  size={up.size}")
print("\nDone.")
