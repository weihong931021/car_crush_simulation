# 衛星圖貼到 Blender 3D 地板平面

## 前置資訊

- 衛星圖：`image.png`（1515×1038 px，銳化版）
- 比例尺：`px_per_meter = 31.10`（1515 / 48.71m）
- 平面實際尺寸：48.71m（寬）× 33.36m（高）— 與舊圖相同物理範圍
- 座標系：平面置中於世界原點 `(0, 0, 0)`；衛星圖左上角對應 Blender `(-24.35, +16.68, 0)`

## 衛星圖座標轉換公式

```
sat_coords (px)  →  Blender world coords (m)
  world_x = sat_x / 31.10 - 24.35
  world_y = -(sat_y / 31.10 - 16.68)
```

## 步驟

### Step 1：清場

```python
import bpy
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
```

### Step 2：建立地面平面（正確尺寸）

```python
import bpy

px_per_meter = 31.10
img_w, img_h = 1515, 1038
width  = img_w / px_per_meter   # 48.71 m
height = img_h / px_per_meter   # 33.36 m

bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0))
plane = bpy.context.active_object
plane.name = 'SatPlane'
plane.scale = (width, height, 1)
bpy.ops.object.transform_apply(scale=True)
```

### Step 3：建立材質並套用衛星圖

```python
import bpy

plane = bpy.data.objects['SatPlane']
img_path = '/Users/weihong/Documents/blender_crash_project/scenes/test1/ground.png'

mat = bpy.data.materials.new(name="SatMat")
mat.use_nodes = True
nodes = mat.node_tree.nodes
links = mat.node_tree.links
nodes.clear()

tex_node = nodes.new('ShaderNodeTexImage')
bsdf     = nodes.new('ShaderNodeBsdfPrincipled')
output   = nodes.new('ShaderNodeOutputMaterial')

img = bpy.data.images.load(img_path)
tex_node.image = img

links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

plane.data.materials.clear()
plane.data.materials.append(mat)
```

### Step 4：修正 UV（重要）

預設 `unwrap` 可能產生偏移，必須手動 reset 為正確的 0–1 映射：

```python
import bpy

plane = bpy.data.objects['SatPlane']
bpy.context.view_layer.objects.active = plane
bpy.ops.object.editmode_toggle()
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.reset()   # 讓整張圖完整對應整個平面
bpy.ops.object.editmode_toggle()
```

### Step 5：加燈光與俯視攝影機

```python
import bpy

# 太陽燈
bpy.ops.object.light_add(type='SUN', location=(0, 0, 20))
bpy.context.active_object.data.energy = 2.0

# 俯視正交攝影機
bpy.ops.object.camera_add(location=(0, 0, 40))
cam = bpy.context.active_object
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 50
bpy.context.scene.camera = cam
```

### Step 6：切換 Viewport 到俯視 + 材質預覽

```python
import bpy

for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        with bpy.context.temp_override(area=area, region=area.regions[-1]):
            bpy.ops.view3d.view_axis(type='TOP', align_active=False)
            bpy.ops.view3d.view_all()
        for space in area.spaces:
            if space.type == 'VIEW_3D':
                space.shading.type = 'MATERIAL'
        break
```

## 注意事項

- `bpy.ops.uv.unwrap()` 會產生錯誤偏移，**必須改用 `bpy.ops.uv.reset()`**
- 若要在同一場景放車輛，用上方座標轉換公式將 `sat_coords` 轉成 Blender 世界座標
- `meta.px_per_meter` 是對應**衛星圖**解析度，不是影片（1920×1080）的 px/m
