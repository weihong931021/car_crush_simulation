#!/usr/bin/env python3
"""最終整合（進場流程 ④）：推論 → 挑當事車 → 標碰撞幀 → 場景包 → Three.js。

這裡**不重寫任何軌跡邏輯**，只把 trafficlab 既有的三支腳本串起來：

    scripts/run_inference.py            → output/<...>/<loc>/<video>.json.gz（全部 track）
    scripts/filter_and_enrich_output.py → trajectory.json（只留當事車，補 position_m）
    tools/build_scene.py                → scenes/<code>/ → player/index.html?scene=<code>

三個必須知道的環境事實（都是踩過才知道的）：

1. **三支腳本用不同的直譯器**。推論要 ultralytics + supervision，只有
   `littering_prediction/venv` 有；enrich 要 numpy + trafficlab，用 `.venv-pifpaf`；
   build_scene 純標準庫，系統 python3 即可。
2. **repo 內 7 組 inference config 的權重全部指向不存在的檔案**（隊友的環境才有）。
   `run_inference.py` 沒有 `--weights` 覆寫，但有 `--config-path`——所以自帶一份，
   不去動隊友那個凍結中的檔案。
3. **挑車的品質判據直接重用 `build_scene`**（連 `kp_quality` 函式本身），
   門檻各寫一份遲早會漂移，然後兩個畫面對同一台車講出不同結論。
"""
import json
import sys
from pathlib import Path

from paths import REPO_ROOT, TRAFFICLAB_DIR

sys.path.insert(0, str(REPO_ROOT / "tools"))
from build_scene import (  # noqa: E402  判據唯一來源，不另寫一份
    QUALITY_MAX_SPREAD_M,
    QUALITY_MIN_WHEEL_KP,
    kp_quality,
    normalize_class,
)

# 推論結果落在 output/model-<stem>_tracker-<type>/<config>/<loc>/<video>.json.gz
WEB_CONFIG_NAME = "web_flow"

# yolo11l-visdrone-ft.pt 的 VisDrone 車輛類別；換模型時必須同步核對 model.names。
HAWARE_YOLO_BOX_CLASSES = (
    "car", "van", "truck", "bus", "motor", "bicycle", "tricycle", "awning-tricycle",
)

# 直譯器候選（依序試，取第一個 import 得起來的）
INFERENCE_PYTHONS = (
    Path("/Users/weihong/Documents/littering_prediction/venv/bin/python"),
    TRAFFICLAB_DIR / ".venv-pifpaf" / "bin" / "python",
)
ENRICH_PYTHONS = (
    TRAFFICLAB_DIR / ".venv-pifpaf" / "bin" / "python",
    Path(sys.executable),
)


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def list_track_candidates(raw, ppm_fallback=None):
    """推論輸出 → 可當「當事車」的 track 清單（含品質欄位）。

    與 `build_scene.scan_tracks` 的差別只有一個：那邊要 `position_m`（enrich 之後才有），
    這邊在 enrich **之前**就要讓人挑車，所以改看 `sat_coords`。品質欄位共用同一組函式。

    `ok` 是建議而不是硬規則——實測 ≥2 個輪關鍵點時 heading 中位誤差 2.42°、災難率 0%；
    0–1 個時約 98°。但那是相關性不是因果（樣本多半來自近端 track），所以只標記不阻擋。
    """
    frames = raw.get("frames") or []
    # haware_replay 的 meta 只有 resolution/fps，沒有 px_per_meter（filter_and_enrich
    # 之後才補）——挑車發生在 enrich 之前，所以讓呼叫端帶底圖的比例尺進來。
    ppm = (raw.get("meta") or {}).get("px_per_meter") or ppm_fallback
    stats, quality, first_last = {}, {}, {}

    for frame in frames:
        idx = frame.get("frame_index")
        for obj in frame.get("objects") or []:
            tid = obj.get("tracked_id")
            # 位置來源兩種：sat_coords（PifPaf 定位，authority 認證）或
            # bbox_fallback_sat_coords（bbox+單應性備援，機車唯一的路）。都沒有才跳過。
            pos = obj.get("sat_coords") or obj.get("bbox_fallback_sat_coords")
            if tid is None or pos is None:
                continue                       # 沒有位置的 track 不能當當事車
            # cls_suggested：偵測類別 → build_scene 的車種鍵（VisDrone 的 motor →
            # Two_Wheeler、van → Van…）。**用 build_scene 自己的別名表**，不另寫一份，
            # 否則哪天別名改了，畫面上選得到的車種會和 build_scene 收得下的對不起來。
            # 對不上（people / pedestrian 等非車輛）回 None，前端據此標示不建議。
            rec = stats.setdefault(tid, {"track_id": tid, "cls": obj.get("class", "?"),
                                         "cls_suggested": normalize_class(obj.get("class")),
                                         "frames_present": 0, "first": idx, "last": idx})
            rec["frames_present"] += 1
            rec["last"] = idx
            rec["n_bbox_pos"] = rec.get("n_bbox_pos", 0) + (0 if obj.get("sat_coords") else 1)
            fl = first_last.setdefault(tid, [pos, pos])
            fl[1] = pos
            spread, n_wheel = kp_quality(obj, ppm)
            if spread is not None:
                q = quality.setdefault(tid, {"spread": [], "wheel": []})
                q["spread"].append(spread)
                q["wheel"].append(n_wheel)

    for tid, rec in stats.items():
        # 淨位移：整段軌跡頭尾直線距離。品質欄位（展開度／輪點）量的是**關鍵點品質**，
        # 停放車反而分數最高（不動、輪子清楚）——實測 tainan_yongkong 的 track 1 是
        # 路邊停放車，可用率 100%，被當成當事車挑下去直到 build_scene 出界檢查才擋下。
        # 「有沒有在動」是另一個維度，必須自己給。
        fl = first_last.get(tid)
        rec["net_disp_m"] = (
            ((fl[1][0] - fl[0][0]) ** 2 + (fl[1][1] - fl[0][1]) ** 2) ** 0.5 / ppm
            if fl and ppm else None)
        n_bbox = rec.get("n_bbox_pos", 0)
        rec["pos_source"] = ("bbox" if n_bbox == rec["frames_present"]
                             else "pifpaf" if n_bbox == 0 else "mixed")
        q = quality.get(tid)
        rec["spread_med"] = _median(q["spread"]) if q else None
        rec["wheel_med"] = _median(q["wheel"]) if q else None
        rec["pass_rate"] = (
            sum(1 for s, w in zip(q["spread"], q["wheel"])
                if s <= QUALITY_MAX_SPREAD_M and w >= QUALITY_MIN_WHEEL_KP) / len(q["spread"])
            if q else None)
        rec["ok"] = bool(rec["pass_rate"] and rec["pass_rate"] >= 0.5)

    return sorted(stats.values(), key=lambda r: -r["frames_present"])


def find_weights(models_dir) -> Path:
    """挑一個**實際存在**的權重檔。repo 內 config 全指向不存在的檔案，所以自己找。"""
    models_dir = Path(models_dir)
    found = sorted(models_dir.glob("*.pt"))
    if not found:
        raise FileNotFoundError(
            f"{models_dir} 內沒有任何 .pt 權重——推論跑不了。"
            f"請放一個模型檔（例如 yolo11l-visdrone-ft.pt）")
    # 檔名帶 visdrone 的優先：實測二輪偵測 ×21、汽車信心 +0.03
    return next((p for p in found if "visdrone" in p.name.lower()), found[0])


def make_inference_config(base_yaml, weights, dst) -> Path:
    """複製 repo 的第一組 config，只把權重換成實際存在的那個。

    不直接改 `inference_config.yaml`：那是隊友主導、凍結中的檔案，而且改了會影響他們
    自己的環境。`run_inference.py` 有 `--config-path`，自帶一份最乾淨。
    """
    import yaml

    base_yaml, weights, dst = Path(base_yaml), Path(weights), Path(dst)
    data = yaml.safe_load(base_yaml.read_text())
    configs = data.get("configs", data)
    body = json.loads(json.dumps(next(iter(configs.values()))))   # 深拷貝
    body.setdefault("model", {})["weights"] = str(weights.resolve())
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(yaml.safe_dump({"configs": {WEB_CONFIG_NAME: body}},
                                  allow_unicode=True, sort_keys=False))
    return dst


def find_raw_output(output_root, code: str, video_stem: str):
    """在 output/**/<code>/<video_stem>.json.gz 裡找推論產物（目錄名含模型與 tracker）。"""
    hits = sorted(Path(output_root).glob(f"*/*/{code}/{video_stem}.json.gz"))
    return hits[0] if hits else None


def pick_python(candidates, probe: str):
    """挑第一個 import 得起來 probe 模組的直譯器。"""
    import subprocess
    for py in candidates:
        if not Path(py).exists():
            continue
        r = subprocess.run([str(py), "-c", f"import {probe}"], capture_output=True)
        if r.returncode == 0:
            return Path(py)
    return None


def subprocess_env() -> dict:
    """跑 trafficlab 腳本用的環境。

    `eval_haware_replay.py` 與 `filter_and_enrich_output.py` 都 `from trafficlab...` import，
    但 trafficlab-project 沒有裝成套件（沒有 setup.py / pip install -e），所以必須把它
    放進 PYTHONPATH，否則一跑就 ModuleNotFoundError。
    """
    import os
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{TRAFFICLAB_DIR}:{existing}" if existing else str(TRAFFICLAB_DIR)
    return env


def find_g_projection(loc_dir, code: str):
    """`location/<code>/` 內的校正檔；trafficlab 支援普通版與 SVG 版兩種檔名。

    只認普通版的話，用 SVG 校正的地點會被判成「還沒標註」，換底圖時舊的 SVG 座標
    也不會被停用——底圖換了、座標沒換，而且不報錯。
    """
    return next(iter(all_g_projections(loc_dir, code)), None)


def all_g_projections(loc_dir, code: str) -> list:
    """兩種校正檔全部列出（普通版優先），給覆蓋防護用。"""
    loc_dir = Path(loc_dir)
    names = [f"G_projection_{code}.json", f"G_projection_svg_{code}.json"]
    return [loc_dir / n for n in names if (loc_dir / n).exists()]


def haware_cmd(python, video, g_projection, yolo_boxes, out_path, frames=-1) -> list:
    """PifPaf 關鍵點 → haware localize → 寫 status / kp_sat / spread_m / n_wheel_kp。

    **這一段不能省**：`run_inference.py` 只用 G-projection 算 `sat_coords` 而不寫 `status`，
    而 `filter_and_enrich_output.py` 的 localization 政策只接受 `status == 'ok'`——
    直接把兩者串起來，每一格都會被判證據不足、position_m 全 null 然後 sys.exit。

    `--yolo-boxes-json` 餵第一步的追蹤結果，讓 haware 的輸出沿用同一組 tracked_id，
    使用者在畫面上挑的 track 才對得起來。
    """
    # --bbox-fallback：PifPaf 的 Apollo-24 汽車模型看不到機車（實測全片 7 條機車
    # track 最佳 IoU 全 0.000），沒有備援定位的話當事機車永遠進不了挑車清單。
    # 備援座標走 bbox_fallback_sat_coords 旁路欄位，enrich 端要配 --accept-bbox-fallback。
    return [str(python), "scripts/eval_haware_replay.py",
            "--video", str(Path(video).resolve()),
            "--g-proj", str(Path(g_projection).resolve()),
            "--method", "geometric",
            "--yolo-boxes-json", str(Path(yolo_boxes).resolve()),
            "--yolo-boxes-class", ",".join(HAWARE_YOLO_BOX_CLASSES),
            "--bbox-fallback",
            "--out", str(Path(out_path).resolve()),
            "--frames", str(int(frames))]


def inference_cmd(python, config_path, code, video, output_root) -> list:
    return [str(python), "scripts/run_inference.py",
            "--config-path", str(Path(config_path).resolve()),
            "--config-name", WEB_CONFIG_NAME,
            "--location", str(code),
            "--mp4", str(Path(video).resolve()),
            "--output-root", str(Path(output_root).resolve()),
            "--force"]


def enrich_cmd(python, raw_path, out_path, ids, g_projection) -> list:
    return [str(python), "scripts/filter_and_enrich_output.py",
            str(Path(raw_path).resolve()), str(Path(out_path).resolve()),
            "--ids", *[str(int(i)) for i in ids],
            "--g-projection", str(Path(g_projection).resolve()),
            "--accept-bbox-fallback"]


def build_scene_cmd(python, code, trajectory, location_dir, colliders,
                    collision_frame) -> list:
    """colliders：兩筆 {"track_id", "cls"}。少於／多於兩台都不成立——
    碰撞模擬本來就是兩台車的事（`simulate.js` 的 OBB 解算假設恰好兩個 collider）。"""
    if len(colliders) != 2:
        raise ValueError(f"要剛好兩台當事車（目前 {len(colliders)} 台）")
    cmd = [str(python), "tools/build_scene.py",
           "--code", str(code),
           "--trajectory", str(Path(trajectory).resolve()),
           "--location-dir", str(Path(location_dir).resolve())]
    for c in colliders:
        cmd += ["--collider", f"{int(c['track_id'])}:{c['cls']}"]
    cmd += ["--source-collision", str(int(collision_frame))]
    return cmd
