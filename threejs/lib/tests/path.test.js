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
