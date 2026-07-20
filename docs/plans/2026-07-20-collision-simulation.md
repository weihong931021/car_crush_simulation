# 碰撞模擬重構 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。步驟以 `- [ ]` 追蹤。

**Goal:** 把「重播＋固定時刻衝量」換成「沿路徑前向模擬＋真實 OBB 碰撞偵測」，並提供臨界速度求解（調慢多少就閃過）。

**Architecture:** 純函式層 `threejs/lib/`（path/obb/simulate/solve + 改造 physics），`main.js` 只負責呈現。物理留在 JS，維持互動。

**Tech Stack:** ES modules、three.js 0.165.0（僅 main.js 用）、`node --test`、Python 3 stdlib + unittest。

**Spec:** `docs/specs/2026-07-20-collision-simulation-design.md`

## Global Constraints

- `threejs/lib/**` **不得 import three.js**（保持 node 可測）；無 bundler、無新增外部相依
- 測試指令：`node --test threejs/lib/tests/*.test.js`（目錄形式在此 Node 會失敗，必用 glob）、`python3 -m unittest discover -s tools/tests`
- 座標約定（已驗證，勿改）：`heading = atan2(dx, dz)`、前向 `(sin h, cos h)`、three.js `rotation.y = heading`、右手系叉積 y 分量 `(r×J)_y = r_z·J_x − r_x·J_z`
- Waypoint 格式維持 `[animFrame, x, z, headingOrNull]`
- 車輛尺寸語意：`length_m` / `width_m` 一律為**真實車輛尺寸**；GLB 依此縮放
- 壞資料一律 throw → 播放器錯誤 overlay，不得靜默算錯
- 每個 task 結尾 commit，訊息繁體中文，結尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- **不得修改 controller 的驗證腳本**（`/private/tmp/claude-501/-Users-weihong-Documents-blender-crash-project/f5008c29-89fc-4c5d-99b4-a7daf239d5ee/scratchpad/{smoke_test,frame_shots}.mjs`）——照原樣執行

## 現況基準（重構前，須在最後比對）

- test1：collider wps 72/61、extras 0、碰撞在 anim frame 32，車 f32 `rotY≈164.1 pos≈[-2.9,4.99]`
- tainan_yongkang：2 colliders + extras 1
- 測試：JS 14、Python 8
- 模型 flip 已修（car −2.9490、moto −0.9495），`registry.json` 另記 `length_m` 實測值

---

### Task 1: 車輛尺寸成為真實尺寸 + GLB scale-to-length

**Files:** `tools/build_scene.py`、`tools/tests/test_build_scene.py`、`scenes/*/scene.json`、`threejs/main.js`、`threejs/models/registry.json`

**Interfaces:**
- Produces: `CLASS_DEFAULTS` 每項增加 `width_m`；scene.json 的 vehicle 多 `width_m`
- Produces: `wrapModel(gltfScene, flip, targetLengthM)` — 依模型實測長度等比縮放至 `targetLengthM`

- [ ] **Step 1: 更新 `CLASS_DEFAULTS` 為真實尺寸**（長, 寬, 質量）

```python
# (model, mass_kg, length_m, width_m, default_speed_kmh, pre_samples)
CLASS_DEFAULTS = {
    "Car":         ("car.glb",  1500, 4.69, 1.85, 20, 15),
    "SUV":         ("car.glb",  1800, 4.60, 1.90, 20, 15),
    "Van":         ("car.glb",  2000, 4.80, 2.00, 20, 15),
    "Truck":       ("car.glb",  5000, 7.00, 2.50, 20, 15),
    "Bus":         ("car.glb", 11000, 11.00, 2.55, 20, 15),
    "Two_Wheeler": ("moto.glb",  200, 1.85, 0.70, 40, 4),
}
```
`build()` 產出的 vehicle 增加 `"width_m": width`。`validate_scene` 的必填欄位加入 `width_m`。

- [ ] **Step 2: Python 測試（先紅）** — 於 `tools/tests/test_build_scene.py` 加：

```python
def test_vehicle_has_real_dimensions(self):
    cfg = build_scene.build(
        trajectory=json.loads(self.traj.read_text()), code="synth",
        ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
        colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=40)
    car, moto = cfg["vehicles"]
    self.assertAlmostEqual(car["length_m"], 4.69)
    self.assertAlmostEqual(car["width_m"], 1.85)
    self.assertAlmostEqual(moto["length_m"], 1.85)
    self.assertAlmostEqual(moto["width_m"], 0.70)

def test_validate_requires_width(self):
    cfg = build_scene.build(
        trajectory=json.loads(self.traj.read_text()), code="synth",
        ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
        colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=40)
    del cfg["vehicles"][0]["width_m"]
    self.assertTrue(any("width_m" in e for e in build_scene.validate_scene(cfg)))
```

跑 `python3 -m unittest discover -s tools/tests` → FAIL → 實作 → PASS（10 tests）。

- [ ] **Step 3: 兩個既有 scene.json 補上真實尺寸**

手動更新 `scenes/test1/scene.json` 與 `scenes/tainan_yongkang/scene.json` 的 vehicles：
Car → `length_m: 4.69, width_m: 1.85`；Two_Wheeler → `length_m: 1.85, width_m: 0.70`。
（tainan_yongkang 也可用 build_scene.py 重新產生後比對。）

- [ ] **Step 4: `wrapModel` 加 scale-to-length**

`threejs/main.js` 的 `wrapModel` 改簽名為 `wrapModel(gltfScene, flip, targetLengthM)`：
在既有的 bbox 量測之後、設定 rotation 之前，**排除名稱含 `Collider` 的 mesh 與零厚度平面**
重新量一次車體 bbox，取其在 XZ 平面上沿模型車頭方向的長度 `modelLen`
（可用 `Math.hypot(size.x, size.z)` 的主軸投影；模型車頭角由 `-flip` 得到，
故沿車頭方向長度 = `|size.x·sin(-flip)| + |size.z·cos(-flip)|` 的估計即可），
再 `gltfScene.scale.setScalar(targetLengthM / modelLen)`。縮放後**重新量 bbox** 做置中與貼地
（現有置中邏輯必須在縮放後執行，否則偏移量錯誤）。

呼叫端傳 `st.vehicle.length_m`；`boxFallback` 也改用 `length_m`/`width_m` 建幾何。

- [ ] **Step 5: 驗證**

```
node .../scratchpad/smoke_test.mjs <repo> "/threejs/index.html?scene=test1" .../t1_smoke.png 8000
node .../scratchpad/frame_shots.mjs <repo> "/threejs/index.html?scene=test1" .../t1 25,32
```
要求：無 console error、colliders 皆 pivot=true nan=false；截圖中汽車長度應明顯接近路寬比例（約 4.7 m），機車比修正前大。附截圖判讀說明。

- [ ] **Step 6: Commit**

---

### Task 2: `threejs/lib/path.js` — 路徑弧長參數化與速度剖面

**Files:** 建立 `threejs/lib/path.js`、`threejs/lib/tests/path.test.js`

**Interfaces (Produces):**
- `buildPath(points) -> {pts:[{x,z,s}], length}` — `points` 為 `[{x,z,t}]`（t = 秒），輸出累積弧長
- `speedProfile(points) -> [{s, v}]` — 由相鄰點的 Δs/Δt 得速率，端點外插
- `sampleAt(path, s) -> {x, z, heading}` — 依弧長取位置與路徑切線方向（`atan2(dx,dz)`）
- `advance(path, profile, s0, dt, k) -> s1` — 以 `k·v(s)` 前進 dt 秒後的弧長（梯形積分，夾在 `[0, length]`）
- `speedAt(profile, s, k) -> number`（m/s）

- [ ] **Step 1: 測試先行** `threejs/lib/tests/path.test.js`

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPath, speedProfile, sampleAt, advance, speedAt } from '../path.js';

// 沿 +Z 直線，等速 10 m/s，每 0.1 秒一點
const straight = Array.from({ length: 11 }, (_, i) => ({ x: 0, z: i, t: i * 0.1 }));

test('buildPath: 累積弧長與總長', () => {
  const p = buildPath(straight);
  assert.equal(p.pts.length, 11);
  assert.ok(Math.abs(p.length - 10) < 1e-9);
  assert.ok(Math.abs(p.pts[5].s - 5) < 1e-9);
});

test('sampleAt: 位置內插與切線方向', () => {
  const p = buildPath(straight);
  const a = sampleAt(p, 2.5);
  assert.ok(Math.abs(a.x) < 1e-9 && Math.abs(a.z - 2.5) < 1e-9);
  assert.ok(Math.abs(a.heading) < 1e-9);            // 朝 +Z ⇒ heading 0
  const start = sampleAt(p, -5), end = sampleAt(p, 999);
  assert.ok(Math.abs(start.z - 0) < 1e-9, '超出範圍夾在起點');
  assert.ok(Math.abs(end.z - 10) < 1e-9, '超出範圍夾在終點');
});

test('speedProfile + speedAt: 還原 10 m/s', () => {
  const prof = speedProfile(straight);
  assert.ok(Math.abs(speedAt(prof, 5, 1) - 10) < 1e-6);
  assert.ok(Math.abs(speedAt(prof, 5, 0.5) - 5) < 1e-6, 'k 線性縮放');
});

test('advance: k=1 一秒走 10 m；k=0.5 走 5 m', () => {
  const p = buildPath(straight), prof = speedProfile(straight);
  assert.ok(Math.abs(advance(p, prof, 0, 1, 1) - 10) < 1e-3);
  assert.ok(Math.abs(advance(p, prof, 0, 1, 0.5) - 5) < 1e-3);
});

test('advance: 變速剖面—慢段耗時較長', () => {
  // 前半 10 m/s、後半 2 m/s
  const pts = [];
  let z = 0, t = 0;
  for (let i = 0; i < 5; i++) { pts.push({ x: 0, z, t }); z += 1; t += 0.1; }
  for (let i = 0; i < 6; i++) { pts.push({ x: 0, z, t }); z += 1; t += 0.5; }
  const p = buildPath(pts), prof = speedProfile(pts);
  const s1 = advance(p, prof, 0, 1, 1);
  assert.ok(s1 > 5 && s1 < 10, `一秒應跨過快段進入慢段，實得 ${s1}`);
});

test('轉彎路徑: heading 隨切線變化', () => {
  const pts = [{x:0,z:0,t:0},{x:0,z:1,t:0.1},{x:1,z:2,t:0.2},{x:2,z:2,t:0.3}];
  const p = buildPath(pts);
  const h0 = sampleAt(p, 0.5).heading, h1 = sampleAt(p, p.length - 0.1).heading;
  assert.ok(Math.abs(h0) < 1e-6, '起段朝 +Z');
  assert.ok(Math.abs(h1 - Math.PI / 2) < 0.2, '末段朝 +X');
});
```

- [ ] **Step 2: RED → 實作 `path.js` → GREEN**（`node --test threejs/lib/tests/*.test.js`）
- [ ] **Step 3: Commit**

---

### Task 3: `threejs/lib/obb.js` — SAT 碰撞偵測與最短距離

**Files:** 建立 `threejs/lib/obb.js`、`threejs/lib/tests/obb.test.js`

**Interfaces (Produces):**
- `makeOBB(x, z, heading, length, width) -> {cx, cz, h, hl, hw}`（hl/hw = 半長/半寬）
- `corners(obb) -> [{x,z} ×4]`
- `overlap(a, b) -> null | {depth, nx, nz, contactX, contactZ}` — 無重疊回 null；有重疊回最小穿透深度、該分離軸的單位法向（由 a 指向 b 為正）、接觸點（重疊區角點的平均）
- `gap(a, b) -> number` — 兩矩形最短距離（重疊時回 0）

- [ ] **Step 1: 測試先行** `threejs/lib/tests/obb.test.js`

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { makeOBB, overlap, gap, corners } from '../obb.js';

const car = (x, z, h) => makeOBB(x, z, h, 4.69, 1.85);

test('corners: 未旋轉時四角正確', () => {
  const c = corners(makeOBB(0, 0, 0, 4, 2));
  const xs = c.map(p => +p.x.toFixed(6)), zs = c.map(p => +p.z.toFixed(6));
  assert.deepEqual([...new Set(xs)].sort((a,b)=>a-b), [-1, 1]);
  assert.deepEqual([...new Set(zs)].sort((a,b)=>a-b), [-2, 2]);
});

test('overlap: 明顯分離回 null，gap 為正且合理', () => {
  const a = car(0, 0, 0), b = car(10, 0, 0);
  assert.equal(overlap(a, b), null);
  assert.ok(Math.abs(gap(a, b) - (10 - 1.85)) < 1e-6, '沿 x 分離：中心距 − 兩個半寬');
});

test('overlap: 同位置必重疊', () => {
  const r = overlap(car(0, 0, 0), car(0, 0, 0));
  assert.ok(r && r.depth > 0);
  assert.equal(gap(car(0,0,0), car(0,0,0)), 0);
});

test('overlap: 沿 x 輕微重疊 → 法向沿 x、深度正確', () => {
  const a = car(0, 0, 0), b = car(1.8, 0, 0);   // 兩個半寬和 = 1.85
  const r = overlap(a, b);
  assert.ok(r, '應重疊');
  assert.ok(Math.abs(Math.abs(r.nx) - 1) < 1e-6 && Math.abs(r.nz) < 1e-6, '法向沿 x');
  assert.ok(Math.abs(r.depth - 0.05) < 1e-6, `深度應 0.05，實得 ${r.depth}`);
});

test('overlap: 旋轉 90 度的 T 字相接', () => {
  const a = car(0, 0, 0);                 // 沿 z 長
  const b = car(0, 2.5, Math.PI / 2);     // 沿 x 長，擺在前方
  assert.ok(overlap(a, b), 'T 骨碰撞應偵測到');
  assert.equal(gap(a, b), 0);
});

test('gap: 對角分離的最短距離為角對角', () => {
  const a = makeOBB(0, 0, 0, 2, 2), b = makeOBB(4, 4, 0, 2, 2);
  // a 角 (1,1)、b 角 (3,3) → 距離 = sqrt(8)
  assert.ok(Math.abs(gap(a, b) - Math.sqrt(8)) < 1e-6);
});

test('overlap 法向方向：由 a 指向 b', () => {
  const r = overlap(car(0, 0, 0), car(1.8, 0, 0));
  assert.ok(r.nx > 0, 'b 在 a 的 +x 側，法向 x 分量應為正');
});
```

- [ ] **Step 2: RED → 實作（SAT 4 軸；`gap` 用點到線段距離取最小） → GREEN**
- [ ] **Step 3: Commit**

---

### Task 4: `physics.js` 改造 — 真實接觸點、完整力臂、比例衰減

**Files:** 改 `threejs/lib/physics.js`、`threejs/lib/tests/physics.test.js`

**Interfaces (Produces):**
- `collisionImpulse({a, b, contact, normal, restitution}) -> {aAfter:{vx,vz,omega}, bAfter:{...}, j}`
  其中 `a`/`b` 為 `{x, z, heading, vx, vz, mass_kg, length_m}`；`contact` 為 `{x,z}`；`normal` 為 `{nx,nz}`
- 力臂 `r = contact − 車輛中心`（完整 2D 向量，不再投影到前向軸、不再 clamp）
- `frictionSlide` 的 `omega` 改為**與線速度同比例衰減**：`omega(t) = omega0 · (speed(t) / speed0)`

- [ ] **Step 1: 測試（先紅）** — 取代舊的 `spinFromImpulse` 測試，新增：

```js
test('collisionImpulse: 動量守恆', () => {
  const a = { x: 0, z: -1, heading: 0, vx: 0, vz: 10, mass_kg: 1500, length_m: 4.69 };
  const b = { x: 0, z: 1, heading: 0, vx: 0, vz: 0, mass_kg: 200, length_m: 1.85 };
  const r = collisionImpulse({ a, b, contact: { x: 0, z: 0 }, normal: { nx: 0, nz: 1 }, restitution: 0.15 });
  const p0 = 1500 * 10 + 200 * 0;
  const p1 = 1500 * r.aAfter.vz + 200 * r.bAfter.vz;
  assert.ok(Math.abs(p1 - p0) < 1e-6, `動量應守恆: ${p0} vs ${p1}`);
});

test('collisionImpulse: 正撞且接觸點在質心連線上 → 無自旋', () => {
  const a = { x: 0, z: -1, heading: 0, vx: 0, vz: 10, mass_kg: 1500, length_m: 4.69 };
  const b = { x: 0, z: 1, heading: 0, vx: 0, vz: 0, mass_kg: 200, length_m: 1.85 };
  const r = collisionImpulse({ a, b, contact: { x: 0, z: 0 }, normal: { nx: 0, nz: 1 }, restitution: 0.15 });
  assert.ok(Math.abs(r.aAfter.omega) < 1e-9 && Math.abs(r.bAfter.omega) < 1e-9);
});

test('collisionImpulse: 偏心正面撞會產生自旋（舊模型恆為 0 的情形）', () => {
  // 兩車都朝 +Z，接觸點偏 +x 側 0.6 m —— 舊的「力臂只取前向軸投影」在此恆為 0
  const a = { x: 0, z: -1, heading: 0, vx: 0, vz: 10, mass_kg: 1500, length_m: 4.69 };
  const b = { x: 0, z: 1, heading: 0, vx: 0, vz: 0, mass_kg: 200, length_m: 1.85 };
  const r = collisionImpulse({ a, b, contact: { x: 0.6, z: 0 }, normal: { nx: 0, nz: 1 }, restitution: 0.15 });
  assert.ok(Math.abs(r.bAfter.omega) > 1e-3, `偏心撞應有自旋，實得 ${r.bAfter.omega}`);
  assert.ok(r.aAfter.omega * r.bAfter.omega < 0, '兩車自旋方向相反（作用力與反作用力）');
});

test('frictionSlide: omega 與速度同比例衰減，且同時歸零', () => {
  const wps = frictionSlide({ x0: 0, z0: 0, vx: 0, vz: 10, heading0: 0, omega0: 2,
                              startFrame: 0, endFrame: 120, mu: 0.7, fps: 30, step: 1 });
  const headings = wps.map(w => w[3]);
  const deltas = [];
  for (let i = 1; i < headings.length; i++) deltas.push(Math.abs(headings[i] - headings[i - 1]));
  const firstNonZero = deltas.findIndex(d => d > 1e-9);
  assert.ok(firstNonZero >= 0, '應有轉動');
  assert.ok(deltas[deltas.length - 1] <= deltas[firstNonZero] + 1e-9, '轉速應遞減');
  assert.ok(deltas[deltas.length - 1] < 1e-6, '末端應停止轉動');
});
```

- [ ] **Step 2: RED → 實作 → GREEN**。`applyCollision` 若已無呼叫者可移除；`spinFromImpulse` 由 `collisionImpulse` 取代（一併刪除舊測試中僅測舊介面者，於報告中列出刪了哪些、為何）。
- [ ] **Step 3: Commit**

---

### Task 5: `threejs/lib/simulate.js` — 前向模擬主迴圈

**Files:** 建立 `threejs/lib/simulate.js`、`threejs/lib/tests/simulate.test.js`

**Interfaces (Produces):**
```js
simulate({ vehicles, kA, kB, dt = 1/60, maxTime = 12 }) -> {
  collided: boolean,
  impactTime: number|null,          // 秒
  contact: {x,z}|null,
  minGap: number,                   // 全程最小間距（碰撞時為 0）
  minGapTime: number,
  tracks: [ {samples:[{t,x,z,heading}]}, ... ]   // 每台車完整時間序列
}
```
`vehicles` 為兩台，各含 `{path, profile, length_m, width_m, mass_kg}`。
碰撞後改為自由體：速度由衝量給定，之後每步套摩擦減速與比例自旋衰減，位置直接積分（脫離路徑）。
撞擊時刻以「前一步無重疊、本步重疊」二分細化至 `dt/16`。

- [ ] **Step 1: 測試先行** `threejs/lib/tests/simulate.test.js`

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { simulate } from '../simulate.js';
import { buildPath, speedProfile } from '../path.js';

function veh(points, length_m, width_m, mass_kg) {
  return { path: buildPath(points), profile: speedProfile(points), length_m, width_m, mass_kg };
}
// 汽車沿 +Z 穿越原點；機車沿 +X 穿越原點；等速 10 m/s，同時抵達 → 必撞
const carPts  = Array.from({ length: 41 }, (_, i) => ({ x: 0, z: -20 + i, t: i * 0.1 }));
const motoPts = Array.from({ length: 41 }, (_, i) => ({ x: -20 + i, z: 0, t: i * 0.1 }));

test('等速同時抵達 → 偵測到碰撞，撞擊點在路口附近', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 1, kB: 1 });
  assert.equal(r.collided, true);
  assert.ok(r.impactTime > 0 && r.impactTime < 12);
  assert.ok(Math.hypot(r.contact.x, r.contact.z) < 4, `接觸點應在路口附近，實得 ${JSON.stringify(r.contact)}`);
  assert.equal(r.minGap, 0);
});

test('汽車大幅放慢 → 不再碰撞，回報正的最小間距', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 0.35, kB: 1 });
  assert.equal(r.collided, false);
  assert.equal(r.impactTime, null);
  assert.ok(r.minGap > 0.5, `應明顯錯開，實得 ${r.minGap}`);
  assert.ok(r.minGapTime > 0);
});

test('未碰撞時兩車都走完各自路徑', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 0.35, kB: 1 });
  const last = r.tracks[1].samples.at(-1);
  assert.ok(last.x > 15, `機車應走到路徑末端，實得 x=${last.x}`);
});

test('碰撞後兩車脫離原路徑（自由體）', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 1, kB: 1 });
  const moto = r.tracks[1].samples.filter(s => s.t > r.impactTime + 0.3);
  assert.ok(moto.some(s => Math.abs(s.z) > 0.3), '機車碰後應被推離原本 z≈0 的直線');
});

test('輸出樣本時間單調遞增且無 NaN', () => {
  const r = simulate({ vehicles: [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)],
                       kA: 1, kB: 1 });
  for (const trk of r.tracks) {
    for (let i = 1; i < trk.samples.length; i++) assert.ok(trk.samples[i].t > trk.samples[i-1].t);
    assert.ok(trk.samples.every(s => Number.isFinite(s.x) && Number.isFinite(s.z) && Number.isFinite(s.heading)));
  }
});
```

- [ ] **Step 2: RED → 實作 → GREEN**
- [ ] **Step 3: Commit**

---

### Task 6: `threejs/lib/solve.js` — 臨界速度求解

**Files:** 建立 `threejs/lib/solve.js`、`threejs/lib/tests/solve.test.js`

**Interfaces (Produces):**
```js
criticalScale({ vehicles, which, otherK = 1, kMin = 0.2, kMax = 1.5, steps = 40, tol = 0.005 })
  -> { monotonic: boolean, criticalK: number|null, band: [number, number]|null, note: string }
```
- 先以 `steps` 點粗掃 `[kMin, kMax]` 判斷撞／不撞的分佈
- 單調（只有一次由撞轉不撞）→ 二分至 `tol` → `criticalK`
- 非單調（多段交錯）→ `monotonic:false`，回報最寬的「安全區間」`band` 與說明，不硬給單一數字

- [ ] **Step 1: 測試先行**（沿用 Task 5 的路徑 fixture）

```js
test('criticalScale: 求出臨界值，其上下 ±tol 分別為撞/不撞', () => {
  const vehicles = [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)];
  const r = criticalScale({ vehicles, which: 0 });
  assert.equal(r.monotonic, true);
  assert.ok(r.criticalK > 0.2 && r.criticalK < 1.5);
  assert.equal(simulate({ vehicles, kA: r.criticalK + 0.02, kB: 1 }).collided, true);
  assert.equal(simulate({ vehicles, kA: r.criticalK - 0.02, kB: 1 }).collided, false);
});

test('criticalScale: 兩台各自求解互不影響', () => {
  const vehicles = [veh(carPts, 4.69, 1.85, 1500), veh(motoPts, 1.85, 0.7, 200)];
  const a = criticalScale({ vehicles, which: 0 });
  const b = criticalScale({ vehicles, which: 1 });
  assert.ok(a.criticalK != null && b.criticalK != null);
});
```

- [ ] **Step 2: RED → 實作 → GREEN**
- [ ] **Step 3: Commit**

---

### Task 7: `main.js` 接線 — 模擬驅動播放、結論文字、間距標註

**Files:** 改 `threejs/main.js`、`threejs/index.html`、`threejs/lib/waypoints.js`（輸出路徑與剖面）

- [ ] **Step 1: `waypoints.js` 增加 `buildPaths(trajectory, cfg)`**
  回傳每台 collider 的 `{vehicle, points:[{x,z,t}]}`（t 由 `frame_index / trajectory.meta.fps` 得），
  extras 維持現行 waypoint 行為不變。原 `buildPreWaypoints` 保留給 extras 用。

- [ ] **Step 2: `main.js` 改用 `simulate()`**
  - 車速滑桿 → `k = 目標速率 / 原始參考速率`（參考速率取碰撞前最後 0.5 秒的平均速率）
  - 模擬結果的 `tracks[i].samples` 轉成 waypoint 陣列餵給既有的 `getState` 播放
  - 動畫總長依模擬結果的時間跨度換算幀數（不再固定 89）
  - 碰撞紅環改用 `result.contact` 與 `impactTime` 對應的幀

- [ ] **Step 3: 結論面板**
  在 `#speed-panel` 下方新增 `#verdict`，依模擬結果顯示：
  - 碰撞：`碰撞於 t=2.41 s · 相對速度 38.2 km/h`
  - 未碰撞：`未發生碰撞 · 最近距離 1.24 m（t = 2.40 s）`
  另加一顆「求安全車速」按鈕，呼叫 `solveSafeSpeeds` 對兩台各求一次。
  **注意**：交會型事故沒有單一門檻——夠慢會在對方抵達前通過、夠快會在對方離開後通過，
  安全解是「區間集合」。顯示格式：
  `汽車 ≤ 15.9 km/h 或 ≥ 25.0 km/h 可避免（實際 20）`
  （`slowerK`/`fasterK` × 該車實際車速換算成 km/h；為 null 時只顯示存在的那側，
  `transitions` 為空時顯示 `note`。）

- [ ] **Step 4: 最近距離標註線**
  未碰撞時，在 `minGapTime` 對應的幀，於兩車最近點之間畫一條線 + 文字標距離（`THREE.Line` + sprite 或 HTML 疊層皆可，選簡單者）。僅在該幀前後數幀顯示。

- [ ] **Step 5: 驗證**
  - `?scene=test1` 預設車速 → 仍發生碰撞，碰撞位置與重構前相近（附兩張截圖比較）
  - 汽車滑桿調到最低 → 顯示未碰撞與最近距離，兩車各自走完
  - 「求臨界速度」給出兩個數字，且用滑桿實際驗證該數字上下的行為相符
  - `?scene=tainan_yongkang` 不得報錯
  - 全部 smoke 無 console error

- [ ] **Step 6: Commit**

---

### Task 8: 回歸與文件收尾

- [ ] **Step 1:** `node --test threejs/lib/tests/*.test.js` 與 `python3 -m unittest discover -s tools/tests` 全綠，於報告列出總數
- [ ] **Step 2:** 兩個場景 smoke + 逐幀截圖，確認無 NaN、無 console error
- [ ] **Step 3:** 更新 `docs/todonext.md`（主線新增「碰撞模擬重構」並勾選）、`CLAUDE.md` 的物理公式段落改指向新模組與新公式
- [ ] **Step 4:** Commit + `git push origin main`

---

## Self-Review 記錄

- Spec 覆蓋：路徑/速度分離(T2)、OBB 偵測(T3)、真實接觸點與完整力臂(T4)、前向模擬(T5)、臨界速度(T6)、UI 與間距標註(T7)、尺寸正確性(T1)、回歸(T8)
- 型別一致：`{x,z,heading}`、`{nx,nz}`、`k` 縮放係數貫穿 T2–T7
- 風險：T7 動畫時間軸不再固定 89 幀，`frame_shots.mjs` 的既有幀號比較會失去意義 → T7 驗證改以「碰撞前/後相對位置」與截圖判讀為準，並在報告中說明
