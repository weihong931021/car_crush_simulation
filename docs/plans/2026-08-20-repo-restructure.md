# 收尾階段目錄重整 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal**：把頂層整理成「一眼分得出我們的前後端／資料／隊友那包」，同時刪掉重複與過時副本。

**Architecture**：三段式 commit —— ①起點與基準線 ②純結構移動（只有 `git mv`／`git rm`，不改任何檔案內容）
③路徑與文件修正。結構與內容分開 commit，`git log --follow` 才追得到 rename。
`player/` 與 `scenes/` 保持同層，`trafficlab-project/` 留在頂層不改名，因此兩個最大的路徑約束都不必碰。

**Tech Stack**：git、Python 3（stdlib unittest）、Node（`node --test`、Playwright）、zsh

**Spec**：[docs/specs/2026-08-20-repo-restructure-design.md](../specs/2026-08-20-repo-restructure-design.md)

## Global Constraints

- **結構移動與內容修改不可同一個 commit**。Task 2 的 commit 內容必須 100% 是 rename／delete，
  `git diff --cached --summary` 不得出現 `create mode` 與 `delete mode` 成對出現的偽 rename。
- **`player/` 與 `scenes/` 必須維持頂層同層**。`player/scene-loader.js:10` 的 `../scenes/` 不得修改。
- **`trafficlab-project/` 目錄名不得改動**。改成 `trafficlab/` 會與其內同名 Python 套件衝突，
  repo root 進 `sys.path` 時 `import trafficlab` 會解析到空的 namespace package。
- **`.venv-pifpaf` 不搬、不重建**。
- **歷史文件不做機械式改名**：`docs/plans/`、`docs/decisions/` 內描述當時狀態的敘述保持原樣。
- **基準線（2026-08-20 實測，全綠）**，任何一項退步都算重整造成的迴歸：

  | 指令 | 期望 |
  | --- | --- |
  | `node --test <player>/lib/tests/*.test.js` | 89 測、86 pass、**0 fail**、3 todo |
  | `python3 -m unittest discover -s tools/tests` | **46 OK** |
  | `python3 -m unittest discover -s <workbench>/tests` | **110 OK** |
  | `(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests)` | **266 OK**（約 170 秒） |
  | `node tools/verify_scenes.mjs` | **4 場景全過**（tainan_yongkang、tainan_yongkong、taipei-cm、test1） |

---

## File Structure

### 目錄搬遷（Task 2 一次做完）

| 現在 | 之後 | 責任 |
| --- | --- | --- |
| `satellite_pipeline/` | `workbench/` | 進場流程 ①②③④ 端到端工作台（HTTP server + 影像 + 標註 + 整合） |
| `threejs/` | `player/` | 3D 播放器與碰撞模擬 |
| `detection_tests/` | `trafficlab-project/detection_tests/` | 偵測模型驗收記錄（讀的全是那棵樹的 footage／models） |
| `environment.yml` | `environments/trafficlab-pifpaf.yml` | pifpaf 環境配方 |
| `open-player.command` | `tools/open-player.command` | 雙擊開播放器 |
| `.kiro/specs/haware-localization-accuracy/` | `docs/legacy-specs/haware-localization-accuracy/` | Kiro 時期的 spec |
| `docs/filter_and_enrich_output.md` | `docs/trafficlab-notes/filter_and_enrich_output.md` | 我們對隊友腳本的筆記 |
| `docs/*.pdf`（2 份中文） | `docs/handouts/` | 交付簡報 |
| `pifpaf/` | `pifpaf-weights/` | 92 MB 權重（未入庫） |
| `tainan_yongkong.mp4` | `samples/tainan_yongkong.mp4` | 範例影片（未入庫） |
| `location/`（頂層 11 檔） | **刪除** | 與 `trafficlab-project/location/` 逐檔 md5 相同 |
| `pifpaf/` 內 3 支 .py/.md | **刪除** | 過時副本 |
| `archive/` | 退出 git、留磁碟 | 舊截圖 |

### 要改內容的檔案（Task 3–8）

| 檔案 | 責任 | 任務 |
| --- | --- | --- |
| `workbench/webapp.py` | `STATIC_ROOTS`、回傳給前端的播放器網址 | 3 |
| `workbench/tests/test_webapp.py` | 靜態服務與路徑穿越測試 | 3, 4 |
| `tools/verify_scenes.mjs` | headless 冒煙驗證的 URL | 3 |
| `index.html` | 根目錄轉址 | 3 |
| `workbench/integrate.py`、`workbench/common.py`、`workbench/tests/test_common.py` | docstring／註解裡的路徑 | 3 |
| `workbench/paths.py` | docstring 目錄樹 | 4 |
| `trafficlab-project/detection_tests/viz_model_compare.py` | repo root 推導 | 5 |
| `trafficlab-project/tests/test_haware_baseline_scope_integration.py` | 移除已刪除樹的存在性斷言 | 5 |
| `tools/open-player.command` | repo root 推導 + 播放器目錄 | 6 |
| `trafficlab-project/OWNERSHIP.md` | **新建**，標示混合歸屬 | 7 |
| `CLAUDE.md`、`README.md`、`workbench/README.md`、`docs/reference.md`、`docs/decisions/2026-08-17-*.md` | 活的指令與敘述 | 8 |

---

## Task 1: 起點確認與基準線

**Files:** 不改任何檔案（只有 git 分支操作）

**Interfaces:**
- Produces: 分支 `chore/directory-reorg`、tag `reorg-preflight-20260820`、基準線輸出檔

- [ ] **Step 1: 確認起點**

```bash
cd /Users/weihong/Documents/blender_crash_project
git branch --show-current     # 預期 fix/web-flow-basemap-variant-and-integrate-chain
git log --oneline -1          # 預期 d19cb44
git status --short
```

預期 `git status --short` 只有兩個未追蹤項：

```text
?? scenes/tainan_yongkong/
?? trafficlab-project/location/tainan_yongkong/G_projection_tainan_yongkong.json.superseded.20260820-012452
```

若不符（有其他未 commit 改動），**停下來問人**，不要自行 `git add -A`。

- [ ] **Step 2: 處理兩個未追蹤項**

`scenes/tainan_yongkong/` 是第一個走完網頁流程 ①②③ 的真實場景包，屬於成果，入庫。
`.superseded.*` 是被取代的備份檔，刪除。

```bash
rm trafficlab-project/location/tainan_yongkong/G_projection_tainan_yongkong.json.superseded.20260820-012452
git add scenes/tainan_yongkong/
git commit -m "加 tainan_yongkong 場景包：第一個走完網頁流程的真實場景"
git status --short        # 預期：空
```

- [ ] **Step 3: 開重整分支並標記回復點**

```bash
git switch -c chore/directory-reorg
git tag reorg-preflight-20260820
git tag -l reorg-preflight-20260820     # 預期印出 tag 名
```

- [ ] **Step 4: 跑基準線五件套並存下輸出**

```bash
mkdir -p /tmp/reorg-baseline
node --test threejs/lib/tests/*.test.js            > /tmp/reorg-baseline/1-player.txt 2>&1
python3 -m unittest discover -s tools/tests        > /tmp/reorg-baseline/2-tools.txt 2>&1
python3 -m unittest discover -s satellite_pipeline/tests > /tmp/reorg-baseline/3-workbench.txt 2>&1
(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests) \
                                                    > /tmp/reorg-baseline/4-trafficlab.txt 2>&1
node tools/verify_scenes.mjs                       > /tmp/reorg-baseline/5-scenes.txt 2>&1
```

- [ ] **Step 5: 確認基準線全綠**

```bash
grep -E "^# (pass|fail|todo)" /tmp/reorg-baseline/1-player.txt
grep -E "^Ran |^OK|^FAILED" /tmp/reorg-baseline/2-tools.txt
grep -E "^Ran |^OK|^FAILED" /tmp/reorg-baseline/3-workbench.txt
grep -E "^Ran |^OK|^FAILED" /tmp/reorg-baseline/4-trafficlab.txt
tail -1 /tmp/reorg-baseline/5-scenes.txt
```

Expected：

```text
# pass 86
# fail 0
# todo 3
Ran 46 tests in 0.0XXs / OK
Ran 110 tests in X.XXXs / OK
Ran 266 tests in XXX.XXXs / OK
✓ 4 場景全過
```

任一項不符 —— **停下來**。基準線不綠就沒辦法分辨後續失敗是誰造成的。

---

## Task 2: 純結構移動

**Files:**
- Move: 上方「目錄搬遷」表全部
- Modify: `.gitignore`（新增兩條忽略規則，見 Step 4）

**Interfaces:**
- Consumes: Task 1 的 `chore/directory-reorg` 分支
- Produces: 新目錄佈局；後續所有任務的路徑都以此為準

> `.gitignore` 是唯一在本任務被修改內容的檔案。它必須跟 `git rm -r --cached archive` 同一個
> commit —— 分開做的話中間狀態會讓 `archive/` 變成一大坨未追蹤檔案。它與 rename 偵測無關。

- [ ] **Step 1: 建立新的容器目錄**

```bash
mkdir -p environments samples docs/legacy-specs docs/trafficlab-notes docs/handouts
```

- [ ] **Step 2: 搬（`git mv`）**

```bash
git mv satellite_pipeline workbench
git mv threejs player
git mv detection_tests trafficlab-project/detection_tests
git mv environment.yml environments/trafficlab-pifpaf.yml
git mv open-player.command tools/open-player.command
git mv .kiro/specs/haware-localization-accuracy docs/legacy-specs/haware-localization-accuracy
git mv docs/filter_and_enrich_output.md docs/trafficlab-notes/filter_and_enrich_output.md
git mv "docs/處理影片的終端機指令.pdf" docs/handouts/
git mv "docs/行車事故影片重建3d模型.pdf" docs/handouts/
```

`.kiro/` 搬完應該變空，移除它：

```bash
rmdir .kiro/specs .kiro 2>/dev/null || true
ls -a .kiro 2>/dev/null || echo ".kiro 已消失"
```

- [ ] **Step 3: 刪（`git rm`）**

```bash
git rm -r location
git rm pifpaf/eval_haware_replay.py \
       pifpaf/haware_localization.py \
       pifpaf/openpifpaf-apollo24.md
```

- [ ] **Step 4: `archive/` 與 `pifpaf-weights/` 退出 git**

先改 `.gitignore` —— 在 `threejs-v1/` 那條之後補上：

```gitignore
# 凍結的基準播放器（本地快速參考，不入庫）
threejs-v1/
# 開發過程驗證截圖：留在磁碟供查閱，不入庫（2026-08-20 重整）
/archive/
# openpifpaf apollo24 權重 92 MB：模型檔不入庫
/pifpaf-weights/
```

再退出追蹤並改名權重目錄：

```bash
git rm -r --cached archive
mv pifpaf pifpaf-weights
git add .gitignore
```

- [ ] **Step 5: 搬未追蹤的範例影片**

`*.mp4` 已被 gitignore，git 管不到，用一般 `mv`：

```bash
mv tainan_yongkong.mp4 samples/tainan_yongkong.mp4
ls samples/       # 預期看到 tainan_yongkong.mp4
```

- [ ] **Step 6: 清 `__pycache__`（stale `co_filename`）**

搬動後舊 `.pyc` 內嵌的是舊路徑，會讓 traceback 指向不存在的檔案。**排除 venv**，
那 912 MB 不該碰：

```bash
find workbench tools trafficlab-project \
  -path 'trafficlab-project/.venv-pifpaf' -prune -o \
  -type d -name __pycache__ -prune -exec rm -rf {} +
find . -path ./.git -prune -o -path '*/.venv-pifpaf' -prune -o \
  -type d -name __pycache__ -print | wc -l      # 預期 0
```

- [ ] **Step 7: 驗證這是一次乾淨的 rename**

```bash
git add -A
git diff --cached --summary | grep -c "^ rename"      # 預期 > 0
git diff --cached --summary | grep "^ create mode\|^ delete mode" | head -20
```

Expected：`delete mode` 只該出現在 `location/` 的 11 檔、`pifpaf/` 的 3 檔、`archive/` 的 37 檔；
`create mode` 不該出現任何一個「其實是搬過去的」檔案。若看到成對的 create/delete，
表示相似度偵測失敗 —— 檢查是不是不小心改到了內容。

```bash
test -f player/index.html && test -f player/scene-loader.js && echo "player OK"
test -f workbench/webapp.py && test -f workbench/web/index.html && echo "workbench OK"
test -f scenes/test1/scene.json && echo "scenes 仍在頂層 OK"
test -x trafficlab-project/.venv-pifpaf/bin/python && echo "venv 未受影響 OK"
test -f trafficlab-project/detection_tests/viz_model_compare.py && echo "detection_tests OK"
test ! -d location && test ! -d .kiro && echo "已刪除的目錄確實消失 OK"
```

`detection_tests/` 搬進 `trafficlab-project/` 之後會受那份 `.gitignore` 管轄，確認 4 個檔案
沒有被新規則吃掉（`output/*` 含斜線所以錨定在 `trafficlab-project/output/`，
不會誤傷 `detection_tests/outputs/`——但還是驗一下）：

```bash
git ls-files trafficlab-project/detection_tests | wc -l    # 預期 4
git check-ignore -v trafficlab-project/detection_tests/outputs/*.png || echo "  未被 ignore ✓"
```

- [ ] **Step 8: Commit 結構移動**

```bash
git commit -m "chore: 目錄重整——前後端按角色改名、刪重複與過時副本

satellite_pipeline → workbench（端到端工作台，不只 onboarding）
threejs            → player（說它是什麼，不說用什麼技術）
detection_tests    → trafficlab-project/detection_tests（讀的是那棵樹的資產）
刪 頂層 location/（與 trafficlab-project/location/ 逐檔 md5 相同）
刪 pifpaf/ 的 3 支過時副本（缺 spread 邊界修正，留著會讓人讀錯版本）
archive/ 退出 git 保留磁碟

本 commit 不改任何檔案內容（.gitignore 除外），路徑修正在下一個 commit。"
```

- [ ] **Step 9: 確認 rename 歷史追得到**

```bash
git log --follow --oneline -3 -- player/scene-loader.js
git log --follow --oneline -3 -- workbench/webapp.py
```

Expected：兩者都印出**重整之前**的 commit（例如 `48c43d8`、`b3ed883`），不是只有這一筆。

---

## Task 3: `threejs/` → `player/` 的路徑修正

**Files:**
- Modify: `workbench/webapp.py:39`、`:665`
- Modify: `workbench/tests/test_webapp.py:438`、`:446-447`、`:456`
- Modify: `tools/verify_scenes.mjs:11`、`:87`、`:117`
- Modify: `index.html:6`、`:8`
- Modify: `workbench/integrate.py:8`、`workbench/common.py:7`、`workbench/tests/test_common.py:4`
- **不改**：`player/scene-loader.js:10`

**Interfaces:**
- Consumes: Task 2 的 `player/` 目錄
- Produces: `webapp.safe_static("player", …)` 可用；API 回傳 `{"player": "/player/index.html?scene=<code>"}`
  —— `workbench/web/integrate.html:322` 用 `location.href = r.player` 導向，**這是唯一控制點**

- [ ] **Step 1: 先改測試（TDD：讓它紅）**

`workbench/tests/test_webapp.py` —— 三處：

```python
# :438 docstring
    """播放器要能從這台 server 開，所以得服務 player/ 與 scenes/。

# :446-447
        got = webapp.safe_static("player", "index.html")
        self.assertEqual(got, webapp.REPO_ROOT / "player" / "index.html")

# :456
                self.assertIsNone(webapp.safe_static("player", bad))
```

- [ ] **Step 2: 跑測試確認它失敗**

```bash
python3 -m unittest discover -s workbench/tests -k StaticServeTest -v 2>&1 | tail -20
```

Expected：`test_正常路徑可通過` FAIL —— `safe_static("player", …)` 回 `None`，
因為 `STATIC_ROOTS` 還是 `("threejs", "scenes")`。

- [ ] **Step 3: 改 `workbench/webapp.py`**

`:37-39`：

```python
# 播放器要從這台 server 開，而 scene-loader.js 走 `../scenes/` 相對路徑，
# 所以站根必須同時看得到這兩個同層目錄（CLAUDE.md 的部署約束）。只開這兩個。
STATIC_ROOTS = ("player", "scenes")
```

`:665`：

```python
    return {"scene": f"scenes/{code}", "player": f"/player/index.html?scene={code}"}
```

- [ ] **Step 4: 跑測試確認它通過**

```bash
python3 -m unittest discover -s workbench/tests -k StaticServeTest -v 2>&1 | tail -10
```

Expected：OK

- [ ] **Step 5: 改 `tools/verify_scenes.mjs`**

三處字串，`:11`（註解）、`:87`、`:117`：

```javascript
//      http://127.0.0.1:8946/player/index.html?scene=<code>，
```

```javascript
      const res = await fetch(`${BASE}/player/index.html`);
```

```javascript
    await page.goto(`${BASE}/player/index.html?scene=${code}`,
```

- [ ] **Step 6: 改根目錄 `index.html`**

`:6` 與 `:8`：

```html
  <script>location.replace('player/index.html' + location.search + location.hash);</script>
```

```html
<body><a href="player/index.html">前往事故重建 Demo</a></body>
```

- [ ] **Step 7: 改三處註解／docstring**

```python
# workbench/integrate.py:8
    tools/build_scene.py                → scenes/<code>/ → player/index.html?scene=<code>
```

```python
# workbench/common.py:7
# 與 player/scene-loader.js 的場景代號規則（/^[\w-]+$/）維持同一條界線。
```

```python
# workbench/tests/test_common.py:4
這裡鎖住「只接受 [A-Za-z0-9_-]」這條界線，與 player/scene-loader.js 的場景代號規則一致。
```

- [ ] **Step 8: 跑套件 1、3、5**

```bash
node --test player/lib/tests/*.test.js 2>&1 | grep -E "^# (pass|fail|todo)"
python3 -m unittest discover -s workbench/tests 2>&1 | grep -E "^Ran |^OK|^FAILED"
node tools/verify_scenes.mjs 2>&1 | tail -1
```

Expected：`# pass 86` / `# fail 0` / `# todo 3`；`Ran 110 … OK`；`✓ 4 場景全過`

第 5 條是關鍵 —— 它是唯一會真的用瀏覽器打 `/player/index.html` 並解析 `../scenes/` 的驗證。

- [ ] **Step 9: Commit**

```bash
git add workbench/webapp.py workbench/tests/test_webapp.py workbench/integrate.py \
        workbench/common.py workbench/tests/test_common.py \
        tools/verify_scenes.mjs index.html
git commit -m "改 player/ 路徑：靜態白名單、API 回傳網址、冒煙驗證 URL"
```

---

## Task 4: `satellite_pipeline/` → `workbench/` 的路徑修正

**Files:**
- Modify: `workbench/paths.py`（docstring 目錄樹）
- Modify: `workbench/tests/test_webapp.py:362`、`:453`、`:460`

**Interfaces:**
- Consumes: Task 2 的 `workbench/` 目錄、Task 3 已改好的 `STATIC_ROOTS`
- Produces: 無新介面（`paths.py` 的常數值全部不變 —— `PKG_DIR` 由 `__file__` 推導、
  `REPO_ROOT = PKG_DIR.parent`、`TRAFFICLAB_DIR` 指向未改名的 `trafficlab-project`）

> `test_webapp.py:453` 與 `:460` 是**行為測試不是註解**。字串不改測試照樣會過，
> 但守的就變成一個不存在的目錄 —— 邊界名存實亡。

- [ ] **Step 1: 改 `workbench/tests/test_webapp.py` 的兩處測試資料**

`:453`（穿越測試 —— 往上跳出白名單）：

```python
        for bad in ("../workbench/.env", "../../etc/passwd", "/etc/passwd",
                    "a/../../.env"):
```

`:460`（白名單測試 —— 非白名單目錄不開放）：

```python
        self.assertIsNone(webapp.safe_static("workbench", "webapp.py"))
```

`:362`（docstring）：

```python
        `FileNotFoundError: ... /workbench/output/_uploads/...` 這種內部路徑，
```

- [ ] **Step 2: 跑測試確認仍然通過**

```bash
python3 -m unittest discover -s workbench/tests -k StaticServeTest -v 2>&1 | tail -10
```

Expected：OK（三個 test 全過）。這兩處改的是測試資料，斷言語意不變 ——
`../workbench/.env` 一樣該被擋、`workbench` 一樣不在白名單。

- [ ] **Step 3: 改 `workbench/paths.py` 的 docstring 目錄樹**

第 8-16 行那棵樹：

```python
    repo/
    ├── workbench/                   PKG_DIR
    │   ├── web/                     WEB_DIR      網頁工作台前端
    │   └── output/<code>/           OUTPUT_DIR   底圖與 meta（gitignore）
    │       └── _uploads/<code>/     UPLOAD_DIR   使用者上傳的影片／截圖暫存
    └── trafficlab-project/          TRAFFICLAB_DIR
        └── location/<code>/         LOCATION_ROOT  交付給標註 GUI 的成品
```

第 1 行的模組說明同步：

```python
"""workbench 的所有路徑，集中一處。
```

`TRAFFICLAB_DIR = REPO_ROOT / "trafficlab-project"` **不改** —— 那個目錄沒有改名。

- [ ] **Step 4: 跑完整套件 3**

```bash
python3 -m unittest discover -s workbench/tests 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Expected：`Ran 110 tests … OK`

- [ ] **Step 5: Commit**

```bash
git add workbench/paths.py workbench/tests/test_webapp.py
git commit -m "改 workbench/ 路徑：paths docstring 與白名單測試資料"
```

---

## Task 5: 刪除與搬移造成的 trafficlab-project 內部修正

**Files:**
- Modify: `trafficlab-project/detection_tests/viz_model_compare.py:29-33`
- Modify: `trafficlab-project/tests/test_haware_baseline_scope_integration.py:195-196`

**Interfaces:**
- Consumes: Task 2 移進來的 `detection_tests/`、已刪除的頂層 `location/` 與 `pifpaf/`
- Produces: 無新介面

- [ ] **Step 1: 改 `viz_model_compare.py` 的 repo root 推導**

它原本假設自己的 parent 就是 repo root。現在多了一層。第 27-33 行：

```python
# Project layout: this file sits in <root>/trafficlab-project/detection_tests/,
# the vendored pipeline (footage + models) lives in <root>/trafficlab-project/.
HERE = Path(__file__).resolve().parent      # trafficlab-project/detection_tests
TLAB = HERE.parent                          # trafficlab-project
ROOT = TLAB.parent                          # repo root
DEF_FOOTAGE = TLAB / "location/test1/footage/test1.mp4"
DEF_RIGHT = TLAB / "models/yolo11l-visdrone-ft.pt"
```

`DEF_OUTPUT`、`_LEFT_CANDIDATES` 沿用 `HERE` / `TLAB` / `ROOT`，語意不變。

- [ ] **Step 2: 驗證路徑推導正確**

這支腳本要 ultralytics（系統 python3 沒有），所以只驗常數不執行主流程：

```bash
python3 - <<'PY'
from pathlib import Path
here = Path("trafficlab-project/detection_tests").resolve()
tlab, root = here.parent, here.parent.parent
print("TLAB 對嗎:", (tlab / "inference_config.yaml").exists())
print("ROOT 對嗎:", (root / "CLAUDE.md").exists())
print("footage 路徑:", tlab / "location/test1/footage/test1.mp4")
PY
```

Expected：兩個 `True`。

- [ ] **Step 3: 先跑那支會壞的測試，確認它現在是紅的**

```bash
cd trafficlab-project && .venv-pifpaf/bin/python -m unittest \
  tests.test_haware_baseline_scope_integration -v 2>&1 | tail -15; cd ..
```

Expected：`test_legacy_root_trees_are_import_and_write_protected` FAIL ——
`AssertionError: False is not true`，因為頂層 `pifpaf/` 與 `location/` 已刪除。

- [ ] **Step 4: 移除兩行存在性斷言**

`trafficlab-project/tests/test_haware_baseline_scope_integration.py:194-196`，刪掉這兩行：

```python
        self.assertTrue((REPOSITORY_ROOT / "pifpaf").is_dir())
        self.assertTrue((REPOSITORY_ROOT / "location").is_dir())
```

在方法 docstring 補一句說明（放在 `def` 之後、`forbidden_imports = []` 之前）：

```python
    def test_legacy_root_trees_are_import_and_write_protected(self):
        """production 程式碼不得 import 或寫入 pifpaf/ 與 location/ 這兩棵舊樹。

        2026-08-20 目錄重整已刪除這兩棵頂層樹（location/ 與 trafficlab-project/location/
        逐檔 md5 相同；pifpaf/ 的 3 支是缺 spread 邊界修正的過時副本）。守衛本身保留 ——
        它防的是「未來有人重新引入這種相依」，樹不存在不影響這個目的。
        """
        forbidden_imports = []
```

**保留** `forbidden_imports` 與 `literal_writes` 兩組斷言，不要一起刪。

- [ ] **Step 5: 跑該測試確認轉綠**

```bash
cd trafficlab-project && .venv-pifpaf/bin/python -m unittest \
  tests.test_haware_baseline_scope_integration -v 2>&1 | tail -8; cd ..
```

Expected：OK

- [ ] **Step 6: 跑完整套件 4**

```bash
(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests) 2>&1 \
  | grep -E "^Ran |^OK|^FAILED"
```

Expected：`Ran 266 tests … OK`（約 170 秒）

- [ ] **Step 7: Commit**

```bash
git add trafficlab-project/detection_tests/viz_model_compare.py \
        trafficlab-project/tests/test_haware_baseline_scope_integration.py
git commit -m "修 trafficlab-project 內因重整而失效的路徑假設與斷言"
```

---

## Task 6: `tools/open-player.command`

**Files:**
- Modify: `tools/open-player.command`（整支改寫）

**Interfaces:**
- Consumes: Task 2 移進 `tools/` 的腳本、Task 3 改好的 `player/`
- Produces: 雙擊可開 `http://127.0.0.1:8950/player/index.html?scene=<code>`

> 它原本 `cd "$(dirname "$0")"` 把自己所在目錄當站根。移進 `tools/` 之後那會讓 HTTP 站根變成
> `tools/`，`player/` 與 `scenes/` 都看不到。另外 `threejs-v1/` 已不入庫，雙版本分支拿掉。

- [ ] **Step 1: 整支改寫**

```bash
#!/bin/bash
# 快速開啟碰撞播放器（雙擊即可）。
# 站根必須同時含 player/ 與 scenes/，相對路徑 ../scenes/ 才解得到，
# 所以這裡要回到 repo 根，不是腳本所在的 tools/。
set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
PORT=8950
SCENE="${1:-test1}"          # 可傳場景代號：tools/open-player.command tainan_yongkang

URL="http://127.0.0.1:${PORT}/player/index.html?scene=${SCENE}"

# server 沒開就開（背景），已開就沿用
if ! curl -s -o /dev/null "http://127.0.0.1:${PORT}/" 2>/dev/null; then
  echo "啟動本地 server (port ${PORT})…"
  (python3 -m http.server "${PORT}" >/dev/null 2>&1 &)
  sleep 1
fi

echo "開啟：${URL}"
open "${URL}"
```

- [ ] **Step 2: 確認可執行位元還在**

`git mv` 會保留，但確認一下：

```bash
ls -l tools/open-player.command      # 預期看到 -rwxr-xr-x
chmod +x tools/open-player.command   # 沒有的話補上
```

- [ ] **Step 3: 驗證站根解析正確（不實際開瀏覽器）**

```bash
bash -c 'REPO_ROOT="$(cd "$(dirname tools/open-player.command)/.." && pwd)"; echo "$REPO_ROOT"; test -d "$REPO_ROOT/player" && test -d "$REPO_ROOT/scenes" && echo "站根正確：player/ 與 scenes/ 都看得到"'
```

Expected：印出 repo 根絕對路徑 + `站根正確：…`

- [ ] **Step 4: 實際跑一次（會開瀏覽器，確認畫面出得來）**

```bash
tools/open-player.command test1
```

Expected：瀏覽器開啟播放器並載入 test1 場景，無「場景載入失敗」overlay。
確認後關掉分頁，並收掉背景 server：

```bash
lsof -ti tcp:8950 | xargs kill 2>/dev/null || true
```

- [ ] **Step 5: Commit**

```bash
git add tools/open-player.command
git commit -m "open-player 移進 tools/：站根回到 repo 根、改開 player/、拿掉 threejs-v1 分支"
```

---

## Task 7: `trafficlab-project/OWNERSHIP.md`

**Files:**
- Create: `trafficlab-project/OWNERSHIP.md`

**Interfaces:**
- Consumes: 無
- Produces: 供 `README.md` 的目錄樹（Task 8）連結

> 這棵樹裡有 64 檔／25,354 行是我們自己寫的（整套 haware 定位）。不寫下來的話，
> 半年後看到「trafficlab-project」這個名字會以為整包都不用碰。

- [ ] **Step 1: 建立檔案**

````markdown
# trafficlab-project 的歸屬

這棵樹是**混合歸屬**，不是純外來套件 —— 別把它整包當「別人的東西」跳過。

## 來源

上游是 [yuk068/TrafficLab](https://yuk068.github.io/) 的 fork，於 commit `9b2cc53`
（2026-06-04，訊息「Add trafficlab-project as direct source (detached from eric-hahha fork)」）
以**直接來源**方式併入本 repo，不是 submodule 也不是 subtree。
`git remote -v` 目前沒有記錄上游 URL，所以還原不到 canonical ref。

## 我們維護（64 檔、25,354 行）

整套 haware 定位子系統。**位置那半直接決定碰撞結論**，改動前先讀
`docs/decisions/2026-07-27-haware-localizer-parity-bug.md`。

```text
trafficlab/motion/haware_localization.py        haware_optimizer.py
trafficlab/motion/haware_hypotheses.py          haware_baseline_dispatch.py
trafficlab/motion/haware_accuracy/{models,validation}.py
trafficlab/motion/localization_authority.py
trafficlab/io/haware_observation_replay.py      haware_track_provenance.py
trafficlab/measurement/{haware_pilot,haware_held_out}.py
trafficlab/projection/haware_forward.py
trafficlab/inference/pifpaf_haware_adapter.py
tests/                     25 支
tests/properties/          19 支 property test
detection_tests/           偵測模型驗收記錄（2026-08-20 從頂層移入）
evidence/haware/           量測產物
```

另外我們也改過兩支隊友的腳本，加的是**編排契約**而非演算法：

- `scripts/eval_haware_replay.py` —— 影片與標定的解析度一致性檢查
- `scripts/filter_and_enrich_output.py` —— 「選到的 track 沒有可用位置」的擋下

## 隊友主導、凍結中（2026-07-20 起）

偵測與軌跡品質由隊友負責，本 repo 不再投入。**不要**在這些檔案上做優化：

```text
trafficlab/inference/pipeline.py     偵測管線與 bbox 品質過濾
trafficlab/trajectory/               軌跡平滑、繪圖
trafficlab/gui/                      PyQt5 GUI
postprocess.py  postprocess_config.yaml
inference_config.yaml                7 組 config，權重路徑全部指向不存在的檔案
models/                              YOLO 權重
```

## 反向相依（抽不出來的原因）

隊友的四支模組 import 我們的 `localization_authority`：

```text
trafficlab/visualization/sat_renderer.py
trafficlab/io/replay_writer.py
trafficlab/trajectory/smoothing.py
trafficlab/trajectory/plotting.py
```

所以 haware 那套**不能**單獨抽到 repo 頂層 —— 抽出要改他們四支檔案，
且未來拉隊友更新會更痛。這就是 2026-08-20 重整時決定「留在原地、只標示歸屬」的理由。

## 目錄名為什麼不改成 `trafficlab/`

會與其內的 Python 套件 `trafficlab/` 同名。repo root 一旦進 `sys.path`
（從 repo 根目錄跑 `python3` 就會），`import trafficlab` 會解析到**空的 namespace package**、
`import trafficlab.motion` 拋 `ModuleNotFoundError`，而錯誤訊息完全不指向真正原因。已實測確認。

## 測試

```bash
cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests
```

**必須用 `.venv-pifpaf`** —— 理由不是 numpy（系統 python3 有），而是整包 discover 會經
`trafficlab/gui/` → `inference/pipeline.py` 載 `ultralytics`，系統 python3 沒有。
2026-08-20 實測 266 測全過，約 170 秒。
````

- [ ] **Step 2: 驗證裡面提到的路徑都真的存在**

```bash
cd /Users/weihong/Documents/blender_crash_project/trafficlab-project
for p in trafficlab/motion/haware_localization.py trafficlab/motion/localization_authority.py \
         trafficlab/io/haware_observation_replay.py trafficlab/measurement/haware_pilot.py \
         trafficlab/projection/haware_forward.py trafficlab/inference/pifpaf_haware_adapter.py \
         trafficlab/inference/pipeline.py trafficlab/trajectory trafficlab/gui \
         postprocess.py inference_config.yaml models detection_tests \
         trafficlab/visualization/sat_renderer.py trafficlab/io/replay_writer.py \
         trafficlab/trajectory/smoothing.py trafficlab/trajectory/plotting.py; do
  test -e "$p" && echo "  ✓ $p" || echo "  ✗ $p 不存在——修正 OWNERSHIP.md"
done; cd ..
```

Expected：全部 ✓

- [ ] **Step 3: Commit**

```bash
git add trafficlab-project/OWNERSHIP.md
git commit -m "加 OWNERSHIP.md：這棵樹有 64 檔 25,354 行是我們自己的"
```

---

## Task 8: 文件更新

**Files:**
- Modify: `CLAUDE.md:38`、`:43-47`、`:132`
- Modify: `README.md:7`、`:30`、`:49-51`、`:62`、`:70`、`:73`、`:78-143`（目錄樹）、`:148-154`
- Modify: `workbench/README.md:1`、`:3`、`:21`
- Modify: `docs/reference.md:40`
- Modify: `docs/decisions/2026-08-17-satellite-genai-provider-choice.md:73`

**Interfaces:**
- Consumes: 前面所有任務完成後的最終佈局
- Produces: 文件裡的每一條指令都可直接複製執行

> **不改**：`docs/plans/`、`docs/decisions/`（除了上面那條可執行指令）、
> `docs/specs/` 內描述當時狀態的敘述。歷史文件記錄的是當時叫什麼。

- [ ] **Step 1: `CLAUDE.md` 三處**

`:38`：

```markdown
- 測試：`node --test player/lib/tests/*.test.js`（目錄形式會失敗，必用 glob）
```

`:43-47` 驗證五件套（同時把測試數更新成實測值）：

```bash
node --test player/lib/tests/*.test.js                      # 期望 fail 0（todo 3 是已知缺口）
python3 -m unittest discover -s tools/tests                  # 期望 OK（46 測）
python3 -m unittest discover -s workbench/tests              # 網頁流程/標註/整合/底圖（110 測）
(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests)  # haware（266 測）
node tools/verify_scenes.mjs                                 # 全場景 headless 冒煙，期望全過
```

`:132`：

```markdown
# 3. 播放器零改碼：player/index.html?scene=<code>；跑 node tools/verify_scenes.mjs 驗收
```

- [ ] **Step 2: `README.md` 的目錄樹（`:78-143`）**

四個條目要改，其餘保持原樣：

```text
├── index.html                      ← 根目錄轉址至 player/index.html
```

`.kiro/specs/` 那行改成（並移到 docs 區塊內）：

```text
│   ├── legacy-specs/               ← Kiro 時期 spec（haware 定位準確度）
│   ├── trafficlab-notes/           ← 我們對隊友腳本的使用說明
│   ├── handouts/                   ← 交付簡報 PDF
```

`satellite_pipeline/` 那塊的標題與第一行：

```text
├── workbench/                      ← 進場流程 ①②③④ 端到端工作台
│   ├── webapp.py                  ← ★ 進場流程 server（①②③④，同時服務 player/ 與 scenes/）
```

`archive/images/`、`detection_tests/`、`threejs-v1/`、`threejs/` 四行：

```text
├── archive/images/                 ← 淘汰衛星圖 + 開發驗證截圖（留磁碟，不入庫）
├── environments/                   ← trafficlab-pifpaf.yml（pifpaf 環境配方）
├── samples/                        ← 範例影片（不入庫）
├── threejs-v1/                     ← 播放器前一版（保留對照，不入庫）
├── player/
```

`trafficlab-project/` 那塊補一行：

```text
└── trafficlab-project/             ← 混合歸屬——見 OWNERSHIP.md（64 檔是我們的）
    ├── OWNERSHIP.md                ← ★ 先讀這個再決定要不要改裡面的東西
    ├── detection_tests/            ← VisDrone fine-tune vs COCO 驗收實驗
```

- [ ] **Step 3: `README.md` 其餘五處**

`:7`：`satellite_pipeline/webapp.py` → `workbench/webapp.py`
`:30`：`threejs/index.html?scene=<code>` → `player/index.html?scene=<code>`
`:49-51`：三個 `.kiro/specs/haware-localization-accuracy/…` 連結 → `docs/legacy-specs/haware-localization-accuracy/…`
`:62`、`:70`、`:73`：敘述中的 `threejs/lib/`、`threejs/index.html` → `player/…`
`:148-154`：

```bash
# 網頁工作台（進場流程 ①②③④ 全在這裡；同時也服務 player/ 與 scenes/）
python3 workbench/webapp.py

# → http://127.0.0.1:8765/player/index.html?scene=test1   直接看既有場景
python3 -m http.server 8765     # 站根要同時看得到 player/ 與 scenes/
```

- [ ] **Step 4: `workbench/README.md` 三處**

`:1`、`:3`、`:21`：

```markdown
# workbench — 進場流程 ①②③④ 端到端工作台
```

```markdown
供 `tools/build_scene.py --sat-dir` 取用，產生場景包的 `ground.png`。
```

```bash
python3 workbench/webapp.py        # → http://127.0.0.1:8765/
```

- [ ] **Step 5: `docs/reference.md:40` 與 decisions**

```markdown
  （CC Attribution）。此類 provenance 記在 `player/models/registry.json` 的 `_comment_provenance`。
```

`docs/decisions/2026-08-17-satellite-genai-provider-choice.md:73`：

```bash
python3 workbench/measure_genai_drift.py --code tainan_yongkang
```

- [ ] **Step 6: 逐條驗證文件裡的指令真的能跑**

```bash
cd /Users/weihong/Documents/blender_crash_project
test -f player/lib/tests/path.test.js        && echo "✓ CLAUDE.md:43 的 glob 有東西"
test -d workbench/tests                       && echo "✓ CLAUDE.md:45"
test -f workbench/webapp.py                   && echo "✓ README:7,149 / workbench README:21"
test -f workbench/measure_genai_drift.py      && echo "✓ decisions:73"
test -f player/models/registry.json           && echo "✓ reference.md:40"
test -d docs/legacy-specs/haware-localization-accuracy && echo "✓ README:49-51"
test -f trafficlab-project/OWNERSHIP.md       && echo "✓ README 目錄樹的 OWNERSHIP 連結"
```

Expected：七個 ✓ 全出現

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md README.md workbench/README.md docs/reference.md \
        docs/decisions/2026-08-17-satellite-genai-provider-choice.md
git commit -m "文件更新到重整後的路徑（歷史文件的敘述保持原樣）"
```

---

## Task 9: 全套驗收與殘留引用分類

**Files:** 不改檔案（除非發現遺漏）

**Interfaces:**
- Consumes: Task 1–8 全部完成
- Produces: 可交付的重整結果

- [ ] **Step 1: 跑完整五件套（新路徑）**

```bash
cd /Users/weihong/Documents/blender_crash_project
node --test player/lib/tests/*.test.js 2>&1 | grep -E "^# (pass|fail|todo)"
python3 -m unittest discover -s tools/tests 2>&1 | grep -E "^Ran |^OK|^FAILED"
python3 -m unittest discover -s workbench/tests 2>&1 | grep -E "^Ran |^OK|^FAILED"
(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests) 2>&1 \
  | grep -E "^Ran |^OK|^FAILED"
node tools/verify_scenes.mjs 2>&1 | tail -1
```

Expected（**與 Task 1 基準線逐項相同**）：

```text
# pass 86
# fail 0
# todo 3
Ran 46 tests … OK
Ran 110 tests … OK
Ran 266 tests … OK
✓ 4 場景全過
```

任一項退步 —— 回頭找是哪個 Task 造成的，不要在這裡硬修。

- [ ] **Step 2: 殘留引用掃描與分類**

```bash
rg -n 'satellite_pipeline|threejs|detection_tests|\.kiro' \
  README.md CLAUDE.md docs workbench tools player index.html \
  --glob '!docs/plans/**' --glob '!docs/specs/**' --glob '!docs/decisions/**'
```

**不要求歸零**，要求每一筆能歸到下列其中一類：

| 類別 | 處理 |
| --- | --- |
| 可執行指令／程式路徑 | **必須改**——漏了就是 bug |
| 現行敘述（描述現在的架構） | **必須改** |
| 歷史敘述（`docs/plans/`、`docs/specs/`、`docs/decisions/` 描述當時狀態） | 不改 |
| `threejs-v1/`、`threejs/vendor/three/`、`three.module.js` 等**技術名詞** | 不改——那是函式庫名不是目錄名 |

- [ ] **Step 3: 確認結構與體積**

```bash
ls -1
git count-objects -vH | grep size-pack
git ls-files | awk -F/ '{print $1}' | sort | uniq -c | sort -rn | head
```

Expected `ls -1` 頂層只剩這 13 項，用檢查取代目視：

```bash
diff <(ls -1) <(printf '%s\n' CLAUDE.md README.md archive docs environments index.html \
  pifpaf-weights player samples scenes threejs-v1 tools trafficlab-project workbench | sort) \
  && echo "頂層結構正確"
```

其中 `archive`、`pifpaf-weights`、`threejs-v1`、`samples` 在磁碟但已不入庫。
確認這四項確實不在 git 裡：

```bash
for d in archive pifpaf-weights threejs-v1 samples; do
  n=$(git ls-files "$d" | wc -l | tr -d ' ')
  [ "$n" = "0" ] && echo "  ✓ $d 未入庫" || echo "  ✗ $d 還有 $n 個檔案入庫"
done
```

- [ ] **Step 4: 確認 rename 歷史完整**

```bash
git log --follow --oneline -3 -- player/main.js
git log --follow --oneline -3 -- workbench/webapp.py
git log --follow --oneline -3 -- tools/open-player.command
```

Expected：三者都能追到 2026-08-20 之前的 commit。

- [ ] **Step 5: 更新 `docs/todonext.md`**

把重整這件事標記完成，並記下 tag：

```markdown
- [x] 收尾階段目錄重整（2026-08-20）——回復點 `git tag reorg-preflight-20260820`
      spec `docs/specs/2026-08-20-repo-restructure-design.md`
      計畫 `docs/plans/2026-08-20-repo-restructure.md`
```

- [ ] **Step 6: Commit 並回報**

```bash
git add docs/todonext.md
git commit -m "重整驗收通過：五件套與基準線逐項相同"
git log --oneline reorg-preflight-20260820..HEAD
```

Expected：7 個 commit（Task 2、3、4、5、6、7、8 各一）+ 本筆。

**回報時必須附上 Step 1 的實際輸出**，不要只說「都過了」。

---

## 風險與回復

| 風險 | 徵兆 | 回復 |
| --- | --- | --- |
| rename 偵測失敗、歷史斷掉 | Task 2 Step 9 的 `git log --follow` 只印出一筆 | `git reset --hard reorg-preflight-20260820`，檢查是不是搬的同時改了內容 |
| `verify_scenes.mjs` 找不到頁面 | `✗ N/4 場景失敗`、console error 有 404 | 確認 `STATIC_ROOTS`、`verify_scenes.mjs` 的 URL、`player/` 與 `scenes/` 是否仍同層 |
| trafficlab 套件 266 測出現 ImportError | `ModuleNotFoundError: trafficlab` | 確認 `trafficlab-project/` **沒有**被改名 |
| 舊 `.pyc` 造成 traceback 指向不存在的檔 | 錯誤訊息裡是 `satellite_pipeline/...` 舊路徑 | 重跑 Task 2 Step 6 的清快取 |
| 誤刪了還在用的東西 | 任何測試找不到檔案 | `git checkout reorg-preflight-20260820 -- <path>` |
