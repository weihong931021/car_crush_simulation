import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPath, speedProfile, sampleAt, advance, speedAt } from '../path.js';

// 沿 +Z 直線，等速 10 m/s，每 0.1 秒一點
const straight = Array.from({ length: 11 }, (_, i) => ({ x: 0, z: i, t: i * 0.1 }));

test('buildPath: 累積弧長與總長', () => {
  const p = buildPath(straight);
  assert.equal(p.pts.length, 11);
  assert.ok(Math.abs(p.length - 10) < 1e-9);
  assert.ok(Math.abs(p.pts[5].s - 5) < 1e-9);
});

test('sampleAt: 位置內插與切線方向', () => {
  const p = buildPath(straight);
  const a = sampleAt(p, 2.5);
  assert.ok(Math.abs(a.x) < 1e-9 && Math.abs(a.z - 2.5) < 1e-9);
  assert.ok(Math.abs(a.heading) < 1e-9);            // 朝 +Z ⇒ heading 0
  const start = sampleAt(p, -5), end = sampleAt(p, 999);
  assert.ok(Math.abs(start.z - 0) < 1e-9, '超出範圍夾在起點');
  assert.ok(Math.abs(end.z - 10) < 1e-9, '超出範圍夾在終點');
});

test('speedProfile + speedAt: 還原 10 m/s', () => {
  const prof = speedProfile(straight);
  assert.ok(Math.abs(speedAt(prof, 5, 1) - 10) < 1e-6);
  assert.ok(Math.abs(speedAt(prof, 5, 0.5) - 5) < 1e-6, 'k 線性縮放');
});

test('advance: k=1 一秒走 10 m；k=0.5 走 5 m', () => {
  const p = buildPath(straight), prof = speedProfile(straight);
  assert.ok(Math.abs(advance(p, prof, 0, 1, 1) - 10) < 1e-3);
  assert.ok(Math.abs(advance(p, prof, 0, 1, 0.5) - 5) < 1e-3);
});

test('advance: 變速剖面—慢段耗時較長', () => {
  // 前半 10 m/s、後半 2 m/s
  const pts = [];
  let z = 0, t = 0;
  for (let i = 0; i < 5; i++) { pts.push({ x: 0, z, t }); z += 1; t += 0.1; }
  for (let i = 0; i < 6; i++) { pts.push({ x: 0, z, t }); z += 1; t += 0.5; }
  const p = buildPath(pts), prof = speedProfile(pts);
  const s1 = advance(p, prof, 0, 1, 1);
  assert.ok(s1 > 5 && s1 < 10, `一秒應跨過快段進入慢段，實得 ${s1}`);
});

test('轉彎路徑: heading 隨切線變化', () => {
  const pts = [{x:0,z:0,t:0},{x:0,z:1,t:0.1},{x:1,z:2,t:0.2},{x:2,z:2,t:0.3}];
  const p = buildPath(pts);
  const h0 = sampleAt(p, 0.5).heading, h1 = sampleAt(p, p.length - 0.1).heading;
  assert.ok(Math.abs(h0) < 1e-6, '起段朝 +Z');
  assert.ok(Math.abs(h1 - Math.PI / 2) < 0.2, '末段朝 +X');
});

// ── 資料淨化管線：smoothPoints / trimFrozenTail / extendPoints ────────────────
import { smoothPoints, trimFrozenTail, extendPoints } from '../path.js';

function noisyLine(n = 60, dt = 0.02, noise = 0.12) {
  // 沿 +Z 等速 5 m/s，x 疊上確定性鋸齒噪音（模擬偵測抖動）
  return Array.from({ length: n }, (_, i) => ({
    t: i * dt,
    x: noise * ((i % 2) * 2 - 1),
    z: i * dt * 5,
  }));
}

test('smoothPoints: 側向噪音大幅降低、首尾錨定、t 不變', () => {
  const raw = noisyLine();
  const sm = smoothPoints(raw, { windowSec: 0.3 });
  const dev = pts => pts.slice(1, -1).reduce((s, p) => s + p.x * p.x, 0) / (pts.length - 2);
  assert.ok(dev(sm) < dev(raw) * 0.05, `噪音應大減：${dev(raw)} → ${dev(sm)}`);
  assert.deepEqual([sm[0].x, sm[0].z], [raw[0].x, raw[0].z]);
  assert.deepEqual([sm.at(-1).x, sm.at(-1).z], [raw.at(-1).x, raw.at(-1).z]);
  assert.ok(sm.every((p, i) => p.t === raw[i].t));
});

test('smoothPoints: 平滑後 heading 抖動下降', () => {
  const raw = noisyLine();
  const headings = pts => {
    const path = buildPath(pts);
    const hs = [];
    for (let s = 0.3; s < path.length; s += 0.3) hs.push(sampleAt(path, s).heading);
    let sum = 0;
    for (let i = 1; i < hs.length; i++) sum += Math.abs(hs[i] - hs[i - 1]);
    return sum / (hs.length - 1);
  };
  assert.ok(headings(smoothPoints(raw, { windowSec: 0.3 })) < headings(raw) * 0.3);
});

test('trimFrozenTail: 切掉凍結尾、保留可信段；乾淨資料不動', () => {
  // 前 2s 等速 5 m/s，最後 0.6s 凍結（幾乎不動）
  const pts = [];
  for (let t = 0; t <= 2.0; t += 0.05) pts.push({ t, x: 0, z: t * 5 });
  const zEnd = pts.at(-1).z;
  for (let t = 2.05; t <= 2.6; t += 0.05) pts.push({ t, x: 0, z: zEnd + (t - 2.0) * 0.05 });
  const trimmed = trimFrozenTail(pts);
  assert.ok(trimmed.at(-1).t <= 2.05 + 1e-9, `凍結尾應被切除，實際尾端 t=${trimmed.at(-1).t}`);
  const clean = Array.from({ length: 40 }, (_, i) => ({ t: i * 0.05, x: 0, z: i * 0.25 }));
  assert.equal(trimFrozenTail(clean).length, clean.length, '乾淨資料不得被修剪');
});

test('trimFrozenTail: 最多切 maxTrimSec，不吃掉真實減速', () => {
  // 全程慢速（0.3 m/s < 門檻）——若無上限會被切到剩 2 點
  const slow = Array.from({ length: 100 }, (_, i) => ({ t: i * 0.05, x: 0, z: i * 0.015 }));
  const trimmed = trimFrozenTail(slow, { maxTrimSec: 1.2 });
  assert.ok(slow.at(-1).t - trimmed.at(-1).t <= 1.2 + 0.05 + 1e-9);
});

test('extendPoints: 沿末向直線外插、等速、標記證據終點', () => {
  const pts = Array.from({ length: 21 }, (_, i) => ({ t: i * 0.1, x: 0, z: i * 0.5 })); // +Z 5 m/s
  const { points: ext, evidenceEndIndex } = extendPoints(pts, { extendM: 10 });
  assert.equal(evidenceEndIndex, 20);
  assert.equal(ext.length, 22);
  const tail = ext.at(-1);
  assert.ok(Math.abs(tail.x) < 1e-9 && Math.abs(tail.z - (10 + 10)) < 1e-9, '沿 +Z 外插 10 m');
  assert.ok(Math.abs((tail.t - pts.at(-1).t) - 2) < 1e-6, '5 m/s 走 10 m 應費時 2 s');
});

// ── splineResample ────────────────────────────────────────────────────────────
import { splineResample } from '../path.js';

test('splineResample: 通過每個原始節點（插值而非逼近）', () => {
  const pts = [{t:0,x:0,z:0},{t:1,x:1,z:2},{t:2,x:3,z:2.5},{t:3,x:4,z:4}];
  const rs = splineResample(pts, { stepSec: 0.05 });
  for (const k of pts) {
    const near = rs.reduce((best, p) => Math.abs(p.t - k.t) < Math.abs(best.t - k.t) ? p : best);
    assert.ok(Math.hypot(near.x - k.x, near.z - k.z) < 0.03, `節點 t=${k.t} 應被通過`);
  }
  assert.deepEqual([rs.at(-1).x, rs.at(-1).z], [4, 4], '終點精確保留');
});

test('splineResample: 折線轉角的 heading 跳動被抹平', () => {
  // 直角折線：+Z 然後 +X
  const pts = [];
  for (let i = 0; i <= 10; i++) pts.push({ t: i * 0.1, x: 0, z: i * 0.5 });
  for (let i = 1; i <= 10; i++) pts.push({ t: 1 + i * 0.1, x: i * 0.5, z: 5 });
  const maxTurn = arr => {
    const path = buildPath(arr);
    let prev = null, worst = 0;
    for (let s = 0.1; s < path.length; s += 0.1) {
      const h = sampleAt(path, s).heading;
      if (prev != null) {
        let d = Math.abs(h - prev); if (d > Math.PI) d = 2 * Math.PI - d;
        if (d > worst) worst = d;
      }
      prev = h;
    }
    return worst;
  };
  const before = maxTurn(pts);
  const after = maxTurn(splineResample(pts, { stepSec: 1 / 60 }));
  // 90° 直角是極端情形：總轉角不變（幾何事實），樣條的貢獻是把它攤開成連續彎。
  // 實測 90°→約 56°；真實軌跡的殘餘轉角在個位數度，攤開效果比例更高。
  assert.ok(after < before * 0.7, `單步最大轉角應明顯下降：${(before*180/Math.PI).toFixed(1)}° → ${(after*180/Math.PI).toFixed(1)}°`);
});

test('splineResample: t 單調遞增、取樣密度正確', () => {
  const pts = Array.from({ length: 20 }, (_, i) => ({ t: i * 0.1, x: Math.sin(i * 0.4), z: i * 0.3 }));
  const rs = splineResample(pts, { stepSec: 1 / 60 });
  for (let i = 1; i < rs.length; i++) assert.ok(rs[i].t > rs[i - 1].t);
  assert.ok(rs.length > pts.length * 2, '取樣應比原始點密');
});

// ── decimatePoints ────────────────────────────────────────────────────────────
import { decimatePoints } from '../path.js';

test('decimatePoints: 依 knotSec 抽稀、首尾必留', () => {
  const pts = Array.from({ length: 101 }, (_, i) => ({ t: i * 0.02, x: i, z: 0 })); // 2s @50Hz
  const d = decimatePoints(pts, { knotSec: 0.25 });
  assert.ok(d.length >= 8 && d.length <= 11, `2s/0.25s 應約 9 個錨點，實得 ${d.length}`);
  assert.deepEqual([d[0].t, d[0].x], [0, 0]);
  assert.deepEqual([d.at(-1).t, d.at(-1).x], [2, 100]);
  for (let i = 1; i < d.length; i++) assert.ok(d[i].t > d[i - 1].t);
});

test('decimate+spline: 帶噪節點的 heading worst-case 大幅下降', () => {
  // 平滑後仍殘留的節點噪音（幅度 0.03m）
  const pts = Array.from({ length: 100 }, (_, i) => ({
    t: i * 0.02, x: 0.03 * Math.sin(i * 2.1), z: i * 0.06,  // ~3 m/s 直行 + 殘噪
  }));
  const worst = arr => {
    const path = buildPath(arr);
    let prev = null, w = 0;
    for (let s = 0.1; s < path.length; s += 0.1) {
      const h = sampleAt(path, s).heading;
      if (prev != null) { let d = Math.abs(h - prev); if (d > Math.PI) d = 2 * Math.PI - d; if (d > w) w = d; }
      prev = h;
    }
    return w;
  };
  const direct = worst(splineResample(pts));
  const viaKnots = worst(splineResample(decimatePoints(pts, { knotSec: 0.25 })));
  assert.ok(viaKnots < direct * 0.5, `抽稀後應大減：${(direct*180/Math.PI).toFixed(1)}° → ${(viaKnots*180/Math.PI).toFixed(1)}°`);
});

// ── limitAcceleration（縱向慣性）──────────────────────────────────────────────
import { limitAcceleration } from '../path.js';

test('limitAcceleration: 假加速尖峰被壓平、位置不變、t0 錨定', () => {
  // 0.5 m/s 蠕行中突然一步跳到 5 m/s（≈90 m/s²，物理不可能）再回落
  const pts = [];
  let z = 0, t = 0;
  for (let i = 0; i < 20; i++) { pts.push({ t, x: 0, z }); z += 0.025; t += 0.05; } // 0.5 m/s
  pts.push({ t: t, x: 0, z: z + 0.25 });  // 一步 0.25m/0.05s = 5 m/s
  z += 0.25; t += 0.05;
  for (let i = 0; i < 20; i++) { z += 0.025; t += 0.05; pts.push({ t, x: 0, z }); }
  const out = limitAcceleration(pts, { aMaxMps2: 3.0, bMaxMps2: 7.5 });
  assert.equal(out.length, pts.length);
  assert.equal(out[0].t, pts[0].t, 't0 錨定');
  out.forEach((p, i) => { assert.equal(p.x, pts[i].x); assert.equal(p.z, pts[i].z); }); // 位置=證據，不動
  // 重算加速度：任何相鄰段的 dv/dt 不得超過上限（含些許數值裕度）
  for (let i = 2; i < out.length; i++) {
    const v1 = Math.hypot(out[i-1].x-out[i-2].x, out[i-1].z-out[i-2].z) / (out[i-1].t-out[i-2].t);
    const v2 = Math.hypot(out[i].x-out[i-1].x, out[i].z-out[i-1].z) / (out[i].t-out[i-1].t);
    const a = (v2 - v1) / (out[i].t - out[i-1].t);
    assert.ok(a < 3.0 * 1.5 + 0.5, `第 ${i} 段加速度 ${a.toFixed(1)} m/s² 仍超標`);
  }
});

test('limitAcceleration: 本來就可行的等速資料不被改動', () => {
  const pts = Array.from({ length: 30 }, (_, i) => ({ t: i * 0.1, x: 0, z: i * 0.5 })); // 5 m/s 等速
  const out = limitAcceleration(pts);
  for (let i = 0; i < pts.length; i++) {
    assert.ok(Math.abs(out[i].t - pts[i].t) < 1e-9, `等速資料 t 不得漂移（第 ${i} 點）`);
  }
});

// ── rdpSimplify（路徑直線化）─────────────────────────────────────────────────
import { rdpSimplify } from '../path.js';

test('rdpSimplify: 帶噪直線塌成兩個端點（真正的直線段）', () => {
  const pts = Array.from({ length: 80 }, (_, i) => ({
    t: i * 0.05, x: 0.05 * Math.sin(i * 1.7), z: i * 0.1,   // 8m 直行 + 5cm 殘噪
  }));
  const out = rdpSimplify(pts, { epsilonM: 0.15 });
  assert.ok(out.length <= 4, `噪音尺度內的直線應收成極少錨點，實得 ${out.length}`);
  assert.deepEqual([out[0].t, out.at(-1).z], [0, pts.at(-1).z], '端點精確保留');
});

test('rdpSimplify: 真實轉角保留（偏差超過門檻的點不會被收掉）', () => {
  const pts = [];
  for (let i = 0; i <= 20; i++) pts.push({ t: i * 0.1, x: 0, z: i * 0.4 });       // 直行 8m
  for (let i = 1; i <= 20; i++) pts.push({ t: 2 + i * 0.1, x: i * 0.4, z: 8 });   // 右轉直行
  const out = rdpSimplify(pts, { epsilonM: 0.15 });
  // 轉角點 (0,8) 必須存活
  assert.ok(out.some(p => Math.hypot(p.x - 0, p.z - 8) < 0.05), '轉角錨點應保留');
  assert.ok(out.length <= 6, `L 形路徑應約 3 個錨點，實得 ${out.length}`);
});

test('rdpSimplify: t 單調且為原始子集合', () => {
  const pts = Array.from({ length: 50 }, (_, i) => ({ t: i * 0.1, x: Math.sin(i * 0.3) * 2, z: i * 0.3 }));
  const out = rdpSimplify(pts, { epsilonM: 0.1 });
  for (let i = 1; i < out.length; i++) assert.ok(out[i].t > out[i - 1].t);
  for (const p of out) assert.ok(pts.some(q => q.t === p.t && q.x === p.x), '錨點必須來自原始點');
});

// ── projectToPath（幾何/時序分離）────────────────────────────────────────────
import { projectToPath } from '../path.js';

test('projectToPath: 橫向蛇行貼回中心線、每點 t 與縱向速度保留', () => {
  const noisy = Array.from({ length: 80 }, (_, i) => ({
    t: i * 0.05, x: 0.05 * Math.sin(i * 1.7), z: i * 0.1 + 0.02 * Math.sin(i * 0.9),
  }));
  // 鏡射真實管線：RDP 的輸入一定是平滑後的資料（殘噪 1-3cm）；
  // 生噪 5cm 直餵會超過 ε=6cm，每個噪音峰都變錨點（見 rdpSimplify 註解）。
  const base = smoothPoints(noisy, { anchorEnd: false });
  const anchors = rdpSimplify(base, { epsilonM: 0.06 });
  assert.ok(anchors.length <= 5, `平滑後的直線應收成極少錨點，實得 ${anchors.length}`);
  const proj = projectToPath(base, anchors);
  assert.equal(proj.length, base.length, '點數不變');
  proj.forEach((p, i) => assert.equal(p.t, base[i].t, 't 逐點保留'));
  // 指標＝局部鋸齒度（點對相鄰兩點中點的偏差）：投影後應近乎共線。
  // 不用絕對 |x|——RDP 錨點含帶噪端點，中心線可微傾，但那不是「蛇行」。
  const zigzag = pts => {
    let s = 0;
    for (let i = 1; i < pts.length - 1; i++) {
      s += Math.abs(pts[i].x - (pts[i - 1].x + pts[i + 1].x) / 2);
    }
    return s / (pts.length - 2);
  };
  assert.ok(zigzag(proj) < zigzag(noisy) * 0.1,
    `鋸齒度應降 90%+：${zigzag(noisy).toFixed(4)} → ${zigzag(proj).toFixed(4)}`);
  // 縱向速度剖面保留：對應時段的前進距離差異 < 10%
  const dist = pts => pts.slice(40, 60).reduce((s, p, i, a) => i ? s + Math.hypot(p.x-a[i-1].x, p.z-a[i-1].z) : 0, 0);
  const d0 = dist(base), d1 = dist(proj);
  assert.ok(Math.abs(d1 - d0) / d0 < 0.15, `區段里程應相近：${d0.toFixed(3)} vs ${d1.toFixed(3)}`);
});

test('projectToPath: 沿曲線單調前進（不回頭黏段）', () => {
  const pts = [];
  for (let i = 0; i <= 30; i++) pts.push({ t: i * 0.1, x: 0.04 * ((i % 2) * 2 - 1), z: i * 0.3 });
  const proj = projectToPath(pts, rdpSimplify(pts, { epsilonM: 0.06 }));
  for (let i = 1; i < proj.length; i++) {
    assert.ok(proj[i].z >= proj[i - 1].z - 1e-6, `第 ${i} 點沿路徑倒退`);
  }
});

// ── refineAnchors（轉角細分）──────────────────────────────────────────────────
import { refineAnchors } from '../path.js';

test('refineAnchors: 大轉角被攤成多段小角度，直段不受影響', () => {
  // 90° 急彎（半徑 1.8m——RDP 在 ε=6cm 下弦間轉角 ~28°，必須靠細分攤平）+ 前後直段
  const pts = [];
  let t = 0;
  for (let i = 0; i < 20; i++) { pts.push({ t, x: 0, z: i * 0.5 }); t += 0.1; }
  for (let i = 1; i <= 30; i++) {
    const th = i * (Math.PI / 2) / 30;
    pts.push({ t, x: 1.8 * (1 - Math.cos(th)), z: 9.5 + 1.8 * Math.sin(th) });
    t += 0.1;
  }
  for (let i = 1; i < 20; i++) { pts.push({ t, x: 1.8 + i * 0.5, z: 11.3 }); t += 0.1; }
  const rough = rdpSimplify(pts, { epsilonM: 0.06 });
  const refined = refineAnchors(pts, rough, { maxTurnDeg: 12 });
  assert.ok(refined.length > rough.length, '彎道應被補入錨點');
  // 每個頂點角 ≤ 門檻（含餘裕）
  for (let k = 1; k < refined.length - 1; k++) {
    const h1 = Math.atan2(refined[k].x - refined[k-1].x, refined[k].z - refined[k-1].z);
    const h2 = Math.atan2(refined[k+1].x - refined[k].x, refined[k+1].z - refined[k].z);
    let d = Math.abs(h2 - h1); if (d > Math.PI) d = 2*Math.PI - d;
    assert.ok(d * 180/Math.PI <= 14, `頂點 ${k} 轉角 ${(d*180/Math.PI).toFixed(1)}° 超標`);
  }
  // 錨點仍是原始子集合
  for (const a of refined) assert.ok(pts.some(p => p.t === a.t));
});
