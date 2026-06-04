"""
Detection filter visualization script.
Renders a side-by-side video: left=all detections, right=after bbox quality filter.
Filtered-out boxes are shown in red on the left panel.

Usage:
    python scripts/viz_detection_filter.py \
        --footage location/test1/footage/test1.mp4 \
        --config inference_config.yaml \
        --config-name mild_smoothing \
        --output location/test1/footage/test1_filter_viz.mp4 \
        --max-frames 300
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np
import yaml
from pathlib import Path
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).parent.parent))


def is_valid_detection(box, conf, cfg):
    if not cfg.get('enabled', False):
        return True
    if conf < cfg.get('min_conf', 0.0):
        return False
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w * h < cfg.get('min_area_px', 0):
        return False
    if h > 0:
        ar = w / h
        if ar < cfg.get('aspect_ratio_min', 0.0) or ar > cfg.get('aspect_ratio_max', float('inf')):
            return False
    return True


def draw_box(frame, box, label, color, thickness=2):
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.rectangle(frame, (x1, y1 - th - 4), (x1 + tw + 2, y1), color, -1)
    cv2.putText(frame, label, (x1 + 1, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)


def run(footage_path, config_path, config_name, output_path, max_frames, model_override=None):
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if 'configs' in raw:
        cfg = raw['configs'].get(config_name, next(iter(raw['configs'].values())))
    else:
        cfg = raw

    det_filter = cfg.get('detection_filter', {})
    model_cfg = cfg['model']
    tracking_cfg = cfg.get('tracking', {})

    weights = model_override or model_cfg['weights']
    print(f"Detection filter: {det_filter}")
    print(f"Loading model: {weights}")
    model = YOLO(weights)

    cap = cv2.VideoCapture(footage_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    frames_to_run = min(total, max_frames) if max_frames > 0 else total

    out_w, out_h = W * 2, H
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path + '.tmp.mp4', fourcc, fps, (out_w, out_h))

    track_kwargs = {
        "source": footage_path,
        "device": model_cfg['device'],
        "persist": True,
        "verbose": False,
        "stream": True,
        "conf": model_cfg['conf'],
        "iou": model_cfg['iou'],
        "imgsz": model_cfg['imgsz'],
        "half": model_cfg.get('half', False),
    }

    total_all = 0
    total_kept = 0
    total_rejected = 0

    # Color scheme
    COLOR_KEPT   = (0, 220, 80)   # green
    COLOR_REJECT = (0, 60, 220)   # red (BGR)
    COLOR_REJECT_REASON = {
        'conf':   (0, 60, 220),   # red
        'area':   (0, 165, 255),  # orange
        'aspect': (255, 0, 150),  # purple
    }

    for i, r in enumerate(model.track(**track_kwargs)):
        if i >= frames_to_run:
            break

        # Grab original frame from video
        frame_orig = r.orig_img.copy()
        left  = frame_orig.copy()
        right = frame_orig.copy()

        boxes   = r.boxes.xyxy.cpu().numpy()
        cls_ids = r.boxes.cls.cpu().numpy()
        confs   = r.boxes.conf.cpu().numpy()
        tids    = r.boxes.id.cpu().numpy() if r.boxes.id is not None else [None] * len(boxes)

        frame_kept = 0
        frame_rejected = 0

        for j, box in enumerate(boxes):
            cls_name = r.names[int(cls_ids[j])]
            conf = float(confs[j])
            tid = int(tids[j]) if tids[j] is not None else -1
            total_all += 1

            # Determine rejection reason
            reject_reason = None
            if det_filter.get('enabled', False):
                if conf < det_filter.get('min_conf', 0.0):
                    reject_reason = 'conf'
                else:
                    x1, y1, x2, y2 = box
                    w, h = x2 - x1, y2 - y1
                    area = w * h
                    if area < det_filter.get('min_area_px', 0):
                        reject_reason = 'area'
                    elif h > 0:
                        ar = w / h
                        if ar < det_filter.get('aspect_ratio_min', 0.0) or ar > det_filter.get('aspect_ratio_max', float('inf')):
                            reject_reason = 'aspect'

            label = f"{cls_name[:4]} {conf:.2f} #{tid}"

            if reject_reason is None:
                # Kept: green on both panels
                draw_box(left,  box, label, COLOR_KEPT)
                draw_box(right, box, label, COLOR_KEPT)
                frame_kept += 1
                total_kept += 1
            else:
                # Rejected: colored on left, skip on right
                color = COLOR_REJECT_REASON.get(reject_reason, COLOR_REJECT)
                draw_box(left, box, f"[{reject_reason}] {label}", color)
                frame_rejected += 1
                total_rejected += 1

        # Panel labels
        def add_panel_label(img, text, sub=None):
            cv2.putText(img, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            if sub:
                cv2.putText(img, sub, (8, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)

        add_panel_label(left,  "ALL DETECTIONS",
                        f"kept={frame_kept}  rejected={frame_rejected}  [red=conf  orange=area  purple=AR]")
        add_panel_label(right, "AFTER FILTER",
                        f"kept={frame_kept}")

        cv2.putText(left,  f"frame {i}", (W - 90, H - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
        cv2.putText(right, f"frame {i}", (W - 90, H - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

        combined = np.concatenate([left, right], axis=1)
        # Divider line
        cv2.line(combined, (W, 0), (W, H), (80, 80, 80), 2)

        writer.write(combined)

        if i % 50 == 0:
            pct = i / frames_to_run * 100
            print(f"  [{pct:.0f}%] frame {i}/{frames_to_run}  kept={total_kept}  rejected={total_rejected}")

    writer.release()

    # Re-encode to h264 for compatibility
    tmp = output_path + '.tmp.mp4'
    ret = os.system(f'ffmpeg -y -i "{tmp}" -vcodec libx264 -crf 18 -preset fast "{output_path}" 2>/dev/null')
    if ret == 0:
        os.remove(tmp)
        print(f"\nSaved: {output_path}")
    else:
        os.rename(tmp, output_path)
        print(f"\nSaved (no h264 re-encode): {output_path}")

    total_run = total_kept + total_rejected
    pct_rejected = total_rejected / total_run * 100 if total_run else 0
    print(f"\nSummary over {frames_to_run} frames:")
    print(f"  Total detections : {total_run}")
    print(f"  Kept             : {total_kept}  ({100-pct_rejected:.1f}%)")
    print(f"  Rejected         : {total_rejected}  ({pct_rejected:.1f}%)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--footage',     default='location/test1/footage/test1.mp4')
    parser.add_argument('--config',      default='inference_config.yaml')
    parser.add_argument('--config-name', default='mild_smoothing')
    parser.add_argument('--output',      default='location/test1/footage/test1_filter_viz.mp4')
    parser.add_argument('--max-frames',  type=int, default=300)
    parser.add_argument('--model',       default=None, help='Override model weights path')
    args = parser.parse_args()

    run(args.footage, args.config, args.config_name, args.output, args.max_frames, model_override=args.model)
