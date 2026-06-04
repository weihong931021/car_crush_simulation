"""
Side-by-side comparison:
  LEFT  — original 25fps  → ByteTrack
  RIGHT — RIFE 4x 100fps  → ByteTrack (all 4 intermediate frames fed to tracker)

Output is at original fps (25fps) so both panels show the same real-time moment.
Trajectory traces show the quality difference clearly.

Usage (from trafficlab-project/):
    python scripts/viz_rife_compare.py \
        --original  location/test1/footage/test1.mp4 \
        --rife      location/test1/footage/test1_4x_rife.mp4 \
        --model     /Users/weihong/Documents/TrafficLab-3D/yolo11l.pt \
        --output    location/test1/footage/test1_rife_compare.mp4 \
        --seconds   8
"""
import argparse
import os
import sys
import warnings
warnings.filterwarnings('ignore')

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO
from collections import deque

CONF   = 0.35
IOU    = 0.5
IMGSZ  = 960
DEVICE = "mps"
TRACE_LEN = 60   # frames of trace history

PALETTE = [
    (0, 220, 80),  (0, 140, 255), (255, 80,  0),
    (220, 0, 220), (0, 220, 220), (220, 180, 0),
    (80, 80, 255), (255, 0, 100), (0, 200, 160),
    (160, 255, 0),
]
def id_color(tid): return PALETTE[int(tid) % len(PALETTE)]


def draw_panel(frame, detections, traces, title, subtitle):
    img = frame.copy()
    h, w = img.shape[:2]

    # traces
    for tid, pts in traces.items():
        pts = list(pts)
        if len(pts) < 2: continue
        color = id_color(tid)
        for i in range(1, len(pts)):
            alpha = i / len(pts)
            cv2.line(img, pts[i-1], pts[i], color, max(1, int(alpha*3)), cv2.LINE_AA)

    # boxes
    for i in range(len(detections)):
        x1,y1,x2,y2 = map(int, detections.xyxy[i])
        tid  = int(detections.tracker_id[i]) if detections.tracker_id is not None else -1
        conf = float(detections.confidence[i]) if detections.confidence is not None else 0.
        _cn = detections.data.get('class_name')
        cls_name = _cn[i] if _cn is not None and len(_cn) > i else '?'
        color = id_color(tid)
        cv2.rectangle(img, (x1,y1), (x2,y2), color, 2)
        lbl = f"#{tid} {str(cls_name)[:4]} {conf:.2f}"
        (tw,th),_ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.rectangle(img,(x1,y1-th-4),(x1+tw+2,y1),color,-1)
        cv2.putText(img,lbl,(x1+1,y1-3),cv2.FONT_HERSHEY_SIMPLEX,0.4,(255,255,255),1,cv2.LINE_AA)

    # header
    cv2.rectangle(img, (0,0), (w, 62), (0,0,0), -1)
    cv2.rectangle(img, (0,0), (w, 62), (60,60,60), 1)
    cv2.putText(img, title,    (8,24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255,255,255), 2, cv2.LINE_AA)
    cv2.putText(img, subtitle, (8,50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180,220,180), 1, cv2.LINE_AA)
    cv2.putText(img, f"active tracks: {len(detections)}", (w-170,24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,220,100), 1, cv2.LINE_AA)
    return img


def run(orig_path, rife_path, model_path, output, seconds):
    model = YOLO(model_path)
    names = model.names

    cap_orig = cv2.VideoCapture(orig_path)
    cap_rife = cv2.VideoCapture(rife_path)

    fps_orig = cap_orig.get(cv2.CAP_PROP_FPS)   # 25
    fps_rife = cap_rife.get(cv2.CAP_PROP_FPS)   # 100
    W = int(cap_orig.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap_orig.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ratio = int(round(fps_rife / fps_orig))      # 4

    n_orig = min(int(cap_orig.get(cv2.CAP_PROP_FRAME_COUNT)),
                 int(seconds * fps_orig))

    print(f"Original : {fps_orig:.0f}fps  |  RIFE : {fps_rife:.0f}fps  |  ratio={ratio}x")
    print(f"Processing {n_orig} original frames ({seconds}s)")

    # ── trackers ─────────────────────────────────────────────────────────
    t_orig = sv.ByteTrack(track_activation_threshold=0.25, lost_track_buffer=30,
                           minimum_matching_threshold=0.8, frame_rate=fps_orig,
                           minimum_consecutive_frames=1)
    t_rife = sv.ByteTrack(track_activation_threshold=0.25, lost_track_buffer=int(30*ratio),
                           minimum_matching_threshold=0.8, frame_rate=fps_rife,
                           minimum_consecutive_frames=2)

    traces_orig  = {}
    traces_rife  = {}

    def update_traces(store, dets):
        for i in range(len(dets)):
            if dets.tracker_id is None: continue
            tid = int(dets.tracker_id[i])
            x1,y1,x2,y2 = map(int, dets.xyxy[i])
            if tid not in store:
                store[tid] = deque(maxlen=TRACE_LEN)
            store[tid].append(((x1+x2)//2, (y1+y2)//2))

    def detect(frame):
        res = model.predict(frame, conf=CONF, iou=IOU, imgsz=IMGSZ,
                             device=DEVICE, verbose=False, half=False)[0]
        dets = sv.Detections.from_ultralytics(res)
        if dets.data is None: dets.data = {}
        dets.data['class_name'] = np.array([names[c] for c in dets.class_id])
        return dets

    # ── output writer ─────────────────────────────────────────────────────
    tmp = output + '.tmp.mp4'
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*'mp4v'),
                              fps_orig, (W*2, H))

    total_orig_tracks = 0
    total_rife_tracks = 0

    for fi in range(n_orig):
        # ── original frame ────────────────────────────────────────────────
        ret, frame_orig = cap_orig.read()
        if not ret: break

        dets_o = detect(frame_orig)
        dets_o = t_orig.update_with_detections(dets_o)
        update_traces(traces_orig, dets_o)
        total_orig_tracks += len(dets_o)

        # ── RIFE: feed all `ratio` intermediate frames to tracker ─────────
        last_rife_frame = None
        last_dets_r = sv.Detections.empty()
        for ri in range(ratio):
            ret_r, frame_rife = cap_rife.read()
            if not ret_r: break
            last_rife_frame = frame_rife
            dets_r = detect(frame_rife)
            last_dets_r = t_rife.update_with_detections(dets_r)
            update_traces(traces_rife, last_dets_r)

        total_rife_tracks += len(last_dets_r)

        # ── compose panel for this real-time moment ───────────────────────
        rife_display = last_rife_frame if last_rife_frame is not None else frame_orig
        n_unique_orig = len(set(int(tid) for store in [traces_orig] for tid in store))
        n_unique_rife = len(set(int(tid) for store in [traces_rife] for tid in store))

        left  = draw_panel(frame_orig, dets_o, {k:list(v) for k,v in traces_orig.items()},
                            f"ORIGINAL  25fps",
                            f"min_consec=1  |  total IDs seen: {n_unique_orig}")
        right = draw_panel(rife_display, last_dets_r, {k:list(v) for k,v in traces_rife.items()},
                            f"RIFE 4x  100fps  (all {ratio} frames fed to tracker)",
                            f"min_consec=2  |  total IDs seen: {n_unique_rife}")

        # timestamp
        t_sec = fi / fps_orig
        for panel in [left, right]:
            cv2.putText(panel, f"{t_sec:.2f}s", (W-75, H-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150,150,150), 1)

        combined = np.concatenate([left, right], axis=1)
        cv2.line(combined, (W,0), (W,H), (80,80,80), 2)
        writer.write(combined)

        if fi % 25 == 0:
            print(f"  {fi:3d}/{n_orig}  orig_tracks={len(dets_o)}  rife_tracks={len(last_dets_r)}")

    cap_orig.release()
    cap_rife.release()
    writer.release()

    ret = os.system(f'ffmpeg -y -i "{tmp}" -vcodec libx264 -crf 18 -preset fast "{output}" 2>/dev/null')
    if ret == 0: os.remove(tmp)
    else:        os.rename(tmp, output)

    avg_o = total_orig_tracks / n_orig
    avg_r = total_rife_tracks / n_orig
    print(f"\n=== Summary ({n_orig} output frames = {seconds}s) ===")
    print(f"  Left  (original 25fps)  avg tracks/real-frame : {avg_o:.1f}")
    print(f"  Right (RIFE 100fps)     avg tracks/real-frame : {avg_r:.1f}")
    diff = avg_r - avg_o
    print(f"  Δ = {diff:+.1f}  ({diff/max(avg_o,0.1)*100:+.1f}%)")
    print(f"\nSaved → {output}")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--original', default='location/test1/footage/test1.mp4')
    p.add_argument('--rife',     default='location/test1/footage/test1_4x_rife.mp4')
    p.add_argument('--model',    default='/Users/weihong/Documents/TrafficLab-3D/yolo11l.pt')
    p.add_argument('--output',   default='location/test1/footage/test1_rife_compare.mp4')
    p.add_argument('--seconds',  type=float, default=7)
    args = p.parse_args()
    run(args.original, args.rife, args.model, args.output, args.seconds)
