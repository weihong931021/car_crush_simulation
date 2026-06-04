import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SNAP_TO_GROUND_CODE = """
import bpy
from mathutils import Vector

def get_world_min_z(root_obj):
    min_z = float('inf')
    for obj in [root_obj] + list(root_obj.children_recursive):
        if obj.type == 'MESH':
            bbox_world = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            min_z = min(min_z, min(v.z for v in bbox_world))
    return min_z

# 找最上層沒有 parent 的物件（匯入的根節點）
roots = [o for o in bpy.context.scene.objects if o.parent is None and o.type != 'CAMERA' and o.type != 'LIGHT']

snapped = []
for root in roots:
    min_z = get_world_min_z(root)
    if min_z != float('inf') and abs(min_z) > 0.001:
        root.location.z -= min_z
        snapped.append(f"{root.name}: moved up {-min_z:.3f}m")

print("Snap to ground:", snapped if snapped else "nothing moved (already on ground)")
"""

async def import_tesla():
    server_params = StdioServerParameters(
        command="uvx",
        args=["blender-mcp", "--port", "9876"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("Downloading and importing Tesla 2018 Model 3 (4.5m)...")
            result = await session.call_tool(
                "download_sketchfab_model",
                arguments={
                    "uid": "5ef9b845aaf44203b6d04e2c677e444f",
                    "target_size": 4.5,
                    "user_prompt": "Import the Tesla 2018 Model 3"
                }
            )
            for content in result.content:
                if content.type == "text":
                    print(content.text)

            print("Snapping vehicle to ground plane...")
            snap_result = await session.call_tool(
                "execute_blender_code",
                arguments={
                    "code": SNAP_TO_GROUND_CODE,
                    "user_prompt": "Snap imported vehicle to Z=0 ground plane"
                }
            )
            for content in snap_result.content:
                if content.type == "text":
                    print(content.text)

if __name__ == "__main__":
    asyncio.run(import_tesla())
