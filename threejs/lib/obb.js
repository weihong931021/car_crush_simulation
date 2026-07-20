// 定向包圍盒（Oriented Bounding Box）：SAT 碰撞偵測與最短距離。
//
// 座標慣例（不可更動）：heading = atan2(dx, dz)，前向單位向量 f = (sin h, cos h)。
// 側向單位向量 l = (cos h, -sin h)（f 順時針轉 90 度，與 f 正交）。
// 一個 OBB 的「長」沿 f（車頭方向）、「寬」沿 l（左右方向）。

const EPS = 1e-9;

function clamp01(v) {
  return Math.max(0, Math.min(1, v));
}

function dot(a, b) {
  return a.x * b.x + a.z * b.z;
}

// z 分量的 2D 外積（用來判斷點在邊的哪一側）。
function cross(a, b) {
  return a.x * b.z - a.z * b.x;
}

// x, z: 中心點；heading: 朝向（弧度）；length, width: 真實車長／車寬（公尺）
// -> {cx, cz, h, hl, hw}，hl/hw 為半長／半寬。
export function makeOBB(x, z, heading, length, width) {
  return { cx: x, cz: z, h: heading, hl: length / 2, hw: width / 2 };
}

// obb -> [{x,z} x4]，依 (+hl+hw)→(+hl-hw)→(-hl-hw)→(-hl+hw) 順序繞行一圈
// （每步翻一個正負號，形成沿矩形周界的合法走訪，不論 h 為何都不會自交）。
export function corners(obb) {
  const { cx, cz, h, hl, hw } = obb;
  const fx = Math.sin(h), fz = Math.cos(h); // 前向單位向量
  const lx = Math.cos(h), lz = -Math.sin(h); // 側向單位向量
  return [
    { x: cx + hl * fx + hw * lx, z: cz + hl * fz + hw * lz },
    { x: cx + hl * fx - hw * lx, z: cz + hl * fz - hw * lz },
    { x: cx - hl * fx - hw * lx, z: cz - hl * fz - hw * lz },
    { x: cx - hl * fx + hw * lx, z: cz - hl * fz + hw * lz },
  ];
}

// 四個角投影到 axis 上的區間重疊量（正值 = 重疊該量、負值/零 = 該軸為分離軸）。
function axisOverlapDepth(cornersA, cornersB, axis) {
  let minA = Infinity, maxA = -Infinity, minB = Infinity, maxB = -Infinity;
  for (const p of cornersA) {
    const proj = p.x * axis.x + p.z * axis.z;
    if (proj < minA) minA = proj;
    if (proj > maxA) maxA = proj;
  }
  for (const p of cornersB) {
    const proj = p.x * axis.x + p.z * axis.z;
    if (proj < minB) minB = proj;
    if (proj > maxB) maxB = proj;
  }
  return Math.min(maxA, maxB) - Math.max(minA, minB);
}

// SAT 核心：4 軸（a 前向/側向、b 前向/側向）逐一測試。
// 任一軸出現分離（depth <= 0）即回 null；否則回穿透深度最小的軸（最小平移向量）。
function satTest(a, b) {
  const ca = corners(a), cb = corners(b);
  const axes = [
    { x: Math.sin(a.h), z: Math.cos(a.h) },
    { x: Math.cos(a.h), z: -Math.sin(a.h) },
    { x: Math.sin(b.h), z: Math.cos(b.h) },
    { x: Math.cos(b.h), z: -Math.sin(b.h) },
  ];

  let minDepth = Infinity;
  let minAxis = null;
  for (const axis of axes) {
    const depth = axisOverlapDepth(ca, cb, axis);
    if (depth <= 0) return null;
    if (depth < minDepth) {
      minDepth = depth;
      minAxis = axis;
    }
  }
  return { depth: minDepth, axis: minAxis, ca, cb };
}

// 用 clipPoly（凸多邊形，含其中心 clipCenter 供邊的內外側判斷）裁切 subject 多邊形。
// Sutherland–Hodgman：逐邊裁切，每邊用「哪一側含 clipCenter」當作「內側」，
// 這樣不論 corners() 走訪方向是順時針或逆時針都正確。
function clipPolygon(subject, clipPoly, clipCenter) {
  let output = subject;
  for (let i = 0; i < clipPoly.length && output.length > 0; i++) {
    const p1 = clipPoly[i];
    const p2 = clipPoly[(i + 1) % clipPoly.length];
    const edge = { x: p2.x - p1.x, z: p2.z - p1.z };
    const refCross = cross(edge, { x: clipCenter.x - p1.x, z: clipCenter.z - p1.z });
    const refSign = refCross >= 0 ? 1 : -1;

    const input = output;
    output = [];
    for (let j = 0; j < input.length; j++) {
      const cur = input[j];
      const prev = input[(j - 1 + input.length) % input.length];
      const curCross = cross(edge, { x: cur.x - p1.x, z: cur.z - p1.z });
      const prevCross = cross(edge, { x: prev.x - p1.x, z: prev.z - p1.z });
      const curIn = curCross * refSign >= -EPS;
      const prevIn = prevCross * refSign >= -EPS;
      if (curIn) {
        if (!prevIn) output.push(intersectAtEdge(prev, cur, prevCross, curCross));
        output.push(cur);
      } else if (prevIn) {
        output.push(intersectAtEdge(prev, cur, prevCross, curCross));
      }
    }
  }
  return output;
}

// prev→cur 線段與裁切邊（由 prevCross/curCross 隱含）的交點。
function intersectAtEdge(prev, cur, prevCross, curCross) {
  const denom = prevCross - curCross;
  const t = Math.abs(denom) > EPS ? prevCross / denom : 0;
  return { x: prev.x + (cur.x - prev.x) * t, z: prev.z + (cur.z - prev.z) * t };
}

// a, b: makeOBB() 的輸出
// -> null（無重疊）| {depth, nx, nz, contactX, contactZ}
//   depth: 最小穿透深度
//   (nx, nz): 該分離軸的單位法向，方向由 a 指向 b
//   (contactX, contactZ): 重疊區域（a、b 角點多邊形的交集）之角點平均；
//     若裁切結果為空（退化情形），退回兩中心點的中點
export function overlap(a, b) {
  const sat = satTest(a, b);
  if (!sat) return null;
  const { depth, axis, ca, cb } = sat;

  let nx = axis.x, nz = axis.z;
  const toBx = b.cx - a.cx, toBz = b.cz - a.cz;
  if (nx * toBx + nz * toBz < 0) {
    nx = -nx;
    nz = -nz;
  }

  const clipped = clipPolygon(ca, cb, { x: b.cx, z: b.cz });
  let contactX, contactZ;
  if (clipped.length > 0) {
    let sx = 0, sz = 0;
    for (const p of clipped) {
      sx += p.x;
      sz += p.z;
    }
    contactX = sx / clipped.length;
    contactZ = sz / clipped.length;
  } else {
    contactX = (a.cx + b.cx) / 2;
    contactZ = (a.cz + b.cz) / 2;
  }

  return { depth, nx, nz, contactX, contactZ };
}

// 兩線段 p1-p2、q1-q2 之最短距離（2D，x/z 平面）。
// 標準最近點演算法（Ericson, Real-Time Collision Detection §5.1.9）。
function segSegDist(p1, p2, q1, q2) {
  const d1x = p2.x - p1.x, d1z = p2.z - p1.z;
  const d2x = q2.x - q1.x, d2z = q2.z - q1.z;
  const rx = p1.x - q1.x, rz = p1.z - q1.z;

  const a = d1x * d1x + d1z * d1z;
  const e = d2x * d2x + d2z * d2z;
  const f = d2x * rx + d2z * rz;

  let s, t;
  if (a <= EPS && e <= EPS) {
    s = 0;
    t = 0;
  } else if (a <= EPS) {
    s = 0;
    t = clamp01(f / e);
  } else {
    const c = d1x * rx + d1z * rz;
    if (e <= EPS) {
      t = 0;
      s = clamp01(-c / a);
    } else {
      const b = d1x * d2x + d1z * d2z;
      const denom = a * e - b * b;
      s = Math.abs(denom) > EPS ? clamp01((b * f - c * e) / denom) : 0;
      t = (b * s + f) / e;
      if (t < 0) {
        t = 0;
        s = clamp01(-c / a);
      } else if (t > 1) {
        t = 1;
        s = clamp01((b - c) / a);
      }
    }
  }

  const c1x = p1.x + d1x * s, c1z = p1.z + d1z * s;
  const c2x = q1.x + d2x * t, c2z = q1.z + d2z * t;
  return Math.hypot(c1x - c2x, c1z - c2z);
}

// a, b: makeOBB() 的輸出 -> 兩矩形最短距離（公尺）。重疊時回 0。
// 非重疊時取兩矩形所有邊（各 4 條）兩兩配對的線段最短距離之最小值——
// 凸多邊形之間的最短距離必發生在某一對邊（或其端點）之間，故窮舉 4x4=16 對已足夠。
export function gap(a, b) {
  if (satTest(a, b) !== null) return 0;

  const ca = corners(a), cb = corners(b);
  let minDist = Infinity;
  for (let i = 0; i < 4; i++) {
    const a1 = ca[i], a2 = ca[(i + 1) % 4];
    for (let j = 0; j < 4; j++) {
      const b1 = cb[j], b2 = cb[(j + 1) % 4];
      const d = segSegDist(a1, a2, b1, b2);
      if (d < minDist) minDist = d;
    }
  }
  return minDist;
}
