# 行車事故影片重建 3D 模型

將碎片化素材（手機影片、低畫質監控）利用 AI 快速重建為 3D 碰撞動畫，協助釐清責任、輔助司法判決。

## 協作分工（先讀這個）

| 目錄 | 誰維護 | 動它之前 |
| --- | --- | --- |
| `backend/` | 本 repo | 進場流程 ①②③④ 的 HTTP server 與影像/標註/整合邏輯。改完跑 `backend/tests` |
| `frontend/onboarding/` | 本 repo | ①②③④ 的三個頁面（自足 HTML，CSS/JS 內嵌） |
| `frontend/player/` | 本 repo | 3D 播放器與碰撞物理。**物理已模組化在 `frontend/player/lib/`，不要重新推導**（spec：[碰撞模擬](docs/specs/2026-07-20-collision-simulation-design.md)） |
| `tools/` | 本 repo | 場景包產生器與驗證腳本 |
| `scenes/` | 產出 | 由 `build_scene.py` 產生，不手改 |
| `trafficlab-project/` | **混合** | 先讀 [OWNERSHIP.md](trafficlab-project/OWNERSHIP.md)——haware 定位那 64 檔是本 repo 維護的，偵測與軌跡（`inference/pipeline.py`、`trajectory/`、`inference_config.yaml`、`models/`）由隊友主導且**已凍結，不要優化** |

兩條硬約束，改架構前務必知道：

- **`frontend/` 與 `scenes/` 必須是同層目錄** —— `scene-loader.js` 走 `../../scenes/`
  （player 在 frontend/ 下一層），只部署 `frontend/` 會全數 404
- **`trafficlab-project/` 不能改名成 `trafficlab/`** —— 會與其內同名 Python 套件衝突，
  `import trafficlab.motion` 會拋 `ModuleNotFoundError` 且訊息不指向真正原因

## 第一次上手

```bash
# 1. 需要什麼
#    Python 3（標準庫即可跑 backend 與 tools）、Node 18+（播放器測試）
#    影像處理另需 numpy / opencv-python / Pillow
#    haware 定位那套用 trafficlab-project/.venv-pifpaf（uv 建的，已在磁碟上）

# 2. 設 API key（只有擷取底圖與 AI 去車需要，跑既有場景不用）
echo "GOOGLE_MAPS_KEY=..." >> backend/.env      # ① 擷取衛星底圖
echo "GEMINI_API_KEY=..."  >> backend/.env      # 選配：AI 去車

# 3. 確認環境沒問題——先看得到既有場景再說
node tools/verify_scenes.mjs                      # 期望「✓ 4 場景全過」

# 4. 開起來看
python3 backend/webapp.py                       # → http://127.0.0.1:8765/
```

跑不動的話最常見兩個原因：haware 測試要用 `.venv-pifpaf`（系統 python3 缺 `ultralytics`）、
`node --test` 必須用 glob 不能給目錄。細節見下方「測試」。

## Pipeline

從 2026-08 起，整條進場流程都在瀏覽器裡完成（`backend/webapp.py`）：

```text
① 選地點   經緯度 + 事故影片
              ↓  Google Static API 擷取 → 銳化（本機、不放大、不動幾何）
② 框範圍   滑桿框大小 → 鎖定（size_m / px_per_meter 就此定案＝座標系）
              ↓
③ 標註     左影片首幀、右衛星底圖點對應點 → 單應性 → G_projection_<code>.json
              ↓
④ 整合     偵測 → 挑兩台當事車 → 標碰撞幀 → 場景包 → 播放器
```

④ 底下是 trafficlab 既有的四段腳本，**不重寫軌跡邏輯**只做串接：

```text
scripts/run_inference.py            YOLO 偵測 + 追蹤   → *.json.gz（sat_coords，無 status）
    ↓
scripts/eval_haware_replay.py       PifPaf + haware 定位 → 補 status / kp_sat / spread_m
    ↓                               ※ 少了這段整條必爆：enrich 只接受 status=='ok'
scripts/filter_and_enrich_output.py 只留當事車 + 補 position_m
    ↓
tools/build_scene.py                → scenes/<code>/（scene.json + ground.png + trajectory.json）
    ↓
frontend/player/index.html?scene=<code>      JS 碰撞物理 + 互動 UI，渲染全在瀏覽器
```

只剩兩個人工判斷：**挑兩台當事車**、**標碰撞幀**（追蹤器碰前 0.5 s 會凍結，無法自動判定）。

設計文件：[進場流程](docs/specs/2026-08-16-web-onboarding-flow-design.md)、
[場景包與播放器](docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md)。

### Haware 定位準確度方向與現況

核心方向是**以量測閘門把關、可靠度感知的多線索定位**，不是僅靠輪點。輪／地面接觸點是
優先的 `h=0` 位置錨點；玻璃／擋風玻璃角點、車頂角點、後視鏡與其他已文件化族群，則可依
角色與可靠度提供朝向、位置或方位。朝向點不得跨高度族群直接混合：各高度族群須分別估計，
再以 Effective Eta 不確定度合併完成的估計。既有手性修正、spread gate 與僅供診斷的
`n_wheel_kp` 均保留。

Fallback 是主要路徑之一；零輪點不代表必然 fallback，只要非輪線索構成有效的 primary support
即可。下游只可使用 authoritative position。驗收須由 `kee-cc` 與 `taoyuan-tc` 各自獨立通過，
`taipei-cm` 僅供診斷；最終驗收還必須具備 Phase 0 凍結基準、獨立 ground truth 與可重現指標。
詳見目前 Kiro 的 [requirements](docs/legacy-specs/haware-localization-accuracy/requirements.md)、
[design](docs/legacy-specs/haware-localization-accuracy/design.md)、
[tasks](docs/legacy-specs/haware-localization-accuracy/tasks.md)，以及
[手性 parity bug 決策記錄](docs/decisions/2026-07-27-haware-localizer-parity-bug.md)。

**實際磁碟狀態：** requirements／design 已納入上述多線索修訂方向，但實作尚未開始；tasks／config
仍須同步後才能執行 Run All Tasks，且目前不可宣稱所有 spec 狀態皆已核准。

## 線上 Demo（單頁打包版）

**<https://claude.ai/code/artifact/1fec3a43-8ccf-4bbb-bcaa-55ac1e9f044f>**（私人連結，可從頁面分享）

- **完整 three.js 3D 版**單頁打包（~6.9MB）：three r165 以 data:URI importmap 內嵌、
  車輛 GLB 經 meshopt 壓縮（car 18.5→3.2MB）base64 內嵌、`frontend/player/lib/` 物理 bundle、
  衛星地面、光影/三種視角（頂視/45°/跟車）/OrbitControls，離線可用
- 軌跡經淨化管線：時間窗平滑 → 切除碰前凍結尾 → RDP 直線化＋轉角細分（路徑＝兩點
  連線、線段間僅些微角度）→ 投影（幾何/時序分離：每點時刻與速度剖面原樣保留）→
  縱向慣性上限 → 證據終點外插（畫面虛線標示）；各車依實際出現時刻進場（`startT`）、
  車身朝向受轉向率上限（單車模型＋側向抓地）約束
- 功能與完整版一致：車速倍率滑桿（即時重模擬）、碰撞/未碰撞結論、求安全車速區間、
  最近間距標註；依會議決定呈現至碰撞瞬間為止
- 產生方式：`scenes/test1/` 資料 + `frontend/player/lib/` bundle 組頁。**組頁流程沒有腳本化**，
  當初在 session scratchpad 裡完成，要重產得重寫（候選檔名 `tools/build_demo_page.py`，
  目前不存在）
- 完整互動 3D 版在 `frontend/player/index.html`，本地用網頁工作台或 `python3 -m http.server` 開；
  GitHub Pages 待 repo 管理者於 Settings → Pages 啟用 main / root

## 資料夾結構

```text
blender_crash_project/
├── CLAUDE.md                       ← Claude 行為指令
├── README.md
├── index.html                      ← 根目錄轉址至 frontend/player/index.html
│
├── backend/                        ← ★ 進場流程 ①②③④ 的 Python 端
│   ├── webapp.py                   ← ★ HTTP server（服務 frontend/ 與 scenes/、所有 /api/*）
│   ├── annotate.py                 ← 對應點 → 單應性 → G_projection（schema 對齊 trafficlab）
│   ├── integrate.py                ← 串接 trafficlab 四段腳本（含直譯器/PYTHONPATH 探測）
│   ├── paths.py                    ← 所有路徑的唯一事實來源
│   ├── pipeline.py                 ← CLI 一鍵流程（擷取 + 增強）
│   ├── map_capture.py              ← Google Static API 擷取
│   ├── image_enhance.py            ← 去車 + 銳化 / --genai HD（預設 gemini，可選 gpt-image-2）
│   ├── measure_genai_drift.py      ← 量生圖把幾何搬了多遠（分塊相位相關）
│   ├── common.py                   ← 地點代號驗證
│   ├── tests/                      ← 111 測
│   └── output/<code>/              ← sat_raw / sat_clean / sat_genai / meta.json（不入庫）
│
├── frontend/                       ← ★ 所有網頁
│   ├── onboarding/                 ← 進場流程三頁（自足 HTML，CSS/JS 內嵌）
│   │   ├── index.html              ←   ①② 選地點 / 框範圍
│   │   ├── annotate.html           ←   ③ 對應點標註（縮放平移、leave-one-out 診斷）
│   │   └── integrate.html          ←   ④ 偵測 → 挑當事車 → 標碰撞幀 → 場景包
│   └── player/                     ← 3D 播放器與碰撞模擬
│       ├── index.html              ← Three.js r165，場景載入 + 播放控制 UI
│       ├── main.js                 ← 核心動畫、碰撞物理、互動邏輯
│       ├── scene-loader.js         ← scene.json 載入器（走 ../../scenes/）
│       ├── lib/                    ← 物理與軌跡模組（path/obb/simulate/solve/physics…）
│       │   └── tests/              ← node --test frontend/player/lib/tests/*.test.js
│       ├── models/                 ← GLB 模型 + registry.json（前方軸向、縮放、hide 清單）
│       └── vendor/three/           ← 本地 Three.js 0.165.0（不可外連）
│
├── tools/
│   ├── build_scene.py              ← 半自動場景包產生器
│   ├── synth_trajectory.py         ← 合成軌跡（換場景驗證用）
│   ├── place_synth_trajectory.py   ← 把合成軌跡擺到真實底圖上
│   ├── verify_scenes.mjs           ← 全場景 headless 冒煙驗證（加新場景必跑）
│   ├── open-player.command         ← 雙擊開播放器（站根自動回到 repo 根）
│   └── tests/                      ← build_scene 單元測試 + 邊界測試
│
├── scenes/                         ← 場景包（scene.json + ground.png + trajectory.json）
├── docs/
│   ├── specs/  plans/  decisions/  ← 設計文件、實作計畫、決策記錄
│   ├── legacy-specs/               ← Kiro 時期 spec（haware 定位準確度）
│   ├── trafficlab-notes/           ← 我們對隊友腳本的使用說明
│   ├── handouts/                   ← 交付簡報 PDF
│   ├── diagrams/                   ← 對外簡報圖（改字請改 make_diagrams.py 再重跑）
│   ├── papers/                     ← 外部參考文獻 PDF
│   ├── PROJECT.md  todonext.md  reference.md  video-processing-commands.md
├── environments/                   ← trafficlab-pifpaf.yml（pifpaf 環境配方）
│
│   ── 以下留在磁碟但不入庫 ──
├── samples/                        ← 範例影片
├── archive/images/                 ← 淘汰衛星圖 + 開發驗證截圖
├── pifpaf-weights/                 ← openpifpaf apollo24 權重 92 MB
├── threejs-v1/                     ← 播放器前一版（保留對照）
│
└── trafficlab-project/             ← 混合歸屬——64 檔 25,442 行是我們的
    ├── OWNERSHIP.md                ← ★ 先讀這個再決定要不要改裡面的東西
    ├── trafficlab/                 ← 核心函式庫（haware_* 與 localization_authority 是我們的）
    ├── tests/                      ← 43 支（24 + properties 19），全是我們寫的
    ├── detection_tests/            ← VisDrone fine-tune vs COCO 驗收實驗
    ├── scripts/                    ← run_inference / eval_haware_replay / filter_and_enrich
    ├── location/<code>/            ← 校正資料（G_projection、cctv/sat 對照圖）
    ├── models/                     ← YOLO 權重（yolo11l-visdrone-ft.pt 已就位）
    ├── output/                     ← 推論輸出 *.json.gz
    ├── main.py                     ← GUI 入口
    └── inference_config.yaml       ← 隊友主導、凍結中
```

## 啟動方式

```bash
# 網頁工作台（進場流程 ①②③④ 全在這裡；同時也服務 frontend/player/ 與 scenes/）
python3 backend/webapp.py
# → http://127.0.0.1:8765/                        選地點 → 框範圍 → 標註 → 整合
# → http://127.0.0.1:8765/frontend/player/index.html?scene=test1    直接看既有場景

# 只想看播放器（不跑工作台）
python3 -m http.server 8765     # 站根要同時看得到 frontend/player/ 與 scenes/

# TrafficLab 桌面 GUI（選配；網頁標註已涵蓋校正，這條不是預設路徑）
python3 trafficlab-project/main.py
```

> **直譯器分工**（踩過才知道，別憑印象挑）：
> 桌面 GUI 用**系統 `python3`**——`littering_prediction/venv` 沒有 PyQt5、
> `.venv-pifpaf` 有 PyQt5 但缺 cocoa platform plugin，兩個都開不起視窗。
> 推論要 ultralytics + supervision（只有 `littering_prediction/venv` 有）；
> haware 定位與 enrich 要 numpy + trafficlab（`.venv-pifpaf`），而且**必須設
> `PYTHONPATH=trafficlab-project`**，否則 `from trafficlab...` 直接 ModuleNotFoundError。
> 網頁工作台的 `integrate.py` 會自動探測與帶入，手動跑才需要自己注意。

## 新增場景（新影片進場）

**建議走網頁工作台**：`python3 backend/webapp.py` → 填經緯度、選影片，
四步走完就有可播放的重建。底圖、比例尺、校正檔、場景包都自動落到正確位置。

### 座標系是怎麼定的（無論走哪條路都要懂）

軌跡的 `position_m` 活在**校正參考圖**的平面上：原點＝圖左上角，尺度＝`px_per_meter`。
換一張不同取景的衛星圖＝換一個座標系，車就會錯位。

- 走網頁流程時，②鎖定的那張圖**就是**校正參考圖（③ 直接對著它標），所以不會有這個問題
- 走 CLI 且沿用隊友既有校正時，地面圖必須是
  `trafficlab-project/location/<code>/sat_<code>.png` 或它的等比縮放

### CLI 備援

```bash
# 沿用既有校正：--location-dir 會自動算出 size_m 與 origin_offset_m，不必人工算
python3 tools/build_scene.py --trajectory T.json --list        # 先挑當事車（有品質欄位輔助）
python3 tools/build_scene.py --code <code> --trajectory T.json \
  --location-dir trafficlab-project/location/<code> \
  --collider <id>:Car --collider <id>:Two_Wheeler --source-collision <frame>

node tools/verify_scenes.mjs      # 加新場景包後必跑：唯一會實際渲染的驗證
```

`--sat-dir`（backend 新擷取的圖）只適用於**在衛星座標系合成的軌跡**
（如 `scenes/tainan_yongkang/`）。走網頁流程則沒有這個限制——那張圖本身就是座標系。

## 測試

```bash
node --test frontend/player/lib/tests/*.test.js                      # 物理/軌跡模組 86 測（必用 glob）
python3 -m unittest discover -s tools/tests                  # 場景包產生器 46 測（只用標準庫）
python3 -m unittest discover -s backend/tests              # 網頁流程/標註/整合/底圖 111 測
(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests)   # haware 271 測
node tools/verify_scenes.mjs                                 # 全場景 headless 冒煙
```

`todo`（node）與 `expectedFailure`（unittest）標記是**已知缺口的執行式文件**，非壞掉的
測試——清單見 [docs/todonext.md](docs/todonext.md)。
