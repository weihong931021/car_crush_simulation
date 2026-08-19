# 網頁化進場流程（經緯度＋影片 → 底圖確認 → 標註 → Three.js）— 設計文件

日期：2026-08-16（2026-08-17 更新實作狀態）
狀態：**① ② ③ 已實作並實機驗證**（`satellite_pipeline/webapp.py`，全網頁）；④ 待做

## 背景

整個專案要以網頁打包。目前真正需要人工的只有兩件事：**影片↔底圖的對應點標註**
（G-projection 校正）與 **挑 collider／標碰撞幀**。其餘（截衛星圖、去車銳化、車辨識、
軌跡淨化、Three.js 呈現）都已有程式。這份 spec 定義把它們串成一條網頁流程時的頁面順序、
每頁的輸入輸出，以及底圖尺寸的互動規則。

## 頁面流程

```text
① 輸入      lat / lon / 代號 / 影片
② 框範圍    自動截圖 → 滑桿框大小 → 鎖定（＝裁切定案，不做任何影像加工）
③ 標註      網頁內完成：影片首幀 ↔ 衛星圖點對應點 → 單應性 → G_projection.json
④ 呈現      車辨識 + 軌跡淨化 + build_scene → Three.js 播放頁
```

**② 不做任何影像加工**（2026-08-20 使用者拍板）：去車與銳化都改成鎖定後的**選配**按鈕。
標對應點不需要乾淨路面，每多一道加工就多一層 Gemini 隨機性與等待；預設路徑因此是
「擷取 → 框 → 鎖 → 交付」，全程沒有 LLM 呼叫。

## 關鍵決策

| 問題 | 決定 | 理由 |
| --- | --- | --- |
| 底圖中心 | ＝使用者輸入的經緯度 | 沿用 `map_capture.py` 的 `center={lat},{lon}` 後裁中央 |
| 底圖大小 | **使用者輸入**，非固定 25 m | 既有真實場景 test1 48.7×33.4 m、taipei-cm 42.7×45.2 m，25 m（`pipeline.py` 預設）對真實事故太小 |
| 太大怎麼辦 | 不設硬上限；滑桿即時預覽＋解析度提示，讓使用者自己縮小 | 大小與清晰度對沖（見下），該由人看預覽決定 |
| ② 為何保留人工 | genai HD 版的幻想標線／浮水印只能人眼驗 | 這是自動化的真正天花板，不硬做 |
| 座標系 | **② 鎖定的底圖就是校正參考圖** | 使用者對著它標對應點，`position_m` 就活在它的平面上；`--sat-dir` 只適用合成軌跡的限制在此流程下自然消失 |

## 底圖大小的互動規則（第 ② 頁）

大小與清晰度是對沖的：Google Static API `zoom=21, scale=2` 約 29 px/m，但單張 1280 px
只能涵蓋 ~44 m；要更大得降 zoom（zoom 20 ≈ 14.5 px/m，可到 ~88 m），圖糊一倍。

1. **滑桿調大小，旁邊顯示 px/m。** 使用者看預覽自己取捨「大但糊」或「小但清楚」。
2. **縮小不重截。** 先以該地點可用的最高 zoom 抓整張 1280²（~44 m）；≤44 m 的任何大小
   都在瀏覽器端裁中央即可，拖滑桿零延遲。只有 >44 m 才需降 zoom 重抓。
3. **超過單張極限只警示不擋**：「解析度將降為 X px/m，建議 ≤ 40 m」。
4. **zoom 21 不是每個地點都有**（README 寫「此地點上限」），後端要 probe 一次可用 zoom。
5. **確認後才鎖定** `size_m` / `px_per_meter` 寫進 `meta.json`。這組數字是 ③ 標註工具與
   `trajectory.meta.px_per_meter` 的唯一來源，鎖定後不可再改（改了座標全跑掉）。
6. **去車在鎖定之後做**（2026-08-16 實測改的）：Gemini 對整張 1280² 只偵測到 7 台車、對 728²
   裁切圖偵測到 38 台，小圖準得多。所以擷取只抓原圖（1 秒）、選大小、鎖定時才對裁好的範圍
   去車銳化，之後人眼檢視；偵測有隨機性（同圖 5／13 台）故提供「再跑一次去車」。

### 實作與實機驗證（2026-08-16 完成，2026-08-17 覆核）

`satellite_pipeline/webapp.py`（stdlib http.server，零依賴）＋ `web/index.html`。
`meta.decar_status`、`finish_capture` 拆分、`lock_size` 皆有離線測試
（`tests/test_webapp.py` 10 測；satellite_pipeline 全套 26 測綠）。用法見
`satellite_pipeline/README.md`「網頁版」。

實機跑出來的數字（台南永康 23.026901/120.249615）：

| 情境 | 結果 |
| --- | --- |
| 擷取原圖（zoom 21） | 29.11 px/m、1280²、涵蓋 43.97 m，約 1 秒 |
| 「降 zoom 重抓」（zoom 20） | 14.56 px/m、涵蓋 87.93 m——**解析度確實減半、範圍加倍，路徑走得通** |
| 鎖定 25 m → 裁切＋去車＋2x 銳化 | 728² raw / 1456² clean，約 12 秒 |
| 同圖重跑去車三次 | 5／13／4 台——**Gemini 偵測有隨機性，故保留「再跑一次去車」** |

兩個當初沒預期、實測才確定的設計：

1. **去車必須在裁切之後**：Gemini 對整張 1280² 只偵測到 7 台車，對裁好的 728² 偵測到 38 台。
   小圖準得多，所以擷取只抓原圖、鎖定時才去車。
2. **縮小純前端裁切**是對的：滑桿即時反應，只有要超過當前 zoom 的涵蓋範圍才需重抓。

### 2026-08-19 修：抓到「Google 拿低 zoom 放大充數」

使用者把緯度 23.026901 打成 23.062901（4 km 外的農田），②頁面**靜默給出一張糊底圖**。
原因是 Google 在該處沒有 zoom 21 的影像時，不回空白磚（`is_blank` 抓得到），而是把低 zoom
的圖放大——尺寸、`px_per_meter`、灰階 std 全部正常，只是沒有資訊量。

實測同一點：z21 銳利度 35／z20 105／z19 128／z18 317，正常永康路口 z21 是 122。
現在 `capture_best_zoom` 會算 `detail_score`（Laplacian 變異數）寫進 meta，
`detail_ok=false` 時 ② 頁面出紅色警示。**不自動降 zoom**——真的平坦的路口會被誤判成
一路降到底，判斷交給使用者按既有的「降 zoom 重抓」。

### ③ 網頁標註（2026-08-20 完成，`web/annotate.html` + `annotate.py`）

**標註不再跳出桌面程式。** 整條鏈其他段都已經是網頁，只為了點幾組對應點就開 PyQt5
是流程裡唯一的斷點。按「開始標註對應點」→ 交付檔案（實作細節，介面不提）→ 直接切到
`/annotate?code=<code>`：左影片首幀、右衛星底圖，交替點擊配對，≥4 組即時求單應性。

- **輸出 schema 對齊 `trafficlab_config.default_config()`**：頂層與各子區段的鍵全部齊全
  （實測相容），下游只讀 `homography.H` 與 `parallax.px_per_meter`
- **`px_per_meter` 直接帶入**（Web Mercator 解析值），不必人工量兩點
- **4 點陷阱**：單應性 8 個自由度，剛好 4 組點會被解死，**再怎麼標歪 RMS 都是 0**。
  `solve_homography()` 回傳 `overdetermined` 旗標，介面據此顯示「標第 5 組才看得出準不準」，
  不會拿假的 0.00 px 給人「標得很準」的錯覺
- **逐點偏差**：>8px 的點在表格與畫布上都標紅，直接指出哪一組要重標
- 既有 `G_projection` 會載回錨點接著改；`parallax` 的相機位置／高度網頁標不了，留 0
  （要視差補償仍須回 GUI 補，故 `proj_method` 用無視差的 `down_h_2`）

PyQt5 GUI 仍可用（`/api/launch_gui`），但不是預設路徑。

#### Codex 交叉審查修掉的（2026-08-20）

- **`force` 覆蓋會留下過期標註**：換了底圖但舊 `G_projection_<code>.json` 還在原地，
  trafficlab 的 `pick_stage` 會自動載入它、網頁標註也會把錨點帶回來——兩邊都拿舊座標配新
  底圖而且不報錯。現在改名成 `.superseded.<原檔時間>` 保留證據
- **沒有 CCTV 也算交付成功**：標註要兩張圖對點，只有底圖是標不了的。回傳
  `annotation_ready`，前端沒選影片就不讓進標註頁
- **去車狀態沒跟著交付**：`sat_clean` 可能是「想去車但沒 key／失敗」的產物，
  下游只看到一張圖會誤以為乾淨。`decar_status`／`vehicles_removed` 併入 `sat_meta`
- **前端解析度少報一半**：顯示 2x 的 `sat_clean` 卻報 raw 的 px/m，與 `sat_meta` 對不上

#### 安全：`/api/handoff` 的路徑穿越（2026-08-20 修，推送後掃描抓到）

`video` / `cctv_image` 是用戶端給的字串，原本直接 `UPLOAD_DIR / code / name`。兩條路都打通過：

- `"/tmp/x"` —— pathlib 的 `Path("/a/b") / "/tmp/x"` 會**整個丟掉前綴**變成 `/tmp/x`
- `"../../../..."` —— 一般相對路徑上跳

實測把 `/tmp` 的 canary 檔複製進了 repo。`cctv_image` 那條更嚴重：會被
`Image.open(...).save(cctv_<code>.png)` 轉存，再經 `/location/...` 對外提供＝任意本機圖片外洩。
server 預設只綁 127.0.0.1，但 `--host` 可改，而且瀏覽器裡任何網頁都打得到本機。

修法：`resolve_upload()` 只收單一檔名，再用 `resolve()` + `is_relative_to()` 覆核一次
（回歸測試 5 個，涵蓋絕對路徑、上跳、子目錄、代號本身）。

已知但不修：`build_scene.pick_sat` 用 `png_width / size_m` 重算 px/m 而非沿用鎖定值，
38 m 場景最大位置誤差 **1 cm（0.027%）**，且 build_scene 自身自洽——遠小於軌跡噪音，
不值得為此改動另一條線的檔案。

交付本身（`POST /api/handoff`）擺出的檔案：

```text
trafficlab-project/location/<code>/
├── sat_<code>.png          ← sat_clean 優先，沒有就 sat_raw；**永遠不用 sat_genai**
├── sat_meta_<code>.json    ← 已知 px/m（含變體放大倍率）、size_m、lat/lon/zoom
├── cctv_<code>.png         ← 影片首幀（或使用者給的截圖）
└── footage/<影片>          ← 給 Inference 分頁
```

- **比例尺一併帶過去**：`DistStage` 新增 `load_known_scale()` 與「採用已知比例尺」按鈕，
  讀 `sat_meta_<code>.json`。原本要人手在衛星圖上點兩個錨點量距離，現在直接採用
  Web Mercator 解析值，少一個人為誤差來源。**沒有 sat_meta 的舊地點照舊人工量測**，
  不影響既有流程（回歸測試：`trafficlab-project/tests/test_dist_stage_known_scale.py`）
- **已標註過的地點拒絕覆蓋**：`G_projection_<code>.json` 存在就擋下（覆蓋底圖會讓既有座標
  全部失效），要重來得明示 force
- **GUI 啟動挑得動 Qt 的直譯器**：`.venv-pifpaf` 有 PyQt5 但缺 cocoa platform plugin，
  拿它開會靜默失敗；`launch_trafficlab_gui()` 會先探測再啟動
- 順手修掉 `main.py` 的 `apply_dark_theme` **無限遞迴**（2.x 分支呼叫自己而不是
  `qdarktheme.setup_theme()`）——這台裝的正是 2.x，標註 GUI 本來就開不起來

### ⚠ 交給 ③ 標註的硬約束：只能對著 `sat_clean` 標

2026-08-17 另一條線用分塊相位相關量出生圖的幾何漂移（`satellite_pipeline/measure_genai_drift.py`）：

| 變體 | 位移中位數 | 全域相關 |
| --- | --- | --- |
| `sat_clean`（inpaint + 銳化，不生圖） | **0.00 m** | 0.968 |
| `sat_genai`（gemini-3.1-flash-image） | 0.20 m | 0.876 |
| `sat_genai`（gpt-image-2） | 0.30 m | 0.746 |

生圖是「重畫」不是「修圖」，路面結構會整體被搬動 0.2–0.3 m。**③ 的對應點一定要標在
`sat_clean` 上**——標在 `sat_genai` 上等於把 0.2 m 誤差直接烙進 G-projection，之後所有
`position_m` 都帶著它。`sat_genai` 只能當「好看的展示底圖」，不能當座標載體。

> 注意這與 `build_scene.pick_sat` 的偏好相反（它以 `sat_genai.png` 為第一優先）。合成軌跡
> 路徑影響僅止於視覺（車會偏離畫上去的車道線 0.2 m）；但真實影片的標註路徑不可妥協。

## satellite_pipeline 需先補的缺口

在 ② 之前底層要先修，否則使用者確認的圖可能已經是壞的卻沒警示：

- [x] **Gemini 去車失敗靜默成功** → `meta.decar_status`（ok／no_vehicles／no_key／failed），
      ② 頁面據此警示（CLI 仍 exit 0，`--strict` 未做）
- [x] `genai_enhance()` 不回寫 meta.json、無長寬比斷言 → 2026-08-17 另一條線修掉：產出一律
      縮回來源尺寸，並回寫 `genai_size` / `genai_matches_raw_size`
- [ ] `pipeline.py` 一鍵不含 genai → 加 `--genai` 旗標（CLI 端；② 頁面已有勾選框）
- [ ] 網頁端寫死用預設 provider（`gemini`）；`--genai-provider openai`（gpt-image-2）只有 CLI 能選
- [x] `map_capture` 省略 `--size` 時 `size_m: null` → 改寫實際涵蓋公尺數
- [ ] （選配）Gemini 呼叫加 timeout／重試，Static API 回圖驗證有影像內容（灰底無圖磚）

## 不在此 spec 範圍

- 車辨識／軌跡品質（隊友主導，凍結）
- ③ 標註工具的 UI 細節（另開 spec；本 spec 只約定它吃 ② 的 meta.json、吐 G-projection 與
  `trajectory.meta.px_per_meter`）
- 部署方式（`threejs/` 與 `scenes/` 同層的靜態約束仍適用）
