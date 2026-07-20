# 行車事故影片重建 3D 模型

將碎片化素材（手機影片、低畫質監控）利用 AI 快速重建為 3D 碰撞動畫，協助釐清責任、輔助司法判決。

## Pipeline

```text
CCTV 影片 (.mp4)
    ↓  [TrafficLab：校正 + 推論]（偵測品質由隊友主導）
trafficlab-project/output/*.json.gz（所有車輛軌跡）
    ↓  [filter_and_enrich_output.py：篩選 + 補欄位]
軌跡 JSON（含 position_m / velocity_mps）＋ satellite_pipeline 衛星地面圖
    ↓  [tools/build_scene.py：半自動產生場景包]（實作中）
scenes/<code>/（scene.json + ground.png + trajectory.json）
    ↓  [Three.js 播放器：JS 碰撞物理 + 互動 UI]
可分享的網頁 demo（Blender 高品質渲染供出版，第二階段）
```

當前方向見 [docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md](docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md)。

## 資料夾結構

```text
blender_crash_project/
├── CLAUDE.md                       ← Claude 行為指令
├── README.md
├── index.html                      ← 根目錄轉址至 threejs/index.html
├── docs/
│   ├── specs/                      ← 設計文件（含當前方向 spec）
│   ├── papers/                     ← 外部參考文獻 PDF
│   ├── PROJECT.md                  ← 專案總覽、競品分析、已知風險
│   ├── todonext.md                 ← 待辦清單
│   ├── reference.md                ← 座標轉換、車規、時間軸快速參考
│   ├── blender_sat_plane.md        ← 衛星圖貼地板平面的完整步驟
│   ├── blender_to_threejs.md       ← Blender → Three.js 遷移指南
│   ├── filter_and_enrich_output.md ← filter_and_enrich_output.py 使用說明
│   ├── video-processing-commands.md ← yt-dlp / ffmpeg / RIFE 指令速查
│   └── *.pdf
├── scenes/                         ← 場景包（scene.json + ground.png + trajectory.json）
├── tools/                          ← build_scene.py 場景包產生器
├── satellite_pipeline/            ← 衛星底圖自動化（lat/lon → 去車 → 貼 Blender）
│   ├── pipeline.py                ← 一鍵流程
│   ├── map_capture.py             ← Google Static API 擷取
│   ├── image_enhance.py           ← Gemini 去車 + 銳化 / --genai HD
│   ├── blender_ground.py          ← 產生 Blender 貼地腳本
│   ├── models/FSRCNN_x4.pb        ← 超解析模型（gitignored）
│   └── output/<code>/             ← sat_raw / sat_clean / sat_genai / meta.json
├── blender_scripts/                ← 現役：模型匯入、縮放、貼地（出版渲染用）
│   ├── vehicle_specs.py
│   ├── import_vehicle.py
│   └── snap_to_ground.py
├── archive/blender_scripts/        ← 淘汰腳本（import_tesla、setup_crash rigid body 版）
├── archive/images/                 ← 淘汰衛星圖版本 + 開發過程驗證截圖
├── detection_tests/                ← VisDrone fine-tune vs COCO 驗收實驗
├── threejs/
│   ├── index.html                  ← Three.js r165，播放控制 UI
│   ├── main.js
│   ├── car.glb
│   └── moto.glb
└── trafficlab-project/             ← 上游 Pipeline（CCTV → 軌跡；偵測優化由隊友主導）
    ├── main.py                     ← GUI 入口
    ├── location/test1/             ← 校正資料（G_projection、cctv/sat 對照圖）
    ├── scripts/                    ← filter_and_enrich_output.py、run_inference.py 等
    ├── output/                     ← 推論輸出 *.json.gz
    ├── models/                     ← YOLO 權重（yolo11l-visdrone-ft.pt 已就位）
    ├── trafficlab/                 ← 核心函式庫
    └── inference_config.yaml
```

## 啟動方式

```bash
# Three.js 預覽（從專案根目錄）
python3 -m http.server 8765
# → http://localhost:8765/threejs/index.html

# Blender MCP
uvx blender-mcp --port 9876

# TrafficLab GUI（trafficlab conda env 不存在，用 littering_prediction 的 venv）
PYTORCH_ENABLE_MPS_FALLBACK=1 /Users/weihong/Documents/littering_prediction/venv/bin/python trafficlab-project/main.py
```
