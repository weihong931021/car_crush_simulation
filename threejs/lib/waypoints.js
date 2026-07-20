import { makeFrameMapper } from './frames.js';

const EXTRA_MAX_SAMPLES = 60;

function sampleN(arr, n) {
  if (arr.length <= n) return [...arr];
  const out = [];
  for (let i = 0; i < n; i++) out.push(arr[Math.round(i * (arr.length - 1) / (n - 1))]);
  return out;
}

function dedup(wps) {
  const map = new Map();
  for (const wp of wps) map.set(wp[0], wp);
  return [...map.values()].sort((a, b) => a[0] - b[0]);
}

// trajectory + scene 設定 → collider 碰前 waypoints 與 extras 全程 waypoints。
// Waypoint 格式: [animFrame, x, z, headingOrNull]
export function buildPreWaypoints(trajectory, cfg) {
  const toAnim = makeFrameMapper(cfg.frames);
  const [offX, offZ] = cfg.origin_offset_m;
  const colliderIds = new Map(cfg.vehicles.filter(v => v.role === 'collider')
                                          .map(v => [v.track_id, []]));
  const extraRaw = new Map();

  for (const frame of trajectory.frames) {
    for (const obj of frame.objects) {
      if (!obj.position_m) continue;
      const rec = { orig: frame.frame_index, x: obj.position_m[0] - offX,
                    z: obj.position_m[1] - offZ, cls: obj.class };
      if (colliderIds.has(obj.tracked_id)) colliderIds.get(obj.tracked_id).push(rec);
      else if (cfg.extras === 'auto') {
        if (!extraRaw.has(obj.tracked_id)) extraRaw.set(obj.tracked_id, []);
        extraRaw.get(obj.tracked_id).push(rec);
      }
    }
  }

  const toWp = r => [Math.round(toAnim(r.orig)), r.x, r.z, null];

  const colliders = cfg.vehicles.filter(v => v.role === 'collider').map(v => {
    const data = (colliderIds.get(v.track_id) ?? []).sort((a, b) => a.orig - b.orig);
    const pre = data.filter(r => r.orig <= cfg.frames.source_collision);
    if (pre.length < 2) {
      throw new Error(`trajectory 缺 collider track_id=${v.track_id} 的碰前資料（${pre.length} 點）`);
    }
    return { vehicle: v, wps: dedup(sampleN(pre, v.pre_samples ?? 15).map(toWp)) };
  });

  const extras = [...extraRaw.entries()].map(([track_id, data]) => {
    data.sort((a, b) => a.orig - b.orig);
    return { track_id, cls: data[0].cls,
             wps: dedup(sampleN(data, EXTRA_MAX_SAMPLES).map(toWp)) };
  }).filter(e => e.wps.length >= 2);

  return { colliders, extras };
}
