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

  const finite = n => typeof n === 'number' && Number.isFinite(n);

  // length_m/width_m 是 wrapModel 縮放（scale-to-length）與貼地量測的唯一依據，
  // 壞資料（0、NaN、缺欄位）絕不能靜默跳過縮放去渲染原始 GLB 尺寸——那樣機車/汽車
  // 模型會用錯誤比例出現在場景裡卻沒有任何錯誤訊號。壞資料一律在此 throw。
  for (const v of cfg.vehicles) {
    if (!finite(v.length_m) || v.length_m <= 0) {
      throw new Error(`scene.json vehicle track_id=${v.track_id} 的 length_m 必須是正的有限數字（目前 ${v.length_m}）`);
    }
    if (!finite(v.width_m) || v.width_m <= 0) {
      throw new Error(`scene.json vehicle track_id=${v.track_id} 的 width_m 必須是正的有限數字（目前 ${v.width_m}）`);
    }
  }

  // frame mapper 用 (collision-start)/(end-start) 當分母；start==collision 或
  // collision==end 會除以零，車輛座標變 -Infinity/NaN 卻不報錯地渲染出去。
  const f = cfg.frames;
  const sourceKeys = ['source_start', 'source_collision', 'source_end'];
  const animKeys = ['anim_start', 'anim_collision', 'anim_end'];
  for (const k of [...sourceKeys, ...animKeys]) {
    if (!finite(f[k])) throw new Error(`scene.json frames.${k} 必須是有限數字（目前 ${f[k]}）`);
  }
  if (!(f.source_start < f.source_collision && f.source_collision < f.source_end)) {
    throw new Error(`scene.json frames.source_start/source_collision/source_end 必須嚴格遞增（目前 ${f.source_start}, ${f.source_collision}, ${f.source_end}）`);
  }
  if (!(f.anim_start < f.anim_collision && f.anim_collision < f.anim_end)) {
    throw new Error(`scene.json frames.anim_start/anim_collision/anim_end 必須嚴格遞增（目前 ${f.anim_start}, ${f.anim_collision}, ${f.anim_end}）`);
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
  return {
    file: name,
    flip: registry.models[name]?.flip ?? Math.PI,
    hide: registry.models[name]?.hide ?? [],   // 模型自帶參考幾何（如地面圓片）的名稱前綴
  };
}
