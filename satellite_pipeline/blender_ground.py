#!/usr/bin/env python3
"""
blender_ground.py — 把衛星圖貼成 Blender 地板平面

兩種用法：
  1. 被 pipeline.py 匯入：build_blender_code(code) 回傳可注入 Blender 的 Python 字串
     （pipeline 透過 Blender MCP execute_blender_code 直接貼進正在開的場景）
  2. 在 Blender 內手動跑：
        _CODE = "tainan_yongkang"
        _ROOT = r"/Users/.../satellite_pipeline"
        exec(open(".../blender_ground.py").read())

座標系（與 design doc 2026-06-01 一致）：
  平面左上角對齊世界 (0,0,0)，往 +X / +Y 延伸，與 position_m 軌跡同源。
  平面尺寸 = (img_w / px_per_meter) × (img_h / px_per_meter) 公尺。
  用 Emission（unlit）材質，texture 不受燈光影響。
  UV 用 bpy.ops.uv.reset()（不可用 unwrap，已知 Blender bug）。
"""
from pathlib import Path


def build_blender_code(code: str, base_dir: str | None = None,
                       variant: str = "auto") -> str:
    """產生貼地板用的 Blender Python 原始碼字串。

    variant 明確指定要貼哪一版，避免默默抓到舊圖：
      "auto"  → 依序找 sat_genai > sat_clean > sat_raw（皆需存在）
      "genai" / "clean" / "raw" → 指定該版，不存在則報錯
    """
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parent
    out_dir = base / "output" / code
    meta_path = out_dir / "meta.json"
    candidates = {
        "genai": out_dir / "sat_genai.png",
        "clean": out_dir / "sat_clean.png",
        "raw": out_dir / "sat_raw.png",
    }
    if variant == "auto":
        img_path = next((p for p in candidates.values() if p.exists()), None)
        if img_path is None:
            raise FileNotFoundError(f"{out_dir} 內找不到任何 sat_*.png（先跑 pipeline）")
    else:
        img_path = candidates.get(variant)
        if img_path is None:
            raise ValueError(f"未知 variant: {variant}")
        if not img_path.exists():
            raise FileNotFoundError(f"指定的 {img_path.name} 不存在於 {out_dir}")

    return f'''
import bpy, json
from pathlib import Path

CODE = "{code}"
META = r"{meta_path}"
IMG  = r"{img_path}"

meta = json.loads(Path(META).read_text())
ppm = meta["px_per_meter"]
img_w, img_h = meta["img_w"], meta["img_h"]
width_m  = img_w / ppm
height_m = img_h / ppm

name = f"GroundPlane_{{CODE}}"
# 移除同名舊平面
if name in bpy.data.objects:
    bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)

# 建平面：左上角對齊原點 → 中心在 (width/2, height/2)
bpy.ops.mesh.primitive_plane_add(size=1, location=(width_m/2, height_m/2, -0.01))
plane = bpy.context.active_object
plane.name = name
plane.scale = (width_m, height_m, 1)
bpy.ops.object.transform_apply(scale=True)

# Emission（unlit）材質
mat = bpy.data.materials.new(f"SatMat_{{CODE}}")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
tex = nt.nodes.new("ShaderNodeTexImage")
emi = nt.nodes.new("ShaderNodeEmission")
out = nt.nodes.new("ShaderNodeOutputMaterial")
tex.image = bpy.data.images.load(IMG, check_existing=False)
nt.links.new(tex.outputs["Color"], emi.inputs["Color"])
nt.links.new(emi.outputs["Emission"], out.inputs["Surface"])
plane.data.materials.clear()
plane.data.materials.append(mat)

# UV reset（整張圖對應整個平面）
bpy.context.view_layer.objects.active = plane
bpy.ops.object.editmode_toggle()
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.reset()
bpy.ops.object.editmode_toggle()

# 俯視 + 材質預覽
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        with bpy.context.temp_override(area=area, region=area.regions[-1]):
            bpy.ops.view3d.view_axis(type="TOP", align_active=False)
            bpy.ops.view3d.view_all()
        for sp in area.spaces:
            if sp.type == "VIEW_3D":
                sp.shading.type = "MATERIAL"
        break

print(f"GroundPlane_{{CODE}}: {{width_m:.2f}} x {{height_m:.2f}} m @ {{ppm:.2f}} px/m")
'''


# 在 Blender 內手動 exec 時的進入點
if "_CODE" in dir():
    _root = globals().get("_ROOT", None)
    exec(build_blender_code(globals()["_CODE"], _root))
