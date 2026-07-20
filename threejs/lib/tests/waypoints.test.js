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

test('getState: heading 欄位優先於 segment 方向，且走最短弧', () => {
  const wps = [[1, 0, 0, 0], [11, 0, 10, Math.PI / 2]];
  const s = getState(wps, 6);
  assert.ok(Math.abs(s.h - Math.PI / 4) < 1e-9);
  const wrap = [[1, 0, 0, 3.0], [11, 0, 10, -3.0]];  // 跨 ±π
  const w = getState(wrap, 6);
  assert.ok(Math.abs(w.h) > 2.9, '跨 π 要走短弧（≈±π），不是掃過 0');
});
