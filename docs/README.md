# docs/ 導覽

新來的先讀 repo 根的 [README.md](../README.md)（分工表 + 上手步驟），要動哪塊再回來查對應文件。

## 現行有效的 spec（動那塊之前必讀）

| 你要動的 | 先讀 | 狀態 |
| --- | --- | --- |
| `frontend/player/lib/` 碰撞物理 | [specs/2026-07-20-collision-simulation-design.md](specs/2026-07-20-collision-simulation-design.md) | ✅ 已實作，勿重新推導 |
| `scenes/` 場景包格式、`tools/build_scene.py` | [specs/2026-07-20-scene-bundle-threejs-demo-design.md](specs/2026-07-20-scene-bundle-threejs-demo-design.md) | ✅ 已實作 |
| `backend/` + `frontend/onboarding/` 進場流程 ①②③④ | [specs/2026-08-16-web-onboarding-flow-design.md](specs/2026-08-16-web-onboarding-flow-design.md) | ✅ 已實作 |
| haware 定位準度（trafficlab-project 內我們那半） | [specs/2026-08-10-haware-localization-accuracy-design.md](specs/2026-08-10-haware-localization-accuracy-design.md) | 進行中 |
| 目錄結構本身 | [specs/2026-08-20-repo-restructure-design.md](specs/2026-08-20-repo-restructure-design.md) | ✅ 已實作（含 08-21 前後端拆分後記） |

## 決策記錄（為什麼是現在這樣）

| 文件 | 一句話 |
| --- | --- |
| [decisions/2026-07-24-blender-threejs-contract-split.md](decisions/2026-07-24-blender-threejs-contract-split.md) | 為什麼全面轉 Three.js、Blender 退場 |
| [decisions/2026-07-27-haware-localizer-parity-bug.md](decisions/2026-07-27-haware-localizer-parity-bug.md) | 定位手性 bug 的完整證據——**改 haware 前必讀** |
| [decisions/2026-08-17-satellite-genai-provider-choice.md](decisions/2026-08-17-satellite-genai-provider-choice.md) | 生圖底圖的幾何漂移量測、provider 選擇 |

## 其他

- `plans/`：已執行完的實作計畫（歷史記錄，含舊目錄名，不回頭改）
- `legacy-specs/`：Kiro 時期的 haware spec（被 2026-08-10 spec 承接）
- `trafficlab-notes/`：對隊友腳本的使用說明
- `handouts/`：對外交付的簡報 PDF
- `papers/`：外部參考文獻
- [todonext.md](todonext.md)：待辦與各方向現況
- [reference.md](reference.md)：座標轉換、車規、指令速查
- [PROJECT.md](PROJECT.md)：專案總覽與競品分析
