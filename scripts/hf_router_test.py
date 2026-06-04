"""
用新的 HF router endpoint 做圖像編輯
用法: HF_TOKEN=xxx python3 scripts/hf_router_test.py
"""
import os, urllib.request, urllib.error, json, base64
from pathlib import Path

TOKEN = os.environ["HF_TOKEN"]
IMG_PATH = "/Users/weihong/Documents/blender_crash_project/images/sat_notxt_raw.png"

with open(IMG_PATH, "rb") as f:
    img_bytes = f.read()

headers_base = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}

# 試 router.huggingface.co (新 Inference Providers 端點)
ENDPOINTS = [
    # instruct-pix2pix via router
    "https://router.huggingface.co/hf-inference/models/timbrooks/instruct-pix2pix",
    # 用 base64 image + json
]

for url in ENDPOINTS:
    payload = json.dumps({
        "inputs": base64.b64encode(img_bytes).decode(),
        "parameters": {
            "prompt": "aerial satellite top-down road intersection no vehicles, clean road pavement",
            "negative_prompt": "car truck motorcycle vehicle",
            "num_inference_steps": 20,
            "image_guidance_scale": 1.5,
        }
    }).encode()

    req = urllib.request.Request(url, data=payload, headers=headers_base, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ct = resp.headers.get("content-type", "")
            data = resp.read()
            print(f"OK: {url}")
            print(f"   Content-Type: {ct}, size: {len(data)}")
            if "image" in ct:
                out = "/Users/weihong/Documents/blender_crash_project/images/sat_hf_edited.png"
                with open(out, "wb") as f:
                    f.write(data)
                print(f"   Saved: {out}")
            else:
                print(f"   Response: {data[:200]}")
    except urllib.error.HTTPError as e:
        body = e.read()
        print(f"HTTP {e.code}: {url}")
        try:
            print(f"   {json.loads(body)}")
        except Exception:
            print(f"   {body[:200]}")
    except Exception as e:
        print(f"FAIL: {url}: {e}")
