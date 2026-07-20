#!/usr/bin/env python3
"""半自動場景包產生器：軌跡 JSON + 地面圖資訊 → scenes/<code>/。

用法：
  列出軌跡內的 track（人工挑 collider 用）:
    python3 tools/build_scene.py --trajectory T.json --list
  產生場景包（衛星 pipeline 輸出當地面）:
    python3 tools/build_scene.py --code tainan_yongkang --trajectory T.json \
        --sat-dir satellite_pipeline/output/tainan_yongkang \
        --collider 1:Car --collider 2:Two_Wheeler --source-collision 100
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

SCHEMA_VERSION = 1
REQUIRED_KEYS = ["code", "ground", "origin_offset_m", "frames", "vehicles", "collision"]
SAT_VARIANTS = ["sat_genai.png", "sat_clean.png", "sat_raw.png"]

# 車種預設（model / 質量 kg / 車長 m / 預設車速 km/h / pre_samples）
CLASS_DEFAULTS = {
    "Car":         ("car.glb", 1500, 3.8, 20, 15),
    "SUV":         ("car.glb", 1800, 4.6, 20, 15),
    "Van":         ("car.glb", 2000, 4.8, 20, 15),
    "Truck":       ("car.glb", 5000, 7.0, 20, 15),
    "Bus":         ("car.glb", 11000, 11.0, 20, 15),
    "Two_Wheeler": ("moto.glb", 200, 1.7, 40, 4),
}


class SceneBuildError(Exception):
    pass


def list_tracks(trajectory):
    stats = {}
    for frame in trajectory["frames"]:
        for obj in frame["objects"]:
            tid = obj.get("tracked_id")
            if tid is None or "position_m" not in obj or obj["position_m"] is None:
                continue
            rec = stats.setdefault(tid, {"track_id": tid, "cls": obj.get("class", "?"),
                                         "frames_present": 0, "first": frame["frame_index"],
                                         "last": frame["frame_index"]})
            rec["frames_present"] += 1
            rec["last"] = frame["frame_index"]
    return sorted(stats.values(), key=lambda r: -r["frames_present"])


def build(trajectory, code, ground_image, px_per_meter, size_m, colliders,
          source_collision, anim=(1, 32, 89), name=None):
    tracks = {t["track_id"]: t for t in list_tracks(trajectory)}
    frames_idx = [f["frame_index"] for f in trajectory["frames"] if f["objects"]]
    if not frames_idx:
        raise SceneBuildError("軌跡 JSON 沒有任何有 objects 的 frame")
    src_start, src_end = min(frames_idx), max(frames_idx)
    if not (src_start <= source_collision <= src_end):
        raise SceneBuildError(f"source_collision {source_collision} 不在 [{src_start},{src_end}]")

    vehicles = []
    for tid, cls in colliders:
        if tid not in tracks:
            raise SceneBuildError(f"collider track_id {tid} 不存在於軌跡（有：{sorted(tracks)}）")
        if cls not in CLASS_DEFAULTS:
            raise SceneBuildError(f"未知車種 {cls}（支援：{sorted(CLASS_DEFAULTS)}）")
        model, mass, length, speed, samples = CLASS_DEFAULTS[cls]
        label = "汽車" if model == "car.glb" else "機車"
        vehicles.append({"track_id": tid, "class": cls, "label": label, "model": model,
                         "mass_kg": mass, "length_m": length, "role": "collider",
                         "default_speed_kmh": speed, "pre_samples": samples})

    return {
        "schema_version": SCHEMA_VERSION,
        "code": code,
        "name": name or f"{code} 事故重建",
        "ground": {"image": ground_image, "px_per_meter": px_per_meter,
                   "size_m": [float(size_m[0]), float(size_m[1])]},
        "origin_offset_m": [size_m[0] / 2, size_m[1] / 2],
        "frames": {"source_start": src_start, "source_collision": source_collision,
                   "source_end": src_end, "anim_start": anim[0],
                   "anim_collision": anim[1], "anim_end": anim[2], "fps": 30},
        "vehicles": vehicles,
        "extras": "auto",
        "collision": {"restitution": 0.15, "friction": 0.7},
        "camera": {"default": "persp45"},
    }


def validate_scene(cfg):
    errs = [f"缺欄位: {k}" for k in REQUIRED_KEYS if k not in cfg]
    vehicles = cfg.get("vehicles", [])
    n_col = sum(1 for v in vehicles if v.get("role") == "collider")
    if n_col != 2:
        errs.append(f"需要恰好 2 台 role=collider，目前 {n_col}")
    for v in vehicles:
        for k in ("track_id", "class", "model", "mass_kg", "length_m"):
            if k not in v:
                errs.append(f"vehicle {v.get('track_id', '?')} 缺 {k}")
    f = cfg.get("frames", {})
    for k in ("source_start", "source_collision", "source_end",
              "anim_start", "anim_collision", "anim_end"):
        if k not in f:
            errs.append(f"frames 缺 {k}")
    return errs


def pick_sat(sat_dir):
    sat_dir = Path(sat_dir)
    meta = json.loads((sat_dir / "meta.json").read_text())
    for variant in SAT_VARIANTS:
        if (sat_dir / variant).exists():
            return sat_dir / variant, meta
    raise SceneBuildError(f"{sat_dir} 內找不到 {SAT_VARIANTS}")


def parse_collider(text):
    tid, cls = text.split(":", 1)
    return int(tid), cls


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trajectory", required=True)
    ap.add_argument("--list", action="store_true", help="列出 track 後結束")
    ap.add_argument("--code")
    ap.add_argument("--sat-dir", help="satellite_pipeline 輸出目錄（自動讀 meta.json）")
    ap.add_argument("--ground-image", help="手動指定地面圖（與 --px-per-meter/--size-m 併用）")
    ap.add_argument("--px-per-meter", type=float)
    ap.add_argument("--size-m", nargs=2, type=float, metavar=("W", "H"))
    ap.add_argument("--collider", action="append", default=[], metavar="ID:CLASS")
    ap.add_argument("--source-collision", type=int)
    ap.add_argument("--anim", default="1,32,89")
    ap.add_argument("--name")
    ap.add_argument("--out", default="scenes")
    args = ap.parse_args(argv)

    trajectory = json.loads(Path(args.trajectory).read_text())
    if args.list:
        for t in list_tracks(trajectory):
            print(f"track {t['track_id']:>5}  {t['cls']:<12} "
                  f"frames {t['frames_present']:>4}  [{t['first']}–{t['last']}]")
        return 0

    if not (args.code and args.collider and args.source_collision is not None):
        ap.error("產生模式需要 --code、至少兩個 --collider、--source-collision")
    if args.sat_dir:
        src_img, meta = pick_sat(args.sat_dir)
        px, size = meta["px_per_meter"], [meta["size_m"], meta["size_m"]]
    elif args.ground_image and args.px_per_meter and args.size_m:
        src_img, px, size = Path(args.ground_image), args.px_per_meter, args.size_m
    else:
        ap.error("需要 --sat-dir 或（--ground-image + --px-per-meter + --size-m）")

    cfg = build(trajectory=trajectory, code=args.code, ground_image="ground.png",
                px_per_meter=px, size_m=size,
                colliders=[parse_collider(c) for c in args.collider],
                source_collision=args.source_collision,
                anim=tuple(int(x) for x in args.anim.split(",")), name=args.name)
    errs = validate_scene(cfg)
    if errs:
        raise SceneBuildError("; ".join(errs))

    out = Path(args.out) / args.code
    out.mkdir(parents=True, exist_ok=True)
    (out / "scene.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy(src_img, out / "ground.png")
    shutil.copy(args.trajectory, out / "trajectory.json")
    print(f"場景包已產生：{out}/（scene.json + ground.png + trajectory.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
