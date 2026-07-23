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
