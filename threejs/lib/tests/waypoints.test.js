import test from 'node:test';
import assert from 'node:assert/strict';
import { makeFrameMapper } from '../frames.js';
import { buildPreWaypoints } from '../waypoints.js';
import { getState } from '../interp.js';

const framesCfg = { source_start: 1, source_collision: 40, source_end: 60,
                    anim_start: 1, anim_collision: 32, anim_end: 89, fps: 30 };
const sceneCfg = {
  origin_offset_m: [12.5, 12.5], frames: framesCfg, extras: 'auto',
  vehicles: [
    { track_id: 1, class: 'Car', role: 'collider', pre_samples: 15 },
    { track_id: 2, class: 'Two_Wheeler', role: 'collider', pre_samples: 4 },
  ],
};

function synthTrajectory() {
  const frames = [];
  for (let i = 1; i <= 60; i++) {
    const objects = [{ tracked_id: 1, class: 'Car', position_m: [10, i * 0.4] }];
    if (i >= 20) objects.push({ tracked_id: 2, class: 'Two_Wheeler', position_m: [i * 0.3, 12] });
    if (i >= 5) objects.push({ tracked_id: 9, class: 'Car', position_m: [20, i * 0.2] });
    frames.push({ frame_index: i, objects });
  }
  return { frames };
}

test('makeFrameMapper: 端點與碰撞幀對映', () => {
  const m = makeFrameMapper(framesCfg);
  assert.equal(m(1), 1);
  assert.equal(m(40), 32);
  assert.equal(m(60), 89);
});

test('buildPreWaypoints: collider 取碰前、extras 全程、offset 已扣', () => {
  const { colliders, extras } = buildPreWaypoints(synthTrajectory(), sceneCfg);
  assert.equal(colliders.length, 2);
  const carWps = colliders[0].wps;
  assert.ok(carWps.every(wp => wp[0] <= 32), 'collider 只留碰前（anim ≤ 32）');
  assert.ok(Math.abs(carWps[0][1] - (10 - 12.5)) < 1e-9, 'x 已扣 offset');
  assert.equal(extras.length, 1);
  assert.equal(extras[0].track_id, 9);
  const lastExtra = extras[0].wps[extras[0].wps.length - 1];
  assert.ok(lastExtra[0] > 32, 'extras 涵蓋碰後');
});

test('buildPreWaypoints: 缺 collider track 直接 throw', () => {
  const bad = { ...sceneCfg, vehicles: [{ track_id: 777, class: 'Car', role: 'collider', pre_samples: 5 },
                                        sceneCfg.vehicles[1]] };
  assert.throws(() => buildPreWaypoints(synthTrajectory(), bad), /777/);
});

test('buildPreWaypoints: collider 軌跡在碰撞前中斷要 throw', () => {
  const traj = synthTrajectory();
  // 讓 track 2 只活到 source frame 25（碰撞在 40）
  traj.frames = traj.frames.map(f => f.frame_index > 25
    ? { ...f, objects: f.objects.filter(o => o.tracked_id !== 2) } : f);
  assert.throws(() => buildPreWaypoints(traj, sceneCfg), /中斷/);
});

function manyExtrasTrajectory() {
  const frames = [];
  for (let i = 1; i <= 60; i++) {
    const objects = [
      { tracked_id: 1, class: 'Car', position_m: [10, i * 0.4] },
      { tracked_id: 2, class: 'Two_Wheeler', position_m: [i * 0.3, 12] },
    ];
    if (i === 1 || i === 39) {
      for (let k = 0; k < 20; k++) {
        objects.push({ tracked_id: 100 + k, class: 'Car', position_m: [k, i] });
      }
    }
    frames.push({ frame_index: i, objects });
  }
  return { frames };
}

test('buildPreWaypoints: extras 超過上限要截斷並警告', () => {
  const traj = manyExtrasTrajectory();
  const originalWarn = console.warn;
  let warned = null;
  console.warn = (msg) => { warned = msg; };
  try {
    const { extras } = buildPreWaypoints(traj, sceneCfg);
    assert.equal(extras.length, 12);
    assert.ok(warned && /12/.test(warned), 'console.warn 要提到上限/捨棄數量，不能默默截斷');
  } finally {
    console.warn = originalWarn;
  }
});

test('buildPreWaypoints: selected_tracked_ids 不限制 extras（該欄位是碰撞車名單）', () => {
  const traj = synthTrajectory();
  traj.selected_tracked_ids = [1, 2];   // 只列 collider，如真實 filtered_output.json
  const { extras } = buildPreWaypoints(traj, sceneCfg);
  assert.equal(extras.length, 1);        // track 9 仍應成為 extras
  assert.equal(extras[0].track_id, 9);
});

test('getState: heading 欄位優先於 segment 方向，且走最短弧', () => {
  const wps = [[1, 0, 0, 0], [11, 0, 10, Math.PI / 2]];
  const s = getState(wps, 6);
  assert.ok(Math.abs(s.h - Math.PI / 4) < 1e-9);
  const wrap = [[1, 0, 0, 3.0], [11, 0, 10, -3.0]];  // 跨 ±π
  const w = getState(wrap, 6);
  assert.ok(Math.abs(w.h) > 2.9, '跨 π 要走短弧（≈±π），不是掃過 0');
});
