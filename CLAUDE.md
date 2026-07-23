# Claude 行為指令

專案文件見 [README.md](README.md)；座標、車規、指令見 [docs/reference.md](docs/reference.md)。

---

## 當前工作方向（2026-07-20 起）

**組件整合優先，Three.js 是最終呈現。** 偵測／軌跡品質由隊友主導，不做 inference 優化。
完整設計見 `docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md`。

1. **場景包**：每個事故場景一個 `scenes/<code>/`（scene.json + ground.png + trajectory.json），
   `main.js` 的硬綁常數（OFFSET、track ID、圖路徑）全數遷入
2. **`tools/build_scene.py`**：軌跡 JSON + satellite_pipeline 輸出 → 半自動產生場景包
3. **Three.js 播放器**：物理留在 JS（保住互動調車速）、加碰後旋轉、光影、相機 preset、
   播放速度、本地 vendor + 靜態部署
4. **Blender 退居出版渲染**（第二階段：讀同一份 scene.json 自動搭渲染場景）

### 碰撞物理（已模組化在 `threejs/lib/`，不要重新推導）

spec：`docs/specs/2026-07-20-collision-simulation-design.md`。前向模擬 + OBB SAT 偵測 +
衝量（含切向摩擦、真實接觸點、完整力臂 `(r×J)_y = r_z·J_x − r_x·J_z`、`I=mL²/12`）。

- `path.js` 弧長參數化／速度剖面、`obb.js` SAT、`simulate.js` 迭代接觸解算、
  `solve.js` 安全速度區間（交會事故無單一門檻，回傳 slowerK/fasterK 區間）
- 座標約定：`heading = atan2(dx, dz)`、前向 `(sin h, cos h)`、rotation.y 右手系
- 測試：`node --test threejs/lib/tests/*.test.js`（目錄形式會失敗，必用 glob）

**產品決定（2026-07 內部會議）**：demo 呈現到碰撞瞬間為止，碰後彈開不播
（`main.js` 以 impactTime 截斷；物理照算，要恢復播放拿掉 cutT 即可）。

**資料陷阱**：追蹤器位置在碰撞前 0.5s 會凍結（bbox 重疊+平滑假象），位移回推的
絕對速度不可靠——UI 滑桿因此用「實錄剖面倍率 ×k」語意，km/h 僅供參考顯示。

---

## 何時主動用 Codex

遇到以下情況**不等使用者說**，直接用 `codex:rescue` skill：

- 設計或修改 Blender Python 腳本（物理、動畫、材質、scene setup）
- 設計或修改 Three.js 相關實作（物理、動畫、模型載入）
- 車輛比例、座標轉換、物理公式的計算邏輯
- 新功能有多種實作方向需要比較時

**怎麼用**：帶入當前場景設定、已知坑、目標，讓 Codex 直接產出實作，再和自己的做法比較，選最好的整合。

---

## 並行規則

| 可並行 | 不可並行 |
| --- | --- |
| 同一事故的多視角場景 | 同一 Blender session 內的步驟（共用 MCP 連線） |
| Track A 軌跡計算 + Track B 場景初始化 | 模型下載 → 複製 → 動畫（有先後依賴） |

---

## Blender 必記的坑

- **Tesla 前端朝 +Y**（本地座標）→ 正面對撞：靜止車 `Z-rot=180°`，撞擊車 `Z-rot=0°`
- **Sketchfab 匯入根物件預設 QUATERNION**：設 euler 前必須先 `obj.rotation_mode = 'XYZ'`
- **複製 hierarchy**：要先 `select children_recursive` 再 duplicate，否則只複製根節點
- **Blender 5.x Action API**：用 `action.layers[0].strips[0].channelbag(slot).fcurves` 存取 fcurves
- **UV 展開**：不能用 `bpy.ops.uv.unwrap()`，要用 `bpy.ops.uv.reset()`
- **Sketchfab 模型縮放不準**：MCP 的 `target_size` 是估算值，匯入後必須用 `scale_to_length()` 依 bounding box 精確重新縮放

## Three.js 必記的坑

- **GLB 匯出用 `export_apply=False`**：`export_apply=True` 會把 transform bake 進頂點，Three.js 內位置跑掉
- **GLTF 座標轉換**：Blender +Y（前方）→ GLTF -Z → Three.js -Z，載入後需 `gltfScene.rotation.y = Math.PI`
- **Bounding box centering**：`Box3.setFromObject()` 讀 stale matrix。先算 rotation 前的 bbox center `(cx, cz)` 和 `minY`，再 `gltfScene.position.set(cx, -minY, cz)`
- **Heading drift**：不要插值 heading 欄位，要從 segment 的 `(dx, dz)` 動態算 `atan2(dx, dz)`

## TrafficLab 必記的坑

- **Apple Silicon MPS + half precision**：推論失敗先確認 `inference_config.yaml` 的 `half: false`
- **Python 環境**：`trafficlab` conda env 不存在，改用 `/Users/weihong/Documents/littering_prediction/venv/bin/python`（有 ultralytics, supervision, opencv）
- **MPS 訓練 bug**：Python 3.14 + PyTorch + MPS 在 tal.py loss 計算會 shape mismatch crash，訓練必須用 `device="cpu"` 或 Colab GPU
- **G-projection 路徑**：推論讀 `location/<code>/G_projection_<code>.json` 或 `G_projection_svg_<code>.json`
- **supervision 0.28.0**：`InferenceSlicer` 用 `overlap_wh=100`（不是 `overlap_ratio_wh`）；`ByteTrack` deprecated 但還能用

---

## TrafficLab 偵測優化進度（trafficlab-project/）

> **2026-07-20 起凍結**：偵測／軌跡優化由隊友主導（他們的結果更好），本 repo 不再投入。
> 以下保留為記錄與參考。

### 已實作

- **bbox quality filter**（`pipeline.py:_is_valid_detection`）：`min_conf=0.45`、`min_area_px=400`、`aspect_ratio 0.4–4.0`，在 `inference_config.yaml` `detection_filter` 段落控制
- **視覺化腳本**：
  - `scripts/viz_detection_filter.py` — 顯示哪些框被過濾
  - `scripts/viz_slicer_compare.py` — InferenceSlicer vs 全圖推論對比
  - `scripts/viz_rife_compare.py` — 原始 25fps vs RIFE 4x 對比

### VisDrone Fine-tune ✅ 完成且驗收通過

- **Colab notebook**：`scripts/colab_train_visdrone.ipynb`，T4 GPU
- **結果**（2026-06-06，50 epochs）：mAP50=0.400，mAP50-95=0.228，val loss 在 epoch 25–30 平台
- **模型位置**：`trafficlab-project/models/yolo11l-visdrone-ft.pt`（勿與 `models/training/` 內
  epoch 21 的本地未完成訓練混淆）
- **驗收**（2026-06-06，`detection_tests/`）：二輪偵測 10→214（×21）、汽車信心 0.761→0.790、
  COCO 的 337 個紅綠燈誤報消失。比較影片與對比圖在 `detection_tests/outputs/`
- 註：`inference_config.yaml` 各 config 的 weights 仍指向不存在的舊模型檔，若隊友要在本機跑
  推論需先改指 `./models/yolo11l-visdrone-ft.pt`

### 測試結果摘要

| 方法 | 效果 | 結論 |
| --- | --- | --- |
| conf 門檻調整 | -24% 框（多為噪音） | 已加入 config |
| InferenceSlicer（640px patch） | +15% 軌跡數 | 可選，腳本已備 |
| RIFE 4x 補幀 | +8% 但偵測品質**下降** | **不用**，AI 生成幀干擾 YOLO |
| VisDrone fine-tune | 二輪 ×21、汽車信心 +0.03 | ✅ 驗收通過，見 `detection_tests/` |

### 已寫好但未啟用的功能

- `MotorcycleLateralCorrector`（`lateral_correction.enabled: false`）
- `MotorcycleMotionFilter`（`motorcycle_filter.enabled: false`）

---

## TrafficLab-3D 2D→3D 優化方向（/Documents/TrafficLab-3D）

> **同樣凍結**（隊友主導）。問題根源：YOLO bbox 噪音 + 幾幀沒偵測到 → 軌跡抖動、heading 亂跳

### 偵測改進

- `yolo11l.pt`（COCO）對轎車偵測良好（conf ≈ 0.90），機車容易漏
- `yolo11l-obb.pt`（DOTA）**不適用**：鏡頭斜角透視，機車被誤判為 ship
- **RIFE 補幀不適用於偵測改進**：AI 生成幀讓 YOLO 品質下降，已測試確認

### 軌跡穩定（Kalman Filter，尚未實作）

設計文件：`TrafficLab-3D/docs/superpowers/specs/2026-05-25-trajectory-stabilization-design.md`

需改動三個檔案：

1. `trafficlab/inference/pipeline.py` — 加 missing-frame predict loop
2. `trafficlab/motion/kinematics.py` — 加 2D Kalman Filter（state: x, y, vx, vy）+ innovation gate
3. `inference_config.yaml` — 加 `kalman_*` 參數

Kalman 關鍵參數：`kalman_process_noise=0.1`、`kalman_measure_noise=2.0`、`kalman_gate_threshold=3.5`

---

## 待辦（詳見 docs/todonext.md）

主線＝場景包 demo（spec：`docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md`）：

- [ ] `scenes/test1/` 場景包 + scene.json schema 定案
- [ ] `tools/build_scene.py` 半自動場景包產生器
- [ ] Three.js 播放器改造：讀場景包、碰後旋轉、光影、相機 preset、播放速度、本地 vendor
- [ ] 確認 car.glb / moto.glb 各自的前方軸向，MODEL_FLIP 改 per-model 設定
- [ ] 靜態部署（丟連結就能看，含手機）
- [ ] 第二場景驗證（satellite_pipeline 既有地點 + 合成軌跡）

第二階段：Blender 讀 scene.json 自動搭渲染場景（出版用）。
凍結（隊友主導）：TrafficLab inference config、Kalman、Motorcycle 濾波器。
