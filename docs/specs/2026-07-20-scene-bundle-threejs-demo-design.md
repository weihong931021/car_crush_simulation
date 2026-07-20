# 場景包驅動的 Three.js 事故重建 Demo — 設計文件

日期：2026-07-20
狀態：已與使用者確認方向（方案 A），待實作

## 背景與目標

偵測／軌跡品質由隊友主導（他們的結果更好），本 repo 的價值在**把既有組件縫起來**：
軌跡 JSON、衛星圖 pipeline、車輛模型、Three.js 播放器 → 一條可重複、可換場景的 demo 產線。

出版素材已足夠，缺的是可展示的 demo。最終呈現以 **Three.js 網頁**為主，Blender 高品質渲染留給出版（第二階段）。

## 已確認的決策

| 問題 | 決定 |
| --- | --- |
| Demo 形式 | 網頁互動 demo 為主 + Blender 渲染供出版 |
| 場景範圍 | 換場景也能跑（scene-agnostic），test1 為第一個驗收場景 |
| 優化面向 | 視覺品質、動畫真實度、互動 UI、部署分享——四者皆要 |
| 架構 | **方案 A：Three.js 自足**。物理留在 JS（保住「調碰前車速→即時重算」的招牌互動），場景描述抽成 scene.json |
| 物理不進 Blender bake | bake 進 GLB 會殺死互動調速功能；Blender 消費端（讀同一份 scene.json 搭渲染場景）列為第二階段 |

## 架構

### 1. 場景包 `scenes/<code>/`（單一事實來源）

```text
scenes/test1/
├── scene.json        ← 場景描述（下方 schema）
├── ground.png        ← 衛星地面圖（取自 satellite_pipeline output，優先 genai HD 版）
└── trajectory.json   ← 軌跡資料（filtered_output.json 格式）
```

`scene.json` schema（草案，實作時可增欄位、不可含糊）：

```jsonc
{
  "code": "test1",
  "name": "台南 test1 汽機車碰撞",
  "ground": {
    "image": "ground.png",
    "px_per_meter": 31.10,        // 一律讀各圖自己的值，不共用常數
    "size_m": [48.71, 33.36]
  },
  "origin_offset_m": [24.35, 16.68], // 衛星圖座標 → 場景中心座標的平移
  "frames": { "source_range": [17, 885], "anim_range": [1, 89] },
  "vehicles": [
    { "track_id": 7,   "class": "Car",         "model": "car.glb",  "mass_kg": 1500, "role": "collider" },
    { "track_id": 373, "class": "Two_Wheeler", "model": "moto.glb", "mass_kg": 200,  "role": "collider" }
  ],
  "extras": "auto",                  // 其他 track：純軌跡跟隨播放（非物理）
  "collision": { "frame": 32, "participants": [7, 373], "restitution": 0.15, "friction": 0.7 },
  "cameras": { "default": "ortho_top" }  // 預設視角，其餘 preset 由 player 內建
}
```

現在硬綁在 `threejs/main.js` 的常數（OFFSET_X/Z、track ID 7/373、`../images/image.png`）全數遷入此檔。

### 2. `tools/build_scene.py`（半自動場景包產生器）

- **輸入**：軌跡 JSON、satellite_pipeline 輸出目錄（`meta.json` 含 px_per_meter）、人工參數（碰撞 frame、參與車 track_id 與車種）
- **自動**：origin offset（由地面圖尺寸推）、frame 映射、車輛清單建議（統計軌跡中的 class 與出現長度）
- **人工介入點**：只有「哪一幀撞、誰撞誰」——本來就該人判斷
- **輸出**：完整 `scenes/<code>/`，含 schema 驗證（缺欄位報明確錯誤）

### 3. Three.js 播放器改造（`threejs/`）

- **場景無關化**：`?scene=<code>` 載入場景包；collider 兩車跑 JS 物理，extras 純軌跡播放
- **動畫真實度**：碰後旋轉（動量公式 + 力臂 → 角速度，等角減速；公式沿用 CLAUDE.md）、碰撞瞬間視覺回饋（標記／可選慢動作）
- **視覺品質**：directional shadow + hemisphere 光、genai HD 地面、天空色/霧、相機 preset（頂視／45°／跟車）
- **互動 UI**：播放速度 0.25x–2x（新增）、視角切換（新增）；保留車速面板、時間軸 scrub
- **部署**：three.js 改本地 vendor（脫離 CDN）、整包靜態部署（GitHub Pages 或任意靜態主機）、基本 responsive

### 4. 模型庫（`threejs/models/`）

- `car.glb`、`moto.glb` 集中至 `threejs/models/`，`scene.json` 指名各車模型
- 車種→模型 fallback 表（如 SUV/Van 暫用 car.glb）
- 每個模型確認前方軸向，`MODEL_FLIP` 改 per-model 設定（解掉舊待辦）

### 5. 錯誤處理

- `scene.json` 載入時驗證，缺欄位顯示明確錯誤（不默默 fallback）
- 軌跡缺幀：線性補洞；模型載入失敗：以尺寸正確的色塊 box 代替並警示
- 現有 hardcoded fallback waypoints 移除（場景包就是資料來源）

## 目標資料夾架構

```text
blender_crash_project/
├── CLAUDE.md / README.md
├── docs/
│   ├── specs/                 ← 設計文件（本檔）
│   ├── papers/                ← 外部文獻（原 paper/）
│   └── *.md、*.pdf
├── scenes/                    ← [實作] 場景包，test1 為首例
├── tools/                     ← [實作] build_scene.py
├── threejs/                   ← 播放器 + vendor/ + models/
├── satellite_pipeline/        ← 衛星圖產線（含 models/FSRCNN_x4.pb）
├── blender_scripts/           ← 現役腳本（出版渲染用）
├── archive/blender_scripts/   ← 淘汰腳本（import_tesla.py、setup_crash.py）
├── detection_tests/           ← VisDrone 驗收實驗（已收錄）
├── data/、images/             ← [過渡] 遷入 scenes/test1 後移除
└── trafficlab-project/        ← 上游偵測（隊友主導，本 repo 僅參考）
```

## 驗收標準

1. `scenes/test1/` 建好後，播放器以 `?scene=test1` 載入，行為與現況一致（含車速調整）
2. 拿 satellite_pipeline 已有的另一地點 + 合成軌跡建第二個場景包，證明換場景不改程式碼
3. 靜態部署後，丟連結給別人（含手機）能直接開啟播放
4. 碰後旋轉視覺上合理（機車被撞後偏轉+自旋，不再只是平移滑行）

## 本階段不做

- Blender 消費端（讀 scene.json 自動搭渲染場景）——第二階段
- TrafficLab 偵測／Kalman／inference config 優化——隊友主導
- 三車以上碰撞物理（extras 僅軌跡播放）
- RIFE 補幀（已證實有害於偵測）

## 附：2026-07-20 資料夾整理記錄

- `paper/` → `docs/papers/`（外部文獻歸 docs）
- 根目錄《處理影片的終端機指令.pdf》→ `docs/`（與 video-processing-commands.md 同源）
- `blender_scripts/{import_tesla,setup_crash}.py` → `archive/blender_scripts/`（無引用；setup_crash 的 rigid body 方向已淘汰）
- `models/FSRCNN_x4.pb` → `satellite_pipeline/models/`（衛星圖超解析用，歸位後移除根目錄 models/）
- 刪除根目錄 `yolo11l-visdrone-ft.pt`（與 `trafficlab-project/models/` 內 md5 相同的重複檔）
- 收錄未追蹤成果：`detection_tests/`、`docs/video-processing-commands.md`、Colab notebook
