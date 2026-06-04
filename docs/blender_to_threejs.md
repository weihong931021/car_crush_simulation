# Blender → Three.js 遷移指南（碰撞重建物理）

> Claude + Codex 共同討論整理，針對行車事故 3D 重建的 journalism/legal 用途

---

## 物理引擎選擇

**結論：用 Manual（手動物理），不要用引擎**

| 選項 | 評估 |
|---|---|
| **Manual（推薦）** | 物理公式已外部確立（衝量、角動量、摩擦減速），直接生成 position/quaternion 軌跡。每幀可稽核，適合法庭用途，bundle 零負擔。|
| **Rapier.js** | 若需要模擬才用。`@dimforge/rapier3d-deterministic` 版本支援跨平台重現，但有 WASM 初始化開銷。|
| **Cannon-ES** | `cannon-es@0.20.0`，仍維護但較老，適合原型，不適合鑑識用途。|
| **Ammo.js** | Bullet 2.82 Emscripten 移植，9 年未更新，API 像 C++，不推薦。|

**核心原因**：物理引擎是迭代求解的，你的案子需要的是**已知重建結果的確定性重現**，不是模擬。Manual 最適合。

---

## 物理公式（與 Blender 版本一致）

```js
// 碰撞後線性減速
const v1 = v0.clone().add(impulse.clone().multiplyScalar(1 / mass));
const a = mu * 9.80665;           // 摩擦加速度，mu ≈ 0.7
const tStop = v1.length() / a;

// Y 軸旋轉衝量（斜角碰撞）
const deltaL = momentArm.clone().cross(impulse);
const I = mass * vehicleLength * vehicleLength / 12;  // 1/12 × m × L²
const deltaOmegaY = deltaL.y / I;
```

---

## 關鍵幀動畫翻譯（Blender fcurve → Three.js AnimationClip）

```js
function buildVehicleClip(vehicleId, totalFrames, fps, sample) {
  const times = [], pos = [], quat = [];
  const yAxis = new THREE.Vector3(0, 1, 0);

  for (let f = 0; f <= totalFrames; f++) {
    const t = f / fps;
    const s = sample(t); // { x, z, yawRad }
    const q = new THREE.Quaternion().setFromAxisAngle(yAxis, s.yawRad);

    times.push(t);
    pos.push(s.x, 0, s.z);
    quat.push(q.x, q.y, q.z, q.w);
  }

  return new THREE.AnimationClip(vehicleId, totalFrames / fps, [
    new THREE.VectorKeyframeTrack('.position', times, pos, THREE.InterpolateLinear),
    new THREE.QuaternionKeyframeTrack('.quaternion', times, quat, THREE.InterpolateLinear),
  ]);
}
```

**Blender → Three.js 關鍵幀對照**：

| Blender | Three.js |
|---|---|
| 接近段 LINEAR | `InterpolateLinear` |
| 衝量段 2-3 幀急劇 | 在 `tc`, `tc+1/fps`, `tc+2/fps` 各放一個 key |
| 摩擦減速漸近停止 | 多個 key 接近 0，仍用 `InterpolateLinear` |
| `action.layers[0].strips[0].channelbag` | `AnimationClip.tracks` |

> **重要**：用 `mixer.setTime(frame / fps)` 驅動，不要用 `clock.getDelta()`，確保幀精確輸出。

---

## GLB 車輛模型載入（對應 Blender 的 QUATERNION 問題）

```js
async function loadVehicle(url, targetLengthM, forwardYawOffset = 0, zUpFix = false) {
  const gltf = await new GLTFLoader().loadAsync(url);

  const vehicle = new THREE.Group();  // 動畫根（forensic root）
  const visual = new THREE.Group();   // 視覺正規化層
  visual.add(gltf.scene);
  vehicle.add(visual);

  gltf.scene.traverse((o) => {
    if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; }
  });

  if (zUpFix) visual.rotation.x = -Math.PI / 2;  // 若模型匯入後側躺才加
  visual.rotation.y += forwardYawOffset;           // 依車頭朝向調整

  visual.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(visual);
  const size = box.getSize(new THREE.Vector3());
  const modelLength = Math.max(size.x, size.z);
  visual.scale.setScalar(targetLengthM / modelLength);

  return vehicle;
}
```

**Sketchfab 匯入常見坑**：

- 嵌套 `Sketchfab_model` / `RootNode` group（不要直接操作 mesh）
- 車頭方向：各模型不同，可能是 `+X`、`-Z`、`+Z`，需逐一檢查
- Draco 壓縮：需掛 `DRACOLoader`，否則靜默 stall
- 大量 PBR 材質：載入慢，考慮降低 texture 解析度

```js
// Draco 必裝
const dracoLoader = new DRACOLoader();
dracoLoader.setDecoderPath('/draco/');
gltfLoader.setDRACOLoader(dracoLoader);
```

---

## 座標系轉換（Blender Z-up → Three.js Y-up）

```
Blender (x, y, z) → Three.js (x, z, -y)
```

**衛星圖 pixel → Three.js 世界座標**：

```js
// sat_test1.png: 1676×1148 px, px_per_meter = 34.41
const worldX = (satX - 838) / 34.41;   // 838 = 1676/2
const worldZ = -(satY - 574) / 34.41;  // 574 = 1148/2
```

**衛星圖地板設定**：

```js
const plane = new THREE.Mesh(
  new THREE.PlaneGeometry(48.71, 33.36),  // 1676/34.41, 1148/34.41
  new THREE.MeshBasicMaterial({ map: satTexture })
);
plane.rotation.x = -Math.PI / 2;
```

---

## 影片輸出

```js
async function record(renderer, scene, camera, mixers, durationSec, fps = 30) {
  const canvas = renderer.domElement;
  const stream = canvas.captureStream(0);
  const track = stream.getVideoTracks()[0];

  const mime = [
    'video/webm;codecs=vp9',
    'video/webm;codecs=vp8',
    'video/mp4;codecs=avc1.42E01E'
  ].find(MediaRecorder.isTypeSupported);

  const chunks = [];
  const rec = new MediaRecorder(stream, {
    mimeType: mime,
    videoBitsPerSecond: 16_000_000
  });

  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const done = new Promise((resolve) => rec.onstop = resolve);

  rec.start();
  for (let f = 0; f < durationSec * fps; f++) {
    const t = f / fps;
    mixers.forEach((m) => m.setTime(t));
    renderer.render(scene, camera);
    track.requestFrame();
    await new Promise((r) => setTimeout(r, 1000 / fps));
  }
  rec.stop();
  await done;
  return new Blob(chunks, { type: mime });
}
```

**進階選項**：WebCodecs + `mp4-muxer` 可做到更精確的時間戳控制，適合法庭提交的正式影片。

---

## 已知坑清單

| 坑 | 解法 |
|---|---|
| 衛星圖 CORS 問題 | 同源服務，或確保 `Access-Control-Allow-Origin: *`；跨源紋理會讓 canvas 失去 captureStream 能力 |
| Sketchfab GLB pivot 不在 CG | 在 animated root group 下面加一層 visual group，pivot 設在接觸點 |
| Blender Z-up vs Three.js Y-up | 定義一個統一的 `blenderToThree(v)` 轉換函數，全場景一致使用 |
| `InterpolateSmooth` 會在稀疏 key 之間發明過衝 | 全程用 `InterpolateLinear` |
| 多台車時間同步 | 一個全局 frame 計數器，所有 mixer 用 `setTime(frame / fps)` |
| Draco GLB 靜默 stall | 必須設定 DRACOLoader，且 WASM 檔案要正確 host |
| 鏡頭設定 | 用正交或近正交攝影機 + 高 ambient fill，避免 filmic tone mapping 遮蓋碰撞細節 |

---

## 與目前 Blender 流程對照

| 功能 | Blender | Three.js |
|---|---|---|
| 衛星圖地板 | Material + `uv.reset()` | `PlaneGeometry` + `TextureLoader` |
| GLB 匯入 | Sketchfab MCP | `GLTFLoader` + `DRACOLoader` |
| 旋轉設定 | `rotation_mode='XYZ'` | `rotation.set()` 或 `Quaternion` |
| 關鍵幀 | layered action fcurves | `AnimationClip` + `KeyframeTrack` |
| 影片輸出 | Blender render | `canvas.captureStream` + `MediaRecorder` |
| 分享 | 本地檔案 | 瀏覽器網頁，可互動旋轉視角 |
