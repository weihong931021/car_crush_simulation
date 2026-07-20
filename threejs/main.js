import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { loadScene, sceneCodeFromURL, modelFor } from './scene-loader.js';
import { buildPreWaypoints } from './lib/waypoints.js';
import { applyCollision } from './lib/physics.js';
import { getState } from './lib/interp.js';

// ── 全域狀態 ──────────────────────────────────────────────────────────────────
let CFG = null;                 // scene.json
let FRAME_DURATION = 1 / 30;
let colliderStates = [];        // [{vehicle, preWps, wps, pivot, speedKmh}]
let extraStates = [];           // [{track_id, cls, wps, pivot}]
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

renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
scene.background = new THREE.Color(0x87a5c4);
scene.fog = new THREE.Fog(0x87a5c4, 90, 260);

scene.add(new THREE.HemisphereLight(0xcfe5ff, 0x8a8f7a, 1.1));
scene.add(new THREE.AmbientLight(0xffffff, 0.5));
const sun = new THREE.DirectionalLight(0xfff2dd, 2.4);
sun.position.set(20, 35, 12);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
scene.add(sun);

// ── 碰撞瞬間標記 ─────────────────────────────────────────────────────────────
let crashRing = null;
function ensureCrashRing() {
  if (crashRing) return crashRing;
  crashRing = new THREE.Mesh(
    new THREE.RingGeometry(0.6, 1.0, 32),
    new THREE.MeshBasicMaterial({ color: 0xff3333, transparent: true, side: THREE.DoubleSide }));
  crashRing.rotation.x = -Math.PI / 2;
  crashRing.visible = false;
  scene.add(crashRing);
  return crashRing;
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

function wrapModel(gltfScene, flip) {
  const pivot = new THREE.Group();
  const box = new THREE.Box3().setFromObject(gltfScene);
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

function boxFallback(cls) {
  const isTwoWheeler = /wheel|motor/i.test(cls);
  const geo = isTwoWheeler ? new THREE.BoxGeometry(0.7, 1.2, 1.8) : new THREE.BoxGeometry(1.8, 1.4, 4.2);
  const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: 0x999999 }));
  mesh.position.y = geo.parameters.height / 2;
  mesh.castShadow = true;
  const pivot = new THREE.Group();
  pivot.add(mesh);
  scene.add(pivot);
  return pivot;
}

// ── 物理重算（車速滑桿觸發）──────────────────────────────────────────────────
function rebuildPhysics() {
  const [A, B] = colliderStates;
  if (!A?.preWps || !B?.preWps) return;
  const { aWps, bWps } = applyCollision({
    aPre: A.preWps, bPre: B.preWps,
    a: { ...A.vehicle, speed_kmh: A.speedKmh },
    b: { ...B.vehicle, speed_kmh: B.speedKmh },
    restitution: CFG.collision.restitution, mu: CFG.collision.friction,
    animCollision: CFG.frames.anim_collision, animEnd: CFG.frames.anim_end,
    fps: CFG.frames.fps ?? 30,
  });
  A.wps = aWps;
  B.wps = bWps;
  rebuildPaths();
  updateScene(currentFrame);
}

function rebuildPaths() {
  for (const l of pathLines) scene.remove(l);
  pathLines = [];
  const colors = [0xffcc33, 0xff8833];
  colliderStates.forEach((st, i) => {
    if (!st.wps) return;
    const pts = st.wps.map(wp => new THREE.Vector3(wp[1], 0.05, wp[2]));
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({ color: colors[i % 2], transparent: true, opacity: 0.75 }));
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

  const cf = CFG?.frames.anim_collision;
  if (cf != null && colliderStates[0]?.wps) {
    const ring = ensureCrashRing();
    const dt = frame - cf;
    if (dt >= 0 && dt <= 8) {
      const s0 = getState(colliderStates[0].wps, cf);
      const s1 = getState(colliderStates[1].wps, cf);
      ring.position.set((s0.x + s1.x) / 2, 0.06, (s0.z + s1.z) / 2);
      ring.scale.setScalar(1 + dt * 0.5);
      ring.material.opacity = 1 - dt / 8;
      ring.visible = true;
    } else {
      ring.visible = false;
    }
  }
}

// ── UI ───────────────────────────────────────────────────────────────────────
const playBtn = document.getElementById('btn-play');
const resetBtn = document.getElementById('btn-reset');
const topdownBtn = document.getElementById('btn-topdown');
const perspBtn = document.getElementById('btn-persp');
const chaseBtn = document.getElementById('btn-chase');

let chaseMode = false;

function setPlayLabel() {
  if (playBtn) playBtn.textContent = isPlaying ? '⏸ 暫停' : '▶ 播放';
}
function gotoFrame(f) {
  currentFrame = Math.max(CFG.frames.anim_start, Math.min(CFG.frames.anim_end, Math.round(f)));
  updateScene(currentFrame);
}
function setTopDownView() {
  chaseMode = false;
  const h = Math.max(...CFG.ground.size_m) * 1.15;
  camera.position.set(0, h, 0.001);
  camera.up.set(0, 0, -1);
  controls.target.set(0, 0, 0);
  controls.update();
}
function setPersp45View() {
  chaseMode = false;
  const span = Math.max(...CFG.ground.size_m);
  camera.up.set(0, 1, 0);
  camera.position.set(-span * 0.06, span * 0.57, span * 0.45);
  controls.target.set(-span * 0.06, 0, span * 0.12);
  controls.update();
}

if (playBtn) playBtn.addEventListener('click', () => { isPlaying = !isPlaying; accumulator = 0; setPlayLabel(); });
if (resetBtn) resetBtn.addEventListener('click', () => { isPlaying = false; accumulator = 0; setPlayLabel(); gotoFrame(CFG.frames.anim_start); });
if (topdownBtn) topdownBtn.addEventListener('click', setTopDownView);
if (perspBtn) perspBtn.addEventListener('click', setPersp45View);
if (chaseBtn) chaseBtn.addEventListener('click', () => { chaseMode = true; });
if (slider) slider.addEventListener('input', () => { isPlaying = false; setPlayLabel(); gotoFrame(Number(slider.value)); });

const speedSelect = document.getElementById('playback-speed');
if (speedSelect) speedSelect.addEventListener('change', () => { playbackSpeed = Number(speedSelect.value); });

function bindSpeedSlider(idx) {
  const input = document.getElementById(`collider${idx}-speed`);
  const label = document.getElementById(`collider${idx}-speed-label`);
  const nameEl = document.getElementById(`collider${idx}-name`);
  const st = colliderStates[idx];
  if (!input || !st) return;
  if (nameEl) nameEl.textContent = st.vehicle.label ?? st.vehicle.class;
  input.value = st.speedKmh;
  if (label) label.textContent = `${st.speedKmh} km/h`;
  input.addEventListener('input', () => {
    st.speedKmh = Number(input.value);
    if (label) label.textContent = `${st.speedKmh} km/h`;
    rebuildPhysics();
  });
}

function fillLegend() {
  const legend = document.getElementById('legend');
  if (!legend) return;
  const dots = ['#4488ff', '#ff4444'];
  legend.innerHTML = colliderStates.map((st, i) =>
    `<div><span class="dot" style="background:${dots[i % 2]}"></span>` +
    `${st.vehicle.label ?? st.vehicle.class} (${st.vehicle.class} id=${st.vehicle.track_id})</div>`
  ).join('') +
  `<div><span class="dot" style="background:#ffcc00; opacity:0.6"></span>路徑</div>`;
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
      if (currentFrame > CFG.frames.anim_end) {
        currentFrame = CFG.frames.anim_end;
        isPlaying = false;
        setPlayLabel();
        break;
      }
    }
    updateScene(currentFrame);
  }
  if (chaseMode && colliderStates[0]?.pivot) {
    const p = colliderStates[0].pivot;
    const h = p.rotation.y;
    const back = new THREE.Vector3(-Math.sin(h) * 9, 5, -Math.cos(h) * 9);
    camera.position.lerp(p.position.clone().add(back), 0.08);
    controls.target.lerp(p.position.clone().setY(1), 0.15);
  }
  controls.update();
  renderer.render(scene, camera);
  window.__scene = scene;
  window.__camera = camera;
  window.__controls = controls;
  window.__renderer = renderer;
  window.__colliders = colliderStates;
  window.__extras = extraStates;
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
  FRAME_DURATION = 1 / (cfg.frames.fps ?? 30);
  document.title = cfg.name ?? cfg.code;
  currentFrame = cfg.frames.anim_start;

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

  // waypoints + 物理
  const { colliders, extras } = buildPreWaypoints(trajectory, cfg);
  colliderStates = colliders.map(c => ({
    vehicle: c.vehicle, preWps: c.wps, wps: null, pivot: null,
    speedKmh: c.vehicle.default_speed_kmh ?? 30,
  }));
  rebuildPhysics();

  if (slider) {
    slider.min = cfg.frames.anim_start;
    slider.max = cfg.frames.anim_end;
    slider.step = 1;
  }
  bindSpeedSlider(0);
  bindSpeedSlider(1);
  fillLegend();

  // 模型（collider 用 registry；extras 用 class fallback，失敗補 box）
  await Promise.all([
    ...colliderStates.map(async st => {
      const m = modelFor(st.vehicle, registry);
      if (!m) {
        console.warn(`車輛 track_id=${st.vehicle.track_id} class=${st.vehicle.class} 無對應模型，改用色塊`);
        st.pivot = boxFallback(st.vehicle.class);
        return;
      }
      try {
        st.pivot = wrapModel(await loadModel(m.file), m.flip);
      } catch (e) {
        console.error(`模型 ${m.file} 載入失敗，改用色塊`, e);
        st.pivot = boxFallback(st.vehicle.class);
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
        st.pivot = wrapModel(await loadModel(m.file), m.flip);
      } catch (e) {
        console.error(`模型 ${m.file} 載入失敗，改用色塊`, e);
        st.pivot = boxFallback(ex.cls);
      }
    }),
  ]);

  loadDiv.remove();
  gotoFrame(cfg.frames.anim_start);
}

setPlayLabel();
animate(0);
boot().catch(err => {
  loadDiv.remove();
  console.error(err);
  showError(err.message);
});
