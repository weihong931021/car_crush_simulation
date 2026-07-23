import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { loadScene, sceneCodeFromURL, modelFor } from './scene-loader.js';
import { buildPaths } from './lib/waypoints.js';
import { buildPath, speedProfile, smoothPoints, trimFrozenTail, decimatePoints, splineResample, limitAcceleration, extendPoints } from './lib/path.js';
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

function wrapModel(gltfScene, flip, targetLengthM) {
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
    const va = velocityBeforeTime(simResult.tracks[0].samples, simResult.impactTime);
    const vb = velocityBeforeTime(simResult.tracks[1].samples, simResult.impactTime);
    const rel = Math.hypot(va.vx - vb.vx, va.vz - vb.vz) * 3.6;
    el.textContent = `碰撞於 t=${simResult.impactTime.toFixed(2)} s · 相對速度 ${rel.toFixed(1)} km/h（播放至碰撞瞬間）`;
    el.style.color = '#ff9999';
  } else {
    el.textContent = `未發生碰撞 · 最近距離 ${simResult.minGap.toFixed(2)} m（t = ${simResult.minGapTime.toFixed(2)} s）`;
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
  const cutT = simResult.collided ? simResult.impactTime : Infinity;
  colliderStates.forEach((st, i) => {
    st.wps = samplesToWps(simResult.tracks[i].samples, cutT);
  });
  animEnd = Math.max(animStart + 1, ...colliderStates.map(st => st.wps[st.wps.length - 1][0]));
  if (slider) {
    slider.min = animStart;
    slider.max = animEnd;
  }
  if (currentFrame > animEnd) currentFrame = animEnd;
  window.__simResult = simResult;   // debug hook 與最新結果同步
  rebuildPathLines();
  updateVerdict();
  updateScene(currentFrame);
}

const PATH_COLORS = [0xffcc33, 0xff8833];

function rebuildPathLines() {
  for (const l of pathLines) {
    scene.remove(l);
    l.geometry.dispose();
    l.material.dispose();
  }
  pathLines = [];
  colliderStates.forEach((st, i) => {
    if (!st.wps) return;
    const pts = st.wps.map(wp => new THREE.Vector3(wp[1], 0.05, wp[2]));
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({ color: PATH_COLORS[i % PATH_COLORS.length], transparent: true, opacity: 0.75 }));
    scene.add(line);
    pathLines.push(line);
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
  if (frameDisplay) frameDisplay.textContent = `${frame}`;
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

function chaseLabel() {
  const st = colliderStates[chaseTarget];
  return `🚗 跟車：${st?.vehicle.label ?? st?.vehicle.class ?? '—'}`;
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
function setTopDownView() {
  chaseMode = false;
  updateChaseBtn();
  const h = Math.max(...CFG.ground.size_m) * 1.15;
  camera.position.set(0, h, 0.001);
  camera.up.set(0, 0, -1);
  controls.target.set(0, 0, 0);
  controls.update();
}
function setPersp45View() {
  chaseMode = false;
  updateChaseBtn();
  const span = Math.max(...CFG.ground.size_m);
  camera.up.set(0, 1, 0);
  camera.position.set(-span * 0.06, span * 0.57, span * 0.45);
  controls.target.set(-span * 0.06, 0, span * 0.12);
  controls.update();
}

if (playBtn) playBtn.addEventListener('click', () => { isPlaying = !isPlaying; accumulator = 0; setPlayLabel(); });
if (resetBtn) resetBtn.addEventListener('click', () => { isPlaying = false; accumulator = 0; setPlayLabel(); gotoFrame(animStart); });
if (topdownBtn) topdownBtn.addEventListener('click', setTopDownView);
if (perspBtn) perspBtn.addEventListener('click', setPersp45View);
if (chaseBtn) {
  chaseBtn.addEventListener('click', () => {
    if (chaseMode) {
      chaseTarget = (chaseTarget + 1) % Math.max(1, colliderStates.length); // 已在跟車 → 換下一台
    } else {
      chaseMode = true;
      camera.up.set(0, 1, 0);
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
  if (nameEl) nameEl.textContent = st.vehicle.label ?? st.vehicle.class;
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
  el.textContent = '碰前 2s 位移均速（參考）：' + colliderStates
    .map(st => `${st.vehicle.label ?? st.vehicle.class} ${st.refSpeedKmh.toFixed(1)} km/h`)
    .join('、');
}

function formatSolveLine(st, r) {
  const name = st.vehicle.label ?? st.vehicle.class;
  const ref = st.refSpeedKmh;
  if (!r.actualCollides) return `${name}：目前設定下已不會碰撞`;
  const parts = [];
  if (r.slowerK != null) parts.push(`×≤${r.slowerK.toFixed(2)}（≈${(r.slowerK * ref).toFixed(1)} km/h）`);
  if (r.fasterK != null) parts.push(`×≥${r.fasterK.toFixed(2)}（≈${(r.fasterK * ref).toFixed(1)} km/h）`);
  if (!parts.length) return `${name}：${r.note}`;
  return `${name} ${parts.join(' 或 ')} 可避開`;
}

const solveBtn = document.getElementById('btn-solve');
if (solveBtn) {
  solveBtn.addEventListener('click', () => {
    const el = document.getElementById('solve-result');
    if (!el || colliderStates.length < 2) return;
    const vehicles = [colliderStates[0].simVehicle, colliderStates[1].simVehicle];
    // 對兩台各自求解；另一台固定在其目前滑桿設定（otherK）。
    // 搜尋範圍對齊滑桿（×0.25–×2.5），steps 按比例加密維持 Δk 解析度。
    const lines = colliderStates.map((st, i) =>
      formatSolveLine(st, solveSafeSpeeds({
        vehicles, which: i, otherK: colliderStates[1 - i].k,
        kMin: 0.25, kMax: 2.5, steps: 68,
      })));
    el.innerHTML = lines.map(t => `<div>${t}</div>`).join('');
  });
}

function fillLegend() {
  const legend = document.getElementById('legend');
  if (!legend) return;
  const dots = ['#4488ff', '#ff4444'];
  const pathHex = PATH_COLORS.map(c => '#' + c.toString(16).padStart(6, '0'));
  legend.innerHTML = colliderStates.map((st, i) =>
    `<div><span class="dot" style="background:${dots[i % 2]}"></span>` +
    `${st.vehicle.label ?? st.vehicle.class} (${st.vehicle.class} id=${st.vehicle.track_id})</div>`
  ).join('') +
  colliderStates.map((st, i) =>
    `<div><span class="dot" style="background:${pathHex[i % pathHex.length]}; opacity:0.75"></span>` +
    `${st.vehicle.label ?? st.vehicle.class} 路徑</div>`
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

  // 相機初始位（依地圖大小縮放）
  if (cfg.camera?.default === 'ortho_top') {
    setTopDownView();
  } else {
    setPersp45View();
  }

  // 路徑 + 速度剖面（真實秒數；時間原點平移到最早的 collider 資料點）
  const rawPaths = buildPaths(trajectory, cfg);
  const t0 = Math.min(...rawPaths.map(p => p.points[0].t));
  colliderStates = rawPaths.map(p => {
    // 資料淨化管線：平滑（消偵測抖動；不錨定尾端，讓 trim 能判斷）→ 切凍結尾
    // （碰前 bbox 重疊假象）→ 沿末向外插（證據終點後車輛才不會被 advance 夾住原地罰站）。
    // 順序固定，見 lib/path.js 註解。startT = 該車第一筆證據時刻（晚出現的車不得提早出發）。
    const shifted = p.points.map(q => ({ x: q.x, z: q.z, t: q.t - t0 }));
    // 平滑（去噪）→ 切凍結尾 → 抽稀錨點 → 樣條（C¹ 曲線）→ 縱向慣性（壓假加速尖峰）→ 外插
    const { points } = extendPoints(limitAcceleration(splineResample(decimatePoints(
      trimFrozenTail(smoothPoints(shifted, { anchorEnd: false }))))));
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

  resimulate();

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
        st.pivot = wrapModel(await loadModel(m.file), m.flip, st.vehicle.length_m);
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
        st.pivot = wrapModel(await loadModel(m.file), m.flip);
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
