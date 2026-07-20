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

// 摩擦滑行的單一時間步（純函數）：套用一步 mu*G 減速，並依「與線速度同比例」衰減 heading
// 的自旋速率（見 frictionSlide 的說明）。抽出成獨立函式的原因：simulate.js 的碰後迭代接觸
// 解算（Task 5 Part A）需要在滑行途中插入額外衝量，無法沿用 frictionSlide 一次吐出整段未來
// 軌跡的介面（它不回傳逐步的 vx/vz），只能逐步呼叫；抽出這個純函數讓 frictionSlide（整段滑行）
// 與 simulate.js（逐步滑行＋期間可能重新解算接觸）共用同一份衰減數學，不必分岔成兩份實作。
//
// omega0/speed0：這段「滑行episode」的參考基準（通常是上一次衝量剛結束時的角速度／線速度），
// 全程固定不變；每步用「目前線速度／speed0」的比例去乘 omega0，得到這一步的『目前角速度』
// （omegaNow），讓自旋與平移同時衰減到 0（視覺選擇，非輪胎偏航阻尼的物理模型）。
// speed0 為 0（滑行一開始就是靜止）時無比例基準可言，omegaNow 直接視為 0，避免除以零。
export function frictionStep({ x, z, vx, vz, heading, omega0, speed0, dt, mu }) {
  let cx = x, cz = z, cvx = vx, cvz = vz;
  const spd = Math.hypot(cvx, cvz);
  if (spd >= 1e-3) {
    const decel = Math.min(mu * G * dt, spd);
    cvx -= (cvx / spd) * decel;
    cvz -= (cvz / spd) * decel;
    cx += cvx * dt;
    cz += cvz * dt;
  }
  let omegaNow = 0;
  let heading2 = heading;
  if (omega0 !== 0 && speed0 > 1e-9) {
    const curSpeed = Math.hypot(cvx, cvz);
    omegaNow = omega0 * (curSpeed / speed0);
    heading2 = heading + omegaNow * dt;
  }
  return { x: cx, z: cz, vx: cvx, vz: cvz, heading: heading2, omegaNow };
}

// 摩擦滑行積分；omega0 非 0 時同步積分 heading（碰後自旋）。內部逐步呼叫 frictionStep（見上），
// 純粹是把它包成「一次要一整段」的介面，行為與抽出前完全相同。
export function frictionSlide({ x0, z0, vx, vz, heading0, omega0, startFrame, endFrame,
                                mu, fps = 30, step = 3 }) {
  const dt = 1 / fps;
  const spin = omega0 !== 0 && heading0 != null;
  const speed0 = Math.hypot(vx, vz);
  const result = [[startFrame, x0, z0, spin ? heading0 : null]];
  let cx = x0, cz = z0, cvx = vx, cvz = vz, h = heading0 ?? 0;
  for (let f = step; startFrame + f <= endFrame; f += step) {
    for (let s = 0; s < step; s++) {
      const next = frictionStep({ x: cx, z: cz, vx: cvx, vz: cvz, heading: h, omega0, speed0, dt, mu });
      cx = next.x; cz = next.z; cvx = next.vx; cvz = next.vz;
      if (spin) h = next.heading;
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
// a/b: {x, z, heading, vx, vz, mass_kg, length_m, omega?}；omega 為碰前既有角速度（首次碰撞恆為
// 0；simulate.js 迭代重新解算同一接觸時可能非 0，省略時預設 0，向後相容舊呼叫）。
// contact: {x,z}；normal: {nx,nz}（單位向量，指向 a→b）；muContact：接觸面（不是路面）摩擦係數，
// 預設 0.5——決定切向衝量能吸收多少偏心衝量原本會全部轉成自旋的量，與路面滑行摩擦係數（frictionSlide
// 的 mu，本專案取 0.7）是兩回事，不要混用。
//
// v_rel·n 慣例：v_rel = v_a − v_b，n 指向 a→b。
// v_rel·n > 0 表示 a 正朝 b 逼近（closing，兩車距離持續縮小）→ 需施加衝量；
// v_rel·n <= 0 表示兩車已在分離或無相對趨近 → 回傳零衝量、原樣保留兩車既有速度／角速度
// （早期版本這裡誤把 omega 重置為 0——只呼叫一次、omega 恆為 0 的舊介面下看不出差異；
//  simulate.js 迭代重新解算接觸時可能在角速度非 0 時呼叫到這個分支，若重置成 0 會憑空吃掉
//  既有自旋，已修正為原樣回傳）。
// （沿用本專案舊 applyCollision 已驗證的動量守恆符號慣例；舊版 normal 方向是 b→a，
//  這裡介面改指定 a→b，guard 的不等號方向隨之對調——已用動量守恆／自旋測試逐一驗證。）
export function collisionImpulse({ a, b, contact, normal, restitution, muContact = 0.5 }) {
  const { nx, nz } = normal;
  const omegaA0 = a.omega ?? 0, omegaB0 = b.omega ?? 0;
  const vrelX = a.vx - b.vx, vrelZ = a.vz - b.vz;
  const vrn = vrelX * nx + vrelZ * nz;

  if (vrn <= 0) {
    return {
      aAfter: { vx: a.vx, vz: a.vz, omega: omegaA0 },
      bAfter: { vx: b.vx, vz: b.vz, omega: omegaB0 },
      j: 0,
      jt: 0,
    };
  }

  const j = -(1 + restitution) * vrn / (1 / a.mass_kg + 1 / b.mass_kg);

  // 力臂 r = 接觸點 − 車輛中心：完整 2D 向量，不投影到前向軸、不 clamp。
  const rax = contact.x - a.x, raz = contact.z - a.z;
  const rbx = contact.x - b.x, rbz = contact.z - b.z;
  const Ia = a.mass_kg * a.length_m * a.length_m / 12;
  const Ib = b.mass_kg * b.length_m * b.length_m / 12;

  // --- 切向摩擦衝量（先算「只有法向衝量」的中間狀態，再用這個中間狀態算切向滑動速度）---
  // 為什麼要用「法向衝量後」而非「碰前」的狀態算切向滑動：偏心正撞在碰前兩車速度往往完全
  // 平行於法向（無切向分量、碰前也還沒有自旋），此時切向滑動速度恆為 0，摩擦無從施力；
  // 真正的切向滑動是法向衝量本身造成的偏心自旋「憑空產生」的——接觸點因為這個新自旋開始
  // 相對滑動，摩擦才有東西可以抓。這也是本函式修正前「全部偏心衝量都轉成自旋、完全沒有東西
  // 抵抗」的根源。中間態的 omega 刻意不 clamp（只用來算切向滑動速度，不是最終回傳值）。
  const JaXn = j * nx, JaZn = j * nz;
  const avx1 = a.vx + JaXn / a.mass_kg, avz1 = a.vz + JaZn / a.mass_kg;
  const bvx1 = b.vx - JaXn / b.mass_kg, bvz1 = b.vz - JaZn / b.mass_kg;
  const omegaA1raw = (raz * JaXn - rax * JaZn) / Ia;
  const omegaB1raw = (rbz * (-JaXn) - rbx * (-JaZn)) / Ib;

  const tx = nz, tz = -nx; // t 為 n 逆時針轉 90 度；下面 jt 的正負號會自動抓對抵抗滑動的方向。

  // 接觸點速度 = 線速度 + ω×r。2D 形式：(vx + ω·r_z, vz − ω·r_x)——正負號經過與本檔案既有、
  // 已由動量守恆／自旋測試驗證過的 torque 慣例（τ = r_z·F_x − r_x·F_z，omega = τ/I，未取負）
  // 反推校對過：若照「vx − ω·r_z, vz + ω·r_x」代入，算出的切向有效質量 1/(1/ma+1/mb+D²/Ia+D²/Ib)
  // 會變成負值（物理上不合理，代表力臂方向反了），且對本檔案 Test 3 的偏心撞數值代入後，摩擦
  // 衝量會讓機車 |ω| 從 21.3 rad/s 惡化到 39 rad/s（方向錯誤，摩擦不該讓滑動變大）；改成這裡
  // 的正負號後兩者都恢復正常（有效質量為正、|ω| 降到 5.79 rad/s，見 Task 5 報告的健檢數字）。
  const vcAx = avx1 + omegaA1raw * raz, vcAz = avz1 - omegaA1raw * rax;
  const vcBx = bvx1 + omegaB1raw * rbz, vcBz = bvz1 - omegaB1raw * rbx;
  const vt = (vcAx - vcBx) * tx + (vcAz - vcBz) * tz;

  const mEff = 1 / (1 / a.mass_kg + 1 / b.mass_kg);
  const jtMax = muContact * Math.abs(j);
  const jt = Math.max(-jtMax, Math.min(jtMax, -vt * mEff));

  // 施加在 a 上的總衝量為 (j·n + jt·t)；施加在 b 上為反作用力，方向相反。
  const JaX = JaXn + jt * tx, JaZ = JaZn + jt * tz;
  const JbX = -JaX, JbZ = -JaZ;

  const avx = a.vx + JaX / a.mass_kg;
  const avz = a.vz + JaZ / a.mass_kg;
  const bvx = b.vx - JaX / b.mass_kg;
  const bvz = b.vz - JaZ / b.mass_kg;

  // (r × J)_y = r_z·J_x − r_x·J_z（右手系）；a、b 受力相反，力臂各自不同，故兩者 τ 未必等大反向，
  // 但同一接觸點、相反的 J 通常仍使兩車自旋方向相反（作用力與反作用力）。J 已含法向+切向合力，
  // 切向摩擦對自旋的貢獻在這裡自動一併算入，不需要另外疊加。
  const omegaA = clampOmega(raz * JaX - rax * JaZ, Ia, 'a');
  const omegaB = clampOmega(rbz * JbX - rbx * JbZ, Ib, 'b');

  return {
    aAfter: { vx: avx, vz: avz, omega: omegaA },
    bAfter: { vx: bvx, vz: bvz, omega: omegaB },
    j,
    jt,
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
