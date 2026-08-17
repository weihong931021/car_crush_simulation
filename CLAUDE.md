# Claude 行為指令

專案文件見 [README.md](README.md)；座標、車規、指令見 [docs/reference.md](docs/reference.md)。

---

## 當前工作方向（2026-07-20 起）

**組件整合優先，Three.js 是最終呈現。** 偵測／軌跡品質由隊友主導，不做 inference 優化。
完整設計見 `docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md`。

1. **場景包**：每個事故場景一個 `scenes/<code>/`（scene.json + ground.png + trajectory.json），
   `main.js` 的硬綁常數（OFFSET、track ID、圖路徑）全數遷入
2. **`tools/build_scene.py`**：軌跡 JSON + satellite_pipeline 輸出 → 半自動產生場景包
3. **Three.js 播放器**：物理留在 JS（保住互動調車速）、加碰後旋轉、光影、相機 preset、
   播放速度、本地 vendor + 靜態部署——**這就是最終呈現，渲染全在網頁**

> **2026-08-05：全面轉 Three.js 網頁渲染，Blender 工具鏈已移除。** 車輛 GLB 是 committed
> 資產（`threejs/models/`），執行期只靠 `GLTFLoader` + `registry.json`，不需要 Blender。
> 原「第二階段 Blender 出版渲染」已從 roadmap 移除；出版級畫面也由 Three.js 負責。

### 碰撞物理（已模組化在 `threejs/lib/`，不要重新推導）

spec：`docs/specs/2026-07-20-collision-simulation-design.md`。前向模擬 + OBB SAT 偵測 +
衝量（含切向摩擦、真實接觸點、完整力臂 `(r×J)_y = r_z·J_x − r_x·J_z`、`I=mL²/12`）。

- `path.js` 弧長參數化／速度剖面／軌跡淨化、`obb.js` SAT、`simulate.js` 迭代接觸解算、
  `solve.js` 安全速度區間（交會事故無單一門檻，回傳 slowerK/fasterK 區間）
- 座標約定：`heading = atan2(dx, dz)`、前向 `(sin h, cos h)`、rotation.y 右手系
- 測試：`node --test threejs/lib/tests/*.test.js`（目錄形式會失敗，必用 glob）

### 驗證五件套（改完務必全跑）

```bash
node --test threejs/lib/tests/*.test.js                     # 期望 fail 0（todo 3 是已知缺口）
python3 -m unittest discover -s tools/tests                  # 期望 OK（23 測，已無 expected failure）
python3 -m unittest discover -s satellite_pipeline/tests     # 代號驗證 + 產生程式碼跳脫
(cd trafficlab-project && .venv-pifpaf/bin/python -m unittest discover -s tests)  # haware 手性回歸
node tools/verify_scenes.mjs                                 # 全場景 headless 冒煙，期望全過
```

haware 那套**必須用 `.venv-pifpaf`**（需要 numpy；系統 python3 沒有）。

`tools/verify_scenes.mjs` 自動掃 `scenes/*/`、自起自收 http server，逐場景驗零 console
error／零外部請求（three.js 必須全走本地 vendor）／collider 恰 2 台無 NaN／無錯誤 overlay。
**加新場景包後跑這支**，這是唯一會實際渲染的驗證，單元測試抓不到視覺與載入問題。

`todo` 與 `expectedFailure` 標記＝**已知缺口的執行式文件**（見下方「已知缺口」），
不是壞掉的測試；缺口補實作後 Python 端會以 unexpected success 示警，JS 端拔掉 `{ todo }`
即轉正式回歸測試。這套機制 2026-07-28 實際運作過一次：`tools/tests` 的 5 個
expectedFailure 在補完實作後全部以 unexpected success 現形，才轉成正式回歸測試。

**軌跡淨化管線（順序固定，播放器與單頁 demo 共用）**：
`smoothPoints(anchorEnd:false)` → `trimFrozenTail` → `rdpSimplify(ε=0.06m)` →
`refineAnchors(頂點角≤12°)` → `projectToPath` → `limitAcceleration` → `extendPoints`。
核心原則＝**幾何/時序分離**：RDP 折線只定直線化中心線（呈現要求：兩點連線、線段間僅
些微角度），每個樣本點投影上去、自己的 t 保留——速度剖面是證據，粗化它會改變碰撞結論
（教訓：純 RDP 讓 minGap 0.66→1.48m；ε=0.15 會吃掉真彎）。對照組驗證：投影版 impact
8.33s ≈ 不動幾何 8.42s，且比舊抽稀+樣條管線（7.90s）更貼近人工標記 ~8.5s。
（8.39→8.33 是 2026-07-24 修掉 `projectToPath` 同線段倒退的結果：test1 track 7 原有
29 次倒退、4.1cm 假里程被 buildPath 當成真的走過。倒退＝憑空多出的里程與速度。）

**運動學約束（simulate 內）**：
- `startT` 出現時間：晚出現的車不得提早出發（漏掉會提早 6.3s 到路口「停著等撞」）
- 轉向率上限 `min(0.6v+0.15, a_lat/v)`：蠕行不原地擺頭（消「飄」）、高速不無視抓地力
- 縱向 `limitAcceleration`（a≤3.0/b≤7.5 m/s²）：壓掉偵測噪音的假加速尖峰

**產品決定（2026-07 內部會議）**：demo 呈現到碰撞瞬間為止，碰後彈開不播
（`main.js` 以 impactTime 截斷；物理照算，要恢復播放拿掉 cutT 即可）。
未碰撞時播到錯車後 4 s 為止（模擬本身跑到兩車走完路徑，慢車設定可達上百秒）。

**模擬視野（2026-08-17 修）**：`simulate()` 舊版寫死 `maxTime=12`，慢速情境會回報
「未碰撞・最近距離落在 t=12.00」的假象（test1 汽車 ×0.5 其實 15.5 s 撞上），連 solve 的
「×≤0.65 可避開」都是假的。現在預設跑到**兩車都走完路徑**為止、保險上限 180 s；回傳
`endTime` 與 `horizonReached`（觸頂且未走完＝結論不完整），`solve.js` 把 horizonReached
當「未證明安全」不列入安全區間並回報 `horizonTruncated`。**`minGapTime` 剛好等於上限
就是視野截斷的訊號。**

**對外 demo 呈現（2026-08-17 定調）**：觀眾是非技術人——預設不顯示任何絕對 km/h、
class、track id（`?debug=1` 才顯示），只顯示倍率 ×k；時間軸顯示秒數不顯示幀號；兩台同
label 的車自動加 A/B；鏡頭 preset 以兩車軌跡包圍盒取景（`actionBounds`），不是地面中心。
`OrbitControls` 建構時就把 `camera.up` 抓死，之後改它不理——頂視圖不要動 up，改成從正上方
往南偏 0.5°，否則相機落在極點左鍵拖曳完全沒反應。

**對外簡報圖**：`docs/diagrams/`（三張 16:9 SVG：概念架構／使用流程／元件級技術架構），
由 `make_diagrams.py` 產生——**改字改座標請改產生器再重跑**，不要手改 SVG；生圖 prompt 在
`image-gen-prompts.md`。

**資料陷阱**：追蹤器位置在碰撞前 0.5s 會凍結（bbox 重疊+平滑假象），位移回推的
絕對速度不可靠——UI 滑桿因此用「實錄剖面倍率 ×k」語意，km/h 僅供參考顯示。

**渲染定調（使用者拍板）**：明亮基調＋單一主光源＋清楚影子（hemi 0.55/ambient 0.25/
sun 3.2/shadow 4096）。ACES+IBL 電影感已試過並否決（revert d917786），勿再往暗沉推。

**模型坑**：`MotoCollider`/`CarCollider` 是整個模型層級的**父節點**（砍子樹＝全滅，
只能拔 mesh 引用或隱藏）；moto.glb 另帶零厚度地面圓片 `Object_4`（父節點 `floor_0`）。
播放器由 `threejs/models/registry.json` 的 per-model `hide` 清單隱藏這類參考幾何，比對是
**精確節點名稱、不是前綴**——Sketchfab 的 `Object_N` 流水號下前綴會誤殺真零件
（`Object_4` 曾連 `Object_41/43/44/46/48` 一起隱藏，機車缺件）。要隱藏整棵子樹就列父節點名。

### 新影片進場流程（2026-07-24 全鏈驗證）

```bash
# 0.（選配，建議）地面圖去車＋銳化。**等比整數倍放大，座標仍然有效**；
#    build_scene 會自動優先採用 sat_<code>_hd.png 並把 px_per_meter 乘上縮放比
python3 satellite_pipeline/image_enhance.py \
  --input  trafficlab-project/location/<code>/sat_<code>.png \
  --output trafficlab-project/location/<code>/sat_<code>_hd.png --upscale 2

# 1. 挑 collider（唯一的人工判讀，但現在有品質欄位輔助）
python3 tools/build_scene.py --trajectory T.json --list

# 2. 產場景包。地面圖＝G-projection 的校正參考圖（見下方「座標對位」，勿用 --sat-dir）
python3 tools/build_scene.py --code <code> --trajectory T.json \
  --ground-image trafficlab-project/location/<code>/sat_<code>.png \
  --px-per-meter <trajectory.meta.px_per_meter> --size-m <sat_w/ppm> <sat_h/ppm> \
  --collider <id>:Car --collider <id>:Two_Wheeler --source-collision <frame>

# 3. 播放器零改碼：threejs/index.html?scene=<code>；跑 node tools/verify_scenes.mjs 驗收
```

只剩兩個必要人工判斷：**挑兩台 collider 的 track ID**、**標碰撞幀**（追蹤器碰前凍結，
無法自動判定）。可重現性已驗證：用 committed 參數重建 tainan_yongkang，ground.png 與
trajectory.json **sha256 位元組級相同**。

**挑 collider 現在有資料輔助**（2026-07-28）：`--list` 會從 `kp_sat` 自算並顯示
展開度中位數／輪關鍵點中位數／可用率（門檻 `spread ≤ 8m` 且 `n_wheel_kp ≥ 2`，
不合的掛 ⚠）；挑到品質不足的 track 當 collider 會發 `UserWarning`。
判據**自己從 `kp_sat` 算**，所以既有的 trajectory.json 不必為此重跑 pifpaf。

實證有效：taipei-cm 的 track 53 可用率 83%、track 1 掛 ⚠（0 個輪點、0% 可用率）——
這與獨立量測的 heading 誤差 3.10° vs 90.23° 完全一致，**不需要 ground truth 就挑得出好 track**。

**地面圖增強的安全邊界**：`image_enhance.py --input/--output` 走的是
「Gemini 偵測車框 → cv2 inpaint 去車 → UnsharpMask 銳化 → LANCZOS 整數倍放大」，
**只動局部像素與像素密度，不動幾何**，所以 `size_m` 不變、只有 `px_per_meter` 乘上倍率。
函式內有最後一道 assert，尺寸若不是精確整數倍會直接 raise。
**`--genai` 不可用於此路徑**（Gemini 重畫整張，長寬比與內容都可能變），CLI 會直接擋下。

`--sat-dir`（satellite_pipeline 新擷取的圖）只適用於**在衛星座標系合成的軌跡**
（tainan_yongkang），真實影片用它會錯位——satellite_pipeline 的定位是合成場景的地面來源，
不是真實影片的地面來源。

### 路徑產生器 haware（2026-07-28 起由本 repo 接管，不再是隊友專屬）

`trafficlab-project/trafficlab/motion/haware_localization.py` 的 `localize()` **就是產出
路徑的那個 module**。它一個函式同時吐兩個東西，而**我們只吃其中一半**：

```text
PifPaf 24 關鍵點 → localize()
   ├─ sat_coords → position_m → trajectory.json → 場景包 → 3D 播放   ← 我們用
   └─ heading                 → 播放器不讀（自己從線段 atan2(dx,dz) 算） ← 我們不用
```

**判斷任何 haware 改動值不值得做，先看它打在哪一半**：位置那半直接決定碰撞結論，
heading 那半只對隊友的 replay/GUI 有用（播放器自己從線段算 heading，不讀這半）。

#### 已修正並套用（含回歸測試 `trafficlab-project/tests/`，14 測）

- **座標系手性 bug**：`localize()` 的 Procrustes 寫死 `no reflection`（強制 det=+1），
  但模板（x=車左、z=車後）→ 衛星像素（x 右、**y 下**）**必然需要反射**（det=−1）。
  誤差不是隨機而是解析可預測的：`heading 誤差 = 2 × angle(點集主軸, 車體 z 軸)`——
  縱向主導的點集看起來正常、**橫向主導的恰好錯 180°**、同側輪對 heading 對但位置偏一個
  軌距。**「輪子看起來是唯一可靠的關鍵點」整個是這個 bug 造成的假象。**
  修法：在 `localize()` 內鏡射 `Q` 的 x 欄（**不要改模板**——`localize_reprojection()`
  也讀它，且模板 docstring 對外承諾「+x = 車左」）。
  實測：近端 track 53 heading 94.73° → **3.10°**；**位置變動 1.52m 中位數**（這半才影響我們）
- **展開度閘門**：`spread_m` > 8m → `status='extrapolated'`（座標仍保留供診斷）
- **`n_wheel_kp`**：參與擬合的輪關鍵點數，與 `spread_m` 一起寫進 replay JSON——
  因為下游 `filter_and_enrich_output.py` → `build_scene.py` **只讀 `sat_coords`、不看
  `status`**，不輸出判據的話外推幀會靜默流進場景包

完整證據與可信度邊界見 `docs/decisions/2026-07-27-haware-localizer-parity-bug.md`。

#### 挑 track 的建議門檻

`spread_m ≤ 8` 且 `n_wheel_kp ≥ 2`。實測（taipei-cm，以行進方向為獨立參考）輪點數
≥2 時 heading 中位誤差 **2.42°、>90° 災難率 0%**；0–1 個時約 98°、>50% 災難。
**但這是相關性不是因果**——≥2 輪點的樣本幾乎都來自近端的 track 53，與「距離近」高度混淆。

#### 路徑那半尚未解決的（優先序）

1. **位置準度從未被量過**：兩站點都沒有位置 ground truth，先前全部是內部一致性指標。
   我們知道手性修正「改變」了位置 1.52m，**不知道「改對」了多少**。唯一可得的準參考是
   h=0 的輪關鍵點（模板裡唯一實測而非估計的高度）
2. **品質判據還沒接進 `build_scene.py`**：`spread_m`／`n_wheel_kp` 已輸出但沒人用來過濾，
   挑 track 仍是純人工判讀
3. **`path.js` 淨化參數只在 test1 一份資料上調過**（RDP ε=0.06、a≤3.0/b≤7.5），
   真實新影片的噪音特性、取樣率、碰前凍結窗都不同

#### heading 那半尚未解決的（對我們的 demo 無直接影響）

前後標籤顛倒：tracks 1/501/502 帶著 90–161° 的壞 heading 通過展開度閘門，共同點是
**沒有輪關鍵點**。這是 PifPaf 語意問題，純幾何閘門擋不掉。注意陷阱：**若整台車一致地
顛倒，任何內部一致性檢查都抓不到**（整組都翻了，自己跟自己一致），必須引入外部證據
（運動方向）——但那又有循環論證風險，因為 course 由同一個擬合的位置推得。

#### 驗收場地

**不要用 taipei-cm 驗收**：它 z_cam=3.596m 是 repo 內 8 個地點最低（1/k 幾何懲罰 1.85×
vs kee-cc 1.29×），而且有**獨立的 homography 度量缺陷**——用 h=0 輪對量觀測軸距，
模板 2.546m 但實測中位數 5.92m、落在合理區間的只有 12.5%（kee-cc 是 53.2%）。
改用 kee-cc / taoyuan-tc。

### 已知缺口（測試已標記，勿當成 bug 重查）

- **座標對位＝用 G-projection 的參考衛星圖，不要用新擷取的 Google 圖**（2026-07-24 實證）：
  `position_m` 的座標系就是 `trafficlab-project/location/<code>/sat_<code>.png` 這張**校正
  參考圖**的平面（原點＝圖左上角，尺度＝`trajectory.meta.px_per_meter`）。所以真實影片的
  地面圖必須是**那張圖本身或其等比縮放**：
  - `size_m = [sat_w / meta.px_per_meter, sat_h / meta.px_per_meter]`
  - `origin_offset_m = size_m / 2`（build_scene 自動算）
  - 等比縮放時 `ground.px_per_meter = meta.px_per_meter × 縮放比`

  test1 就是這樣做的：`sat_test1.png` 1676×1148 @34.41px/m → 48.71×33.36m，與
  `scene.json` 的 `size_m` **完全相同**；`ground.png` 1515×1038 是它的 0.904 倍縮放
  （31.10 = 34.41×0.904）。**但 `scenes/test1/ground.png` 是幾何相同、畫質遠好於
  `sat_test1.png` 的增強版**（2026-08-17 實測：拿 `sat_test1.png` 或它的 `image_enhance`
  輸出換掉它會明顯變糊，Gemini 對整張圖只抓到 2 台車、inpaint 還留下污漬）——**不要重產
  test1 的 ground.png**。taipei-cm 同樣吻合（1190×1258 @27.85 → 42.72×45.16m，
  軌跡 x 9.0–33.2、y 15.7–43.1 完全落在範圍內）。

  **陷阱**：`--sat-dir`（satellite_pipeline 新擷取的 Google 圖）是**另一張不同取景的圖**，
  對真實軌跡會錯位——它只適用於在衛星座標系合成的軌跡（tainan_yongkang 就是這樣來的）。

  ✅ **2026-07-28 已自動化**：真實影片改用
  `--location-dir trafficlab-project/location/<code>`，會自動讀 `sat_<code>.png` 尺寸 ×
  `trajectory.meta.px_per_meter` 算出 `size_m`，不必再人工算三個數字。
- ~~車種 class 大小寫不符~~ ✅ **2026-07-28 修掉**：`build_scene.normalize_class()`
  與 `scene-loader.js` 的 `lookupClass()` 都改成不分大小寫（含 motorcycle/scooter 等別名）
- ~~fps 寫死 30~~ ✅ **2026-07-28 修掉**：`build_scene.resolve_fps()` 從
  `trajectory.meta.fps` 帶入，含 0／負／NaN／∞／型別錯的驗證與回退警告
- ~~壞格式軌跡報錯不乾淨~~ ✅ **2026-07-28 修掉**：`scan_tracks()` 一律拋 `SceneBuildError`
  並指名壞在哪；缺 `position_m` 的計數會併進「collider 不存在」訊息，不再誤導
- **入口驗證不完整**（注意：失敗方式不是 NaN 傳染，是**靜默給出錯誤結論**）：
  `trajectory.meta.fps` 有驗證（無效會 warn 並回退），但**回退目標 `cfg.frames.fps` 完全
  沒人驗**——fps=0 → 時間軸 NaN/Infinity、fps<0 → 時間軸倒流、fps=∞ → t 全 0；下游
  `speedProfile` 被 guard 夾成 0.01 m/s、`startT=NaN` 讓 simulate **回報「沒有碰撞」**。
  另：`origin_offset_m` 缺失是 raw TypeError／含 NaN 則靜默產生 NaN 座標；`mass_kg`
  缺失或為 0 不 throw 也不 warn，碰後兩車速度變 NaN、各自凍在撞擊瞬間位姿到 maxTime
- **scene.json 的假可配置欄位**：`collision` 只有**頂層物件**被列為必要，
  `restitution/friction` 兩個子欄位**完全不驗**（`"collision": {}` 照樣通過），而且全 repo
  沒有任何程式讀 `cfg.collision`——`simulate.js:16-17` 寫死 `RESTITUTION=0.15`／`MU=0.7`
  （MU 只管碰後地面滑行；碰撞當下的切向摩擦是 `physics.js:118` 另一個寫死的
  `muContact=0.5`，simulate 也沒傳）。build_scene 仍照樣把這組沒人讀的值寫進 scene.json。
  `frames.anim_*` 同理：被驗證但播放器不讀（時間軸由 simulate 輸出決定，`animStart` 是
  main.js 寫死的 1），`--anim` 預設 1,32,89 是死值
- **部署約束**：`scene-loader.js` 用 `../scenes/` 相對路徑 → 站根必須同時含 `threejs/`
  與 `scenes/` 兩個同層目錄，只部署 `threejs/` 會全數 404
- **HD 底圖無自動驗收**：`sat_genai` 的去車乾淨度、幻想標線、左下角 Google 浮水印殘留
  只能人眼確認；`genai_enhance()` 也不回寫 meta.json（長寬比若與 raw 不同會被拉伸）

---

## 何時主動用 Codex

遇到以下情況**不等使用者說**，直接用 `codex:rescue` skill：

- 設計或修改 Three.js 相關實作（物理、動畫、模型載入、渲染）
- 車輛比例、座標轉換、物理公式的計算邏輯
- 新功能有多種實作方向需要比較時

**怎麼用**：帶入當前場景設定、已知坑、目標，讓 Codex 直接產出實作，再和自己的做法比較，選最好的整合。

---

## 並行規則

| 可並行 | 不可並行 |
| --- | --- |
| 同一事故的多視角場景 | 產場景包 → verify_scenes 驗收（有先後依賴） |
| Track A 軌跡計算 + Track B 場景初始化 | 淨化管線各步（順序固定，見上方） |

---

## Three.js 必記的坑

- **GLTF 座標轉換**：GLB 模型的原生軸向 → GLTF -Z → Three.js -Z，載入後需
  `gltfScene.rotation.y = flip`（每模型的 flip 記在 `registry.json`，量法見該檔 `_comment`）
- **Bounding box centering**：`Box3.setFromObject()` 讀 stale matrix。先算 rotation 前的 bbox center `(cx, cz)` 和 `minY`，再 `gltfScene.position.set(cx, -minY, cz)`
- **車輛尺寸**：縮放目標讀 `scene.json` 的 `length_m`，用 8 角點投影到車頭軸精確量測後
  scale-to-length（`measureBodyExtentAlongAxis`）——不靠估算值
- **Heading drift**：不要插值 heading 欄位，要從 segment 的 `(dx, dz)` 動態算 `atan2(dx, dz)`
- **換模型**：直接放新 GLB 到 `threejs/models/`、在 `registry.json` 補一筆（file/flip/hide），
  flip 在瀏覽器量前後輪中心連線重算。無需任何離線工具鏈

## TrafficLab 必記的坑

- **Apple Silicon MPS + half precision**：推論失敗先確認 `inference_config.yaml` 的 `half: false`
- **Python 環境**：`trafficlab` conda env 不存在，改用 `/Users/weihong/Documents/littering_prediction/venv/bin/python`（有 ultralytics, supervision, opencv）
- **MPS 訓練 bug**：Python 3.14 + PyTorch + MPS 在 tal.py loss 計算會 shape mismatch crash，訓練必須用 `device="cpu"` 或 Colab GPU
- **G-projection 路徑**：推論讀 `location/<code>/G_projection_<code>.json` 或 `G_projection_svg_<code>.json`
- **supervision 0.28.0**：`InferenceSlicer` 用 `overlap_wh=100`（不是 `overlap_ratio_wh`）；`ByteTrack` deprecated 但還能用

---

## TrafficLab 偵測優化進度（trafficlab-project/）

> **2026-07-20 起凍結**：偵測／軌跡優化由隊友主導（他們的結果更好），本 repo 不再投入。
> 以下保留為記錄與參考。

### 已實作

- **bbox quality filter**（`pipeline.py:_is_valid_detection`）：`min_conf=0.45`、`min_area_px=400`、`aspect_ratio 0.4–4.0`，在 `inference_config.yaml` `detection_filter` 段落控制
- **視覺化腳本**：
  - `scripts/viz_detection_filter.py` — 顯示哪些框被過濾
  - `scripts/viz_slicer_compare.py` — InferenceSlicer vs 全圖推論對比
  - `scripts/viz_rife_compare.py` — 原始 25fps vs RIFE 4x 對比

### VisDrone Fine-tune ✅ 完成且驗收通過

- **Colab notebook**：`scripts/colab_train_visdrone.ipynb`，T4 GPU
- **結果**（2026-06-06，50 epochs）：mAP50=0.400，mAP50-95=0.228，val loss 在 epoch 25–30 平台
- **模型位置**：`trafficlab-project/models/yolo11l-visdrone-ft.pt`（勿與 `models/training/` 內
  epoch 21 的本地未完成訓練混淆）
- **驗收**（2026-06-06，`detection_tests/`）：二輪偵測 10→214（×21）、汽車信心 0.761→0.790、
  COCO 的 337 個紅綠燈誤報消失。比較影片與對比圖在 `detection_tests/outputs/`
- 註：`inference_config.yaml` 各 config 的 weights 仍指向不存在的舊模型檔，若隊友要在本機跑
  推論需先改指 `./models/yolo11l-visdrone-ft.pt`

### 測試結果摘要

| 方法 | 效果 | 結論 |
| --- | --- | --- |
| conf 門檻調整 | -24% 框（多為噪音） | 已加入 config |
| InferenceSlicer（640px patch） | +15% 軌跡數 | 可選，腳本已備 |
| RIFE 4x 補幀 | +8% 但偵測品質**下降** | **不用**，AI 生成幀干擾 YOLO |
| VisDrone fine-tune | 二輪 ×21、汽車信心 +0.03 | ✅ 驗收通過，見 `detection_tests/` |

### 已寫好但未啟用的功能

- `MotorcycleLateralCorrector`（`lateral_correction.enabled: false`）
- `MotorcycleMotionFilter`（`motorcycle_filter.enabled: false`）

---

## TrafficLab-3D 2D→3D 優化方向（/Documents/TrafficLab-3D）

> **同樣凍結**（隊友主導）。問題根源：YOLO bbox 噪音 + 幾幀沒偵測到 → 軌跡抖動、heading 亂跳

### 偵測改進

- `yolo11l.pt`（COCO）對轎車偵測良好（conf ≈ 0.90），機車容易漏
- `yolo11l-obb.pt`（DOTA）**不適用**：鏡頭斜角透視，機車被誤判為 ship
- **RIFE 補幀不適用於偵測改進**：AI 生成幀讓 YOLO 品質下降，已測試確認

### 軌跡穩定（Kalman Filter，尚未實作）

設計文件：`TrafficLab-3D/docs/superpowers/specs/2026-05-25-trajectory-stabilization-design.md`

需改動三個檔案：

1. `trafficlab/inference/pipeline.py` — 加 missing-frame predict loop
2. `trafficlab/motion/kinematics.py` — 加 2D Kalman Filter（state: x, y, vx, vy）+ innovation gate
3. `inference_config.yaml` — 加 `kalman_*` 參數

Kalman 關鍵參數：`kalman_process_noise=0.1`、`kalman_measure_noise=2.0`、`kalman_gate_threshold=3.5`

---

## 待辦（詳見 docs/todonext.md）

主線＝場景包 demo（spec：`docs/specs/2026-07-20-scene-bundle-threejs-demo-design.md`）：

- [x] `scenes/test1/` 場景包 + scene.json schema 定案（`schema_version: 1`）
- [x] `tools/build_scene.py` 半自動場景包產生器
- [x] Three.js 播放器改造：讀場景包、碰後旋轉、光影、相機 preset、播放速度、本地 vendor
- [x] 確認 car.glb / moto.glb 各自的前方軸向，MODEL_FLIP 改 per-model 設定（registry.json）
- [ ] 靜態部署（丟連結就能看，含手機）← **唯一真未完成的主線項**（Pages 未啟用）
- [x] 第二場景驗證（tainan_yongkang，換場景零程式碼修改）

接下來（依 2026-07-24 全鏈驗證，優先序）：

1. 跟隊友要一份新影片的真實 `filtered_output` 樣本，驗格式契約並寫進文件
2. `build_scene.py` 帶入 `trajectory.meta.fps`（測試已寫好，補實作即轉綠）
3. 靜態部署（注意 `threejs/` 與 `scenes/` 同層的路徑約束）
4. 座標對位（等真實影片＋衛星圖組合出現才做得動）

凍結（隊友主導）：TrafficLab inference config、Kalman、Motorcycle 濾波器。
