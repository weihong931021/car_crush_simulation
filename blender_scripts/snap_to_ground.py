"""
車輛放置工具：
  - snap_to_ground()      貼到 Z=0 地板
  - scale_to_length()     依真實長度精確縮放
  - place_vehicle()       縮放 + 貼地一次完成（主要入口）
"""
import bpy
from mathutils import Vector


# ── bounding box 工具 ──────────────────────────────────────────────────────

def _get_world_bbox(root_obj):
    """回傳整個 hierarchy 的世界座標 bounding box (min, max) Vector。"""
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


# ── 縮放 ───────────────────────────────────────────────────────────────────

def scale_to_length(root_obj, target_length_m):
    """
    把 root_obj 縮放到讓水平最長邊 == target_length_m。
    縮放後需重新 snap_to_ground，因為 Z 也會跟著變。
    回傳 scale factor。
    """
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


# ── 貼地 ───────────────────────────────────────────────────────────────────

def snap_to_ground(root_obj, ground_z=0.0):
    """將 root_obj 底部貼到 ground_z，回傳 Z 偏移量。"""
    mn, _ = _get_world_bbox(root_obj)
    if mn.x == float('inf'):
        return 0.0
    offset = ground_z - mn.z
    if abs(offset) > 0.001:
        root_obj.location.z += offset
    return offset


# ── 主入口：縮放 + 貼地 ────────────────────────────────────────────────────

def place_vehicle(root_obj, target_length_m, ground_z=0.0):
    """
    依真實車長縮放，並貼到地板。
    回傳 { scale_factor, z_offset, final_dims }。
    """
    factor = scale_to_length(root_obj, target_length_m)
    z_off  = snap_to_ground(root_obj, ground_z)
    mn, mx = _get_world_bbox(root_obj)
    return {
        "name":         root_obj.name,
        "scale_factor": round(factor, 6),
        "z_offset_m":   round(z_off, 4),
        "final_dims_m": {
            "length": round(max(mx.x - mn.x, mx.y - mn.y), 3),
            "width":  round(min(mx.x - mn.x, mx.y - mn.y), 3),
            "height": round(mx.z - mn.z, 3),
        },
    }


# ── 場景批次貼地（不縮放）─────────────────────────────────────────────────

def snap_roots_to_ground(ground_z=0.0, exclude_names=("SatPlane", "Floor")):
    """把場景裡所有根節點（排除地板）貼到 ground_z。"""
    skip = set(exclude_names)
    roots = [
        o for o in bpy.context.scene.objects
        if o.parent is None
        and o.type not in ('CAMERA', 'LIGHT', 'EMPTY')
        and o.name not in skip
    ]
    results = []
    for root in roots:
        offset = snap_to_ground(root, ground_z)
        results.append({"name": root.name, "offset_m": round(offset, 4)})
    return results


if __name__ == "__main__":
    results = snap_roots_to_ground()
    for r in results:
        print(f"  {r['name']}: moved {r['offset_m']:+.4f}m")
    if not results:
        print("  No objects to snap.")
