import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { loadScene, sceneCodeFromURL, modelFor, shouldHideNode } from './scene-loader.js';
import { buildPaths } from './lib/waypoints.js';
import { buildPath, speedProfile, smoothPoints, trimFrozenTail, rdpSimplify, refineAnchors, projectToPath, limitAcceleration, extendPoints } from './lib/path.js';
import { simulate } from './lib/simulate.js';
import { solveSafeSpeeds } from './lib/solve.js';
import { getState } from './lib/interp.js';

// ── 全域狀態 ──────────────────────────────────────────────────────────────────
const DISPLAY_FPS = 30;                 // 顯示幀率（模擬輸出重採樣到這個節奏）
const FRAME_DURATION = 1 / DISPLAY_FPS;
let CFG = null;                         // scene.json
let colliderStates = [];                // [{vehicle, simVehicle, refSpeedKmh, k, wps, pivot}]
let extraStates = [];                   // [{track_id, cls, wps, pivot}]
let simResult = null;                   // 最近一次 simulate() 的結果
let animStart = 1;
let animEnd = 2;                        // 每次 resimulate() 後更新
let pathLines = [];
let currentFrame = 1;
let isPlaying = false;
let accumulator = 0;
let lastTS = 0;
let playbackSpeed = 1;

// 對外 demo 預設不顯示任何絕對 km/h（追蹤器碰前凍結，位移回推的絕對速度不可靠，
// 「3.9 km/h」這種數字對觀眾只像壞掉）。要看的話加 ?debug=1。倍率 ×k 永遠顯示。
const SHOW_ABS_SPEED = new URLSearchParams(location.search).get('debug') === '1';

// ── Renderer / Scene / Camera ────────────────────────────────────────────────
const container = document.getElementById('canvas-container');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 500);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 3;
controls.maxDistance = 200;

// ── Debug hooks（scratchpad smoke test 依賴這些存在）─────────────────────────
window.__scene = scene;
window.__camera = camera;
window.__controls = controls;
window.__renderer = renderer;
window.__colliders = colliderStates;
window.__extras = extraStates;

renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
scene.background = new THREE.Color(0x87a5c4);
scene.fog = new THREE.Fog(0x87a5c4, 90, 260);

// 打光策略（使用者定調）：單一主光源＋清楚的影子。環境光只留提亮暗部的最低量
// （太高會把影子洗掉），太陽當絕對主角；影子解析度拉到 4096 讓輪廓乾淨。
scene.add(new THREE.HemisphereLight(0xcfe5ff, 0x8a8f7a, 0.55));
scene.add(new THREE.AmbientLight(0xffffff, 0.25));
const sun = new THREE.DirectionalLight(0xfff2dd, 3.2);
sun.position.set(24, 40, 14);
sun.castShadow = true;
sun.shadow.mapSize.set(4096, 4096);
sun.shadow.bias = -0.0001;      // 消陰影痤瘡
sun.shadow.normalBias = 0.02;   // 斜面漏光
scene.add(sun);

// ── 碰撞瞬間標記 ─────────────────────────────────────────────────────────────
let crashRing = null;
function ensureCrashRing() {
  if (crashRing) return crashRing;
  crashRing = new THREE.Mesh(
    new THREE.RingGeometry(0.95, 1.12, 48),
    new THREE.MeshBasicMaterial({ color: 0xff3333, transparent: true, side: THREE.DoubleSide }));
  crashRing.rotation.x = -Math.PI / 2;
  crashRing.visible = false;
  scene.add(crashRing);
  return crashRing;
}

// ── 最近間距標註（未碰撞時）──────────────────────────────────────────────────
let gapLine = null;
let gapLabel = null;
let gapMid = new THREE.Vector3();
function ensureGapMarker() {
  if (gapLine) return;
  gapLine = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
    new THREE.LineDashedMaterial({ color: 0x7fdc9a, dashSize: 0.3, gapSize: 0.15 }));
  gapLine.visible = false;
  scene.add(gapLine);
  gapLabel = document.createElement('div');
  Object.assign(gapLabel.style, {
    position: 'fixed', color: '#7fdc9a', background: 'rgba(0,0,0,0.65)',
    padding: '2px 8px', borderRadius: '4px', fontSize: '12px',
    fontFamily: 'monospace', pointerEvents: 'none', zIndex: '11', display: 'none',
    transform: 'translate(-50%, -140%)',
  });
  document.body.appendChild(gapLabel);
}

// 車輛 OBB 沿任意方向的半投影長（畫間距線時把中心連線縮到車身表面附近用；
// 端點是近似值，標示的距離數字本身用 simulate() 回報的真實 OBB 最短距離）。
function halfExtentAlong(vehicle, heading, dirX, dirZ) {
  const fx = Math.sin(heading), fz = Math.cos(heading);
  const px = fz, pz = -fx;
  return (vehicle.length_m / 2) * Math.abs(dirX * fx + dirZ * fz)
       + (vehicle.width_m / 2) * Math.abs(dirX * px + dirZ * pz);
}

function sampleAtTime(samples, t) {
  if (t <= samples[0].t) return samples[0];
  for (let i = 1; i < samples.length; i++) {
    if (samples[i].t >= t) {
      const a = samples[i - 1], b = samples[i];
      const u = (t - a.t) / ((b.t - a.t) || 1e-9);
      return { t, x: a.x + (b.x - a.x) * u, z: a.z + (b.z - a.z) * u, heading: b.heading };
    }
  }
  return samples[samples.length - 1];
}

function updateGapMarker(frame) {
  ensureGapMarker();
  const show = simResult && !simResult.collided && Number.isFinite(simResult.minGapTime);
  const gapFrame = show ? Math.round(simResult.minGapTime * DISPLAY_FPS) + 1 : -1;
  if (!show || Math.abs(frame - gapFrame) > 6) {
    gapLine.visible = false;
    gapLabel.style.display = 'none';
    return;
  }
  const [A, B] = colliderStates;
  const p0 = sampleAtTime(simResult.tracks[0].samples, simResult.minGapTime);
  const p1 = sampleAtTime(simResult.tracks[1].samples, simResult.minGapTime);
  let dx = p1.x - p0.x, dz = p1.z - p0.z;
  const len = Math.hypot(dx, dz) || 1;
  dx /= len; dz /= len;
  const h0 = halfExtentAlong(A.vehicle, p0.heading, dx, dz);
  const h1 = halfExtentAlong(B.vehicle, p1.heading, dx, dz);
  const e0 = new THREE.Vector3(p0.x + dx * h0, 0.4, p0.z + dz * h0);
  const e1 = new THREE.Vector3(p1.x - dx * h1, 0.4, p1.z - dz * h1);
  gapLine.geometry.setFromPoints([e0, e1]);
  gapLine.computeLineDistances();
  gapLine.visible = true;
  gapMid.copy(e0).add(e1).multiplyScalar(0.5);
  gapLabel.textContent = `${simResult.minGap.toFixed(2)} m`;
  gapLabel.style.display = 'block';
  positionGapLabel();
}

function positionGapLabel() {
  if (!gapLabel || gapLabel.style.display === 'none') return;
  const v = gapMid.clone().project(camera);
  gapLabel.style.left = `${(v.x * 0.5 + 0.5) * window.innerWidth}px`;
  gapLabel.style.top = `${(-v.y * 0.5 + 0.5) * window.innerHeight}px`;
}

// ── 錯誤 overlay（scene 包壞掉時唯一的出口）─────────────────────────────────
function showError(msg) {
  const div = document.createElement('div');
  Object.assign(div.style, {
    position: 'fixed', inset: '0', display: 'flex', alignItems: 'center',
    justifyContent: 'center', background: 'rgba(0,0,0,0.85)', color: '#ff6666',
    fontSize: '16px', zIndex: '30', padding: '24px', textAlign: 'center',
  });
  div.textContent = `場景載入失敗：${msg}`;
  document.body.appendChild(div);
}

// ── 模型載入（同一 GLB 只載一次，複用 clone）────────────────────────────────
const gltfLoader = new GLTFLoader();
const modelCache = new Map();
function loadModel(file) {
  if (!modelCache.has(file)) {
    modelCache.set(file, new Promise((resolve, reject) => {
      gltfLoader.load(`models/${file}`, g => resolve(g.scene), undefined, reject);
    }));
  }
  return modelCache.get(file).then(base => base.clone(true));
}

// 排除 Collider 命名 mesh 與零厚度平面（如 moto.glb 的地面參考片 Object_4），
// 量測「車體」本身的世界座標 bbox；沒有殘留該類 mesh 就退回整個物件的 bbox。
//
// 呼叫前必須 updateMatrixWorld(true)：Box3.setFromObject()/expandByObject() 內部用
// child.updateWorldMatrix(false, false)（updateParents=false），只會沿用「快取」的
// parent matrixWorld。wrapModel 在呼叫這裡之前剛設過 gltfScene.scale，若不強制刷新，
// 量到的還是縮放前的舊 matrixWorld——回傳的 box 完全沒反映新 scale。
function measureBodyBox(gltfScene) {
  gltfScene.updateMatrixWorld(true);
  const box = new THREE.Box3();
  const tmp = new THREE.Box3();
  const size = new THREE.Vector3();
  let found = false;
  gltfScene.traverse(child => {
    if (!child.isMesh || !child.geometry) return;
    if (/collider/i.test(child.name)) return;
    tmp.setFromObject(child);
    tmp.getSize(size);
    if (size.y < 0.01) return; // 零厚度平面
    box.union(tmp);
    found = true;
  });
  return found ? box : new THREE.Box3().setFromObject(gltfScene);
}

// 排除 collider/零厚度平面，把每個 body mesh 的 8 個 local bbox 角點轉到 gltfScene
// 座標系後逐一丟給 callback。前提：呼叫時 gltfScene 尚未套用任何 rotation/scale/position
// （矩陣為單位矩陣），因此 child.matrixWorld 就等於「該 mesh 在 gltfScene 座標系底下」的
// 變換，角點轉換後即為 gltfScene-local 座標，不必再手動反乘 gltfScene 的逆矩陣。
function forEachBodyMeshCorners(gltfScene, callback) {
  gltfScene.updateMatrixWorld(true);
  const corner = new THREE.Vector3();
  gltfScene.traverse(child => {
    if (!child.isMesh || !child.geometry) return;
    if (/collider/i.test(child.name)) return;
    let bb = child.geometry.boundingBox;
    if (!bb) {
      child.geometry.computeBoundingBox();
      bb = child.geometry.boundingBox;
    }
    const corners = [];
    let minY = Infinity, maxY = -Infinity;
    for (let i = 0; i < 8; i++) {
      corner.set(
        (i & 1) ? bb.max.x : bb.min.x,
        (i & 2) ? bb.max.y : bb.min.y,
        (i & 4) ? bb.max.z : bb.min.z,
      ).applyMatrix4(child.matrixWorld);
      corners.push(corner.clone());
      if (corner.y < minY) minY = corner.y;
      if (corner.y > maxY) maxY = corner.y;
    }
    if (maxY - minY < 0.01) return; // 零厚度平面（如 moto.glb 的地面參考片）
    callback(corners);
  });
}

// 車體沿任意軸（單位向量 axisX/axisZ，僅用 XZ 平面分量）的精確投影長度
// = max(projection) − min(projection)，取代軸對齊 bbox 對角線估計
// （後者在非 0/90° 朝向時有 W·sin(2θ) 量級的系統誤差，量到的長度會偏短）。
function measureBodyExtentAlongAxis(gltfScene, axisX, axisZ) {
  let min = Infinity, max = -Infinity;
  forEachBodyMeshCorners(gltfScene, corners => {
    for (const c of corners) {
      const proj = c.x * axisX + c.z * axisZ;
      if (proj < min) min = proj;
      if (proj > max) max = proj;
    }
  });
  return max > min ? max - min : 0;
}

function wrapModel(gltfScene, flip, targetLengthM, hideNames = []) {
  // 模型自帶的參考幾何（地面圓片等）依 registry.json 的 hide 清單隱藏，比對是**精確名稱**
  // （前綴語意會誤殺 Object_41/43/… 這類同前綴的真實零件，見 scene-loader.shouldHideNode）。
  // 不限定 isMesh：hide 可以列空節點（如 moto.glb 的 floor_0），visible=false 會連同
  // 後代一起不繪製，正好對應「隱藏這團參考幾何」。用 visible 而非拆除，維持模型檔原樣。
  // 唯一禁區是 gltfScene 自己——它是整個模型的根（moto.glb 是 MotoCollider），
  // 一旦被列進 hide 就是整台車消失。
  gltfScene.traverse(child => {
    if (child === gltfScene) return;
    if (shouldHideNode(child.name, hideNames)) child.visible = false;
  });
  const pivot = new THREE.Group();

  // 縮放前（此時 gltfScene 的 rotation/position/scale 皆為初始值，矩陣為單位矩陣）：
  // 沿車頭方向（角度 = -flip）對車體 8 角點做精確投影量測，換算成等比縮放係數
  // （scale-to-length）。順序是關鍵——縮放/旋轉/位移一旦套用，corners 就不再是
  // gltfScene-local 座標，量測會錯。
  //
  // targetLengthM 只允許「未提供」（== null，僅 extras 這種沒有已驗證尺寸的呼叫方
  // 會這樣做，代表刻意不縮放、用 GLB 原始比例）或「正的有限數字」（colliders 一律
  // 走這條路，scene-loader 已在載入時驗證過）。0/NaN/負數視為程式錯誤直接 throw，
  // 不要像過去那樣被 `if (targetLengthM)` 悄悄吃掉、用未縮放的原始尺寸渲染出去。
  if (targetLengthM != null) {
    if (!Number.isFinite(targetLengthM) || targetLengthM <= 0) {
      throw new Error(`wrapModel: targetLengthM 必須是正的有限數字，收到 ${targetLengthM}`);
    }
    const noseAngle = -flip;
    const noseX = Math.sin(noseAngle), noseZ = Math.cos(noseAngle);
    const modelLen = measureBodyExtentAlongAxis(gltfScene, noseX, noseZ);
    if (modelLen > 1e-6) {
      gltfScene.scale.setScalar(targetLengthM / modelLen);
    }
  }

  // 縮放後重新量 bbox 做置中與貼地（現有置中邏輯必須在縮放後執行，否則偏移量錯誤）。
  const box = measureBodyBox(gltfScene);
  const cx = (box.min.x + box.max.x) / 2;
  const cz = (box.min.z + box.max.z) / 2;
  const minY = box.min.y;
  gltfScene.rotation.y = flip;
  const cosF = Math.cos(flip), sinF = Math.sin(flip);
  gltfScene.position.set(-(cx * cosF + cz * sinF), -minY, cx * sinF - cz * cosF);
  gltfScene.traverse(child => {
    if (child.name === 'CarCollider' || child.name === 'MotoCollider') {
      if (child.material) {
        child.material = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false });
      }
    } else if (child.isMesh) {
      child.castShadow = true;
    }
  });
  pivot.add(gltfScene);
  scene.add(pivot);
  return pivot;
}

// extras（無 scene.json vehicle 記錄、沒有經驗證的 length_m/width_m）與模型載入失敗
// 時唯一的保底尺寸來源。刻意只分「二輪」與「其餘」兩種概略值，不是證據等級的資料，
// 純粹讓色塊方塊有個合理大小可畫——不要重建一份完整車種對照表（那份表已隨 Fix 3
// 刪除，尺寸真相只有 scene.json 的 length_m/width_m 一份，見 scene-loader.js 驗證）。
function boxFallback(cls, lengthM, widthM) {
  const isTwoWheeler = /wheel|motor/i.test(cls);
  const [defLen, defWidth] = isTwoWheeler ? [1.85, 0.70] : [4.69, 1.85];
  const length = lengthM ?? defLen;
  const width = widthM ?? defWidth;
  const height = isTwoWheeler ? 1.2 : 1.4;
  const geo = new THREE.BoxGeometry(width, height, length);
  const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: 0x999999 }));
  mesh.position.y = geo.parameters.height / 2;
  mesh.castShadow = true;
  const pivot = new THREE.Group();
  pivot.add(mesh);
  scene.add(pivot);
  return pivot;
}

// ── 模擬 → 播放資料 ──────────────────────────────────────────────────────────

// 參考車速（僅供顯示）：碰撞前最後 2 秒的位移平均速率（km/h）。
// 注意：test1 實測顯示追蹤器位置在碰撞前 0.5s 幾乎凍結（bbox 重疊+平滑假象，
// 位移回推 <1 km/h，而資料的 speed_kmh 欄位同時段為 14–21 km/h），絕對速度不可靠。
// 因此滑桿語意是「倍率 k」直接縮放實錄剖面（誠實），km/h 只是約略參考值。
function referenceSpeedKmh(points) {
  const tEnd = points[points.length - 1].t;
  const from = tEnd - 2.0;
  let dist = 0, tSpan = 0, prev = null;
  for (const p of points) {
    if (prev && p.t >= from) {
      dist += Math.hypot(p.x - prev.x, p.z - prev.z);
      tSpan += p.t - prev.t;
    }
    prev = p;
  }
  if (tSpan < 1e-6) return 0;
  return (dist / tSpan) * 3.6;
}

// simulate() 的樣本（秒）→ 播放 waypoint [frame, x, z, heading]，30fps 重採樣。
// cutT：會議決定 demo 呈現到碰撞瞬間為止——碰撞時把時間軸截在 impactTime，
// 撞後的滑行/旋轉樣本不進播放資料（物理照算，只是不播；未碰撞時 cutT=Infinity 播全程）。
function samplesToWps(samples, cutT) {
  const map = new Map();
  for (const s of samples) {
    if (s.t > cutT) break;
    const f = Math.round(s.t * DISPLAY_FPS) + 1;
    map.set(f, [f, s.x, s.z, s.heading]);
  }
  const wps = [...map.values()].sort((a, b) => a[0] - b[0]);
  if (wps.length < 2) {
    throw new Error(`模擬輸出在截斷點前樣本不足（${wps.length} 點）`);
  }
  return wps;
}

function velocityBeforeTime(samples, t) {
  // 取「跨越 t 之前」的兩個樣本做差分（避開衝量後的樣本，拿到碰前速度）
  let idx = samples.findIndex(s => s.t >= t);
  if (idx < 0) idx = samples.length - 1;
  const b = samples[Math.max(1, idx - 1)];
  const a = samples[Math.max(0, idx - 2)];
  const dt = (b.t - a.t) || 1e-9;
  return { vx: (b.x - a.x) / dt, vz: (b.z - a.z) / dt };
}

function updateVerdict() {
  const el = document.getElementById('verdict');
  if (!el || !simResult) return;
  if (simResult.collided) {
    let extra = '';
    if (SHOW_ABS_SPEED) {
      const va = velocityBeforeTime(simResult.tracks[0].samples, simResult.impactTime);
      const vb = velocityBeforeTime(simResult.tracks[1].samples, simResult.impactTime);
      const rel = Math.hypot(va.vx - vb.vx, va.vz - vb.vz) * 3.6;
      extra = ` · 相對速度 ${rel.toFixed(1)} km/h`;
    }
    el.textContent = `碰撞於 ${simResult.impactTime.toFixed(2)} s${extra}（播放至碰撞瞬間）`;
    el.style.color = '#ff9999';
  } else if (simResult.horizonReached) {
    // 保險上限截斷：兩車還沒走完路徑就停算，不能宣稱「未發生碰撞」
    el.textContent = `模擬 ${simResult.endTime.toFixed(0)} s 內未碰撞（有車輛過慢、尚未走完路徑，結論不完整）` +
      ` · 最近距離 ${simResult.minGap.toFixed(2)} m（${simResult.minGapTime.toFixed(2)} s）`;
    el.style.color = '#ffcc66';
  } else {
    el.textContent = `未發生碰撞（兩車皆已通過）· 最近距離 ${simResult.minGap.toFixed(2)} m（${simResult.minGapTime.toFixed(2)} s）`;
    el.style.color = '#7fdc9a';
  }
}

// 車速滑桿觸發：重新前向模擬（一次 ≈0.25ms，input 事件內同步跑沒問題）
function resimulate() {
  const [A, B] = colliderStates;
  if (!A?.simVehicle || !B?.simVehicle) return;
  simResult = simulate({
    vehicles: [A.simVehicle, B.simVehicle],
    kA: A.k, kB: B.k,
  });
  // 碰撞：播到撞擊瞬間（會議決定）。未碰撞：播到錯車後幾秒就夠了——模擬本身會跑到兩車
  // 都走完路徑（慢車 ×0.25 可能是上百秒），全播進時間軸只會讓觀眾拖一條長到沒意義的拉桿。
  const POST_GAP_SEC = 4;
  // 至少讓晚出現的那台車也進場（samplesToWps 要求截斷點前每台 ≥2 個樣本）
  const latestStart = Math.max(A.simVehicle.startT ?? 0, B.simVehicle.startT ?? 0);
  const cutT = simResult.collided ? simResult.impactTime
    : Math.max(latestStart + 1, Math.min(simResult.endTime, simResult.minGapTime + POST_GAP_SEC));
  colliderStates.forEach((st, i) => {
    st.wps = samplesToWps(simResult.tracks[i].samples, cutT);
  });
  animEnd = Math.max(animStart + 1, ...colliderStates.map(st => st.wps[st.wps.length - 1][0]));
  if (slider) {
    slider.min = animStart;
    slider.max = animEnd;
  }
  // 時間軸長度隨結果變：目前幀若已超出新的結尾，回到開頭重看，不要卡在（新的）最後一幀
  if (currentFrame > animEnd) currentFrame = animStart;
  window.__simResult = simResult;   // debug hook 與最新結果同步
  rebuildPathLines();
  updateVerdict();
  invalidateSolveResult();
  updateScene(currentFrame);
}

// 「求安全車速」的答案是針對按下當時的兩個倍率算的；滑桿一動就過期，必須清掉，
// 否則面板會同時顯示「目前設定下已不會碰撞」與上方的「碰撞於 …」自相矛盾。
function invalidateSolveResult() {
  const el = document.getElementById('solve-result');
  if (!el || !el.textContent) return;
  el.innerHTML = '<div style="color:#999">車速已變更，請重新按「求安全車速」</div>';
}

const PATH_COLORS = [0xffcc33, 0xff8833];
const PATH_RIBBON_WIDTH_M = 0.30;   // WebGL 的 linewidth 不生效（1px 幾乎看不見），路徑改畫成貼地色帶

// 把折線 [x,z]… 鋪成寬 w 的貼地色帶（每段一個四邊形、兩個三角形，法線朝上）。
// 幾何簡單到不需要 addons 的 Line2；轉角處相鄰四邊形直接重疊，30cm 寬肉眼看不出接縫。
function ribbonGeometry(pts, w, y) {
  const pos = [];
  const half = w / 2;
  for (let i = 1; i < pts.length; i++) {
    const [ax, az] = pts[i - 1], [bx, bz] = pts[i];
    const dx = bx - ax, dz = bz - az;
    const len = Math.hypot(dx, dz);
    if (len < 1e-6) continue;
    const nx = -dz / len * half, nz = dx / len * half;   // 左法線
    // 兩個三角形（逆時針、從上方看）：a-左, b-左, b-右 / a-左, b-右, a-右
    pos.push(ax + nx, y, az + nz,  bx + nx, y, bz + nz,  bx - nx, y, bz - nz);
    pos.push(ax + nx, y, az + nz,  bx - nx, y, bz - nz,  ax - nx, y, az - nz);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  return geo;
}

function rebuildPathLines() {
  for (const l of pathLines) {
    scene.remove(l);
    l.geometry.dispose();
    l.material.dispose();
  }
  pathLines = [];
  colliderStates.forEach((st, i) => {
    if (!st.wps) return;
    const mesh = new THREE.Mesh(
      ribbonGeometry(st.wps.map(wp => [wp[1], wp[2]]), PATH_RIBBON_WIDTH_M, 0.03),
      new THREE.MeshBasicMaterial({
        color: PATH_COLORS[i % PATH_COLORS.length], transparent: true, opacity: 0.8,
        side: THREE.DoubleSide, depthWrite: false,
      }));
    scene.add(mesh);
    pathLines.push(mesh);
  });
}

// ── 每幀更新 ─────────────────────────────────────────────────────────────────
function applyState(pivot, wps, frame, showFrom) {
  if (!pivot) return;
  pivot.visible = frame >= showFrom;
  const s = getState(wps, frame);
  pivot.position.set(s.x, 0, s.z);
  pivot.rotation.y = s.h;
}

const slider = document.getElementById('frame-slider');
const frameDisplay = document.getElementById('frame-display');

function updateScene(frame) {
  for (const st of colliderStates) {
    if (st.wps) applyState(st.pivot, st.wps, frame, st.wps[0][0]);
  }
  for (const st of extraStates) {
    applyState(st.pivot, st.wps, frame, st.wps[0][0]);
    if (st.pivot) st.pivot.visible = frame >= st.wps[0][0] && frame <= st.wps[st.wps.length - 1][0];
  }
  // 觀眾看秒數，不看幀號（幀號只是內部時間軸單位；frame 1 = 0.00 s）
  if (frameDisplay) frameDisplay.textContent = `${((frame - 1) * FRAME_DURATION).toFixed(2)} s`;
  if (slider) slider.value = `${frame}`;

  // 碰撞紅環：時間軸截在碰撞瞬間，紅環在最後幾幀淡入、停在接觸點
  if (simResult?.collided && simResult.contact) {
    const ring = ensureCrashRing();
    const impactFrame = Math.round(simResult.impactTime * DISPLAY_FPS) + 1;
    const dt = impactFrame - frame;           // 距碰撞尚餘幾幀（frame ≤ impactFrame）
    if (dt <= 6) {
      ring.position.set(simResult.contact.x, 0.06, simResult.contact.z);
      ring.scale.setScalar(1 + Math.max(0, dt) * 0.15);
      ring.material.opacity = 0.85 * (1 - Math.max(0, dt) / 7);
      ring.visible = true;
    } else {
      ring.visible = false;
    }
  } else if (crashRing) {
    crashRing.visible = false;
  }

  updateGapMarker(frame);
}

// ── UI ───────────────────────────────────────────────────────────────────────
const playBtn = document.getElementById('btn-play');
const resetBtn = document.getElementById('btn-reset');
const topdownBtn = document.getElementById('btn-topdown');
const perspBtn = document.getElementById('btn-persp');
const chaseBtn = document.getElementById('btn-chase');

let chaseMode = false;
let chaseTarget = 0;   // colliderStates 的索引；跟車鈕再按一次就換下一台

// 觀眾看得懂的車名。兩台同類（taipei 兩台都叫「汽車」）就加 A/B 後綴，否則
// 滑桿列、圖例、求解結果三處都分不出誰是誰。
function displayName(idx) {
  const st = colliderStates[idx];
  if (!st) return '—';
  const base = st.vehicle.label ?? st.vehicle.class;
  const dup = colliderStates.some((o, j) => j !== idx && (o.vehicle.label ?? o.vehicle.class) === base);
  return dup ? `${base} ${String.fromCharCode(65 + idx)}` : base;
}

function chaseLabel() {
  return `🚗 跟車：${displayName(chaseTarget)}`;
}
function updateChaseBtn() {
  if (chaseBtn) chaseBtn.textContent = chaseMode ? chaseLabel() : '🚗 跟車';
}

function setPlayLabel() {
  if (playBtn) playBtn.textContent = isPlaying ? '⏸ 暫停' : '▶ 播放';
}
function gotoFrame(f) {
  currentFrame = Math.max(animStart, Math.min(animEnd, Math.round(f)));
  updateScene(currentFrame);
}

// 「事發範圍」：兩台 collider 整段播放軌跡的 XZ 包圍盒（含車身尺寸的餘裕）。
// 鏡頭 preset 以它為準，不是以地面中心為準——地面圖多大跟事故發生在哪裡無關
// （tainan 第 1 幀汽車在畫面外、taipei 兩車卡在底部控制列後面，都是框地面中心的後果）。
function actionBounds() {
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const st of colliderStates) {
    if (!st.wps) continue;
    for (const wp of st.wps) {
      if (wp[1] < minX) minX = wp[1]; if (wp[1] > maxX) maxX = wp[1];
      if (wp[2] < minZ) minZ = wp[2]; if (wp[2] > maxZ) maxZ = wp[2];
    }
  }
  if (!Number.isFinite(minX)) {           // 還沒有模擬結果 → 退回地面
    const [w, d] = CFG.ground.size_m;
    return { cx: 0, cz: 0, w, d };
  }
  const pad = Math.max(...colliderStates.map(st => st.vehicle.length_m ?? 4.5));
  return {
    cx: (minX + maxX) / 2, cz: (minZ + maxZ) / 2,
    w: Math.max(maxX - minX + 2 * pad, 12), d: Math.max(maxZ - minZ + 2 * pad, 12),
  };
}

// 讓半徑 r 的球正好塞進視錐（考慮視窗長寬比：直式視窗受水平 fov 限制），再留 margin。
function fitDistance(r, margin = 1.15) {
  const fovV = THREE.MathUtils.degToRad(camera.fov);
  const fovH = 2 * Math.atan(Math.tan(fovV / 2) * camera.aspect);
  return (r / Math.sin(Math.min(fovV, fovH) / 2)) * margin;
}

function setTopDownView() {
  chaseMode = false;
  updateChaseBtn();
  // 頂視圖看整張地面圖（事發範圍一定在其中），依視窗長寬比 fit，不留大片藍邊
  const [w, d] = CFG.ground.size_m;
  const fovV = THREE.MathUtils.degToRad(camera.fov);
  const fovH = 2 * Math.atan(Math.tan(fovV / 2) * camera.aspect);
  const h = Math.max(d / 2 / Math.tan(fovV / 2), w / 2 / Math.tan(fovH / 2)) * 1.05;
  // 不改 camera.up：OrbitControls 建構時就把 up 抓死，之後改它不理，相機若正好落在極點
  // （正上方）就退化成原地自轉——左鍵拖曳完全沒反應。改成從正上方往南偏 0.5°：
  // 看起來仍是頂視圖、北（-z）在螢幕上方，而且拖曳能正常旋轉／傾斜。
  const tilt = THREE.MathUtils.degToRad(0.5);
  camera.position.set(0, h * Math.cos(tilt), h * Math.sin(tilt));
  controls.target.set(0, 0, 0);
  controls.update();
}
function setPersp45View() {
  chaseMode = false;
  updateChaseBtn();
  const b = actionBounds();
  const r = Math.hypot(b.w, b.d) / 2;
  const dist = fitDistance(r);
  // 從南偏一點、俯角約 50° 看向事發範圍中心
  const dir = new THREE.Vector3(-0.1, 0.78, 0.62).normalize();
  controls.target.set(b.cx, 0, b.cz);
  camera.position.copy(controls.target).addScaledVector(dir, dist);
  controls.update();
}

if (playBtn) playBtn.addEventListener('click', () => {
  // 播到底再按播放 → 從頭重播（不必先按重置）
  if (!isPlaying && currentFrame >= animEnd) gotoFrame(animStart);
  isPlaying = !isPlaying; accumulator = 0; setPlayLabel();
});
if (resetBtn) resetBtn.addEventListener('click', () => { isPlaying = false; accumulator = 0; setPlayLabel(); gotoFrame(animStart); });
if (topdownBtn) topdownBtn.addEventListener('click', setTopDownView);
if (perspBtn) perspBtn.addEventListener('click', setPersp45View);
if (chaseBtn) {
  chaseBtn.addEventListener('click', () => {
    if (chaseMode) {
      chaseTarget = (chaseTarget + 1) % Math.max(1, colliderStates.length); // 已在跟車 → 換下一台
    } else {
      chaseMode = true;
    }
    updateChaseBtn();
  });
}
if (slider) slider.addEventListener('input', () => { isPlaying = false; setPlayLabel(); gotoFrame(Number(slider.value)); });

const speedSelect = document.getElementById('playback-speed');
if (speedSelect) speedSelect.addEventListener('change', () => { playbackSpeed = Number(speedSelect.value); });

// 滑桿 = 速度剖面倍率 k（×0.25–×2.5），保留實錄的加減速特徵、只整體快慢。
// 不用絕對 km/h 當滑桿語意——位置回推的絕對速度在碰撞近端不可靠（見 referenceSpeedKmh 註解）。
function bindSpeedSlider(idx) {
  const input = document.getElementById(`collider${idx}-speed`);
  const label = document.getElementById(`collider${idx}-speed-label`);
  const nameEl = document.getElementById(`collider${idx}-name`);
  const st = colliderStates[idx];
  if (!input || !st) return;
  if (nameEl) nameEl.textContent = displayName(idx);
  input.min = '0.25';
  input.max = '2.5';
  input.step = '0.05';
  input.value = '1';
  if (label) label.textContent = '×1.00';
  input.addEventListener('input', () => {
    st.k = Number(input.value);
    if (label) label.textContent = `×${st.k.toFixed(2)}`;
    resimulate();
  });
}

function fillRefSpeeds() {
  const el = document.getElementById('ref-speeds');
  if (!el) return;
  if (!SHOW_ABS_SPEED) {
    el.textContent = '×1.00 = 實錄車速；拖動可假設「當時再快／再慢一點」';
    return;
  }
  el.textContent = '碰前 2s 位移均速（參考）：' + colliderStates
    .map((st, i) => `${displayName(i)} ${st.refSpeedKmh.toFixed(1)} km/h`)
    .join('、');
}

// solve 的 slowerK/fasterK 是相對 k=1（實錄）的邊界；面板要回答的是「相對**目前滑桿**」
// 該怎麼調，所以這裡從 safeIntervals 自己找目前 st.k 左右最近的安全邊界，
// 「目前設定下已不會碰撞」也直接看目前的 simResult，而不是 solve 在 k=1 的評估。
function formatSolveLine(idx, r) {
  const st = colliderStates[idx];
  const name = displayName(idx);
  const ref = st.refSpeedKmh;
  const kmh = k => (SHOW_ABS_SPEED ? `（≈${(k * ref).toFixed(1)} km/h）` : '');
  const k = st.k;
  const inSafe = r.safeIntervals.some(([lo, hi]) => k >= lo - 1e-9 && k <= hi + 1e-9);
  if (!simResult?.collided || inSafe) return `${name}：目前設定下已不會碰撞`;
  let slower = null, faster = null;
  for (const [lo, hi] of r.safeIntervals) {
    if (hi <= k && (slower == null || hi > slower)) slower = hi;
    if (lo >= k && (faster == null || lo < faster)) faster = lo;
  }
  const parts = [];
  if (slower != null) parts.push(`慢到 ×${slower.toFixed(2)} 以下${kmh(slower)}`);
  if (faster != null) parts.push(`快到 ×${faster.toFixed(2)} 以上${kmh(faster)}`);
  const truncated = r.horizonTruncated > 0 ? '（更慢的部分倍率因模擬視野不足未計入）' : '';
  // 觀眾版不貼 solve 的技術性 note（取樣間距、建議加大 steps…），?debug=1 才附上
  if (!parts.length) {
    return SHOW_ABS_SPEED ? `${name}：${r.note}`
      : `${name}：在 ×0.25–×2.50 範圍內單獨調它都仍會碰撞（另一台維持目前設定）${truncated}`;
  }
  return `${name} ${parts.join('，或')} 可避開${truncated}`;
}

const solveBtn = document.getElementById('btn-solve');
if (solveBtn) {
  solveBtn.addEventListener('click', () => {
    const el = document.getElementById('solve-result');
    if (!el || colliderStates.length < 2) return;
    const vehicles = [colliderStates[0].simVehicle, colliderStates[1].simVehicle];
    // 136 次前向模擬同步跑在主執行緒（慢車設定下可到 1 秒多），先把「計算中」畫出來
    // 再開算，按鈕才不會像沒反應。
    el.textContent = '計算中…';
    solveBtn.disabled = true;
    setTimeout(() => {
      try {
        // 對兩台各自求解；另一台固定在其目前滑桿設定（otherK）。
        // 搜尋範圍對齊滑桿（×0.25–×2.5），steps 按比例加密維持 Δk 解析度。
        const lines = colliderStates.map((st, i) =>
          formatSolveLine(i, solveSafeSpeeds({
            vehicles, which: i, otherK: colliderStates[1 - i].k,
            kMin: 0.25, kMax: 2.5, steps: 68,
          })));
        el.innerHTML = lines.map(t => `<div>${t}</div>`).join('');
      } finally {
        solveBtn.disabled = false;
      }
    }, 0);
  });
}

function fillLegend() {
  const legend = document.getElementById('legend');
  if (!legend) return;
  const dots = ['#4488ff', '#ff4444'];
  const pathHex = PATH_COLORS.map(c => '#' + c.toString(16).padStart(6, '0'));
  // 對外 demo 不秀 class/track id（觀眾不需要）；?debug=1 才附上
  const tech = st => (SHOW_ABS_SPEED ? ` (${st.vehicle.class} id=${st.vehicle.track_id})` : '');
  legend.innerHTML = colliderStates.map((st, i) =>
    `<div><span class="dot" style="background:${dots[i % 2]}"></span>${displayName(i)}${tech(st)}</div>`
  ).join('') +
  colliderStates.map((st, i) =>
    `<div><span class="dot" style="background:${pathHex[i % pathHex.length]}; opacity:0.8"></span>` +
    `${displayName(i)} 路徑</div>`
  ).join('');
}

// ── Resize / Render loop ─────────────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

function animate(ts) {
  requestAnimationFrame(animate);
  const delta = Math.min((ts - lastTS) / 1000, 0.2);
  lastTS = ts;
  if (isPlaying && CFG) {
    accumulator += delta * playbackSpeed;
    while (accumulator >= FRAME_DURATION) {
      accumulator -= FRAME_DURATION;
      currentFrame++;
      if (currentFrame > animEnd) {
        currentFrame = animEnd;
        isPlaying = false;
        setPlayLabel();
        break;
      }
    }
    updateScene(currentFrame);
  }
  if (chaseMode && colliderStates[chaseTarget]?.pivot) {
    const st = colliderStates[chaseTarget];
    const p = st.pivot;
    const h = p.rotation.y;
    // 跟車距離隨車身尺寸縮放：機車貼近一點、汽車拉遠一點
    const L = st.vehicle.length_m ?? 4.5;
    const dist = Math.max(5, L * 2.2);
    const height = Math.max(2.5, L * 1.1);
    const back = new THREE.Vector3(-Math.sin(h) * dist, height, -Math.cos(h) * dist);
    camera.position.lerp(p.position.clone().add(back), 0.08);
    controls.target.lerp(p.position.clone().setY(1), 0.15);
  }
  positionGapLabel();       // 相機移動時標籤要跟著投影位置
  controls.update();
  renderer.render(scene, camera);
}

// ── extras（背景車）────────────────────────────────────────────────────────────
// collider 時間軸改為真實秒數後，extras 必須用同一個時鐘，否則背景車與主車完全對不上
// 時間（舊的 1–89 壓縮幀映射已棄用）。fps 解析邏輯與 lib/waypoints.js 的
// resolveTrajectoryFps 一致：trajectory.meta.fps 優先，缺失回退 cfg.frames.fps ?? 30。
function buildExtrasRealtime(trajectory, cfg, fps, t0) {
  if (cfg.extras !== 'auto') return [];
  const [offX, offZ] = cfg.origin_offset_m;
  const colliderIds = new Set(cfg.vehicles.filter(v => v.role === 'collider').map(v => v.track_id));
  const byId = new Map();
  for (const frame of trajectory.frames) {
    for (const obj of frame.objects) {
      if (!obj.position_m || colliderIds.has(obj.tracked_id)) continue;
      if (!byId.has(obj.tracked_id)) {
        byId.set(obj.tracked_id, { track_id: obj.tracked_id, cls: obj.class, wps: [] });
      }
      const f = Math.round((frame.frame_index / fps - t0) * DISPLAY_FPS) + 1;
      byId.get(obj.tracked_id).wps.push([f, obj.position_m[0] - offX, obj.position_m[1] - offZ, null]);
    }
  }
  const dedup = wps => {
    const m = new Map();
    for (const w of wps) m.set(w[0], w);
    return [...m.values()].sort((a, b) => a[0] - b[0]);
  };
  return [...byId.values()]
    .map(e => ({ ...e, wps: dedup(e.wps) }))
    .filter(e => e.wps.length >= 2);
}

// ── Bootstrap ────────────────────────────────────────────────────────────────
const loadDiv = document.createElement('div');
Object.assign(loadDiv.style, {
  position: 'fixed', inset: '0', display: 'flex', alignItems: 'center',
  justifyContent: 'center', background: 'rgba(0,0,0,0.7)', color: '#fff',
  fontSize: '20px', zIndex: '20',
});
loadDiv.textContent = '載入場景中…';
document.body.appendChild(loadDiv);

async function boot() {
  const code = sceneCodeFromURL();
  const { cfg, trajectory, registry, basePath } = await loadScene(code);
  CFG = cfg;
  document.title = cfg.name ?? cfg.code;
  currentFrame = animStart;

  // 地面
  const satTex = new THREE.TextureLoader().load(basePath + cfg.ground.image);
  satTex.colorSpace = THREE.SRGBColorSpace;
  satTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(cfg.ground.size_m[0], cfg.ground.size_m[1]),
    new THREE.MeshLambertMaterial({ map: satTex }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.02;
  ground.receiveShadow = true;
  scene.add(ground);

  // 陰影相機範圍（依地圖大小）
  const ext = Math.max(...cfg.ground.size_m) * 0.65;
  Object.assign(sun.shadow.camera, { left: -ext, right: ext, top: ext, bottom: -ext, near: 1, far: 120 });
  sun.shadow.camera.updateProjectionMatrix();

  // 路徑 + 速度剖面（真實秒數；時間原點平移到最早的 collider 資料點）
  const rawPaths = buildPaths(trajectory, cfg);
  const t0 = Math.min(...rawPaths.map(p => p.points[0].t));
  colliderStates = rawPaths.map(p => {
    // 資料淨化管線：平滑（消偵測抖動；不錨定尾端，讓 trim 能判斷）→ 切凍結尾
    // （碰前 bbox 重疊假象）→ 沿末向外插（證據終點後車輛才不會被 advance 夾住原地罰站）。
    // 順序固定，見 lib/path.js 註解。startT = 該車第一筆證據時刻（晚出現的車不得提早出發）。
    const shifted = p.points.map(q => ({ x: q.x, z: q.z, t: q.t - t0 }));
    // 平滑（去噪）→ 切凍結尾 → RDP 錨點（直線化的幾何中心線）→ 投影（每點保留自己的 t，
    // 橫向蛇行貼回中心線；幾何與時序分離，速度剖面＝證據不被粗化）→ 縱向慣性 → 外插
    const trimmed = trimFrozenTail(smoothPoints(shifted, { anchorEnd: false }));
    // RDP 錨點 → 轉角細分（頂點角 ≤12°）→ 投影：折線幾何、逐點時序（證據）保留
    const anchors = refineAnchors(trimmed, rdpSimplify(trimmed));
    const { points } = extendPoints(limitAcceleration(projectToPath(trimmed, anchors)));
    return {
      vehicle: p.vehicle,
      simVehicle: {
        path: buildPath(points),
        profile: speedProfile(points),
        length_m: p.vehicle.length_m,
        width_m: p.vehicle.width_m,
        mass_kg: p.vehicle.mass_kg,
        startT: points[0].t,
      },
      refSpeedKmh: referenceSpeedKmh(points),
      k: 1,
      wps: null,
      pivot: null,
    };
  });

  // extras 與 collider 用同一個時鐘（見 buildExtrasRealtime 註解）
  const metaFps = trajectory.meta?.fps;
  const fps = (typeof metaFps === 'number' && Number.isFinite(metaFps) && metaFps > 0)
    ? metaFps : (cfg.frames.fps ?? 30);
  const extras = buildExtrasRealtime(trajectory, cfg, fps, t0);

  // 開場切到「第二台車出現前 LEAD_IN_SEC 秒」：test1 機車 6.3 s 才進場，前面只有汽車
  // 用 3.9 km/h 蠕行——對觀眾是空等。模擬與證據不動（時間原點仍是最早的資料點、
  // startT 照舊），只是把時間軸／拉桿的下限往後挪，前段刻意不給看。秒數顯示仍以
  // 資料原點為 0，所以開場會從 4.30 s 之類的數字起跳，這是誠實的。
  const LEAD_IN_SEC = 2;
  const latestStart = Math.max(...colliderStates.map(st => st.simVehicle.startT ?? 0));
  animStart = Math.max(1, Math.floor((latestStart - LEAD_IN_SEC) * DISPLAY_FPS) + 1);
  currentFrame = animStart;

  resimulate();

  // 相機初始位：要等 resimulate() 有了播放軌跡才知道事發範圍在哪（見 actionBounds）
  if (cfg.camera?.default === 'ortho_top') {
    setTopDownView();
  } else {
    setPersp45View();
  }

  if (slider) slider.step = 1;
  bindSpeedSlider(0);
  bindSpeedSlider(1);
  fillRefSpeeds();
  fillLegend();

  // 模型（collider 用 registry；extras 用 class fallback，失敗補 box）
  await Promise.all([
    ...colliderStates.map(async st => {
      const m = modelFor(st.vehicle, registry);
      if (!m) {
        console.warn(`車輛 track_id=${st.vehicle.track_id} class=${st.vehicle.class} 無對應模型，改用色塊`);
        st.pivot = boxFallback(st.vehicle.class, st.vehicle.length_m, st.vehicle.width_m);
        return;
      }
      try {
        st.pivot = wrapModel(await loadModel(m.file), m.flip, st.vehicle.length_m, m.hide);
      } catch (e) {
        console.error(`模型 ${m.file} 載入失敗，改用色塊`, e);
        st.pivot = boxFallback(st.vehicle.class, st.vehicle.length_m, st.vehicle.width_m);
      }
    }),
    ...extras.map(async ex => {
      const st = { ...ex, pivot: null };
      extraStates.push(st);
      const m = modelFor(ex.cls, registry);
      if (!m) {
        console.warn(`車輛 track_id=${ex.track_id} class=${ex.cls} 無對應模型，改用色塊`);
        st.pivot = boxFallback(ex.cls);
        return;
      }
      try {
        // extras 沒有 scene.json vehicle 記錄、沒有經驗證的 length_m，故不傳
        // targetLengthM——wrapModel 視為「刻意不縮放」，直接用 GLB 原始比例。
        st.pivot = wrapModel(await loadModel(m.file), m.flip, undefined, m.hide);
      } catch (e) {
        console.error(`模型 ${m.file} 載入失敗，改用色塊`, e);
        st.pivot = boxFallback(ex.cls);
      }
    }),
  ]);

  // colliderStates 在上面被整包換掉了（不是原地 mutate），debug hook 要重指才會反映新陣列
  window.__colliders = colliderStates;
  window.__extras = extraStates;
  window.__simResult = simResult;

  loadDiv.remove();
  gotoFrame(animStart);
}

setPlayLabel();
animate(0);
boot().catch(err => {
  loadDiv.remove();
  console.error(err);
  showError(err.message);
});
