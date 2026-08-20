#!/usr/bin/env python3
"""把合成軌跡擺到真實衛星底圖的路面上（PoC 展示用）。

用法：
    python3 tools/place_synth_trajectory.py <碰撞點x> <碰撞點z> <track1角度> <track2角度> <輸出.json>
    # 目前 tainan_yongkong 用的參數（角度單位：度）：
    python3 tools/place_synth_trajectory.py 16.6 17.0 0 -60 /tmp/traj_placed.json
    python3 tools/build_scene.py --code tainan_yongkong --trajectory /tmp/traj_placed.json \
        --sat-dir satellite_pipeline/output/tainan_yongkong \
        --collider 1:Car --collider 2:Two_Wheeler --source-collision 100

角度是看渲染截圖調出來的，不是算出來的——主幹道在路口會轉彎，一條直線沒辦法兩頭都
貼齊路面，所以只對齊**進場那半**（播放器本來就只播到碰撞瞬間）。第一版 -49.6° 會讓
機車壓在路緣上，-60° 才整段在柏油上。

合成軌跡是正交的（汽車走 +z、機車走 +x），而真實路口是 Y 字形：上方一條直路、
主幹道從左下往右上斜切。所以只平移會讓車開在草地上，必須**逐 track 繞碰撞點旋轉**
——繞同一個點轉，兩台車在 frame 100 仍然在同一位置相撞，碰撞結論不受影響。

這是合成資料的**視覺擺位**，不是量測。位置沒有 ground truth，也不宣稱有。
"""
import json, math, sys
from pathlib import Path

SRC = Path("scenes/tainan_yongkang/trajectory.json")
COLLISION_FRAME = 100
PPM = 29.113                      # 與新底圖 meta.json 一致
DROP_TRACKS = {9}                 # 對向車：原本在 x=18.5 的直路上，新底圖那條路只有 ~3.4m 寬，擺不下

# 目標碰撞點（公尺，底圖左上角為原點）與各 track 的行進方向旋轉量（度）
TARGET = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (16.14, 16.5)
ROT = {1: float(sys.argv[3]) if len(sys.argv) > 3 else 0.0,      # 汽車：沿上方直路往下
       2: float(sys.argv[4]) if len(sys.argv) > 4 else -49.6}    # 機車：沿主幹道往右上

data = json.loads(SRC.read_text())

# 碰撞點＝frame 100 時兩台 collider 的中點
at100 = {o["tracked_id"]: o["position_m"]
         for f in data["frames"] if f["frame_index"] == COLLISION_FRAME
         for o in f["objects"]}
px0 = (at100[1][0] + at100[2][0]) / 2
pz0 = (at100[1][1] + at100[2][1]) / 2
print(f"原碰撞點 ({px0:.2f}, {pz0:.2f}) → 目標 ({TARGET[0]:.2f}, {TARGET[1]:.2f})")

def xform(pos, tid):
    th = math.radians(ROT.get(tid, ROT[2]))
    dx, dz = pos[0] - px0, pos[1] - pz0
    rx = dx * math.cos(th) - dz * math.sin(th)
    rz = dx * math.sin(th) + dz * math.cos(th)
    return [TARGET[0] + rx, TARGET[1] + rz]

out_frames, ranges = [], {}
for f in data["frames"]:
    objs = []
    for o in f["objects"]:
        tid = o["tracked_id"]
        if tid in DROP_TRACKS:
            continue
        p = xform(o["position_m"], tid)
        objs.append({**o, "position_m": p})
        r = ranges.setdefault(tid, [p[0], p[0], p[1], p[1]])
        r[0], r[1] = min(r[0], p[0]), max(r[1], p[0])
        r[2], r[3] = min(r[2], p[1]), max(r[3], p[1])
    out_frames.append({"frame_index": f["frame_index"], "objects": objs})

data["frames"] = out_frames
data["location_code"] = "tainan_yongkong"
dst = Path(sys.argv[5] if len(sys.argv) > 5 else "/tmp/traj_placed.json")
dst.write_text(json.dumps(data, ensure_ascii=False))

print(f"\n{'track':>6}  {'x 範圍 (m)':<18} {'z 範圍 (m)':<18}  起點像素      終點像素")
for tid, (x0, x1, z0, z1) in sorted(ranges.items()):
    first = [o for f in out_frames for o in f["objects"] if o["tracked_id"] == tid][0]["position_m"]
    last  = [o for f in out_frames for o in f["objects"] if o["tracked_id"] == tid][-1]["position_m"]
    inb = "✓" if 0 <= x0 and x1 <= 35 and 0 <= z0 and z1 <= 35 else "✗ 出界"
    print(f"{tid:>6}  {x0:6.2f}~{x1:6.2f} {inb:<7} {z0:6.2f}~{z1:6.2f}       "
          f"({first[0]*PPM:4.0f},{first[1]*PPM:4.0f})  ({last[0]*PPM:4.0f},{last[1]*PPM:4.0f})")
print(f"\n已寫入 {dst}")
