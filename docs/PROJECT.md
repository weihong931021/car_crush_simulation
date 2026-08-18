# 行車事故影片重建 3D 模型

## 專案目標

將路人手機影片、低畫質監控等碎片化素材，利用 AI 快速重建為 3D 碰撞動畫，生成第一視角重現影片。

**核心用途**：協助釐清責任歸屬、為新聞報導提供事實根據、輔助司法判決。

---

## 現階段做法（2025-05）

### 整體架構

```
真實事故影片
    │
    ├── [Track A] 軌跡提取（陳柏衡）
    │       影片 → 2D 路線軌跡 → 車輛位置/速度序列
    │       現況：80% 可行，需優化影片品質與路徑線性化
    │
    └── [Track B] 碰撞場景重建（本專案核心）
            軌跡 JSON + 衛星圖 → tools/build_scene.py → 場景包
                → Three.js 播放器（JS 碰撞物理 + 互動 UI + 渲染）
                → 可分享的網頁 demo
```

> **架構演進**：早期 Track B 走 Claude Code + Blender MCP 生成碰撞動畫（POC 已驗證，
> 見下方「早期 Blender POC」）。2026-07 起改為**場景包驅動的 Three.js 網頁播放器**，
> 2026-08-05 全面轉 Three.js、移除 Blender 工具鏈。渲染與出版級畫面都在瀏覽器。

### Track B 技術細節（現行：Three.js）

- 物理模組化在 `threejs/lib/`（path/obb/simulate/solve/physics）：前向模擬 + OBB SAT +
  衝量，安全速度區間；播放器讀 `scenes/<code>/` 場景包，換場景零改碼
- 車輛 GLB 是 committed 資產（`threejs/models/`），`GLTFLoader` + `registry.json` 載入
- 驗證：`node --test threejs/lib/tests/*.test.js`、`node tools/verify_scenes.mjs`

**早期 Blender POC（已淘汰，保留為記錄）**：工具鏈 Claude Code CLI → Blender MCP →
Blender 5.x Python API。已驗證：Sketchfab 下載 Tesla Model 3
（UID `5ef9b845aaf44203b6d04e2c677e444f`）、複製 301 子物件 hierarchy、純 Y 軸正面碰撞
動畫、3-4 次對話完成 demo。踩過的坑：Cybertruck 誤搜需指定 UID、QUATERNION 根物件須先設
`rotation_mode='XYZ'`、Blender 5.x layered action API、Tesla 前端朝本地 +Y。
**這些只對重啟 Blender 路線有意義，現行網頁流程不需要。**

---

## Agents 策略

**適合並行的任務（可用 agents）**：
1. **多場景並行**：同一起事故的多視角場景包
2. **Track A + Track B 並行**：軌跡計算和場景初始化同時進行

**不適合並行的任務**：
- 產場景包 → verify_scenes 驗收（有先後依賴）
- 淨化管線各步（順序固定）

---

## 競品分析摘要

| 競品 | 優勢 | 劣勢 |
|------|------|------|
| Forensic Architecture | 學術公信力強 | 成本高、速度慢（1-2個月） |
| SITU Research | Space-Timeline 完整 | 需專業團隊 |
| NYT Visual Investigations | 手動 Blender 功夫扎實 | 無自動化，難複製 |
| Amped FIVE / TEMA | 0.01px 追蹤精度 | 主要用於工業/軍事鑑識 |
| D4RT (Google DeepMind) | 2D→3D 即時查詢 | 研究階段，非產品 |

**我們的差異化**：碎片化素材（手機、監控）+ AI 自動化 + 數小時內產出，針對新聞媒體速度需求。

---

## 已知風險與待驗證

| 項目 | 狀態 | 風險等級 |
|------|------|----------|
| 直線正面碰撞重建 | ✅ 已驗證 | 低 |
| 斜角碰撞（T-bone、追尾偏轉）| ⏳ 未測試 | 中 |
| Track A 軌跡 → 場景包 → Three.js 路徑整合 | ✅ 已驗證（test1/tainan_yongkang） | 低 |
| 複雜場景（多車、行人、障礙物）| ⏳ 未測試 | 高 |
| FoundationPose 碰撞後車體變形重建 | ❌ 技術限制 | 高（考慮 Dynamic 3DGS） |
| 整體品質依賴 Claude 模型表現 | ⚠️ 已知限制 | 中（現階段可控） |

---

## NVIDIA Asset Harvester 評估（2026-07-24）

### 結論

[NVIDIA Asset Harvester](https://github.com/NVIDIA/asset-harvester) 有機會加入本專案，
但它是 **image-to-3D 資產生成模型**，不是物件偵測或多物件追蹤模型，因此不能直接取代
TrafficLab 目前的 YOLO 權重。

TrafficLab 的偵測流程依賴 `YOLO.track()` 每幀提供：

- 2D bounding box
- 類別與信心值
- `tracked_id`

後續才使用這些資料進行地面投影、軌跡、速度與方向計算。Asset Harvester 的輸入則是
一至數張已裁切、置中並帶有前景遮罩的物件影像；輸出是完整物件的 3D Gaussian Splat
`gaussians.ply`。它不會從完整交通影片產生 TrafficLab 所需的逐幀偵測框、紅綠燈狀態
或 `tracked_id`。

### 建議整合位置

```text
事故影片
  → YOLO 偵測與追蹤
  → TrafficLab 投影、軌跡、速度與方向
  → 依 tracked_id 挑選 1–4 張清楚的物件畫面
  → 裁切與前景遮罩
  → 雲端 Asset Harvester
  → 每個物件的 Gaussian Splat .ply
  → Three.js 場景載入與快取
```

因此，Asset Harvester 適合作為「辨識完成後的 3D 外觀生成器」：

- YOLO 和追蹤器繼續負責車輛、機車等移動物件的辨識與身分連續性。
- 同一個 `tracked_id` 只需挑選少量最佳視角並生成一次 3D 資產，不應逐幀執行。
- 生成結果需以場景或 track 為單位快取，避免重複付費和等待。
- Three.js 現有的 `car.glb`／`moto.glb` 可保留為 fallback。
- Asset Harvester 輸出是 Gaussian Splat `.ply`，不是現有流程直接使用的 `.glb`；
  播放器需要 Gaussian Splat loader，或另行評估轉 mesh 的品質。

### 紅綠燈限制

Asset Harvester 不能判斷燈號是紅、黃或綠，也不是專門的燈桿偵測器。若要納入紅綠燈：

1. 使用另一個 detector 找出燈體或燈桿位置。
2. 使用小型分類器或規則判斷每幀燈號狀態。
3. 固定式燈桿只需建立一次 3D 資產並放入場景，不需要追蹤。
4. Asset Harvester 主要針對自駕場景中的車輛、行人、騎士等道路物件；用於細長燈桿屬於
   domain 外推，必須先用實際 CCTV 裁圖驗證品質。

### 權重與運算需求

官方開放的 checkpoint 包含：

- `AH_multiview_diffusion.safetensors`
- `AH_tokengs_lifting.safetensors`
- `AH_camera_estimator.safetensors`
- `AH_object_seg_jit.pt`

權重合計約 12.8 GB。官方環境要求 NVIDIA driver 570 以上、CUDA 12.8，完整
image-to-3D 推論約需 16 GB VRAM。`--offload_model_to_cpu` 只會在不同階段把暫時不用的
模型搬到 CPU 以降低顯存，不等於純 CPU 推論。

官方程式雖會在 CUDA 不存在時為部分模型選擇 `cpu`，但 TokenGS／Gaussian lifting
仍包含 CUDA 計時、同步與 CUDA `gsplat` 依賴。使用 `--skip_gs_lifting --precision fp32`
最多只能嘗試在 CPU 產生多視角圖片，無法得到最終 3D `.ply`，速度也不適合正式流程。
Apple Silicon MPS 目前沒有官方支援。

無本機 NVIDIA 顯卡時，可先使用
[官方 Hugging Face Demo](https://huggingface.co/spaces/nvidia/asset-harvester) 驗證少量裁圖；
批次或敏感事故素材則應使用私有雲端 NVIDIA GPU。事故影像上傳前應只保留必要的物件裁圖、
移除不相關人物與影像 metadata。

### 專案決策

- **不以 Asset Harvester 替換 TrafficLab detector／tracker。**
- 若實測品質可接受，將它規劃為獨立、可選的離線 3D asset generation stage。
- 第一個驗證目標應是同一台車的 1、2、4 張輸入比較，檢查幾何完整度、外觀一致性、
  執行時間與 Three.js 顯示方式。
- 紅綠燈辨識與燈號狀態另立模型，不綁定 Asset Harvester。

---

## 常用資源

**車輛模型資產來源**（provenance 記在 `threejs/models/registry.json` `_comment_provenance`）：
- car.glb = Tesla 2018 Model 3，Sketchfab UID `5ef9b845aaf44203b6d04e2c677e444f`
  （684K faces，CC Attribution）

**本地預覽**：`python3 -m http.server 8765` → `http://localhost:8765/threejs/index.html`
