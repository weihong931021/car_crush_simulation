# 快速參考

## 座標轉換

```python
# sat_test1.png pixel → Blender 世界座標（px_per_meter=34.41）
world_x = sat_x / 34.41 - 24.35
world_y = -(sat_y / 34.41 - 16.68)
```

```js
// filtered_output.json pos_m → Three.js
three_x = pos_m[0] - 24.35
three_z = pos_m[1] - 16.68   // 不取負號，south = +Z
```

衛星圖：`images/image.png`，1515×1038 px，px_per_meter=31.10（銳化版）
test1 G-projection：px_per_meter=34.41

## 動畫時間軸

- FIRST_FRAME=1，LAST_FRAME=89，30fps
- 碰撞在 **frame 32**
- Car（id=7）：frame 1 → 89，碰前速度 ~20 km/h
- Moto（id=373）：frame 21 → 89，碰前速度 ~40 km/h

## 車輛尺寸規格

`length_m` 是縮放基準；完整 `get_spec()` 見 `blender_scripts/vehicle_specs.py`。

| 車種 | 長 (m) | 寬 (m) | 高 (m) | 質量 (kg) |
|---|---|---|---|---|
| Car（轎車） | 3.8 | 1.8 | 1.55 | 1500 |
| Two_Wheeler（機車） | 1.7 | 0.6 | 1.6 | 200 |
| SUV | 4.7 | 1.9 | 1.65 | 2000 |
| Van（廂型車） | 5.2 | 2.0 | 2.0 | 2500 |
| Truck（大卡車） | 12.0 | 2.5 | 4.0 | 15000 |
| Bus（巴士） | 12.0 | 2.5 | 3.5 | 12000 |

## 常用 Sketchfab UID

- Tesla 2018 Model 3：`5ef9b845aaf44203b6d04e2c677e444f`（684K faces，CC Attribution）

## TrafficLab 常用指令

```bash
# 推論（從 trafficlab-project/ 內執行）
conda activate trafficlab
PYTORCH_ENABLE_MPS_FALLBACK=1 python scripts/run_inference.py \
  --config-name car_heading_smooth --location test1

# 篩選 + 補欄位 → 輸出到 data/
python scripts/filter_and_enrich_output.py \
  output/model-*/car_heading_smooth/test1/*.json.gz \
  ../data/filtered_output.json \
  --ids 7 373 \
  --g-projection location/test1/G_projection_test1.json \
  --prior-dimensions prior_dimensions.json

# 軌跡平滑 + 繪圖
python scripts/trajectory_tools.py smooth-and-plot \
  output/example.json.gz --ids 7,373 --zoom-to-fit
```
