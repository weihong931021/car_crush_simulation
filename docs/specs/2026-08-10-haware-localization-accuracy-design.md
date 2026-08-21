# haware 定位準確度優化設計

> **路徑對照（2026-08-21 目錄重整後讀本文必看）**：本文寫於重整前，內文的
> `satellite_pipeline/` ＝現在的 `backend/`（Python）＋ `frontend/onboarding/`（web/ 三頁）；
> `threejs/` ＝ `frontend/player/`；`scene-loader.js` 現走 `../../scenes/`。
> 其餘內容仍然有效。完整對照見 `CLAUDE.md` 的「Repo 結構」段。

> **⚠️ 已被取代（2026-08-16）**：本文件的正式規格是 Kiro spec
> [`.kiro/specs/haware-localization-accuracy/`](../../.kiro/specs/haware-localization-accuracy/)
> （requirements.md / design.md / tasks.md）。對應關係：
>
> - **誤差模型（§一）**與「輪子 h=0 是唯一乾淨輸入」的洞察 → 被吸收為優化器的 **wheel-seeded 假設優先起手**（排序偏好，非權重、非獨佔）
> - **§3.1 加權 Procrustes「輪子優先」** → 降級為 pilot 內的**診斷候選** `wheel_weighted_procrustes`（Kiro Requirement 12），
>   與 baseline／優化器同資料同指標對比，**永不進生產路徑、不參與任何決策**
> - **§3.2 近地平線前置剔除** → Kiro Requirement 1.21（`pre_gate_near_horizon`）
> - **§3.3 展開度閘門接下游** → Kiro Requirement 1.19–1.20（`legacy-localize-v1` 狀態政策）＋ 7.17–7.19（`build_scene.py` 綁定）
> - **§3.4 時序融合** → 明列為 out of scope（Kiro "Scope boundary and later phases"）
> - **§四 驗證階梯／§五 Phase 0 量尺** → Kiro Requirement 9（`gt-protocol-v1`）、10（`pilot-stats-v1`）
>
> 以下內容保留為史料與推理脈絡，**數字與階段規劃不再是行動依據**。

日期：2026-08-10　範圍：`trafficlab-project/trafficlab/motion/haware_localization.py`
及其上下游（`scripts/eval_haware_replay.py`、`scripts/filter_and_enrich_output.py`、
`tools/build_scene.py`）

> **一句話**：haware 定位的位置誤差可拆成「高度估計誤差 × 近地平線放大倍率」，
> 四個優化各打其中一項；但**位置準度從未被真正量過**，所以第一步是建量尺，
> 核心工作是「輪子優先」把演算法本身做準。

---

## 為什麼做這件事

路徑辨識負責人交接了一套用 OpenPifPaf 24 關鍵點做車輛定位的方法（`pifpaf/`，已整合，
見 `trafficlab-project/docs/openpifpaf-apollo24.md`）。整合後在真實影片上跑通了全鏈
（PifPaf → replay JSON → `position_m` → Three.js 場景包），但輸出品質**只有近端車輛可用**：
遠離相機的車位置誤差急速惡化，最遠可飄到路口外上百公尺。

這次優化的**目的是把定位演算法本身做準**（不是只求 demo 能多幾個場景）。這需要兩件事同時
成立：一是有一把能量「準確度」而非只量「精密度」的尺，二是針對誤差的真正來源改演算法。
本文件把這兩件事拆解成可執行的階段。

---

## 一、誤差模型（整個設計的脊椎）

每一幀的位置誤差可拆成兩個**相乘**的來源：

```text
位置誤差  ≈  ( 高度估計誤差 Δhᵢ  +  像素噪音 )  ×  近地平線放大倍率
```

**高度估計誤差 Δhᵢ。** `GProjection.cctv_to_sat(u, v, h)`（`g_projection.py:89-93`）對每個
keypoint 用它的模板高度 hᵢ 做視差修正，公式 `real = cam + (apparent − cam) · (z_cam − hᵢ)/z_cam`
（`parallax_correct_ground_to_real`，`g_projection.py:75-80`）。模板 24 個點裡只有四個輪子
在 h=0（`build_car_template` 的 `t[7],t[8],t[18],t[19]`），高度是**實測**且視差因子恰為 1
（免修正）；其餘車頂/車燈/後視鏡/保險桿的高度全是**估計值**（見 `haware_localization.py`
的 `H_BUMPER/H_LAMP/H_MIRROR/H_ROOF` 常數）。再加上 z_cam 本身被系統性高估 15–22%
（決策文件第四節），這一項帶系統偏差。

**近地平線放大倍率。** CCTV→地面的 homography 有投影分母，越靠畫面頂端（近地平線）分母越
接近 0，1 個 CCTV 像素就放大成好幾公尺。這是與**距離／俯角**相關、非隨機的放大。

四個優化各打一項，互補、可疊加、可獨立驗證：

| 優化 | 打誤差公式的哪一項 | 性質 |
| --- | --- | --- |
| **輪子優先** | 消掉「高度估計誤差 Δhᵢ」（輪子 h=0、零視差、實測） | 演算法改良（核心） |
| **近地平線剔除** | 從源頭砍掉「放大倍率」 | 幾何前置過濾 |
| **展開度閘門** | 偵測「兩項相乘後爆掉」的症狀並拒答 | 已實作，缺接下游 |
| **多幀時序融合** | 平均掉「像素噪音」的隨機部分 | 後處理，最複雜 |

---

## 二、現況（動手前必讀，避免重做已完成的部分）

2026-07-28 的手性修正一併帶進了兩個原本規劃的優化，現行程式碼已有：

| 項目 | 位置 | 狀態 |
| --- | --- | --- |
| 座標系手性修正（鏡射 `Q` 的 x 欄） | `haware_localization.py:352` | ✅ 已套用，14 測回歸（`tests/test_haware_localization.py`） |
| 展開度品質閘門（`spread_m > 8.0` → `status='extrapolated'`） | `haware_localization.py:382`、`DEFAULT_MAX_SPREAD_M`=`:27` | ✅ 已在定位器實作，eval 預設開啟 |
| 輪點數指標 `n_wheel_kp` | `haware_localization.py:393`、`WHEEL_KP_IDX=(7,8,18,19)`=`:38` | ✅ 已輸出到 replay JSON，但僅供診斷 |

**兩個直接的推論：**

1. **「展開度閘門」這個想法在定位器層已經做完**，剩下的是把 `status='extrapolated'` 接進
   `build_scene.py`——目前 `build_scene.py:53` 只看 `position_m` 是否存在，**不看 `status`**，
   外推幀會靜默流進場景包（`filter_and_enrich_output.py` 也只讀 `sat_coords`、不看 `status`）。
2. **「輪子優先」還沒做**：`n_wheel_kp` 只是計數，`localize()` 的 Procrustes 仍把 24 個點
   平等丟進 SVD 擬合，並未加重輪子。這是本設計的核心新工作。

**一份要作廢的舊分析。** 先前 `openpifpaf-apollo24.md §5` 那份 taipei-cm 品質表
（track 3 飛走、track 53「乾淨 5.0°」、procrustes vs reprojection 對比）是在**修正前的舊版**
上跑的（輸出裡無 `n_wheel_kp`、從無 `extrapolated`），且用了**錯的驗收場地**（見下）。
數字不可再引用，需在新場地重跑。

**現行版重跑實證（taipei-cm 198 幀，僅供對照，非驗收）：**

| | 舊版 | 現行修正版 |
| --- | --- | --- |
| `status='ok'` | 820 | **241** |
| `status='extrapolated'` | （無此狀態） | **579** |
| `failed_insufficient_kp` | 163 | 163 |

已存在的展開度閘門把舊版當成「可用」的 820 筆裡 **71%（579 筆）重新判為外推**——這正是舊分析
把 track 2/3 當可用的錯誤所在。另外，820 筆定位裡只有 **276 筆（34%）有 `n_wheel_kp ≥ 2`**
（分布 0→417、1→127、2→276），這是「輪子優先」實際能適用的比例，其餘三分之二必須走回退
——所以 Phase 2 的回退策略不是邊角料，是主要路徑之一。

---

## 三、四個技術細節

### 3.1 輪子優先（核心，Phase 2）

**機制**：在 `localize()` 的固定尺度 Procrustes 擬合裡，給輪關鍵點（`WHEEL_KP_IDX`）更高權重，
或提供「只用輪子」的模式。輪子 h=0 免視差、高度實測，是誤差公式裡唯一乾淨的輸入。

**設計要點**：
- 加權 SVD：`Hc = (Q−q̄)ᵀ · W · (P−p̄)`，W 對角線輪子項放大。權重比例是要調的超參數。
- 退化保護：輪子常被遮擋。當 `n_wheel_kp < 2` 時必須有回退策略（退回全點擬合，但把
  `confidence` 調低、或標記來源），不能無聲失敗。決策文件實測 `n_wheel_kp ≥ 2` 時 heading
  中位誤差 2.42°、0–1 個時約 98°——這條界線同時是回退門檻的依據。
- 不要動模板的 x 欄符號：`localize_reprojection()` 也讀模板（`_LR_PAIRS`/offset_axis），
  且模板 docstring 對外承諾「+x = 車左」（這正是手性修正選擇在 `localize()` 內鏡射、
  而非改模板的原因，`haware_localization.py:347-350`）。

**風險**：加重輪子會減少有效點數、放大 PifPaf 輪點偵測噪音；必須用 Phase 0 的尺確認
「更乾淨的點」勝過「更多的點」，不能想當然。

### 3.2 近地平線剔除（Phase 1）

**機制**：定位**前**用幾何條件擋掉 homography 已在外推的車。兩個候選判據：
- CCTV y 座標門檻（畫面頂端一定比例）——最簡單。
- `homography.fov_polygon` 或 homography 分母的數值大小——較準，直接反映放大倍率。

**與展開度閘門的關係**：展開度閘門是**症狀偵測**（算完才知道爆了），近地平線剔除是
**源頭前置**（算之前就擋）。兩者互補：前置省算力、閘門兜底。

### 3.3 展開度閘門接下游（Phase 1）

**機制**：`build_scene.py` 與 `filter_and_enrich_output.py` 讀取 `status`，把
`status='extrapolated'` 的 object 當成無效點（等同缺 `position_m`）跳過，並在輸出摘要裡
計數，不要靜默丟棄。門檻 `max_spread_m` 目前寫死 8.0，應在新場地重新校。

### 3.4 多幀時序融合（Phase 3，最後）

**機制**：用 `tracked_id` 把同一台車的多幀綁起來，用時序連續性修單幀爛座標（車不會瞬移）。
概念接近 Kalman，但 CLAUDE.md 記錄 Kalman 那套被凍結（隊友主導）——這裡做的是**離線後處理**
版本，操作在 replay JSON 上，不碰 inference pipeline。

**風險與順序**：這是最複雜、最容易引入新假象（過度平滑會抹掉真實轉向）的一步，**只有在
Phase 1–2 還沒把品質推到目標時才做**。前面幾步把爛幀擋掉、把單幀做準之後，時序融合要修的
殘量會小很多。

---

## 四、驗證階梯（由便宜到決定性）

| 基準 | 量什麼 | 成本 | 陷阱 |
| --- | --- | --- | --- |
| 內部一致性（Procrustes 殘差／展開度） | 精密度 | 免費 | 自信地算錯也會低殘差，**不能**證明更準 |
| 行進方向一致性 | heading 準確度 | 免費 | 對**位置**有循環論證（course 由同一擬合推得） |
| 輪點量軌距（h=0） | 位置準確度（免視差） | 低 | 兼作場地體檢（見下） |
| 輪子人工標註 | 真實位置 ground truth | 高 | 唯一能一槌定音，少量幀做一次 |

前三個是代理指標，只有第四個能回答「變**對**了多少」。CLAUDE.md 說「位置準度從未被量過」
指的就是缺第四個——這也是本設計把手動標註列為 Phase 0 一部分的原因。

**驗收場地：用 kee-cc / taoyuan-tc，不要用 taipei-cm。** 決策文件實測：用 h=0 輪對量觀測軸距，
模板 2.546 m，taipei-cm 中位數 **5.92 m**、落在合理區間 2.0–3.2 m 的只有 **12.5%**；
kee-cc 是 53.2%（中位 3.18 m）。taipei-cm 有獨立於手性 bug 的 homography 度量缺陷，
加上 z_cam=3.596 m 是全 repo 8 地點最低、幾何懲罰最重（1/k 1.85× vs kee-cc 1.29×）。

---

## 五、執行階段

### Phase 0 — 先建量尺（不可跳過，使能後三個 phase）

- 把前三個基準寫成可重跑腳本（擴充 `scripts/viz_haware_replay.py`：已有展開度／heading 抖動，
  補「輪點量軌距」與「行進方向 vs 定位 heading」對照）。
- 驗收場地切到 kee-cc / taoyuan-tc；在 kee-cc/taoyuan-tc 上先跑一次現行版本當 baseline。
- 手標少量幀（幾台車、幾個時刻）在衛星圖上的真實位置，當 gold reference。

### Phase 1 — 便宜的過濾（零演算法風險，立即品質）

- 展開度閘門接進 `build_scene.py` / `filter_and_enrich_output.py`（讀 `status`）。
- 加近地平線前置剔除。
- 在新場地重校 `max_spread_m` 門檻。

### Phase 2 — 輪子優先（核心，本次目的）

- `localize()` 加權／限輪模式 + `n_wheel_kp < 2` 回退。
- 用 Phase 0 的尺量：軌距誤差、行進方向誤差、（有 gold 的幀）真實位置誤差，
  對比現行全點擬合，確認「更乾淨」勝過「更多」。

### Phase 3 — 多幀時序融合（最後，視情況才做）

- 離線後處理版，操作 replay JSON，不碰 inference pipeline。

---

## 六、未解與相依

- **位置 ground truth 仍需人力**：兩站點都沒有真實位置標註，Phase 0 的手標是唯一來源。
  唯一免標的準參考是 h=0 輪關鍵點（模板裡唯一實測而非估計的高度）。
- **PifPaf 前後標籤顛倒**：決策文件記載部分 track（無輪關鍵點者）heading 前後顛倒，
  純幾何閘門擋不掉；輪子優先能改善有輪點的 track，但無輪點的仍需 PifPaf 層或運動方向佐證。
- **`yilan-cv` 缺 `G_projection`**：四個交接場景包裡它無校正檔，不能進驗收，需向隊友索取。
- **z_cam 系統性高估 15–22%**（決策文件第四節）：影響所有 h>0 keypoint 的視差修正，
  是「輪子優先」之外另一條可能的準度來源，但不在本次範圍，先記著。
