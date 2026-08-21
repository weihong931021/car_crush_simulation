#!/usr/bin/env python3
"""measure_genai_drift.py — 量生圖模型把幾何搬了多遠

為什麼需要這支：`--genai` 是「重畫」不是「修圖」，但「有沒有亂砍亂生」原本只能人眼看。
人眼看不出 0.2m 和 0.3m 的差別，也分不清「整張圖平移了」和「內容被改寫了」——
前者可校正、後者不可救。這支把那個判斷變成數字。

做法：把兩張圖切成 128px（或 --tile）的方塊，逐塊做相位相關求位移。
    位移中位數  該塊結構被搬了多遠（除以 px_per_meter 就是公尺）
    對位信心    低 ＝ 該塊根本對不上，結構已被改寫
    全域相關    整張圖的結構相似度

用法：
    python3 measure_genai_drift.py --code tainan_yongkang
    python3 measure_genai_drift.py --ref a.png --test b.png --ppm 29.11

實測基準（2026-08-17，tainan_yongkang，見 docs/decisions/2026-08-17-satellite-genai-provider-choice.md）：
    sat_clean（不生圖）        0.00 m ／ 全域相關 0.968
    gemini-3.1-flash-image     0.20 m ／ 全域相關 0.876
    gpt-image-2                0.30 m ／ 全域相關 0.746
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPTS_DIR))
from common import validate_code  # noqa: E402
from paths import OUTPUT_DIR      # noqa: E402  路徑集中在 paths.py


def measure(ref_path: Path, test_path: Path, ppm: float, tile: int = 128) -> dict:
    """回傳 {median_px, median_m, frac_over_10px, confidence, global_corr, n_tiles}。"""
    import cv2
    import numpy as np

    a = cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(str(test_path), cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        raise FileNotFoundError(f"讀不到圖：{ref_path} / {test_path}")
    if a.shape != b.shape:
        # 尺寸不同就縮到參考圖的尺寸——比的是幾何位置，不是解析度
        b = cv2.resize(b, a.shape[::-1], interpolation=cv2.INTER_AREA)

    t = min(tile, a.shape[0], a.shape[1])
    a32, b32 = a.astype(np.float32), b.astype(np.float32)
    win = cv2.createHanningWindow((t, t), cv2.CV_32F)
    mags, confs = [], []
    for y in range(0, a.shape[0] - t + 1, t):
        for x in range(0, a.shape[1] - t + 1, t):
            pa, pb = a32[y:y + t, x:x + t].copy(), b32[y:y + t, x:x + t].copy()
            if pa.std() < 5:          # 純色塊沒有可對位的結構
                continue
            (dx, dy), conf = cv2.phaseCorrelate(pa, pb, win)
            mags.append((dx * dx + dy * dy) ** 0.5)
            confs.append(conf)
    if not mags:
        raise ValueError("沒有可對位的區塊（圖太小或太平）")

    mags, confs = np.array(mags), np.array(confs)
    sa, sb = cv2.resize(a, (320, 320)), cv2.resize(b, (320, 320))
    med = float(np.median(mags))
    return {
        "median_px": round(med, 2),
        "median_m": round(med / ppm, 3) if ppm else None,
        "frac_over_10px": round(float((mags > 10).mean()), 3),
        "confidence": round(float(np.median(confs)), 3),
        "global_corr": round(float(np.corrcoef(sa.ravel(), sb.ravel())[0, 1]), 3),
        "n_tiles": len(mags),
    }


def main():
    ap = argparse.ArgumentParser(description="量生圖模型的幾何漂移")
    ap.add_argument("--code", type=validate_code,
                    help="量 output/<code>/ 內 sat_clean 與 sat_genai 相對 sat_raw 的漂移")
    ap.add_argument("--ref", help="參考圖（通常是 sat_raw.png）")
    ap.add_argument("--test", help="待測圖")
    ap.add_argument("--ppm", type=float, help="px_per_meter；--code 模式自動從 meta.json 讀")
    ap.add_argument("--tile", type=int, default=128, help="分塊邊長，預設 128")
    args = ap.parse_args()

    if args.ref or args.test:
        if not (args.ref and args.test):
            ap.error("--ref 與 --test 必須併用")
        r = measure(Path(args.ref), Path(args.test), args.ppm or 0, args.tile)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if not args.code:
        ap.error("需要 --code，或（--ref + --test）")
    out_dir = OUTPUT_DIR / args.code
    raw = out_dir / "sat_raw.png"
    if not raw.exists():
        sys.exit(f"ERROR: 找不到 {raw}")
    ppm = args.ppm
    meta_path = out_dir / "meta.json"
    if ppm is None and meta_path.exists():
        ppm = float(json.loads(meta_path.read_text()).get("px_per_meter", 0)) or None
    if not ppm:
        sys.exit("ERROR: 需要 px_per_meter（meta.json 沒有就給 --ppm）")

    print(f"[measure] {args.code}  參考=sat_raw.png  ppm={ppm:.2f}  tile={args.tile}")
    print("| 待測圖 | 位移中位數 | >10px | 對位信心 | 全域相關 |")
    print("| --- | --- | --- | --- | --- |")
    for name in ("sat_clean.png", "sat_genai.png"):
        p = out_dir / name
        if not p.exists():
            continue
        r = measure(raw, p, ppm, args.tile)
        print(f"| {name} | {r['median_px']:.1f} px = {r['median_m']:.2f} m "
              f"| {r['frac_over_10px'] * 100:.0f}% | {r['confidence']:.3f} "
              f"| {r['global_corr']:.3f} |")


if __name__ == "__main__":
    main()
