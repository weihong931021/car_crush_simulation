// 契約缺口測試（2026-07-24 審計結論）：對「期望行為尚未實作」的輸入驗證缺口，
// 直接斷言期望行為，並用 node:test 的 { todo: '已知缺口：…' } 標記——todo 測試
// 失敗只會記為 # todo、不影響 exit code（已在 node v22 實驗驗證），套件保持綠色；
// 缺口補實作後把 todo 標記拿掉，即轉為正式回歸測試。
// 最後一個測試是真基準（現在就要過）：meta.fps 與 cfg.frames.fps 並存時採 meta 值。
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPaths } from '../waypoints.js';
import { simulate } from '../simulate.js';
import { buildPath, speedProfile } from '../path.js';

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
    frames.push({ frame_index: i, objects });
  }
  return { frames };
}

// 目前的回退路徑會 console.warn；todo 測試走到它時把警告吞掉，保持測試輸出乾淨。
function silencingWarn(fn) {
  const originalWarn = console.warn;
  console.warn = () => {};
  try { return fn(); } finally { console.warn = originalWarn; }
}

// ── 缺口 1：fps 無效值應 throw ───────────────────────────────────────────────
test('buildPaths: cfg.frames.fps <= 0 或非有限值、且 meta 無 fps 時應 throw',
     { todo: '已知缺口：目前靜默回退 cfg.frames.fps，t = frame/fps 產生 Infinity/NaN 時間軸' },
     () => {
  // fps=0 → t 全為 Infinity；負值 → 時間軸倒流；NaN/Infinity → t 全為 NaN/0。
  // 這些都應在入口擋下（throw 且訊息提到 fps），而不是靜默產出壞時間軸給 simulate()。
  for (const badFps of [0, -25, NaN, Infinity]) {
    const cfg = { ...sceneCfg, frames: { ...framesCfg, fps: badFps } };
    silencingWarn(() => {
      assert.throws(() => buildPaths(synthTrajectory(), cfg), /fps/,
        `fps=${badFps} 應 throw，不得靜默產生非有限時間軸`);
    });
  }
});

// ── 缺口 2：origin_offset_m 缺失/含 NaN 應 throw ─────────────────────────────
test('buildPaths: cfg.origin_offset_m 缺失或含 NaN 時應 throw 乾淨錯誤',
     { todo: '已知缺口：目前缺失時是解構的 raw TypeError、含 NaN 時靜默產生 NaN 座標' },
     () => {
  const traj = synthTrajectory();
  traj.meta = { fps: 30 }; // 給足 fps，讓本測試只檢驗 offset 這一個缺口

  // 缺失：應是自家丟出的 Error（訊息提到 origin_offset_m），
  // 不是 `const [offX, offZ] = undefined` 解構炸出的 raw TypeError。
  const { origin_offset_m, ...noOffsetCfg } = sceneCfg;
  assert.throws(() => buildPaths(traj, noOffsetCfg),
    (err) => err.constructor === Error && /origin_offset_m/.test(err.message),
    '缺 origin_offset_m 應丟乾淨的 Error，不是 raw TypeError');

  // 含 NaN：目前會靜默解構、所有座標變 NaN，一路流進 simulate()。
  const nanCfg = { ...sceneCfg, origin_offset_m: [NaN, 12.5] };
  assert.throws(() => buildPaths(traj, nanCfg), /origin_offset_m/,
    'origin_offset_m 含 NaN 應 throw，不得靜默產生 NaN 座標');
});

// ── 缺口 3：simulate 的 vehicle 缺 mass_kg 應 throw ──────────────────────────
// 汽車沿 +Z、機車沿 +X 等速 10 m/s 穿越原點（與 simulate.test.js 同一組必撞 fixture）
const carPts  = Array.from({ length: 41 }, (_, i) => ({ x: 0, z: -20 + i, t: i * 0.1 }));
const motoPts = Array.from({ length: 41 }, (_, i) => ({ x: -20 + i, z: 0, t: i * 0.1 }));
function veh(points, length_m, width_m, mass_kg) {
  const v = { path: buildPath(points), profile: speedProfile(points), length_m, width_m };
  if (mass_kg !== undefined) v.mass_kg = mass_kg; // 缺口情境：完全不帶 mass_kg 欄位
  return v;
}

test('simulate: vehicle 缺 mass_kg 時應 throw',
     { todo: '已知缺口：目前 1/undefined=NaN，衝量後兩車速度全 NaN、凍結在接觸點直到 maxTime' },
     () => {
  // 實測現況：不會 throw、collided=true，但碰後 frictionStep 的 NaN 速度讓兩車
  // 原地凍結（機車 10 m/s 瞬間停死＝無限減速），也永遠到不了停止門檻。
  // 期望：simulate 在入口驗 mass_kg，缺失/非正數就 throw（訊息提到 mass_kg）。
  assert.throws(
    () => simulate({ vehicles: [veh(carPts, 4.69, 1.85), veh(motoPts, 1.85, 0.7, 200)],
                     kA: 1, kB: 1 }),
    /mass_kg/,
    '缺 mass_kg 應 throw，不得靜默算出 NaN 碰撞');
});

// ── 真基準：meta.fps 優先於 cfg.frames.fps（現在就要過）─────────────────────
test('buildPaths: meta.fps 與 cfg.frames.fps 同時存在且不同值時，時間軸長度採 meta.fps', () => {
  const traj = synthTrajectory();
  traj.meta = { fps: 20 }; // cfg.frames.fps=30 同時存在且不同值
  const paths = buildPaths(traj, sceneCfg);
  const car = paths.find(p => p.vehicle.track_id === 1);
  // 汽車碰前資料涵蓋 source frame 1..40 → 時間軸總長 = (40-1)/fps，採 meta 的 20fps
  const span = car.points.at(-1).t - car.points[0].t;
  assert.ok(Math.abs(span - 39 / 20) < 1e-9, `時間軸長度應為 39/20=1.95s，實得 ${span}`);
  assert.ok(Math.abs(span - 39 / 30) > 1e-6, '不得採 cfg.frames.fps=30 的 1.3s');
  assert.ok(Math.abs(car.points[0].t - 1 / 20) < 1e-9, 't 起點也應是 frame/meta.fps');
});
