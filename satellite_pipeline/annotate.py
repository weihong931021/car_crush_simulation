#!/usr/bin/env python3
"""網頁標註（進場流程 ③）的後端：對應點 → 單應性 → `G_projection_<code>.json`。

原本這一步只能開 trafficlab 的 PyQt5 GUI 手動點。整條鏈其他段都已經是網頁了，
只為了點幾組對應點就要跳出桌面程式，是流程裡唯一的斷點。

輸出 schema 對齊 `trafficlab/io/trafficlab_config.py:default_config()`——下游
（`haware_forward`、`filter_and_enrich_output.py`）只讀 `homography.H` 與
`parallax.px_per_meter`，其餘欄位給預設值即可，但**鍵一定要在**，
否則 GUI 開啟同一份檔會 KeyError。

`px_per_meter` 由 ② 鎖定的底圖直接帶入（Web Mercator 解析值），不必再人工量兩點。
"""
from datetime import datetime
from pathlib import Path

MIN_PAIRS = 4          # 單應性 8 個自由度，4 組對應點是下限


def solve_homography(pairs):
    """對應點 → (H 3×3 list, 誤差 dict)。

    pairs：[{"coords_cctv": [x, y], "coords_sat": [x, y]}, ...]
    誤差是把 cctv 點經 H 投到衛星圖後與人工標的距離（像素）——這是唯一能當場看出
    「哪一點標歪了」的訊號，所以連逐點明細一起回傳。
    """
    import cv2
    import numpy as np

    if len(pairs) < MIN_PAIRS:
        raise ValueError(f"至少要 {MIN_PAIRS} 組對應點（目前 {len(pairs)} 組）")

    src = np.array([p["coords_cctv"] for p in pairs], dtype=np.float64)
    dst = np.array([p["coords_sat"] for p in pairs], dtype=np.float64)
    H, _ = cv2.findHomography(src, dst, method=0)
    if H is None or not np.isfinite(H).all() or abs(H[2, 2]) < 1e-12:
        raise ValueError("這組點求不出單應性——常見原因是四點共線或重複，請換位置重標")

    H = H / H[2, 2]                       # haware_forward 會檢查 H[2,2] ≈ 1

    proj = (H @ np.hstack([src, np.ones((len(src), 1))]).T).T
    w = proj[:, 2:3]
    if not np.isfinite(w).all() or (np.abs(w) < 1e-12).any():
        raise ValueError("投影出現無窮遠點，這組點退化，請換位置重標")
    residual = np.linalg.norm(proj[:, :2] / w - dst, axis=1)

    err = {
        "rms_px": float(np.sqrt((residual ** 2).mean())),
        "max_px": float(residual.max()),
        "per_point_px": [float(v) for v in residual],
        "worst_index": int(residual.argmax()),
        # 單應性 8 個自由度：剛好 4 組點會被解死，**再怎麼標歪殘差都是 0**。
        # 沒有這個旗標，介面上的「誤差 0.00 px」會被誤讀成標得很準。
        "overdetermined": len(pairs) > MIN_PAIRS,
    }
    return H.tolist(), err


def build_g_projection(code, pairs, px_per_meter, cctv_path="", sat_path="",
                       cctv_size=None, sat_size=None):
    """組出 trafficlab 認得的 G_projection 物件（不寫檔）。"""
    H, err = solve_homography(pairs)
    anchors = [{
        "id": i,
        "name": p.get("name") or f"Pair {i}",
        "coords_cctv": [float(p["coords_cctv"][0]), float(p["coords_cctv"][1])],
        "coords_sat": [float(p["coords_sat"][0]), float(p["coords_sat"][1])],
    } for i, p in enumerate(pairs)]

    return {
        "meta": {
            "location_code": code,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "source": "satellite_pipeline web annotate",
            "reprojection_rms_px": err["rms_px"],
            "reprojection_max_px": err["max_px"],
        },
        "inputs": {
            "cctv_path": cctv_path,
            "sat_path": sat_path,
            "layout_path": "",
            "roi_path": "",
            "note": "對應點在網頁工作台標定；px_per_meter 由衛星底圖解析值帶入",
        },
        # 未做鏡頭校正：resolution 記下來給下游判斷，K/D 留單位矩陣＋零畸變
        "undistort": {
            "resolution": list(cctv_size) if cctv_size else [],
            "K": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "D": [0.0, 0.0, 0.0, 0.0, 0.0],
            "model": "radial_tangential",
        },
        "homography": {"H": H, "fov_polygon": [], "anchors_list": anchors},
        "parallax": {
            # 視差補償需要相機位置與高度，網頁標註沒有這些資訊 → 留 0，
            # 下游若要用 parallax 仍須回 GUI 補（proj_method 因此設 down_h_2 的無視差版）
            "x_cam_coords_sat": 0.0,
            "y_cam_coords_sat": 0.0,
            "z_cam_meters": 0.0,
            "scale": {
                "source": "satellite_pipeline (Web Mercator)",
                "measured_px": 0.0,
                "real_m": 0.0,
                "reference_anchors": [],
            },
            "px_per_meter": float(px_per_meter),
        },
        "use_svg": False,
        "layout_svg": {"A": [], "association_pairs": []},
        "use_roi": False,
        "roi_method": "partial",
        "ref_method": "center_box",
        "proj_method": "down_h_2",
        "sat_size": list(sat_size) if sat_size else [],
    }


def save_g_projection(loc_dir, code, pairs, px_per_meter, **kw) -> Path:
    """寫 `location/<code>/G_projection_<code>.json`，回傳路徑。"""
    import json

    obj = build_g_projection(code, pairs, px_per_meter, **kw)
    path = Path(loc_dir) / f"G_projection_{code}.json"
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
    return path
