// 場景包載入與驗證。錯誤一律 throw（由 main.js 顯示 overlay），不做 fallback。
const REQUIRED = ['code', 'ground', 'origin_offset_m', 'frames', 'vehicles', 'collision'];

export function sceneCodeFromURL() {
  return new URLSearchParams(location.search).get('scene') || 'test1';
}

export async function loadScene(code) {
  if (!/^[\w-]+$/.test(code)) throw new Error(`場景代號不合法：${code}`);
  const basePath = `../scenes/${code}/`;
  const cfgRes = await fetch(basePath + 'scene.json');
  if (!cfgRes.ok) throw new Error(`scenes/${code}/scene.json 載入失敗（HTTP ${cfgRes.status}）`);
  const cfg = await cfgRes.json();

  const missing = REQUIRED.filter(k => !(k in cfg));
  if (missing.length) throw new Error(`scene.json 缺欄位：${missing.join(', ')}`);
  const colliders = cfg.vehicles.filter(v => v.role === 'collider');
  if (colliders.length !== 2) {
    throw new Error(`scene.json 需要恰好 2 台 role=collider，目前 ${colliders.length}`);
  }

  const trajRes = await fetch(basePath + 'trajectory.json');
  if (!trajRes.ok) throw new Error(`scenes/${code}/trajectory.json 載入失敗（HTTP ${trajRes.status}）`);
  const trajectory = await trajRes.json();

  const regRes = await fetch('./models/registry.json');
  if (!regRes.ok) throw new Error('models/registry.json 載入失敗');
  const registry = await regRes.json();

  return { cfg, trajectory, registry, basePath };
}

export function modelFor(vehicleOrClass, registry) {
  const name = typeof vehicleOrClass === 'string'
    ? registry.class_fallback[vehicleOrClass]
    : (vehicleOrClass.model ?? registry.class_fallback[vehicleOrClass.class]);
  if (!name) return null;
  return { file: name, flip: registry.models[name]?.flip ?? Math.PI };
}
