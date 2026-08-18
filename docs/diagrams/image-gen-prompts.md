# 三張簡報圖的生圖 prompt（Codex / gpt-image 用）

對應 `docs/diagrams/` 的三張 SVG：A `architecture-overview.svg`、B `user-flow-overview.svg`、
C `system-architecture-flow.svg`。內容以 SVG 版為準，這裡是把它翻成生圖模型吃得懂的描述。

## 使用前先知道的三件事

1. **生圖模型畫中文字很不穩**（缺筆畫、亂碼）。建議做法二選一：
   - 先用「Style / Layout」段生**沒有文字**的版本（prompt 末尾加 `no text, no labels`），
     再把中文字在 Keynote／Figma 疊上去（字都在 SVG 裡可以直接複製）；
   - 或標籤改用英文（每段都附了 EN 對照），生完再視需要換中文。
2. 每張都固定 **16:9、白底、扁平向量插畫風**，三張才會像同一套。
3. 三張共用同一組顏色，直接把 hex 貼進 prompt：
   - 墨色 `#14212B`、灰字 `#63707C`、線 `#A3AEBA`
   - **藍**（系統／主流程）`#1E63D6`（淡底 `#DDE8FA`）
   - **琥珀**（人工／準備）`#C46A12`（淡底 `#FBEBD3`）
   - **綠**（產出）`#178A4C`（淡底 `#D8F1E2`）
   - 核心區底 `#E9EFF7`

共用的風格句（三張 prompt 開頭都貼這段）：

```
Flat vector infographic, presentation slide, 16:9, pure white background, clean geometric
shapes with rounded corners, thin 2.5px outlines, no gradients, no shadows, no 3D, no photos,
sans-serif typography, generous whitespace, aligned to a strict grid, minimal and professional.
Palette: ink #14212B, gray #63707C, blue #1E63D6 with light fill #DDE8FA, amber #C46A12 with
light fill #FBEBD3, green #178A4C with light fill #D8F1E2.
```

---

## 圖 A・系統架構「兩種資料，合成一個 3D 現場」

**中文標籤（EN 對照）**
- 標題：兩種資料，合成一個 3D 現場（Two data sources, one 3D scene）
- 副標：地點給底圖、影片給軌跡；經空間對位後在同一個 3D 場景匯流，產出可互動的事故重演
- 輸入 chip（琥珀、人形圖示）：經緯度（Location）、監視影片（CCTV video）
- 上軌「地面資料」：現場底圖（Site base map）— 地點 → 衛星圖底圖
- 下軌「動態資料」：影像素材（Video frames）→ 空間對位（Spatial alignment，琥珀、人形）→ 車輛軌跡（Vehicle trajectories）
- 匯流：場景合成（Scene composition）— 底圖 + 軌跡 合而為一
- 產出（綠色大瀏覽器視窗）：3D 重演（3D replay）— 瀏覽器直接看／調車速，看會不會撞，附「慢 ←●→ 快」滑桿
- 箭頭字：對位置、取畫面、定位、鋪現場、放車流、生成
- 圖例：需要人動手（琥珀）／系統自動（藍）／產出（綠）

**Prompt**

```
[共用風格句]

Title top-left in bold: "兩種資料，合成一個 3D 現場". Subtitle in gray below it.

Layout, left to right. Far left: two small amber pill boxes with a tiny person icon:
"經緯度" (top) and "監視影片" (bottom). Two horizontal lanes labelled in small gray caps
"地面資料" (upper lane) and "動態資料" (lower lane).
Upper lane: one blue rounded box "現場底圖" with a small lightning icon and gray caption
"地點 → 衛星圖底圖".
Lower lane: three boxes in a row connected by gray arrows: blue "影像素材" (caption
"事故當下的車輛畫面") → amber "空間對位" with a person icon (caption "影像位置 ↔ 現場位置")
→ blue "車輛軌跡" (caption "還原每台車的移動"). Arrow labels "取畫面" and "定位".
A thin gray arrow drops from "現場底圖" down into "空間對位", labelled "對位置".
Both lanes converge (Y shape) into one blue box on the right "場景合成" (caption
"底圖 + 軌跡 合而為一"); the two incoming arrows are labelled "鋪現場" and "放車流".
From "場景合成" a dark arrow labelled "生成" points down to the visual focus at bottom-right:
a large green-outlined browser window mockup (three traffic-light dots in the title bar)
containing a tiny top-down intersection with a white car, a green scooter, dashed orange and
solid yellow trajectory lines, a red collision ring, the bold green title "3D 重演", captions
"瀏覽器直接看" and "調車速，看會不會撞", and a small slider "慢 ●— 快".
Bottom-left legend: three small swatches — amber dashed with person icon "需要人動手",
blue with lightning "系統自動", green with play triangle "產出".
The browser window is the only large element; everything else is quiet and evenly spaced.
```

---

## 圖 B・使用流程「三次人工，其餘自動」

**中文標籤（EN 對照）**
- 標題：三次人工，其餘自動（Three manual steps, everything else automatic）
- 副標：從一支監視器影片到可操作的 3D 事故重演，使用者只需在三個地方動手
- 六步（1–5 為卡片、6 為大瀏覽器視窗）：
  1. 提供素材（Provide inputs，琥珀）— 你：給影片、填地點／系統：抓現場底圖
  2. 對準現場（Align to site，琥珀）— 你：點兩畫面同一處／系統：建立位置對應
  3. 還原軌跡（Recover trajectories，藍）— 系統：辨識車輛、還原每台車移動
  4. 指定事故（Mark the crash，琥珀）— 你：挑兩車、標碰撞／系統：鎖定主角與時間
  5. 建立場景（Build scene，藍）— 系統：合成道路、車輛與碰撞
  6. 互動重演（Interactive replay，綠）— 調車速・切鏡頭・看會不會撞／系統即時算出安全車速
- 底部：你只做三件事：給地點與影片・點對應位置・挑車、標碰撞／其餘辨識、軌跡重建、場景生成、碰撞計算全部自動。

**Prompt**

```
[共用風格句]

Title top-left in bold: "三次人工，其餘自動". Gray subtitle below.

One horizontal row of five equal rounded cards, left to right, connected by small gray arrows,
each card has a numbered circle badge top-left (1–5) and an icon top-right:
1 "提供素材" amber card with a person icon; two lines below the title:
  "你：給影片、填地點" and "系統：抓現場底圖".
2 "對準現場" amber card with a person icon: "你：點兩畫面同一處" / "系統：建立位置對應".
3 "還原軌跡" blue card with a lightning icon: "系統：辨識車輛，還原每台車移動".
4 "指定事故" amber card with a person icon: "你：挑兩車、標碰撞" / "系統：鎖定主角與時間".
5 "建立場景" blue card with a lightning icon: "系統：合成道路、車輛與碰撞".
A dark arrow leads to step 6 on the far right: a taller green-outlined browser window mockup
titled "6 互動重演" with a green play button, containing a top-down intersection thumbnail
(white car, green scooter, orange dashed and yellow trajectory lines, red collision ring),
a slider "慢 ●— 快", captions "調車速・切鏡頭・看會不會撞" and green bold
"系統即時算出安全車速".
Below the row, one line: bold "你只做三件事：" followed by three small amber person icons
with "給地點與影片", "點對應位置", "挑車、標碰撞"; then a gray sentence
"其餘辨識、軌跡重建、場景生成、碰撞計算全部自動。"
Bottom-left legend: amber "需要人動手", blue "系統自動", green "產出".
Cards are identical in size; amber and blue alternate exactly as listed.
```

---

## 圖 C・技術架構（RAG 教學圖語法：圖示＋編號流程）

**中文標籤（EN 對照）**
- 標題：系統架構：監視器影片 → 3D 事故重演
- 副標：前端收素材與人工標註；重建管線把影像換成現場公尺座標與軌跡；Three.js 在瀏覽器內模擬重演
- 左：User（兩個人形）
- 前端：網頁前端（Web front-end）— 底圖工作台・標註・播放器／瀏覽器，零安裝；上方一個小瀏覽器圖示
- 左上「外部服務」盒：Google 衛星圖（Static Maps API・zoom 21）、Gemini 去車（偵測車框 → inpaint → 銳化）
- 中央淺藍大區「TrafficLab 重建管線」（Python・OpenCV・YOLO・PifPaf），內含四個白盒：
  空間校正（G-projection：H・K/D・視差，琥珀外框）、車輛偵測（YOLO 追蹤 + PifPaf 24 關鍵點）、
  地面定位（關鍵點 → 現場公尺座標）、軌跡整理（平滑・直線化・速度剖面）
- 三個虛線對話框（資料範例）：「對應點 ≥4 對／影像 px ↔ 現場 m・px/m」、
  「每幀每車 (x, y) m／spread・輪點數（品質）」、「position_m・startT／速度剖面（實錄）」
- 右上：Three.js 3D 重演（藍外框、3D 方塊圖示）— 瀏覽器內前向物理模擬／OBB 碰撞・衝量・調速倍率・安全車速
- 下中：場景包 scenes/<code>/（資料庫圓柱圖示）— scene.json・ground.png・trajectory.json
- 左下虛線框「輸入資料」：CCTV 影片（攝影機圖示）、事故地點（地標圖示）
- 編號箭頭（藍＝主流程，琥珀＝準備）：
  ① 影片＋經緯度（User→前端）② 經緯度 → 擷取衛星圖（前端→Google，琥珀）
  ③ 去車銳化的底圖（Gemini→空間校正，琥珀）④ 點對應點／對應點（User→前端→空間校正，琥珀）
  ⑤ 影格（前端→車輛偵測）⑥ 定位 ⑦ 整理 ⑧ 挑車・標碰撞（User→前端）
  ⑨ build_scene 打包（軌跡整理→場景包）⑩ 載入場景包（場景包→Three.js）
  ⑪ 3D 重演回到瀏覽器（Three.js→User，沿頂部繞回）；另一條無編號琥珀線「校正參數」（空間校正→地面定位）
- 圖例：重建主流程 1 → 11（藍）／底圖與校正準備 2 → 4（琥珀）／資料範例（虛線框）

**Prompt**

```
[共用風格句]
Style reference: a RAG tutorial architecture diagram — component icons with labels, numbered
arrows for the main flow, one large light-blue rounded region grouping the core pipeline,
an external-service box, data stores at the bottom.

Title top-left in bold: "系統架構：監視器影片 → 3D 事故重演". Gray subtitle below.

Left: a "User" icon (two black person silhouettes) with a small label box "User".
Center-left: a rounded box "網頁前端" (caption "底圖工作台・標註・播放器", small gray note
"瀏覽器，零安裝") with a tiny browser-window icon above it.
Three parallel horizontal arrows from User to the front-end, each with a numbered circle badge
and label above: ① blue "影片＋經緯度", ④ amber "點對應點", ⑧ blue "挑車・標碰撞".
Above the front-end: a light-gray rounded box "外部服務" containing two rows with icons:
map-pin "Google 衛星圖" (caption "Static Maps API・zoom 21") and a target/lens icon
"Gemini 去車" (caption "偵測車框 → inpaint → 銳化"). An amber vertical arrow ② labelled
"經緯度 → 擷取衛星圖" goes up from the front-end into this box; an amber arrow ③ labelled
"去車銳化的底圖" leaves its right side, turns down and enters the top of "空間校正".
Center: a large light-blue (#E9EFF7) rounded region titled top-right "TrafficLab 重建管線"
(small caption "Python・OpenCV・YOLO・PifPaf"). Inside: top-left an amber-outlined box
"空間校正" (caption "G-projection：H・K/D・視差") with a dashed speech bubble to its right
reading "對應點 ≥4 對 / 影像 px ↔ 現場 m・px/m". Bottom row, three white boxes connected by
blue arrows: "車輛偵測" (caption "YOLO 追蹤 + PifPaf 24 關鍵點") →⑥ "定位"→ "地面定位"
(caption "關鍵點 → 現場公尺座標") →⑦ "整理"→ "軌跡整理" (caption "平滑・直線化・速度剖面").
Two dashed bubbles float above the last two boxes: "每幀每車 (x, y) m / spread・輪點數（品質）"
and "position_m・startT / 速度剖面（實錄）". An amber right-angle arrow labelled "校正參數"
runs from the bottom of "空間校正" into the top of "地面定位".
From the front-end, two right-angle arrows enter the region: amber ④ "對應點" into
"空間校正", blue ⑤ "影格" into "車輛偵測".
Top-right: a blue-outlined box "Three.js 3D 重演" with a small blue isometric cube icon,
captions "瀏覽器內前向物理模擬" and "OBB 碰撞・衝量・調速倍率・安全車速".
Bottom-center: a database cylinder icon next to a label box "場景包 scenes/<code>/"
(caption "scene.json・ground.png・trajectory.json"). Blue arrow ⑨ "build_scene 打包" comes
down from "軌跡整理" into it; blue arrow ⑩ "載入場景包" leaves it to the right, goes up the
right margin and enters the Three.js box. Blue arrow ⑪ "3D 重演回到瀏覽器" leaves the top of
the Three.js box, runs along the very top back to the left and drops onto the User.
Bottom-left: a dashed rounded frame "輸入資料" with a camera icon "CCTV 影片" and a map-pin
icon "事故地點"; a blue arrow labelled "上傳" goes from it up into the front-end.
Bottom legend: blue arrow "重建主流程 1 → 11", amber arrow "底圖與校正準備 2 → 4",
dashed small box "資料範例".
All arrows are orthogonal (horizontal/vertical with right-angle bends), never diagonal, and
labels sit in clear whitespace with no overlaps.
```

---

## 建議的生成參數

- 尺寸：1792×1024（最接近 16:9）或 1536×864；品質 high。
- 一次只生一張、先看無文字版的構圖對不對，再決定要不要讓模型畫字。
- 若模型把中文畫壞，把 prompt 內的中文全換成上面括號裡的英文，中文用 SVG 版本裡的字疊回去。
