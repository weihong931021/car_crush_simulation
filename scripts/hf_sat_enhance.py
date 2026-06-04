"""
Hugging Face Inference API - 衛星圖 AI 去車 + 高清化
用法: HF_TOKEN=xxx python3 scripts/hf_sat_enhance.py
"""
import os, sys
from pathlib import Path

HF_TOKEN = os.environ.get("HF_TOKEN", "")
if not HF_TOKEN:
    print("ERROR: 請設定 HF_TOKEN 環境變數")
    sys.exit(1)

SRC = Path("/Users/weihong/Documents/blender_crash_project/images/sat_notxt_raw.png")
OUT_EDIT = Path("/Users/weihong/Documents/blender_crash_project/images/sat_hf_edited.png")
OUT_FINAL = Path("/Users/weihong/Documents/blender_crash_project/images/sat_25m_final.png")

from huggingface_hub import InferenceClient
from PIL import Image, ImageFilter, ImageEnhance
import io

client = InferenceClient(token=HF_TOKEN)

# --- Step 1: instruct-pix2pix 去車 ---
print("Step 1: image-to-image (instruct-pix2pix)...")
try:
    with open(SRC, "rb") as f:
        img_bytes = f.read()

    result = client.image_to_image(
        image=img_bytes,
        prompt=(
            "aerial satellite top-down view of road intersection in Taiwan, "
            "no vehicles, clean empty road surface, "
            "visible road markings lane lines zebra crossings, "
            "buildings and trees intact"
        ),
        negative_prompt="car, truck, motorcycle, scooter, bus, vehicle, person",
        model="timbrooks/instruct-pix2pix",
    )
    result.save(OUT_EDIT)
    print(f"  Saved edited: {OUT_EDIT}  size={result.size}")
    edited_img = result

except Exception as e:
    print(f"  instruct-pix2pix failed: {e}")
    print("  Falling back to original image...")
    edited_img = Image.open(SRC)

# --- Step 2: 4x Lanczos + UnsharpMask 高清化 ---
print("Step 2: 4x upscale + sharpen...")
up = edited_img.resize((edited_img.width * 4, edited_img.height * 4), Image.LANCZOS)
up = up.filter(ImageFilter.UnsharpMask(radius=1.0, percent=150, threshold=2))
up = up.filter(ImageFilter.UnsharpMask(radius=0.5, percent=80, threshold=1))
up = ImageEnhance.Contrast(up).enhance(1.12)
up = ImageEnhance.Sharpness(up).enhance(1.3)
up.save(OUT_FINAL)
print(f"  Saved final: {OUT_FINAL}  size={up.size}")
print("Done.")
