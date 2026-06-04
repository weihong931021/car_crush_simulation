"""
測試 HF Inference API 哪些圖像編輯模型可用
用法: HF_TOKEN=xxx python3 scripts/hf_test_models.py
"""
import os, requests, base64, json
from pathlib import Path

TOKEN = os.environ["HF_TOKEN"]
IMG_PATH = "/Users/weihong/Documents/blender_crash_project/images/sat_notxt_raw.png"

headers = {"Authorization": f"Bearer {TOKEN}"}

with open(IMG_PATH, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

MODELS = [
    ("timbrooks/instruct-pix2pix", "image-to-image"),
    ("lllyasviel/sd-controlnet-canny", "image-to-image"),
    ("stabilityai/stable-diffusion-xl-refiner-1.0", "image-to-image"),
    ("black-forest-labs/FLUX.1-schnell", "text-to-image"),
    ("black-forest-labs/FLUX.1-dev", "text-to-image"),
]

PROMPT = "aerial satellite view, no vehicles, clean road, top-down"

for model, task in MODELS:
    url = f"https://api-inference.huggingface.co/models/{model}"
    if task == "image-to-image":
        payload = {"inputs": img_b64, "parameters": {"prompt": PROMPT}}
    else:
        payload = {"inputs": PROMPT}

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    ct = r.headers.get("content-type", "")
    print(f"{model}: {r.status_code} | {ct[:40]}")
    if r.status_code != 200:
        try:
            err = r.json()
            print(f"  → {err.get('error', '')[:120]}")
        except Exception:
            print(f"  → {r.text[:120]}")
