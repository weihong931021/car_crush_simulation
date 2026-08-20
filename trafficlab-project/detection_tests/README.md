# Detection Tests — 車輛辨識模型評測

把「增加辨識」相關的測試從 vendored 的 `trafficlab-project/` 搬出來，集中在這裡，避免污染上游 repo。

## 內容

```
detection_tests/
├── viz_model_compare.py     # 並排比較腳本：baseline vs fine-tune
├── outputs/
│   ├── test1_model_compare.mp4        # 整段 168 frames 並排影片（左原本 / 右 tune 完）
│   ├── test1_motor_compare_f104.png   # frame 104 機車區裁切對比（標籤清楚）
│   └── test1_compare_full_f104.png    # frame 104 完整幀對比
└── README.md
```

## 怎麼跑

預設路徑已指回 `trafficlab-project/`（footage + 模型），可直接無參數執行：

```bash
/Users/weihong/Documents/littering_prediction/venv/bin/python \
    detection_tests/viz_model_compare.py
```

常用參數：`--no-video`（只印統計）、`--max-frames N`、`--conf 0.25`、`--imgsz 736`、
`--left/--right`（換模型）、`--footage`、`--output`。

## 測試結果（2026-06-06）

`yolo11l-visdrone-ft.pt`（Colab 50ep，mAP50=0.400）vs 原本 COCO base `yolo11l.pt`，
跑 `test1.mp4`（路口 CCTV，168 frames，conf 0.25 / imgsz 736）：

| 類別 | 原本 COCO yolo11l | tune 完 VisDrone-ft | 差異 |
|---|---|---|---|
| 二輪 (motor+bicycle) | 10 | 214 | **×21** |
| 機車 motor | 10 | 210 | ×21 |
| 汽車 car | 425 (conf 0.761) | 434 (conf 0.790) | +9, 信心↑ |
| 誤報 | 紅綠燈 ×337、火車 ×2 | 無（純車輛語彙） | — |

**結論**：fine-tune 在機車辨識上壓倒性勝出，汽車也小幅進步且信心更高，並消除了 COCO 的
無關類別噪音。對事故重建（需準確抓機車軌跡）是實打實的提升。

最佳示範幀 frame 104：原本 COCO 抓 0 台二輪、tune 完抓 4 台（3 motor + 1 bicycle）。

## 備註

- fine-tune 模型本體仍在 `trafficlab-project/models/yolo11l-visdrone-ft.pt`（pipeline 讀取位置），
  此處只放評測腳本與輸出。
- 之前 pipeline 用的舊 VisDrone 模型（yolo11s-visdrone-v2-ft）本機與 Google Drive 皆已不存在，
  故 baseline 只能比 fine-tune 的起點 COCO `yolo11l.pt`。
- Python 環境：`/Users/weihong/Documents/littering_prediction/venv/bin/python`。
