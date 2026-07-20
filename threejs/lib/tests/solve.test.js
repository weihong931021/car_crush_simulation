import test from 'node:test';
import assert from 'node:assert/strict';
import { simulate } from '../simulate.js';
import { buildPath, speedProfile } from '../path.js';
import { solveSafeSpeeds } from '../solve.js';

function veh(points, length_m, width_m, mass_kg) {
  return { path: buildPath(points), profile: speedProfile(points), length_m, width_m, mass_kg };
}
// 沿用 Task 5 的路徑 fixture：汽車沿 +Z 穿越原點；機車沿 +X 穿越原點；
// 等速 10 m/s，同時抵達 → 必撞（見 simulate.test.js）
const carPts  = Array.from({ length: 41 }, (_, i) => ({ x: 0, z: -20 + i, t: i * 0.1 }));
const motoPts = Array.from({ length: 41 }, (_, i) => ({ x: -20 + i, z: 0, t: i * 0.1 }));

function fixtureVehicles() {
  return [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)];
}

// 這組共用 fixture 在預設參數 [0.2, 1.5] 下沒有單一臨界值，而是「中間會撞、兩端安全」的
// 速度窗（交叉路口衝突的本質：太慢對方先過、太快自己先過，兩邊都閃得掉）——見
// p2-task-6-report.md 的 BLOCKED 記錄與控制者裁定。以下數值是用獨立二分腳本量測的邊界：
//   which=0（汽車，otherK=1 固定機車）：下邊界 ≈0.7927、上邊界 ≈1.2492
//   which=1（機車，otherK=1 固定汽車）：下邊界 ≈0.8007、上邊界 ≈1.2607

test('solveSafeSpeeds: 目前車速（k=1）確實會碰撞', () => {
  const vehicles = fixtureVehicles();
  const r = solveSafeSpeeds({ vehicles, which: 0 });
  assert.equal(r.actualCollides, true);
});

test('solveSafeSpeeds: which=0 找到兩個邊界，符合獨立量測值 ±0.01', () => {
  const vehicles = fixtureVehicles();
  const r = solveSafeSpeeds({ vehicles, which: 0 });
  assert.equal(r.transitions.length, 2);
  assert.ok(Math.abs(r.transitions[0] - 0.7927) < 0.01,
    `下邊界應接近 0.7927，實得 ${r.transitions[0]}`);
  assert.ok(Math.abs(r.transitions[1] - 1.2492) < 0.01,
    `上邊界應接近 1.2492，實得 ${r.transitions[1]}`);
});

test('solveSafeSpeeds: safeIntervals 有兩段，分別止於下邊界、始於上邊界', () => {
  const vehicles = fixtureVehicles();
  const r = solveSafeSpeeds({ vehicles, which: 0 });
  assert.equal(r.safeIntervals.length, 2);
  assert.ok(Math.abs(r.safeIntervals[0][1] - r.transitions[0]) < 1e-6);
  assert.ok(Math.abs(r.safeIntervals[1][0] - r.transitions[1]) < 1e-6);
});

test('solveSafeSpeeds: 邊界用 simulate() 交叉驗證——這是真正重要的斷言', () => {
  const vehicles = fixtureVehicles();
  const r = solveSafeSpeeds({ vehicles, which: 0 });
  assert.ok(r.slowerK != null && r.fasterK != null);

  assert.equal(simulate({ vehicles, kA: r.slowerK - 0.02, kB: 1 }).collided, false,
    '再慢一點（slowerK-0.02）應該閃過');
  assert.equal(simulate({ vehicles, kA: r.slowerK + 0.02, kB: 1 }).collided, true,
    '比 slowerK 快一點應該撞上');

  assert.equal(simulate({ vehicles, kA: r.fasterK + 0.02, kB: 1 }).collided, false,
    '再快一點（fasterK+0.02）應該閃過');
  assert.equal(simulate({ vehicles, kA: r.fasterK - 0.02, kB: 1 }).collided, true,
    '比 fasterK 慢一點應該撞上');
});

test('solveSafeSpeeds: 兩台車各自求解都能找到 slowerK/fasterK', () => {
  const vehicles = fixtureVehicles();
  const a = solveSafeSpeeds({ vehicles, which: 0 });
  const b = solveSafeSpeeds({ vehicles, which: 1 });
  assert.ok(a.slowerK != null && a.fasterK != null);
  assert.ok(b.slowerK != null && b.fasterK != null);
});

test('solveSafeSpeeds: 兩車路徑完全不靠近 → 不撞、無邊界、不丟例外', () => {
  const farMotoPts = motoPts.map(p => ({ ...p, z: p.z + 50 })); // 機車整條路徑平移到 z=50，永遠不會靠近汽車（沿 x=0 直線）
  const vehicles = [veh(carPts, 4.69, 1.85, 1500), veh(farMotoPts, 1.85, 0.7, 200)];
  const r = solveSafeSpeeds({ vehicles, which: 0 });
  assert.equal(r.actualCollides, false);
  assert.equal(r.transitions.length, 0);
  assert.equal(typeof r.note, 'string');
  assert.ok(r.note.length > 0);
});

test('solveSafeSpeeds: calls 有界（粗掃 + 每個邊界約 10 次二分，不失控）', () => {
  const vehicles = fixtureVehicles();
  const r = solveSafeSpeeds({ vehicles, which: 0 });
  // steps(40，k=1 剛好落在網格上、與 actualCollides 共用同一次評估，不重複算) +
  // 2 個邊界各自二分（每個遠低於 20 步保險絲）
  assert.ok(Number.isFinite(r.calls) && r.calls > 0 && r.calls < 100,
    `calls 應該是有界的小數字，實得 ${r.calls}`);
});

// --- Fix 回歸測試：粗掃走樣（aliasing）與搜尋範圍不涵蓋 k=1 ---
// 見 p2-task-6-report.md「Fix：掃描一致性與範圍處理」：reviewer 發現的兩個真實缺陷，
// 以下兩個測試分別釘住修復後的不變量，而不是釘死某個具體數字（那樣反而會把 bug 錄回去）。

test('solveSafeSpeeds: 粗掃走樣情境（車輛縮到 0.02m、steps=41）——actualCollides 與 safeIntervals 必須自洽', () => {
  // reviewer 的原始 repro：車輛縮到 0.02m，安全窗變得非常窄，steps=41 的預設等距網格
  // 剛好兩側都落在「撞」，若 actualCollides 和 safeIntervals 各自獨立計算，會回報矛盾的
  // 「全程都撞」但 actualCollides 自己說 k=1 會撞——這裡直接釘住「不能同時矛盾」這個不變量。
  const vehicles = [veh(carPts, 0.02, 0.02, 1500), veh(motoPts, 0.02, 0.02, 200)];
  const r = solveSafeSpeeds({ vehicles, which: 0, steps: 41 });

  const oneInsideSafeInterval = r.safeIntervals.some(([lo, hi]) => 1 >= lo && 1 <= hi);
  if (r.actualCollides) {
    assert.equal(oneInsideSafeInterval, false,
      'actualCollides=true 時，k=1 不該落在任何 safeIntervals 區間內');
  } else {
    assert.equal(oneInsideSafeInterval, true,
      'actualCollides=false 時，k=1 應該落在某個 safeIntervals 區間內');
  }
  // 用獨立的 simulate() 呼叫核實 ground truth，確保「自洽」不是兩邊都錯但剛好一致：
  assert.equal(r.actualCollides, simulate({ vehicles, kA: 1, kB: 1 }).collided);
});

test('solveSafeSpeeds: 搜尋範圍不涵蓋 k=1（kMin=1.2, kMax=1.5）——slowerK/fasterK 不能亂標', () => {
  const vehicles = fixtureVehicles();
  const r = solveSafeSpeeds({ vehicles, which: 0, kMin: 1.2, kMax: 1.5 });
  // reviewer 的原始 repro：範圍內找到的 transition（≈1.248，其實是撞轉不撞的「快邊」）
  // 被誤標成 slowerK，且與 actualCollides=true（k=1 會撞、但 1 < kMin，範圍外）矛盾。
  assert.ok(!(r.actualCollides === true && r.slowerK != null && r.slowerK > 1),
    'actualCollides=true 時，slowerK 不該是一個大於 1 的值（那是快邊，不是慢邊）');
  assert.equal(r.slowerK, null, '搜尋範圍不含 k=1 時，slowerK 應回傳 null');
  assert.equal(r.fasterK, null, '搜尋範圍不含 k=1 時，fasterK 應回傳 null');
  assert.match(r.note, /範圍|kMin|kMax/, 'note 必須說明搜尋範圍不包含目前車速');
});
