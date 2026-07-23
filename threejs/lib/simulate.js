// 前向模擬主迴圈：兩車各自沿路徑（可調速率係數 k）推進，逐步偵測 OBB 重疊；
// 一旦偵測到碰撞，兩車脫離路徑改為自由體，套用衝量後沿用 physics.js 既有的摩擦滑行／
// 自旋衰減模型滑停。取代「重播錄好的軌跡、在寫死的幀數放煙火」——改速度可以真的讓
// 碰撞「不發生」，這是本次重構的核心能力。
//
// 座標慣例（不可更動，見 path.js/obb.js）：heading = atan2(dx, dz)，
// 前向單位向量 = (sin h, cos h)。

import { sampleAt, advance, speedAt } from './path.js';
import { makeOBB, overlap, gap } from './obb.js';
import { collisionImpulse, frictionStep } from './physics.js';

// simulate() 介面（見 brief）不收 mu/restitution 參數，沿用本專案既有碰撞模型的預設值
// （physics.test.js 的 applyCollision 呼叫、Task 4 報告）：restitution=0.15（正撞，
// 大部分動能轉形變熱）、mu=0.7（乾燥路面）。之後若要開放調整，這裡是唯一要改的地方。
const RESTITUTION = 0.15;
const MU = 0.7;

const STOP_SPEED_MPS = 0.05; // 自由體階段視為「已停止」的速度門檻
const MIN_POST_IMPACT_FRAMES = 2; // 碰撞後至少多輸出幾幀，讓呼叫端能畫出碰後效果
const BISECT_DT_DIVISOR = 16; // 撞擊時刻二分細化至 dt/16 以內
const MAX_REAPPLY = 40; // 同一接觸 episode 最多重新套用衝量幾次（約 2/3 秒 @60fps），
                         // 防止穿透過深或參數不穩定時無止盡反覆解算（見 runFreeBodyLoop）
const POSITION_CORRECTION = 0.8; // 每次重新套用衝量後，沿法向修正掉多少比例的穿透深度
                                  // （Baumgarte 風格），避免同一次穿透連續好幾步一直判定
                                  // 「仍重疊且仍逼近」而反覆套用衝量（抖動）

function obbAt(veh, x, z, heading) {
  return makeOBB(x, z, heading, veh.length_m, veh.width_m);
}

// 該車在弧長 s、heading h 處的瞬時速度向量（大小取自速度剖面，方向取路徑切線）。
function velocityAt(veh, s, heading, k) {
  const v = speedAt(veh.profile, s, k);
  return { vx: v * Math.sin(heading), vz: v * Math.cos(heading) };
}

// 接觸點速度 = 線速度 + ω×r，2D 形式 (vx+ω·rz, vz−ω·rx)。正負號與 physics.js 的
// collisionImpulse 切向摩擦公式用同一組（已對照本專案既有、已驗證的 torque 慣例
// τ=rz·Fx−rx·Fz、omega=τ/I（未取負）反推校正過，見 physics.js 內對應註解與 Task 5
// 報告的推導）。
function contactVelocity(vx, vz, omega, rx, rz) {
  return { vcx: vx + omega * rz, vcz: vz - omega * rx };
}

// t0（已知無重疊，兩車此時弧長為 sA0/sB0）、t1（已知重疊）之間二分至 dt/16 以內，
// 回傳 bracket 內較晚那一端（仍重疊）的完整狀態，視為撞擊時刻。
// 兩車此時都還在路徑上，任意時刻的狀態可由 advance(s0, t-t0) 這個純函數直接算出，
// 不需要真的逐步微推進即可二分查找。
function bisectImpact(vehA, kA, sA0, vehB, kB, sB0, t0, t1, dt, startTA, startTB) {
  function stateAt(tt) {
    // 車輛在自己的 startT 之前不會移動——bracket 可能跨過其中一台的出現時刻，
    // 前進時間要從 max(t0, startT) 起算（sA0/sB0 即該時刻的位置）。
    const dtA = Math.max(0, tt - Math.max(t0, startTA));
    const dtB = Math.max(0, tt - Math.max(t0, startTB));
    const sA = advance(vehA.path, vehA.profile, sA0, dtA, kA);
    const sB = advance(vehB.path, vehB.profile, sB0, dtB, kB);
    const pA = sampleAt(vehA.path, sA);
    const pB = sampleAt(vehB.path, sB);
    const ov = overlap(obbAt(vehA, pA.x, pA.z, pA.heading), obbAt(vehB, pB.x, pB.z, pB.heading));
    return { sA, sB, pA, pB, ov };
  }

  let lo = t0, hi = t1;
  let hiState = stateAt(hi); // 呼叫端保證 t1 時重疊
  while (hi - lo > dt / BISECT_DT_DIVISOR) {
    const mid = (lo + hi) / 2;
    const midState = stateAt(mid);
    if (midState.ov) {
      hi = mid;
      hiState = midState;
    } else {
      lo = mid;
    }
  }
  return { t: hi, ...hiState };
}

// 碰撞後自由體：逐步（每個 dt）套用摩擦減速＋自旋比例衰減（frictionStep，沿用 physics.js
// 唯一一份摩擦數學，不在這裡重寫），並在每一步結束時重新檢查 overlap()——只要兩車仍重疊、
// 且接觸點的相對速度仍在逼近（見 contactVelocity），就再套用一次 collisionImpulse，更新
// 雙方速度／角速度，並把這次衝量後的速度／角速度設成新的摩擦衰減參考基準（每次衝量視為
// 重新開始一段滑行）。直到分離或不再逼近才停止套用衝量（但摩擦滑行照常繼續積分）。
//
// 這是「碰撞持續發展」而非「單次衝量」的正確模型：第一次偵測到的重疊往往只是輕輕擦到
// （衝量很小、幾乎沒有動能轉移），真正的撞擊力道是接下來幾步穿透逐漸加深時才套用上去的
// ——單一衝量模型會把整場碰撞「凍結」在那個擦到的瞬間，漏掉後續真正的正撞。
//
// state: {x,z,heading,vx,vz,omega,speed0,omega0}；speed0/omega0 是目前這段滑行的固定
// 參考基準（frictionStep 用它們算「目前」的比例衰減 omega），只在套用新衝量時重置。
function runFreeBodyLoop({ vehA, vehB, dt, maxTime, impactTime, stateA, stateB, samplesA, samplesB }) {
  let t = impactTime;
  let totalReapplyCount = 0;
  let contactExhausted = false; // MAX_REAPPLY 保險絲跳了之後，這段接觸不再重新套用衝量
  let stepsPushed = 0;

  while (t < maxTime) {
    const dtStep = Math.min(dt, maxTime - t);
    if (dtStep <= 1e-12) break;

    // 1) 摩擦減速 + 自旋比例衰減（各自沿用「上一次衝量」設下的參考基準）
    const nextA = frictionStep({ x: stateA.x, z: stateA.z, vx: stateA.vx, vz: stateA.vz,
      heading: stateA.heading, omega0: stateA.omega0, speed0: stateA.speed0, dt: dtStep, mu: MU });
    const nextB = frictionStep({ x: stateB.x, z: stateB.z, vx: stateB.vx, vz: stateB.vz,
      heading: stateB.heading, omega0: stateB.omega0, speed0: stateB.speed0, dt: dtStep, mu: MU });

    let xA = nextA.x, zA = nextA.z, headingA = nextA.heading;
    let vxA = nextA.vx, vzA = nextA.vz, omegaA = nextA.omegaNow;
    let xB = nextB.x, zB = nextB.z, headingB = nextB.heading;
    let vxB = nextB.vx, vzB = nextB.vz, omegaB = nextB.omegaNow;
    let speed0A = stateA.speed0, omega0A = stateA.omega0;
    let speed0B = stateB.speed0, omega0B = stateB.omega0;

    // 2) 這一步結束時的位置若仍重疊，檢查接觸點相對速度是否仍在逼近，是的話重新套用衝量
    if (!contactExhausted) {
      const ov = overlap(obbAt(vehA, xA, zA, headingA), obbAt(vehB, xB, zB, headingB));
      if (ov) {
        const rax = ov.contactX - xA, raz = ov.contactZ - zA;
        const rbx = ov.contactX - xB, rbz = ov.contactZ - zB;
        const cA = contactVelocity(vxA, vzA, omegaA, rax, raz);
        const cB = contactVelocity(vxB, vzB, omegaB, rbx, rbz);
        const vrn = (cA.vcx - cB.vcx) * ov.nx + (cA.vcz - cB.vcz) * ov.nz;

        if (vrn > 0) {
          const res = collisionImpulse({
            a: { x: xA, z: zA, heading: headingA, vx: vxA, vz: vzA, omega: omegaA,
                 mass_kg: vehA.mass_kg, length_m: vehA.length_m },
            b: { x: xB, z: zB, heading: headingB, vx: vxB, vz: vzB, omega: omegaB,
                 mass_kg: vehB.mass_kg, length_m: vehB.length_m },
            contact: { x: ov.contactX, z: ov.contactZ },
            normal: { nx: ov.nx, nz: ov.nz },
            restitution: RESTITUTION,
          });

          if (res.j !== 0 || res.jt !== 0) {
            vxA = res.aAfter.vx; vzA = res.aAfter.vz; omegaA = res.aAfter.omega;
            vxB = res.bAfter.vx; vzB = res.bAfter.vz; omegaB = res.bAfter.omega;
            speed0A = Math.hypot(vxA, vzA); omega0A = omegaA;
            speed0B = Math.hypot(vxB, vzB); omega0B = omegaB;

            // 位置修正：沿法向把兩車推開一部分穿透深度（依質量反比分配），避免同一次
            // 穿透連續好幾步一直判定「仍重疊且仍逼近」而反覆套用衝量（抖動）。
            const invA = 1 / vehA.mass_kg, invB = 1 / vehB.mass_kg;
            const invSum = invA + invB;
            if (ov.depth > 0 && invSum > 0) {
              const corr = (ov.depth * POSITION_CORRECTION) / invSum;
              xA -= ov.nx * corr * invA; zA -= ov.nz * corr * invA;
              xB += ov.nx * corr * invB; zB += ov.nz * corr * invB;
            }

            totalReapplyCount++;
            if (totalReapplyCount === MAX_REAPPLY) {
              contactExhausted = true;
              console.warn(`simulate: 同一接觸重新套用衝量已達上限 ${MAX_REAPPLY} 次，` +
                `之後這段接觸不再重新解算（可能是穿透過深或參數不穩定造成的抖動），` +
                `僅停止再套用衝量，摩擦滑行照常繼續積分。`);
            }
          }
        }
      }
    }

    stateA = { x: xA, z: zA, heading: headingA, vx: vxA, vz: vzA, omega: omegaA,
               speed0: speed0A, omega0: omega0A };
    stateB = { x: xB, z: zB, heading: headingB, vx: vxB, vz: vzB, omega: omegaB,
               speed0: speed0B, omega0: omega0B };

    t += dtStep;
    stepsPushed++;
    samplesA.push({ t, x: stateA.x, z: stateA.z, heading: stateA.heading });
    samplesB.push({ t, x: stateB.x, z: stateB.z, heading: stateB.heading });

    if (stepsPushed >= MIN_POST_IMPACT_FRAMES) {
      const speedA = Math.hypot(stateA.vx, stateA.vz);
      const speedB = Math.hypot(stateB.vx, stateB.vz);
      if (speedA < STOP_SPEED_MPS && speedB < STOP_SPEED_MPS) break;
    }
  }

  return { totalReapplyCount };
}

// 套用第一次衝量、產生碰撞當幀樣本，並把兩車交給 runFreeBodyLoop 進入迭代接觸解算。
// 回傳 {x,z} 接觸點，供最終結果的 contact 欄位使用。
function finalizeCollision({ vehA, kA, vehB, kB, dt, maxTime, impactTime,
                              pA, pB, ovResult, sA, sB, samplesA, samplesB }) {
  const contact = { x: ovResult.contactX, z: ovResult.contactZ };
  const vA = velocityAt(vehA, sA, pA.heading, kA);
  const vB = velocityAt(vehB, sB, pB.heading, kB);
  const res = collisionImpulse({
    a: { x: pA.x, z: pA.z, heading: pA.heading, vx: vA.vx, vz: vA.vz, omega: 0,
         mass_kg: vehA.mass_kg, length_m: vehA.length_m },
    b: { x: pB.x, z: pB.z, heading: pB.heading, vx: vB.vx, vz: vB.vz, omega: 0,
         mass_kg: vehB.mass_kg, length_m: vehB.length_m },
    contact,
    normal: { nx: ovResult.nx, nz: ovResult.nz },
    restitution: RESTITUTION,
  });

  samplesA.push({ t: impactTime, x: pA.x, z: pA.z, heading: pA.heading });
  samplesB.push({ t: impactTime, x: pB.x, z: pB.z, heading: pB.heading });

  const stateA = { x: pA.x, z: pA.z, heading: pA.heading,
    vx: res.aAfter.vx, vz: res.aAfter.vz, omega: res.aAfter.omega,
    speed0: Math.hypot(res.aAfter.vx, res.aAfter.vz), omega0: res.aAfter.omega };
  const stateB = { x: pB.x, z: pB.z, heading: pB.heading,
    vx: res.bAfter.vx, vz: res.bAfter.vz, omega: res.bAfter.omega,
    speed0: Math.hypot(res.bAfter.vx, res.bAfter.vz), omega0: res.bAfter.omega };

  runFreeBodyLoop({ vehA, vehB, dt, maxTime, impactTime, stateA, stateB, samplesA, samplesB });

  return contact;
}

// vehicles: 兩台，各含 {path, profile, length_m, width_m, mass_kg, startT?}
// startT：該車第一筆證據的時刻（秒）。在 startT 之前車輛尚未進場——不前進、不參與
// 碰撞偵測與最近間距、不輸出樣本。忽略它會讓晚出現的車提早出發、先騎到衝突點
// 「停著等撞」（test1 機車實際 t≈6.3s 才進場，未修正前被提早了 6.3 秒）。
export function simulate({ vehicles, kA, kB, dt = 1 / 60, maxTime = 12 }) {
  const [vehA, vehB] = vehicles;

  if (!(vehA.path.length > 0) || !(vehB.path.length > 0)) {
    throw new Error('simulate: 車輛路徑長度為 0，無法模擬（軌跡至少需要兩個不同的點）');
  }

  const startTA = vehA.startT ?? 0;
  const startTB = vehB.startT ?? 0;
  const bothPresent = (tt) => tt >= startTA - 1e-12 && tt >= startTB - 1e-12;

  const p0A = sampleAt(vehA.path, 0);
  const p0B = sampleAt(vehB.path, 0);
  const samplesA = [{ t: startTA, x: p0A.x, z: p0A.z, heading: p0A.heading }];
  const samplesB = [{ t: startTB, x: p0B.x, z: p0B.z, heading: p0B.heading }];

  let sA = 0, sB = 0, t = 0;
  let collided = false, impactTime = null, contact = null;
  let minGap = Infinity, minGapTime = 0;

  const ov0 = bothPresent(0)
    ? overlap(obbAt(vehA, p0A.x, p0A.z, p0A.heading), obbAt(vehB, p0B.x, p0B.z, p0B.heading))
    : null;

  if (ov0) {
    // 起點就重疊（極端情境）：沒有「前一步無重疊」可供二分，撞擊時刻直接視為 0。
    collided = true;
    impactTime = 0;
    contact = finalizeCollision({ vehA, kA, vehB, kB, dt, maxTime, impactTime,
      pA: p0A, pB: p0B, ovResult: ov0, sA: 0, sB: 0, samplesA, samplesB });
  } else {
    if (bothPresent(0)) {
      minGap = gap(obbAt(vehA, p0A.x, p0A.z, p0A.heading), obbAt(vehB, p0B.x, p0B.z, p0B.heading));
      minGapTime = 0;
    }

    // Phase 1：兩車各自在（出現後）沿路徑前進，兩車都在場時每步偵測重疊。
    while (t < maxTime) {
      const dtStep = Math.min(dt, maxTime - t);
      if (dtStep <= 1e-12) break;
      const tNext = t + dtStep;

      // 各車只在自己的 startT 之後前進（跨過出現時刻的那一步只前進超出的部分）
      const dtA = Math.max(0, tNext - Math.max(t, startTA));
      const dtB = Math.max(0, tNext - Math.max(t, startTB));
      const sANext = dtA > 0 ? advance(vehA.path, vehA.profile, sA, dtA, kA) : sA;
      const sBNext = dtB > 0 ? advance(vehB.path, vehB.profile, sB, dtB, kB) : sB;
      const pANext = sampleAt(vehA.path, sANext);
      const pBNext = sampleAt(vehB.path, sBNext);

      if (bothPresent(tNext)) {
        const obbANext = obbAt(vehA, pANext.x, pANext.z, pANext.heading);
        const obbBNext = obbAt(vehB, pBNext.x, pBNext.z, pBNext.heading);
        const ov = overlap(obbANext, obbBNext);

        if (ov) {
          const impact = bisectImpact(vehA, kA, sA, vehB, kB, sB, t, tNext, dt, startTA, startTB);
          collided = true;
          impactTime = impact.t;
          contact = finalizeCollision({ vehA, kA, vehB, kB, dt, maxTime, impactTime,
            pA: impact.pA, pB: impact.pB, ovResult: impact.ov, sA: impact.sA, sB: impact.sB,
            samplesA, samplesB });
          break;
        }

        const g = gap(obbANext, obbBNext);
        if (g < minGap) { minGap = g; minGapTime = tNext; }
      }

      sA = sANext; sB = sBNext; t = tNext;
      if (tNext >= startTA) samplesA.push({ t, x: pANext.x, z: pANext.z, heading: pANext.heading });
      if (tNext >= startTB) samplesB.push({ t, x: pBNext.x, z: pBNext.z, heading: pBNext.heading });

      // 兩車都已出現且走完路徑（advance 會把 s 夾在 path.length）→ 之後不會再變化，提早結束。
      if (bothPresent(tNext)
        && sA >= vehA.path.length - 1e-9 && sB >= vehB.path.length - 1e-9) break;
    }
  }

  return {
    collided,
    impactTime,
    contact,
    minGap: collided ? 0 : minGap,
    minGapTime,
    tracks: [{ samples: samplesA }, { samples: samplesB }],
  };
}
