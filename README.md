# 行車事故影片重建 3D 模型

將碎片化素材（手機影片、低畫質監控）利用 AI 快速重建為 3D 碰撞動畫，協助釐清責任、輔助司法判決。

## Pipeline

```text
CCTV 影片 (.mp4)
    ↓  [TrafficLab：校正 + 推論]
trafficlab-project/output/*.json.gz（所有車輛軌跡）
    ↓  [filter_and_enrich_output.py：篩選 + 補欄位]
data/filtered_output.json（目標車輛，含 position_m / velocity_mps）
    ↓  [Three.js 動畫 / Blender MCP]
3D 碰撞動畫
```

## 資料夾結構

```text
blender_crash_project/
├── CLAUDE.md                       ← Claude 行為指令
├── README.md
├── docs/
│   ├── PROJECT.md                  ← 專案總覽、競品分析、已知風險
│   ├── todonext.md                 ← 待辦清單
│   ├── reference.md                ← 座標轉換、車規、時間軸快速參考
│   ├── blender_sat_plane.md        ← 衛星圖貼地板平面的完整步驟
│   ├── blender_to_threejs.md       ← Blender → Three.js 遷移指南
│   ├── filter_and_enrich_output.md ← filter_and_enrich_output.py 使用說明
│   └── 行車事故影片重建3d模型.pdf
├── data/
│   ├── filtered_output.json        ← 已篩選 + 補欄位的軌跡資料（含 sat_center）
│   └── road_features.json
├── images/
│   ├── image.png                   ← 主要衛星圖（銳化版），1515×1038 px
│   ├── sat_bw.png
│   └── screenshots/
├── paper/                          ← 學術參考論文
├── satellite_pipeline/            ← 衛星底圖自動化（lat/lon → 去車 → 貼 Blender）
│   ├── pipeline.py                ← 一鍵流程
│   ├── map_capture.py             ← Google Static API 擷取
│   ├── image_enhance.py           ← Gemini 去車 + 銳化
│   ├── blender_ground.py          ← 貼 Blender 地板（MCP）
│   └── output/<code>/             ← sat_raw / sat_clean / meta.json
├── blender_scripts/
│   ├── vehicle_specs.py
│   ├── import_vehicle.py
│   ├── setup_crash.py
│   └── snap_to_ground.py
├── threejs/
│   ├── index.html                  ← Three.js r165，播放控制 UI
│   ├── main.js
│   ├── car.glb
│   └── moto.glb
└── trafficlab-project/             ← 上游 Pipeline（CCTV → 軌跡）
    ├── AGENTS.md
    ├── main.py                     ← GUI 入口
    ├── location/test1/
    │   ├── footage/                ← CCTV 原始影片
    │   ├── G_projection_test1.json
    │   ├── cctv_test1.png
    │   └── sat_test1.png
    ├── scripts/
    │   ├── filter_and_enrich_output.py
    │   ├── run_inference.py
    │   └── trajectory_tools.py
    ├── output/                     ← 推論輸出 *.json.gz
    ├── models/                     ← YOLO 模型權重
    ├── trafficlab/                 ← 核心函式庫
    ├── environment.yml
    └── inference_config.yaml
```

## 啟動方式

```bash
# Three.js 預覽（從專案根目錄）
python3 -m http.server 8765
# → http://localhost:8765/threejs/index.html

# Blender MCP
uvx blender-mcp --port 9876

# TrafficLab GUI
conda activate trafficlab
PYTORCH_ENABLE_MPS_FALLBACK=1 python trafficlab-project/main.py
```
