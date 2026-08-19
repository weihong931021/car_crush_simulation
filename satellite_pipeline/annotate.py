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

# 判「這點標歪了」的門檻，單位是**公尺**不是像素：像素門檻會隨底圖倍率浮動
# （8px 在 58px/m 是 0.14m、在 29px/m 是 0.28m），公尺才跟解析度無關。
# 取 0.30 m 的理由：29px/m 底圖一個像素 3.4cm，人工點擊精度約 ±3px ≈ ±0.1m；
# 標得好的組合 RMS 落在 0.07–0.17 m，所以超過 0.3 m 是真的標錯而不是手抖。
BAD_RESIDUAL_M = 0.30

# 點位涵蓋面積（凸包 / 整張底圖）低於此值＝其餘區域全靠外推，殘差再小也不代表準
MIN_COVERAGE = 0.10


def _fit(src, dst):
    """擬合單應性並回傳 (H, 逐點殘差)；退化時回 (None, None)，讓呼叫端自己決定要不要炸。"""
    import cv2
    import numpy as np

    H, _ = cv2.findHomography(src, dst, method=0)
    if H is None or not np.isfinite(H).all() or abs(H[2, 2]) < 1e-12:
        return None, None
    H = H / H[2, 2]                       # haware_forward 會檢查 H[2,2] ≈ 1
    proj = (H @ np.hstack([src, np.ones((len(src), 1))]).T).T
    w = proj[:, 2:3]
    if not np.isfinite(w).all() or (np.abs(w) < 1e-12).any():
        return None, None
    return H, np.linalg.norm(proj[:, :2] / w - dst, axis=1)


def solve_homography(pairs, px_per_meter=None, sat_size=None):
    """對應點 → (H 3×3 list, 診斷 dict)。

    pairs：[{"coords_cctv": [x, y], "coords_sat": [x, y]}, ...]

    診斷要回答的是「**哪一點該重標**」，而這件事不能看殘差：最小平方會把單一錯點的
    誤差分攤到所有點。實測 6 組點只有 index 2 標歪 30px，殘差最大的卻是 index 4——
    照殘差叫人重標就是叫他去改沒問題的點。

    所以改用 **leave-one-out**：逐一拿掉某點重擬合，看剩下的點變多乾淨。拿掉真正的
    錯點殘差會塌下來，拿掉好點則不會。拿掉後剩下的點若退化（共線等）就跳過該點。
    """
    import numpy as np

    if len(pairs) < MIN_PAIRS:
        raise ValueError(f"至少要 {MIN_PAIRS} 組對應點（目前 {len(pairs)} 組）")

    src = np.array([p["coords_cctv"] for p in pairs], dtype=np.float64)
    dst = np.array([p["coords_sat"] for p in pairs], dtype=np.float64)
    H, residual = _fit(src, dst)
    if H is None:
        raise ValueError("這組點求不出單應性——常見原因是四點共線或重複，請換位置重標")

    n = len(pairs)
    rms = float(np.sqrt((residual ** 2).mean()))
    overdetermined = n > MIN_PAIRS
    warnings = []

    # --- 哪一點該重標：leave-one-out ---
    # 需要拿掉一點後還剩 >MIN_PAIRS 個點，否則剩下的又被解死、RMS 恆為 0，分不出好壞
    suspect_index, suspect_gain = None, None
    if n > MIN_PAIRS + 1:
        best = None
        for i in range(n):
            keep = [j for j in range(n) if j != i]
            _, r2 = _fit(src[keep], dst[keep])
            if r2 is None:
                continue                       # 剩下的點退化，這個 i 沒有資訊
            loo = float(np.sqrt((r2 ** 2).mean()))
            if best is None or loo < best[0]:
                best = (loo, i)
        if best and rms > 1e-9 and best[0] < rms * 0.5:
            suspect_index, suspect_gain = best[1], rms - best[0]

    # --- 涵蓋範圍：點擠成一團時，其餘區域是外推的 ---
    coverage = None
    if sat_size and len(dst) >= 3:
        import cv2
        hull = cv2.convexHull(dst.astype(np.float32))
        area = float(cv2.contourArea(hull))
        coverage = area / float(sat_size[0] * sat_size[1])
        if coverage < MIN_COVERAGE:
            warnings.append({
                "code": "coverage",
                "text": f"對應點只涵蓋底圖 {coverage * 100:.0f}% 的範圍，其餘區域是外推的——"
                        f"請把點分散到畫面四周",
            })

    if not overdetermined:
        warnings.append({
            "code": "exact_fit",
            "text": "剛好 4 組點會被單應性解死，誤差必然為 0——標第 5 組才看得出準不準",
        })

    to_m = (lambda v: v / px_per_meter) if px_per_meter else (lambda v: None)
    per_point_m = [to_m(float(v)) for v in residual] if px_per_meter else None
    if px_per_meter and overdetermined and float(residual.max()) / px_per_meter > BAD_RESIDUAL_M:
        warnings.append({
            "code": "residual",
            "text": f"最大偏差 {float(residual.max()) / px_per_meter:.2f} m，超過 "
                    f"{BAD_RESIDUAL_M} m——有點標歪了",
        })

    return H.tolist(), {
        "rms_px": rms,
        "max_px": float(residual.max()),
        "per_point_px": [float(v) for v in residual],
        "worst_index": int(residual.argmax()),      # 描述用：殘差最大的那點
        "suspect_index": suspect_index,             # 建議用：真正該重標的那點
        "suspect_gain_px": suspect_gain,
        "rms_m": to_m(rms),
        "max_m": to_m(float(residual.max())),
        "per_point_m": per_point_m,
        "coverage": coverage,
        "warnings": warnings,
        # 單應性 8 個自由度：剛好 4 組點會被解死，**再怎麼標歪殘差都是 0**。
        # 沒有這個旗標，介面上的「誤差 0.00 px」會被誤讀成標得很準。
        "overdetermined": overdetermined,
    }


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
