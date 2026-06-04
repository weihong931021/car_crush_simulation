"""
Blender Python script: create a ground plane textured with the satellite image.

Run via Blender MCP or paste into Blender scripting panel:
    exec(open('/path/to/blender_ground.py').read())

Or call from pipeline_mapground.py which passes location_code + project root via globals.

Coordinate convention:
    - sat image top-left  → Blender world (0, 0, 0)
    - sat image bottom-right → (img_w/px_per_m, img_h/px_per_m, 0)
    - vehicle position_m (x, y) maps directly to Blender (x, y, 0)
"""
import json
import os
from pathlib import Path

import bpy

# --- resolve paths ---
# When called from pipeline, these globals are injected before exec()
_location_code = globals().get("_LOCATION_CODE", "test1")
_project_root = Path(globals().get("_PROJECT_ROOT",
                                    Path(__file__).parent.parent))

location_dir = _project_root / "location" / _location_code
meta_path = location_dir / f"sat_capture_meta.json"
clean_img_path = location_dir / f"sat_clean_{_location_code}.png"

# fallback to raw if clean doesn't exist yet
if not clean_img_path.exists():
    clean_img_path = location_dir / f"sat_raw_{_location_code}.png"

if not meta_path.exists():
    raise FileNotFoundError(f"Meta file not found: {meta_path}")
if not clean_img_path.exists():
    raise FileNotFoundError(f"Image not found: {clean_img_path}")

meta = json.loads(meta_path.read_text())
px_per_m = meta["px_per_meter"]
img_w = meta["img_w"]
img_h = meta["img_h"]

width_m = img_w / px_per_m
height_m = img_h / px_per_m

print(f"[blender_ground] code={_location_code}  "
      f"plane size: {width_m:.1f} x {height_m:.1f} m  "
      f"px_per_m={px_per_m:.2f}")

# --- remove existing ground plane for this code ---
obj_name = f"GroundPlane_{_location_code}"
if obj_name in bpy.data.objects:
    bpy.data.objects.remove(bpy.data.objects[obj_name], do_unlink=True)

# --- create plane ---
# Blender creates a 2x2 unit plane by default
bpy.ops.mesh.primitive_plane_add(size=1, enter_editmode=False, location=(0, 0, 0))
plane = bpy.context.active_object
plane.name = obj_name

# scale to actual meters
plane.scale.x = width_m
plane.scale.y = height_m

# move so top-left corner is at world origin:
# default plane center is at (0,0,0) with scale → center at (width_m/2, height_m/2)
# we want top-left at (0,0), so center at (width_m/2, height_m/2)
plane.location.x = width_m / 2
plane.location.y = height_m / 2
plane.location.z = -0.01  # just below z=0 so vehicles sit on top

bpy.ops.object.transform_apply(scale=True, location=False, rotation=False)

# --- UV: reset to simple box projection ---
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.uv.reset()
bpy.ops.object.mode_set(mode="OBJECT")

# --- material with emission (unlit) ---
mat_name = f"GroundMat_{_location_code}"
if mat_name in bpy.data.materials:
    bpy.data.materials.remove(bpy.data.materials[mat_name])

mat = bpy.data.materials.new(name=mat_name)
mat.use_nodes = True
mat.blend_method = "OPAQUE"

nodes = mat.node_tree.nodes
links = mat.node_tree.links
nodes.clear()

img_node = nodes.new("ShaderNodeTexImage")
img_node.location = (-300, 0)

# load image (reload if already in memory)
img_name = clean_img_path.name
if img_name in bpy.data.images:
    bpy.data.images.remove(bpy.data.images[img_name])
blender_img = bpy.data.images.load(str(clean_img_path))
img_node.image = blender_img

emit_node = nodes.new("ShaderNodeEmission")
emit_node.location = (0, 0)
emit_node.inputs["Strength"].default_value = 1.0

output_node = nodes.new("ShaderNodeOutputMaterial")
output_node.location = (300, 0)

links.new(img_node.outputs["Color"], emit_node.inputs["Color"])
links.new(emit_node.outputs["Emission"], output_node.inputs["Surface"])

plane.data.materials.append(mat)

print(f"[blender_ground] Created '{obj_name}' — plane {width_m:.1f}x{height_m:.1f}m")
print(f"[blender_ground] Image: {clean_img_path.name}")
