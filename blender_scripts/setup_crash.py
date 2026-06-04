import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def setup_crash():
    server_params = StdioServerParameters(
        command="uvx",
        args=["blender-mcp", "--port", "9876"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            code = """
import bpy
import math

# 1. Clear any partially created crash objects
for name in ["Tesla_Cybertruck_1", "Tesla_Cybertruck_2", "Floor"]:
    if name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)

# 2. Force find ALL meshes by looking at data blocks if objects are hidden/nested
all_meshes = [obj for obj in bpy.data.objects if obj.type == 'MESH']

if not all_meshes:
    print("Could not find any mesh objects in the scene.")
else:
    # 3. Join all existing meshes into a single car object
    bpy.ops.object.select_all(action='DESELECT')
    for obj in all_meshes:
        obj.select_set(True)
    
    bpy.context.view_layer.objects.active = all_meshes[0]
    bpy.ops.object.join()
    car1 = bpy.context.active_object
    car1.name = "Tesla_Cybertruck_1"
    car1.parent = None
    
    # Move it to a clear start position
    car1.location = (0, -10, 1.1)
    car1.rotation_euler = (0, 0, math.radians(90))

    # 4. Create the second car by duplicating the first
    bpy.ops.object.select_all(action='DESELECT')
    car1.select_set(True)
    bpy.ops.object.duplicate()
    car2 = bpy.context.active_object
    car2.name = "Tesla_Cybertruck_2"

    # Position car 2 face-to-face
    car2.location = (0, 10, 1.1)
    car2.rotation_euler = (0, 0, math.radians(-90))

    # 5. Add Floor
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0,0,0))
    floor = bpy.context.active_object
    floor.name = "Floor"

    # 6. Set up Rigid Body
    if not bpy.context.scene.rigidbody_world:
        bpy.ops.rigidbody.world_add()
    
    # Set Floor to Passive
    bpy.ops.rigidbody.object_add()
    floor.rigid_body.type = 'PASSIVE'

    # Set Cars to Active
    for car in [car1, car2]:
        bpy.ops.object.select_all(action='DESELECT')
        car.select_set(True)
        bpy.context.view_layer.objects.active = car
        bpy.ops.rigidbody.object_add()
        car.rigid_body.collision_shape = 'CONVEX_HULL'
        car.rigid_body.mass = 2000

    # 7. Animation "Push"
    bpy.context.scene.frame_set(1)
    for car, start_y in [(car1, -10), (car2, 10)]:
        car.location.y = start_y
        car.rigid_body.kinematic = True
        car.keyframe_insert(data_path="location", index=1)
        car.keyframe_insert(data_path="rigid_body.kinematic")

    bpy.context.scene.frame_set(10)
    for car, end_y in [(car1, -2), (car2, 2)]:
        car.location.y = end_y
        car.rigid_body.kinematic = False
        car.keyframe_insert(data_path="location", index=1)
        car.keyframe_insert(data_path="rigid_body.kinematic")

    bpy.context.scene.frame_set(1)
    print("Head-on crash simulation set up! Press SPACE in Blender to watch.")
"""
            result = await session.call_tool(
                "execute_blender_code",
                arguments={"code": code, "user_prompt": "Final crash simulation setup with deep mesh search"}
            )
            
            for content in result.content:
                if content.type == "text":
                    print(content.text)

if __name__ == "__main__":
    asyncio.run(setup_crash())
