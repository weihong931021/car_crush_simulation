"""
通用車輛匯入腳本。
用法：
    python import_vehicle.py --class Car
    python import_vehicle.py --class Two_Wheeler
    python import_vehicle.py --class Car --uid <自訂UID> --name "MyCar"
    python import_vehicle.py --class Car --no-export   # 只匯入不匯出 GLB
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from vehicle_specs import get_spec

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THREEJS_DIR  = os.path.join(PROJECT_ROOT, "threejs")

# Blender 端執行的 place_vehicle 程式碼（內嵌，避免路徑問題）
PLACE_CODE = """
import bpy
from mathutils import Vector

def _get_world_bbox(root_obj):
    mn = Vector((float('inf'),) * 3)
    mx = Vector((float('-inf'),) * 3)
    for obj in [root_obj] + list(root_obj.children_recursive):
        if obj.type == 'MESH':
            for corner in obj.bound_box:
                wc = obj.matrix_world @ Vector(corner)
                mn.x = min(mn.x, wc.x); mx.x = max(mx.x, wc.x)
                mn.y = min(mn.y, wc.y); mx.y = max(mx.y, wc.y)
                mn.z = min(mn.z, wc.z); mx.z = max(mx.z, wc.z)
    return mn, mx

def scale_to_length(root_obj, target_length_m):
    mn, mx = _get_world_bbox(root_obj)
    if mn.x == float('inf'):
        return 1.0
    current_length = max(mx.x - mn.x, mx.y - mn.y)
    if current_length < 0.001:
        return 1.0
    factor = target_length_m / current_length
    root_obj.scale = tuple(s * factor for s in root_obj.scale)
    bpy.context.view_layer.update()
    return factor

def snap_to_ground(root_obj, ground_z=0.0):
    mn, _ = _get_world_bbox(root_obj)
    if mn.x == float('inf'):
        return 0.0
    offset = ground_z - mn.z
    if abs(offset) > 0.001:
        root_obj.location.z += offset
    return offset

# 找最新匯入的根節點（排除地板、燈光、攝影機）
EXCLUDE = {"SatPlane", "Floor"}
roots = [
    o for o in bpy.context.scene.objects
    if o.parent is None
    and o.type not in ('CAMERA', 'LIGHT')
    and o.name not in EXCLUDE
]

if not roots:
    print("ERROR: no root objects found")
else:
    root = roots[-1]  # 最後匯入的
    factor = scale_to_length(root, TARGET_LENGTH_M)
    z_off  = snap_to_ground(root)
    mn, mx = _get_world_bbox(root)
    print(f"Vehicle: {root.name}")
    print(f"  scaled x{factor:.4f} → length {max(mx.x-mn.x, mx.y-mn.y):.3f}m")
    print(f"  snapped Z {z_off:+.4f}m → bottom at 0")
    print(f"  final dims: {max(mx.x-mn.x,mx.y-mn.y):.2f}L x {min(mx.x-mn.x,mx.y-mn.y):.2f}W x {mx.z-mn.z:.2f}H m")
"""

EXPORT_CODE = """
import bpy, os

glb_path = GLB_PATH_PLACEHOLDER

# 選取車輛 hierarchy（排除地板）
EXCLUDE = {"SatPlane", "Floor"}
roots = [o for o in bpy.context.scene.objects
         if o.parent is None and o.type not in ('CAMERA', 'LIGHT') and o.name not in EXCLUDE]

if not roots:
    print("ERROR: no vehicle to export")
else:
    bpy.ops.object.select_all(action='DESELECT')
    root = roots[-1]
    for obj in [root] + list(root.children_recursive):
        obj.select_set(True)
    bpy.context.view_layer.objects.active = root

    os.makedirs(os.path.dirname(glb_path), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format='GLB',
        export_apply=False,
        use_selection=True,
    )
    print(f"Exported → {glb_path}")
"""


async def import_vehicle(vehicle_class: str, uid: str | None = None, name: str | None = None, export: bool = True):
    spec = get_spec(vehicle_class)
    uid = uid or spec.get("sketchfab_uid")
    if not uid:
        raise ValueError(f"No Sketchfab UID for {vehicle_class}. Provide --uid.")

    target_length = spec["length_m"]
    glb_filename  = spec["glb_filename"]
    glb_path      = os.path.join(THREEJS_DIR, glb_filename)
    label = name or vehicle_class

    server_params = StdioServerParameters(
        command="uvx",
        args=["blender-mcp", "--port", "9876"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print(f"[1/3] Downloading {label} (UID: {uid}, target ~{target_length}m)...")
            result = await session.call_tool(
                "download_sketchfab_model",
                arguments={
                    "uid": uid,
                    "target_size": target_length,
                    "user_prompt": f"Import {label}",
                }
            )
            for c in result.content:
                if c.type == "text":
                    print(c.text)

            print(f"[2/3] Scaling to {target_length}m + snap to ground...")
            code = PLACE_CODE.replace("TARGET_LENGTH_M", str(target_length))
            snap_result = await session.call_tool(
                "execute_blender_code",
                arguments={
                    "code": code,
                    "user_prompt": f"Scale {label} to real dimensions and place on ground",
                }
            )
            for c in snap_result.content:
                if c.type == "text":
                    print(c.text)

            if export:
                print(f"[3/3] Exporting GLB → threejs/{glb_filename} ...")
                export_code = EXPORT_CODE.replace("GLB_PATH_PLACEHOLDER", repr(glb_path))
                export_result = await session.call_tool(
                    "execute_blender_code",
                    arguments={
                        "code": export_code,
                        "user_prompt": f"Export {label} as GLB to threejs/",
                    }
                )
                for c in export_result.content:
                    if c.type == "text":
                        print(c.text)


def main():
    parser = argparse.ArgumentParser(description="Import a Sketchfab vehicle with real-world scale")
    parser.add_argument("--class", dest="vehicle_class", required=True,
                        help="Vehicle class: Car, Two_Wheeler, SUV, Van, Truck, Bus")
    parser.add_argument("--uid", default=None, help="Override Sketchfab UID")
    parser.add_argument("--name", default=None, help="Display name for logs")
    parser.add_argument("--no-export", dest="export", action="store_false",
                        help="Skip GLB export to threejs/")
    args = parser.parse_args()
    asyncio.run(import_vehicle(args.vehicle_class, args.uid, args.name, args.export))


if __name__ == "__main__":
    main()
