#!/opt/homebrew/Caskroom/miniconda/base/bin/python3
"""
Enhance a satellite image: detect vehicles via Gemini, remove with cv2 inpaint, sharpen with PIL.

Usage:
    python3 image_enhance.py --code test1 [--api-key YOUR_KEY]
    # or set env var GEMINI_API_KEY

Input:  location/{code}/sat_raw_{code}.png
Output: location/{code}/sat_clean_{code}.png
"""
import argparse
import json
import os
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter

SCRIPTS_DIR = Path(__file__).parent
LOCATION_DIR = SCRIPTS_DIR.parent / "location"

DETECT_PROMPT = """This is an aerial satellite view of a road intersection.
Identify all vehicles visible: cars, trucks, motorcycles, buses, vans, SUVs.
Return ONLY a valid JSON array, no other text:
[{{"x1": int, "y1": int, "x2": int, "y2": int, "type": "car"}}]
Image size is {W}x{H} pixels. If no vehicles found, return []."""


def detect_vehicles_gemini(img_path: Path, api_key: str) -> list[dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    img_bytes = img_path.read_bytes()
    img = Image.open(img_path)
    W, H = img.size

    prompt = DETECT_PROMPT.format(W=W, H=H)

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
            types.Part.from_text(text=prompt),
        ],
    )

    text = response.text.strip()
    print(f"  Gemini raw response: {text[:200]}")

    # extract JSON array from response
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        print("  Warning: Gemini returned no parseable JSON, skipping vehicle removal")
        return []

    try:
        boxes = json.loads(match.group())
        print(f"  Detected {len(boxes)} vehicles")
        return boxes
    except json.JSONDecodeError as e:
        print(f"  Warning: JSON parse error: {e}")
        return []


def remove_vehicles(img_bgr: np.ndarray, boxes: list[dict], expand_px: int = 8) -> np.ndarray:
    if not boxes:
        return img_bgr

    H, W = img_bgr.shape[:2]
    mask = np.zeros((H, W), dtype=np.uint8)

    for box in boxes:
        x1 = max(0, int(box["x1"]) - expand_px)
        y1 = max(0, int(box["y1"]) - expand_px)
        x2 = min(W, int(box["x2"]) + expand_px)
        y2 = min(H, int(box["y2"]) + expand_px)
        mask[y1:y2, x1:x2] = 255

    # TELEA works well for road textures (propagates from boundary inward)
    result = cv2.inpaint(img_bgr, mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)
    return result


def sharpen_pil(img_path: Path) -> Image.Image:
    img = Image.open(img_path)
    sharpened = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=2))
    return sharpened


def enhance(code: str, api_key: str | None = None) -> Path:
    out_dir = LOCATION_DIR / code
    raw_path = out_dir / f"sat_raw_{code}.png"
    clean_path = out_dir / f"sat_clean_{code}.png"

    if not raw_path.exists():
        raise FileNotFoundError(f"Raw image not found: {raw_path}")

    # --- Step 1: Gemini vehicle detection ---
    boxes = []
    if api_key:
        print("  [Step 1] Gemini vehicle detection...")
        try:
            boxes = detect_vehicles_gemini(raw_path, api_key)
        except Exception as e:
            print(f"  Warning: Gemini detection failed ({e}), skipping removal")
    else:
        print("  [Step 1] No GEMINI_API_KEY — skipping vehicle detection")

    # --- Step 2: cv2 inpaint ---
    print(f"  [Step 2] Inpainting {len(boxes)} vehicle regions...")
    img_bgr = cv2.imread(str(raw_path))
    img_clean = remove_vehicles(img_bgr, boxes)

    # save intermediate for PIL to read
    tmp_path = out_dir / f"sat_inpainted_{code}.png"
    cv2.imwrite(str(tmp_path), img_clean)

    # --- Step 3: PIL sharpen ---
    print("  [Step 3] Sharpening...")
    sharpened = sharpen_pil(tmp_path)
    sharpened.save(str(clean_path))
    tmp_path.unlink()  # remove intermediate file

    print(f"  Saved: {clean_path}")
    return clean_path


def main():
    parser = argparse.ArgumentParser(description="Enhance satellite image: remove vehicles + sharpen")
    parser.add_argument("--code", type=str, required=True, help="location_code, e.g. test1")
    parser.add_argument("--api-key", type=str, default=None,
                        help="Gemini API key (or set GEMINI_API_KEY env var)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Warning: GEMINI_API_KEY not set — will sharpen only, no vehicle removal")

    print(f"[image_enhance] code={args.code}")
    enhance(args.code, api_key)
    print("[image_enhance] Done.")


if __name__ == "__main__":
    main()
