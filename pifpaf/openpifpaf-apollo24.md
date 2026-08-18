# OpenPifPaf Apollo-24 最短使用說明

本專案使用 OpenPifPaf checkpoint `shufflenetv2k16-apollo-24` 偵測車輛 24 個 keypoints，並輸出 TrafficLab GUI 可讀的 replay JSON。

## 輸入

- 影片：`location/<location_code>/footage/*.mp4`
- 投影檔：`location/<location_code>/G_projection_<location_code>.json`
- checkpoint：`shufflenetv2k16-apollo-24`（預設值）

## 三個檔案放置位置

如果是從外部資料夾拿到這三個檔案，請放回專案中的以下位置：

| 檔案 | 專案內位置 |
|---|---|
| `eval_haware_replay.py` | `scripts/eval_haware_replay.py` |
| `haware_localization.py` | `trafficlab/motion/haware_localization.py` |
| `shufflenetv2k16-201113-135121-apollo.pkl.epoch290` | `models/shufflenetv2k16-201113-135121-apollo.pkl.epoch290` |

若使用本地 checkpoint 檔，執行時把 `--checkpoint` 改成 `models/shufflenetv2k16-201113-135121-apollo.pkl.epoch290`。

## 執行

```bash
source /Users/eric/opt/anaconda3/bin/activate trafficlab && \
PYTORCH_ENABLE_MPS_FALLBACK=1 python scripts/eval_haware_replay.py \
  --video location/test21/footage/test21-4.mp4 \
  --g-proj location/test21/G_projection_test21.json \
  --method geometric \
  --checkpoint shufflenetv2k16-apollo-24
```

`--method geometric` 會用 YOLO bbox 把 PifPaf 偵測結果橋接到 track ID。若只想跑 PifPaf，不要 track ID，可加：

```bash
--yolo ""
```

## 常用參數

| 參數 | 用途 |
|---|---|
| `--frames 100` | 只跑前 100 幀做測試 |
| `--start-frame 500` | 從第 500 幀開始 |
| `--kp-conf 0.2` | keypoint 信心門檻 |
| `--out path/to/out.json.gz` | 指定輸出路徑 |

## 輸出

預設輸出：

```text
output/haware/<location_code>/<video_stem>.json.gz
```

這是標準 TrafficLab replay JSON，可直接在 GUI Visualization 載入。
