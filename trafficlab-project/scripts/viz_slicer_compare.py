"""
Side-by-side comparison:
  LEFT  — standard full-frame YOLO detect → ByteTrack(min_consecutive_frames=1)  [current]
  RIGHT — InferenceSlicer patches         → ByteTrack(min_consecutive_frames=2)  [proposed]

Includes trajectory traces so you can see the smoothness difference.

Usage (from trafficlab-project/):
    python scripts/viz_slicer_compare.py \
        --footage location/test1/footage/test1.mp4 \
        --model /Users/weihong/Documents/TrafficLab-3D/yolo11l.pt \
        --output location/test1/footage/test1_slicer_compare.mp4 \
        --max-frames 300
"""
import argparse
import os
import sys
from pathlib import Path

import warnings
warnings.filterwarnings('ignore', category=FutureWarning)

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

CONF   = 0.35
IOU    = 0.5
IMGSZ  = 960
DEVICE = "mps"

PALETTE = [
    (0, 200, 80),   (0, 140, 255),  (255, 80,  0),
    (220, 0, 220),  (0, 220, 220),  (220, 180, 0),
    (80, 80, 255),  (255, 0, 100),
]

def id_color(tid):
    return PALETTE[int(tid) % len(PALETTE)]


def draw_panel(frame, detections, traces, label):
    img = frame.copy()
    h, w = img.shape[:2]

    # draw traces
    for tid, pts in traces.items():
        if len(pts) < 2:
            continue
        color = id_color(tid)
        for i in range(1, len(pts)):
            alpha = i / len(pts)
            thick = max(1, int(alpha * 3))
            cv2.line(img, pts[i-1], pts[i], color, thick, cv2.LINE_AA)

    # draw boxes
    for i in range(len(detections)):
        x1, y1, x2, y2 = map(int, detections.xyxy[i])
        tid  = int(detections.tracker_id[i]) if detections.tracker_id is not None else -1
        conf = float(detections.confidence[i]) if detections.confidence is not None else 0.0
        cls  = int(detections.class_id[i]) if detections.class_id is not None else 0
        cls_name = detections.data.get('class_name', ['?'*20])[i] if detections.data else '?'
        color = id_color(tid)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        lbl = f"#{tid} {cls_name[:4]} {conf:.2f}"
        (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.rectangle(img, (x1, y1-th-4), (x1+tw+2, y1), color, -1)
        cv2.putText(img, lbl, (x1+1, y1-3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1, cv2.LINE_AA)

    n = len(detections)
    cv2.putText(img, label, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255,255,255), 2, cv2.LINE_AA)
    cv2.putText(img, f"tracks={n}", (8, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,200,200), 1, cv2.LINE_AA)
    return img


def run(footage, model_path, output, max_frames):
    PYTHON = sys.executable
    print(f"supervision {sv.__version__}")

    model = YOLO(model_path)
    names = model.names  # {id: name}

    cap   = cv2.VideoCapture(footage)
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30
    W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    n_frames = min(total, max_frames) if max_frames > 0 else total

    print(f"Video: {W}x{H} @ {fps:.1f}fps  ({n_frames} frames to process)")

    # ── trackers ──────────────────────────────────────────────────────────
    tracker_base   = sv.ByteTrack(track_activation_threshold=0.25,
                                   lost_track_buffer=30,
                                   minimum_matching_threshold=0.8,
                                   frame_rate=fps,
                                   minimum_consecutive_frames=1)   # current
    tracker_slicer = sv.ByteTrack(track_activation_threshold=0.25,
                                   lost_track_buffer=30,
                                   minimum_matching_threshold=0.8,
                                   frame_rate=fps,
                                   minimum_consecutive_frames=2)   # proposed

    # ── InferenceSlicer callback ───────────────────────────────────────────
    def yolo_callback(img_slice):
        res = model.predict(img_slice, conf=CONF, iou=IOU, imgsz=640,
                            device=DEVICE, verbose=False, half=False)[0]
        dets = sv.Detections.from_ultralytics(res)
        if dets.data is None:
            dets.data = {}
        dets.data['class_name'] = np.array([names[c] for c in dets.class_id])
        return dets

    slicer = sv.InferenceSlicer(callback=yolo_callback,
                                 slice_wh=(640, 640),
                                 overlap_wh=100,
                                 iou_threshold=0.5)

    # ── trace history ──────────────────────────────────────────────────────
    TRACE_LEN = 40
    traces_base   = {}   # tid -> deque of (cx,cy)
    traces_slicer = {}

    def update_traces(store, detections):
        for i in range(len(detections)):
            if detections.tracker_id is None:
                continue
            tid = int(detections.tracker_id[i])
            x1, y1, x2, y2 = map(int, detections.xyxy[i])
            cx, cy = (x1+x2)//2, (y1+y2)//2
            if tid not in store:
                from collections import deque
                store[tid] = deque(maxlen=TRACE_LEN)
            store[tid].append((cx, cy))

    # ── output writer ──────────────────────────────────────────────────────
    tmp = output + '.tmp.mp4'
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*'mp4v'),
                              fps, (W*2, H))

    cap = cv2.VideoCapture(footage)
    total_base_dets   = 0
    total_slicer_dets = 0

    for fi in range(n_frames):
        ret, frame = cap.read()
        if not ret:
            break

        # ── LEFT: full-frame predict ───────────────────────────────────────
        res = model.predict(frame, conf=CONF, iou=IOU, imgsz=IMGSZ,
                             device=DEVICE, verbose=False, half=False)[0]
        dets_base = sv.Detections.from_ultralytics(res)
        if dets_base.data is None:
            dets_base.data = {}
        dets_base.data['class_name'] = np.array([names[c] for c in dets_base.class_id])
        dets_base = tracker_base.update_with_detections(dets_base)
        update_traces(traces_base, dets_base)
        total_base_dets += len(dets_base)

        # ── RIGHT: InferenceSlicer ─────────────────────────────────────────
        dets_sliced = slicer(frame)
        if dets_sliced.data is None:
            dets_sliced.data = {}
        if 'class_name' not in dets_sliced.data:
            dets_sliced.data['class_name'] = np.array([names[c] for c in dets_sliced.class_id])
        dets_sliced = tracker_slicer.update_with_detections(dets_sliced)
        update_traces(traces_slicer, dets_sliced)
        total_slicer_dets += len(dets_sliced)

        # ── compose ────────────────────────────────────────────────────────
        left  = draw_panel(frame, dets_base,   {k: list(v) for k,v in traces_base.items()},
                           "CURRENT  (full-frame, min_consec=1)")
        right = draw_panel(frame, dets_sliced, {k: list(v) for k,v in traces_slicer.items()},
                           "PROPOSED (InferenceSlicer, min_consec=2)")

        # frame counter
        cv2.putText(left,  f"f{fi}", (W-55, H-8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150,150,150), 1)
        cv2.putText(right, f"f{fi}", (W-55, H-8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150,150,150), 1)

        combined = np.concatenate([left, right], axis=1)
        cv2.line(combined, (W, 0), (W, H), (60, 60, 60), 2)
        writer.write(combined)

        if fi % 30 == 0:
            print(f"  [{fi}/{n_frames}]  base_tracks={len(dets_base)}  slicer_tracks={len(dets_sliced)}")

    cap.release()
    writer.release()

    # re-encode h264
    ret = os.system(f'ffmpeg -y -i "{tmp}" -vcodec libx264 -crf 18 -preset fast "{output}" 2>/dev/null')
    if ret == 0:
        os.remove(tmp)
    else:
        os.rename(tmp, output)

    avg_b = total_base_dets / n_frames
    avg_s = total_slicer_dets / n_frames
    print(f"\n=== Summary ({n_frames} frames) ===")
    print(f"  Left  (current)  avg tracks/frame : {avg_b:.1f}")
    print(f"  Right (slicer)   avg tracks/frame : {avg_s:.1f}")
    print(f"  Δ = {avg_s - avg_b:+.1f}  ({(avg_s/avg_b - 1)*100:+.1f}% vs current)")
    print(f"\nSaved → {output}")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--footage',    default='location/test1/footage/test1.mp4')
    p.add_argument('--model',      default='/Users/weihong/Documents/TrafficLab-3D/yolo11l.pt')
    p.add_argument('--output',     default='location/test1/footage/test1_slicer_compare.mp4')
    p.add_argument('--max-frames', type=int, default=200)
    args = p.parse_args()
    run(args.footage, args.model, args.output, args.max_frames)
