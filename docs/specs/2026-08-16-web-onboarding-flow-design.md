# 網頁化進場流程（經緯度＋影片 → 底圖確認 → 標註 → Three.js）— 設計文件

日期：2026-08-16（2026-08-20 更新實作狀態）
狀態：**① ② ③ ④ 全數實作，真實影片端到端已跑通**（2026-08-20，tainan_yongkong：
一支真實事故影片從輸入經緯度到 Three.js 播放器全程走完，四段軌跡鏈
run_inference → eval_haware_replay → filter_and_enrich → build_scene 實跑約 15 分鐘，
瓶頸是 PifPaf 逐格 1.5–2.5 秒）。端到端的結論與剩餘缺口見文末「④ 首次真實資料
端到端的結果」。

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
④ 整合      偵測 → 挑兩台當事車 → 標碰撞幀 → 場景包 → Three.js 播放頁
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

#### 上傳暫存檔會消失，要當成常態處理

`output/_uploads/<code>/` 是暫存，換 code、清測試檔、重開機都可能讓它不見，但瀏覽器那邊
`S.upload` 還記著。原本會讓 `shutil.copy2` 拋 `FileNotFoundError` 並**把內部路徑吐給使用者**
（`.../satellite_pipeline/output/_uploads/...`）——看到的人既不知道那是什麼，也不知道該做什麼。

現在兩層處理：`resolve_upload(..., must_exist=True)` 自己擋下並回「找不到先前上傳的
「X」，可能已被清除——請重新選一次檔案」；前端偵測到這個訊息就用**記憶體裡還握著的
File 物件自動重傳**再試一次，使用者根本不用重選。

已知但不修：`build_scene.pick_sat` 用 `png_width / size_m` 重算 px/m 而非沿用鎖定值，
38 m 場景最大位置誤差 **1 cm（0.027%）**，且 build_scene 自身自洽——遠小於軌跡噪音，
不值得為此改動另一條線的檔案。

交付本身（`POST /api/handoff`）擺出的檔案：

```text
trafficlab-project/location/<code>/
├── sat_<code>.png          ← ① 頁面「使用者當下看的那張」（前端送 S.tab 當 variant）；
│                              沒指定時 sat_clean → sat_raw，**不會自動挑 sat_genai**
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

### 交給 ③ 標註的底圖：預設忠實版，genai 要明示（2026-08-20 改）

原規則是「只能對著 `sat_clean` 標」。2026-08-20 使用者拍板改成**交付使用者在 ①
當下看的那張**：前端把 `S.tab` 當 `variant` 送進 `/api/handoff`，後端照做並把出處
寫進 `sat_meta_<code>.json`（`sat_variant`；genai 另寫 `geometry: rewritten_by_genai`
與 provider/model/prompt），標註頁「衛星底圖」旁常駐顯示是哪一版。三道防呆：

- **沒指定 variant 時仍不會自動挑 genai**（sat_clean → sat_raw），要用它必須明示
- 指定了但檔案不存在→直接報錯不默默降級（默默降級正是「以為高清有進去」的失敗模式）
- ① 頁面常駐標籤顯示「XX版・標註會用這張」，取代原本會被 apply() 清掉的一次性警告

代價已量化（`satellite_pipeline/measure_genai_drift.py`，分塊相位相關）：

| 變體 | 位移中位數 | 全域相關 |
| --- | --- | --- |
| `sat_clean`（inpaint + 銳化，不生圖） | **0.00 m**（位元組可重現） | 0.968 |
| `sat_genai`（gemini，2026-08-17 量測） | 0.20 m | 0.876 |
| `sat_genai`（gemini，同來源同 prompt 連跑兩次） | **0.04 m／0.40 m** | 0.833–0.995 |
| `sat_genai`（gpt-image-2） | 0.30 m | 0.746 |

生圖是「重畫」不是「修圖」，而且**不是確定性的**——同一張來源、同一組參數，兩次的
位移差 10 倍，事前無從得知這次拿到哪種。這個誤差會原樣傳進 G-projection →
`position_m` → 碰撞判定（minGap 本來就在 0.66–1.48 m 量級）。之所以仍開放：只要
③ 的對應點**標在交付的同一張圖上**，整條鏈的座標系是自洽的，誤差表現為「相對真實
世界的整體偏差」而非內部矛盾；使用者以觀感優先接受了這個代價（tainan_yongkong
即用 genai 版標定，rms 6.3 px ≈ 0.22 m）。

> 注意這與 `build_scene.pick_sat` 的偏好相反（它以 `sat_genai.png` 為第一優先）。合成軌跡
> 路徑影響僅止於視覺（車會偏離畫上去的車道線 0.2 m）；但真實影片的標註路徑不可妥協。

## ④ 整合重建（2026-08-20 完成，`web/integrate.html` + `integrate.py`）

存檔完對應點直接切到 `/integrate?code=<code>`，四步：

1. **偵測**：背景跑 `scripts/run_inference.py`，log 即時串到畫面
2. **挑兩台當事車**：`list_track_candidates()` 從推論輸出算展開度／輪關鍵點／可用率，
   品質判據**直接重用 `build_scene.kp_quality` 與它的門檻**（各寫一份遲早漂移，
   然後兩個畫面對同一台車講出不同結論）
3. **標碰撞幀**：追蹤器碰撞前 0.5 s 會凍結，這幀無法自動判定
4. **產場景包**：`filter_and_enrich_output.py --ids` → `build_scene.py --collider` → 播放器

不重寫任何軌跡邏輯，只串既有腳本。三個踩過才知道的環境事實：

- **三支腳本要三個不同的直譯器**：推論要 ultralytics + supervision（只有
  `littering_prediction/venv` 有）、enrich 要 numpy + trafficlab（`.venv-pifpaf`）、
  build_scene 純標準庫。`pick_python()` 逐一探測。
- **repo 內 7 組 inference config 的權重全部指向不存在的檔案**，而 `run_inference.py`
  沒有 `--weights` 覆寫。改用 `--config-path` 自帶一份（`make_inference_config()`
  複製第一組、只換權重），不去動隊友凍結中的 `inference_config.yaml`。
- **播放器要同站服務**：`scene-loader.js` 走 `../scenes/` 相對路徑，所以 webapp 加了
  `threejs/` 與 `scenes/` 的靜態路由（`safe_static()` 白名單 + resolve 覆核，
  和上傳檔名同一類穿越風險）。實測播放器從 :8765 開起來零 console error。

## 標歪偵測：殘差會指錯人（2026-08-20 改）

原本「最大偏差 > 8px → 建議重標」有三個問題，都修了：

| 問題 | 為什麼是問題 | 改成 |
| --- | --- | --- |
| 看**最大殘差** | 最小平方會把單一錯點的誤差**分攤到所有點**。實測 6 組點只有 index 2 標歪 30px，殘差最大的卻是 index 4——照它叫人重標，就是叫他去改沒問題的點 | **leave-one-out**：逐一拿掉重擬合，看剩下的變多乾淨。同組資料指向 index 2，正確 |
| 門檻用**像素** | 8px 在 58px/m 是 0.14 m、在 29px/m 是 0.28 m，同一個數字意義隨底圖倍率浮動 | 改用**公尺**（`BAD_RESIDUAL_M = 0.30`）。理由：29px/m 一像素 3.4 cm，人工點擊約 ±3px ≈ ±0.1 m，標得好的 RMS 落在 0.07–0.17 m |
| 只看殘差 | 點全擠在一角時殘差可以很小，但其餘區域全是**外推** | 加**涵蓋範圍**（凸包／底圖面積），低於 10% 就警告 |

LOO 需要拿掉一點後還剩 >4 個點（否則剩下的又被解死、RMS 恆為 0），所以 6 組點以上才給
建議；拿掉某點後若剩下的退化（共線）就跳過該點，不讓整組診斷壞掉。

### Codex 全鏈審查修掉的（2026-08-20，1 blocker + 4 high）

**BLOCKER：鏈少了一段，整條必爆。** `run_inference.py` 用 G-projection 算 `sat_coords`
但**不寫 `status`**，而 `filter_and_enrich_output.py` 的 localization 政策只接受
`status == 'ok'`——直接串接的話每一格都被判證據不足、`position_m` 全 null，然後 `sys.exit`。
實測重現，錯誤訊息自己指出正解：位置那半的產出者是 `scripts/eval_haware_replay.py`
（PifPaf 關鍵點 → haware localize → 寫 status / kp_sat / spread_m / n_wheel_kp）。正確的鏈是：

```text
run_inference → eval_haware_replay → filter_and_enrich → build_scene
                ^^^^^^^^^^^^^^^^^^ 原本漏掉的一段（PifPaf 逐格 1.5–2.5 秒，最慢）
```

其餘四項：

- **`PYTHONPATH` 沒設**：`eval_haware_replay` 與 `filter_and_enrich` 都 `from trafficlab...`
  import，但 trafficlab-project 沒裝成套件——實測直接 ModuleNotFoundError
- **重鎖可繞過**：`run_lock` 原本先做 zoom 升級才檢查 `locked`，重抓寫出的新 meta 不含
  `locked`，接著就能用不同尺寸再鎖一次。現在第一件事就擋
- **4 點仍可存檔**：前端警告可以被忽略，而這份檔決定所有 `position_m`。後端加
  `MIN_PAIRS_TO_SAVE = 5`
- **SVG 校正檔沒被認**：trafficlab 支援 `G_projection_svg_<code>.json`，只認普通版會讓
  該類地點被判「還沒標註」、換底圖時舊座標也不會停用。改用 `find_g_projection()` /
  `all_g_projections()`
- **碰撞幀只有數字滑桿**：這是整條鏈唯二的人工判斷，沒有畫面等於在猜。加影格預覽
  （`/api/frame/<code>/<n>`）、逐格按鈕與左右鍵，滑桿範圍自動縮到**兩台當事車同時在場**
  的區間（實測 0–9 → 3–8）

尚未處理（記錄在案）：`center_box + z_cam=0` 把 bbox 中心當地面接觸點（需要相機高度才能
正解；bbox 備援定位同樣受此偏移影響）、per-code 併發鎖、`/api/solve` 的請求競態。
~~job 狀態只在記憶體~~ ✅ 2026-08-20 修掉：server 重啟後從磁碟產物回退重建狀態。

### 標註看起來糊 ≠ 底圖沒銳化（2026-08-20）

回報「底圖還是拿沒銳化的」時實際交付的就是 `sat_clean`（1630px，同尺度銳利度 208 vs
原圖 114）。糊的原因是**顯示縮放**：1630px 的圖被塞進約 520px 的窗格＝**32%**，
Retina 上再被放大回 1900 裝置像素。而且底層 Google 影像本來就只有 29 px/m，
28 m 寬＝815 個真實像素——銳化不會生出不存在的細節。

真正該做的是讓人**放大來點**，所以標註頁加了滾輪縮放／拖曳平移／雙擊回到符合視窗。
兩個實作細節：

- **拖曳不能誤放對應點**：位移超過 4px 才算平移，否則算點擊（實測拖曳 60px 只平移、
  不放點；原地單擊正常配對）
- **標記大小要除以縮放倍率**：不然放大到 8× 時圓點會膨脹成一大塊，正好蓋住要對準的位置

座標運算完全不受影響——畫布維持影像原生尺寸，縮放全交給 CSS transform，
`getBoundingClientRect()` 換算時自動含倍率。

### 銳化不放大：2x 是純損失（2026-08-20 實測改回 1x）

原本鎖定會產出 2 倍放大的 `sat_clean`，理由是「標註要點得準」。實測推翻了它——
放大等於把**一次重取樣烤進檔案**，之後不論縮小顯示或放大檢視都在那個損失之上。

真實底圖（tainan_yongkong，Laplacian 變異數，1x 銳化 vs 當時交付的 2x 版）：

| 顯示尺寸 | 原圖直接縮 | 2x 版 | **1x 銳化** |
| --- | --- | --- | --- |
| 400 px | — | 161.8 | **407.4** |
| 554 px（符合視窗） | 115.8 | 260.4 | **624.2** |
| 815 px（原生） | — | 207.8 | **658.0** |
| 1630 px（放大 200%） | 13.1 | 47.1 | **69.3** |
| 2400 px | — | 13.3 | **18.3** |

**每個尺寸 1x 都贏 2–3 倍。** 瀏覽器要放大自己會放，而且是從更銳利的來源放。
順帶 `px_per_meter` 不必再乘倍率，少一個座標換算的出錯點，`sat_meta` 的
`upscale_factor` 變成 1.0。

量法的教訓：先前用「把 2x 縮回原尺寸再比」得出 208 vs 114，看起來 2x 有效——
那個量法量的是「銳化有沒有發生」，不是「使用者實際看到的畫面」。要比就得在**實際顯示
尺寸**上比。合成圖也不能當依據（人工邊緣特性不同，結果會反過來），必須用真實底圖。

## ④ 首次真實資料端到端的結果（2026-08-20，tainan_yongkong）

一支真實事故影片（1280×720、360 幀、汽車撞機車）從 ① 跑到播放器。過程中修掉三個
阻斷點、加了一條備援路徑，全部含回歸測試：

- **`--method` 缺參**：`eval_haware_replay.py` 的 `--method` 是 `required=True`，
  `haware_cmd()` 沒傳→argparse exit 2（網頁上只看得到「returncode 2」）。補
  `geometric`——只有它會讀 `--yolo-boxes-json`（track id 橋接檔），選 `crop` 該參數
  被整個忽略
- **機車被類別過濾丟光**：`--yolo-boxes-class` 原是精確比對單一類別（預設 `car`），
  VisDrone 的機車叫 `motor`——實測 car 697 框／motor 143 框／van 13 框，舊行為只載
  697。改逗號分隔多類別（排除 pedestrian/people），載入 853 框
- **輸出 `class` 寫死 `'car'`**：挑車介面的類別欄一直是死值。改由 tracked_id 的
  **多數決**偵測類別帶出（單幀類別會跳動），挑車選單據此把偵測車種排第一並標「（偵測）」
- **機車的位置走 bbox 備援定位**：PifPaf 的 Apollo-24 是**汽車**關鍵點模型，機車
  偵測不到——實測 7 條機車 track 與 PifPaf 框的最佳 IoU **全部 0.000**（22–52 px 小
  目標，調門檻無效）。`eval_haware_replay --bbox-fallback` 對沒被認領的 YOLO track
  用 bbox 參考點過單應性取位置，座標放**旁路欄位 `bbox_fallback_sat_coords`**
  （`status='bbox_fallback'`；`sat_coords` 權威欄位不寫——localization authority 的
  政策被測試凍結為只信 `status='ok'`，順著架構走）。下游
  `filter_and_enrich --accept-bbox-fallback` 明示才在 sanitize 之後注入 `position_m`
  並標 `position_source`。挑車介面新增「定位」欄（PifPaf／bbox／混合）與「移動」欄
  （頭尾淨位移——**停放車的品質分數反而最高**，360 幀不動的 track 1 可用率 100%，
  這欄就是防這個陷阱）

**端到端跑完的誠實結論**：整合鏈全線運作（含出界閘門、解析度一致性檢查、碰撞幀
限縮），但以真實資料模擬的結果是「未發生碰撞、最近距離 7.50 m」——所有機車 track
淨位移僅 0.2–0.7 m（路口等紅燈那排），**真正撞車那台機車追蹤器沒有抓穩**。這屬於
偵測／追蹤品質（隊友主導的凍結範圍）；整合端的接口已就緒，track 一穩位置就會自己
流進來。對外 demo 用合成軌跡場景包（`tools/place_synth_trajectory.py` 擺位到真實
底圖，見 421da6a）。

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
