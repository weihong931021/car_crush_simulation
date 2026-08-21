# 快速參考

## 座標轉換

軌跡 `position_m` → Three.js 世界座標，扣掉場景中心位移（`scene.json` 的 `origin_offset_m`）：

```js
// scenes/<code>/trajectory.json pos_m → Three.js（見 waypoints.js / main.js）
three_x = pos_m[0] - origin_offset_m[0]
three_z = pos_m[1] - origin_offset_m[1]   // 不取負號，south = +Z
```

test1：`origin_offset_m = [24.355, 16.68]`；`ground.png` 1515×1038 px、px_per_meter=31.10
（銳化版；G-projection 原圖 px_per_meter=34.41）。

## 動畫時間軸

- FIRST_FRAME=1，LAST_FRAME=89，30fps
- 碰撞在 **frame 32**
- Car（id=7）：frame 1 → 89，碰前速度 ~20 km/h
- Moto（id=373）：frame 21 → 89，碰前速度 ~40 km/h

## 車輛尺寸規格

尺寸真相只有一份：`tools/build_scene.py` 的 `CLASS_DEFAULTS` → 寫進 `scenes/*/scene.json`
的 `length_m`/`width_m`，播放器（`scene-loader.js` 驗證、`main.js` OBB 與 scale-to-length）
就讀這份。`length_m` 是模型縮放基準。

| 車種 | 長 (m) | 寬 (m) | 質量 (kg) |
|---|---|---|---|
| Car（轎車） | 4.69 | 1.85 | 1500 |
| Two_Wheeler（機車） | 1.85 | 0.70 | 200 |

> SUV/Van/Truck/Bus 目前都 fallback 到 car.glb（見 `registry.json` `class_fallback`），
> 尺寸沿用 Car；要細分再於 `CLASS_DEFAULTS` 補列。

## 模型資產來源

- car.glb = Tesla 2018 Model 3，Sketchfab UID `5ef9b845aaf44203b6d04e2c677e444f`
  （CC Attribution）。此類 provenance 記在 `frontend/player/models/registry.json` 的 `_comment_provenance`。

## TrafficLab 常用指令

```bash
# 推論（從 trafficlab-project/ 內執行）
# trafficlab conda env 不存在，用 littering_prediction 的 venv（有 ultralytics/supervision/opencv）
PY=/Users/weihong/Documents/littering_prediction/venv/bin/python
PYTORCH_ENABLE_MPS_FALLBACK=1 $PY scripts/run_inference.py \
  --config-name car_heading_smooth --location test1

# 篩選 + 補欄位 → 輸出到 scenes/test1/
$PY scripts/filter_and_enrich_output.py \
  output/model-*/car_heading_smooth/test1/*.json.gz \
  ../scenes/test1/trajectory.json \
  --ids 7 373 \
  --g-projection location/test1/G_projection_test1.json \
  --prior-dimensions prior_dimensions.json

# 軌跡平滑 + 繪圖
$PY scripts/trajectory_tools.py smooth-and-plot \
  output/example.json.gz --ids 7,373 --zoom-to-fit
```
