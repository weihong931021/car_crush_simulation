"""
Gemini 圖像增強 v2 - 試最強模型，強化 prompt
用法: GEMINI_KEY=xxx python3 scripts/gemini_enhance_v2.py
"""
import os, sys
from google import genai
from google.genai import types
from PIL import Image, ImageFilter, ImageEnhance
import numpy as np
import io

KEY = os.environ["GEMINI_KEY"]
client = genai.Client(api_key=KEY)

SRC   = "/Users/weihong/Documents/blender_crash_project/images/sat_notxt_raw.png"
FINAL = "/Users/weihong/Documents/blender_crash_project/images/sat_25m_final.png"

with open(SRC, "rb") as f:
    img_bytes = f.read()

PROMPT = (
    "Sharpen and enhance the clarity of this aerial satellite image. "
    "Increase contrast so the road surface, existing zebra crossings and lane markings "
    "already present in the image become more visible and crisp. "
    "IMPORTANT: only enhance what is ALREADY there — do not add, invent, or move any "
    "road markings, arrows, zebra stripes, or structures. "
    "Do not change the road geometry or layout in any way. "
    "Think of this as a deblur + contrast boost operation only."
)

MODELS = [
    "gemini-3.1-flash-image",
    "gemini-3-pro-image",
    "gemini-3.1-flash-image-preview",
    "gemini-2.5-flash-image",
]

for model in MODELS:
    print(f"Trying {model}...")
    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Content(parts=[
                    types.Part(inline_data=types.Blob(data=img_bytes, mime_type="image/png")),
                    types.Part(text=PROMPT)
                ])
            ],
            config=types.GenerateContentConfig(
                response_modalities=["image", "text"],
                temperature=0.3,   # 0.3: 夠保守不亂畫，但仍能銳化
            )
        )

        out_img = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image"):
                out_img = Image.open(io.BytesIO(part.inline_data.data))
                raw_path = f"/Users/weihong/Documents/blender_crash_project/images/sat_gemini_{model.replace('/', '_')}.png"
                out_img.save(raw_path)
                print(f"  Raw output: {out_img.size} → {raw_path}")
                break
            elif hasattr(part, "text") and part.text:
                print(f"  Text: {part.text[:200]}")

        if out_img is None:
            print("  No image in response, next model...")
            continue

        # Post-process: contrast stretch + sharpen
        arr = np.array(out_img, dtype=np.float32)
        for c in range(3):
            ch = arr[:,:,c]
            lo, hi = np.percentile(ch, 1), np.percentile(ch, 99)
            arr[:,:,c] = np.clip((ch - lo) / (hi - lo) * 255, 0, 255)
        enhanced = Image.fromarray(arr.astype(np.uint8))
        enhanced = enhanced.filter(ImageFilter.UnsharpMask(radius=1.0, percent=130, threshold=2))
        enhanced = ImageEnhance.Contrast(enhanced).enhance(1.1)

        # upscale if needed
        if enhanced.width < 1400:
            scale = 1400 // enhanced.width + 1
            enhanced = enhanced.resize(
                (enhanced.width * scale, enhanced.height * scale), Image.LANCZOS
            )

        enhanced.save(FINAL)
        print(f"  Final saved: {FINAL}  size={enhanced.size}")
        print(f"  Model used: {model}")
        break

    except Exception as e:
        print(f"  {model} failed: {e}")
