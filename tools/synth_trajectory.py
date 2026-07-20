#!/usr/bin/env python3
"""產生 filtered_output 相容的合成軌跡（驗證換場景用）。

場景：25×25m 路口。汽車(1)沿 +y 直行、機車(2)沿 +x 橫越，frame 100 在 (12.5, 12.5)
附近相撞；另一台汽車(9)在遠車道通過（extras 驗證用）。
"""
import argparse
import json
import math
from pathlib import Path


def make(frames_total=200, collision_frame=100):
    frames = []
    for i in range(1, frames_total + 1):
        objects = []
        # track 1: 汽車，沿 +y，等速 ~8 m/s @ 25fps 等效
        y = 2.0 + (i / collision_frame) * 10.5
        objects.append({"tracked_id": 1, "class": "Car", "position_m": [12.3, y]})
        # track 2: 機車，沿 +x，frame 30 出現
        if i >= 30:
            x = 2.0 + ((i - 30) / (collision_frame - 30)) * 10.3
            objects.append({"tracked_id": 2, "class": "Two_Wheeler", "position_m": [x, 12.8]})
        # track 9: 對向車道通過（純 extras）
        if 20 <= i <= 180:
            objects.append({"tracked_id": 9, "class": "Car",
                            "position_m": [18.5, 24.0 - (i - 20) * 0.13]})
        frames.append({"frame_index": i, "objects": objects})
    # selected_tracked_ids 是碰撞參與者（collider）名單，不是 extras 白名單——
    # 真實 filtered_output.json 裡只會列 1、2 這兩台碰撞車，track 9 不列入是正常的。
    return {"meta": {"px_per_meter": 29.113, "fps": 25.0}, "location_code": "synth",
            "frames": frames, "selected_tracked_ids": [1, 2]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/synth_trajectory.json")
    args = ap.parse_args()
    Path(args.out).write_text(json.dumps(make(), ensure_ascii=False))
    print(f"合成軌跡已寫入 {args.out}（碰撞 frame=100）")


if __name__ == "__main__":
    main()
