// 安全速度區間求解：不是「找一個臨界值」，而是回答「哪些速度縮放 k 可以避開碰撞」。
//
// 背景（見 p2-task-6-report.md）：交叉路口衝突沒有單一臨界值——車速太慢，對方已經先通過；
// 車速太快，換成自己先通過——「撞」只是中間一段速度窗，兩端都是安全的。這正是事故分析想
// 呈現的洞見：「車速再慢一點，或再快一點，都能避開」，所以這裡回傳的是完整的安全區間集合，
// 而不是一個單一的「臨界速度」（原本 `criticalScale` 的單一臨界值介面已捨棄，見報告第一輪）。
//
// 座標與碰撞判定完全沿用 simulate()（見 simulate.js），這裡只是對它做多點掃描 + 二分。
//
// 解析度限制（沒有自適應加密）：粗掃只在 [kMin, kMax] 內均勻取 steps 個點，相鄰兩點之間
// 一律線性假設「狀態不變」。如果安全窗比掃描間距 Δk=(kMax-kMin)/(steps-1) 還窄，掃描可能
// 兩側都採到「撞」而完全跳過中間那段窄窗，回報「全程都撞」但其實存在漏看的窄安全窗——
// 這不是 bug，是離散取樣的本質限制，呼叫端（含 note 文字）必須誠實反映這一點，不能宣稱
// 「全程」是範圍內每一點都驗證過的事實。

import { simulate } from './simulate.js';

const DEFAULT_OTHER_K = 1;
const DEFAULT_K_MIN = 0.2;
const DEFAULT_K_MAX = 1.5;
const DEFAULT_STEPS = 40;
const DEFAULT_TOL = 0.005;
const MAX_BISECT_STEPS = 20; // 保險絲：即使 tol 給得很小也不會無止盡二分（見下方呼叫處註解）
const ONE_EPS = 1e-9; // 判斷粗掃網格上是否「已經」剛好有一點等於 k=1（浮點誤差容許值）

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
  let n = 0;
  while (hi - lo > tol && n < MAX_BISECT_STEPS) {
    const mid = (lo + hi) / 2;
    const midCollided = evalFn(mid);
    if (midCollided === loCollided) lo = mid; else hi = mid;
    n++;
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

  const oneInRange = kMin <= 1 && 1 <= kMax;

  // 1) 粗掃：steps 個等間距點涵蓋 [kMin, kMax]（含兩端）。
  //    若 k=1 落在範圍內，把它併入掃描點（除非網格本來就剛好踩到），這樣 actualCollides
  //    和 safeIntervals/note 保證來自同一批評估、不會互相矛盾（見檔案開頭說明與
  //    p2-task-6-report.md「Fix：掃描一致性與範圍處理」）。避免對 k=1 重複呼叫 simulate()，
  //    calls 才誠實反映真正做了幾次模擬。
  const ks = new Array(steps);
  for (let i = 0; i < steps; i++) {
    ks[i] = steps === 1 ? kMin : kMin + (i * (kMax - kMin)) / (steps - 1);
  }
  let oneIdx = -1;
  if (oneInRange) {
    oneIdx = ks.findIndex((k) => Math.abs(k - 1) < ONE_EPS);
    if (oneIdx === -1) {
      let insertAt = ks.length;
      for (let i = 0; i < ks.length; i++) {
        if (ks[i] > 1) { insertAt = i; break; }
      }
      ks.splice(insertAt, 0, 1);
      oneIdx = insertAt;
    }
  }

  const collided = ks.map(evalFn);

  // actualCollides：k=1 若在掃描範圍內，直接重用剛剛那次評估（見上）；不在範圍內時，
  // 掃描本來就不涵蓋 k=1，沒有既有評估可重用，只能另外呼叫一次（+1 calls）。
  const actualCollides = oneInRange ? collided[oneIdx] : evalFn(1);

  // 2) 每個翻轉點各自精修到 tol 以內，由小到大收集進 transitions
  const transitions = [];
  for (let i = 1; i < ks.length; i++) {
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

  // 5) slowerK / fasterK：只有在 k=1 本身落在掃描範圍內時，才談得上「相對於目前車速」的
  //    邊界——範圍不涵蓋 k=1（1 < kMin 或 1 > kMax）時，範圍內找到的任何 transition 都跟
  //    「目前車速」無關（不是它的左右邊界），硬要標成 slowerK/fasterK 就是錯誤標記
  //    （見 p2-task-6-report.md 的第二個 bug 記錄），一律回傳 null，note 另外說明。
  let slowerK = null;
  let fasterK = null;
  if (oneInRange && actualCollides) {
    let segIdx = segStates.length - 1;
    for (let i = 0; i < breakpoints.length - 1; i++) {
      if (1 >= breakpoints[i] && 1 <= breakpoints[i + 1]) { segIdx = i; break; }
    }
    if (segIdx > 0) slowerK = breakpoints[segIdx]; // 左邊界是 transitions[segIdx-1]
    if (segIdx < segStates.length - 1) fasterK = breakpoints[segIdx + 1]; // 右邊界是下一個 transition
  }

  // 6) note：繁體中文，描述這次求解的結論。粗掃是有限取樣，不能宣稱「全程」——
  //    只能誠實描述「取樣的 N 點皆為 X」並附上取樣間距，承認解析度限制（見檔案開頭說明）。
  const deltaK = steps > 1 ? (kMax - kMin) / (steps - 1) : 0;
  let note;
  if (!oneInRange) {
    const side = 1 < kMin ? `低於搜尋範圍下限 kMin=${fmt(kMin)}` : `高於搜尋範圍上限 kMax=${fmt(kMax)}`;
    note = `目前車速（k=1）${side}，本次搜尋範圍不包含目前車速，slowerK/fasterK 未定義（回傳 null）。` +
      (transitions.length > 0
        ? `範圍內另外找到 ${transitions.length} 個速度邊界（僅供參考，並非相對於目前車速的邊界）。`
        : `範圍內取樣的 ${steps} 點（間距 Δk≈${deltaK.toFixed(3)}）皆為${collided[0] ? '碰撞' : '不碰撞'}。`);
  } else if (transitions.length === 0) {
    note = actualCollides
      ? `在 k∈[${fmt(kMin)}, ${fmt(kMax)}] 取樣的 ${steps} 點皆發生碰撞（掃描間距 Δk≈${deltaK.toFixed(3)}）；` +
        `這是有限取樣的結果，不代表整個區間必然無安全窗——比 Δk 更窄的安全窗可能未被偵測到，` +
        `建議加大 steps 或縮小搜尋範圍重新檢查。`
      : `在 k∈[${fmt(kMin)}, ${fmt(kMax)}] 取樣的 ${steps} 點皆未發生碰撞（掃描間距 Δk≈${deltaK.toFixed(3)}）；` +
        `目前車速（k=1）在取樣範圍內安全，但比 Δk 更窄的碰撞窗理論上仍可能被漏看。`;
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
