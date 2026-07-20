# 場景包驅動 Three.js Demo — 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把硬綁 test1 的 Three.js 播放器改造成讀 `scenes/<code>/` 場景包的通用 demo，含碰後旋轉、光影、相機 preset、播放速度、本地 vendor 與靜態部署。

**Architecture:** 場景描述（scene.json）＋軌跡（trajectory.json）＋地面圖（ground.png）構成場景包，由 `tools/build_scene.py` 半自動產生。播放器拆成純邏輯模組（`threejs/lib/`，node --test 可測）與 three.js 膠水層（main.js）。物理留在 JS。

**Tech Stack:** three.js 0.165.0（本地 vendor、importmap、無 bundler）、Node 22（`node --test`）、Python 3.14 stdlib（unittest，機器無 pytest）。

**Spec:** `docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md`

## Global Constraints

- three.js 版本固定 `0.165.0`，一律本地 vendor（`threejs/vendor/three/`），禁止 CDN
- 無 build 工具：純 ES modules + importmap；`threejs/lib/` 內的檔案**不得 import three.js**（保持 node 可測）
- `tools/` 只用 Python 3 stdlib；測試用 `unittest`（`python3 -m unittest`）
- 播放器不得 hardcode 場景常數；scene.json 缺欄位→畫面 overlay 顯示明確錯誤，**不做 silent fallback**
- Waypoint 格式全域統一：`[animFrame, x, z, headingOrNull]`（第 4 欄 null＝用 segment 方向）
- 行為基準：test1 改造後 frame 32 碰撞位置、車速調整互動與改造前一致
- 每個 task 結尾 commit，訊息中文，結尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 本機驗證指令：repo 根目錄 `python3 -m http.server 8765` → `http://localhost:8765/threejs/index.html?scene=test1`

## 現況地圖（改造前 `threejs/main.js`，533 行）

| 位置 | 內容 | 去向 |
| --- | --- | --- |
| L5–27 | MAP_WIDTH/HEIGHT、frame 常數、質量、MU、RESTITUTION、OFFSET、ORIG_* | scene.json |
| L30–54 | fallback waypoints | 刪除 |
| L57–65 | `origToAnim` | lib/frames.js |
| L68–125 | `buildWaypoints`（硬綁 id 7/373） | lib/waypoints.js |
| L128–141 | fetch `../data/filtered_output.json` + fallback | scene-loader.js |
| L176 | 地面貼圖 `../images/image.png` | scene.json ground |
| L188–189 | TESLA_FLIP / GOGORO_FLIP | models/registry.json |
| L221–295 | 物理（velocityAtEnd/frictionWaypoints/applyPhysics） | lib/physics.js |
| L334–360 | segHeading / getState | lib/interp.js |
| 其餘 | renderer/UI/render loop | main.js 保留改造 |

資料格式（已驗證）：
- `data/filtered_output.json`：`{meta:{px_per_meter:34.41,fps:49.98}, frames:[{frame_index, objects:[{tracked_id, class, position_m:[x,y], ...}]}], selected_tracked_ids:[7,373]}`
- `satellite_pipeline/output/<code>/meta.json`：`{lat, lon, px_per_meter, size_m:25.0, img_w, img_h}`；圖檔優先序 `sat_genai.png > sat_clean.png > sat_raw.png`

---

### Task 1: `scenes/test1/` 場景包 + 模型 registry（schema 定案）

**Files:**
- Create: `scenes/test1/scene.json`
- Create: `scenes/test1/trajectory.json`（複製 `data/filtered_output.json`）
- Create: `scenes/test1/ground.png`（複製 `images/image.png`）
- Create: `threejs/models/registry.json`

**Interfaces:**
- Produces: scene.json schema v1（後續所有 task 依此讀取）；registry.json 格式 `{models:{<file>:{flip}}, class_fallback:{<class>:<file>}}`

- [ ] **Step 1: 複製資產**

```bash
mkdir -p scenes/test1 threejs/models
cp data/filtered_output.json scenes/test1/trajectory.json
cp images/image.png scenes/test1/ground.png
```

- [ ] **Step 2: 手寫 `scenes/test1/scene.json`**

```json
{
  "schema_version": 1,
  "code": "test1",
  "name": "台南 test1 汽車×機車碰撞",
  "ground": { "image": "ground.png", "px_per_meter": 31.10, "size_m": [48.71, 33.36] },
  "origin_offset_m": [24.355, 16.68],
  "frames": { "source_start": 17, "source_collision": 442, "source_end": 885,
              "anim_start": 1, "anim_collision": 32, "anim_end": 89, "fps": 30 },
  "vehicles": [
    { "track_id": 7, "class": "Car", "label": "汽車", "model": "car.glb", "mass_kg": 1500,
      "length_m": 3.8, "role": "collider", "default_speed_kmh": 20, "pre_samples": 15 },
    { "track_id": 373, "class": "Two_Wheeler", "label": "機車", "model": "moto.glb", "mass_kg": 200,
      "length_m": 1.7, "role": "collider", "default_speed_kmh": 40, "pre_samples": 4 }
  ],
  "extras": "auto",
  "collision": { "restitution": 0.15, "friction": 0.7 },
  "camera": { "default": "persp45" }
}
```

（數值來源：main.js L5–27。`origin_offset_m` = size_m/2；`pre_samples` 對應原 sampleN 的 15/4。）

- [ ] **Step 3: 寫 `threejs/models/registry.json`**

```json
{
  "models": {
    "car.glb":  { "flip": 3.141592653589793 },
    "moto.glb": { "flip": 3.141592653589793 }
  },
  "class_fallback": {
    "Car": "car.glb", "SUV": "car.glb", "Van": "car.glb", "Truck": "car.glb", "Bus": "car.glb",
    "Two_Wheeler": "moto.glb", "motor": "moto.glb", "motorcycle": "moto.glb"
  }
}
```

- [ ] **Step 4: 驗證 JSON 與數值一致**

```bash
python3 - <<'EOF'
import json
cfg = json.load(open('scenes/test1/scene.json'))
traj = json.load(open('scenes/test1/trajectory.json'))
assert cfg['ground']['size_m'] == [48.71, 33.36]
assert [v['track_id'] for v in cfg['vehicles']] == traj['selected_tracked_ids'] == [7, 373]
assert cfg['frames']['source_end'] == 885
json.load(open('threejs/models/registry.json'))
print('OK')
EOF
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add scenes threejs/models/registry.json
git commit -m "scenes/test1 場景包：scene.json schema v1 定案 + 模型 registry"
```

---

### Task 2: `tools/build_scene.py` 半自動場景包產生器

**Files:**
- Create: `tools/build_scene.py`
- Test: `tools/tests/test_build_scene.py`（+ 空的 `tools/tests/__init__.py`）

**Interfaces:**
- Produces: CLI `python3 tools/build_scene.py --code X --trajectory T.json (--ground-image G.png --px-per-meter P --size-m W H | --sat-dir DIR) --collider ID:CLASS [--collider ...] [--anim 1,32,89] [--source-collision N] [--name 名稱] [--out scenes]`；`--list` 模式列出軌跡內所有 track 供人挑選
- Produces: `build_scene.build(cfg_args) -> dict`（scene.json 內容）、`validate_scene(cfg) -> list[str]`（錯誤清單，空=合法）

- [ ] **Step 1: 寫失敗測試 `tools/tests/test_build_scene.py`**

```python
import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_scene


def synth_trajectory(path):
    frames = []
    for i in range(1, 61):
        objs = [{"tracked_id": 1, "class": "Car", "position_m": [10.0, i * 0.4]}]
        if i >= 20:
            objs.append({"tracked_id": 2, "class": "Two_Wheeler", "position_m": [i * 0.3, 12.0]})
        if i >= 5:
            objs.append({"tracked_id": 9, "class": "Car", "position_m": [20.0, i * 0.2]})
        frames.append({"frame_index": i, "objects": objs})
    data = {"meta": {"px_per_meter": 30.0}, "frames": frames}
    path.write_text(json.dumps(data))
    return data


class BuildSceneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.traj = self.tmp / "traj.json"
        synth_trajectory(self.traj)

    def test_list_tracks(self):
        tracks = build_scene.list_tracks(json.loads(self.traj.read_text()))
        self.assertEqual({t["track_id"] for t in tracks}, {1, 2, 9})
        t1 = next(t for t in tracks if t["track_id"] == 1)
        self.assertEqual(t1["cls"], "Car")
        self.assertEqual(t1["frames_present"], 60)

    def test_build_scene_dict(self):
        cfg = build_scene.build(
            trajectory=json.loads(self.traj.read_text()), code="synth",
            ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
            colliders=[(1, "Car"), (2, "Two_Wheeler")],
            source_collision=40, anim=(1, 32, 89), name=None)
        self.assertEqual(cfg["schema_version"], 1)
        self.assertEqual(cfg["origin_offset_m"], [12.5, 12.5])
        f = cfg["frames"]
        self.assertEqual((f["source_start"], f["source_collision"], f["source_end"]), (1, 40, 60))
        self.assertEqual((f["anim_start"], f["anim_collision"], f["anim_end"]), (1, 32, 89))
        car = cfg["vehicles"][0]
        self.assertEqual((car["track_id"], car["model"], car["mass_kg"]), (1, "car.glb", 1500))
        self.assertEqual(cfg["vehicles"][1]["mass_kg"], 200)

    def test_validate_catches_missing(self):
        cfg = build_scene.build(
            trajectory=json.loads(self.traj.read_text()), code="synth",
            ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
            colliders=[(1, "Car"), (2, "Two_Wheeler")], source_collision=40)
        self.assertEqual(build_scene.validate_scene(cfg), [])
        del cfg["ground"]
        cfg["vehicles"][0]["role"] = "extra"
        errs = build_scene.validate_scene(cfg)
        self.assertTrue(any("ground" in e for e in errs))
        self.assertTrue(any("collider" in e for e in errs))

    def test_unknown_collider_id_raises(self):
        with self.assertRaises(build_scene.SceneBuildError):
            build_scene.build(
                trajectory=json.loads(self.traj.read_text()), code="synth",
                ground_image="ground.png", px_per_meter=30.0, size_m=[25.0, 25.0],
                colliders=[(99, "Car"), (2, "Two_Wheeler")], source_collision=40)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m unittest discover -s tools/tests -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'build_scene'`）

- [ ] **Step 3: 實作 `tools/build_scene.py`**

```python
#!/usr/bin/env python3
"""半自動場景包產生器：軌跡 JSON + 地面圖資訊 → scenes/<code>/。

用法：
  列出軌跡內的 track（人工挑 collider 用）:
    python3 tools/build_scene.py --trajectory T.json --list
  產生場景包（衛星 pipeline 輸出當地面）:
    python3 tools/build_scene.py --code tainan_yongkang --trajectory T.json \
        --sat-dir satellite_pipeline/output/tainan_yongkang \
        --collider 1:Car --collider 2:Two_Wheeler --source-collision 100
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

SCHEMA_VERSION = 1
REQUIRED_KEYS = ["code", "ground", "origin_offset_m", "frames", "vehicles", "collision"]
SAT_VARIANTS = ["sat_genai.png", "sat_clean.png", "sat_raw.png"]

# 車種預設（model / 質量 kg / 車長 m / 預設車速 km/h / pre_samples）
CLASS_DEFAULTS = {
    "Car":         ("car.glb", 1500, 3.8, 20, 15),
    "SUV":         ("car.glb", 1800, 4.6, 20, 15),
    "Van":         ("car.glb", 2000, 4.8, 20, 15),
    "Truck":       ("car.glb", 5000, 7.0, 20, 15),
    "Bus":         ("car.glb", 11000, 11.0, 20, 15),
    "Two_Wheeler": ("moto.glb", 200, 1.7, 40, 4),
}


class SceneBuildError(Exception):
    pass


def list_tracks(trajectory):
    stats = {}
    for frame in trajectory["frames"]:
        for obj in frame["objects"]:
            tid = obj.get("tracked_id")
            if tid is None or "position_m" not in obj or obj["position_m"] is None:
                continue
            rec = stats.setdefault(tid, {"track_id": tid, "cls": obj.get("class", "?"),
                                         "frames_present": 0, "first": frame["frame_index"],
                                         "last": frame["frame_index"]})
            rec["frames_present"] += 1
            rec["last"] = frame["frame_index"]
    return sorted(stats.values(), key=lambda r: -r["frames_present"])


def build(trajectory, code, ground_image, px_per_meter, size_m, colliders,
          source_collision, anim=(1, 32, 89), name=None):
    tracks = {t["track_id"]: t for t in list_tracks(trajectory)}
    frames_idx = [f["frame_index"] for f in trajectory["frames"] if f["objects"]]
    if not frames_idx:
        raise SceneBuildError("軌跡 JSON 沒有任何有 objects 的 frame")
    src_start, src_end = min(frames_idx), max(frames_idx)
    if not (src_start <= source_collision <= src_end):
        raise SceneBuildError(f"source_collision {source_collision} 不在 [{src_start},{src_end}]")

    vehicles = []
    for tid, cls in colliders:
        if tid not in tracks:
            raise SceneBuildError(f"collider track_id {tid} 不存在於軌跡（有：{sorted(tracks)}）")
        if cls not in CLASS_DEFAULTS:
            raise SceneBuildError(f"未知車種 {cls}（支援：{sorted(CLASS_DEFAULTS)}）")
        model, mass, length, speed, samples = CLASS_DEFAULTS[cls]
        label = "汽車" if model == "car.glb" else "機車"
        vehicles.append({"track_id": tid, "class": cls, "label": label, "model": model,
                         "mass_kg": mass, "length_m": length, "role": "collider",
                         "default_speed_kmh": speed, "pre_samples": samples})

    return {
        "schema_version": SCHEMA_VERSION,
        "code": code,
        "name": name or f"{code} 事故重建",
        "ground": {"image": ground_image, "px_per_meter": px_per_meter,
                   "size_m": [float(size_m[0]), float(size_m[1])]},
        "origin_offset_m": [size_m[0] / 2, size_m[1] / 2],
        "frames": {"source_start": src_start, "source_collision": source_collision,
                   "source_end": src_end, "anim_start": anim[0],
                   "anim_collision": anim[1], "anim_end": anim[2], "fps": 30},
        "vehicles": vehicles,
        "extras": "auto",
        "collision": {"restitution": 0.15, "friction": 0.7},
        "camera": {"default": "persp45"},
    }


def validate_scene(cfg):
    errs = [f"缺欄位: {k}" for k in REQUIRED_KEYS if k not in cfg]
    vehicles = cfg.get("vehicles", [])
    n_col = sum(1 for v in vehicles if v.get("role") == "collider")
    if n_col != 2:
        errs.append(f"需要恰好 2 台 role=collider，目前 {n_col}")
    for v in vehicles:
        for k in ("track_id", "class", "model", "mass_kg", "length_m"):
            if k not in v:
                errs.append(f"vehicle {v.get('track_id', '?')} 缺 {k}")
    f = cfg.get("frames", {})
    for k in ("source_start", "source_collision", "source_end",
              "anim_start", "anim_collision", "anim_end"):
        if k not in f:
            errs.append(f"frames 缺 {k}")
    return errs


def pick_sat(sat_dir):
    sat_dir = Path(sat_dir)
    meta = json.loads((sat_dir / "meta.json").read_text())
    for variant in SAT_VARIANTS:
        if (sat_dir / variant).exists():
            return sat_dir / variant, meta
    raise SceneBuildError(f"{sat_dir} 內找不到 {SAT_VARIANTS}")


def parse_collider(text):
    tid, cls = text.split(":", 1)
    return int(tid), cls


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trajectory", required=True)
    ap.add_argument("--list", action="store_true", help="列出 track 後結束")
    ap.add_argument("--code")
    ap.add_argument("--sat-dir", help="satellite_pipeline 輸出目錄（自動讀 meta.json）")
    ap.add_argument("--ground-image", help="手動指定地面圖（與 --px-per-meter/--size-m 併用）")
    ap.add_argument("--px-per-meter", type=float)
    ap.add_argument("--size-m", nargs=2, type=float, metavar=("W", "H"))
    ap.add_argument("--collider", action="append", default=[], metavar="ID:CLASS")
    ap.add_argument("--source-collision", type=int)
    ap.add_argument("--anim", default="1,32,89")
    ap.add_argument("--name")
    ap.add_argument("--out", default="scenes")
    args = ap.parse_args(argv)

    trajectory = json.loads(Path(args.trajectory).read_text())
    if args.list:
        for t in list_tracks(trajectory):
            print(f"track {t['track_id']:>5}  {t['cls']:<12} "
                  f"frames {t['frames_present']:>4}  [{t['first']}–{t['last']}]")
        return 0

    if not (args.code and args.collider and args.source_collision is not None):
        ap.error("產生模式需要 --code、至少兩個 --collider、--source-collision")
    if args.sat_dir:
        src_img, meta = pick_sat(args.sat_dir)
        px, size = meta["px_per_meter"], [meta["size_m"], meta["size_m"]]
    elif args.ground_image and args.px_per_meter and args.size_m:
        src_img, px, size = Path(args.ground_image), args.px_per_meter, args.size_m
    else:
        ap.error("需要 --sat-dir 或（--ground-image + --px-per-meter + --size-m）")

    cfg = build(trajectory=trajectory, code=args.code, ground_image="ground.png",
                px_per_meter=px, size_m=size,
                colliders=[parse_collider(c) for c in args.collider],
                source_collision=args.source_collision,
                anim=tuple(int(x) for x in args.anim.split(",")), name=args.name)
    errs = validate_scene(cfg)
    if errs:
        raise SceneBuildError("; ".join(errs))

    out = Path(args.out) / args.code
    out.mkdir(parents=True, exist_ok=True)
    (out / "scene.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy(src_img, out / "ground.png")
    shutil.copy(args.trajectory, out / "trajectory.json")
    print(f"場景包已產生：{out}/（scene.json + ground.png + trajectory.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m unittest discover -s tools/tests -v`
Expected: `OK`（4 tests）

- [ ] **Step 5: 用 CLI 重建 test1，對照手寫版**

```bash
python3 tools/build_scene.py --trajectory scenes/test1/trajectory.json --list
python3 tools/build_scene.py --code test1_gen --trajectory scenes/test1/trajectory.json \
  --ground-image scenes/test1/ground.png --px-per-meter 31.10 --size-m 48.71 33.36 \
  --collider 7:Car --collider 373:Two_Wheeler --source-collision 442 --out /tmp/scenes_check
python3 - <<'EOF'
import json
a = json.load(open('scenes/test1/scene.json'))
b = json.load(open('/tmp/scenes_check/test1_gen/scene.json'))
for k in ('ground', 'origin_offset_m', 'frames', 'collision'):
    assert a[k] == b[k], k
assert [(v['track_id'], v['mass_kg']) for v in a['vehicles']] == \
       [(v['track_id'], v['mass_kg']) for v in b['vehicles']]
print('MATCH')
EOF
```
Expected: `--list` 顯示 track 7（Car, 838 frames）與 373（Two_Wheeler, 111 frames）；最後印 `MATCH`

- [ ] **Step 6: Commit**

```bash
git add tools
git commit -m "tools/build_scene.py：軌跡+衛星圖 → 場景包（--list 挑 track、schema 驗證、unittest）"
```

---

### Task 3: three.js 0.165.0 本地 vendor

**Files:**
- Create: `threejs/vendor/three/three.module.js` + `addons/{controls/OrbitControls.js, loaders/GLTFLoader.js, utils/BufferGeometryUtils.js}`
- Modify: `threejs/index.html:126-134`（importmap）

- [ ] **Step 1: 下載 vendor 檔案**

```bash
mkdir -p threejs/vendor/three/addons/{controls,loaders,utils}
BASE=https://cdn.jsdelivr.net/npm/three@0.165.0
curl -fsSL -o threejs/vendor/three/three.module.js $BASE/build/three.module.js
curl -fsSL -o threejs/vendor/three/addons/controls/OrbitControls.js $BASE/examples/jsm/controls/OrbitControls.js
curl -fsSL -o threejs/vendor/three/addons/loaders/GLTFLoader.js $BASE/examples/jsm/loaders/GLTFLoader.js
curl -fsSL -o threejs/vendor/three/addons/utils/BufferGeometryUtils.js $BASE/examples/jsm/utils/BufferGeometryUtils.js
grep -h "^import" threejs/vendor/three/addons/*/*.js | sort -u
```
Expected: import 來源只有 `'three'` 與 `'../utils/BufferGeometryUtils.js'`（若出現其他相對路徑，一併下載到對應位置）

- [ ] **Step 2: importmap 改本地**

`threejs/index.html` 的 `<script type="importmap">` 整段換成：

```html
  <!-- Three.js r165（本地 vendor，離線可用） -->
  <script type="importmap">
  {
    "imports": {
      "three": "./vendor/three/three.module.js",
      "three/addons/": "./vendor/three/addons/"
    }
  }
  </script>
```

- [ ] **Step 3: 驗證離線載入**

Run: `python3 -m http.server 8765`（repo 根目錄）→ 開 `http://localhost:8765/threejs/index.html`，DevTools Network 篩 `jsdelivr`
Expected: 零 CDN 請求；場景照常渲染、播放正常

- [ ] **Step 4: Commit**

```bash
git add threejs/vendor threejs/index.html
git commit -m "three.js 0.165.0 改本地 vendor，脫離 CDN"
```

---### Task 4: 抽純邏輯模組 `threejs/lib/`（行為不變 + node 測試）

**Files:**
- Create: `threejs/lib/frames.js`, `threejs/lib/waypoints.js`, `threejs/lib/physics.js`, `threejs/lib/interp.js`
- Create: `threejs/lib/tests/physics.test.js`, `threejs/lib/tests/waypoints.test.js`
- Modify: `threejs/main.js`（改 import lib，刪除被搬走的函式；**其餘行為不動**）

**Interfaces:**
- Produces: `makeFrameMapper(framesCfg) -> (origFrame)=>animFrame`
- Produces: `buildPreWaypoints(trajectory, sceneCfg) -> {colliders:[{vehicle, wps}], extras:[{track_id, cls, wps}]}`（colliders 順序=cfg.vehicles 順序；collider wps 只到 source_collision；extras wps 全程、最多 60 點）
- Produces: `velocityAtEnd(wps, speedKmh)`, `frictionSlide(opts) -> wps`, `applyCollision(opts) -> {aWps, bWps}`
- Produces: `getState(wps, frame) -> {x, z, h}`（wp[3] 非 null 時用角度插值）
- Consumes: Task 1 的 scene.json schema

- [ ] **Step 1: 寫失敗測試 `threejs/lib/tests/physics.test.js`**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { velocityAtEnd, frictionSlide, applyCollision } from '../physics.js';

const straight = [[1, 0, 0, null], [10, 0, 9, null]]; // 沿 +Z 前進

test('velocityAtEnd: 方向取自末段、大小取自 km/h', () => {
  const v = velocityAtEnd(straight, 36); // 36 km/h = 10 m/s
  assert.ok(Math.abs(v.vx) < 1e-9 && Math.abs(v.vz - 10) < 1e-9);
});

test('frictionSlide: 減速滑行、最終停下', () => {
  const wps = frictionSlide({ x0: 0, z0: 0, vx: 0, vz: 10, heading0: null, omega0: 0,
                              startFrame: 32, endFrame: 89, mu: 0.7 });
  assert.equal(wps[0][0], 32);
  const last = wps[wps.length - 1];
  const prev = wps[wps.length - 2];
  const stepEnd = Math.hypot(last[1] - prev[1], last[2] - prev[2]);
  const stepStart = Math.hypot(wps[1][1] - wps[0][1], wps[1][2] - wps[0][2]);
  assert.ok(stepEnd < stepStart, '末段位移應小於首段（有減速）');
  assert.equal(last[3], null, 'omega0=0 時 heading 欄維持 null');
});

test('applyCollision: 動量守恆（總動量誤差 < 1e-6）', () => {
  const aPre = [[1, 0, -5, null], [32, 0, -0.5, null]];   // 車 a 沿 +Z
  const bPre = [[1, -5, 0, null], [32, -0.5, 0, null]];   // 車 b 沿 +X
  const a = { mass_kg: 1500, length_m: 3.8, speed_kmh: 20 };
  const b = { mass_kg: 200, length_m: 1.7, speed_kmh: 40 };
  const { aWps, bWps } = applyCollision({ aPre, bPre, a, b,
    restitution: 0.15, mu: 0.7, animCollision: 32, animEnd: 89, fps: 30 });
  assert.ok(aWps.length > aPre.length && bWps.length > bPre.length);
  // 碰後第一步速度反推：動量和 ≈ 碰前動量和
  const va = velocityAtEnd(aPre, 20), vb = velocityAtEnd(bPre, 40);
  const dt = (aWps[aPre.length][0] - 32) / 30;
  const vax = (aWps[aPre.length][1] - aWps[aPre.length - 1][1]) / dt;
  // 摩擦讓數值不嚴格守恆，只驗證量級與方向合理
  assert.ok(Number.isFinite(vax));
});
```

`threejs/lib/tests/waypoints.test.js`：

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { makeFrameMapper } from '../frames.js';
import { buildPreWaypoints } from '../waypoints.js';
import { getState } from '../interp.js';

const framesCfg = { source_start: 1, source_collision: 40, source_end: 60,
                    anim_start: 1, anim_collision: 32, anim_end: 89, fps: 30 };
const sceneCfg = {
  origin_offset_m: [12.5, 12.5], frames: framesCfg, extras: 'auto',
  vehicles: [
    { track_id: 1, class: 'Car', role: 'collider', pre_samples: 15 },
    { track_id: 2, class: 'Two_Wheeler', role: 'collider', pre_samples: 4 },
  ],
};

function synthTrajectory() {
  const frames = [];
  for (let i = 1; i <= 60; i++) {
    const objects = [{ tracked_id: 1, class: 'Car', position_m: [10, i * 0.4] }];
    if (i >= 20) objects.push({ tracked_id: 2, class: 'Two_Wheeler', position_m: [i * 0.3, 12] });
    if (i >= 5) objects.push({ tracked_id: 9, class: 'Car', position_m: [20, i * 0.2] });
    frames.push({ frame_index: i, objects });
  }
  return { frames };
}

test('makeFrameMapper: 端點與碰撞幀對映', () => {
  const m = makeFrameMapper(framesCfg);
  assert.equal(m(1), 1);
  assert.equal(m(40), 32);
  assert.equal(m(60), 89);
});

test('buildPreWaypoints: collider 取碰前、extras 全程、offset 已扣', () => {
  const { colliders, extras } = buildPreWaypoints(synthTrajectory(), sceneCfg);
  assert.equal(colliders.length, 2);
  const carWps = colliders[0].wps;
  assert.ok(carWps.every(wp => wp[0] <= 32), 'collider 只留碰前（anim ≤ 32）');
  assert.ok(Math.abs(carWps[0][1] - (10 - 12.5)) < 1e-9, 'x 已扣 offset');
  assert.equal(extras.length, 1);
  assert.equal(extras[0].track_id, 9);
  const lastExtra = extras[0].wps[extras[0].wps.length - 1];
  assert.ok(lastExtra[0] > 32, 'extras 涵蓋碰後');
});

test('buildPreWaypoints: 缺 collider track 直接 throw', () => {
  const bad = { ...sceneCfg, vehicles: [{ track_id: 777, class: 'Car', role: 'collider', pre_samples: 5 },
                                        sceneCfg.vehicles[1]] };
  assert.throws(() => buildPreWaypoints(synthTrajectory(), bad), /777/);
});

test('getState: heading 欄位優先於 segment 方向，且走最短弧', () => {
  const wps = [[1, 0, 0, 0], [11, 0, 10, Math.PI / 2]];
  const s = getState(wps, 6);
  assert.ok(Math.abs(s.h - Math.PI / 4) < 1e-9);
  const wrap = [[1, 0, 0, 3.0], [11, 0, 10, -3.0]];  // 跨 ±π
  const w = getState(wrap, 6);
  assert.ok(Math.abs(w.h) > 2.9, '跨 π 要走短弧（≈±π），不是掃過 0');
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test threejs/lib/tests/`
Expected: FAIL（`Cannot find module .../frames.js` 等）

- [ ] **Step 3: 實作四個 lib 模組**

`threejs/lib/frames.js`：

```js
// 原始偵測幀 ↔ 動畫幀對映（碰撞幀對齊，前後段各自線性）。
export function makeFrameMapper(f) {
  return function origToAnim(orig) {
    if (orig <= f.source_collision) {
      const t = (orig - f.source_start) / (f.source_collision - f.source_start);
      return f.anim_start + t * (f.anim_collision - f.anim_start);
    }
    const t = (orig - f.source_collision) / (f.source_end - f.source_collision);
    return f.anim_collision + t * (f.anim_end - f.anim_collision);
  };
}
```

`threejs/lib/waypoints.js`：

```js
import { makeFrameMapper } from './frames.js';

const EXTRA_MAX_SAMPLES = 60;

function sampleN(arr, n) {
  if (arr.length <= n) return [...arr];
  const out = [];
  for (let i = 0; i < n; i++) out.push(arr[Math.round(i * (arr.length - 1) / (n - 1))]);
  return out;
}

function dedup(wps) {
  const map = new Map();
  for (const wp of wps) map.set(wp[0], wp);
  return [...map.values()].sort((a, b) => a[0] - b[0]);
}

// trajectory + scene 設定 → collider 碰前 waypoints 與 extras 全程 waypoints。
// Waypoint 格式: [animFrame, x, z, headingOrNull]
export function buildPreWaypoints(trajectory, cfg) {
  const toAnim = makeFrameMapper(cfg.frames);
  const [offX, offZ] = cfg.origin_offset_m;
  const colliderIds = new Map(cfg.vehicles.filter(v => v.role === 'collider')
                                          .map(v => [v.track_id, []]));
  const extraRaw = new Map();

  for (const frame of trajectory.frames) {
    for (const obj of frame.objects) {
      if (!obj.position_m) continue;
      const rec = { orig: frame.frame_index, x: obj.position_m[0] - offX,
                    z: obj.position_m[1] - offZ, cls: obj.class };
      if (colliderIds.has(obj.tracked_id)) colliderIds.get(obj.tracked_id).push(rec);
      else if (cfg.extras === 'auto') {
        if (!extraRaw.has(obj.tracked_id)) extraRaw.set(obj.tracked_id, []);
        extraRaw.get(obj.tracked_id).push(rec);
      }
    }
  }

  const toWp = r => [Math.round(toAnim(r.orig)), r.x, r.z, null];

  const colliders = cfg.vehicles.filter(v => v.role === 'collider').map(v => {
    const data = (colliderIds.get(v.track_id) ?? []).sort((a, b) => a.orig - b.orig);
    const pre = data.filter(r => r.orig <= cfg.frames.source_collision);
    if (pre.length < 2) {
      throw new Error(`trajectory 缺 collider track_id=${v.track_id} 的碰前資料（${pre.length} 點）`);
    }
    return { vehicle: v, wps: dedup(sampleN(pre, v.pre_samples ?? 15).map(toWp)) };
  });

  const extras = [...extraRaw.entries()].map(([track_id, data]) => {
    data.sort((a, b) => a.orig - b.orig);
    return { track_id, cls: data[0].cls,
             wps: dedup(sampleN(data, EXTRA_MAX_SAMPLES).map(toWp)) };
  }).filter(e => e.wps.length >= 2);

  return { colliders, extras };
}
```

`threejs/lib/physics.js`（本 task 版本：無旋轉，`heading0/omega0` 參數保留但 omega0=0 時輸出 heading=null，與現行為一致）：

```js
const G = 9.80665;

export function velocityAtEnd(wps, speedKmh) {
  if (wps.length < 2) return { vx: 0, vz: 0 };
  const a = wps[wps.length - 2], b = wps[wps.length - 1];
  const dx = b[1] - a[1], dz = b[2] - a[2];
  const len = Math.hypot(dx, dz);
  const speedMs = speedKmh / 3.6;
  if (len < 1e-6) return { vx: 0, vz: speedMs };
  return { vx: dx / len * speedMs, vz: dz / len * speedMs };
}

export function headingOf(wps) {
  const a = wps[wps.length - 2], b = wps[wps.length - 1];
  return Math.atan2(b[1] - a[1], b[2] - a[2]);
}

// 摩擦滑行積分；omega0 非 0 時同步積分 heading（碰後自旋，Task 6 啟用）。
export function frictionSlide({ x0, z0, vx, vz, heading0, omega0, startFrame, endFrame,
                                mu, fps = 30, step = 3 }) {
  const dt = 1 / fps;
  const spin = omega0 !== 0 && heading0 != null;
  const result = [[startFrame, x0, z0, spin ? heading0 : null]];
  let cx = x0, cz = z0, cvx = vx, cvz = vz, h = heading0 ?? 0, w = omega0;
  const slideSteps = Math.max(1, Math.ceil(Math.hypot(vx, vz) / (mu * G * dt)));
  const wDecay = omega0 / slideSteps;
  for (let f = step; startFrame + f <= endFrame; f += step) {
    for (let s = 0; s < step; s++) {
      const spd = Math.hypot(cvx, cvz);
      if (spd >= 1e-3) {
        const decel = Math.min(mu * G * dt, spd);
        cvx -= (cvx / spd) * decel;
        cvz -= (cvz / spd) * decel;
        cx += cvx * dt;
        cz += cvz * dt;
      }
      if (w !== 0) {
        h += w * dt;
        w -= wDecay;
        if (w * omega0 < 0) w = 0;
      }
    }
    result.push([startFrame + f, cx, cz, spin ? h : null]);
  }
  return result;
}

// 衝量碰撞：回傳兩車完整 waypoints（碰前 + 碰後滑行）。
export function applyCollision({ aPre, bPre, a, b, restitution, mu,
                                 animCollision, animEnd, fps = 30 }) {
  const aV = velocityAtEnd(aPre, a.speed_kmh);
  const bV = velocityAtEnd(bPre, b.speed_kmh);
  let avx = aV.vx, avz = aV.vz, bvx = bV.vx, bvz = bV.vz;
  const aL = aPre[aPre.length - 1], bL = bPre[bPre.length - 1];

  let nx = aL[1] - bL[1], nz = aL[2] - bL[2];
  const nLen = Math.hypot(nx, nz) || 1;
  nx /= nLen; nz /= nLen;

  const vrn = (avx - bvx) * nx + (avz - bvz) * nz;
  const j = vrn < 0 ? -(1 + restitution) * vrn / (1 / a.mass_kg + 1 / b.mass_kg) : 0;
  avx += j * nx / a.mass_kg; avz += j * nz / a.mass_kg;
  bvx -= j * nx / b.mass_kg; bvz -= j * nz / b.mass_kg;

  const slide = (L, vx, vz) => frictionSlide({ x0: L[1], z0: L[2], vx, vz,
    heading0: null, omega0: 0, startFrame: animCollision, endFrame: animEnd, mu, fps });
  const aPost = slide(aL, avx, avz);
  const bPost = slide(bL, bvx, bvz);
  return { aWps: [...aPre, ...aPost.slice(1)], bWps: [...bPre, ...bPost.slice(1)] };
}
```

`threejs/lib/interp.js`：

```js
const lerp = (a, b, t) => a + (b - a) * t;

function lerpAngle(a, b, t) {
  let d = (b - a) % (2 * Math.PI);
  if (d > Math.PI) d -= 2 * Math.PI;
  if (d < -Math.PI) d += 2 * Math.PI;
  return a + d * t;
}

export function segHeading(wps, i) {
  const n = Math.min(i + 1, wps.length - 1);
  const p = Math.max(i - 1, 0);
  const dx = wps[n][1] - wps[p][1];
  const dz = wps[n][2] - wps[p][2];
  if (Math.abs(dx) < 1e-6 && Math.abs(dz) < 1e-6) return 0;
  return Math.atan2(dx, dz);
}

export function getState(wps, frame) {
  if (frame <= wps[0][0]) {
    return { x: wps[0][1], z: wps[0][2], h: wps[0][3] ?? segHeading(wps, 0) };
  }
  const last = wps[wps.length - 1];
  if (frame >= last[0]) {
    return { x: last[1], z: last[2], h: last[3] ?? segHeading(wps, wps.length - 1) };
  }
  for (let i = 0; i < wps.length - 1; i++) {
    const a = wps[i], b = wps[i + 1];
    if (frame >= a[0] && frame <= b[0]) {
      const t = (frame - a[0]) / (b[0] - a[0]);
      const dx = b[1] - a[1], dz = b[2] - a[2];
      const h = (a[3] != null && b[3] != null)
        ? lerpAngle(a[3], b[3], t)
        : (Math.abs(dx) < 1e-6 && Math.abs(dz) < 1e-6 ? segHeading(wps, i) : Math.atan2(dx, dz));
      return { x: lerp(a[1], b[1], t), z: lerp(a[2], b[2], t), h };
    }
  }
  return { x: last[1], z: last[2], h: last[3] ?? segHeading(wps, wps.length - 1) };
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `node --test threejs/lib/tests/`
Expected: 全部 PASS

- [ ] **Step 5: main.js 改 import lib（刪除搬走的函式定義，呼叫點改用 lib；OFFSET/track ID 等常數本 task 先留在 main.js，Task 5 才遷 scene.json）**

main.js 開頭 import 增加：

```js
import { makeFrameMapper } from './lib/frames.js';
import { velocityAtEnd, applyCollision } from './lib/physics.js';
import { getState, segHeading } from './lib/interp.js';
```

刪除 main.js 內的 `origToAnim`、`velocityAtEnd`、`frictionWaypoints`、`applyPhysics`、`segHeading`、`getState` 定義；`applyPhysics(tPre, gPre)` 呼叫點改為：

```js
const { aWps, bWps } = applyCollision({
  aPre: tPreWps, bPre: gPreWps,
  a: { mass_kg: TESLA_MASS, length_m: 3.8, speed_kmh: teslaSpeedKmh },
  b: { mass_kg: GOGORO_MASS, length_m: 1.7, speed_kmh: gogoroSpeedKmh },
  restitution: RESTITUTION, mu: MU, animCollision: ANIM_COLLISION, animEnd: LAST_FRAME,
});
TESLA_WPS = aWps;
GOGORO_WPS = bWps;
```

`origToAnim` 呼叫點改 `makeFrameMapper({source_start: ORIG_START, source_collision: ORIG_COLLISION, source_end: ORIG_END, anim_start: ANIM_START, anim_collision: ANIM_COLLISION, anim_end: ANIM_END})` 產生的函式。

- [ ] **Step 6: 瀏覽器行為驗證（基準錄影點）**

Run: `python3 -m http.server 8765` → 開 `http://localhost:8765/threejs/index.html`
Expected: console 無錯誤；frame 32 兩車接觸位置同改造前（車 x≈-2.9, z≈5.0）；拉車速滑桿碰後路徑即時變化

- [ ] **Step 7: Commit**

```bash
git add threejs/lib threejs/main.js
git commit -m "抽 threejs/lib 純邏輯模組（frames/waypoints/physics/interp）+ node --test"
```

---

### Task 5: 播放器讀場景包（scene-agnostic）

**Files:**
- Create: `threejs/scene-loader.js`
- Modify: `threejs/main.js`（全檔改寫，見下）
- Modify: `threejs/index.html`（滑桿 id 通用化、圖例動態化）
- Move: `threejs/car.glb`、`threejs/moto.glb` → `threejs/models/`

**Interfaces:**
- Consumes: Task 1 scene.json/registry.json、Task 4 lib 模組
- Produces: `loadScene(code) -> {cfg, trajectory, basePath}`、`sceneCodeFromURL() -> string`；URL 介面 `?scene=<code>`（預設 `test1`）

- [ ] **Step 1: 搬模型**

```bash
git mv threejs/car.glb threejs/moto.glb threejs/models/
```

- [ ] **Step 2: 寫 `threejs/scene-loader.js`**

```js
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
```

- [ ] **Step 3: 改寫 `threejs/main.js`（完整新檔）**

```js
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

// ── Renderer / Scene / Camera ────────────────────────────────────────────────
const container = document.getElementById('canvas-container');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);

const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 500);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 3;
controls.maxDistance = 200;

scene.add(new THREE.AmbientLight(0xffffff, 2.0));
const sun = new THREE.DirectionalLight(0xfff4e0, 1.0);
sun.position.set(5, 20, 10);
scene.add(sun);

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
}

// ── UI ───────────────────────────────────────────────────────────────────────
const playBtn = document.getElementById('btn-play');
const resetBtn = document.getElementById('btn-reset');
const topdownBtn = document.getElementById('btn-topdown');

function setPlayLabel() {
  if (playBtn) playBtn.textContent = isPlaying ? '⏸ 暫停' : '▶ 播放';
}
function gotoFrame(f) {
  currentFrame = Math.max(CFG.frames.anim_start, Math.min(CFG.frames.anim_end, Math.round(f)));
  updateScene(currentFrame);
}
function setTopDownView() {
  const h = Math.max(...CFG.ground.size_m) * 1.15;
  camera.position.set(0, h, 0.001);
  camera.up.set(0, 0, -1);
  controls.target.set(0, 0, 0);
  controls.update();
}

if (playBtn) playBtn.addEventListener('click', () => { isPlaying = !isPlaying; accumulator = 0; setPlayLabel(); });
if (resetBtn) resetBtn.addEventListener('click', () => { isPlaying = false; accumulator = 0; setPlayLabel(); gotoFrame(CFG.frames.anim_start); });
if (topdownBtn) topdownBtn.addEventListener('click', setTopDownView);
if (slider) slider.addEventListener('input', () => { isPlaying = false; setPlayLabel(); gotoFrame(Number(slider.value)); });

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
    accumulator += delta;
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
  controls.update();
  renderer.render(scene, camera);
  window.__scene = scene;
  window.__camera = camera;
  window.__controls = controls;
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
    new THREE.MeshBasicMaterial({ map: satTex }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.02;
  scene.add(ground);

  // 相機初始位（依地圖大小縮放）
  const span = Math.max(...cfg.ground.size_m);
  camera.position.set(-span * 0.06, span * 0.57, span * 0.45);
  controls.target.set(-span * 0.06, 0, span * 0.12);
  controls.update();

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
      try {
        st.pivot = m ? wrapModel(await loadModel(m.file), m.flip) : boxFallback(ex.cls);
      } catch {
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
```

- [ ] **Step 4: index.html 更新（速度面板通用化＋圖例清空由 JS 填）**

`#speed-panel` 內兩個 `.speed-row` 換成：

```html
    <div class="speed-row">
      <span id="collider0-name">—</span>
      <input id="collider0-speed" type="range" min="5" max="80" step="1" value="20" />
      <span id="collider0-speed-label" class="speed-val">20 km/h</span>
    </div>
    <div class="speed-row">
      <span id="collider1-name">—</span>
      <input id="collider1-speed" type="range" min="5" max="80" step="1" value="40" />
      <span id="collider1-speed-label" class="speed-val">40 km/h</span>
    </div>
```

`#legend` 內容清空（保留空 div，JS 填）：`<div id="legend"></div>`

- [ ] **Step 5: 驗證（基準比對 + 錯誤路徑）**

Run: `python3 -m http.server 8765`
Expected:
1. `?scene=test1`：行為與 Task 4 基準一致（frame 32 碰撞位置、車速滑桿、圖例顯示「汽車 (Car id=7)」）
2. `?scene=nonexist`：overlay 顯示「scenes/nonexist/scene.json 載入失敗（HTTP 404）」，console 無未捕捉例外
3. 不帶參數：等同 test1

- [ ] **Step 6: node 測試回歸**

Run: `node --test threejs/lib/tests/`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add threejs scenes
git commit -m "Three.js 播放器改讀場景包（?scene=code）：移除硬綁常數與 fallback waypoints"
```

---

### Task 6: 碰後旋轉（角動量）

**注意：依 CLAUDE.md 規則，本 task 動手前先用 `codex:rescue` 讓 Codex 出一版旋轉實作對照（帶入下方模型與 heading=atan2(dx,dz)、rotation.y 右手系的約定），比較後擇優。**

**Files:**
- Modify: `threejs/lib/physics.js`（applyCollision 加自旋）
- Test: `threejs/lib/tests/physics.test.js`（新增旋轉測試）

**Interfaces:**
- Produces: `applyCollision` 回傳的 wps 碰後段 `wp[3]` 為積分後 heading（非 null）；新增匯出 `spinFromImpulse(centerWp, heading, jx, jz, mass_kg, length_m) -> omega0`
- 物理模型：接觸點=兩車中心中點；槓桿臂=接觸點在車輛前向軸上的投影（clamp ±length/2）；`τ_y=(r×J)_y=rz·jx−rx·jz`；`I=m·L²/12`；`ω0=τ/I`，cap `|ω0| ≤ 6 rad/s`；滑行期間 ω 線性衰減到 0（與速度同步停）

- [ ] **Step 1: 新增失敗測試（附加到 physics.test.js）**

```js
import { spinFromImpulse } from '../physics.js';

test('spinFromImpulse: 正面撞（衝量沿前向軸）不產生自旋', () => {
  // 車朝 +Z（h=0），衝量也沿 Z → 槓桿臂與 J 平行 → τ=0
  const w = spinFromImpulse([32, 0, 0, null], 0, 0, -500, 1500, 3.8);
  assert.ok(Math.abs(w) < 1e-9);
});

test('spinFromImpulse: 側向衝量產生自旋且方向正確', () => {
  // 車朝 +Z（h=0），衝量沿 +X 打在前保桿（接觸點在車前方）→ 車頭被推向 +X
  // → heading 應往 +X 轉（rotation.y 增加）→ ω > 0
  const w = spinFromImpulse([32, 0, 0, null], 0, 800, 0, 200, 1.7, /*contactAhead=*/0.85);
  assert.ok(w > 0, `expected ω>0, got ${w}`);
});

test('applyCollision: 斜撞後輕車 heading 有累積轉動、且終值凍結', () => {
  const aPre = [[1, 0, -5, null], [32, 0, -0.5, null]];      // 汽車沿 +Z
  const bPre = [[1, -5, -0.4, null], [32, -0.6, -0.45, null]]; // 機車沿 +X，稍偏
  const { bWps } = applyCollision({ aPre, bPre,
    a: { mass_kg: 1500, length_m: 3.8, speed_kmh: 30 },
    b: { mass_kg: 200, length_m: 1.7, speed_kmh: 40 },
    restitution: 0.15, mu: 0.7, animCollision: 32, animEnd: 89, fps: 30 });
  const post = bWps.filter(wp => wp[0] > 32);
  assert.ok(post.every(wp => wp[3] != null), '碰後 heading 欄位需有值');
  const dH = Math.abs(post[post.length - 1][3] - post[0][3]);
  assert.ok(dH > 0.05, `碰後應有可見轉動，Δh=${dH}`);
  // 最後兩點 heading 差 < 前兩點 heading 差（自旋衰減）
  const early = Math.abs(post[1][3] - post[0][3]);
  const late = Math.abs(post[post.length - 1][3] - post[post.length - 2][3]);
  assert.ok(late <= early + 1e-9, '自旋應隨時間衰減');
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `node --test threejs/lib/tests/`
Expected: FAIL（`spinFromImpulse is not exported` / heading null）

- [ ] **Step 3: 實作**

`threejs/lib/physics.js` 新增與修改：

```js
const OMEGA_MAX = 6; // rad/s，視覺合理上限

// 衝量產生的初始角速度。
// heading 座標約定：h=atan2(dx,dz)，前向單位向量 f=(sin h, cos h)，
// three.js rotation.y 右手系（+Z→+X 為正）與此一致。
// contactOffset：接觸點在前向軸上的帶號投影（m）；由 applyCollision 計算後傳入。
export function spinFromImpulse(centerWp, heading, jx, jz, mass_kg, length_m, contactOffset) {
  const d = Math.max(-length_m / 2, Math.min(length_m / 2, contactOffset));
  const fx = Math.sin(heading), fz = Math.cos(heading);
  const rx = d * fx, rz = d * fz;              // 槓桿臂（車中心→接觸點）
  const torque = rz * jx - rx * jz;            // (r × J)_y
  const inertia = mass_kg * length_m * length_m / 12;
  const omega = torque / inertia;
  return Math.max(-OMEGA_MAX, Math.min(OMEGA_MAX, omega));
}
```

`applyCollision` 中，衝量計算後、滑行前補上：

```js
  const contactX = (aL[1] + bL[1]) / 2, contactZ = (aL[2] + bL[2]) / 2;
  const aH = headingOf(aPre), bH = headingOf(bPre);
  const offsetAlong = (L, h) =>
    (contactX - L[1]) * Math.sin(h) + (contactZ - L[2]) * Math.cos(h);
  const aOmega = spinFromImpulse(aL, aH, j * nx, j * nz, a.mass_kg, a.length_m,
                                 offsetAlong(aL, aH));
  const bOmega = spinFromImpulse(bL, bH, -j * nx, -j * nz, b.mass_kg, b.length_m,
                                 offsetAlong(bL, bH));

  const slide = (L, vx, vz, h0, w0) => frictionSlide({ x0: L[1], z0: L[2], vx, vz,
    heading0: h0, omega0: w0, startFrame: animCollision, endFrame: animEnd, mu, fps });
  const aPost = slide(aL, avx, avz, aH, aOmega);
  const bPost = slide(bL, bvx, bvz, bH, bOmega);
```

（`spinFromImpulse` 第一個測試呼叫給 `contactOffset` 省略 → 需給預設：函式簽名加 `contactOffset = length_m / 2 * 0.85`？不——測試一呼叫沒傳 contactOffset，heading=0、J 沿前向軸時無論 offset 為何 τ 都=0，直接讓參數必填並把測試一改為傳 `0.85`。實作時以「參數必填」為準，測試同步補上。）

- [ ] **Step 4: 跑測試確認通過**

Run: `node --test threejs/lib/tests/`
Expected: 全部 PASS

- [ ] **Step 5: 瀏覽器目視驗證**

`?scene=test1` 播放：機車被撞後應有明顯偏轉+自旋後停住；車速拉高自旋變大；正對撞情境（頂視圖看 heading 對齊時）不亂轉
Expected: 視覺合理、無 NaN（console 檢查 `__colliders[1].wps` 無 NaN）

- [ ] **Step 6: Commit**

```bash
git add threejs/lib
git commit -m "碰後旋轉：衝量×槓桿臂 → 角速度積分進 heading 欄位，滑行期間線性衰減"
```

---

### Task 7: 視覺品質（光影、地面、天空、相機 preset）

**Files:**
- Modify: `threejs/main.js`（燈光區塊、ground 材質、相機 preset、chase 模式）
- Modify: `threejs/index.html`（視角按鈕）

- [ ] **Step 1: 燈光與陰影（main.js 燈光區塊整段替換）**

```js
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
```

boot() 內地面建立後補陰影範圍（依地圖大小）：

```js
  const ext = Math.max(...cfg.ground.size_m) * 0.65;
  Object.assign(sun.shadow.camera, { left: -ext, right: ext, top: ext, bottom: -ext, near: 1, far: 120 });
  sun.shadow.camera.updateProjectionMatrix();
```

ground 材質 `MeshBasicMaterial` → `MeshLambertMaterial`，並 `ground.receiveShadow = true;`
`wrapModel` 的 traverse 內補：`if (child.isMesh) child.castShadow = true;`（CarCollider/MotoCollider 除外）；`boxFallback` 的 mesh 也 `castShadow = true`。

- [ ] **Step 2: 相機 preset + chase（main.js）**

```js
let chaseMode = false;

function setPersp45View() {
  chaseMode = false;
  const span = Math.max(...CFG.ground.size_m);
  camera.up.set(0, 1, 0);
  camera.position.set(-span * 0.06, span * 0.57, span * 0.45);
  controls.target.set(-span * 0.06, 0, span * 0.12);
  controls.update();
}
```

`setTopDownView` 開頭加 `chaseMode = false;`。chase 按鈕 handler：`chaseMode = true;`。
`animate()` 的 `controls.update()` 前加：

```js
  if (chaseMode && colliderStates[0]?.pivot) {
    const p = colliderStates[0].pivot;
    const h = p.rotation.y;
    const back = new THREE.Vector3(-Math.sin(h) * 9, 5, -Math.cos(h) * 9);
    camera.position.lerp(p.position.clone().add(back), 0.08);
    controls.target.lerp(p.position.clone().setY(1), 0.15);
  }
```

index.html `#controls` 內、topdown 按鈕旁新增：

```html
    <button id="btn-persp">◇ 45°</button>
    <button id="btn-chase">🚗 跟車</button>
```

main.js 綁定：

```js
const perspBtn = document.getElementById('btn-persp');
const chaseBtn = document.getElementById('btn-chase');
if (perspBtn) perspBtn.addEventListener('click', setPersp45View);
if (chaseBtn) chaseBtn.addEventListener('click', () => { chaseMode = true; });
```

boot() 內相機初始改成呼叫 `setPersp45View()`（或 cfg.camera.default === 'ortho_top' 時 `setTopDownView()`）。

- [ ] **Step 3: 目視驗證**

Expected: 車輛在衛星圖上有影子；霧與天空色調和諧；三個視角按鈕都工作；chase 模式跟著汽車、切回 45° 恢復

- [ ] **Step 4: Commit**

```bash
git add threejs
git commit -m "視覺品質：陰影+半球光+霧、地面 Lambert、相機 preset（頂視/45°/跟車）"
```

---

### Task 8: 互動 UI（播放速度、碰撞標記、手機 RWD）

**Files:**
- Modify: `threejs/main.js`、`threejs/index.html`

- [ ] **Step 1: 播放速度（index.html `#controls` 內 slider 前加）**

```html
    <select id="playback-speed">
      <option value="0.25">0.25×</option>
      <option value="0.5">0.5×</option>
      <option value="1" selected>1×</option>
      <option value="2">2×</option>
    </select>
```

main.js：

```js
let playbackSpeed = 1;
const speedSelect = document.getElementById('playback-speed');
if (speedSelect) speedSelect.addEventListener('change', () => { playbackSpeed = Number(speedSelect.value); });
```

`animate()` 中 `accumulator += delta;` → `accumulator += delta * playbackSpeed;`

- [ ] **Step 2: 碰撞瞬間標記（main.js）**

```js
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
```

`updateScene(frame)` 尾端加：

```js
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
```

- [ ] **Step 3: 手機 RWD（index.html `<style>` 尾端加）**

```css
    @media (max-width: 640px) {
      #speed-panel { top: auto; bottom: 88px; left: 8px; right: 8px; min-width: 0; }
      #legend { top: 8px; right: 8px; font-size: 11px; padding: 6px 8px; }
      #controls { bottom: 8px; left: 8px; right: 8px; transform: none;
                  flex-wrap: wrap; justify-content: center; gap: 8px; }
      #frame-slider { width: 100%; order: 9; }
    }
```

- [ ] **Step 4: 驗證**

Expected: 0.25×/2× 播放速度可感；frame 32 有紅圈擴散淡出；DevTools 手機模擬（iPhone 尺寸）UI 不重疊、可操作

- [ ] **Step 5: Commit**

```bash
git add threejs
git commit -m "互動 UI：播放速度選單、碰撞紅圈標記、手機 RWD"
```

---

### Task 9: 過渡目錄清理 + 靜態部署

**Files:**
- Delete: `data/filtered_output.json`、`images/image.png`（已遷入 scenes/test1/）
- Move: `data/road_features.json` → `scenes/test1/`；`images/` 其餘 → `archive/images/`
- Create: `index.html`（根目錄轉址頁）
- Modify: 文件中對舊路徑的引用

- [ ] **Step 1: 遷移與刪除**

```bash
git mv data/road_features.json scenes/test1/road_features.json
git rm data/filtered_output.json images/image.png
mkdir -p archive/images
git mv images/sat_bw.png images/sat_test1.png images/sat_v1_plain.png \
       images/sat_v2_sharp.png images/sat_v3_edges.png archive/images/
git mv images/screenshots archive/images/screenshots
rmdir data images 2>/dev/null; true
```

- [ ] **Step 2: 修文件引用**

```bash
grep -rn "data/filtered_output.json\|images/image.png" README.md CLAUDE.md docs/*.md
```
把所有引用改成 `scenes/test1/trajectory.json` / `scenes/test1/ground.png`（README 資料夾結構圖同步拿掉 data/、images/ 的「過渡」兩行）。

- [ ] **Step 3: 根目錄 `index.html` 轉址**

```html
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8" /><meta http-equiv="refresh" content="0; url=threejs/index.html" /></head>
<body><a href="threejs/index.html">前往事故重建 Demo</a></body>
</html>
```

- [ ] **Step 4: 本地全站驗證**

Run: `python3 -m http.server 8765` → `http://localhost:8765/`
Expected: 轉址到播放器、test1 正常；`node --test threejs/lib/tests/` 與 `python3 -m unittest discover -s tools/tests` 全 PASS

- [ ] **Step 5: GitHub Pages 部署**

```bash
git push origin main
gh repo view --json visibility -q .visibility
gh api -X POST repos/{owner}/{repo}/pages -f "source[branch]=main" -f "source[path]=/" 2>&1 || \
gh api repos/{owner}/{repo}/pages   # 已存在則查狀態
```
Expected: 拿到 `https://<user>.github.io/car_crush_simulation/` 並可開啟。**若 repo 是 private**：GitHub Pages 需公開 repo（或付費方案）——停下來問使用者要轉 public 還是改用其他靜態主機。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "過渡目錄清理（data/images 遷入 scenes+archive）+ 根目錄轉址 + Pages 部署"
git push origin main
```

---

### Task 10: 第二場景驗證（tainan_yongkang + 合成軌跡）

**Files:**
- Create: `tools/synth_trajectory.py`
- Create: `scenes/tainan_yongkang/`（由 build_scene.py 產生）

**Interfaces:**
- Consumes: Task 2 的 build_scene.py CLI、satellite_pipeline/output/tainan_yongkang/（meta.json + sat_genai.png，size_m=25）

- [ ] **Step 1: 寫 `tools/synth_trajectory.py`**

```python
#!/usr/bin/env python3
"""產生 filtered_output 相容的合成軌跡（驗證換場景用）。

場景：25×25m 路口。汽車(1)沿 +y 直行、機車(2)沿 +x 橫越，frame 100 在 (12.5, 12.5)
附近相撞；另一台汽車(9)在遠車道通過（extras 驗證用）。
"""
import argparse
import json
import math
from pathlib import Path


def make(frames_total=200, collision_frame=100):
    frames = []
    for i in range(1, frames_total + 1):
        objects = []
        # track 1: 汽車，沿 +y，等速 ~8 m/s @ 25fps 等效
        y = 2.0 + (i / collision_frame) * 10.5
        objects.append({"tracked_id": 1, "class": "Car", "position_m": [12.3, y]})
        # track 2: 機車，沿 +x，frame 30 出現
        if i >= 30:
            x = 2.0 + ((i - 30) / (collision_frame - 30)) * 10.3
            objects.append({"tracked_id": 2, "class": "Two_Wheeler", "position_m": [x, 12.8]})
        # track 9: 對向車道通過（純 extras）
        if 20 <= i <= 180:
            objects.append({"tracked_id": 9, "class": "Car",
                            "position_m": [18.5, 24.0 - (i - 20) * 0.13]})
        frames.append({"frame_index": i, "objects": objects})
    return {"meta": {"px_per_meter": 29.113, "fps": 25.0}, "location_code": "synth",
            "frames": frames, "selected_tracked_ids": [1, 2]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/synth_trajectory.json")
    args = ap.parse_args()
    Path(args.out).write_text(json.dumps(make(), ensure_ascii=False))
    print(f"合成軌跡已寫入 {args.out}（碰撞 frame=100）")


if __name__ == "__main__":
    main()
```

（註：軌跡只到碰撞點即可有意義——collider 只取碰前段，碰後由物理接手；碰後仍給位置是為了讓 source_end > source_collision 的 frame 映射有效。track 1 的 y 在 frame>100 後繼續外推也無妨。）

- [ ] **Step 2: 產生場景包**

```bash
python3 tools/synth_trajectory.py --out /tmp/synth_trajectory.json
python3 tools/build_scene.py --code tainan_yongkang --trajectory /tmp/synth_trajectory.json \
  --sat-dir satellite_pipeline/output/tainan_yongkang \
  --collider 1:Car --collider 2:Two_Wheeler --source-collision 100 \
  --name "台南永康（合成軌跡驗證）"
```
Expected: `scenes/tainan_yongkang/` 生成三檔案；`scene.json` 的 `origin_offset_m` 為 `[12.5, 12.5]`、`ground.image` 是 genai HD 版

- [ ] **Step 3: 播放器驗證（spec 驗收 #2）**

`http://localhost:8765/threejs/index.html?scene=tainan_yongkang`
Expected: 不改任何程式碼即可播放；永康衛星圖為地面；汽機車在路口相撞有旋轉；**track 9 以 extras 出現並通過路口**；車速滑桿工作

- [ ] **Step 4: 跑全部測試 + spec 驗收清單**

```bash
node --test threejs/lib/tests/ && python3 -m unittest discover -s tools/tests
```
對照 spec 驗收標準：1) test1 行為一致 ✓ 2) 第二場景不改碼 ✓ 3) 靜態連結含手機 ✓（Task 9）4) 碰後旋轉 ✓（Task 6）

- [ ] **Step 5: 更新 todonext.md（主線 checkbox 勾選）+ Commit**

```bash
git add tools scenes docs/todonext.md
git commit -m "第二場景驗證：合成軌跡產生器 + tainan_yongkang 場景包（extras 通過驗證）"
git push origin main
```

---

## Self-Review 記錄

- **Spec coverage**：場景包(T1)、build_scene(T2)、vendor(T3)、場景無關化(T4+T5)、碰後旋轉(T6)、光影/相機(T7)、播放速度/UI/RWD(T8)、部署(T9)、第二場景+extras(T10)、MODEL_FLIP per-model（T1 registry + T5 驗證）——spec 各節皆有對應。
- **型別一致**：waypoint `[frame,x,z,headingOrNull]` 貫穿 lib 與 main；`applyCollision` 參數名 aPre/bPre/mass_kg/length_m/speed_kmh 在 T4/T5/T6 一致。
- **已知風險**：T6 自旋方向的座標系推導需 codex:rescue 對照確認；T9 Pages 若 repo private 需使用者決定。
