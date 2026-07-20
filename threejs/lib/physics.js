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

  const slide = (L, vx, vz) => frictionSlide({ x0: L[1], z0: L[2], vx, vz,
    heading0: null, omega0: 0, startFrame: animCollision, endFrame: animEnd, mu, fps });
  const aPost = slide(aL, avx, avz);
  const bPost = slide(bL, bvx, bvz);
  return { aWps: [...aPre, ...aPost.slice(1)], bWps: [...bPre, ...bPost.slice(1)] };
}
