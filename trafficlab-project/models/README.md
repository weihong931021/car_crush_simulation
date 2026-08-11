```
TrafficLab-3D/
├── location/
│   └── {location_code}/
│       ├── footage/
│       │   └── *.mp4
│       │
│       ├── illustrator/                 (optional, Adobe Illustrator assets)
│       │   ├── layout_{location_code}.ai
│       │   ├── roi_{location_code}.ai
│       │   └── *.ai
│       │
│       ├── G_projection_{location_code}.json
│       ├── cctv_{location_code}.png     (critical!)
│       ├── sat_{location_code}.png      (critical!)
│       ├── layout_{location_code}.svg   (optional)
│       └── roi_{location_code}.png      (optional)
│
├── media/                               (resources for README and Introduction tab)
│
├── gui/                                 (GUI implementation)
│
├── models/                              (object detection & tracker models)
│   └── *.pt                             (YOLO checkpoints)
│
├── output/
│   └── model-{model_name}_tracker-{tracker_name}/
│       └── {config-name}/
│           └── {location_code}/
│               └── *.json.gz             (inference outputs)
│
├── environment.yml
├── inference_config.yaml
├── prior_dimensions.json
└── main.py
```

## 模型角色

此目錄的 `.pt` 權重是 TrafficLab 的 **2D detector**。目前
`trafficlab/inference/pipeline.py` 直接以 Ultralytics `YOLO(weights)` 載入模型，並使用
`model.track()` 取得每幀的 bounding box、類別、信心值與 `tracked_id`。要替換這裡的權重，
新模型必須提供相同資訊，或先實作一層相容的 detector／tracker adapter。

## NVIDIA Asset Harvester 不是 detector 權重

[NVIDIA Asset Harvester](https://github.com/NVIDIA/asset-harvester) 的 checkpoint 不能直接填入
`inference_config.yaml` 的 `model.weights`。它接收已裁切並帶有前景遮罩的物件影像，輸出
3D Gaussian Splat `.ply`，不會從完整影片提供逐幀偵測框或 `tracked_id`。

建議保留現有 YOLO／ByteTrack 流程，把 Asset Harvester 放在辨識之後：

```text
YOLO + tracker
  → 依 tracked_id 收集最佳物件裁圖
  → Asset Harvester（獨立雲端 GPU 工作）
  → gaussians.ply
  → Three.js／Blender
```

官方完整推論約需 16 GB NVIDIA GPU VRAM、CUDA 12.8。CPU offload 只是降低不同階段的顯存
占用，不能把完整 Gaussian lifting 變成純 CPU 推論。無本機 NVIDIA GPU 時，可先使用
[官方 Demo](https://huggingface.co/spaces/nvidia/asset-harvester) 做少量驗證。

紅綠燈的偵測與紅／黃／綠狀態判斷仍需另外的 detector／classifier；Asset Harvester
最多只負責在物件已被定位後嘗試建立 3D 外觀。
