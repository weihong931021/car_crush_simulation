// 路徑弧長參數化與速度剖面。
//
// 把「軌跡幾何」（固定證據：車走過哪裡）和「速度剖面」（可調變數：車走多快）分開。
// 速度滑桿之後會變成剖面上的縮放係數 k：改變 k 只改變「幾時到某個弧長位置」，
// 不改變路徑本身——這樣才能表達「如果當時開慢一點，就不會撞上」。
//
// 座標慣例（不可更動）：heading = atan2(dx, dz)，前向單位向量 = (sin h, cos h)。

const MIN_SPEED_MPS = 0.01; // speedAt 的下限；0 會讓 advance 卡死（ds 永遠是 0）。

// 偵測點位的逐幀噪音會讓車輛位置與 heading（取自相鄰線段切線）明顯抖動，
// 也會虛增路徑長（鋸齒比直線長）進而污染速度剖面。播放器與單頁 demo 都應在
// buildPath/speedProfile 之前先過這一步。
//
// 時間窗置中移動平均：每點取 [t-window/2, t+window/2] 內所有點的平均位置。
// 端點錨定不動——首點是出現位置、末點決定碰撞幾何（衝量方向、接觸點），
// 被平均往內拉會直接改變碰撞結果。
// anchorEnd=false 用於「後面接 trimFrozenTail」的管線：凍結尾本來就是要被切掉的假象，
// 錨定它反而在平滑尾端與原始末點之間製造一個瞬間跳躍（假高速），讓 trim 的視窗均速
// 誤判「已回到可信速度」而提前停手。
export function smoothPoints(points, { windowSec = 0.5, anchorEnd = true } = {}) {
  if (!points || points.length < 3) return points ? points.map(p => ({ ...p })) : [];
  const half = windowSec / 2;
  const out = new Array(points.length);
  let lo = 0, hi = 0;
  for (let i = 0; i < points.length; i++) {
    const t = points[i].t;
    while (points[lo].t < t - half) lo++;
    while (hi < points.length - 1 && points[hi + 1].t <= t + half) hi++;
    let sx = 0, sz = 0, n = 0;
    for (let j = lo; j <= hi; j++) { sx += points[j].x; sz += points[j].z; n++; }
    out[i] = { t, x: sx / n, z: sz / n };
  }
  out[0] = { ...points[0] };
  if (anchorEnd) out[out.length - 1] = { ...points[points.length - 1] };
  return out;
}

// 節點抽稀：每 knotSec 取一個錨點（首尾必留）。搭配 splineResample 使用——樣條是
// 「插值」曲線，會忠實通過每個帶噪節點；先抽稀讓殘餘噪音失去節點可依附，樣條再把
// 稀疏錨點連成平滑曲線。代價是比 knotSec 更快的真實小動作會被圓滑掉（demo 可接受，
// 方法卡需註明）。
// minDistM：距離門檻——近乎靜止的路段不下錨（時間制會在原地擠出一團空間重合的錨點，
// 樣條被迫在毫米尺度繞小圈、局部 heading 反而暴衝）。靜止段塌成前後兩個錨點之間的
// 「原地停留」，樣條在該段位置幾乎不動，符合實際。
export function decimatePoints(points, { knotSec = 0.25, minDistM = 0.08 } = {}) {
  if (!points || points.length < 3) return points ? points.map(p => ({ ...p })) : [];
  const out = [{ ...points[0] }];
  let lastT = points[0].t;
  let last = points[0];
  for (let i = 1; i < points.length - 1; i++) {
    const p = points[i];
    if (p.t - lastT >= knotSec && Math.hypot(p.x - last.x, p.z - last.z) >= minDistM) {
      out.push({ ...p });
      lastT = p.t;
      last = p;
    }
  }
  // 終點必留；但它若與最後幾個錨點在空間上擠在一起，樣條會在末端擺尾
  // （尾向也是 extendPoints 的外插方向，敏感）→ 先彈掉距終點 < minDistM 的錨點。
  const finalPt = points[points.length - 1];
  while (out.length > 1
    && Math.hypot(out[out.length - 1].x - finalPt.x, out[out.length - 1].z - finalPt.z) < minDistM) {
    out.pop();
  }
  out.push({ ...finalPt });
  return out;
}

// Catmull-Rom（Barry–Goldman 非均勻節點版）樣條重取樣：以 t 為參數、通過每一個輸入點、
// 切線連續（C¹）。折線的「每個節點一個小轉角」在此消失——路線視覺平順、heading（取自
// 相鄰取樣點切線）連續變化不再逐格跳動。放在 smoothPoints（去噪）之後、extendPoints 之前。
// 邊界用幻影節點（鏡射）避免端點段參數退化；stepSec 取 1/60 讓折線逼近曲線到視覺無感。
export function splineResample(points, { stepSec = 1 / 60 } = {}) {
  if (!points || points.length < 3) return points ? points.map(p => ({ ...p })) : [];
  const n = points.length;
  const mirror = (a, b) => ({ t: a.t - (b.t - a.t), x: a.x - (b.x - a.x), z: a.z - (b.z - a.z) });
  const knots = [mirror(points[0], points[1]), ...points, mirror(points[n - 1], points[n - 2])];
  const lerp2 = (a, b, u, tt) => ({ t: tt, x: a.x + (b.x - a.x) * u, z: a.z + (b.z - a.z) * u });

  const out = [];
  let seg = 1; // knots 索引：目前落在 [knots[seg], knots[seg+1]]
  const tEnd = points[n - 1].t;
  for (let t = points[0].t; t < tEnd - 1e-9; t += stepSec) {
    while (seg < knots.length - 3 && knots[seg + 1].t <= t) seg++;
    const p0 = knots[seg - 1], p1 = knots[seg], p2 = knots[seg + 1], p3 = knots[seg + 2];
    const d10 = (p1.t - p0.t) || 1e-9, d21 = (p2.t - p1.t) || 1e-9, d32 = (p3.t - p2.t) || 1e-9;
    const d20 = (p2.t - p0.t) || 1e-9, d31 = (p3.t - p1.t) || 1e-9;
    const A1 = lerp2(p0, p1, (t - p0.t) / d10, t);
    const A2 = lerp2(p1, p2, (t - p1.t) / d21, t);
    const A3 = lerp2(p2, p3, (t - p2.t) / d32, t);
    const B1 = lerp2(A1, A2, (t - p0.t) / d20, t);
    const B2 = lerp2(A2, A3, (t - p1.t) / d31, t);
    out.push(lerp2(B1, B2, (t - p1.t) / d21, t));
  }
  out.push({ ...points[n - 1] });
  return out;
}

// 縱向慣性約束（前向-後向兩趟掃描，運動規劃的標準做法）：真車的加減速有物理極限
// （加速 ≲0.3g、煞車 ≲0.8g），偵測噪音卻常產生 10g 級的假速度尖峰——蠕行段忽快忽慢
// 的「湧動感」就是它。位置（證據）完全不動，只把「每段耗時」重新分配成可行的
// 速度歷程：前向趟限制加速度、後向趟限制減速度，再由段速重積分時間戳。
// t[0] 錨定（startT 不受影響）；乾淨資料（原本就可行）幾乎不變。
export function limitAcceleration(points, { aMaxMps2 = 3.0, bMaxMps2 = 7.5, minSpeedMps = 0.05 } = {}) {
  if (!points || points.length < 3) return points ? points.map(p => ({ ...p })) : [];
  const n = points.length;
  const ds = new Array(n - 1);
  const v = new Array(n - 1);
  for (let i = 0; i < n - 1; i++) {
    ds[i] = Math.hypot(points[i + 1].x - points[i].x, points[i + 1].z - points[i].z);
    const dt = points[i + 1].t - points[i].t;
    v[i] = Math.max(minSpeedMps, dt > 1e-9 ? ds[i] / dt : minSpeedMps);
  }
  // 前向：v[i]² ≤ v[i-1]² + 2·a·ds（加速上限）
  for (let i = 1; i < n - 1; i++) {
    const cap = Math.sqrt(v[i - 1] * v[i - 1] + 2 * aMaxMps2 * Math.max(ds[i], 1e-9));
    if (v[i] > cap) v[i] = cap;
  }
  // 後向：v[i]² ≤ v[i+1]² + 2·b·ds（煞車上限，倒著看就是加速）
  for (let i = n - 3; i >= 0; i--) {
    const cap = Math.sqrt(v[i + 1] * v[i + 1] + 2 * bMaxMps2 * Math.max(ds[i], 1e-9));
    if (v[i] > cap) v[i] = cap;
  }
  const out = [{ ...points[0] }];
  let t = points[0].t;
  for (let i = 0; i < n - 1; i++) {
    t += ds[i] > 1e-9 ? ds[i] / v[i] : (points[i + 1].t - points[i].t);
    out.push({ t, x: points[i + 1].x, z: points[i + 1].z });
  }
  return out;
}

// 追蹤器在碰撞前 ~0.5s 會因 bbox 重疊+平滑而「凍結」（test1 實測：位移回推 <1 km/h，
// 同時段資料 speed_kmh 欄位 14–21 km/h）。凍結尾若不切除，速度剖面尾端被污染成近 0，
// 模擬會呈現「滑行到定點停著等撞」的假象。
// 從尾端往回走，丟棄「windowSec 視窗均速 < minSpeedMps」的點；最多切 maxTrimSec
// （凍結假象很短，切更多就會吃掉真實的減速行為）。只切尾不切頭——頭部靜止是真實
// 行為（路口等待），尾部靜止緊貼碰撞才是假象。
// windowSec 刻意取短（0.15s）：視窗一跨到凍結前的快段，均速就會被拉高而提前停止修剪，
// 殘留最多一個視窗長的凍結尾。代價是對原始噪音敏感——管線約定「先 smoothPoints 再 trim」。
export function trimFrozenTail(points, { minSpeedMps = 0.5, windowSec = 0.15, maxTrimSec = 1.2 } = {}) {
  if (!points || points.length < 3) return points ? points.map(p => ({ ...p })) : [];
  const tEnd = points[points.length - 1].t;
  let cut = points.length; // 保留 [0, cut)
  for (let i = points.length - 1; i >= 2; i--) {
    if (tEnd - points[i].t > maxTrimSec) break;
    // i 往前 windowSec 的視窗均速
    let j = i;
    while (j > 0 && points[i].t - points[j - 1].t <= windowSec) j--;
    const dt = points[i].t - points[j].t;
    if (dt <= 1e-9) break;
    let d = 0;
    for (let m = j + 1; m <= i; m++) d += Math.hypot(points[m].x - points[m - 1].x, points[m].z - points[m - 1].z);
    if (d / dt >= minSpeedMps) break; // 已回到可信速度，停止修剪
    cut = i;
  }
  const kept = points.slice(0, Math.max(cut, 2));
  return kept.map(p => ({ ...p }));
}

// 證據路徑在最後一個偵測點就斷了：模擬中車輛走到終點會被 advance() 夾住原地停住
// （視覺上像「停著等撞」或「停在路口不走了」）。沿「終點前 headingWindowSec 的平均方向」
// 直線外插 extendM 公尺、以終端速度等速前進——這段是外插不是證據，呼叫端顯示時應與
// 實錄段區分（demo 以虛線表示）。回傳 {points, evidenceEndIndex}。
export function extendPoints(points, { extendM = 10, headingWindowSec = 0.5, minTailSpeedMps = 0.5 } = {}) {
  if (!points || points.length < 2) {
    return { points: points ? points.map(p => ({ ...p })) : [], evidenceEndIndex: (points?.length ?? 1) - 1 };
  }
  const out = points.map(p => ({ ...p }));
  const last = out[out.length - 1];
  // 終點方向與速度：取終點往回 headingWindowSec 的位移
  let j = out.length - 1;
  while (j > 0 && last.t - out[j - 1].t <= headingWindowSec) j--;
  const ref = out[j];
  const dx = last.x - ref.x, dz = last.z - ref.z;
  const dist = Math.hypot(dx, dz);
  const dt = last.t - ref.t;
  if (dist < 1e-6 || dt <= 1e-9) return { points: out, evidenceEndIndex: out.length - 1 }; // 無方向可依，不外插
  const v = Math.max(minTailSpeedMps, dist / dt);
  const ux = dx / dist, uz = dz / dist;
  const evidenceEndIndex = out.length - 1;
  out.push({ t: last.t + extendM / v, x: last.x + ux * extendM, z: last.z + uz * extendM });
  return { points: out, evidenceEndIndex };
}

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
