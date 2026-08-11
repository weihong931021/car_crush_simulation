"""Visual + numeric sanity check for an h-aware replay JSON.

Plots each track's satellite-plane trajectory over sat_<code>.png and prints a
per-track quality table. The key quality signal is *keypoint spread*: all 24
Apollo-24 keypoints of one car should lift to sat points inside a ~4 m box, so a
spread far above the vehicle's own length means the projection is extrapolating
(typically a vehicle near the horizon, where one CCTV pixel covers metres).

Usage:
    .venv-pifpaf/bin/python scripts/viz_haware_replay.py \\
        output/haware/taipei-cm/taipei-cm_procrustes.json.gz
"""
import argparse
import gzip
import json
import os
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load(path):
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rt') as f:
        return json.load(f)


def kp_spread_m(obj, px_per_m):
    """Max pairwise distance between this detection's lifted keypoints, in metres."""
    pts = [p for p in obj.get('kp_sat') or [] if p is not None]
    if len(pts) < 2:
        return None
    a = np.asarray(pts, dtype=float)
    d = np.linalg.norm(a[:, None, :] - a[None, :, :], axis=-1)
    return float(d.max()) / px_per_m


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('replay', help='replay .json / .json.gz from eval_haware_replay.py')
    ap.add_argument('--location-dir', default=None,
                    help='location/<code>/ dir (default: derived from location_code)')
    ap.add_argument('--out', default=None, help='output PNG (default: alongside replay)')
    ap.add_argument('--max-spread-m', type=float, default=8.0,
                    help='detections whose keypoint spread exceeds this are flagged '
                         'as extrapolated (default 8.0 m, ~2x a sedan length)')
    ap.add_argument('--fit-all', action='store_true',
                    help='zoom out until every localization fits, instead of framing '
                         'on the calibrated area (sat raster + FOV polygon)')
    args = ap.parse_args()

    data = load(args.replay)
    code = data['location_code']
    loc_dir = args.location_dir or os.path.join('location', code)
    g_path = os.path.join(loc_dir, f'G_projection_{code}.json')
    sat_path = os.path.join(loc_dir, f'sat_{code}.png')

    with open(g_path) as f:
        g = json.load(f)
    px_per_m = g['parallax']['px_per_meter']
    fov = g['homography'].get('fov_polygon') or []

    # ---- collect per-track series ----
    tracks = {}
    for fr in data['frames']:
        for o in fr['objects']:
            if o.get('status') != 'ok' or not o.get('sat_coords'):
                continue
            tracks.setdefault(o['tracked_id'], []).append({
                'frame': fr['frame_index'],
                'xy': o['sat_coords'],
                'n_kp': o['n_keypoints'],
                'heading': o.get('heading'),
                'spread': kp_spread_m(o, px_per_m),
            })

    # real YOLO tracks first; ids >= 500 are per-frame PifPaf fragments, not tracks
    real = {t: v for t, v in tracks.items() if t is not None and t < 500}
    frag = {t: v for t, v in tracks.items() if t is None or t >= 500}

    print(f'{code}: {len(data["frames"])} frames, px_per_m={px_per_m:.2f}')
    print(f'  real tracks: {len(real)}   per-frame fragments (id>=500): {len(frag)}\n')
    print(f'{"tid":>5} {"幀數":>5} {"kp中位":>6} {"spread中位(m)":>13} '
          f'{"外推幀":>6} {"位移(m)":>8} {"heading抖動(度)":>14}')
    print('  ' + '-' * 66)
    for t in sorted(real):
        s = real[t]
        spreads = [p['spread'] for p in s if p['spread'] is not None]
        med_spread = statistics.median(spreads) if spreads else float('nan')
        bad = sum(1 for v in spreads if v > args.max_spread_m)
        xy = np.array([p['xy'] for p in s], dtype=float)
        dist = float(np.linalg.norm(xy[-1] - xy[0])) / px_per_m
        hs = [p['heading'] for p in s if p['heading'] is not None]
        jitter = float('nan')
        if len(hs) > 1:
            dh = np.diff(np.unwrap(np.radians(hs)))
            jitter = float(np.degrees(np.abs(dh)).mean())
        print(f'{t:>5} {len(s):>5} {statistics.median(p["n_kp"] for p in s):>6.0f} '
              f'{med_spread:>13.1f} {bad:>6} {dist:>8.1f} {jitter:>14.1f}')

    # ---- plot ----
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 11))
    if os.path.exists(sat_path):
        img = plt.imread(sat_path)
        ax.imshow(img)
        H, W = img.shape[0], img.shape[1]
    else:
        W = H = None
        print(f'  (sat image not found at {sat_path}; plotting without background)')

    if fov:
        p = np.array(fov + [fov[0]], dtype=float)
        ax.plot(p[:, 0], p[:, 1], '--', color='deepskyblue', lw=1.2,
                label='FOV polygon (calibrated area)')

    cmap = plt.get_cmap('tab10')
    for i, t in enumerate(sorted(real)):
        xy = np.array([p['xy'] for p in real[t]], dtype=float)
        c = cmap(i % 10)
        ax.plot(xy[:, 0], xy[:, 1], '-o', color=c, ms=3, lw=1.5, label=f'track {t}')
        ax.annotate(f'{t}', xy[0], color=c, fontsize=11, fontweight='bold')

    if frag:
        fx = np.array([p['xy'] for v in frag.values() for p in v], dtype=float)
        ax.plot(fx[:, 0], fx[:, 1], 'x', color='0.6', ms=4, alpha=0.5,
                label=f'unmatched fragments ({len(fx)})')

    if W:
        ax.add_patch(plt.Rectangle((0, 0), W, H, fill=False, ec='white', lw=2,
                                   label='satellite image extent'))

    # Frame on the calibrated area (sat raster + FOV polygon), not on the data:
    # a single blown-up extrapolation would otherwise shrink the map to a speck.
    allxy = np.array([p['xy'] for v in tracks.values() for p in v], dtype=float)
    box = [[0, 0], [W or 0, H or 0]] + ([list(map(list, fov))] if fov else [])
    ref = np.vstack([np.array(b, dtype=float).reshape(-1, 2) for b in box])
    x0, y0 = ref.min(0)
    x1, y1 = ref.max(0)
    # No sat raster and no FOV polygon leaves a degenerate box — fall back to the data
    if args.fit_all or (x1 - x0) < 1 or (y1 - y0) < 1:
        ref = np.vstack([ref, allxy])
        x0, y0 = ref.min(0)
        x1, y1 = ref.max(0)
    pad = 0.08 * max(x1 - x0, y1 - y0)
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y1 + pad, y0 - pad)
    off = int(((allxy[:, 0] < x0 - pad) | (allxy[:, 0] > x1 + pad) |
               (allxy[:, 1] < y0 - pad) | (allxy[:, 1] > y1 + pad)).sum())
    if off:
        print(f'  {off}/{len(allxy)} 個定位點落在校正範圍外，未畫進圖裡（--fit-all 可全部納入）')
        ax.set_xlabel(f'{off}/{len(allxy)} localizations fall outside this view')

    ax.set_title(f'{code} — h-aware satellite trajectories\n{os.path.basename(args.replay)}')
    ax.legend(loc='upper right', fontsize=8)
    ax.set_aspect('equal')

    out = args.out or os.path.splitext(os.path.splitext(args.replay)[0])[0] + '_tracks.png'
    fig.savefig(out, dpi=110, bbox_inches='tight')
    print(f'\nSaved plot -> {out}')


if __name__ == '__main__':
    main()
