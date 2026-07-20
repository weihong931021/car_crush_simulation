// 安全速度區間求解：不是「找一個臨界值」，而是回答「哪些速度縮放 k 可以避開碰撞」。
//
// 背景（見 p2-task-6-report.md）：交叉路口衝突沒有單一臨界值——車速太慢，對方已經先通過；
// 車速太快，換成自己先通過——「撞」只是中間一段速度窗，兩端都是安全的。這正是事故分析想
// 呈現的洞見：「車速再慢一點，或再快一點，都能避開」，所以這裡回傳的是完整的安全區間集合，
// 而不是一個單一的「臨界速度」（原本 `criticalScale` 的單一臨界值介面已捨棄，見報告第一輪）。
//
// 座標與碰撞判定完全沿用 simulate()（見 simulate.js），這裡只是對它做多點掃描 + 二分。

import { simulate } from './simulate.js';

const DEFAULT_OTHER_K = 1;
const DEFAULT_K_MIN = 0.2;
const DEFAULT_K_MAX = 1.5;
const DEFAULT_STEPS = 40;
const DEFAULT_TOL = 0.005;
const MAX_BISECT_STEPS = 20; // 保險絲：即使 tol 給得很小也不會無止盡二分（見下方呼叫處註解）

function fmt(k) {
  return k.toFixed(3);
}

// vehicles/which/otherK → 該次呼叫要用哪組 kA/kB 呼叫 simulate()
function collidedAt(vehicles, which, otherK, k) {
  const kA = which === 0 ? k : otherK;
  const kB = which === 0 ? otherK : k;
  return simulate({ vehicles, kA, kB }).collided;
}

// [lo, hi] 已知兩端 collided 狀態不同，二分到 hi-lo <= tol，回傳邊界（取中點）。
// MAX_BISECT_STEPS 是保險絲：正常情況下 tol=0.005 配合粗掃後的 bracket 寬度，
// 遠低於這個上限就會收斂（見下方 report 的 calls 統計），只在極端小 tol 時才會提早跳出。
function refine(lo, hi, loCollided, evalFn, tol) {
  let steps = 0;
  while (hi - lo > tol && steps < MAX_BISECT_STEPS) {
    const mid = (lo + hi) / 2;
    const midCollided = evalFn(mid);
    if (midCollided === loCollided) lo = mid; else hi = mid;
    steps++;
  }
  return (lo + hi) / 2;
}

// vehicles: 兩台，各含 {path, profile, length_m, width_m, mass_kg}（同 simulate() 的介面）
// which: 0 或 1，要為哪一台求安全速度區間；另一台固定在 otherK。
export function solveSafeSpeeds({
  vehicles,
  which,
  otherK = DEFAULT_OTHER_K,
  kMin = DEFAULT_K_MIN,
  kMax = DEFAULT_K_MAX,
  steps = DEFAULT_STEPS,
  tol = DEFAULT_TOL,
}) {
  let calls = 0;
  const evalFn = (k) => {
    calls++;
    return collidedAt(vehicles, which, otherK, k);
  };

  const actualCollides = evalFn(1);

  // 1) 粗掃：steps 個等間距點涵蓋 [kMin, kMax]（含兩端）
  const ks = new Array(steps);
  const collided = new Array(steps);
  for (let i = 0; i < steps; i++) {
    const k = steps === 1 ? kMin : kMin + (i * (kMax - kMin)) / (steps - 1);
    ks[i] = k;
    collided[i] = evalFn(k);
  }

  // 2) 每個翻轉點各自精修到 tol 以內，由小到大收集進 transitions
  const transitions = [];
  for (let i = 1; i < steps; i++) {
    if (collided[i] !== collided[i - 1]) {
      const boundary = refine(ks[i - 1], ks[i], collided[i - 1], evalFn, tol);
      transitions.push(boundary);
    }
  }

  // 3) 用 [kMin, ...transitions, kMax] 當分段點，重建每一段的撞/不撞狀態
  //    （第一段狀態 = 粗掃第一個點 collided[0]，之後每跨過一個 transition 就翻轉一次）。
  const breakpoints = [kMin, ...transitions, kMax];
  const segStates = new Array(breakpoints.length - 1);
  let state = collided[0];
  for (let i = 0; i < segStates.length; i++) {
    segStates[i] = state;
    state = !state;
  }

  // 4) safeIntervals：不撞的連續段，clip 在 [kMin, kMax] 內（分段點本身就已經是 clip 過的）
  const safeIntervals = [];
  for (let i = 0; i < segStates.length; i++) {
    if (!segStates[i]) safeIntervals.push([breakpoints[i], breakpoints[i + 1]]);
  }

  // 5) slowerK / fasterK：找出 k=1 所在的那一段，若該段是「撞」，
  //    左右邊界只有在「確實是一個 transition（不是 kMin/kMax 本身）」時才回報，
  //    否則代表在搜尋範圍內、往那個方向到頭都還在撞，回傳 null。
  let slowerK = null;
  let fasterK = null;
  if (actualCollides) {
    let segIdx = segStates.length - 1;
    for (let i = 0; i < breakpoints.length - 1; i++) {
      if (1 >= breakpoints[i] && 1 <= breakpoints[i + 1]) { segIdx = i; break; }
    }
    if (segIdx > 0) slowerK = breakpoints[segIdx]; // 左邊界是 transitions[segIdx-1]
    if (segIdx < segStates.length - 1) fasterK = breakpoints[segIdx + 1]; // 右邊界是下一個 transition
  }

  // 6) note：繁體中文，描述這次求解的結論
  let note;
  if (transitions.length === 0) {
    note = actualCollides
      ? `在搜尋範圍 k∈[${fmt(kMin)}, ${fmt(kMax)}] 內全程都會碰撞，速度縮放本身無法避開，` +
        `需要擴大搜尋範圍或改變路徑幾何。`
      : `在搜尋範圍 k∈[${fmt(kMin)}, ${fmt(kMax)}] 內全程都不會碰撞（兩車路徑本來就沒有靠近），` +
        `目前車速（k=1）本來就安全。`;
  } else if (!actualCollides) {
    note = `目前車速（k=1）已可避開碰撞。搜尋範圍內另外偵測到 ${transitions.length} 個速度邊界，` +
      `代表某些其他速度縮放（不含目前值）會撞上，僅供參考。`;
  } else if (slowerK != null && fasterK != null) {
    note = `目前車速（k=1）會碰撞。放慢到 k≤${fmt(slowerK)}（對方先通過）或加快到 k≥${fmt(fasterK)}` +
      `（自己先通過）都能避開——這是一個中間會撞、兩端安全的速度窗，不是單一臨界值。`;
  } else if (slowerK != null) {
    note = `目前車速（k=1）會碰撞。放慢到 k≤${fmt(slowerK)} 可避開；往加快方向在搜尋範圍內` +
      `（最高到 k=${fmt(kMax)}）找不到安全速度，需擴大 kMax 才能確認是否存在更快的安全區間。`;
  } else if (fasterK != null) {
    note = `目前車速（k=1）會碰撞。加快到 k≥${fmt(fasterK)} 可避開；往放慢方向在搜尋範圍內` +
      `（最低到 k=${fmt(kMin)}）找不到安全速度，需擴大 kMin 才能確認是否存在更慢的安全區間。`;
  } else {
    // segIdx 涵蓋了整個 [kMin, kMax]（transitions 都不在 1 的兩側，理論上不會發生在
    // transitions.length>0 且該段仍撞的情況下，保留為防禦性分支）。
    note = `目前車速（k=1）會碰撞，但在搜尋範圍 k∈[${fmt(kMin)}, ${fmt(kMax)}] 內找不到明確的` +
      `安全邊界，建議擴大搜尋範圍。`;
  }

  return { actualCollides, transitions, safeIntervals, slowerK, fasterK, calls, note };
}
