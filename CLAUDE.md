# Claude 行為指令

專案文件見 [README.md](README.md)；座標、車規、指令見 [docs/reference.md](docs/reference.md)。

---

## 當前工作方向

**Blender 優先，Three.js 是最終輸出。**

1. Blender：用 `filtered_output.json` 軌跡 + 物理公式做完整碰撞動畫（位置、方向、碰後路徑）
2. 物理公式決定碰後行為（動量守恆、角動量），不靠 Blender rigid body（太難控制）
3. 完成後匯出 GLB → Three.js 只做播放速度調整和 UI

### Blender 物理動畫流程

```text
filtered_output.json 軌跡（frame 1–32）
    ↓  碰撞前：直接從 position_m 轉換成 keyframe
frame 32：用動量公式算碰後初速和旋轉角
    ↓  碰撞後：等減速（摩擦力）+ 旋轉關鍵幀
frame 32–89：碰後滑行路徑
```

**碰撞物理公式**（每次用到直接查這裡）：

```python
# 動量守恆（斜角碰撞）
# m1, m2: 質量(kg), v1x/v1y, v2x/v2y: 碰前速度(m/s), e: 恢復係數(0=完全非彈, 1=完全彈)
# 正面撞（e≈0.1）: 大部分動能轉形變熱
v1_after = (m1 * v1 + m2 * v2 - m2 * e * (v1 - v2)) / (m1 + m2)
v2_after = (m1 * v1 + m2 * v2 + m1 * e * (v1 - v2)) / (m1 + m2)

# 旋轉（斜角碰撞有力臂時）
# I ≈ 1/12 * m * L²（長方體繞中心）
# α = torque / I, torque = F_perp * arm_length
```

**碰前速度換算**：`velocity_mps` 已在 `filtered_output.json`，直接用。

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
- **conda run 在沙盒環境失敗**：改用 `source activate trafficlab && python ...`
- **G-projection 路徑**：推論讀 `location/<code>/G_projection_<code>.json` 或 `G_projection_svg_<code>.json`

---

## TrafficLab-3D 2D→3D 優化方向（/Documents/TrafficLab-3D）

> 問題根源：YOLO bbox 噪音 + 幾幀沒偵測到 → 軌跡抖動、heading 亂跳

### 補幀前處理（機車偵測用）

**選定工具：`rife-ncnn-vulkan`**（不用 Python，Metal/Vulkan，macOS binary）

```bash
# 一次性下載（416MB）
curl -L -o rife.zip https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/rife-ncnn-vulkan-20221029-macos.zip
unzip rife.zip -d ~/tools/rife

# 4x 補幀（25fps → 100fps），讓快速機車不模糊
~/tools/rife/rife-ncnn-vulkan -i input.mp4 -o output_4x.mp4 -m rife-v4.6 -n 4
```

不用 Practical-RIFE（需 PyTorch，與現有 conda env 衝突風險）。
不用 FFmpeg minterpolate（非 AI，快速物體補幀品質差）。

### 偵測改進（已測試 test1.mp4）

- `yolo11l.pt`（COCO）對轎車偵測良好（conf ≈ 0.90），機車在 100fps 影片中 frame 333–560 有 112 幀偵測到
- `yolo11l-obb.pt`（DOTA）**不適用**此場景：鏡頭是斜角透視（非正射俯視），機車被誤判為 ship
- 偵測品質 filter 建議：`min_conf=0.45`、`min_area_px=400`、`aspect_ratio 0.4–4.0`

### 軌跡穩定（Kalman Filter）

設計文件：`TrafficLab-3D/docs/superpowers/specs/2026-05-25-trajectory-stabilization-design.md`

改動三個檔案：

1. `trafficlab/inference/pipeline.py` — 加 bbox quality filter + missing-frame predict loop
2. `trafficlab/motion/kinematics.py` — 加 2D Kalman Filter（state: x, y, vx, vy）+ innovation gate
3. `inference_config.yaml` — 加 `detection_filter` 和 `kalman_*` 參數

Kalman 關鍵參數：`kalman_process_noise=0.1`、`kalman_measure_noise=2.0`、`kalman_gate_threshold=3.5`

---

## 待辦（詳見 docs/todonext.md）

- [ ] 確認 car.glb / moto.glb 各自的前方軸向，修正 MODEL_FLIP 分開設定
- [ ] 寫 `blender-collision-physics` skill
- [ ] 測試斜角碰撞（T-bone、追尾偏轉）
- [ ] 接 Track A 軌跡格式 `[(frame, x, y, heading_deg)]` 注入 Blender 場景
- [ ] TrafficLab-3D：實作 Kalman + bbox filter（見設計文件）
- [ ] TrafficLab-3D：整合 rife-ncnn-vulkan 補幀到推論前處理
