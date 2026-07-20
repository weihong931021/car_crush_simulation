const G = 9.80665;

export function velocityAtEnd(wps, speedKmh) {
  if (wps.length < 2) return { vx: 0, vz: 0 };
  const a = wps[wps.length - 2], b = wps[wps.length - 1];
  const dx = b[1] - a[1], dz = b[2] - a[2];
  const len = Math.hypot(dx, dz);
  const speedMs = speedKmh / 3.6;
  if (len < 1e-6) return { vx: 0, vz: speedMs };
  return { vx: dx / len * speedMs, vz: dz / len * speedMs };
}

export function headingOf(wps) {
  const a = wps[wps.length - 2], b = wps[wps.length - 1];
  return Math.atan2(b[1] - a[1], b[2] - a[2]);
}

// 摩擦滑行積分；omega0 非 0 時同步積分 heading（碰後自旋，Task 6 啟用）。
export function frictionSlide({ x0, z0, vx, vz, heading0, omega0, startFrame, endFrame,
                                mu, fps = 30, step = 3 }) {
  const dt = 1 / fps;
  const spin = omega0 !== 0 && heading0 != null;
  const result = [[startFrame, x0, z0, spin ? heading0 : null]];
  let cx = x0, cz = z0, cvx = vx, cvz = vz, h = heading0 ?? 0, w = omega0;
  const slideSteps = Math.max(1, Math.ceil(Math.hypot(vx, vz) / (mu * G * dt)));
  const wDecay = omega0 / slideSteps;
  for (let f = step; startFrame + f <= endFrame; f += step) {
    for (let s = 0; s < step; s++) {
      const spd = Math.hypot(cvx, cvz);
      if (spd >= 1e-3) {
        const decel = Math.min(mu * G * dt, spd);
        cvx -= (cvx / spd) * decel;
        cvz -= (cvz / spd) * decel;
        cx += cvx * dt;
        cz += cvz * dt;
      }
      if (w !== 0) {
        h += w * dt;
        w -= wDecay;
        if (w * omega0 < 0) w = 0;
      }
    }
    result.push([startFrame + f, cx, cz, spin ? h : null]);
  }
  return result;
}

const OMEGA_MAX = 6; // rad/s，視覺合理上限

// 已知簡化（刻意為之，非 bug，勿「修正」）：
// 1. 槓桿臂只取前向軸投影，忽略側向偏移 → 純正面對撞（J 平行前向軸）恆無自旋。
//    真實偏心正面撞會轉，此處為簡化。
// 2. ω 線性衰減至與滑行同時停止，是視覺選擇（保證車停時不再轉），
//    非輪胎偏航阻尼的物理模型（實際較接近指數衰減）。
//
// 衝量產生的初始角速度。
// heading 座標約定：h=atan2(dx,dz)，前向單位向量 f=(sin h, cos h)，
// three.js rotation.y 右手系（+Z→+X 為正）與此一致。
// contactOffset：接觸點在前向軸上的帶號投影（m）；由 applyCollision 計算後傳入。
export function spinFromImpulse(centerWp, heading, jx, jz, mass_kg, length_m, contactOffset) {
  const d = Math.max(-length_m / 2, Math.min(length_m / 2, contactOffset));
  const fx = Math.sin(heading), fz = Math.cos(heading);
  const rx = d * fx, rz = d * fz;              // 槓桿臂（車中心→接觸點）
  const torque = rz * jx - rx * jz;            // (r × J)_y
  const inertia = mass_kg * length_m * length_m / 12;
  const omega = torque / inertia;
  return Math.max(-OMEGA_MAX, Math.min(OMEGA_MAX, omega));
}

// 衝量碰撞：回傳兩車完整 waypoints（碰前 + 碰後滑行）。
export function applyCollision({ aPre, bPre, a, b, restitution, mu,
                                 animCollision, animEnd, fps = 30 }) {
  const aV = velocityAtEnd(aPre, a.speed_kmh);
  const bV = velocityAtEnd(bPre, b.speed_kmh);
  let avx = aV.vx, avz = aV.vz, bvx = bV.vx, bvz = bV.vz;
  const aL = aPre[aPre.length - 1], bL = bPre[bPre.length - 1];

  let nx = aL[1] - bL[1], nz = aL[2] - bL[2];
  const nLen = Math.hypot(nx, nz) || 1;
  nx /= nLen; nz /= nLen;

  const vrn = (avx - bvx) * nx + (avz - bvz) * nz;
  const j = vrn < 0 ? -(1 + restitution) * vrn / (1 / a.mass_kg + 1 / b.mass_kg) : 0;
  avx += j * nx / a.mass_kg; avz += j * nz / a.mass_kg;
  bvx -= j * nx / b.mass_kg; bvz -= j * nz / b.mass_kg;

  const contactX = (aL[1] + bL[1]) / 2, contactZ = (aL[2] + bL[2]) / 2;
  const aH = headingOf(aPre), bH = headingOf(bPre);
  const offsetAlong = (L, h) =>
    (contactX - L[1]) * Math.sin(h) + (contactZ - L[2]) * Math.cos(h);
  const aOmega = spinFromImpulse(aL, aH, j * nx, j * nz, a.mass_kg, a.length_m,
                                 offsetAlong(aL, aH));
  const bOmega = spinFromImpulse(bL, bH, -j * nx, -j * nz, b.mass_kg, b.length_m,
                                 offsetAlong(bL, bH));

  // step: 1 — 碰後動態變化快（減速+自旋衰減常在 5–10 幀內結束），沿用滑行滑段預設
  // step=3 會讓大半衰減落在單一取樣區間內看不見，heading 曲線失真。
  const slide = (L, vx, vz, h0, w0) => frictionSlide({ x0: L[1], z0: L[2], vx, vz,
    heading0: h0, omega0: w0, startFrame: animCollision, endFrame: animEnd, mu, fps, step: 1 });
  const aPost = slide(aL, avx, avz, aH, aOmega);
  const bPost = slide(bL, bvx, bvz, bH, bOmega);
  // aPost[0]/bPost[0] 帶碰撞當幀的真實 heading（含 spin 標記），取代 aPre/bPre 該幀原本的 null，
  // 避免交界幀 heading 遺失、interp 退回 chord 方向造成銜接處跳動。
  return { aWps: [...aPre.slice(0, -1), ...aPost], bWps: [...bPre.slice(0, -1), ...bPost] };
}
