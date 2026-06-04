"""
Gemini 衛星圖增強 - 最佳版本（恢復清晰路面效果）
用法: GEMINI_KEY=xxx python3 scripts/gemini_enhance_best.py
"""
import os, sys, io
from google import genai
from google.genai import types
from PIL import Image, ImageFilter, ImageEnhance
import numpy as np

KEY = os.environ["GEMINI_KEY"]
client = genai.Client(api_key=KEY)

SRC   = "/Users/weihong/Documents/blender_crash_project/images/sat_notxt_raw.png"
OUT_RAW = "/Users/weihong/Documents/blender_crash_project/images/sat_gemini_best_raw.png"
FINAL = "/Users/weihong/Documents/blender_crash_project/images/sat_25m_final.png"

with open(SRC, "rb") as f:
    img_bytes = f.read()

# 原始最佳效果的 prompt（只改 temperature，不碰 prompt）
PROMPT = (
    "Enhance this aerial/satellite photograph of a road intersection in Taiwan into a "
    "professional-quality high-resolution aerial image. Requirements:\n"
    "1. Make road surfaces very sharp, dark grey asphalt clearly defined\n"
    "2. Make zebra crossing white stripes crisp, bright white\n"
    "3. Make lane markings and road arrows clearly visible\n"
    "4. Enhance building rooftop textures\n"
    "5. Improve overall sharpness and contrast significantly\n"
    "6. Keep EXACTLY the same top-down viewpoint and road layout\n"
    "7. Make it look like a high-resolution drone photograph taken from directly above\n"
    "Do NOT change the road layout, do NOT add elements that are not there."
)

print("Running gemini-3.1-flash-image (best quality)...")
response = client.models.generate_content(
    model="gemini-3.1-flash-image",
    contents=[
        types.Content(parts=[
            types.Part(inline_data=types.Blob(data=img_bytes, mime_type="image/png")),
            types.Part(text=PROMPT)
        ])
    ],
    config=types.GenerateContentConfig(
        response_modalities=["image", "text"],
        temperature=0.5,  # 介於清晰（高）和忠實（低）之間
    )
)

out_img = None
for part in response.candidates[0].content.parts:
    if part.inline_data and part.inline_data.mime_type.startswith("image"):
        out_img = Image.open(io.BytesIO(part.inline_data.data))
        out_img.save(OUT_RAW)
        print(f"Raw saved: {OUT_RAW}  size={out_img.size}")
        break
    elif hasattr(part, "text") and part.text:
        print(f"Text: {part.text[:150]}")

if out_img is None:
    print("No image returned.")
    sys.exit(1)

# post-process
arr = np.array(out_img, dtype=np.float32)
for c in range(3):
    ch = arr[:,:,c]
    lo, hi = np.percentile(ch, 1), np.percentile(ch, 99)
    arr[:,:,c] = np.clip((ch - lo) / (hi - lo) * 255, 0, 255)
enhanced = Image.fromarray(arr.astype(np.uint8))
enhanced = enhanced.filter(ImageFilter.UnsharpMask(radius=0.8, percent=110, threshold=2))

if enhanced.width < 1400:
    enhanced = enhanced.resize((enhanced.width * 2, enhanced.height * 2), Image.LANCZOS)

enhanced.save(FINAL)
print(f"Final saved: {FINAL}  size={enhanced.size}")
