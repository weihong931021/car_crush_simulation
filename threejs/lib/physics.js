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
  if (wps.length < 2) return 0;
  const a = wps[wps.length - 2], b = wps[wps.length - 1];
  return Math.atan2(b[1] - a[1], b[2] - a[2]);
}

// 摩擦滑行積分；omega0 非 0 時同步積分 heading（碰後自旋）。
// omega 隨線速度「同比例」衰減：omega(t) = omega0 · (speed(t) / speed0)，
// 讓自旋與平移同時停止（視覺選擇，非輪胎偏航阻尼的物理模型）。
// speed0 為 0（碰前即靜止）時無比例基準可言，直接視為不轉，避免除以零。
export function frictionSlide({ x0, z0, vx, vz, heading0, omega0, startFrame, endFrame,
                                mu, fps = 30, step = 3 }) {
  const dt = 1 / fps;
  const spin = omega0 !== 0 && heading0 != null;
  const speed0 = Math.hypot(vx, vz);
  const result = [[startFrame, x0, z0, spin ? heading0 : null]];
  let cx = x0, cz = z0, cvx = vx, cvz = vz, h = heading0 ?? 0;
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
      if (spin && speed0 > 1e-9) {
        const curSpeed = Math.hypot(cvx, cvz);
        h += omega0 * (curSpeed / speed0) * dt;
      }
    }
    result.push([startFrame + f, cx, cz, spin ? h : null]);
  }
  return result;
}

const OMEGA_MAX = 6; // rad/s，視覺合理上限；碰撞衝量算出的角速度理論上無上限，
                      // 超過此值代表「點衝量剛體」模型已超出合理範圍，clamp 前會 warn。

function clampOmega(torque, inertia, label) {
  const omega = torque / inertia;
  if (Math.abs(omega) > OMEGA_MAX) {
    console.warn(`physics: omega_${label}=${omega.toFixed(2)} rad/s 超過 OMEGA_MAX=${OMEGA_MAX}，已 clamp（模型超出合理範圍）`);
    return Math.max(-OMEGA_MAX, Math.min(OMEGA_MAX, omega));
  }
  return omega;
}

// 已知簡化（刻意為之，非 bug，勿「修正」）：舊版 applyCollision 內部沿用的槓桿臂只取
// 前向軸投影，忽略側向偏移 → 純正面對撞（J 平行前向軸）恆無自旋。collisionImpulse（下方）
// 已改用完整 2D 力臂修正此簡化；本函式僅供 applyCollision 相容舊行為之用，不對外匯出。
// heading 座標約定：h=atan2(dx,dz)，前向單位向量 f=(sin h, cos h)，
// three.js rotation.y 右手系（+Z→+X 為正）與此一致。
// contactOffset：接觸點在前向軸上的帶號投影（m）；由 applyCollision 計算後傳入。
function legacySpinFromImpulse(centerWp, heading, jx, jz, mass_kg, length_m, contactOffset) {
  const d = Math.max(-length_m / 2, Math.min(length_m / 2, contactOffset));
  const fx = Math.sin(heading), fz = Math.cos(heading);
  const rx = d * fx, rz = d * fz;              // 槓桿臂（車中心→接觸點）
  const torque = rz * jx - rx * jz;            // (r × J)_y
  const inertia = mass_kg * length_m * length_m / 12;
  return clampOmega(torque, inertia, 'legacy');
}

// 衝量碰撞（新介面）：真實接觸點 + 完整 2D 力臂，取代 legacySpinFromImpulse 的前向軸投影
// 簡化——偏心正面撞（衝量平行前向軸、接觸點偏離質心連線）在此可正確產生自旋。
// 只回傳碰撞瞬間的碰後速度/角速度；滑行積分仍交給 frictionSlide。
//
// a/b: {x, z, heading, vx, vz, mass_kg, length_m}；contact: {x,z}；normal: {nx,nz}（單位向量，指向 a→b）。
//
// v_rel·n 慣例：v_rel = v_a − v_b，n 指向 a→b。
// v_rel·n > 0 表示 a 正朝 b 逼近（closing，兩車距離持續縮小）→ 需施加衝量；
// v_rel·n <= 0 表示兩車已在分離或無相對趨近 → 回傳零衝量（否則會產生「吸附」而非「推開」的力）。
// （沿用本專案舊 applyCollision 已驗證的動量守恆符號慣例；舊版 normal 方向是 b→a，
//  這裡介面改指定 a→b，guard 的不等號方向隨之對調——已用動量守恆／自旋測試逐一驗證。）
export function collisionImpulse({ a, b, contact, normal, restitution }) {
  const { nx, nz } = normal;
  const vrelX = a.vx - b.vx, vrelZ = a.vz - b.vz;
  const vrn = vrelX * nx + vrelZ * nz;

  if (vrn <= 0) {
    return {
      aAfter: { vx: a.vx, vz: a.vz, omega: 0 },
      bAfter: { vx: b.vx, vz: b.vz, omega: 0 },
      j: 0,
    };
  }

  const j = -(1 + restitution) * vrn / (1 / a.mass_kg + 1 / b.mass_kg);
  const avx = a.vx + j * nx / a.mass_kg;
  const avz = a.vz + j * nz / a.mass_kg;
  const bvx = b.vx - j * nx / b.mass_kg;
  const bvz = b.vz - j * nz / b.mass_kg;

  // 力臂 r = 接觸點 − 車輛中心：完整 2D 向量，不投影到前向軸、不 clamp。
  const rax = contact.x - a.x, raz = contact.z - a.z;
  const rbx = contact.x - b.x, rbz = contact.z - b.z;

  // 施加在 a 上的衝量為 j·n；施加在 b 上為反作用力 −j·n。
  const JaX = j * nx, JaZ = j * nz;
  const JbX = -JaX, JbZ = -JaZ;

  const Ia = a.mass_kg * a.length_m * a.length_m / 12;
  const Ib = b.mass_kg * b.length_m * b.length_m / 12;

  // (r × J)_y = r_z·J_x − r_x·J_z（右手系）；a、b 受力相反，力臂各自不同，故兩者 τ 未必等大反向，
  // 但同一接觸點、相反的 J 通常仍使兩車自旋方向相反（作用力與反作用力）。
  const omegaA = clampOmega(raz * JaX - rax * JaZ, Ia, 'a');
  const omegaB = clampOmega(rbz * JbX - rbx * JbZ, Ib, 'b');

  return {
    aAfter: { vx: avx, vz: avz, omega: omegaA },
    bAfter: { vx: bvx, vz: bvz, omega: omegaB },
    j,
  };
}

// 衝量碰撞：回傳兩車完整 waypoints（碰前 + 碰後滑行）。
// 保留供 main.js 相容（Task 7 前不切換）；內部沿用舊接觸點/力臂簡化（見 legacySpinFromImpulse）。
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
  const aOmega = legacySpinFromImpulse(aL, aH, j * nx, j * nz, a.mass_kg, a.length_m,
                                 offsetAlong(aL, aH));
  const bOmega = legacySpinFromImpulse(bL, bH, -j * nx, -j * nz, b.mass_kg, b.length_m,
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
