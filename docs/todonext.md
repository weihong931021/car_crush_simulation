# 下一步

## 目錄重整（2026-08-20 完成）

> spec：`docs/specs/2026-08-20-repo-restructure-design.md`
> plan：`docs/plans/2026-08-20-repo-restructure.md`
> 回復點：`git tag reorg-preflight-20260820`

- [x] 兩階段完成：08-20 `satellite_pipeline`→`workbench`、`threejs`→`player`；
      08-21 前後端拆分 `workbench`→`backend/`+`frontend/onboarding/`、`player`→`frontend/player/`
      （scene-loader 因此改走 `../../scenes/`，部署約束＝**frontend/ 與 scenes/ 必須同層**）
- [x] `trafficlab-project/` 留原地不改名 + 新增 `OWNERSHIP.md`——那棵樹有 64 檔 25,354 行是我們的
      （改名成 `trafficlab/` 會與其內同名 Python 套件衝突，實測 `import trafficlab.motion` 會爆）
- [x] `detection_tests/` → `trafficlab-project/`、`open-player.command` → `tools/`、
      `.kiro/specs/` → `docs/legacy-specs/`、`environment.yml` → `environments/trafficlab-pifpaf.yml`
- [x] 刪頂層 `location/`（與 trafficlab-project 逐位元相同）與 `pifpaf/` 的 3 支過時副本
- [x] `archive/` 退出 git 保留磁碟（入庫量 −26 MB）
- [x] 驗證五件套逐項與重整前基準線相同：86 pass/0 fail/3 todo、46、111、271、4 場景全過

**仍未做**：`trafficlab-project/` 的瘦身（`media/` 23 MB、未用的 location 地點）、
改成 git subtree（要先確認隊友 repo 的 URL 與 canonical ref，目前 `git remote -v` 沒有記錄）。

## 碰撞模擬重構（2026-07-21 完成）

> spec：`docs/specs/2026-07-20-collision-simulation-design.md`
> plan：`docs/plans/2026-07-20-collision-simulation.md`

- [x] 車輛真實尺寸 + GLB scale-to-length（精確投影量測，誤差 0%）
- [x] `lib/path.js` 弧長參數化與速度剖面
- [x] `lib/obb.js` SAT 碰撞偵測與最短距離
- [x] `lib/physics.js` 真實接觸點、完整力臂、切向摩擦、接觸點速度 closing guard
- [x] `lib/simulate.js` 前向模擬 + 迭代接觸解算
- [x] `lib/solve.js` 安全速度區間（交會事故是 false→true→false 安全窗，無單一門檻）
- [x] `main.js` 接線：結論面板、求安全車速、間距標註、呈現至碰撞瞬間（會議決定）
- [x] 模型前方軸向 Blender 實測修正（car 偏 11°、moto 偏 234°）
- [x] 單頁打包 demo：**完整 three.js 3D 版**（~6.4MB 單一 HTML，three 內聯無 importmap、
      GLB meshopt 壓縮 base64 內嵌、atob 解碼避開 CSP），發佈於
      <https://claude.ai/code/artifact/1fec3a43-8ccf-4bbb-bcaa-55ac1e9f044f>
      （候選收尾工作：把組頁流程固化成 `tools/build_demo_page.py`，
      目前 assembler 在 session scratchpad）

### 續作（2026-07-21〜24，呈現品質與資料淨化）

- [x] 軌跡淨化管線定案：平滑 → 切凍結尾 → RDP 直線化（ε=6cm）→ 轉角細分（≤12°）→
      投影（幾何/時序分離，速度剖面＝證據不粗化）→ 縱向慣性 → 外插；
      test1 結果＝每台 2 段直線＋單一 ~7° 微角，impact 8.33s（對照組不動幾何 8.42s、
      人工標記 ~8.5s；舊抽稀+樣條管線 7.90s 反而漂移）
      ↑ 2026-07-24 修 `projectToPath` 同線段倒退後由 8.39s 變 8.33s（見下方審查修復）
- [x] `simulate` 車輛出現時間 `startT`（機車 6.3s 進場，修「提早出發停著等撞」）
- [x] 運動學約束：轉向率上限 min(0.6v+0.15, a_lat/v)（消「飄」）、
      縱向加減速上限 a≤3.0/b≤7.5 m/s²（壓假加速尖峰）
- [x] 跟車鏡頭：可切換目標（再按循環下一台）、距離隨車身尺寸縮放
- [x] 渲染定調：明亮＋單一主光源＋4096 影子（ACES/IBL 試過否決，revert d917786）
- [x] 模型清理：MotoCollider 是模型父節點（不可砍子樹）；demo 資產拔 mesh 引用、
      播放器走 registry.json per-model `hide` 清單（碰撞盒＋地面圓片）
- [x] `simulate` bisect 潛在 crash 修復（受限 heading 離散化不一致 → bisectImpactSafe 回退）
- 遺留：`solve.js` 兩處防禦性死碼（reviewer 確認不可達，留有註解）；碰後彈開播放
  已實作但依會議決定關閉

## 主線：場景包驅動的 Three.js Demo（2026-07-20 起）

> 設計文件：`docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md`
> 方向：偵測交隊友，我們做組件整合——軌跡 JSON + 衛星圖 → 場景包 → 可分享的網頁 demo

- [x] `scenes/test1/` 場景包（scene.json schema 定案，data/、images/ 遷入）
- [x] `tools/build_scene.py` 半自動場景包產生器
- [x] Three.js 播放器：讀場景包、移除硬綁常數與 fallback waypoints
- [x] 動畫真實度：碰後旋轉（角動量）、碰撞瞬間視覺回饋
- [x] 視覺品質：光影、genai HD 地面、相機 preset（頂視／45°／跟車）
- [x] 互動 UI：播放速度 0.25x–2x、視角切換
- [x] three.js 本地 vendor（離線可用）、手機 RWD
- [x] MODEL_FLIP per-model 設定（確認 car.glb / moto.glb 前方軸向 → registry.json）
- [ ] 靜態部署（GitHub Pages）（待 repo 管理者於 Settings → Pages 啟用）
- [x] 第二場景驗證（backend 既有地點 + 合成軌跡，`tools/synth_trajectory.py` +
  `scenes/tainan_yongkang/`，換場景零程式碼修改驗證通過）
- [x] **全面轉 Three.js 網頁渲染，Blender 工具鏈移除**（2026-08-05）：渲染／出版級畫面
  都由 Three.js 負責，原「第二階段 Blender 出版渲染」取消（見本檔末與決策記錄）

### 全鏈驗證與缺口測試（2026-07-24）

6 個 agent 平行審讀衛星管線／build_scene／播放器／文件＋實跑重現性，結論：**合成軌跡走完
全鏈可位元組級重現**（用 committed 參數重建 tainan_yongkang，ground.png 與 trajectory.json
sha256 相同，scene.json 僅 `0.70` vs `0.7` 的浮點格式差異）。

- [x] 冒煙驗證固化進 repo：`tools/verify_scenes.mjs`（自動掃 `scenes/*/`、自起自收
      http server、headless 驗零 console error／零外部請求／collider 恰 2 台無 NaN／
      無錯誤 overlay）。**加新場景包必跑**——這是唯一會實際渲染的驗證
- [x] 缺口測試（`todo` / `expectedFailure` ＝已知缺口的執行式文件，非壞測試）：
      `tools/tests/test_build_scene_edges.py`（新增 8 測，套件期望 OK + expected failures=5）、
      `frontend/player/lib/tests/contract-gaps.test.js`（新增 4 測，其中 3 個 todo；套件期望 fail 0）

### 播放器全功能實測與修正（2026-08-17）

Playwright 逐一操作三個場景的每個按鈕／拉桿／鏡頭／手機版（冒煙全綠但實際操作抓到一批），
Codex review 後修正並回歸（JS 86/86、verify_scenes 全過）：

- [x] **12 s 模擬視野假象**：`simulate` 改跑到兩車走完路徑（保險上限 180 s，回傳
      `endTime`／`horizonReached`）；`solve` 把 horizonReached 當「未證明安全」，
      test1 汽車 ×0.5 由假的「未碰撞」變成正確的「碰撞於 15.50 s」、安全車速 ×≤0.65 → ×≤0.30
- [x] 求安全車速：結果隨滑桿過期、改相對目前滑桿而非 ×1、按下先顯示「計算中」
- [x] 鏡頭 preset 依兩車軌跡包圍盒取景（`actionBounds`）；頂視圖依視窗比例 fit、
      不再改 `camera.up`（OrbitControls 建構時抓死，改了在極點左鍵拖曳無反應）
- [x] 播到底再播從頭；改車速後幀數超出回開頭；未碰撞播到錯車後 4 s 為止
- [x] 對外 demo 定調：秒數取代幀號、同 label 車 A/B、藏 km/h／class／id（`?debug=1` 顯示）、
      路徑改 30 cm 貼地色帶、開場切到第二台車進場前 2 s（test1 從 4.30 s 起播）
- [x] test1 底圖：試過 `image_enhance` 去車高清版**更糟**（Gemini 只抓 2 台、留污漬），
      已還原；committed 的 `scenes/test1/ground.png` 就是增強版，**勿重產**（CLAUDE.md 有記）
- [ ] 台北民生 `scenes/taipei-cm/`：資料不撞（80 s 內最近 7.2 m）、底圖糊、track 1 壞
      ——待決定拿掉或用 kee-cc／taoyuan-tc 重出
- [ ] 視窗 resize 後不重新 fit 鏡頭；背景車（extras）用 GLB 原始比例（Codex 提的兩個小風險）

**底圖工作台（`backend/webapp.py`，①②）實測到的 bug（使用者決定先修播放器，
這些待處理；③ 標註另開 spec）**：對已鎖定代號再擷取會靜默覆蓋（locked 消失、clean 圖被刪）、
重新整理全丟沒有「打開既有代號」、鎖 30 m 滑桿顯示 29 m 與上限提示永不出現（floor 取整）、
降 zoom 重抓後滑桿仍停 40 m、去車隨機（同圖 9 台→1 台）且銳化放大 Google 浮水印、favicon 404。

### 對外簡報圖（2026-08-17）

`docs/diagrams/`：三張 16:9 SVG＋預覽頁 `index.html`＋產生器 `make_diagrams.py`（改字或座標後
重跑即同步三張），生圖 prompt 在 `image-gen-prompts.md`。artifact：
<https://claude.ai/code/artifact/54df9b6f-0938-4881-b820-34928efc8cd8>

- 圖 A `architecture-overview.svg`「兩種資料，合成一個 3D 現場」（概念、非技術觀眾）
- 圖 B `user-flow-overview.svg`「三次人工，其餘自動」（六步流程、人工三處）
- 圖 C `system-architecture-flow.svg` 元件級技術架構（RAG 教學圖語法：圖示＋編號流程
  ①→⑪、淺藍核心區、外部服務盒、資料源在底部）
- 視覺語彙三張共用：交通號誌三色（藍＝系統／主流程、琥珀＝人工／準備、綠＝產出），
  說明文字帶白色光暈、圓形站號徽章、連線只走水平／垂直

## 路徑產生器 haware（2026-07-28 接管）

> 決策與完整證據：`docs/decisions/2026-07-27-haware-localizer-parity-bug.md`
> 行為指令摘要見 CLAUDE.md「路徑產生器 haware」節

`trafficlab-project/trafficlab/motion/haware_localization.py` 的 `localize()` 就是產出
路徑的 module，它同時吐 `sat_coords`（→ position_m → 我們的場景包）與 `heading`
（播放器不讀，自己從線段算）。**評估任何改動先看它打在哪一半。**

### 已完成

- [x] **座標系手性 bug 修正**（`localize()` 內鏡射 `Q` 的 x 欄，不動模板）。
      誤差是解析可預測的 `2 × angle(點集主軸, 車體 z 軸)`——橫向點集恰錯 180°，
      這就是「輪子看起來唯一可靠」的成因。實測 track 53 heading 94.73° → **3.10°**、
      位置變動 **1.52m 中位數**
- [x] 回歸測試 `trafficlab-project/tests/test_haware_localization.py`（14 測）：
      映射行列式自我檢定、7 個朝向往返、4 種鑑別力子集、rank-1 掃整圈防跳變
- [x] 展開度閘門 `spread_m` > 8m → `status='extrapolated'`（座標保留供診斷）
- [x] `n_wheel_kp` 與 `spread_m` 寫進 replay JSON——下游只讀 `sat_coords` 不看 `status`，
      不輸出判據的話外推幀會靜默流進場景包
- [x] `pifpaf/` 暫存副本同步

### 位置那半（直接影響碰撞結論，優先）

- [ ] **量位置準度**（最大空白）：兩站點都沒有位置 ground truth，先前全部只是內部一致性
      指標。唯一可得的準參考是 **h=0 的輪關鍵點**（模板裡唯一實測而非估計的高度）。
      沒有這個，我們只知道手性修正「改變」了 1.52m，不知道「改對」多少
- [x] ✅ **2026-07-28 品質判據已接進 `build_scene.py`**：`kp_quality()` 直接從 `kp_sat`
      自算 `spread_m`／`n_wheel_kp`（物件自帶欄位優先），所以**既有 trajectory.json 不必
      重跑 pifpaf**。`--list` 顯示展開度／輪點／可用率並對不合門檻者掛 ⚠；挑到品質不足的
      track 當 collider 會發 `UserWarning`。
      實證：taipei-cm track 53 可用率 83%、track 1 掛 ⚠ —— 與獨立量測的 heading 誤差
      3.10° vs 90.23° 一致，**不需 ground truth 就挑得出好 track**
- [x] ✅ **2026-07-28 地面圖增強可安全套用在校正參考圖上**：
      `image_enhance.enhance_file(src, dst, upscale)` 保證輸出是輸入的**精確整數倍等比放大**
      （去車＝局部 inpaint、放大＝整數倍 LANCZOS、銳化不動幾何），函式內有最後一道 assert。
      `build_scene --location-dir` 自動優先採用 `sat_<code>_hd.png` 並把 px_per_meter
      乘上縮放比，長寬比不符時警告並退回原圖。
      實測 taipei-cm：1190×1258 → 2380×2516、去車 8 台、ppm 27.85 → 55.71，
      **`size_m` 維持 42.72×45.16 不變**（座標未被破壞）。
      ⚠ `--genai` 不可用於此路徑（重畫整張會改寫路面內容），CLI 已擋下
- [x] ✅ **2026-08-17 生圖那半改成雙供應商，並把幾何漂移量化**：
      `--genai-provider {gemini,openai}`，**預設 `gemini`**。同一張 sat_raw 實測位移中位數
      `sat_clean` 0.00 m ／ `gemini-3.1-flash-image` 0.20 m ／ `gpt-image-2` 0.30 m，
      Gemini 兩次獨立跑一致。原本「HD 底圖只能人眼確認」現在有可重跑的數字
      （`backend/measure_genai_drift.py`）。
      診斷過「是不是只是取景跑掉」：扣掉最佳全域仿射只降 16%，是內容被改寫、不可校正。
      prompt／`mask`／`input_fidelity` 三條路都查證無效（官方文件明載 mask 也是整張重生）。
      決策文件：`docs/decisions/2026-08-17-satellite-genai-provider-choice.md`
      ⚠ 換供應商**沒有讓 `--genai` 變安全**，只是量清楚了不安全的程度；座標關鍵路徑照舊禁用
- [ ] **`path.js` 淨化參數的泛化性**：RDP ε=0.06、a≤3.0/b≤7.5 全在 test1 一份資料上調過，
      真實新影片的噪音特性、取樣率、碰前凍結窗都不同
- [ ] per-site `η = h/z_cam` 校準（h 與 z_cam 無法分離，只能校 η；兩站點都顯示 z_cam
      被高估 15–22%）

### heading 那半（只對隊友 replay/GUI 有用；播放器自算 heading 不讀這半）

- [ ] **前後標籤顛倒**：tracks 1/501/502 帶著 90–161° 壞 heading 通過展開度閘門，
      共同點是**沒有輪關鍵點**。陷阱：**若整台車一致地顛倒，任何內部一致性檢查都抓不到**
      （整組都翻了，自己跟自己一致），必須引入外部證據（運動方向）；但 course 由同一個
      擬合的位置推得，有循環論證風險，要先驗證獨立性
- [ ] `localize_reprojection()` 的同型問題：`_rotation_from_vectors()` docstring 明寫
      "Proper 2D rotation"，同樣排除反射，且逐對算 heading 會互相矛盾（程式碼推論，未實測）

### 驗收場地

**不要用 taipei-cm**：z_cam=3.596m 在 8 個地點中第二低（僅次於 test4 的 3.418m），
但**是有真實影片的地點裡最低**的（1/k 懲罰 1.85× vs kee-cc 1.29×），
且有獨立的 homography 度量缺陷（h=0 輪對量觀測軸距，模板 2.546m 但實測中位 5.92m、
合理率僅 12.5%；kee-cc 53.2%）。改用 kee-cc / taoyuan-tc。

---

補實作待辦（測試已寫好，補完即轉綠；Python 端會以 unexpected success 示警）：

- [x] ✅ **2026-07-28** `build_scene.py` 帶入 `trajectory.meta.fps`（`resolve_fps()`，
      含 0／負／NaN／∞／型別錯的驗證與回退警告）。實測 taipei-cm 場景包寫出 fps=23
- [x] ✅ **2026-07-28** 壞格式軌跡改報乾淨 `SceneBuildError`（`scan_tracks()`）：
      缺 frames/frame_index/objects 一律指名，缺 `position_m` 的計數併進
      「collider 不存在」訊息不再誤導
- [x] ✅ **2026-07-28** 車種大小寫正規化：`build_scene.normalize_class()` +
      `scene-loader.js` 的 `lookupClass()`（修掉背景車全變灰方塊）
- [x] ✅ **2026-07-28** `--location-dir` 座標對位自動化（原本要人工算三個數字）
- [x] ✅ **2026-07-28** 第一個真實影片場景包 `scenes/taipei-cm/`（headless 渲染通過）。
      註：兩台車最近只到 19.43m，**不是事故場景**，它的定位是管線驗證
- [ ] `lib` 入口驗證補完（失敗方式不是 NaN 傳染，是**靜默給出錯誤結論**）：
      `trajectory.meta.fps` 已有驗證並會 warn 回退，但**回退目標 `cfg.frames.fps` 沒人驗**
      （scene-loader 也不驗）——fps=0 → NaN/Infinity 時間軸、fps<0 → 時間軸倒流、
      fps=∞ → t 全 0；下游 `speedProfile` 被 guard 夾成 0.01 m/s、`startT=NaN` 使
      simulate **回報「沒有碰撞」**。另 `origin_offset_m` 缺失／null 是 raw TypeError、
      含 NaN 或空陣列則靜默 NaN 座標；`mass_kg` 缺失或 0 不 throw 不 warn，
      碰後兩車速度 NaN、各自凍在撞擊瞬間位姿到 maxTime
- [ ] 清理假可配置欄位：scene-loader 只驗**頂層** `collision` 物件存在，
      `restitution/friction` 子欄位完全不驗（`"collision": {}` 照樣通過），且全 repo 無人讀
      `cfg.collision`——`simulate.js:16-17` 寫死 `RESTITUTION=0.15`／`MU=0.7`，而碰撞當下的
      切向摩擦是 `physics.js:118` 另一個寫死的 `muContact=0.5`（simulate 也沒傳）。
      `frames.anim_*` 同樣被驗證但播放器不讀（`animStart` 是 main.js 寫死的 1）——
      擇一：接上實作、或標註為死欄位

### 程式碼審查修復（2026-07-24 第二輪）

審查提出 8 項，逐條實測驗證後 6 項成立、2 項降級（見決策記錄）。已修：

- [x] **模型 hide 誤殺真零件**：`wrapModel` 用裸 `startsWith()` 比對 registry 的 hide 清單，
      `"Object_4"` 連 `Object_41/43/44/46/48`（車身、油箱、輪胎，533–3002 頂點）一起隱藏
      → 機車缺件。改為**精確名稱**比對（`scene-loader.shouldHideNode`），registry 改列
      父節點 `floor_0`（隱藏子樹）。新增 `tests/scene-loader.test.js` 直接解析 moto.glb
      比對，打錯字的 hide 項目也會被抓出來
- [x] **`projectToPath` 同線段倒退**：舊版只擋段索引下降，同一段內投影比例 `u` 仍可變小；
      test1 track 7 實測 **29 次倒退、4.1cm 假里程**被 buildPath 當成真的走過（＝假速度）。
      改為約束 `(段索引, u)` 這一對。**impact 8.39s → 8.33s**
- [x] **`refineAnchors` 一個尖角就中止全部**：舊版每輪只處理全域最大角，該角若不可細分就
      `break` 整個迴圈，其他仍超標的彎道全被放生。改為封鎖不可細分的角並繼續；
      `maxIter` 只計成功插入（封鎖不吃額度）；兩側鄰段都試
- [x] **衛星 pipeline 代號未驗證**：`code` 會變成 `output/<code>` 路徑，`../` 可寫到 output
      外。新增 `backend/common.py` 的 `validate_code`（`^[A-Za-z0-9_-]+$`，
      各進入點都擋）。（當時 `blender_ground` 產生 Blender 原始碼的注入面也一併封了，
      該檔已於 2026-08-05 隨 Blender 移除刪除）
- [x] ~~`import_vehicle.py` 選錯匯入物件~~：當時改為根物件差集具名鎖定；該檔已於
      2026-08-05 隨 Blender 工具鏈移除刪除，此修正一併作廢
- [x] `docs/reference.md` 的 `conda activate trafficlab` 改為實際可用的 venv 路徑

當時降級為架構債務、**已於 2026-08-05 因移除 Blender 而解決**（決策記錄：
`docs/decisions/2026-07-24-blender-threejs-contract-split.md`）：

- 車規來源分裂（Three.js 4.69/1.85 vs Blender 3.8/1.7）→ **解決**：Blender 側
  `vehicle_specs.py` 已刪，尺寸真相只剩 `scene.json` 一份
- 座標契約分裂（blender_ground vs reference.md vs Three.js）→ **解決**：Blender 兩套
  座標約定的檔案都已刪，只剩 Three.js 的 `origin_offset_m` 置中約定
- 審查主張的「增強圖與 metadata 解析度不一致會讓 Blender 地板尺度錯」經實測**不成立**，
  且 Blender 地板已不存在——`build_scene` 用實際 PNG 寬度重算 `px_per_meter`，尺度正確

### 真實新影片：座標對位規則（2026-07-24 解開，原以為是斷鏈）

`position_m` 的座標系＝`trafficlab-project/location/<code>/sat_<code>.png` 這張 **G-projection
校正參考圖**的平面（原點＝圖左上角，尺度＝`trajectory.meta.px_per_meter`）。所以地面圖
必須是那張圖本身或其等比縮放：

```text
size_m          = [sat_w / meta.px_per_meter, sat_h / meta.px_per_meter]
origin_offset_m = size_m / 2                       （build_scene.py:93 自動）
ground.px_per_meter = meta.px_per_meter × 縮放比    （不縮放時就是 meta 值）
```

實證（兩份真實資料都吻合）：

- test1：`sat_test1.png` 1676×1148 @34.41px/m → 48.71×33.36m，與 `scene.json` 的
  `ground.size_m` **完全相同**；`ground.png` 1515×1038 是它 0.904 倍縮放（31.10＝34.41×0.904）
- taipei-cm：`sat_taipei-cm.png` 1190×1258 @27.85px/m → 42.72×45.16m，軌跡
  x 9.0–33.2／y 15.7–43.1 完全落在平面內

**陷阱**：`--sat-dir`（backend 新擷取的 Google 圖）是另一張不同取景的圖，
對真實軌跡會錯位；它只適用於在衛星座標系合成的軌跡（tainan_yongkang 即是）。
真實影片走 `--ground-image / --px-per-meter / --size-m` 手動路徑。

- [ ] 把上述配方自動化：`build_scene.py` 加 `--location-dir trafficlab-project/location/<code>`，
      自動讀 `sat_<code>.png` 尺寸 + `trajectory.meta.px_per_meter` 算出 size_m
      （現在要人工算三個數字，是最容易出錯的一步）
- [ ] `--sat-dir` 對真實軌跡加防呆：偵測到 `trajectory.meta.px_per_meter` 與衛星圖
      推算值不符時警告或拒絕（現在會靜默產出錯位的場景包）
- [x] **端到端驗一個真實新場景**（✅ 2026-08-20，tainan_yongkong 走網頁流程 ①→④
      全線跑通，`verify_scenes.mjs` 4 場景全過）。誠實結論：整合鏈運作正常，但真實
      資料模擬結果「未碰撞、最近 7.50 m」——撞車那台機車追蹤器沒抓穩（全部機車 track
      淨位移僅 0.2–0.7 m），屬偵測層品質（隊友凍結範圍）。詳見 web-onboarding spec
      「④ 首次真實資料端到端的結果」
- [x] **格式契約已用第二份真實樣本驗過**（2026-07-24，haware 管線的
      `trafficlab-project/output/haware/taipei-cm/taipei-cm_trajectory.json`）：
      `python3 tools/build_scene.py --trajectory <該檔> --list` **不改碼直接讀得出**
      （track 1 car [0–192]、track 53 car [162–197]），頂層結構與 test1 同構
      （mp4_path／meta／location_code／frames／selected_tracked_ids／selected_track_stats）
- [ ] **但車種 class 大小寫不符**（同次實測發現）：haware 輸出小寫 `car`，
      `CLASS_DEFAULTS`（build_scene.py:24）與 `registry.json` 的 `class_fallback` 全是
      大寫且精確比對。collider 可由 CLI 手打 `Car` 規避，**背景車（extras）直接吃
      `obj.class`** → 查表 miss → 全退灰方塊（只有 console.warn）。查表前正規化大小寫
- [ ] 其餘尚未驗的真實樣本：`location/` 下 kee-cc、taipei-cm、taoyuan-tc、yilan-cv
      四支影片已就位，只有 taipei-cm 有軌跡輸出；另三支產出後應各跑一次 `--list` 複驗
- [ ] **淨化管線參數的泛化性未驗**：RDP ε=0.06、加減速上限等全部只在 test1 一份資料上
      調過（impact 8.33s vs 人工 ~8.5s）。新影片噪音特性、取樣率（test1 是 49.98fps）、
      碰前凍結窗都不同，無第二份真實資料佐證
- [ ] **`source_collision` 容錯未做敏感度分析**：`waypoints.js` 硬性要求 collider 軌跡撐到
      碰撞幀附近（tolerance `max(span*0.1, 5)`），新影片若凍結/中斷更早會直接 throw
- [ ] 文件化模型 GLB 取得鏈：car.glb/moto.glb 已在 git 但來源、授權、新車種的
      flip 量測流程零文件
- [ ] `scenes/test1/road_features.json` 定位不明：不在 build_scene 產出清單、播放器與
      工具皆不讀——納入 schema 或移除

## Track A：衛星圖自動化 pipeline（→ `backend/` 模組，✅ 已完成）

> **2026-08-16 網頁化進場流程**：spec `docs/specs/2026-08-16-web-onboarding-flow-design.md`
> （① 輸入經緯度/影片/大小 → ② 底圖自動截圖＋去車、滑桿調大小、人工確認鎖定 →
> ③ 標註 → ④ Three.js）。底圖大小改由使用者輸入、太大可縮小不重截；② 鎖定的圖就是
> 校正參考圖，`--sat-dir` 只限合成軌跡的限制在此流程下消失。

### ①② 底圖網頁工作台（✅ 2026-08-16 完成，2026-08-17 實機驗證）

`backend/webapp.py` + `web/index.html`，`python3 backend/webapp.py`
→ <http://127.0.0.1:8765/>。stdlib http.server，零依賴，輸出與 CLI 共用 `output/<code>/`。

- [x] 探測可用 zoom（空白圖磚自動降級）＋抓整張 1280² 原圖
- [x] 滑桿選大小：≤ 涵蓋範圍純前端裁中央（零延遲），超過按「降 zoom 重抓」
      （實測 zoom 21 → 43.97 m @29.11px/m；zoom 20 → 87.93 m @14.56px/m）
- [x] 鎖定＝裁切 + 去車 + 2x 銳化，之後才人眼驗品質；`locked: true` 後不可再改大小
- [x] `decar_status` 讓去車降級不再靜默（前端紅／黃／綠橫幅）
- [x] 「再跑一次去車」——Gemini 偵測有隨機性（同圖三次 5／13／4 台）
- [x] 離線測試 `tests/test_webapp.py` 10 測（TDD 先紅後綠）；全套 26 測綠
- 順手修掉的兩個既有坑：`size_m: null` → 寫實際涵蓋公尺數（`pick_sat` 不再 TypeError）、
      `map_capture` 拆出 `finish_capture()` 讓裁切／meta 規則可離線測

**接 ③ 標註的底圖**（2026-08-20 改）：交付「使用者在 ① 當下看的那張」（variant 隨
`S.tab`），預設仍 sat_clean → sat_raw、不會自動挑 genai；明示選 genai 時出處寫進
sat_meta（`geometry: rewritten_by_genai`）。代價：genai 是重畫且**非確定性**（同來源
同 prompt 兩次 0.04 m／0.40 m），只要對應點標在交付的同一張圖上座標系自洽，誤差
表現為相對真實世界的整體偏差。見 web-onboarding spec 同名章節與 `measure_genai_drift.py`。

待補（不擋 ③ 開工）：網頁端寫死預設 provider（gemini）、CLI `pipeline.py` 一鍵仍不含 genai、
Gemini 呼叫無 timeout／重試、`--strict`（去車失敗非零退出）未做。

### 已完成（2025-06）

- **圖源鎖定**：Google Maps Static API `zoom=21 scale=2` = 29 px/m（此地點上限）
  - 全部來源實測過：Esri 台南無資料（舊 pipeline 用的，z19 僅 3.6px/m 糊 8 倍）、
    Bing/Earth KH/NLSC 皆不可用。換不同 Google API 不會更清楚（同一份底圖）
- **去車 + 增強定案**：Gemini 偵測 bbox + cv2 inpaint + PIL 銳化
  - 否決 Gemini 重畫整張（會幻想假道路/標線）
- **`backend/` 一鍵流程已完成並驗證**：
  `pipeline.py --lat --lon --code` → sat_raw → sat_clean(去車)；`sat_*.png` + `meta.json`
  供 `build_scene.py --sat-dir` 產場景包 ground.png
  - 台南永康點端到端通過（去 24 台車、25×25m @ 29px/m）
- 詳細決策見 `backend/README.md`
- 圖源比對：`backend/compare/source_compare.png`

### 待辦（微調）

- [x] genai prompt 定案：真實深柏油 + 粗糙質感 + 標線最小化 + 風格參考圖（refs/road_style_ref.png，借柏油材質）（temp 0.4, raw 來源）
- [x] 多地點範例：`backend/demo/` 5 個台灣路口原圖 vs HD 對比圖
- [x] Codex 審查 #1 修正：map_capture 重抓時清除過時 sat_clean/sat_genai（修「新地形配舊圖」bug）
- [ ] Codex 審查 #2（待軌跡接入時驗）：`uv.reset()` 沒明確指定哪個 UV 角=世界原點，image-y-down 映射是隱性的，衛星圖可能上下相反
- [x] Codex 審查 #3：px_per_meter 是「此緯度」專屬非通用常數（README 已註明「此地點 29px/m」）
- [x] Apple Maps 評估：網頁嵌入版 zoom 鎖死約 3.6px/m，不如 Google，維持現狀
- [ ] （選配）需更高解析度時，手動從 NLSC（maps.nlsc.gov.tw）截圖的標準流程
- [ ] `pipeline.py` 的「一鍵」只到 `sat_clean`，從不呼叫 `genai_enhance()`——但實務上
      場景包用的是 HD 的 `sat_genai`（demo 5 個地點也全都只有 raw + genai、沒有 clean）。
      主力產物不在一鍵流程內，應加 `--genai` 旗標或改預設
- [ ] `genai_enhance()` 不回寫 meta.json（`enhance()` 會記 enhanced_px）：Gemini 回傳的圖
      若長寬比與 raw 不同，下游若照 raw 的 img_w/img_h 算尺寸會被拉伸。（Three.js 端無此
      問題，`build_scene.py` 依實際 PNG 寬重算 px_per_meter）
- [ ] `meta.json` 的 `px_per_meter` 對下游是誤導值（描述 raw，enhanced 版像素密度不同），
      考慮改名或標註適用範圍
- [ ] `--genai` 的 help 寫「在**去車結果**上做 HD 化」，但 `genai_enhance()` 的
      `src_name` 預設是 `sat_raw.png`（image_enhance.py:108，且 fallback 也是 raw）——
      實際吃的是未去車的原圖。修 help 或改預設，兩者擇一
- 註：`models/FSRCNN_x4.pb` 無任何**程式碼**引用（backend 五支 .py 全數零命中），
  且被根 `.gitignore` 的 `*.pb` 忽略、git 未追蹤——死資產。但根 `README.md` 與 docs/specs
  仍有文字提及，清理時一併移除
- 註：舊版 `trafficlab-project/scripts/{map_capture,image_enhance,pipeline_mapground}.py`
  （Esri 版）已被 `backend/` 取代

## Track B：TrafficLab 偵測優化（❄️ 凍結，隊友主導）

- [x] VisDrone 訓練完成（Colab 50 epochs，mAP50=0.400）→ 模型已放 `trafficlab-project/models/yolo11l-visdrone-ft.pt`
- [x] 測試 VisDrone 對機車偵測效果：二輪 ×21、汽車信心 +0.03，驗收見 `trafficlab-project/detection_tests/`
- 以下轉隊友，不在本 repo 追蹤：Kalman filter、輪胎辨識、Motorcycle 濾波器啟用、
  inference_config.yaml weights 更新（現指向不存在的舊檔，跑推論前需改指新模型）

## Track C：Blender ~~碰撞動畫／出版渲染~~（❌ 2026-08-05 取消）

全面轉 Three.js 網頁渲染，Blender 工具鏈已移除（見本檔頂端主線項與決策記錄）。
出版級畫面改由 Three.js 負責。以下原 Blender 待辦作廢；仍有效的驗證項移到主線：

- [ ] 測試斜角碰撞（T-bone、追尾偏轉）：用自然語言描述碰撞角度，驗證 `physics.js` 力分量
      計算是否正確（此項與渲染引擎無關，留著）

## 之後

- [ ] 主動煞車（AEB）模擬＋煞車參數自動求解（最晚煞車點／時機×力度 2D 掃描），
      設計見 `docs/specs/2026-07-20-collision-simulation-design.md`「未來擴充：主動煞車」節
- [ ] （實驗性）Asset Harvester 3D 資產生成：保留 YOLO／tracker，依 `tracked_id`
      挑選 1、2、4 張最佳車輛裁圖，在雲端 GPU 生成 `.ply`，評估幾何品質、成本、
      快取策略與 Three.js Gaussian Splat loader；技術評估見 `docs/PROJECT.md`
- [ ] 紅綠燈拆成獨立流程：detector 定位燈體／燈桿、classifier 判斷紅黃綠狀態，
      固定式 3D 燈桿資產只生成或建模一次
- [ ] 多車、行人、障礙物複雜場景測試

## 已知坑（勿忘）

- 換車輛模型：放新 GLB 到 `frontend/player/models/`、`registry.json` 補 file/flip/hide；flip 在
  瀏覽器量前後輪中心連線 `atan2(dx,-dy)` 取負，量法見 `registry.json` `_comment`
- 斜角碰撞後有旋轉：角動量 = F × 力臂，轉動慣量 ≈ 1/12 × m × L²（在 `physics.js`）
