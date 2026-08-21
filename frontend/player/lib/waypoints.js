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

// 收集每台 collider 碰撞前（含）的原始資料點（已扣 origin_offset_m），並套用兩個 throw
// 檢查（缺資料 / 軌跡在碰撞前中斷）。buildPreWaypoints（動畫 waypoint）與 buildPaths
// （simulate() 用的弧長路徑）共用這份萃取邏輯，唯一差異是後續怎麼把 {orig,x,z} 轉成
// 各自要的輸出格式，兩處的「壞資料就 throw」保證不會因為各自實作分岔而走樣。
function collectColliderPreFrames(trajectory, cfg) {
  const [offX, offZ] = cfg.origin_offset_m;
  const colliderVehicles = cfg.vehicles.filter(v => v.role === 'collider');
  const colliderIds = new Map(colliderVehicles.map(v => [v.track_id, []]));

  for (const frame of trajectory.frames) {
    for (const obj of frame.objects) {
      if (!obj.position_m) continue;
      if (!colliderIds.has(obj.tracked_id)) continue;
      colliderIds.get(obj.tracked_id).push({ orig: frame.frame_index,
        x: obj.position_m[0] - offX, z: obj.position_m[1] - offZ });
    }
  }

  return colliderVehicles.map(v => {
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
    return { vehicle: v, pre };
  });
}

// trajectory.meta.fps 優先；缺失/非正數時回退 cfg.frames.fps ?? 30 並 console.warn 記錄
// （見 brief：simulate() 的路徑用秒為單位，fps 選錯會讓整個速度剖面等比例錯開）。
function resolveTrajectoryFps(trajectory, cfg) {
  const metaFps = trajectory.meta?.fps;
  if (typeof metaFps === 'number' && Number.isFinite(metaFps) && metaFps > 0) return metaFps;
  const fallback = cfg.frames.fps ?? 30;
  if (typeof console !== 'undefined' && console.warn) {
    console.warn(`buildPaths: trajectory.meta.fps 缺失或無效，改用 cfg.frames.fps ?? 30 = ${fallback}`);
  }
  return fallback;
}

// trajectory + scene 設定 → 每台 collider 的 simulate() 路徑輸入 {vehicle, points:[{x,z,t}]}。
// t = frame_index / fps（真實秒數，fps 見 resolveTrajectoryFps）。點數 = 該車碰撞前的
// 全部原始資料點（不像 buildPreWaypoints 那樣用 sampleN 降採樣）——path.js 的弧長/速度剖面
// 直接吃時間序列，點越密速度剖面越準，降採樣只是動畫 waypoint 平滑用的手法，這裡不需要。
export function buildPaths(trajectory, cfg) {
  const fps = resolveTrajectoryFps(trajectory, cfg);
  return collectColliderPreFrames(trajectory, cfg).map(({ vehicle, pre }) => ({
    vehicle,
    points: pre.map(r => ({ x: r.x, z: r.z, t: r.orig / fps })),
  }));
}

// trajectory + scene 設定 → collider 碰前 waypoints 與 extras 全程 waypoints。
// Waypoint 格式: [animFrame, x, z, headingOrNull]
export function buildPreWaypoints(trajectory, cfg) {
  const toAnim = makeFrameMapper(cfg.frames);
  const [offX, offZ] = cfg.origin_offset_m;
  const colliderTrackIds = new Set(cfg.vehicles.filter(v => v.role === 'collider').map(v => v.track_id));
  const extraRaw = new Map();

  for (const frame of trajectory.frames) {
    for (const obj of frame.objects) {
      if (!obj.position_m) continue;
      if (colliderTrackIds.has(obj.tracked_id)) continue; // colliders 走 collectColliderPreFrames
      if (cfg.extras !== 'auto') continue;
      const rec = { orig: frame.frame_index, x: obj.position_m[0] - offX,
                    z: obj.position_m[1] - offZ, cls: obj.class };
      if (!extraRaw.has(obj.tracked_id)) extraRaw.set(obj.tracked_id, []);
      extraRaw.get(obj.tracked_id).push(rec);
    }
  }

  const toWp = r => [Math.round(toAnim(r.orig)), r.x, r.z, null];

  const colliders = collectColliderPreFrames(trajectory, cfg).map(({ vehicle, pre }) =>
    ({ vehicle, wps: dedup(sampleN(pre, vehicle.pre_samples ?? 15).map(toWp)) }));

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
