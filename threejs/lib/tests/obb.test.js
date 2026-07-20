import test from 'node:test';
import assert from 'node:assert/strict';
import { makeOBB, overlap, gap, corners } from '../obb.js';

const car = (x, z, h) => makeOBB(x, z, h, 4.69, 1.85);

test('corners: 未旋轉時四角正確', () => {
  const c = corners(makeOBB(0, 0, 0, 4, 2));
  const xs = c.map(p => +p.x.toFixed(6)), zs = c.map(p => +p.z.toFixed(6));
  assert.deepEqual([...new Set(xs)].sort((a,b)=>a-b), [-1, 1]);
  assert.deepEqual([...new Set(zs)].sort((a,b)=>a-b), [-2, 2]);
});

test('overlap: 明顯分離回 null，gap 為正且合理', () => {
  const a = car(0, 0, 0), b = car(10, 0, 0);
  assert.equal(overlap(a, b), null);
  assert.ok(Math.abs(gap(a, b) - (10 - 1.85)) < 1e-6, '沿 x 分離：中心距 − 兩個半寬');
});

test('overlap: 同位置必重疊', () => {
  const r = overlap(car(0, 0, 0), car(0, 0, 0));
  assert.ok(r && r.depth > 0);
  assert.equal(gap(car(0,0,0), car(0,0,0)), 0);
});

test('overlap: 沿 x 輕微重疊 → 法向沿 x、深度正確', () => {
  const a = car(0, 0, 0), b = car(1.8, 0, 0);   // 兩個半寬和 = 1.85
  const r = overlap(a, b);
  assert.ok(r, '應重疊');
  assert.ok(Math.abs(Math.abs(r.nx) - 1) < 1e-6 && Math.abs(r.nz) < 1e-6, '法向沿 x');
  assert.ok(Math.abs(r.depth - 0.05) < 1e-6, `深度應 0.05，實得 ${r.depth}`);
});

test('overlap: 旋轉 90 度的 T 字相接', () => {
  const a = car(0, 0, 0);                 // 沿 z 長
  const b = car(0, 2.5, Math.PI / 2);     // 沿 x 長，擺在前方
  assert.ok(overlap(a, b), 'T 骨碰撞應偵測到');
  assert.equal(gap(a, b), 0);
});

test('gap: 對角分離的最短距離為角對角', () => {
  const a = makeOBB(0, 0, 0, 2, 2), b = makeOBB(4, 4, 0, 2, 2);
  // a 角 (1,1)、b 角 (3,3) → 距離 = sqrt(8)
  assert.ok(Math.abs(gap(a, b) - Math.sqrt(8)) < 1e-6);
});

test('overlap 法向方向：由 a 指向 b', () => {
  const r = overlap(car(0, 0, 0), car(1.8, 0, 0));
  assert.ok(r.nx > 0, 'b 在 a 的 +x 側，法向 x 分量應為正');
});
