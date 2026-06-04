# Satellite Ground Plane Auto-Capture Pipeline

**Date:** 2026-06-01  
**Status:** Approved

## Goal

Automate the manual step of capturing a Google Maps satellite screenshot and placing it as a correctly-scaled ground plane in Blender, so collision animations have a real-world road texture background.

## Pipeline

```
lat/lon (user input)
  → [1] map_capture.py      → sat_raw_{code}.png + meta.json
  → [2] image_enhance.py    → sat_clean_{code}.png
  → [3] blender_ground.py   → Blender Plane with texture
```

All outputs go to `trafficlab-project/location/{code}/`.

## Coordinate System

- `position_m` origin = satellite image top-left corner
- `position_m_x = sat_coords_x / px_per_meter`, `position_m_y = sat_coords_y / px_per_meter`
- Blender ground plane: top-left at world (0, 0, 0), extends +X and +Y
- No offset needed between vehicle tracks and ground plane if same px_per_meter

## px_per_meter Formula

```python
import math
meters_per_pixel = (2 * math.pi * 6378137 * math.cos(math.radians(lat))) / (2**zoom * 256)
px_per_meter = 1 / meters_per_pixel
# zoom=22, lat=25° (Taiwan) → px_per_meter ≈ 29.6
```

Recommended zoom: 21–22 to match existing test1 scale (~34 px/m).

## Component: map_capture.py

**Input:** `lat`, `lon`, `location_code`, `zoom` (default 21)  
**Method:** Playwright Chromium, headless  
**URL:** `https://www.google.com/maps/@{lat},{lon},{zoom}z/data=!3m1!1e3`  
**UI hiding:** CSS injection to hide controls, labels, attribution  
**Tile wait:** `networkidle` + 2s extra  
**Output:** `sat_raw_{code}.png` (1024×1024), `sat_capture_meta.json` `{lat, lon, zoom, px_per_meter, img_w, img_h, timestamp}`

## Component: image_enhance.py

**Step 1 – Gemini vehicle detection**  
Model: `gemini-1.5-flash`  
Prompt:
```
This is an aerial satellite view of a road intersection.
Identify all vehicles (cars, trucks, motorcycles, buses, vans).
Return ONLY a JSON array: [{"x1":int,"y1":int,"x2":int,"y2":int,"type":"car"}]
Image size: {W}x{H} pixels. No other text.
```

**Step 2 – cv2 inpaint**  
- Expand bboxes by 8px
- Create binary mask
- `cv2.inpaint(img, mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)`

**Step 3 – PIL sharpen**  
- `ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=2)`

**Output:** `sat_clean_{code}.png`  
**Fallback:** If Gemini fails/returns no vehicles, save sharpened-only version.

## Component: blender_ground.py

**Input:** `location_code` (reads meta.json + sat_clean.png from location dir)  
**Blender object:** `Plane` named `GroundPlane_{code}`  
- Size: `(img_w / px_per_meter) × (img_h / px_per_meter)` meters
- Position: center at `(img_w/2/px_per_m, img_h/2/px_per_m, -0.01)` so top-left = (0,0)
- Material: Emission shader (unlit) with image texture, alpha blend
- UV: simple box project via `bpy.ops.uv.reset()`

**Note:** Use `bpy.ops.uv.reset()` not `bpy.ops.uv.unwrap()` (known Blender bug).

## Dependencies

```
playwright (+ chromium browser)
google-generativeai
opencv-python  (already installed)
Pillow         (already installed)
```

## Config

API key loaded from env var `GEMINI_API_KEY` or `.env` file in project root. Never hardcoded.

## File Layout

```
trafficlab-project/
  scripts/
    map_capture.py
    image_enhance.py
    blender_ground.py
    pipeline_mapground.py   ← orchestrator (all-in-one CLI)
  location/{code}/
    sat_raw_{code}.png
    sat_clean_{code}.png
    sat_capture_meta.json
    G_projection_{code}.json  (existing)
```
