#!/usr/bin/env python3
"""半自動場景包產生器：軌跡 JSON + 地面圖資訊 → scenes/<code>/。

用法：
  列出軌跡內的 track（人工挑 collider 用）:
    python3 tools/build_scene.py --trajectory T.json --list
  產生場景包（**真實影片**：地面＝G-projection 的校正參考圖，尺度自動算）:
    python3 tools/build_scene.py --code taipei-cm --trajectory T.json \
        --location-dir trafficlab-project/location/taipei-cm \
        --collider 1:car --collider 53:car --source-collision 180
  產生場景包（**合成軌跡**：衛星 pipeline 輸出當地面）:
    python3 tools/build_scene.py --code tainan_yongkang --trajectory T.json \
        --sat-dir workbench/output/tainan_yongkang \
        --collider 1:Car --collider 2:Two_Wheeler --source-collision 100

--sat-dir 只適用於**在衛星座標系合成的軌跡**；真實影片的 position_m 活在校正參考圖的
平面上，用新擷取的衛星圖會換一個座標系導致車輛錯位，請走 --location-dir。
"""
import argparse
import json
import math
import shutil
import struct
import sys
import warnings
from pathlib import Path

SCHEMA_VERSION = 1
REQUIRED_KEYS = ["code", "ground", "origin_offset_m", "frames", "vehicles", "collision"]
# 地面圖優先序：genai > clean > raw。**這條路徑上畫質優先是對的，不要「修」它。**
#
# 為什麼 genai 排第一不違反座標安全（2026-08-18 走了一趟冤枉路後補的說明）：
# pick_sat() 只有 `--sat-dir` 那一支呼叫，而 --sat-dir **只適用於在衛星座標系合成的
# 軌跡**（tainan_yongkang）——那種軌跡的 position_m 是直接以公尺編出來的名目座標，
# 不是從這張圖上量出來的，所以 genai 重畫造成的 0.20 m 局部位移不影響任何結論。
# 真實影片走的是另一支 from_location_dir()，用 G-projection 的校正參考圖，
# genai 從來就不在那條路上（image_enhance 的 --input 路徑也明文禁用 --genai）。
#
# 實測代價（若誤改成 clean 優先）：tainan_yongkang 的 sat_clean 帶著 38 個去車 inpaint
# 塗抹（多數是斑馬線／陰影誤報），渲染出來路口糊成一片、Google 浮水印也跑出來；
# 而 repo 內另外 5 個地點（banqiao_xianmin / chiayi_fountain / kaohsiung_wufu /
# taipei_nanjing / taipei_sogo）根本沒有 sat_clean，會靜默掉到 sat_raw ——車還在路上。
SAT_VARIANTS = ["sat_genai.png", "sat_clean.png", "sat_raw.png"]
DEFAULT_FPS = 30

# 車種預設（model / 質量 kg / 車長 m / 車寬 m / 預設車速 km/h / pre_samples）
CLASS_DEFAULTS = {
    "Car":         ("car.glb",  1500, 4.69, 1.85, 20, 15),
    "SUV":         ("car.glb",  1800, 4.60, 1.90, 20, 15),
    "Van":         ("car.glb",  2000, 4.80, 2.00, 20, 15),
    "Truck":       ("car.glb",  5000, 7.00, 2.50, 20, 15),
    "Bus":         ("car.glb", 11000, 11.00, 2.55, 20, 15),
    "Two_Wheeler": ("moto.glb",  200, 1.85, 0.70, 40, 4),
}

# 車種別名 → CLASS_DEFAULTS 的鍵。haware 管線輸出小寫 `car`，而 CLASS_DEFAULTS 是精確
# 字串比對的大寫鍵——不正規化的話真實影片的 collider 會直接被拒。
CLASS_ALIASES = {name.lower(): name for name in CLASS_DEFAULTS}
CLASS_ALIASES.update({
    "motor": "Two_Wheeler", "motorcycle": "Two_Wheeler", "motorbike": "Two_Wheeler",
    "scooter": "Two_Wheeler", "twowheeler": "Two_Wheeler",
    "pickup": "Van", "minivan": "Van", "lorry": "Truck", "coach": "Bus",
})


class SceneBuildError(Exception):
    pass


def normalize_class(cls):
    """把車種正規化成 CLASS_DEFAULTS 的鍵；無法對應回傳 None（比對不分大小寫）。"""
    if not isinstance(cls, str):
        return None
    key = cls.strip().lower().replace("-", "_").replace(" ", "_")
    return CLASS_ALIASES.get(key)


# 輪關鍵點索引（Apollo-24 的 front/rear × left/right）。輪子 h=0 是模板裡唯一實測而非
# 估計的高度，同側前後輪基線也最長，所以「有幾個輪點參與擬合」是定位可信度最強的指標。
# 與 trafficlab/motion/haware_localization.py 的 WHEEL_KP_IDX 一致。
WHEEL_KP_IDX = (7, 8, 18, 19)

# 挑 track 的建議門檻。實測（taipei-cm，以行進方向為獨立參考）：
#   spread > 8 m       → homography 已在外推，度量位置不可信（車長只有 3.8 m）
#   n_wheel_kp >= 2    → heading 中位誤差 2.42°、>90° 災難率 0%；0–1 個時約 98°
# 注意：輪點數那條是**相關性不是因果**（樣本與「距離近」高度混淆），當保守門檻用即可。
QUALITY_MAX_SPREAD_M = 8.0
QUALITY_MIN_WHEEL_KP = 2


def kp_quality(obj, px_per_meter):
    """算單一 object 的 (spread_m, n_wheel_kp)；沒有 kp_sat 時回傳 (None, None)。

    上游定位器現在會直接輸出這兩個欄位，有就直接用（避免定義漂移）。既有的
    trajectory.json 產生於那之前，但 `kp_sat` 本來就在裡面——所以這裡自己算，
    不必為了拿判據去重跑 pifpaf（1.5–2.5 秒/幀）。
    """
    if obj.get("spread_m") is not None and obj.get("n_wheel_kp") is not None:
        return float(obj["spread_m"]), int(obj["n_wheel_kp"])
    ks = obj.get("kp_sat")
    if not ks:
        return None, None
    n_wheel = sum(1 for i in WHEEL_KP_IDX if i < len(ks) and ks[i] is not None)
    pts = [p for p in ks if p is not None]
    if len(pts) < 2 or not px_per_meter:
        return 0.0, n_wheel
    worst = 0.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = math.dist(pts[i], pts[j])
            if d > worst:
                worst = d
    return worst / float(px_per_meter), n_wheel


def _median(values):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def resolve_fps(trajectory):
    """從 trajectory.meta.fps 取幀率，回傳 (fps, warning)。

    實證沒有一支影片是 30：test1 是 49.98、taipei-cm 是 23.0。寫死會讓整條時間軸錯，
    而且下游只會 console.warn，所以這裡缺失/無效時要明確回報。
    """
    meta = trajectory.get("meta") if isinstance(trajectory, dict) else None
    fps = (meta or {}).get("fps")
    if fps is None:
        return DEFAULT_FPS, f"trajectory.meta.fps 缺失，回退 {DEFAULT_FPS}（時間軸可能不準）"
    if isinstance(fps, bool) or not isinstance(fps, (int, float)):
        return DEFAULT_FPS, f"trajectory.meta.fps 型別無效（{fps!r}），回退 {DEFAULT_FPS}"
    if not math.isfinite(fps) or fps <= 0:
        return DEFAULT_FPS, f"trajectory.meta.fps 無效（{fps!r}），回退 {DEFAULT_FPS}"
    return (int(fps) if float(fps).is_integer() else float(fps)), None


def png_size(path):
    """讀 PNG 寬高（IHDR 位於簽名後第一個 chunk）。"""
    with open(path, "rb") as f:
        header = f.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise SceneBuildError(f"{path} 不是 PNG")
    w, h = struct.unpack(">II", header[16:24])
    return w, h


def scan_tracks(trajectory):
    """走訪軌跡統計每條 track，回傳 (tracks, diag)。

    隊友的輸出格式是**外部契約**，所以格式錯誤一律拋 SceneBuildError 並指名壞在哪，
    不要讓 raw KeyError 冒出來。缺 position_m 的 object 仍然跳過（部分幀缺是正常的），
    但會計數——否則「全部都缺」會以誤導的「collider track_id 不存在」浮出。
    """
    if not isinstance(trajectory, dict):
        raise SceneBuildError("軌跡 JSON 頂層必須是物件")
    if "frames" not in trajectory:
        raise SceneBuildError("軌跡 JSON 缺頂層 frames 欄位（隊友輸出格式契約）")
    frames = trajectory["frames"]
    if not isinstance(frames, list):
        raise SceneBuildError(f"軌跡 JSON 的 frames 必須是陣列（目前 {type(frames).__name__}）")

    ppm = (trajectory.get("meta") or {}).get("px_per_meter")
    stats = {}
    quality = {}                 # {tid: {"spread": [...], "wheel": [...]}}
    skipped_no_position = 0
    total_objects = 0
    for n, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise SceneBuildError(f"frames[{n}] 必須是物件（目前 {type(frame).__name__}）")
        if "frame_index" not in frame:
            raise SceneBuildError(f"frames[{n}] 缺 frame_index")
        if "objects" not in frame:
            raise SceneBuildError(f"frames[{n}]（frame_index={frame['frame_index']}）缺 objects")
        objects = frame["objects"]
        if not isinstance(objects, list):
            raise SceneBuildError(
                f"frames[{n}] 的 objects 必須是陣列（目前 {type(objects).__name__}）")
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            total_objects += 1
            tid = obj.get("tracked_id")
            if tid is None:
                continue
            if obj.get("position_m") is None:
                skipped_no_position += 1
                continue
            rec = stats.setdefault(tid, {"track_id": tid, "cls": obj.get("class", "?"),
                                         "frames_present": 0, "first": frame["frame_index"],
                                         "last": frame["frame_index"]})
            rec["frames_present"] += 1
            rec["last"] = frame["frame_index"]
            spread, n_wheel = kp_quality(obj, ppm)
            if spread is not None:
                q = quality.setdefault(tid, {"spread": [], "wheel": []})
                q["spread"].append(spread)
                q["wheel"].append(n_wheel)

    for tid, rec in stats.items():
        q = quality.get(tid)
        rec["spread_med"] = _median(q["spread"]) if q else None
        rec["wheel_med"] = _median(q["wheel"]) if q else None
        rec["pass_rate"] = (
            sum(1 for s, w in zip(q["spread"], q["wheel"])
                if s <= QUALITY_MAX_SPREAD_M and w >= QUALITY_MIN_WHEEL_KP) / len(q["spread"])
            if q else None)

    diag = {"skipped_no_position": skipped_no_position, "total_objects": total_objects}
    return sorted(stats.values(), key=lambda r: -r["frames_present"]), diag


def list_tracks(trajectory):
    """scan_tracks 的薄包裝，只回傳 track 清單（--list 與既有測試使用）。"""
    return scan_tracks(trajectory)[0]


# 大量出界幾乎只有一個原因：標定壞了。門檻由實測訂——捏造的 G_projection 會產出
# 83% 出界，而合成軌跡尾端溢出只有 2.6%（scenes/tainan_yongkang 的 14/532）。
OUT_OF_BOUNDS_ERROR_FRAC = 0.20


def check_positions_in_bounds(trajectory, size_m, colliders):
    """檢查 collider 的 position_m 是否落在地面圖範圍內。

    **這是目前唯一能分辨「標定標好了」與「標壞了但整條鏈照樣跑完」的檢查。**
    2026-08-19 實測：用一份捏造的 G_projection 跑完 ⑤⑥⑦⑧，331 個位置點有 276 個
    落在地面圖外、143 m 的路徑塞進 37.5×26 m 的平面，build_scene 照樣產包、
    播放器照樣回報 collided=true——全程沒有任何一行警告。

    只看 collider：extras（路人車）出界不影響碰撞結論，不該因此擋下整包。
    回傳 {"severity": ok|warn|error, "out_of_bounds": {track_id: {...}}}。
    """
    ids = {tid for tid, _ in colliders}
    seen = {tid: {"n": 0, "out": 0, "xs": [], "zs": []} for tid in ids}
    for frame in trajectory.get("frames", []):
        for obj in frame.get("objects", []):
            tid = obj.get("tracked_id")
            if tid not in ids:
                continue
            pos = obj.get("position_m")
            if not pos or len(pos) < 2:
                continue
            x, z = float(pos[0]), float(pos[1])
            st = seen[tid]
            st["n"] += 1
            st["xs"].append(x)
            st["zs"].append(z)
            if not (0.0 <= x <= size_m[0] and 0.0 <= z <= size_m[1]):
                st["out"] += 1

    report, severity = {}, "ok"
    for tid, st in seen.items():
        if not st["n"] or not st["out"]:
            continue
        frac = st["out"] / st["n"]
        report[tid] = {
            "n": st["n"], "out": st["out"], "frac": frac,
            "x_range": [min(st["xs"]), max(st["xs"])],
            "z_range": [min(st["zs"]), max(st["zs"])],
            "bounds": [float(size_m[0]), float(size_m[1])],
        }
        severity = "error" if frac > OUT_OF_BOUNDS_ERROR_FRAC else (
            "error" if severity == "error" else "warn")
    return {"severity": severity, "out_of_bounds": report}


def describe_out_of_bounds(report):
    lines = []
    for tid, r in sorted(report["out_of_bounds"].items()):
        lines.append(
            f"  track {tid}: {r['out']}/{r['n']} 點（{r['frac']*100:.1f}%）落在地面圖外；"
            f"x {r['x_range'][0]:.1f}~{r['x_range'][1]:.1f}（界 0~{r['bounds'][0]:.1f}）、"
            f"z {r['z_range'][0]:.1f}~{r['z_range'][1]:.1f}（界 0~{r['bounds'][1]:.1f}）")
    return "\n".join(lines)


def build(trajectory, code, ground_image, px_per_meter, size_m, colliders,
          source_collision, anim=(1, 32, 89), name=None):
    track_list, diag = scan_tracks(trajectory)
    tracks = {t["track_id"]: t for t in track_list}
    fps, fps_warning = resolve_fps(trajectory)
    if fps_warning:
        print(f"[build_scene] 警告：{fps_warning}", file=sys.stderr)
    frames_idx = [f["frame_index"] for f in trajectory["frames"] if f["objects"]]
    if not frames_idx:
        raise SceneBuildError("軌跡 JSON 沒有任何有 objects 的 frame")
    src_start, src_end = min(frames_idx), max(frames_idx)
    if not (src_start < source_collision < src_end):
        raise SceneBuildError(
            f"source_collision {source_collision} 必須嚴格介於 src_start={src_start} 與 "
            f"src_end={src_end} 之間（不可等於端點，否則 frame mapper 除以零）")

    bounds = check_positions_in_bounds(trajectory, size_m, colliders)
    if bounds["severity"] == "error":
        raise SceneBuildError(
            "collider 的位置大量落在地面圖出界範圍——這幾乎一定是 G-projection 標定錯誤，"
            "不是資料噪音：\n" + describe_out_of_bounds(bounds) +
            "\n（若確定要照樣產出，目前沒有旁路旗標；請先檢查標定的 anchors 與 parallax）")
    if bounds["severity"] == "warn":
        print("[build_scene] 警告：部分 collider 位置落在地面圖外\n"
              + describe_out_of_bounds(bounds), file=sys.stderr)

    vehicles = []
    for tid, cls in colliders:
        if tid not in tracks:
            hint = ""
            if diag["skipped_no_position"]:
                hint = (f"；注意有 {diag['skipped_no_position']}/{diag['total_objects']} 個 "
                        f"object 因缺 position_m 被跳過，track 清單可能因此不完整")
            raise SceneBuildError(
                f"collider track_id {tid} 不存在於軌跡（有：{sorted(tracks)}）{hint}")
        canon = normalize_class(cls)
        if canon is None:
            raise SceneBuildError(
                f"未知車種 {cls}（支援：{sorted(CLASS_DEFAULTS)}，比對不分大小寫）")
        # 挑 collider 是整條流程僅存的兩個人工判斷之一。有品質判據時就據此示警——
        # 外推的 track 會靜默給出錯誤的位置，而位置直接決定碰撞結論。
        t = tracks[tid]
        if t.get("spread_med") is not None:
            bad = []
            if t["spread_med"] > QUALITY_MAX_SPREAD_M:
                bad.append(f"展開度中位 {t['spread_med']:.1f}m > {QUALITY_MAX_SPREAD_M}m"
                           f"（homography 外推，位置不可信）")
            if (t.get("wheel_med") or 0) < QUALITY_MIN_WHEEL_KP:
                bad.append(f"輪關鍵點中位 {t['wheel_med']} < {QUALITY_MIN_WHEEL_KP}")
            if bad:
                warnings.warn(
                    f"collider track {tid} 品質不足：{'；'.join(bad)}。"
                    f"通過率僅 {100 * (t.get('pass_rate') or 0):.0f}%，建議換一條 track",
                    UserWarning, stacklevel=2)

        model, mass, length, width, speed, samples = CLASS_DEFAULTS[canon]
        label = "汽車" if model == "car.glb" else "機車"
        vehicles.append({"track_id": tid, "class": canon, "label": label, "model": model,
                         "mass_kg": mass, "length_m": length, "width_m": width,
                         "role": "collider", "default_speed_kmh": speed, "pre_samples": samples})

    return {
        "schema_version": SCHEMA_VERSION,
        "code": code,
        "name": name or f"{code} 事故重建",
        "ground": {"image": ground_image, "px_per_meter": px_per_meter,
                   "size_m": [float(size_m[0]), float(size_m[1])]},
        "origin_offset_m": [size_m[0] / 2, size_m[1] / 2],
        "frames": {"source_start": src_start, "source_collision": source_collision,
                   "source_end": src_end, "anim_start": anim[0],
                   "anim_collision": anim[1], "anim_end": anim[2], "fps": fps},
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
        for k in ("track_id", "class", "model", "mass_kg", "length_m", "width_m"):
            if k not in v:
                errs.append(f"vehicle {v.get('track_id', '?')} 缺 {k}")
    f = cfg.get("frames", {})
    for k in ("source_start", "source_collision", "source_end",
              "anim_start", "anim_collision", "anim_end"):
        if k not in f:
            errs.append(f"frames 缺 {k}")
    # frame mapper 用 (collision - start) / (end - start) 當分母；start==collision 或
    # collision==end 會除以零產生 -Infinity/NaN，車輛座標整個壞掉卻不報錯。
    if all(k in f for k in ("source_start", "source_collision", "source_end")):
        if not (f["source_start"] < f["source_collision"] < f["source_end"]):
            errs.append(
                f"frames.source_start/source_collision/source_end 必須嚴格遞增（目前 "
                f"{f['source_start']}, {f['source_collision']}, {f['source_end']}）")
    if all(k in f for k in ("anim_start", "anim_collision", "anim_end")):
        if not (f["anim_start"] < f["anim_collision"] < f["anim_end"]):
            errs.append(
                f"frames.anim_start/anim_collision/anim_end 必須嚴格遞增（目前 "
                f"{f['anim_start']}, {f['anim_collision']}, {f['anim_end']}）")
    return errs


def pick_sat(sat_dir):
    sat_dir = Path(sat_dir)
    meta = json.loads((sat_dir / "meta.json").read_text())
    for variant in SAT_VARIANTS:
        if (sat_dir / variant).exists():
            img_path = sat_dir / variant
            # 根據實際 PNG 寬度重新計算 px_per_meter，以補償 variant 與原始解析度的差異
            png_width, _ = png_size(img_path)
            px_per_meter = png_width / meta["size_m"]
            return img_path, meta, px_per_meter
    raise SceneBuildError(f"{sat_dir} 內找不到 {SAT_VARIANTS}")


def from_location_dir(location_dir, code, trajectory):
    """從 G-projection 的校正參考圖推出地面圖與尺度，回傳 (img_path, px_per_meter, size_m)。

    真實影片的 position_m 就活在 `location/<code>/sat_<code>.png` 這張**校正參考圖**的
    平面上（原點＝圖左上角、尺度＝trajectory.meta.px_per_meter），所以地面圖必須是那張
    圖本身或其等比縮放。用 workbench 新擷取的圖是另一張取景，會整個錯位。

    實證：test1 的 sat 圖 1676×1148 @34.41px/m → 48.71×33.36m，與 committed scene.json
    的 size_m 完全相同；taipei-cm 1190×1258 @27.85 → 42.72×45.16m，軌跡範圍完全落在內。
    """
    d = Path(location_dir)
    # 場景代號（--code）與地點代號不必相同——同一個路口可以出多個場景包。
    # 依序試：sat_<場景代號> → sat_<目錄名> → 目錄內唯一的 sat_*.png。
    candidates = [d / f"sat_{code}.png", d / f"sat_{d.name}.png"]
    img = next((p for p in candidates if p.exists()), None)
    if img is None:
        found = sorted(d.glob("sat_*.png"))
        if len(found) == 1:
            img = found[0]
        else:
            raise SceneBuildError(
                f"在 {d} 找不到校正參考圖（試過 {[p.name for p in candidates]}）；"
                f"目錄內的 sat_*.png：{[p.name for p in found] or '無'}")
    meta = trajectory.get("meta") if isinstance(trajectory, dict) else None
    ppm = (meta or {}).get("px_per_meter")
    if not isinstance(ppm, (int, float)) or isinstance(ppm, bool) \
            or not math.isfinite(ppm) or ppm <= 0:
        raise SceneBuildError(
            f"trajectory.meta.px_per_meter 無效（{ppm!r}），無法由 --location-dir 推出尺度")
    w, h = png_size(img)
    base_size_m = [w / ppm, h / ppm]

    # 優先採用去車＋銳化過的增強版（workbench/image_enhance.py --input/--output 產生）。
    # 它是原圖的整數倍等比放大，所以**覆蓋的公尺數不變、只有像素密度變高** ——
    # px_per_meter 跟著乘上縮放比即可，座標仍然正確。
    hd = img.with_name(f"{img.stem}_hd{img.suffix}")
    if hd.exists():
        hw, hh = png_size(hd)
        fx, fy = hw / w, hh / h
        if abs(fx - fy) > 1e-6:
            warnings.warn(
                f"{hd.name} 長寬比與原圖不符（{hw}×{hh} vs {w}×{h}），"
                f"無法用單一係數換算 px_per_meter，改用原圖。"
                f"（增強務必用 image_enhance.py --input/--output，不要用 --genai）",
                UserWarning, stacklevel=2)
        else:
            return hd, float(ppm) * fx, base_size_m

    return img, float(ppm), base_size_m


def parse_collider(text):
    tid, cls = text.split(":", 1)
    return int(tid), cls


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trajectory", required=True)
    ap.add_argument("--list", action="store_true", help="列出 track 後結束")
    ap.add_argument("--code")
    ap.add_argument("--location-dir",
                    help="G-projection 校正目錄 location/<code>/（真實影片用；自動由 "
                         "sat_<code>.png 與 trajectory.meta.px_per_meter 推出尺度）")
    ap.add_argument("--sat-dir", help="workbench 輸出目錄（自動讀 meta.json）"
                                      "；僅適用於在衛星座標系合成的軌跡")
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
        has_q = any(t.get("spread_med") is not None for t in list_tracks(trajectory))
        if has_q:
            print(f"{'track':>7} {'class':<12} {'frames':>7} {'範圍':>13} "
                  f"{'展開度':>8} {'輪點':>5} {'可用率':>7}")
        for t in list_tracks(trajectory):
            line = (f"track {t['track_id']:>5}  {t['cls']:<12} "
                    f"frames {t['frames_present']:>4}  [{t['first']}–{t['last']}]")
            if t.get("spread_med") is not None:
                flag = "" if (t["spread_med"] <= QUALITY_MAX_SPREAD_M
                              and (t.get("wheel_med") or 0) >= QUALITY_MIN_WHEEL_KP) else "  ⚠"
                line += (f" {t['spread_med']:>7.1f}m {t['wheel_med']:>5}"
                         f" {100 * (t.get('pass_rate') or 0):>6.0f}%{flag}")
            print(line)
        if has_q:
            print(f"\n門檻：展開度 ≤ {QUALITY_MAX_SPREAD_M}m 且輪關鍵點 ≥ "
                  f"{QUALITY_MIN_WHEEL_KP}（⚠ = 不建議當 collider）")
        return 0

    if not (args.code and len(args.collider) >= 2 and args.source_collision is not None):
        ap.error("產生模式需要 --code、至少兩個 --collider、--source-collision")
    if args.location_dir:
        src_img, px, size = from_location_dir(args.location_dir, args.code, trajectory)
        print(f"[build_scene] 地面圖 {src_img}  {px:.4f} px/m  "
              f"→ size_m {size[0]:.2f} × {size[1]:.2f}")
    elif args.sat_dir:
        src_img, meta, px = pick_sat(args.sat_dir)
        size = [meta["size_m"], meta["size_m"]]
    elif args.ground_image and args.px_per_meter and args.size_m:
        src_img, px, size = Path(args.ground_image), args.px_per_meter, args.size_m
    else:
        ap.error("需要 --location-dir 或 --sat-dir 或"
                 "（--ground-image + --px-per-meter + --size-m）")

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
