import { makeFrameMapper } from './frames.js';

const EXTRA_MAX_SAMPLES = 60;
const EXTRA_MAX_TRACKS = 12;
const COLLIDER_STALL_MIN_SOURCE_FRAMES = 5;
const COLLIDER_STALL_TOLERANCE_RATIO = 0.1;

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
  // trajectory.selected_tracked_ids（若存在）是 pipeline/人工圈定的合法 track 名單；
  // 非空時當 extras 白名單，避免原始輸出裡幾十條雜訊軌跡全變成模型 clone。
  const allowedExtraIds = Array.isArray(trajectory.selected_tracked_ids) && trajectory.selected_tracked_ids.length
    ? new Set(trajectory.selected_tracked_ids)
    : null;

  for (const frame of trajectory.frames) {
    for (const obj of frame.objects) {
      if (!obj.position_m) continue;
      const rec = { orig: frame.frame_index, x: obj.position_m[0] - offX,
                    z: obj.position_m[1] - offZ, cls: obj.class };
      if (colliderIds.has(obj.tracked_id)) colliderIds.get(obj.tracked_id).push(rec);
      else if (cfg.extras === 'auto' && (!allowedExtraIds || allowedExtraIds.has(obj.tracked_id))) {
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
    // 軌跡必須撐到接近 source_collision，否則法向量是拿兩個離碰撞很遠的最後位置算出來的
    // （車子會凍結後突然飛出去、撞擊圈畫在空地上）——寧可 throw 也不要默默算出幻影碰撞。
    const lastOrig = pre[pre.length - 1].orig;
    const span = cfg.frames.source_collision - cfg.frames.source_start;
    const tolerance = Math.max(span * COLLIDER_STALL_TOLERANCE_RATIO, COLLIDER_STALL_MIN_SOURCE_FRAMES);
    if (cfg.frames.source_collision - lastOrig > tolerance) {
      throw new Error(`collider track_id=${v.track_id} 的軌跡在 source frame ${lastOrig} 就中斷（碰撞在 ${cfg.frames.source_collision}），無法據此計算碰撞`);
    }
    return { vehicle: v, wps: dedup(sampleN(pre, v.pre_samples ?? 15).map(toWp)) };
  });

  // extras 數量無上限的話，一個未經篩選的原始 pipeline 輸出（60+ tracks）會生出等量
  // 帶陰影的 GLB clone，手機上直接卡死。依原始資料點數保留最多的 N 條，其餘明確警告丟棄。
  let extraEntries = [...extraRaw.entries()];
  if (extraEntries.length > EXTRA_MAX_TRACKS) {
    extraEntries.sort((a, b) => b[1].length - a[1].length);
    const dropped = extraEntries.length - EXTRA_MAX_TRACKS;
    extraEntries = extraEntries.slice(0, EXTRA_MAX_TRACKS);
    if (typeof console !== 'undefined' && console.warn) {
      console.warn(`extras 軌跡數超過上限 ${EXTRA_MAX_TRACKS}，已捨棄點數最少的 ${dropped} 條（保留 ${EXTRA_MAX_TRACKS} 條）`);
    }
  }

  const extras = extraEntries.map(([track_id, data]) => {
    data.sort((a, b) => a.orig - b.orig);
    return { track_id, cls: data[0].cls,
             wps: dedup(sampleN(data, EXTRA_MAX_SAMPLES).map(toWp)) };
  }).filter(e => e.wps.length >= 2);

  return { colliders, extras };
}
