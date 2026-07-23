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

// ── 出現時間（startT）─────────────────────────────────────────────────────────
test('startT: 晚出現的車不會提早出發到衝突點等撞', () => {
  // 機車 6 秒後才出現；若忽略 startT，它 t=0 就出發、2 秒內走完路徑並停在路口，
  // 汽車撞上的是「提早出發後停著等」的幽靈；正確行為是它 6 秒後才進場。
  const moto = veh(motoPts, 1.85, 0.7, 200);
  moto.startT = 6.0;
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), moto], kA: 1, kB: 1 });
  // 機車樣本必須從 startT 才開始
  assert.ok(Math.abs(r.tracks[1].samples[0].t - 6.0) < 1e-9);
  // t < 6 期間不得有機車樣本
  assert.ok(r.tracks[1].samples.every(s => s.t >= 6.0 - 1e-9));
});

test('startT: 出現前不參與碰撞偵測與最近間距', () => {
  // 汽車路徑 4 秒內通過原點；機車 6 秒後才出現在原點附近的路徑上 → 不可能碰撞，
  // 且 minGapTime 不得早於機車出現時刻。
  const fastCar = Array.from({ length: 41 }, (_, i) => ({ x: 0, z: -20 + i, t: i * 0.1 }));
  const lateMoto = veh(motoPts, 1.85, 0.7, 200);
  lateMoto.startT = 6.0;
  const r = simulate({ vehicles: [veh(fastCar, 4.69, 1.85, 1500), lateMoto], kA: 1, kB: 1 });
  assert.equal(r.collided, false);
  assert.ok(r.minGapTime >= 6.0 - 1e-9, `minGapTime=${r.minGapTime} 不得早於出現時刻`);
});

test('startT: 兩車皆從 0 開始時行為與未指定完全相同', () => {
  const a = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)], kA: 1, kB: 1 });
  const withZero = [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)];
  withZero[0].startT = 0; withZero[1].startT = 0;
  const b = simulate({ vehicles: withZero, kA: 1, kB: 1 });
  assert.equal(a.collided, b.collided);
  assert.equal(a.impactTime, b.impactTime);
});

// ── 轉向率上限（車身朝向不「飄」）───────────────────────────────────────────
test('yaw limit: 蠕行時輸出 heading 的變化率被限制', () => {
  // 0.3 m/s 蠕行 + 高頻側向噪音：路徑切線劇烈擺動，但車身朝向必須平穩
  const creep = Array.from({ length: 120 }, (_, i) => ({
    t: i * 0.05, x: 0.05 * ((i % 2) * 2 - 1), z: i * 0.015,
  }));
  const far = Array.from({ length: 40 }, (_, i) => ({ x: 200, z: 200 + i, t: i * 0.1 }));
  const r = simulate({ vehicles: [veh(creep, 4.69, 1.85, 1500), veh(far, 1.85, 0.7, 200)], kA: 1, kB: 1 });
  const s = r.tracks[0].samples;
  for (let i = 1; i < s.length; i++) {
    const dt = s[i].t - s[i - 1].t;
    let d = Math.abs(s[i].heading - s[i - 1].heading);
    if (d > Math.PI) d = 2 * Math.PI - d;
    // 不變量本體：yaw rate ≤ 0.6·v + 0.15（v 用該步實際位移速度，含 40% 裕度容納
    // 剖面速度與位移速度的積分差）——蠕行時遠小於切線噪音要求的擺頭速率
    const v = Math.hypot(s[i].x - s[i - 1].x, s[i].z - s[i - 1].z) / dt;
    assert.ok(d <= (0.6 * v * 1.4 + 0.15) * dt + 1e-6,
      `第 ${i} 步 yaw ${(d / dt).toFixed(3)} rad/s 超過 v=${v.toFixed(2)} 的上限`);
  }
});

test('yaw limit: 正常速度轉彎完全跟得上切線', () => {
  // 半徑 20m 圓弧、5 m/s → 切線角速度 0.25 rad/s，遠低於上限 3.15 rad/s
  const arc = Array.from({ length: 63 }, (_, i) => {
    const th = i * 0.025; // 每步 0.5m / r=20
    return { t: i * 0.1, x: 20 * Math.sin(th), z: 20 * (1 - Math.cos(th)) };
  });
  const far = Array.from({ length: 40 }, (_, i) => ({ x: 300, z: 300 + i, t: i * 0.1 }));
  const r = simulate({ vehicles: [veh(arc, 4.69, 1.85, 1500), veh(far, 1.85, 0.7, 200)], kA: 1, kB: 1 });
  const s = r.tracks[0].samples;
  const mid = s[Math.floor(s.length / 2)];
  const path = buildPath(arc.map(p => ({ ...p })));
  // 對照：同時刻的路徑切線（用鄰近樣本位置差近似）
  const j = s.indexOf(mid);
  const tangent = Math.atan2(s[j + 1].x - s[j - 1].x, s[j + 1].z - s[j - 1].z);
  let d = Math.abs(mid.heading - tangent);
  if (d > Math.PI) d = 2 * Math.PI - d;
  assert.ok(d < 0.06, `轉彎中車身朝向應貼合行進方向，偏差 ${(d * 180 / Math.PI).toFixed(2)}°`);
});
