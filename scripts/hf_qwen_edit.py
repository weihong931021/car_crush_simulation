"""
用 Qwen-Image-Edit-2511 (via fal-ai) 做指令式衛星圖去車
用法: HF_TOKEN=xxx python3 scripts/hf_qwen_edit.py
"""
import os, urllib.request, urllib.error, json, base64
from pathlib import Path
from PIL import Image
import io

TOKEN = os.environ["HF_TOKEN"]
SRC = "/Users/weihong/Documents/blender_crash_project/images/sat_notxt_raw.png"
OUT = "/Users/weihong/Documents/blender_crash_project/images/sat_hf_edited.png"
FINAL = "/Users/weihong/Documents/blender_crash_project/images/sat_25m_final.png"

with open(SRC, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

# 試幾種格式
MODELS_PROVIDERS = [
    ("fal-ai", "Qwen/Qwen-Image-Edit-2511"),
    ("fal-ai", "lightx2v/Qwen-Image-Edit-2511-Lightning"),
    ("fal-ai", "black-forest-labs/FLUX.2-dev"),
]

PROMPT = (
    "Remove all vehicles including cars, motorcycles, scooters, trucks and buses from this aerial satellite image. "
    "Fill the areas where vehicles were with the appropriate road surface, pavement, or markings that would be underneath. "
    "Keep all buildings, road markings, zebra crossings, lane lines, and road surface exactly as they are."
)

for provider, model in MODELS_PROVIDERS:
    url = f"https://router.huggingface.co/{provider}/models/{model}"
    payload = json.dumps({
        "inputs": img_b64,
        "parameters": {"prompt": PROMPT}
    }).encode()

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    print(f"\nTrying {provider}/{model}...")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            ct = resp.headers.get("content-type", "")
            data = resp.read()
            print(f"  Status 200, Content-Type: {ct}, size: {len(data)}")
            if "image" in ct:
                with open(OUT, "wb") as f:
                    f.write(data)
                print(f"  Saved: {OUT}")

                # 高清化
                edited = Image.open(OUT)
                from PIL import ImageFilter, ImageEnhance
                up = edited.resize((edited.width * 4, edited.height * 4), Image.LANCZOS)
                up = up.filter(ImageFilter.UnsharpMask(radius=1.0, percent=150, threshold=2))
                up = ImageEnhance.Contrast(up).enhance(1.12)
                up.save(FINAL)
                print(f"  Final saved: {FINAL}  size={up.size}")
                break
            else:
                print(f"  Response: {data[:300]}")
    except urllib.error.HTTPError as e:
        body = e.read()
        print(f"  HTTP {e.code}")
        try:
            err = json.loads(body)
            print(f"  Error: {err}")
        except Exception:
            print(f"  Body: {body[:200]}")
    except Exception as e:
        print(f"  FAIL: {e}")
