import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader }    from 'three/addons/loaders/GLTFLoader.js';
import { makeFrameMapper } from './lib/frames.js';
import { velocityAtEnd, applyCollision } from './lib/physics.js';
import { getState, segHeading } from './lib/interp.js';

const MAP_WIDTH       = 48.71;
const MAP_HEIGHT      = 33.36;
const FIRST_FRAME     = 1;
const LAST_FRAME      = 89;
const FRAME_DURATION  = 1 / 30;
const ANIM_COLLISION  = 32;

// ── Physics constants ─────────────────────────────────────────────────────────
const TESLA_MASS  = 1500;   // kg
const GOGORO_MASS = 200;    // kg
const MU          = 0.7;    // road friction coefficient
const RESTITUTION = 0.15;   // crash coefficient of restitution

// ── Coordinate offsets ────────────────────────────────────────────────────────
const OFFSET_X = 24.35;
const OFFSET_Z = 16.68;

// ── Original-frame → animation-frame mapping constants ────────────────────────
const ORIG_START     = 17;
const ORIG_COLLISION = 442;
const ORIG_END       = 885;
const ANIM_START     = FIRST_FRAME;
const ANIM_END       = LAST_FRAME;

// ── Fallback waypoints (used if filtered_output.json fails to load) ───────────
const TESLA_WPS_FALLBACK = [
  [  1,  -4.676,  10.582],
  [  2,  -4.631,  10.416],
  [  3,  -4.610,  10.231],
  [  5,  -4.544,   9.807],
  [  6,  -4.473,   9.559],
  [  7,  -4.421,   9.323],
  [  9,  -4.331,   9.027],
  [ 14,  -4.020,   8.155],
  [ 18,  -3.738,   7.406],
  [ 19,  -3.668,   7.179],
  [ 23,  -3.411,   6.427],
  [ 25,  -3.264,   6.007],
  [ 28,  -3.088,   5.556],
  [ 31,  -2.925,   5.069],
  [ 32,  -2.905,   4.987],  // COLLISION
];

const GOGORO_WPS_FALLBACK = [
  [ 21,  -5.729,   0.394],
  [ 23,  -5.243,   0.742],
  [ 26,  -4.514,   1.264],
  [ 31,  -3.298,   2.134],
  [ 32,  -3.055,   2.308],  // COLLISION
];

// ── Frame-mapping helpers ─────────────────────────────────────────────────────
const origToAnim = makeFrameMapper({
  source_start: ORIG_START, source_collision: ORIG_COLLISION, source_end: ORIG_END,
  anim_start: ANIM_START, anim_collision: ANIM_COLLISION, anim_end: ANIM_END,
});

// ── Waypoint generation from JSON data ───────────────────────────────────────
function buildWaypoints(jsonData) {
  const teslaData  = [];
  const gogoroData = [];

  for (const frame of jsonData.frames) {
    for (const obj of frame.objects) {
      if (obj.tracked_id === 7) {
        teslaData.push({
          origFrame: frame.frame_index,
          x: obj.position_m[0] - OFFSET_X,
          z: obj.position_m[1] - OFFSET_Z,
        });
      } else if (obj.tracked_id === 373) {
        gogoroData.push({
          origFrame: frame.frame_index,
          x: obj.position_m[0] - OFFSET_X,
          z: obj.position_m[1] - OFFSET_Z,
        });
      }
    }
  }

  if (teslaData.length === 0 || gogoroData.length === 0) {
    throw new Error('Missing tracked_id=7 or tracked_id=373 in filtered_output.json');
  }

  teslaData.sort((a, b) => a.origFrame - b.origFrame);
  gogoroData.sort((a, b) => a.origFrame - b.origFrame);

  function sampleN(arr, n) {
    if (arr.length <= n) return [...arr];
    const result = [];
    for (let i = 0; i < n; i++) {
      const idx = Math.round(i * (arr.length - 1) / (n - 1));
      result.push(arr[idx]);
    }
    return result;
  }

  function toWp(entry) {
    return [Math.round(origToAnim(entry.origFrame)), entry.x, entry.z];
  }

  function dedup(wps) {
    const map = new Map();
    for (const wp of wps) map.set(wp[0], wp);
    return [...map.values()].sort((a, b) => a[0] - b[0]);
  }

  // Pre-collision only — physics will add post-collision
  const teslaPre  = teslaData.filter(e => e.origFrame <= ORIG_COLLISION);
  const gogoroPre = gogoroData.filter(e => e.origFrame <= ORIG_COLLISION);

  const teslaWps  = dedup(sampleN(teslaPre,  15).map(toWp));
  const gogoroWps = dedup(sampleN(gogoroPre,  4).map(toWp));

  return { teslaWps, gogoroWps };
}

// ── Async waypoint loader ─────────────────────────────────────────────────────
async function loadWaypoints() {
  try {
    const response = await fetch('../data/filtered_output.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.url}`);
    const jsonData = await response.json();
    const result = buildWaypoints(jsonData);
    console.log('[waypoints] Generated from filtered_output.json',
      { tesla: result.teslaWps.length, gogoro: result.gogoroWps.length });
    return result;
  } catch (err) {
    console.warn('[waypoints] fetch failed, using hardcoded fallback:', err.message);
    return { teslaWps: TESLA_WPS_FALLBACK, gogoroWps: GOGORO_WPS_FALLBACK };
  }
}

// ── Renderer ──────────────────────────────────────────────────────────────────
const container = document.getElementById('canvas-container');
const renderer  = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
container.appendChild(renderer.domElement);

// ── Scene ─────────────────────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);

// ── Camera & Controls ─────────────────────────────────────────────────────────
const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 500);
camera.position.set(-3, 28, 22);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(-3, 0, 6);
controls.enableDamping  = true;
controls.dampingFactor  = 0.08;
controls.minDistance    = 3;
controls.maxDistance    = 120;
controls.update();

// ── Lights ────────────────────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 2.0));
const sun = new THREE.DirectionalLight(0xfff4e0, 1.0);
sun.position.set(5, 20, 10);
scene.add(sun);
const fill = new THREE.DirectionalLight(0xffffff, 0.6);
fill.position.set(-5, 10, 25);
scene.add(fill);

// ── Satellite ground plane ────────────────────────────────────────────────────
const satTex = new THREE.TextureLoader().load('../images/image.png');
satTex.colorSpace = THREE.SRGBColorSpace;
satTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(MAP_WIDTH, MAP_HEIGHT),
  new THREE.MeshBasicMaterial({ map: satTex }),
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.02;
scene.add(ground);

// ── GLB loader helpers ────────────────────────────────────────────────────────
const TESLA_FLIP  = Math.PI;
const GOGORO_FLIP = Math.PI;

function wrapModel(gltfScene, flip) {
  const pivot = new THREE.Group();
  const box   = new THREE.Box3().setFromObject(gltfScene);
  const cx    = (box.min.x + box.max.x) / 2;
  const cz    = (box.min.z + box.max.z) / 2;
  const minY  = box.min.y;

  gltfScene.rotation.y = flip;

  const cosF = Math.cos(flip), sinF = Math.sin(flip);
  gltfScene.position.set(
    -(cx * cosF + cz * sinF),
    -minY,
    cx * sinF - cz * cosF,
  );

  gltfScene.traverse(child => {
    if (child.name === 'CarCollider' || child.name === 'MotoCollider') {
      if (child.material) {
        child.material = new THREE.MeshBasicMaterial({
          transparent: true, opacity: 0, depthWrite: false,
        });
      }
    }
  });
  pivot.add(gltfScene);
  scene.add(pivot);
  return pivot;
}

// ── Physics ───────────────────────────────────────────────────────────────────
let teslaSpeedKmh  = 20;   // km/h pre-collision speed, user-adjustable
let gogoroSpeedKmh = 40;   // km/h pre-collision speed, user-adjustable
let teslaPreWps   = null;
let gogoroPreWps  = null;
let pathLines     = [];

// Remove and re-draw path lines after physics update
function rebuildPaths() {
  for (const l of pathLines) scene.remove(l);
  pathLines = [];
  if (!TESLA_WPS || !GOGORO_WPS) return;
  function mk(wps, color) {
    const pts  = wps.map(wp => new THREE.Vector3(wp[1], 0.05, wp[2]));
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.75 }),
    );
    scene.add(line);
    pathLines.push(line);
  }
  mk(TESLA_WPS,  0xffcc33);
  mk(GOGORO_WPS, 0xff8833);
}

// Called when speed sliders change — recompute physics and refresh scene
function rebuildPhysics() {
  if (!teslaPreWps || !gogoroPreWps) return;
  const { aWps, bWps } = applyCollision({
    aPre: teslaPreWps, bPre: gogoroPreWps,
    a: { mass_kg: TESLA_MASS, length_m: 3.8, speed_kmh: teslaSpeedKmh },
    b: { mass_kg: GOGORO_MASS, length_m: 1.7, speed_kmh: gogoroSpeedKmh },
    restitution: RESTITUTION, mu: MU, animCollision: ANIM_COLLISION, animEnd: LAST_FRAME,
  });
  TESLA_WPS  = aWps;
  GOGORO_WPS = bWps;
  rebuildPaths();
  updateScene(currentFrame);
}

// ── Animation state ───────────────────────────────────────────────────────────
let teslaPivot  = null;
let gogoroPivot = null;
let currentFrame = FIRST_FRAME;
let isPlaying    = false;
let accumulator  = 0;
let lastTS       = 0;

// ── Interpolation ─────────────────────────────────────────────────────────────
function applyState(pivot, wps, frame, showFrom) {
  if (!pivot) return;
  pivot.visible = frame >= showFrom;
  const s = getState(wps, frame);
  pivot.position.set(s.x, 0, s.z);
  pivot.rotation.y = s.h;
}

// ── Global waypoint arrays (set after loadWaypoints resolves) ─────────────────
let TESLA_WPS  = null;
let GOGORO_WPS = null;

function updateScene(frame) {
  if (!TESLA_WPS || !GOGORO_WPS) return;
  applyState(teslaPivot,  TESLA_WPS,  frame, FIRST_FRAME);
  applyState(gogoroPivot, GOGORO_WPS, frame, GOGORO_WPS[0][0]);
  if (frameDisplay) frameDisplay.textContent = `${frame}`;
  if (slider)       slider.value = `${frame}`;
}

// ── UI ────────────────────────────────────────────────────────────────────────
const playBtn      = document.getElementById('btn-play');
const resetBtn     = document.getElementById('btn-reset');
const topdownBtn   = document.getElementById('btn-topdown');
const slider       = document.getElementById('frame-slider');
const frameDisplay = document.getElementById('frame-display');
if (slider) { slider.min = FIRST_FRAME; slider.max = LAST_FRAME; slider.step = 1; }

function setPlayLabel() {
  if (playBtn) playBtn.textContent = isPlaying ? '⏸ 暫停' : '▶ 播放';
}
function gotoFrame(f) {
  currentFrame = Math.max(FIRST_FRAME, Math.min(LAST_FRAME, Math.round(f)));
  updateScene(currentFrame);
}
function setTopDownView() {
  camera.position.set(0, 55, 0.001);
  camera.up.set(0, 0, -1);
  controls.target.set(0, 0, 0);
  controls.update();
}

if (playBtn)    playBtn   .addEventListener('click', () => { isPlaying = !isPlaying; accumulator = 0; setPlayLabel(); });
if (resetBtn)   resetBtn  .addEventListener('click', () => { isPlaying = false; accumulator = 0; setPlayLabel(); gotoFrame(FIRST_FRAME); });
if (topdownBtn) topdownBtn.addEventListener('click', setTopDownView);
if (slider)     slider    .addEventListener('input', () => { isPlaying = false; setPlayLabel(); gotoFrame(Number(slider.value)); });

// ── Speed sliders ─────────────────────────────────────────────────────────────
const teslaSlider   = document.getElementById('tesla-speed');
const gogoroSlider  = document.getElementById('gogoro-speed');
const teslaLabel    = document.getElementById('tesla-speed-label');
const gogoroLabel   = document.getElementById('gogoro-speed-label');

if (teslaSlider) {
  teslaSlider.addEventListener('input', () => {
    teslaSpeedKmh = Number(teslaSlider.value);
    if (teslaLabel) teslaLabel.textContent = `${teslaSpeedKmh} km/h`;
    rebuildPhysics();
  });
}
if (gogoroSlider) {
  gogoroSlider.addEventListener('input', () => {
    gogoroSpeedKmh = Number(gogoroSlider.value);
    if (gogoroLabel) gogoroLabel.textContent = `${gogoroSpeedKmh} km/h`;
    rebuildPhysics();
  });
}

// ── Resize ────────────────────────────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ── Render loop ───────────────────────────────────────────────────────────────
function animate(ts) {
  requestAnimationFrame(animate);
  const delta = Math.min((ts - lastTS) / 1000, 0.2);
  lastTS = ts;

  if (isPlaying) {
    accumulator += delta;
    while (accumulator >= FRAME_DURATION) {
      accumulator -= FRAME_DURATION;
      currentFrame++;
      if (currentFrame > LAST_FRAME) { currentFrame = LAST_FRAME; isPlaying = false; setPlayLabel(); break; }
    }
    updateScene(currentFrame);
  }

  controls.update();
  renderer.render(scene, camera);

  window.__teslaPivot  = teslaPivot;
  window.__gogoroPivot = gogoroPivot;
  window.__scene       = scene;
  window.__camera      = camera;
  window.__controls    = controls;
  window.__TESLA_WPS   = TESLA_WPS;
  window.__GOGORO_WPS  = GOGORO_WPS;
}

setPlayLabel();
animate(0);

// ── Loading overlay ───────────────────────────────────────────────────────────
const loadDiv = document.createElement('div');
Object.assign(loadDiv.style, {
  position: 'fixed', inset: '0', display: 'flex',
  alignItems: 'center', justifyContent: 'center',
  background: 'rgba(0,0,0,0.7)', color: '#fff',
  fontSize: '20px', zIndex: '20',
});
loadDiv.textContent = '載入模型中…';
document.body.appendChild(loadDiv);

// ── Init validation ───────────────────────────────────────────────────────────
function validateVehicles() {
  const checks = [
    { pivot: teslaPivot,  name: 'Tesla',  expectedLength: 3.8 },
    { pivot: gogoroPivot, name: 'Gogoro', expectedLength: 1.7 },
  ];
  for (const { pivot, name, expectedLength } of checks) {
    if (!pivot) { console.warn(`[INIT] ${name}: pivot missing`); continue; }
    const box = new THREE.Box3().setFromObject(pivot);
    const size = new THREE.Vector3();
    box.getSize(size);
    const onGround = Math.abs(box.min.y) < 0.05;
    const maxDim = Math.max(size.x, size.z);
    const scaleOK = maxDim > expectedLength * 0.5 && maxDim < expectedLength * 3;
    console.log(`[INIT] ${name}: ground=${onGround}, maxDim=${maxDim.toFixed(2)}m (expected ~${expectedLength}m), scale_ok=${scaleOK}`);
    if (!onGround) console.warn(`[INIT] ${name} NOT on ground! min.y=${box.min.y.toFixed(3)}`);
  }
}

// ── Bootstrap: load waypoints → apply physics → load GLBs ────────────────────
let glbsLoaded = 0;

function onBothLoaded() {
  glbsLoaded++;
  if (glbsLoaded < 2) return;
  loadDiv.remove();
  validateVehicles();
  gotoFrame(FIRST_FRAME);
}

loadWaypoints().then(({ teslaWps, gogoroWps }) => {
  // Store pre-collision waypoints — physics rebuilds post-collision from these
  teslaPreWps  = teslaWps;
  gogoroPreWps = gogoroWps;

  // Apply initial physics with default speed scales (1.0)
  const { aWps, bWps } = applyCollision({
    aPre: teslaPreWps, bPre: gogoroPreWps,
    a: { mass_kg: TESLA_MASS, length_m: 3.8, speed_kmh: teslaSpeedKmh },
    b: { mass_kg: GOGORO_MASS, length_m: 1.7, speed_kmh: gogoroSpeedKmh },
    restitution: RESTITUTION, mu: MU, animCollision: ANIM_COLLISION, animEnd: LAST_FRAME,
  });
  TESLA_WPS  = aWps;
  GOGORO_WPS = bWps;
  rebuildPaths();

  console.log('[physics] Collision impulse applied.',
    { teslaWps: TESLA_WPS.length, gogoroWps: GOGORO_WPS.length });

  const loader = new GLTFLoader();
  loader.load('car.glb', gltf => {
    teslaPivot = wrapModel(gltf.scene, TESLA_FLIP);
    onBothLoaded();
  }, undefined, err => console.error('tesla (car.glb) load error:', err));

  loader.load('moto.glb', gltf => {
    gogoroPivot = wrapModel(gltf.scene, GOGORO_FLIP);
    onBothLoaded();
  }, undefined, err => console.error('gogoro (moto.glb) load error:', err));
});
