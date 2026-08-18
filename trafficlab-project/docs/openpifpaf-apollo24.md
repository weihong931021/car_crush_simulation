# OpenPifPaf Apollo-24 車輛關鍵點定位

用 OpenPifPaf 的 `shufflenetv2k16-apollo-24` checkpoint 偵測車輛 24 個 keypoints，
配合每個 keypoint 的高度先驗把它投影到衛星座標，再擬合出車輛中心與朝向，
輸出 TrafficLab GUI 可讀的 replay JSON。

原始說明由路徑辨識負責人提供；本文件已改寫為**這個 repo 實際驗證過**的版本
（原稿的 conda 路徑與 `models/best.pt` 在本機都不存在）。

---

## 1. 執行環境（必須另建，不能用既有 venv）

`openpifpaf==0.13.11` 在 PyPI **只有原始碼、沒有任何 wheel**，且 `setup.py` 硬綁
`torch==1.13.1`，必須用 Python 3.10 自行編譯。既有的
`/Users/weihong/Documents/littering_prediction/venv`（Python 3.14 + torch 2.9）無法使用。

環境已建好在 `trafficlab-project/.venv-pifpaf/`（已加入 `.gitignore`）。重建步驟：

```bash
cd trafficlab-project
UV=/Users/weihong/.langflow/uv/uv

$UV venv --python 3.10 .venv-pifpaf
export VIRTUAL_ENV=$PWD/.venv-pifpaf

$UV pip install "torch==1.13.1" "torchvision==0.14.1" "numpy<2" \
                "pillow!=8.3.0" "opencv-python<4.10" wheel
$UV pip install "setuptools==65.5.1"           # 見下方坑 1
$UV pip install --no-build-isolation "openpifpaf==0.13.11"
$UV pip install ultralytics "lap>=0.5.12" pip  # 見下方坑 2、3
```

### 建置的三個坑

1. **`setuptools` 必須降到 65.5.1。** setuptools 81+ 移除了 `pkg_resources`，
   而 torch 1.13.1 的 `torch/utils/cpp_extension.py` 第 25 行 `from pkg_resources import packaging`
   會直接 `ModuleNotFoundError`，openpifpaf 的 C++ extension 就編不起來。
2. **`--no-build-isolation` 是必要的**：openpifpaf 建置時要 import 已安裝的 torch
   來編 `openpifpaf._cpp`，隔離環境裡沒有 torch。
3. **ByteTrack 需要 `lap`，而且要手動裝。** ultralytics 會嘗試自動 `pip install lap`，
   但 uv 建的環境預設沒有 pip，自動安裝失敗會讓 `model.track()` 整個炸掉。

ultralytics 8.4 在 torch 1.13.1 下可正常載入 YOLO 權重與跑 ByteTrack，不會被迫升級 torch。

---

## 2. 輸入

| 項目 | 路徑 |
|---|---|
| 影片 | `location/<code>/footage/<code>.mp4` |
| 投影檔 | `location/<code>/G_projection_<code>.json` |
| checkpoint | `models/shufflenetv2k16-201113-135121-apollo.pkl.epoch290` |
| YOLO（track ID 用） | `models/yolo11l-visdrone-ft.pt`，**car = class 3** |

本機 checkpoint 檔就是 `--checkpoint shufflenetv2k16-apollo-24` 會去下載的同一個檔
（openpifpaf 的 `CHECKPOINT_URLS` 指向 DuncanZauss/openpifpaf_assets 上的同名檔），
指定本地路徑只是免去每次下載。

> **原稿的 `--yolo models/best.pt` 在本機不存在。** 從參數 hint「e.g. "3" for car」可確認
> 隊友的 `best.pt` 是 VisDrone fine-tune 模型，本機對應的是 `models/yolo11l-visdrone-ft.pt`
> （class map：`0 pedestrian, 1 people, 2 bicycle, 3 car, 4 van, 5 truck, 6 tricycle,
> 7 awning-tricycle, 8 bus, 9 motor`）。注意 COCO 的 car 是 2、VisDrone 是 3，別搞混。

---

## 3. 執行

```bash
cd trafficlab-project

PYTORCH_ENABLE_MPS_FALLBACK=1 .venv-pifpaf/bin/python scripts/eval_haware_replay.py \
  --video   location/taipei-cm/footage/taipei-cm.mp4 \
  --g-proj  location/taipei-cm/G_projection_taipei-cm.json \
  --method  geometric \
  --yolo    models/yolo11l-visdrone-ft.pt --yolo-classes 3 \
  --checkpoint models/shufflenetv2k16-201113-135121-apollo.pkl.epoch290
```

`--method geometric` 用 YOLO bbox 的 IoU 把 PifPaf 偵測結果橋接到 track ID。
只想跑 PifPaf、不要 track ID 的話加 `--yolo ""`（此時 `tracked_id` 全為 null）。

跑在 CPU 上（torch 1.13.1 的 MPS 對 openpifpaf 不穩），約 **1.5–2.5 秒／幀 @1080p**。

### 常用參數

| 參數 | 用途 |
|---|---|
| `--frames 100` | 只跑前 100 幀做測試 |
| `--start-frame 500` | 從第 500 幀開始 |
| `--kp-conf 0.2` | keypoint 信心門檻 |
| `--localizer procrustes\|reprojection` | 定位演算法，見 §5 |
| `--out path/to/out.json.gz` | 指定輸出路徑 |

### 輸出

預設 `output/haware/<location_code>/<video_stem>.json.gz`，
標準 TrafficLab replay JSON，可直接在 GUI Visualization 載入。

每個 object 的欄位是 `pipeline.py` 的**嚴格超集**（多了 `n_keypoints`、`status`、
`method`、`kp_cctv`、`kp_sat` 五個診斷欄位），GUI 不會因缺欄位壞掉。但有兩個值得注意的行為：

- `bbox_3d` 恆為 `null` 而 `have_measurements` 恆為 `true`，會讓 GUI 自動勾選 3D 模式，
  結果 CCTV 面板兩種框都不畫（不是崩潰，把 3D 取消勾選就會畫 `bbox_2d`）。
- `speed_kmh` 恆為 `0.0`，GUI 直接照著顯示、不會自己重算。

---

## 4. 驗證輸出

```bash
.venv-pifpaf/bin/python scripts/viz_haware_replay.py \
  output/haware/taipei-cm/taipei-cm_procrustes.json.gz
```

印出每條 track 的品質表，並存一張軌跡圖（疊在 `sat_<code>.png` 上，含 FOV 多邊形）。

最重要的欄位是 **spread（keypoint 展開度）**：同一台車的 24 個 keypoint 投影到衛星平面後
應該落在約 4 公尺見方內，**展開度遠大於車長 3.8 m 就代表投影在外推**，該幀定位不可信。

---

## 5. 已知品質限制（taipei-cm 198 幀實測）

管線本身跑得通，但**目前的輸出品質只有近端車輛可用**。這是接下來要改善的重點。

一次完整跑批（198 幀，`--localizer procrustes`）：983 個 detection、820 個定位成功（83.4%）、
YOLO track ID 配對率 45.1%。八條 track 的品質差異極大：

| track | 幀數 | kp 中位數 | spread 中位數 | heading 抖動 | 幀間位移 | 判讀 |
| --- | --- | --- | --- | --- | --- | --- |
| 53 | 36 | 12 | **5.4 m** | **5.0°** | 0.37 m | **可用**，沿道路的乾淨軌跡 |
| 1 | 167 | 6 | 6.6 m | 23.0° | 0.29 m | 位置勉強，朝向抖 |
| 2 | 198 | 7 | 15.2 m | 3.9° | 0.04 m | 靜止車，位置穩但 spread 過大 |
| 3 | 183 | 10 | 25.7 m | 18.3° | 1.22 m | **不可用**，飛出 177 m |
| 4 / 31 / 50 / 63 | 2–11 | 4–9 | 10–430 m | — | — | 片段，無意義 |

**規律是距離，不是偵測品質。** track 3 有 10–12 個 keypoint（全場最好），卻定位到 177 公尺外：
它在畫面頂端（y≈130–240 px，近地平線），homography 在該處已經是外推，1 個 CCTV 像素橫跨數公尺。
反過來 track 53 只有 36 幀但全在路口近端，就給出 5.0° 抖動的乾淨軌跡。

判斷單幀是否可信看 **spread**（同一台車 24 個 keypoint 投影後的最大跨距）：
車長只有 3.8 m，spread 超過 8 m 基本上就是在外推。全跑批 820 個定位點裡有 244 個（30%）
落在校正範圍外。

> **落在衛星圖外 ≠ 算錯。** 衛星圖只是被映射平面的一小塊裁切 —— taipei-cm 的
> `fov_polygon` 範圍是 x 207…2379、y −1258…1177，而 `sat_taipei-cm.png` 只有 1190×1258。
> 要用 FOV 多邊形判斷，不是圖片邊界。

### `--localizer`：實測 procrustes 勝出，維持預設

| | procrustes | reprojection |
| --- | --- | --- |
| 定位成功率 | **83.4%**（820/983） | 67.0%（659/983） |
| track 1 heading 抖動 | **23.0°** | 39.1° |
| track 2 heading 抖動 | **3.9°** | 11.3° |
| track 53 heading 抖動 | **5.0°** | 7.1° |
| method 分布 | 不適用 | method 2 = 426、method 1 = 233 |

- `procrustes`（預設）：所有可信 keypoint 一次丟進固定尺度 2D Procrustes（SVD）擬合，
  只要 2 個 keypoint 就能出解，所以成功率高。
- `reprojection`：幾何中線交點法，用成對 keypoint（左右對稱對／同側前後輪對）的垂直平分線
  求交點。需要特定的**成對** keypoint 同時可見，配不到就直接失敗（324 幀 vs procrustes 的 163），
  且在這份資料上朝向反而更抖。輸出的 `method` 欄位記錄用了 1/2/3 哪一種分支。

### 關於 `z_cam_meters`（已排除的假設）

taipei-cm 的 `z_cam_meters = 3.60 m`，比 kee-cc（7.42）和 taoyuan-tc（7.39）低一倍，
一度懷疑是校正錯誤。用存下來的 `kp_cctv` 反掃相機高度（找 Procrustes 殘差極小值）後
**確認 3.6 m 是對的**：近端 track 1 的最佳值落在 3.3–4.0 m，正好涵蓋校正值；
把 z 改成 7.4 m 反而讓殘差從 1.6 m 惡化到 2.0 m。殘差大的原因是距離，不是相機高度。

### 下一步可以往哪裡改

1. **用 spread 當品質閘門**過濾掉外推幀，比事後平滑軌跡有效。
2. **track ID 配對率只有 45.1%**：track 4/5/6/7 完全配不到（IoU 全數失敗），
   代表 PifPaf 對這些車的 keypoint box 和 YOLO box 對不起來，可以調 `--iou-threshold`。
3. 近地平線的車可能根本不該送進定位 —— 用 `fov_polygon` 或 CCTV y 座標先擋掉。

---

## 6. 接到 Three.js 場景包（已驗證）

replay JSON 可以直接餵進既有的轉換腳本，產出 `tools/build_scene.py` 吃的 `trajectory.json`：

```bash
.venv-pifpaf/bin/python scripts/filter_and_enrich_output.py \
  output/haware/taipei-cm/taipei-cm_procrustes.json.gz \
  output/haware/taipei-cm/taipei-cm_trajectory.json \
  --ids 53 1 --prior-set measurements_visdrone
```

`filter_and_enrich_output.py` 會補上 `meta.px_per_meter`、每個 object 的
`position_m`（= `sat_coords / px_per_meter`）、`dimensions_m`、`velocity_mps`，
以及 `selected_tracked_ids`。`build_scene.py` 只看 `tracked_id` + `position_m`，
沒有 `position_m` 的 object 會被靜默丟掉。

實測 track 53 產出 36 個有效點，從 (9.16, 43.13) 走到 (16.88, 35.89)，
位移 10.6 m —— 形狀正確、可以直接進場景包。

> `--ids` 是必填的：這支腳本設計上就是挑幾條 track 出來做場景，不是全量轉換。
> 挑之前先用 `viz_haware_replay.py` 看哪幾條 track 的 spread 和 heading 抖動可以接受。

### 影片中繼資料的坑

`taipei-cm.mp4` 的 packet 時間戳從 −4.26 s 跑到 +4.30 s（共 198 幀 @23 fps ＝ 8.6 秒），
但容器的 `duration` 只寫 4.388 s —— 只涵蓋 pts ≥ 0 的後半段。
Finder／QuickTime／`mdls` 因此只顯示一半長度。

**以 frame index 為準的管線不受影響**（cv2 讀到的 `fps=23`、198 幀都是對的），
但如果之後有工具改用時間軸 seek，會踩到這個坑。

---

## 7. 檔案位置與孤兒參照

三個交接檔案已從 repo 根目錄的 `pifpaf/` 歸位：

| 檔案 | 專案內位置 |
|---|---|
| `eval_haware_replay.py` | `scripts/eval_haware_replay.py` |
| `haware_localization.py` | `trafficlab/motion/haware_localization.py` |
| `shufflenetv2k16-...epoch290` | `models/`（已 gitignore） |

程式碼註解引用了幾份**這個 repo 裡沒有**的文件與模組，是從隊友工作副本帶來的孤兒參照，
不影響執行，但要完整理解演算法得回頭跟他要：

- `docs/3d-keypoint-template-localization.md`（§3B，演算法出處）
- `docs/localization-methods.md`（method 1/2/3 的 tie-breaking 討論）
- `trafficlab/motion/wheel_localization.py`（`_TRACK_RATIO` / `_WHEELBASE_RATIO` 的來源）
- `scripts/eval_haware.py`（不寫 replay JSON 的版本）

### `prior_dimensions.json` 的搜尋路徑

`eval_haware_replay.py` 從 `--g-proj` 所在目錄往上找 5 層。場景包放在
`trafficlab-project/location/<code>/` 時走 `<code>/ → location/ → trafficlab-project/`
剛好找得到；**放在 repo 根目錄的 `location/` 則找不到**，會靜默退回內建 fallback 尺寸
（數值差 4 mm，但訊息會變成 `Using built-in fallback dims`）。這也是把場景包複製進
`trafficlab-project/location/` 而不是直接指向根目錄的原因。

檔案裡的 `car` 只有 `width/length/height`，沒有 `track_width`／`wheelbase`，
`build_car_template()` 會用 0.85／0.67 比例推算。
