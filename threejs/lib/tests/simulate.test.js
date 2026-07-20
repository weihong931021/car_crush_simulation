import test from 'node:test';
import assert from 'node:assert/strict';
import { simulate } from '../simulate.js';
import { buildPath, speedProfile } from '../path.js';

function veh(points, length_m, width_m, mass_kg) {
  return { path: buildPath(points), profile: speedProfile(points), length_m, width_m, mass_kg };
}
// 汽車沿 +Z 穿越原點；機車沿 +X 穿越原點；等速 10 m/s，同時抵達 → 必撞
const carPts  = Array.from({ length: 41 }, (_, i) => ({ x: 0, z: -20 + i, t: i * 0.1 }));
const motoPts = Array.from({ length: 41 }, (_, i) => ({ x: -20 + i, z: 0, t: i * 0.1 }));

test('等速同時抵達 → 偵測到碰撞，撞擊點在路口附近', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 1, kB: 1 });
  assert.equal(r.collided, true);
  assert.ok(r.impactTime > 0 && r.impactTime < 12);
  assert.ok(Math.hypot(r.contact.x, r.contact.z) < 4, `接觸點應在路口附近，實得 ${JSON.stringify(r.contact)}`);
  assert.equal(r.minGap, 0);
});

test('汽車大幅放慢 → 不再碰撞，回報正的最小間距', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 0.35, kB: 1 });
  assert.equal(r.collided, false);
  assert.equal(r.impactTime, null);
  assert.ok(r.minGap > 0.5, `應明顯錯開，實得 ${r.minGap}`);
  assert.ok(r.minGapTime > 0);
});

test('未碰撞時兩車都走完各自路徑', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 0.35, kB: 1 });
  const last = r.tracks[1].samples.at(-1);
  assert.ok(last.x > 15, `機車應走到路徑末端，實得 x=${last.x}`);
});

test('碰撞後兩車脫離原路徑（自由體）', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 1, kB: 1 });
  const moto = r.tracks[1].samples.filter(s => s.t > r.impactTime + 0.3);
  assert.ok(moto.some(s => Math.abs(s.z) > 0.3), '機車碰後應被推離原本 z≈0 的直線');
});

test('擦邊接觸造成的速度變化應明顯小於正面T骨（迭代解算按穿透程度按比例，不是全有全無）', () => {
  // 機車路徑往 +z 平移 1.0m：只擦到汽車車頭最前緣的角落（穿透淺），而非直接撞穿車身中段
  // （預設 fixture、z=0，等同正面 T 骨）。兩者用同一組車輛/質量/速度，唯一差異是幾何。
  const grazeMotoPts = Array.from({ length: 41 }, (_, i) => ({ x: -20 + i, z: 1.0, t: i * 0.1 }));
  const vehicles = (motoPts) => [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)];

  const broadside = simulate({ vehicles: vehicles(motoPts), kA: 1, kB: 1 });
  const graze = simulate({ vehicles: vehicles(grazeMotoPts), kA: 1, kB: 1 });
  assert.equal(broadside.collided, true);
  assert.equal(graze.collided, true, '擦邊也應偵測到碰撞（只是穿透淺）');

  // 用撞擊後一小段固定時窗（0.3s）量測機車速率變化，避開之後摩擦滑行把兩者都磨到停止
  // 掩蓋掉碰撞本身造成的差異。
  function speedChangeOf(r) {
    const moto = r.tracks[1].samples;
    const idx = moto.findIndex(s => Math.abs(s.t - r.impactTime) < 1e-9);
    const pre1 = moto[Math.max(0, idx - 1)], pre2 = moto[idx];
    const preSpeed = Math.hypot(pre2.x - pre1.x, pre2.z - pre1.z) / (pre2.t - pre1.t);
    const targetT = r.impactTime + 0.3;
    let wIdx = moto.findIndex(s => s.t >= targetT);
    if (wIdx < 1) wIdx = moto.length - 1;
    const w1 = moto[wIdx - 1], w2 = moto[wIdx];
    const postSpeed = Math.hypot(w2.x - w1.x, w2.z - w1.z) / (w2.t - w1.t);
    return Math.abs(postSpeed - preSpeed);
  }

  const dvBroadside = speedChangeOf(broadside);
  const dvGraze = speedChangeOf(graze);
  assert.ok(dvGraze < dvBroadside * 0.5,
    `擦邊的速度變化應明顯小於正面T骨，實得 graze=${dvGraze.toFixed(3)} broadside=${dvBroadside.toFixed(3)}`);
});

test('輸出樣本時間單調遞增且無 NaN', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 1, kB: 1 });
  for (const trk of r.tracks) {
    for (let i = 1; i < trk.samples.length; i++) assert.ok(trk.samples[i].t > trk.samples[i-1].t);
    assert.ok(trk.samples.every(s => Number.isFinite(s.x) && Number.isFinite(s.z) && Number.isFinite(s.heading)));
  }
});
