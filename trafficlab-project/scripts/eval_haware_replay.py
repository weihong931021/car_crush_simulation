"""
Run h-aware 3D keypoint localization and output a TrafficLab replay JSON.

Identical detection loop to eval_haware.py, but writes a .json.gz in the
standard TrafficLab replay format so results can be loaded in the GUI.

--method selects one of two mutually exclusive per-frame strategies:
    geometric  Bridge PifPaf detections to YOLO track IDs via bbox IoU.
               Reads --yolo / --yolo-classes / --yolo-conf / --iou-threshold.
    crop       Crop each Pass-1 bbox and re-run PifPaf on the crop to recover
               more confident keypoints. Reads --crop-redetect / --crop-padding.
Both strategies' own flags keep their existing meaning and defaults; --method
only decides which one actually runs this invocation.

Usage:
    source /Users/eric/opt/anaconda3/bin/activate trafficlab && \\
    PYTORCH_ENABLE_MPS_FALLBACK=1 python scripts/eval_haware_replay.py \\
        --video location/test21/footage/test21-4.mp4 \\
        --g-proj location/test21/G_projection_test21.json \\
        --method geometric \\
        --spec-csv /tmp/autospec/engines.csv
"""
import argparse
import gzip
import json
import math
import os
import re
import sys

import cv2
import numpy as np
import PIL.Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trafficlab.projection.g_projection import GProjection
from trafficlab.motion.haware_localization import (
    HawareLocalizer,
    build_car_template,
    compute_car_dims_from_spec_csv,
    _FALLBACK_DIMS,
)
from trafficlab.io.replay_writer import ReplayWriter
from trafficlab.inference.pifpaf_haware_adapter import create_openpifpaf_predictor


def _check_resolution_match(video_path, g_data):
    """影片解析度 vs 標定的 undistort.resolution。不符就 exit，不是警告。"""
    cap = cv2.VideoCapture(video_path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if not w or not h:
        sys.exit(f"ERROR: 讀不到影片解析度：{video_path}")

    calib = (g_data.get("undistort") or {}).get("resolution")
    if not calib or len(calib) != 2:
        print(f"警告：G_projection 沒有 undistort.resolution，無法驗證解析度一致性"
              f"（影片為 {w}x{h}）", file=sys.stderr)
        return
    cw, ch = int(calib[0]), int(calib[1])
    if (cw, ch) != (w, h):
        sys.exit(
            f"ERROR: 影片解析度 {w}x{h} 與標定的 undistort.resolution {cw}x{ch} 不符。\n"
            f"  標定的內參（K 的 cx/cy）綁在 {cw}x{ch} 上，套到 {w}x{h} 的影格會讓每個\n"
            f"  像素座標投影到錯的地面位置——而且不會報錯，只會靜默偏移數公尺。\n"
            f"  修法：用與影片同解析度的影格重抽 cctv_<code>.png 並重標，\n"
            f"  或確認 --video 指到的是標定當時那支影片。")


def _infer_location_code(g_proj_path: str) -> str:
    """Extract location code from path like .../location/<code>/G_projection_*.json."""
    m = re.search(r'location[/\\]([^/\\]+)[/\\]', os.path.abspath(g_proj_path))
    if m:
        return m.group(1)
    # fallback: parent directory name
    return os.path.basename(os.path.dirname(os.path.abspath(g_proj_path)))


def _sat_floor_box(sat_coords, heading_deg: float, dims: dict, px_m: float):
    """Compute 4-corner vehicle footprint in sat pixels (same formula as pipeline.py)."""
    ang = math.radians(heading_deg)
    c, s = math.cos(ang), math.sin(ang)
    dx = (dims['length'] * px_m) / 2
    dy = (dims['width']  * px_m) / 2
    corners = np.array([[dx, dy], [dx, -dy], [-dx, -dy], [-dx, dy]])
    R = np.array([[c, -s], [s, c]])
    return (corners @ R.T + np.array(sat_coords)).tolist()


def _kp_bbox_xyxy(kp_24: np.ndarray, kp_conf: float):
    """Return (x1,y1,x2,y2) tight box around confident keypoints, or None."""
    pts = kp_24[(kp_24[:, 2] >= kp_conf) & ~((kp_24[:, 0] == 0) & (kp_24[:, 1] == 0))]
    if len(pts) == 0:
        return None
    return (float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max()))


def _single_confident_kp(kp_24: np.ndarray, kp_conf: float):
    """Return (kp_index, x, y) if exactly one keypoint clears kp_conf, else None.

    Counts directly rather than inferring from a degenerate (zero-area)
    _kp_bbox_xyxy box, since two different keypoint indices landing on the
    same pixel would also produce a degenerate box despite n=2.
    """
    mask = (kp_24[:, 2] >= kp_conf) & ~((kp_24[:, 0] == 0) & (kp_24[:, 1] == 0))
    idx = np.nonzero(mask)[0]
    if len(idx) != 1:
        return None
    i = int(idx[0])
    return i, float(kp_24[i, 0]), float(kp_24[i, 1])


def _point_in_box(x: float, y: float, box) -> bool:
    x0, y0, x1, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


def _match_by_bbox_iou(pifpaf_boxes, yolo_boxes, yolo_tids, iou_threshold=0.3):
    """Match each PifPaf bbox to the best-IoU YOLO bbox.

    Returns (tracked_ids, matched_boxes): parallel lists, one entry per PifPaf
    box. matched_boxes holds the assigned YOLO bbox (xyxy) or None when
    nothing cleared iou_threshold.
    """
    def _iou(a, b):
        if a is None or b is None:
            return 0.0
        ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
        ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
        return inter / ua if ua > 0 else 0.0

    tracked_ids, matched_boxes = [], []
    for pb in pifpaf_boxes:
        best_tid, best_box, best_iou = None, None, iou_threshold
        for yb, yt in zip(yolo_boxes, yolo_tids):
            v = _iou(pb, yb)
            if v > best_iou:
                best_iou, best_tid, best_box = v, yt, yb
        tracked_ids.append(best_tid)
        matched_boxes.append(best_box)
    return tracked_ids, matched_boxes


def _load_yolo_boxes_json(path: str, car_class: str) -> tuple:
    """Load a pre-computed replay JSON (e.g. from a separate YOLO run) and return
    ({frame_index: (boxes_xyxy, track_ids)}, {track_id: class}), filtered to
    comma-separated car_class — an alternative YOLO box source for --method geometric
    IoU matching, in place of a live model.

    第二個回傳值是每個 tracked_id 的**多數決類別**。沒有它的話輸出的 `class` 只能寫死
    'car'（本來就是這樣），下游的挑車介面就看不出哪一條 track 是機車——而事故當事車
    常常是機車。用多數決而非首次出現：YOLO 的類別在單幀會跳動（機車被瞄成 car 之類）。
    """
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rt') as f:
        data = json.load(f)
    car_classes = {value.strip() for value in car_class.split(',') if value.strip()}
    by_frame, tid_class_votes = {}, {}
    for fr in data['frames']:
        cars = [o for o in fr['objects'] if o.get('class') in car_classes and o.get('bbox_2d')]
        if cars:
            boxes = [tuple(o['bbox_2d']) for o in cars]
            tids  = [o.get('tracked_id') for o in cars]
            by_frame[fr['frame_index']] = (boxes, tids)
            for obj, tid in zip(cars, tids):
                if tid is not None:
                    votes = tid_class_votes.setdefault(tid, {})
                    votes[obj['class']] = votes.get(obj['class'], 0) + 1
    tid_class = {tid: max(votes.items(), key=lambda kv: kv[1])[0]
                 for tid, votes in tid_class_votes.items()}
    return by_frame, tid_class


def _extract_yolo(results) -> tuple:
    """Extract (boxes_xyxy, track_ids) from a YOLO result list."""
    boxes, tids = [], []
    for r in results:
        if r.boxes is None:
            continue
        xyxy = r.boxes.xyxy.cpu().numpy()
        ids  = r.boxes.id.cpu().numpy() if r.boxes.id is not None else [None] * len(xyxy)
        for box, tid in zip(xyxy, ids):
            boxes.append(tuple(float(v) for v in box))
            tids.append(int(tid) if tid is not None else None)
    return boxes, tids


def main():
    parser = argparse.ArgumentParser(
        description='h-aware localization → TrafficLab replay JSON')
    parser.add_argument('--video',      required=True,  help='Input video path')
    parser.add_argument('--g-proj',     required=True,  help='G_projection_*.json path')
    parser.add_argument('--out',        default=None,
                        help='Output .json.gz path '
                             '(default: output/haware/<location>/<video_stem>.json.gz)')
    parser.add_argument('--checkpoint', default='shufflenetv2k16-apollo-24')
    parser.add_argument('--spec-csv',   default=None,
                        help='engines.csv from ilyasozkurt/automobile-models-and-specs')
    parser.add_argument('--body-type',  default='Sedan')
    parser.add_argument('--kp-conf',    type=float, default=0.2)
    parser.add_argument('--frames',          type=int,   default=-1,  help='-1 = all')
    parser.add_argument('--pifpaf-threshold', type=float, default=0.01,
                        help='PifPaf instance score threshold (default 0.01)')
    parser.add_argument('--seed-threshold',   type=float, default=0.01,
                        help='PifPaf CIF seed threshold (default 0.01)')
    parser.add_argument('--method', required=True, choices=['geometric', 'crop'],
                        help='geometric = bridge to YOLO track IDs via bbox IoU '
                             '(reads --yolo*/--iou-threshold); '
                             'crop = crop-and-redetect for better keypoints '
                             '(reads --crop-redetect/--crop-padding). Mutually exclusive: '
                             'only the selected strategy runs.')
    parser.add_argument('--crop-redetect', action='store_true',
                        help='Crop each Pass-1 bbox with 50%% padding and re-run PifPaf '
                             '(only takes effect when --method crop)')
    parser.add_argument('--crop-padding', type=float, default=0.5,
                        help='Fractional padding around bbox for crop-and-redetect crop (default 0.5)')
    # geometric matching: YOLO track-ID matching (only when --method geometric)
    parser.add_argument('--yolo',          default='models/best.pt',
                        help='YOLO model path/name for track-ID matching (default: models/best.pt, '
                             'ByteTrack tracker); pass --yolo "" to disable and leave tracked_id=None')
    parser.add_argument('--yolo-conf',     type=float, default=0.25,
                        help='YOLO detection confidence threshold (default 0.25)')
    parser.add_argument('--yolo-classes',  default=None,
                        help='Comma-separated YOLO class indices to keep, e.g. "3" for car '
                             'in models/best.pt — class indices are model-specific, check '
                             '--yolo model.names (default: all classes)')
    parser.add_argument('--iou-threshold', type=float, default=0.3,
                        help='Minimum bbox IoU to accept a PifPaf↔YOLO match (default 0.3)')
    parser.add_argument('--yolo-boxes-json', default=None,
                        help='Path to a pre-computed replay JSON (e.g. pipeline.py output) '
                             'supplying car bbox_2d + tracked_id per frame, used as the YOLO '
                             'box source for --method geometric IoU matching instead of '
                             'running a live YOLO model. When set, --yolo/--yolo-conf/'
                             '--yolo-classes are ignored.')
    parser.add_argument('--yolo-boxes-class', default='car',
                        help='Comma-separated class values in --yolo-boxes-json to treat as vehicles '
                             '(default "car")')
    parser.add_argument('--start-frame', type=int, default=0,
                        help='First frame index to process (default 0). Frames before this '
                             'are read and discarded, not seeked — CAP_PROP_POS_FRAMES '
                             'seeking has been unreliable on some test videos. --frames counts '
                             'from this point, not from frame 0.')
    parser.add_argument('--bbox-fallback', action='store_true',
                        help='For YOLO tracks with no PifPaf match, emit a fallback record '
                             'whose position comes from the bbox reference point through the '
                             'homography (status="bbox_fallback", coords in '
                             'bbox_fallback_sat_coords — NOT sat_coords, which stays under '
                             'the localization authority). Downstream must opt in via '
                             'filter_and_enrich --accept-bbox-fallback.')
    parser.add_argument('--localizer', choices=['procrustes', 'reprojection'], default='procrustes',
                        help='procrustes = closed-form 2D Procrustes on lifted sat coords '
                             '(default); reprojection = fit the 3D template directly against '
                             'PifPaf pixel positions via nonlinear least-squares '
                             '(HawareLocalizer.localize_reprojection)')
    args = parser.parse_args()

    if args.method == 'geometric' and not args.yolo and not args.yolo_boxes_json:
        print('[haware] --method geometric but --yolo is empty: no track-ID matching '
              'will happen, tracked_id will be null for every detection.')
    if args.method == 'crop' and not args.crop_redetect:
        print('[haware] --method crop but --crop-redetect was not passed: no re-detection '
              'will happen, this run is equivalent to plain Pass-1 PifPaf.')

    # --- G projection ---
    g_proj_dir = os.path.dirname(os.path.abspath(args.g_proj))
    with open(args.g_proj) as f:
        g_data = json.load(f)
    g_engine = GProjection(g_data, base_dir=g_proj_dir)

    # 解析度三方一致性——必須在載模型之前擋下，否則要等幾十秒才發現輸入根本不匹配。
    # 影片解析度必須等於標定當時的解析度，否則每個像素座標都被套在錯的內參上：
    # 失敗方式不是報錯而是**靜默偏移**（test1 就是這樣——標定寫 1920x1004、影片是
    # 1920x1080，畫面上緣造成數公尺的地面誤差，至今沒有任何程式會發現）。
    _check_resolution_match(args.video, g_data)

    location_code = _infer_location_code(args.g_proj)

    # --- Dimensions & template ---
    prior_map_all = {}          # class → dims；bbox 備援定位的 h/2 視差修正用
    if args.spec_csv:
        dims = compute_car_dims_from_spec_csv(args.spec_csv, body_type=args.body_type)
    else:
        d = g_proj_dir
        dims_path = None
        for _ in range(5):
            candidate = os.path.join(d, 'prior_dimensions.json')
            if os.path.exists(candidate):
                dims_path = candidate
                break
            d = os.path.dirname(d)
        if dims_path:
            with open(dims_path) as f:
                pj = json.load(f)
            dims = pj.get('measurements_visdrone', {}).get('car', dict(_FALLBACK_DIMS))
            prior_map_all = pj.get('measurements_visdrone', {})
            print(f'[haware] Using prior_dimensions.json: {dims}')
        else:
            dims = dict(_FALLBACK_DIMS)
            prior_map_all = {}
            print(f'[haware] Using built-in fallback dims: {dims}')

    template = build_car_template(dims)
    localizer = HawareLocalizer(g_engine, template, kp_conf=args.kp_conf)
    px_m = g_engine.px_per_m

    # --- OpenPifPaf (provider imports are isolated in the Haware adapter) ---
    predictor = create_openpifpaf_predictor(
        args.checkpoint,
        instance_threshold=args.pifpaf_threshold,
        seed_threshold=args.seed_threshold,
    )

    # --- YOLO box source (only loaded for --method geometric) ---
    # Either a live model (--yolo) or a pre-computed replay JSON (--yolo-boxes-json);
    # the latter takes priority when both are set.
    yolo_model = None
    yolo_classes = None
    yolo_boxes_by_frame = None
    yolo_tid_class = {}          # tracked_id → 來源偵測類別（live-YOLO 路徑留空）
    if args.method == 'geometric' and args.yolo_boxes_json:
        yolo_boxes_by_frame, yolo_tid_class = _load_yolo_boxes_json(
            args.yolo_boxes_json, args.yolo_boxes_class)
        n_loaded = sum(len(v[0]) for v in yolo_boxes_by_frame.values())
        print(f'[haware] Loaded {n_loaded} "{args.yolo_boxes_class}" boxes across '
              f'{len(yolo_boxes_by_frame)} frames from {args.yolo_boxes_json} '
              f'(IoU threshold={args.iou_threshold})')
    elif args.method == 'geometric' and args.yolo:
        from ultralytics import YOLO as _YOLO
        yolo_model = _YOLO(args.yolo)
        if args.yolo_classes:
            yolo_classes = [int(c) for c in args.yolo_classes.split(',')]
        cls_str = str(yolo_classes) if yolo_classes else 'all'
        print(f'[haware] YOLO model loaded: {args.yolo} classes={cls_str} (IoU threshold={args.iou_threshold})')

    # --- Video metadata ---
    cap   = cv2.VideoCapture(args.video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start = max(0, args.start_frame)
    limit = total if args.frames < 0 else min(total, start + args.frames)

    # --- Output path ---
    if args.out:
        out_path = args.out
    else:
        video_stem = os.path.splitext(os.path.basename(args.video))[0]
        out_path = os.path.join('output', 'haware', location_code, f'{video_stem}.json.gz')
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # --- Replay JSON skeleton ---
    out_data = {
        'mp4_path':             args.video,
        'meta':                 {'resolution': [W, H], 'fps': fps},
        'location_code':        location_code,
        'mp4_frame_count':      total,
        'animation_frame_count': 0,
        'frames':               [],
    }

    # --- Frame loop ---
    n_det = n_ok = n_ambig = n_fail = 0
    n_matched = 0
    n_yolo_det = 0
    n_yolo_frames = 0
    n_frames_pifpaf_fewer = 0        # frames where PifPaf count < YOLO count
    n_bbox_fallback = 0              # --bbox-fallback 產生的備援定位筆數
    bbox_fallback_tids: set = set()  # 拿過備援定位的 track
    yolo_tid_frames: dict = {}       # tid → frames YOLO detected it
    matched_tid_frames: dict = {}    # tid → frames PifPaf matched it
    no_pifpaf_tid_frames: dict = {}  # tid → YOLO saw it but PifPaf detected nothing
    no_match_tid_frames: dict = {}   # tid → PifPaf detected but IoU match failed
    print(f'Processing frames {start}..{limit - 1} ({limit - start}/{total}) → {out_path}')

    for frame_idx in range(limit):
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx < start:
            continue

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = PIL.Image.fromarray(rgb)
        try:
            predictions, _, _ = predictor.pil_image(pil)
        except Exception as e:
            print(f'  frame {frame_idx}: predictor error — {e}')
            out_data['frames'].append({'frame_index': frame_idx, 'objects': []})
            continue

        # --- geometric matching (--method geometric only): YOLO tracking + IoU matching ---
        tracked_ids = [None] * len(predictions)
        bbox_2d_list = [None] * len(predictions)
        kp_override = {}   # j (post-filter index) -> merged kp_24, set below for
                            # detections that absorbed a stray single-keypoint match
        if yolo_model is not None or yolo_boxes_by_frame is not None:
            if yolo_model is not None:
                yolo_res = yolo_model.track(frame, persist=True, conf=args.yolo_conf,
                                            classes=yolo_classes, tracker='bytetrack.yaml',
                                            verbose=False)
                yolo_boxes, yolo_tids = _extract_yolo(yolo_res)
            else:
                yolo_boxes, yolo_tids = yolo_boxes_by_frame.get(frame_idx, ([], []))
            n_yolo_det += len(yolo_boxes)
            if yolo_boxes:
                n_yolo_frames += 1
            for yt in yolo_tids:
                if yt is not None:
                    yolo_tid_frames[yt] = yolo_tid_frames.get(yt, 0) + 1
            if len(predictions) < len(yolo_boxes):
                n_frames_pifpaf_fewer += 1
            if predictions:
                pifpaf_boxes = [_kp_bbox_xyxy(ann.data, args.kp_conf) for ann in predictions]
                tracked_ids, matched_boxes = _match_by_bbox_iou(
                    pifpaf_boxes, yolo_boxes, yolo_tids, iou_threshold=args.iou_threshold)
                n_matched += sum(1 for t in tracked_ids if t is not None)
                matched_this_frame = set(t for t in tracked_ids if t is not None)
                for t in matched_this_frame:
                    matched_tid_frames[t] = matched_tid_frames.get(t, 0) + 1
                for yt in set(yt for yt in yolo_tids if yt is not None):
                    if yt not in matched_this_frame:
                        no_match_tid_frames[yt] = no_match_tid_frames.get(yt, 0) + 1

                # bbox_2d: the matched YOLO box when there is one; otherwise
                # fall back to the PifPaf-keypoint box (no YOLO box to borrow).
                bbox_2d_list = [mb if mb is not None else pb
                                for mb, pb in zip(matched_boxes, pifpaf_boxes)]

                # Single-keypoint recovery: a PifPaf detection with only one
                # confident keypoint has a zero-area bbox, so its IoU against
                # every YOLO box is 0 and it never clears iou_threshold above —
                # even when it's really just a fragment of a car YOLO already
                # tracks. If its one point falls inside exactly one (unpadded)
                # YOLO box, borrow that YOLO box's track: merge the point into
                # the detection already IoU-matched to that track this frame
                # (more keypoints -> better localizer fit) and drop this
                # fragment so it doesn't also appear as its own object; if no
                # such detection exists this frame, just tag the fragment with
                # the track id directly (it will still fail localization on
                # its own, but stays colour-consistent downstream).
                absorbed = set()
                for j, ann in enumerate(predictions):
                    if tracked_ids[j] is not None:
                        continue
                    single = _single_confident_kp(ann.data, args.kp_conf)
                    if single is None:
                        continue
                    kp_idx, x, y = single
                    containing = [k for k, yb in enumerate(yolo_boxes) if _point_in_box(x, y, yb)]
                    if len(containing) != 1:
                        continue
                    tid = yolo_tids[containing[0]]
                    if tid is None:
                        continue
                    main_j = next((jj for jj in range(len(predictions))
                                   if jj != j and tracked_ids[jj] == tid), None)
                    if main_j is None:
                        tracked_ids[j] = tid
                        continue
                    main_kp = kp_override.get(main_j, predictions[main_j].data.copy())
                    if main_kp[kp_idx, 2] < args.kp_conf or (
                            main_kp[kp_idx, 0] == 0 and main_kp[kp_idx, 1] == 0):
                        main_kp[kp_idx] = ann.data[kp_idx]
                        kp_override[main_j] = main_kp
                    absorbed.add(j)

                if absorbed:
                    keep = [j for j in range(len(predictions)) if j not in absorbed]
                    predictions  = [predictions[j] for j in keep]
                    tracked_ids  = [tracked_ids[j] for j in keep]
                    bbox_2d_list = [bbox_2d_list[j] for j in keep]
                    kp_override  = {new_j: kp_override[old_j]
                                    for new_j, old_j in enumerate(keep) if old_j in kp_override}

                # Detections that didn't clear the IoU threshold keep their own
                # PifPaf per-frame instance index as an id (offset by 500 to
                # stay clear of real YOLO track IDs), so they stay
                # colour-distinguishable downstream. This is NOT a real track:
                # the offset index has no meaning from one frame to the next.
                for j in range(len(tracked_ids)):
                    if tracked_ids[j] is None:
                        tracked_ids[j] = j + 500
            else:
                # True no-PifPaf frames: YOLO ran but PifPaf found nothing
                for yt in set(yt for yt in yolo_tids if yt is not None):
                    no_pifpaf_tid_frames[yt] = no_pifpaf_tid_frames.get(yt, 0) + 1

        frame_objects = []
        for j, ann in enumerate(predictions):
            n_det += 1

            # crop-and-redetect (--method crop only): crop around Pass-1 bbox and re-detect
            # kp_override (--method geometric only): use the merged keypoints when this
            # detection absorbed a stray single-keypoint match (see geometric matching above)
            kp_24 = kp_override.get(j, ann.data)
            if args.method == 'crop' and args.crop_redetect:
                bx, by, bw, bh = ann.bbox()
                pad_x, pad_y = bw * args.crop_padding, bh * args.crop_padding
                x0 = max(0, int(bx - pad_x))
                y0 = max(0, int(by - pad_y))
                x1 = min(W, int(bx + bw + pad_x))
                y1 = min(H, int(by + bh + pad_y))
                if x1 > x0 and y1 > y0:
                    try:
                        crop_preds, _, _ = predictor.pil_image(pil.crop((x0, y0, x1, y1)))
                    except Exception:
                        crop_preds = []
                    if crop_preds:
                        best = max(crop_preds,
                                   key=lambda a: sum(1 for kp in a.data if kp[2] >= args.kp_conf))
                        kp_24 = best.data.copy()
                        kp_24[:, 0] += x0
                        kp_24[:, 1] += y0

            if args.localizer == 'reprojection':
                result = localizer.localize_reprojection(kp_24)
            else:
                result = localizer.localize(kp_24)

            sat_coords = list(result.sat_coords) if result.sat_coords is not None else None
            have_heading = result.heading is not None

            sfb = None
            if have_heading and sat_coords is not None:
                sfb = _sat_floor_box(sat_coords, result.heading, dims, px_m)

            if result.status == 'ok':
                n_ok += 1
            elif result.status == 'ambiguous_heading':
                n_ambig += 1
            else:
                n_fail += 1

            frame_objects.append({
                'id':               j,
                'tracked_id':       tracked_ids[j],
                # 來源偵測的類別；橋接不到（或走 live-YOLO 路徑）才退回 'car'。
                # 注意：定位用的**模板仍然是汽車模板**，這個欄位只說明它原本被偵測成什麼，
                # 不代表 localize() 換了模板——機車的位置誤差問題不因這行而改變。
                'class':            yolo_tid_class.get(tracked_ids[j], 'car'),
                'confidence':       result.confidence,
                'bbox_2d':          list(bbox_2d_list[j]) if bbox_2d_list[j] is not None else None,
                'reference_point':  None,
                'sat_coords':       sat_coords,
                'have_heading':     have_heading,
                'have_measurements': True,
                'default_heading':  False,
                'heading':          result.heading,
                'speed_kmh':        0.0,
                'sat_floor_box':    sfb,
                'bbox_3d':          None,
                # h-aware diagnostic fields
                'n_keypoints':      result.n_keypoints,
                'status':           result.status,
                'method':           result.method,
                # 品質判據。下游（filter_and_enrich_output.py → build_scene.py）只讀
                # sat_coords、不看 status，所以外推幀原本會靜默流進場景包；把判據一起
                # 寫出來，讓挑 track 時能真的據此拒答。
                #   spread_m   > 8      → homography 外推，度量位置不可信
                #   n_wheel_kp >= 2     → heading 可信（實測 2.42°）；0–1 個時中位誤差約 98°
                'spread_m':         round(result.spread_m, 3),
                'n_wheel_kp':       result.n_wheel_kp,
                # raw CCTV keypoints [x, y, conf] × 24 for overlay rendering
                'kp_cctv':          kp_24.tolist(),
                # per-keypoint sat-plane projection, same indexing as kp_cctv;
                # null where that keypoint wasn't confident enough to lift
                'kp_sat':           [list(result.p_sat[i]) if i in result.p_sat else None
                                     for i in range(24)],
            })

        # --- bbox 備援定位（--bbox-fallback）---
        # PifPaf 的 Apollo-24 是**汽車**關鍵點模型，機車偵測不到——實測 tainan_yongkong
        # 全片 7 條機車 track 與 PifPaf 框的最佳 IoU 全部是 0.000（不是門檻問題）。
        # 沒被任何 PifPaf 偵測認領的 YOLO track，改用 bbox 參考點過單應性取位置。
        # 這與 run_inference 的 center_box+z_cam 座標模型相同，有已知系統性偏移
        # （bbox 中心不是地面接觸點；正解需要相機高度）——所以座標**不寫 sat_coords**：
        # 那是 localization authority 的權威欄位，政策被下游測試凍結為只信 status='ok'。
        # 放 bbox_fallback_sat_coords，由 filter_and_enrich --accept-bbox-fallback
        # 明示採用，provenance 全程機器可讀，任何一層都能拒收。
        if args.bbox_fallback and (yolo_model is not None or yolo_boxes_by_frame is not None):
            claimed = set(t for t in tracked_ids if t is not None)
            for fb_box, fb_tid in zip(yolo_boxes, yolo_tids):
                if fb_tid is None or fb_tid in claimed:
                    continue
                fb_cls = yolo_tid_class.get(fb_tid, 'car')
                fb_h = float((prior_map_all.get(fb_cls) or {}).get('height',
                                                                   dims.get('height', 1.55)))
                fx1, fy1, fx2, fy2 = fb_box
                proj = g_engine.get_ground_contact_from_box(
                    (fx1, fy1, fx2 - fx1, fy2 - fy1), fb_h,
                    ref_method=g_data.get('ref_method', 'center_bottom_side'),
                    proj_method=g_data.get('proj_method', 'down_h'))
                n_bbox_fallback += 1
                bbox_fallback_tids.add(fb_tid)
                frame_objects.append({
                    'id':               len(frame_objects),
                    'tracked_id':       fb_tid,
                    'class':            fb_cls,
                    'confidence':       None,
                    'bbox_2d':          [float(v) for v in fb_box],
                    'reference_point':  list(proj.get('cctv_ref_point') or []) or None,
                    'sat_coords':       None,      # 權威欄位留給 authority，這裡絕不寫
                    'bbox_fallback_sat_coords': [float(proj['sat_coords'][0]),
                                                 float(proj['sat_coords'][1])],
                    'have_heading':     False,
                    'have_measurements': fb_cls in prior_map_all,
                    'default_heading':  False,
                    'heading':          None,
                    'speed_kmh':        0.0,
                    'sat_floor_box':    None,
                    'bbox_3d':          None,
                    'n_keypoints':      0,
                    'status':           'bbox_fallback',
                    'method':           'bbox_homography',
                    'spread_m':         None,
                    'n_wheel_kp':       0,
                    'kp_cctv':          None,
                    'kp_sat':           None,
                })

        out_data['frames'].append({'frame_index': frame_idx, 'objects': frame_objects})

        if (frame_idx + 1) % 50 == 0:
            print(f'  frame {frame_idx + 1}/{limit} — '
                  f'ok={n_ok} ambig={n_ambig} fail={n_fail}')

    cap.release()
    # Not `limit`: that's the pre-computed cap (possibly from an unreliable
    # CAP_PROP_FRAME_COUNT), not how far the loop actually got before a failed
    # cap.read() broke it early. Read back the last frame actually recorded instead,
    # same pattern as pipeline.py's animation_frame_count (= the loop's actual
    # last index, not the pre-computed frames_to_process cap).
    n_frames_processed = len(out_data['frames'])
    out_data['animation_frame_count'] = (
        out_data['frames'][-1]['frame_index'] if out_data['frames'] else 0
    )

    ReplayWriter.write(out_path, out_data)

    print(f'\nDone: {n_frames_processed} frames, {n_det} detections')
    print(f'  ok={n_ok}  ambiguous={n_ambig}  failed={n_fail}')
    if args.bbox_fallback:
        print(f'  bbox 備援定位: {n_bbox_fallback} 筆'
              f'（{len(bbox_fallback_tids)} tracks: {sorted(bbox_fallback_tids)}）')
    if yolo_model is not None or yolo_boxes_by_frame is not None:
        pct = 100 * n_matched / n_det if n_det > 0 else 0.0
        print(f'  YOLO frames:      {n_yolo_frames}/{n_frames_processed}  detections: {n_yolo_det}')
        print(f'  PifPaf < YOLO 幀: {n_frames_pifpaf_fewer}/{n_frames_processed}')
        print(f'  track-ID matched: {n_matched}/{n_det} ({pct:.1f}%)')
        if yolo_tid_frames:
            print(f'\n  {"ID":>4}  {"YOLO幀":>6}  {"配對幀":>6}  {"無PifPaf":>8}  {"IoU失敗":>7}  {"配對率":>6}')
            print(f'  {"----":>4}  {"------":>6}  {"------":>6}  {"--------":>8}  {"-------":>7}  {"------":>6}')
            for tid in sorted(yolo_tid_frames):
                yf = yolo_tid_frames[tid]
                mf = matched_tid_frames.get(tid, 0)
                np_ = no_pifpaf_tid_frames.get(tid, 0)
                nm  = no_match_tid_frames.get(tid, 0)
                ratio = 100 * mf / yf if yf > 0 else 0.0
                print(f'  {tid:>4}  {yf:>6}  {mf:>6}  {np_:>8}  {nm:>7}  {ratio:>5.1f}%')
    print(f'Saved → {out_path}')


if __name__ == '__main__':
    main()
