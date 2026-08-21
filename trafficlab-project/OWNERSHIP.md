# trafficlab-project 的歸屬

這棵樹是**混合歸屬**，不是純外來套件 —— **別把它整包當「別人的東西」跳過**。
裡面有 64 個檔案、25,354 行 Python 是我們自己寫的，是本 repo 頂層核心（5,821 行）的 4.4 倍。

## 來源

上游是 [yuk068/TrafficLab](https://yuk068.github.io/) 的 fork，於 commit `9b2cc53`
（2026-06-04，訊息「Add trafficlab-project as direct source (detached from eric-hahha fork)」）
以**直接來源**方式併入本 repo —— 不是 submodule 也不是 subtree。
`git remote -v` 目前沒有記錄上游 URL，所以還原不到 canonical ref；
要改成 subtree 得先確認上游位址。

## 我們維護

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
tests/                     24 支
tests/properties/          19 支 property test
detection_tests/           偵測模型驗收記錄（2026-08-20 從 repo 頂層移入）
evidence/haware/           量測產物
```

另外我們也改過兩支隊友的腳本，加的是**編排契約**而非演算法：

- `scripts/eval_haware_replay.py` —— 影片與標定的解析度一致性檢查
- `scripts/filter_and_enrich_output.py` —— 「選到的 track 沒有可用位置」就擋下

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

## 反向相依（haware 抽不出來的原因）

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

不改名還有一個附帶好處：目錄深度不變，樹內四處 repo 深度假設
（`tests/test_downstream_localization_authority.py` 的 `parents[2]`、
`tests/test_haware_replay_adapter_integration.py` 的 `REPOSITORY_ROOT` 與 `../scenes/` fixture、
`trafficlab/io/haware_observation_replay.py` 的 `parents[3]` 與字面值 `"trafficlab-project"`）
全部不必修改。

## 測試

```bash
cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests
```

**必須用 `.venv-pifpaf`** —— 理由不是 numpy（系統 python3 有），而是整包 discover 會經
`trafficlab/gui/` → `inference/pipeline.py` 載 `ultralytics`，系統 python3 沒有。
2026-08-20 實測 271 測全過，約 180 秒。

`.venv-pifpaf` 是 uv 建的（912 MB，未入庫）。`sys.prefix` 由 executable 位置推導、
`bin/python` 是指向 venv 外部 uv python 的 symlink、site-packages 沒有任何 editable install
指回本專案 —— 所以整個目錄搬家不會壞，只有 20 支 console script（`pip`／`ultralytics`／
`torchrun` 等）的絕對路徑 shebang 會斷，而本 repo 一支都沒用到。
