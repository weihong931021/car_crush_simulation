# haware 定位優化：給路徑辨識負責人的交接摘要

日期：2026-08-10。完整設計見 `docs/specs/2026-08-10-haware-localization-accuracy-design.md`
（本 repo 根目錄的 `blender_crash_project/docs/specs/`）。這份只講**你需要知道的、
和需要你出手的**。

## 我們這邊做了什麼

- 把你交接的三個檔案（`haware_localization.py`、`eval_haware_replay.py`、apollo checkpoint）
  整合進 repo 並跑通全鏈：PifPaf → replay JSON → `position_m` → Three.js 場景包。
- 環境要點：openpifpaf 0.13.11 只有原始碼、硬綁 torch 1.13.1，另建了 Python 3.10 的
  `.venv-pifpaf`。細節見 `docs/openpifpaf-apollo24.md`。
- 確認你 2026-07-28 的**手性修正、展開度閘門、`n_wheel_kp`** 都在現行碼裡且運作正常。

## 我們接下來要優化什麼（一句話）

把定位**準確度**做上去。位置誤差 ≈（高度估計誤差 × 近地平線放大倍率），核心做法是
**輪子優先**（h=0 輪關鍵點免視差、高度實測，是唯一乾淨的輸入）。

## 需要你出手的三件事

1. **`yilan-cv` 缺 `G_projection`**：四個交接場景包裡只有它沒有校正檔，無法定位也無法驗收。
   能補一份嗎？
2. **位置 ground truth**：兩個站點都沒有真實位置標註，我們現在只能用 h=0 輪對量軌距、
   用行進方向量 heading 當代理指標——這些能證明「精密度」但不能證明「準確度」。如果你手上
   有任何幀的真實車輛位置（哪怕幾台車、幾個時刻），會是唯一能一槌定音的基準。
3. **PifPaf 前後標籤顛倒**：無輪關鍵點的 track（如你文件提到的 1/501/502）heading 前後顛倒，
   純幾何閘門擋不掉。這是 PifPaf 層的語意問題，想確認你那邊有沒有已知的處理方向。

## 兩個提醒（避免誤用）

- **驗收不要用 taipei-cm**：它有獨立於手性 bug 的 homography 度量缺陷（h=0 輪對量軌距
  中位 5.92 m vs 模板 2.55 m，合理區間內僅 12.5%；kee-cc 是 53.2%），z_cam 3.596 m 也是
  全 repo 最低。改用 kee-cc / taoyuan-tc。
- **我們只吃 `localize()` 的位置那半**（`sat_coords` → `position_m`）。heading 那半播放器
  自己從軌跡線段 `atan2(dx,dz)` 算，不讀你輸出的 heading——所以 heading 相關的改動對我們的
  demo 沒有直接影響，但對你的 replay/GUI 有用。
