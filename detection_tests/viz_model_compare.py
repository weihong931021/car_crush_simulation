"""
Model comparison: baseline COCO yolo11l vs fine-tuned VisDrone model.
Renders a side-by-side video (left=baseline, right=fine-tune) and prints
per-class detection tallies so we can judge whether the fine-tune helps,
especially on motorcycles / two-wheelers.

Lives outside the vendored trafficlab-project/ folder. Defaults point back
into trafficlab-project for the footage and the fine-tuned model, so you can
just run it with no args:

    python detection_tests/viz_model_compare.py

Or override any path:
    python detection_tests/viz_model_compare.py \
        --footage <video.mp4> --left yolo11l.pt \
        --right <model.pt> --output detection_tests/outputs/out.mp4 \
        --conf 0.25 --imgsz 736 --max-frames 0
"""

import argparse
import os
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

# Project layout: this file sits in <root>/detection_tests/, the vendored
# pipeline (footage + models) lives in <root>/trafficlab-project/.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TLAB = ROOT / "trafficlab-project"
DEF_FOOTAGE = TLAB / "location/test1/footage/test1.mp4"
DEF_RIGHT = TLAB / "models/yolo11l-visdrone-ft.pt"
DEF_OUTPUT = HERE / "outputs/test1_model_compare.mp4"
# Prefer a local copy of the COCO base so ultralytics doesn't re-download it.
_LEFT_CANDIDATES = [TLAB / "yolo11l.pt", ROOT.parent / "TrafficLab-3D/yolo11l.pt"]
DEF_LEFT = next((str(p) for p in _LEFT_CANDIDATES if p.exists()), "yolo11l.pt")

# Vehicle-ish classes we care about for the crash-reconstruction use case.
# Keys are lowercase class names as they appear in either COCO or VisDrone.
TWO_WHEELER = {"motor", "motorcycle", "bicycle"}
FOUR_WHEELER = {"car", "van", "truck", "bus", "tricycle", "awning-tricycle"}

PALETTE = {
    "car": (80, 220, 80), "van": (80, 220, 160), "truck": (80, 180, 220),
    "bus": (80, 140, 255), "motor": (0, 80, 255), "motorcycle": (0, 80, 255),
    "bicycle": (255, 120, 0), "tricycle": (200, 80, 220),
    "awning-tricycle": (200, 80, 180), "pedestrian": (160, 160, 160),
    "people": (130, 130, 130), "person": (160, 160, 160),
}
DEFAULT_COLOR = (200, 200, 200)


def draw_box(frame, box, label, color, thickness=2):
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.rectangle(frame, (x1, y1 - th - 4), (x1 + tw + 2, y1), color, -1)
    cv2.putText(frame, label, (x1 + 1, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (255, 255, 255), 1, cv2.LINE_AA)


def panel_label(img, text, sub=None):
    cv2.putText(img, text, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    if sub:
        cv2.putText(img, sub, (8, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, sub, (8, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)


def run_model(weights, footage, conf, imgsz, device, max_frames):
    """Returns list of per-frame detections and an aggregate stats dict."""
    model = YOLO(weights)
    per_frame = []  # list of [(box, cls_name, conf), ...]
    stats = {"count": defaultdict(int), "conf_sum": defaultdict(float),
             "two": 0, "four": 0, "total": 0, "frames": 0}

    results = model.predict(source=footage, device=device, conf=conf, imgsz=imgsz,
                            half=False, verbose=False, stream=True)
    for i, r in enumerate(results):
        if max_frames > 0 and i >= max_frames:
            break
        dets = []
        boxes = r.boxes.xyxy.cpu().numpy()
        cls_ids = r.boxes.cls.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        for j, box in enumerate(boxes):
            name = r.names[int(cls_ids[j])].lower()
            c = float(confs[j])
            dets.append((box, name, c))
            stats["count"][name] += 1
            stats["conf_sum"][name] += c
            stats["total"] += 1
            if name in TWO_WHEELER:
                stats["two"] += 1
            elif name in FOUR_WHEELER:
                stats["four"] += 1
        per_frame.append(dets)
        stats["frames"] += 1
    return per_frame, stats


def render(left_frames, right_frames, footage, out_path, left_name, right_name, fps):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    cap = cv2.VideoCapture(footage)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    tmp = out_path + ".tmp.mp4"
    writer = cv2.VideoWriter(tmp, fourcc, fps, (W * 2, H))

    n = min(len(left_frames), len(right_frames))
    for i in range(n):
        ok, frame = cap.read()
        if not ok:
            break
        left = frame.copy()
        right = frame.copy()
        for panel, dets, name in ((left, left_frames[i], left_name),
                                  (right, right_frames[i], right_name)):
            two = four = 0
            for box, cname, c in dets:
                color = PALETTE.get(cname, DEFAULT_COLOR)
                draw_box(panel, box, f"{cname[:5]} {c:.2f}", color)
                if cname in TWO_WHEELER:
                    two += 1
                elif cname in FOUR_WHEELER:
                    four += 1
            panel_label(panel, name, f"2-wheel={two}  4-wheel={four}  total={len(dets)}")
            cv2.putText(panel, f"frame {i}", (W - 110, H - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        combined = np.concatenate([left, right], axis=1)
        cv2.line(combined, (W, 0), (W, H), (60, 60, 60), 2)
        writer.write(combined)
    writer.release()
    cap.release()

    ret = os.system(f'ffmpeg -y -i "{tmp}" -vcodec libx264 -crf 20 -preset fast "{out_path}" 2>/dev/null')
    if ret == 0 and os.path.exists(out_path):
        os.remove(tmp)
    else:
        os.rename(tmp, out_path)


def print_stats(name, stats):
    print(f"\n=== {name} ===  frames={stats['frames']}  total_det={stats['total']}")
    print(f"  2-wheeler (motor/bicycle): {stats['two']}    4-wheeler (car/van/truck/bus): {stats['four']}")
    print(f"  {'class':<18}{'count':>7}{'avg_conf':>10}")
    for cname in sorted(stats["count"], key=lambda k: -stats["count"][k]):
        cnt = stats["count"][cname]
        avg = stats["conf_sum"][cname] / cnt if cnt else 0
        print(f"  {cname:<18}{cnt:>7}{avg:>10.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--footage", default=str(DEF_FOOTAGE))
    ap.add_argument("--left", default=DEF_LEFT, help="baseline weights")
    ap.add_argument("--right", default=str(DEF_RIGHT), help="fine-tuned weights")
    ap.add_argument("--output", default=str(DEF_OUTPUT))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=736)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--no-video", action="store_true")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.footage)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    left_name = os.path.basename(args.left)
    right_name = os.path.basename(args.right)

    print(f"[1/2] baseline: {args.left}")
    lf, ls = run_model(args.left, args.footage, args.conf, args.imgsz, args.device, args.max_frames)
    print(f"[2/2] fine-tune: {args.right}")
    rf, rs = run_model(args.right, args.footage, args.conf, args.imgsz, args.device, args.max_frames)

    print_stats(f"BASELINE  {left_name}", ls)
    print_stats(f"FINE-TUNE {right_name}", rs)

    if not args.no_video:
        print(f"\nRendering side-by-side -> {args.output}")
        render(lf, rf, args.footage, args.output, f"BASELINE {left_name}",
               f"FINE-TUNE {right_name}", fps)
        print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
