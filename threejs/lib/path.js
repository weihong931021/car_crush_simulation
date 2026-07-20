// 路徑弧長參數化與速度剖面。
//
// 把「軌跡幾何」（固定證據：車走過哪裡）和「速度剖面」（可調變數：車走多快）分開。
// 速度滑桿之後會變成剖面上的縮放係數 k：改變 k 只改變「幾時到某個弧長位置」，
// 不改變路徑本身——這樣才能表達「如果當時開慢一點，就不會撞上」。
//
// 座標慣例（不可更動）：heading = atan2(dx, dz)，前向單位向量 = (sin h, cos h)。

const MIN_SPEED_MPS = 0.01; // speedAt 的下限；0 會讓 advance 卡死（ds 永遠是 0）。

// points: [{x, z, t}]（依時間先後排列）→ {pts: [{x, z, s}], length}
// s 為從第一點開始的累積弧長。相鄰重複位置（零長度線段）會被丟棄以避免後續除以零，
// 但一定保留第一點與最後一點。
export function buildPath(points) {
  if (!points || points.length === 0) return { pts: [], length: 0 };

  const pts = [{ x: points[0].x, z: points[0].z, s: 0 }];
  let s = 0;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const cur = points[i];
    const d = Math.hypot(cur.x - prev.x, cur.z - prev.z);
    const isLast = i === points.length - 1;
    if (d < 1e-12 && !isLast) continue; // 丟棄零長度線段（保留首尾）
    s += d;
    pts.push({ x: cur.x, z: cur.z, s });
  }
  return { pts, length: s };
}

// points: [{x, z, t}] → [{s, v}]，v 為該點所在（結束於該點的）線段之平均速度 (m/s)。
// 第一點取第一段的速度。dt <= 0 的段落跳過（沿用前一個有效速度），
// 避免除以零或倒退時間造成的負速度污染剖面。
export function speedProfile(points) {
  if (!points || points.length === 0) return [];
  if (points.length === 1) return [{ s: 0, v: 0 }];

  // 先算每個相鄰點的弧長，對齊 buildPath 的 s（含零長度線段丟棄邏輯）。
  const path = buildPath(points);
  // buildPath 可能丟棄零長度中間點，這裡改用「原始點對」自行推算對應弧長，
  // 因為 speedProfile 需要保留與 points 對應的每一筆 v，而 buildPath.pts 可能較短。
  let s = 0;
  const sAt = [0];
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const cur = points[i];
    s += Math.hypot(cur.x - prev.x, cur.z - prev.z);
    sAt.push(s);
  }

  const profile = new Array(points.length);
  let lastV = 0;
  let firstV = null;
  for (let i = 1; i < points.length; i++) {
    const dt = points[i].t - points[i - 1].t;
    const ds = sAt[i] - sAt[i - 1];
    let v;
    if (dt > 0) {
      v = ds / dt;
      lastV = v;
    } else {
      v = lastV; // guard dt <= 0：跳過、沿用前一個有效速度
    }
    if (firstV === null) firstV = v;
    profile[i] = { s: sAt[i], v };
  }
  profile[0] = { s: sAt[0], v: firstV ?? 0 };
  return profile;
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

// path: buildPath 的輸出，s: 弧長 → {x, z, heading}
// s 會夾在 [0, path.length]。heading 為所在線段的切線方向（atan2(dx, dz)）。
// 剛好落在頂點上時，用「從該點出發」的線段（結尾頂點例外，用最後一段）。
export function sampleAt(path, s) {
  const pts = path.pts;
  if (!pts || pts.length === 0) return { x: 0, z: 0, heading: 0 };
  if (pts.length === 1) return { x: pts[0].x, z: pts[0].z, heading: 0 };

  const clamped = clamp(s, 0, path.length);

  // 找出 clamped 所在的線段 [i, i+1]。頂點落在該段起點時用該段（往前找），
  // 但若已在最後一點，用最後一段（i = len-2）。
  let i = 0;
  if (clamped >= pts[pts.length - 1].s) {
    i = pts.length - 2;
  } else {
    for (let k = 0; k < pts.length - 1; k++) {
      if (clamped >= pts[k].s && clamped < pts[k + 1].s) { i = k; break; }
    }
  }

  const a = pts[i], b = pts[i + 1];
  const segLen = b.s - a.s;
  const t = segLen > 1e-12 ? (clamped - a.s) / segLen : 0;
  const x = a.x + (b.x - a.x) * t;
  const z = a.z + (b.z - a.z) * t;
  const heading = Math.atan2(b.x - a.x, b.z - a.z);
  return { x, z, heading };
}

// profile: [{s, v}]，線性內插並乘上 k。s 會夾在剖面範圍內。
// 永不回傳小於 MIN_SPEED_MPS 的值（0 會讓 advance 的 ds 永遠是 0、模擬卡死）。
export function speedAt(profile, s, k) {
  if (!profile || profile.length === 0) return MIN_SPEED_MPS;
  if (profile.length === 1) return Math.max(MIN_SPEED_MPS, profile[0].v * k);

  const lo = profile[0].s, hi = profile[profile.length - 1].s;
  const clamped = clamp(s, lo, hi);

  let v;
  if (clamped <= lo) {
    v = profile[0].v;
  } else if (clamped >= hi) {
    v = profile[profile.length - 1].v;
  } else {
    let i = 0;
    for (let k2 = 0; k2 < profile.length - 1; k2++) {
      if (clamped >= profile[k2].s && clamped <= profile[k2 + 1].s) { i = k2; break; }
    }
    const a = profile[i], b = profile[i + 1];
    const segLen = b.s - a.s;
    const t = segLen > 1e-12 ? (clamped - a.s) / segLen : 0;
    v = a.v + (b.v - a.v) * t;
  }
  return Math.max(MIN_SPEED_MPS, v * k);
}

// path, profile, s0（起始弧長）, dt（秒）, k（速度縮放係數）→ s1（前進後的弧長）
// 梯形積分（Heun's method / improved Euler）：先取 s0 的速度 v0 做 Euler 預測得到
// 預測弧長，在預測點重新取速度 v1，取 v0、v1 的平均當作這一步的代表速度。
// 這比單純用 v0 積分更準：變速路段（例如前快後慢）時，v0、v1 分別代表區間頭尾的
// 速度，平均後才不會整段都用「起點速度」導致過衝／低估。結果夾在 [0, path.length]。
export function advance(path, profile, s0, dt, k) {
  const v0 = speedAt(profile, s0, k);
  const sPredict = clamp(s0 + v0 * dt, 0, path.length);
  const v1 = speedAt(profile, sPredict, k);
  const vAvg = (v0 + v1) / 2;
  return clamp(s0 + vAvg * dt, 0, path.length);
}
