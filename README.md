# 行車事故影片重建 3D 模型

將碎片化素材（手機影片、低畫質監控）利用 AI 快速重建為 3D 碰撞動畫，協助釐清責任、輔助司法判決。

## Pipeline

```text
CCTV 影片 (.mp4)
    ↓  [TrafficLab：校正 + 推論]（偵測品質由隊友主導）
trafficlab-project/output/*.json.gz（所有車輛軌跡）
    ↓  [filter_and_enrich_output.py：篩選 + 補欄位]
軌跡 JSON（含 position_m / velocity_mps）＋ G-projection 校正參考圖 sat_<code>.png
    ↓  [tools/build_scene.py：半自動產生場景包]  ※ 地面圖須與軌跡同座標系，見「新增場景」
scenes/<code>/（scene.json + ground.png + trajectory.json）
    ↓  [Three.js 播放器：JS 碰撞物理 + 互動 UI + 渲染]
可分享的網頁 demo（渲染全在瀏覽器）
```

當前方向見 [docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md](docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md)。

### Haware 定位準確度方向與現況

核心方向是**以量測閘門把關、可靠度感知的多線索定位**，不是僅靠輪點。輪／地面接觸點是
優先的 `h=0` 位置錨點；玻璃／擋風玻璃角點、車頂角點、後視鏡與其他已文件化族群，則可依
角色與可靠度提供朝向、位置或方位。朝向點不得跨高度族群直接混合：各高度族群須分別估計，
再以 Effective Eta 不確定度合併完成的估計。既有手性修正、spread gate 與僅供診斷的
`n_wheel_kp` 均保留。

Fallback 是主要路徑之一；零輪點不代表必然 fallback，只要非輪線索構成有效的 primary support
即可。下游只可使用 authoritative position。驗收須由 `kee-cc` 與 `taoyuan-tc` 各自獨立通過，
`taipei-cm` 僅供診斷；最終驗收還必須具備 Phase 0 凍結基準、獨立 ground truth 與可重現指標。
詳見目前 Kiro 的 [requirements](.kiro/specs/haware-localization-accuracy/requirements.md)、
[design](.kiro/specs/haware-localization-accuracy/design.md)、
[tasks](.kiro/specs/haware-localization-accuracy/tasks.md)，以及
[手性 parity bug 決策記錄](docs/decisions/2026-07-27-haware-localizer-parity-bug.md)。

**實際磁碟狀態：** requirements／design 已納入上述多線索修訂方向，但實作尚未開始；tasks／config
仍須同步後才能執行 Run All Tasks，且目前不可宣稱所有 spec 狀態皆已核准。

## 線上 Demo（單頁打包版）

**<https://claude.ai/code/artifact/1fec3a43-8ccf-4bbb-bcaa-55ac1e9f044f>**（私人連結，可從頁面分享）

- **完整 three.js 3D 版**單頁打包（~6.9MB）：three r165 以 data:URI importmap 內嵌、
  車輛 GLB 經 meshopt 壓縮（car 18.5→3.2MB）base64 內嵌、`threejs/lib/` 物理 bundle、
  衛星地面、光影/三種視角（頂視/45°/跟車）/OrbitControls，離線可用
- 軌跡經淨化管線：時間窗平滑 → 切除碰前凍結尾 → RDP 直線化＋轉角細分（路徑＝兩點
  連線、線段間僅些微角度）→ 投影（幾何/時序分離：每點時刻與速度剖面原樣保留）→
  縱向慣性上限 → 證據終點外插（畫面虛線標示）；各車依實際出現時刻進場（`startT`）、
  車身朝向受轉向率上限（單車模型＋側向抓地）約束
- 打包腳本化候選：`tools/build_demo_page.py`（目前組頁流程在 session scratchpad）
- 功能與完整版一致：車速倍率滑桿（即時重模擬）、碰撞/未碰撞結論、求安全車速區間、
  最近間距標註；依會議決定呈現至碰撞瞬間為止
- 產生方式：`scenes/test1/` 資料 + lib bundle 組頁（來源：session scratchpad，
  之後可整理成 `tools/build_demo_page.py`）
- 完整互動 3D 版仍在 `threejs/index.html`（本地 `python3 -m http.server` 開啟；
  GitHub Pages 待 repo 管理者於 Settings → Pages 啟用 main / root）

## 資料夾結構

```text
blender_crash_project/
├── CLAUDE.md                       ← Claude 行為指令
├── README.md
├── index.html                      ← 根目錄轉址至 threejs/index.html
├── docs/
│   ├── specs/                      ← 設計文件（含當前方向 spec）
│   ├── papers/                     ← 外部參考文獻 PDF
│   ├── PROJECT.md                  ← 專案總覽、競品分析、已知風險
│   ├── todonext.md                 ← 待辦清單
│   ├── reference.md                ← 座標轉換、車規、時間軸快速參考
│   ├── decisions/                  ← 決策記錄
│   ├── filter_and_enrich_output.md ← filter_and_enrich_output.py 使用說明
│   ├── video-processing-commands.md ← yt-dlp / ffmpeg / RIFE 指令速查
│   └── *.pdf
├── scenes/                         ← 場景包（scene.json + ground.png + trajectory.json）
├── tools/
│   ├── build_scene.py              ← 半自動場景包產生器
│   ├── synth_trajectory.py         ← 合成軌跡（換場景驗證用）
│   ├── verify_scenes.mjs           ← 全場景 headless 冒煙驗證（加新場景必跑）
│   └── tests/                      ← build_scene 單元測試 + 邊界測試
├── satellite_pipeline/            ← 衛星底圖自動化（lat/lon → 去車 → sat_*.png）
│   ├── pipeline.py                ← 一鍵流程（擷取 + 增強）
│   ├── map_capture.py             ← Google Static API 擷取
│   ├── image_enhance.py           ← Gemini 去車 + 銳化 / --genai HD（OpenAI gpt-image-2）
│   ├── common.py                  ← 地點代號驗證
│   ├── models/FSRCNN_x4.pb        ← 超解析模型（gitignored；目前無程式引用，待清理）
│   └── output/<code>/             ← sat_raw / sat_clean / sat_genai / meta.json
├── archive/images/                 ← 淘汰衛星圖版本 + 開發過程驗證截圖
├── detection_tests/                ← VisDrone fine-tune vs COCO 驗收實驗
├── threejs/
│   ├── index.html                  ← Three.js r165，場景載入 + 播放控制 UI
│   ├── main.js                     ← 核心動畫、碰撞物理、互動邏輯
│   ├── scene-loader.js             ← scene.json 載入器
│   ├── lib/                        ← 模組化工具函式
│   │   ├── frames.js               ← 幀插值
│   │   ├── waypoints.js            ← 路徑點管理
│   │   ├── physics.js              ← 碰撞物理（JS 實作）
│   │   ├── interp.js               ← 速度 / 旋轉插值
│   │   └── tests/                  ← 單元測試
│   ├── models/                     ← GLB 模型 + 註冊表
│   │   ├── car.glb
│   │   ├── moto.glb
│   │   └── registry.json           ← 模型元數據（前方軸向、縮放）
│   └── vendor/three/               ← 本地 Three.js 0.165.0
└── trafficlab-project/             ← 上游 Pipeline（CCTV → 軌跡；偵測優化由隊友主導）
    ├── main.py                     ← GUI 入口
    ├── location/test1/             ← 校正資料（G_projection、cctv/sat 對照圖）
    ├── scripts/                    ← filter_and_enrich_output.py、run_inference.py 等
    ├── output/                     ← 推論輸出 *.json.gz
    ├── models/                     ← YOLO 權重（yolo11l-visdrone-ft.pt 已就位）
    ├── trafficlab/                 ← 核心函式庫
    └── inference_config.yaml
```

## 啟動方式

```bash
# Three.js 預覽（從專案根目錄）
python3 -m http.server 8765
# → http://localhost:8765/threejs/index.html

# TrafficLab GUI（trafficlab conda env 不存在，用 littering_prediction 的 venv）
PYTORCH_ENABLE_MPS_FALLBACK=1 /Users/weihong/Documents/littering_prediction/venv/bin/python trafficlab-project/main.py
```

## 新增場景（新影片進場）

**地面圖必須用 G-projection 的校正參考圖**：軌跡的 `position_m` 就活在
`trafficlab-project/location/<code>/sat_<code>.png` 這張圖的平面上（原點＝圖左上角，
尺度＝`trajectory.meta.px_per_meter`）。換一張新擷取的衛星圖＝換一個座標系，車會錯位。

```bash
# 1. 算出該平面的實際尺寸（sat 圖寬高 ÷ trajectory.meta.px_per_meter）
python3 - <<'PY'
import json, struct
code = "<code>"; traj = "<軌跡JSON路徑>"
ppm = json.load(open(traj))["meta"]["px_per_meter"]
p = f"trafficlab-project/location/{code}/sat_{code}.png"
w, h = struct.unpack(">II", open(p, "rb").read(24)[16:24])
print(f"--ground-image {p} --px-per-meter {ppm} --size-m {w/ppm:.2f} {h/ppm:.2f}")
PY

# 2. 先列 track 挑碰撞車（人工判讀），再帶上一步印出的參數產場景包
python3 tools/build_scene.py --trajectory T.json --list
python3 tools/build_scene.py --code <code> --trajectory T.json \
  --ground-image trafficlab-project/location/<code>/sat_<code>.png \
  --px-per-meter <ppm> --size-m <W> <H> \
  --collider <id>:Car --collider <id>:Two_Wheeler --source-collision <frame>

# 3. 播放器零改碼開啟，並跑冒煙驗證
#    http://localhost:8765/threejs/index.html?scene=<code>
node tools/verify_scenes.mjs
```

必要的人工判斷只有兩處：**挑兩台 collider 的 track ID**、**標碰撞幀**（追蹤器碰撞前 0.5s
會凍結，無法自動判定）。

`--sat-dir`（satellite_pipeline 新擷取的 Google 圖）**只適用於在衛星座標系合成的軌跡**
（如 `scenes/tainan_yongkang/`），對真實影片軌跡會錯位。satellite_pipeline 的定位是
合成場景的地面來源，不是真實影片的地面來源。

## 測試

```bash
node --test threejs/lib/tests/*.test.js                     # 物理/軌跡模組（必用 glob）
python3 -m unittest discover -s tools/tests                  # 場景包產生器（只用標準庫）
python3 -m unittest discover -s satellite_pipeline/tests     # 代號驗證 + 產生程式碼跳脫
node tools/verify_scenes.mjs                                 # 全場景 headless 冒煙
```

`todo`（node）與 `expectedFailure`（unittest）標記是**已知缺口的執行式文件**，非壞掉的
測試——清單見 [docs/todonext.md](docs/todonext.md)。
