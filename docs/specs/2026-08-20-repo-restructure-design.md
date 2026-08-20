# 收尾階段的目錄重整

**日期**：2026-08-20
**狀態**：設計定案，待實作
**動機**：專案進入收尾。頂層 17 個項目混雜「我們維護的」「隊友主導的」「歷史產物」「純重複」，
新人（含半年後的自己）看不出哪個是前端、哪個是後端、哪個不用看。

---

## 一、現況與問題

| 目錄 | 入庫 | 磁碟 | 問題 |
| --- | --- | --- | --- |
| `trafficlab-project/` | 66 MB | 1.4 G | 名字暗示「整包都是別人的」，實際上 64 檔 / 25,354 行是我們的 |
| `archive/` | 26 MB | 26 M | 37 張舊截圖，沒人引用，卻是第二大入庫項 |
| `threejs/` | 20 MB | 20 M | 名字講的是「用什麼技術」，不是「它是什麼」 |
| `location/`（頂層） | 11.5 MB | 15 M | 11 檔 md5 與 `trafficlab-project/location/` **完全相同** |
| `satellite_pipeline/` | 7 MB | 27 M | 名字只描述了它最早的功能（抓衛星圖），現在它跑完整條 ①②③④ |
| `detection_tests/` | 5.5 MB | 8.4 M | 讀的全是 `trafficlab-project/` 的 footage 與 models，卻放在頂層 |
| `pifpaf/` | 64 KB | 92 M | 3 支是 `trafficlab-project/` 對應檔的**過時**副本（缺 spread 邊界修正） |
| 根目錄散檔 | — | — | `environment.yml`／`tainan_yongkong.mp4`／`.kiro/`／`open-player.command` |

### 三個必須先講清楚的事實

**① 路徑耦合只有一處。** 全 repo 只有 `satellite_pipeline/paths.py:30` 知道隊友那包在哪。

**② `player/` 與 `scenes/` 必須同層。** `scene-loader.js:10` 走 `../scenes/`，
`webapp.py:39` 的 `STATIC_ROOTS` 與 `verify_scenes.mjs:36` 的 `REPO_ROOT` 都建在這個假設上。
本設計**保持兩者同層**，因此不必碰這個約束。

**③ `trafficlab-project/` 不是「隊友的」。** 整套 haware 定位子系統是我們自己寫的：

```text
trafficlab/motion/haware_localization.py       haware_optimizer.py
trafficlab/motion/haware_hypotheses.py         haware_baseline_dispatch.py
trafficlab/motion/haware_accuracy/{models,validation}.py
trafficlab/motion/localization_authority.py
trafficlab/io/haware_observation_replay.py     haware_track_provenance.py
trafficlab/measurement/{haware_pilot,haware_held_out}.py
trafficlab/projection/haware_forward.py
trafficlab/inference/pifpaf_haware_adapter.py
tests/  25 支 + tests/properties/  19 支 property test
                                   —— 合計 64 檔、25,354 行
```

對照：我們頂層的「核心」（satellite_pipeline + tools + threejs/lib）合計 5,821 行。
**埋在那棵樹裡的自家程式碼是它的 4.4 倍。** 所以本設計**不**把它標成 `vendor/`。

耦合方向已量測：

- **正向乾淨** —— haware 各模組只 import 自己人，零個 import 隊友的非 haware 模組
- **反向不乾淨** —— 隊友的 `visualization/sat_renderer.py`、`io/replay_writer.py`、
  `trajectory/smoothing.py`、`trajectory/plotting.py` 四支都 import 我們的 `localization_authority`

因此**不抽出 haware**：抽出要改隊友 4 支檔案，且未來拉隊友更新更痛。改用 `OWNERSHIP.md` 標示歸屬。

---

## 二、目標結構

```text
blender_crash_project/
├── README.md  CLAUDE.md  index.html          入口三件
├── workbench/          【我們】進場流程 ①②③④ 端到端工作台   ← satellite_pipeline/
│   ├── webapp.py annotate.py integrate.py
│   ├── map_capture.py image_enhance.py pipeline.py
│   ├── common.py paths.py
│   ├── web/ {index,annotate,integrate}.html
│   └── tests/
├── player/             【我們】Three.js 播放器與碰撞模擬      ← threejs/
│   ├── index.html main.js scene-loader.js
│   ├── lib/ + lib/tests/
│   ├── models/ *.glb registry.json
│   └── vendor/three/
├── tools/              build_scene.py  verify_scenes.mjs  open-player.command  tests/
├── scenes/             場景包（player 的 `../scenes/`）
├── samples/            tainan_yongkong.mp4（未入庫）
├── environments/       trafficlab-pifpaf.yml
├── docs/
│   ├── specs/ plans/ decisions/ diagrams/ papers/ reference.md todonext.md PROJECT.md
│   ├── legacy-specs/haware-localization-accuracy/     ← .kiro/specs/
│   ├── trafficlab-notes/filter_and_enrich_output.md
│   └── handouts/*.pdf
├── trafficlab-project/  【混合歸屬，見 OWNERSHIP.md】
│   ├── OWNERSHIP.md                    ← 新增
│   └── detection_tests/                ← detection_tests/
└── pifpaf-weights/     92 MB 模型權重（未入庫）              ← pifpaf/
```

### 命名理由

- **`workbench/`**：`webapp.py` 內 `run_capture`／`run_lock` 做 ①②、`track_candidates` 做 ④ 挑車、
  `build_scene_for` 補軌跡／產場景包／回傳播放器網址。它是端到端工作台，不是「後端」也不只是
  「onboarding」。（引函式名不引行號——行號會隨開發漂移，本文件已被實證過一次。）
- **`player/`**：說它是什麼，不說它用什麼技術。
- **`trafficlab-project/` 不改名**：頂層若叫 `trafficlab/`，會與其內的 Python 套件 `trafficlab/` 同名。
  repo root 一旦進 `sys.path`（從根目錄跑 `python3` 就會），`import trafficlab` 解析到**空的
  namespace package**、`import trafficlab.motion` 拋 `ModuleNotFoundError`，而錯誤訊息完全不指向
  真正原因。實測確認。不改名的附帶好處：目錄深度不變，四處 repo 深度假設全部免修。

---

## 三、搬遷對照

### 搬（`git mv`）

| 現在 | 之後 |
| --- | --- |
| `satellite_pipeline/` | `workbench/` |
| `threejs/` | `player/` |
| `detection_tests/` | `trafficlab-project/detection_tests/` |
| `environment.yml` | `environments/trafficlab-pifpaf.yml` |
| `open-player.command` | `tools/open-player.command` |
| `.kiro/specs/haware-localization-accuracy/` | `docs/legacy-specs/haware-localization-accuracy/` |
| `docs/filter_and_enrich_output.md` | `docs/trafficlab-notes/filter_and_enrich_output.md` |
| `docs/處理影片的終端機指令.pdf`、`docs/行車事故影片重建3d模型.pdf` | `docs/handouts/` |
| `pifpaf/` | `pifpaf-weights/`（僅剩未入庫權重） |
| `tainan_yongkong.mp4` | `samples/`（未入庫，用 `mv`） |

`environment.yml` **不是**重複品：根那份 pin 了 `openpifpaf==0.13.11`／`torch==2.2.2`／`Pillow`／
`scipy`，`trafficlab-project/environment.yml` 是不 pin 的 torch 加 `hypothesis`。兩份都留。

### 刪（`git rm`）

| 對象 | 理由 |
| --- | --- |
| `location/`（11 檔） | md5 與 `trafficlab-project/location/` 逐檔相同 |
| `pifpaf/{eval_haware_replay.py, haware_localization.py, openpifpaf-apollo24.md}` | 過時副本，缺 spread 邊界的 `>=` 與非有限值修正；留著只會讓人讀錯版本 |
| `archive/`（`git rm -r --cached`） | 退出 git、留在磁碟；入庫量 170 → 144 MB |

### 不動

`scenes/`、`tools/` 內容、`docs/{specs,plans,decisions,diagrams,papers}`、
`threejs-v1/`（已 gitignore 的凍結基準版）、`trafficlab-project/` 既有內容。

---

## 四、要改的程式碼

### 4.1 因為 `threejs/` → `player/`

| 位置 | 改動 |
| --- | --- |
| `workbench/webapp.py:39` | `STATIC_ROOTS = ("player", "scenes")` |
| `workbench/webapp.py:665` | 回傳 `/player/index.html?scene=…` |
| `workbench/tests/test_webapp.py:438-460` | `safe_static("threejs", …)` → `"player"`，斷言同步 |
| `workbench/common.py:7`、`workbench/tests/test_common.py:4` | 註解裡的 `threejs/scene-loader.js` 路徑 |
| `tools/verify_scenes.mjs:11,87,117` | `/threejs/index.html` → `/player/index.html` |
| `index.html:6,8` | 轉址與連結改 `player/index.html` |
| `workbench/integrate.py:8` | docstring 的 `→ threejs/index.html?scene=<code>` |

`player/scene-loader.js:10` 的 `../scenes/` **不改** —— 兩者仍同層。

### 4.1b 因為 `satellite_pipeline/` → `workbench/`

| 位置 | 改動 |
| --- | --- |
| `workbench/paths.py:12` | docstring 目錄樹裡的 `satellite_pipeline/` |
| `workbench/tests/test_webapp.py:453` | 穿越測試字串 `"../satellite_pipeline/.env"` → `"../workbench/.env"` |
| `workbench/tests/test_webapp.py:460` | `safe_static("satellite_pipeline", …)` → `safe_static("workbench", …)` |
| `workbench/tests/test_webapp.py:362` | docstring 的 `/satellite_pipeline/output/_uploads/` |

第 453、460 兩處是**行為測試不是註解**：前者驗「往上跳出白名單會被擋」、後者驗「非白名單目錄
不開放」。改的是測試資料字串，斷言語意不變——但字串若不改，測的就是一個不存在的目錄，
測試會照樣通過卻不再守住真正的邊界。

### 4.2 因為 `open-player.command` 移進 `tools/`

```bash
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
```

同時把 `threejs` 改成 `player`，並拿掉 `threejs-v1` / `live` 的雙版本分支（`threejs-v1/` 已不入庫）。

### 4.3 因為 `detection_tests/` 進了 `trafficlab-project/`

`trafficlab-project/detection_tests/viz_model_compare.py:29-33`：

```python
HERE = Path(__file__).resolve().parent      # trafficlab-project/detection_tests
TLAB = HERE.parent                          # trafficlab-project
ROOT = TLAB.parent                          # repo root
```

### 4.4 因為刪掉頂層 `location/` 與 `pifpaf/`

`trafficlab-project/tests/test_haware_baseline_scope_integration.py:195-196` 移除這兩行：

```python
self.assertTrue((REPOSITORY_ROOT / "pifpaf").is_dir())
self.assertTrue((REPOSITORY_ROOT / "location").is_dir())
```

它們只是後面「production 程式碼不得 import／寫入這兩棵樹」守衛的前置檢查。樹刪掉後守衛變空轉但仍
有效（防止未來有人重新引入這種相依）。**保留** `forbidden_imports` 與 `literal_writes` 兩組斷言。

### 4.5 `.gitignore`

```gitignore
/archive/          # 舊驗證截圖，留在磁碟不入庫
/pifpaf-weights/   # 92 MB openpifpaf 權重
```

`samples/tainan_yongkong.mp4` 已被既有的 `*.mp4` 規則涵蓋。
`satellite_pipeline/.gitignore`（`output/`）與 `trafficlab-project/.gitignore`（`.venv-pifpaf`）
隨目錄一起搬，規則自動繼續生效。

### 4.6 文件

**更新**（活的指令與現行敘述，行號已逐條核對）：

| 檔案 | 行 | 內容 |
| --- | --- | --- |
| `CLAUDE.md` | 43-47 | 驗證五件套：`threejs/lib/tests` → `player/lib/tests`、`satellite_pipeline/tests` → `workbench/tests` |
| `CLAUDE.md` | 38 | 碰撞物理段的 `node --test threejs/lib/tests/*.test.js` |
| `CLAUDE.md` | 132 | 新影片進場流程第 3 步的 `threejs/index.html?scene=<code>` |
| `README.md` | 7, 148-154 | `satellite_pipeline/webapp.py` → `workbench/webapp.py`；`/threejs/index.html` → `/player/index.html` |
| `README.md` | 82-120 | **目錄樹整塊重寫**（含 `.kiro/specs/`、`satellite_pipeline/`、`detection_tests/`、`threejs/` 四個條目） |
| `README.md` | 30, 62, 70, 73 | 敘述中的 `threejs/…` 路徑 |
| `README.md` | 49-51 | `.kiro/specs/haware-localization-accuracy/` 三個連結 → `docs/legacy-specs/…` |
| `workbench/README.md` | 21 | `python3 satellite_pipeline/webapp.py` → `python3 workbench/webapp.py` |
| `docs/reference.md` | 40 | `threejs/models/registry.json` → `player/models/registry.json` |
| `docs/decisions/2026-08-17-satellite-genai-provider-choice.md` | 73 | `python3 satellite_pipeline/measure_genai_drift.py …` |

`README.md:36` 的 `docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md` 是**檔名**，不改。

**不改**（歷史文件）：`docs/plans/`、`docs/decisions/` 內描述當時狀態的敘述。
歷史文件寫的是「當時叫什麼」，機械式改名會讓記錄失真。必要時在檔頭加一行
「本文件寫於重整前，`satellite_pipeline/` 現為 `workbench/`」。

### 4.7 新增 `trafficlab-project/OWNERSHIP.md`

寫明三件事：

1. 上游是 yuk068/TrafficLab 的 fork，於 commit `9b2cc53` 以直接來源方式併入
2. **我們維護**：`trafficlab/motion/haware_*`、`haware_accuracy/`、`localization_authority.py`、
   `io/haware_*`、`measurement/`、`projection/haware_forward.py`、
   `inference/pifpaf_haware_adapter.py`、`tests/`（25 支）、`tests/properties/`（19 支）
3. **隊友主導、凍結中**：`inference/pipeline.py`、`trajectory/`、`gui/`、`postprocess.py`、
   `inference_config.yaml`、`models/`

---

## 五、`.venv-pifpaf` 不需重建

實測（`trafficlab-project/.venv-pifpaf`）：

| 檢查 | 結果 |
| --- | --- |
| `sys.prefix` | 由 executable 位置推導，非寫死 |
| `bin/python` | symlink → `~/.local/share/uv/python/…`（venv 外部，與搬家無關） |
| `.pth` 檔 | 只有 `_virtualenv.pth`、`distutils-precedence.pth`，皆無絕對路徑 |
| editable install | 無任何指回本專案的 `__editable__` / `direct_url.json` |
| `bin/` console script | 20 支 shebang 寫死舊路徑 —— **但我們一支都沒用** |

本設計不搬動 `trafficlab-project/`，因此連上述風險都不存在。列在這裡是為了記錄：
**未來若要搬，只會壞 console script 與 `source activate`，`bin/python -m …` 照常運作。**

---

## 六、實作順序

分成**三個 commit**，結構移動與路徑修改**不可混在同一個 commit** —— 混了 `git log --follow`
就追不到 rename。

### 第 0 步：保住現況

> **2026-08-20 14:57 更新**：本設計初稿寫的是「8 個 modified + 2 個 untracked 要先 checkpoint」。
> 那批改動已由另一個 session 在 `fix/web-flow-basemap-variant-and-integrate-chain` 上以 6 個
> commit 收掉（含本文件本身，commit `0a95356`）。**起點因此改變**，第 0 步簡化如下。

起點檢查 —— 三件事都要成立才動手：

```bash
git branch --show-current     # 預期 fix/web-flow-basemap-variant-and-integrate-chain
git status --short            # 只應剩兩個未追蹤項（見下）
git log --oneline -1          # 預期 d19cb44
```

工作區僅存的兩個未追蹤項，動手前先決定去留（**不要用 `git add -A` 一把收進來**，
那會把產物與 `.superseded` 備份永久寫進歷史）：

| 未追蹤項 | 建議 |
| --- | --- |
| `scenes/tainan_yongkong/` | **入庫**——它是第一個走完網頁流程 ①②③ 的真實場景包，屬於成果 |
| `trafficlab-project/location/tainan_yongkong/G_projection_*.json.superseded.*` | **刪除**——被取代的備份檔，不入庫 |

從當前分支切出重整分支並標記回復點：

```bash
git switch -c chore/directory-reorg
git tag reorg-preflight-20260820
```

**接著跑一次完整五件套並存下輸出**，用來分辨「本來就壞的」與「搬家弄壞的」。
新分支上的 `trafficlab-project/tests/test_filter_and_enrich_position_gate.py` 是本次新增的測試，
基準線要含它。

### 第 1 步：純結構移動

只有 `git mv` / `git rm` / `mv`，不改任何一個位元組的檔案內容。
**這個中間點預期是跑不動的**，只驗結構與 rename 偵測：

```bash
test -f player/index.html && test -f scenes/test1/scene.json
git diff --cached --summary          # 應該全是 rename，不是 delete+create
git commit -m "chore: reorganize project directories"
git log --follow -- player/scene-loader.js    # 追得到歷史才算成功
```

### 第 2 步：路徑與文件修正

第四節的全部改動，加上清快取（21 個 `__pycache__`、293 個 `.pyc`，
搬動後會留下 stale `co_filename`）：

```bash
find workbench tools trafficlab-project \
  -path 'trafficlab-project/.venv-pifpaf' -prune -o \
  -type d -name __pycache__ -prune -exec rm -rf {} +
```

---

## 七、驗收

重整後的驗證五件套：

```bash
node --test player/lib/tests/*.test.js                            # 改：threejs → player
python3 -m unittest discover -s tools/tests                       # 不變
python3 -m unittest discover -s workbench/tests                   # 改：satellite_pipeline → workbench
(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests)   # 不變
node tools/verify_scenes.mjs                                      # 不變
```

檢查點：

| 時機 | 跑什麼 | 期望 |
| --- | --- | --- |
| 動手前 | 全部五條，存下輸出 | 建立基準線 |
| 第 1 步後 | 只檢查結構與 rename 偵測 | 不期望測試會過 |
| 第 2 步後 | 第 1–4 條 | 全過；第 4 條專門抓 vendor 樹的假設 |
| 最後 | 第 5 條 | 全場景過 —— 它是唯一會實際渲染、驗 `/player/` 與 `../scenes/` 的 |

**最終殘留引用檢查**（不要求歸零，要求逐條分類成「可執行／現行敘述／歷史敘述／出處記錄」）：

```bash
rg -n 'satellite_pipeline|threejs|detection_tests' \
  README.md CLAUDE.md docs workbench tools player index.html
```

---

## 八、明確不做的事

| 不做 | 理由 |
| --- | --- |
| 把 `trafficlab-project/` 改成 git submodule 或 subtree | 沒有已驗證的 upstream URL 與 canonical ref（`git remote -v` 只有本 repo 的 origin）。等 URL 確認後再考慮 subtree —— 它比 submodule 更適合這裡，因為能保持 demo 自給自足 |
| 把 haware 子系統抽到頂層 | 隊友 4 支檔案 import 我們的 `localization_authority`；抽出要改他們的碼，且未來拉更新更痛 |
| 把 `trafficlab-project/` 瘦身（移除 `media/` 23 MB、未用的 `location/`） | 使用者決定原封保留。可日後另案處理 |
| 重寫 git 歷史移除大檔 | `.git` 189 MB 的既往體積不會因 `git rm --cached` 變小，但重寫歷史會讓所有既有 clone 失效 |
| 機械式改寫歷史文件裡的舊目錄名 | 歷史文件記錄的是當時狀態 |
| 引入 `frontend/` / `backend/` 二分 | `workbench/web/*.html` 本身就是前端頁面，二分法在這個 repo 是假的 |

---

## 附錄：Codex 審查

本設計經 Codex 獨立審查（session `01a01d33-e763-7e91-806a-ed8934b0bed4`），
其指出而原設計遺漏的項目已全數併入：`detection_tests` 的 repo-root 假設、
`test_haware_baseline_scope_integration.py` 的存在性斷言、兩份 `environment.yml` 並非重複、
`.kiro/` 的活連結、`archive/` 尚未被 ignore、`__pycache__` 的 stale `co_filename`、
三段式 commit 順序、以及 `onboarding/` → `workbench/` 的命名建議。

Codex 針對「搬進 `vendor/`」提出的四處 repo 深度修正
（`test_downstream_localization_authority.py:194`、
`test_haware_replay_adapter_integration.py:12,163`、
`haware_observation_replay.py:627,662`）在本設計中**不需要**——
因為 `trafficlab-project/` 留在頂層、深度未變。
