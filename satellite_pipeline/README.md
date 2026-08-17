# satellite_pipeline — 衛星底圖自動化

事故地點經緯度 → 衛星圖 → 去車 + 銳化高清化。輸出的 `sat_*.png` + `meta.json`
供 `tools/build_scene.py --sat-dir` 取用，產生場景包的 `ground.png`。
獨立模組，與 `trafficlab-project/`（上游軌跡推論）分開。

```text
lat/lon
  → [1] map_capture.py    Google Static API      → sat_raw.png + meta.json
  → [2] image_enhance.py  Gemini 去車 + 銳化      → sat_clean.png
                          生圖 HD（--genai，gemini／openai）→ sat_genai.png
```

全部輸出在 `output/{code}/`。

---

## 用法

```bash
# 設 key（擇一）：環境變數 或 satellite_pipeline/.env
#   GOOGLE_MAPS_KEY=...   (Static API)
#   GEMINI_API_KEY=...    (去車偵測，只回 bbox JSON 不生圖)
#   OPENAI_API_KEY=...    (--genai-provider openai 才需要)

# 一鍵全流程
python3 satellite_pipeline/pipeline.py \
    --lat 23.026901 --lon 120.249615 --code tainan_yongkang --size 25

# 單步 / 重跑
python3 satellite_pipeline/map_capture.py  --lat .. --lon .. --code ..
python3 satellite_pipeline/image_enhance.py --code .. --genai     # 出 HD 版 sat_genai.png
python3 satellite_pipeline/pipeline.py --code .. --skip-capture   # 只重新增強

# HD 版預設帶風格參考圖 refs/road_style_ref.png（真實空拍馬路，借柏油材質）
# 關閉風格參考：--style-ref ""
```

輸出：

| 檔案 | 內容 |
| --- | --- |
| `output/{code}/sat_raw.png` | 原始衛星圖（裁中心 size×size m） |
| `output/{code}/sat_clean.png` | 去車 + 銳化（忠實版） |
| `output/{code}/sat_genai.png` | Gemini HD 版（`--genai`，視覺最佳） |
| `output/{code}/meta.json` | lat/lon, px_per_meter, img_w/h, 去車數… |

---

## 鎖定的技術決策（2025-06 實測）

### 圖源：Google Maps Static API（`zoom=21, scale=2`）

此地點 **29 px/m**，純 HTTP 免 playwright。其他來源全部實測過：

| 來源 | 結果 |
| --- | --- |
| **Google Static API** | ✅ 採用。29 px/m、無 UI 標籤、穩定 |
| Esri World Imagery（舊 pipeline 用） | ❌ 台南此點 z20 無資料、z19 僅 3.6 px/m（糊 8 倍，見 `compare/source_compare.png`） |
| Bing / Google Earth KH / NLSC | ❌ 無資料 / 需 token / SSL 壞 |

> 換不同 Google API 不會更清楚（Maps/Earth/Static 同一份底圖）。

### 兩種增強，輸出兩個版本

**A. 忠實版 `sat_clean.png`（預設，`enhance()`）— Gemini 偵測 bbox + cv2 inpaint + PIL 銳化**

- Gemini（`gemini-2.5-flash`）只回傳車輛 bbox JSON → `cv2.inpaint` 只填車輛區域 → `UnsharpMask` + 2x 放大。
- 不改動其他像素，幾何 100% 忠實。Gemini 失敗 → fallback 只銳化、不去車。

**B. HD 版 `sat_genai.png`（`--genai`）— 生圖清理 + 銳化（雙供應商，2026-08-17）**

- `--genai-provider gemini`（**預設**）走 `gemini-3.1-flash-image`，temperature 固定 0.4；
  `--genai-provider openai` 走 `gpt-image-2`（`images.edit`）。
  **來源都用 `sat_raw.png`**（比 sat_clean 銳利，模型會順手去車）。

- **兩家生圖模型實測對照**（同一張 `tainan_yongkang/sat_raw.png`、同 prompt、分塊相位相關，2026-08-17）：

  | 路徑 | 位移中位數 | >10px 區塊 | 全域相關 |
  | --- | --- | --- | --- |
  | `sat_clean`（忠實路徑，不生圖） | **0.00 m** | 0% | 0.968 |
  | `gemini-3.1-flash-image` | **0.20 m** | 37–39% | 0.854–0.876 |
  | `gpt-image-2` | **0.30 m** | 47% | 0.746 |

  Gemini 兩次獨立跑（6/8 舊產物、8/17 重跑）都落在 0.20–0.21 m，**穩定比 OpenAI 忠於原圖**，
  所以 `--genai-provider` 預設是 `gemini`。**但兩家都是重畫不是修圖**——承載座標的地面圖
  一律走 `sat_clean`，`--input` 路徑照舊禁用 `--genai`。

  完整證據（含「是內容被改寫、不是取景跑掉」的診斷，與 prompt／mask／input_fidelity
  三條死路的查證）見 [`docs/decisions/2026-08-17-satellite-genai-provider-choice.md`](../docs/decisions/2026-08-17-satellite-genai-provider-choice.md)。
  自己重量：`python3 satellite_pipeline/measure_genai_drift.py --code <code>`
- **OpenAI 那邊為什麼不是更便宜的 `gpt-image-1-mini`**：只有 `gpt-image-2` 能指定任意輸出尺寸
  （邊長 16 倍數、長邊 ≤3840、比例 ≤3:1、總像素 655,360–8,294,400）；
  `gpt-image-1` / `-mini` 只吐 1024x1024、1024x1536、1536x1024 三種比例，
  衛星圖不是這三種，送進去必被壓扁——**長寬比一變 px_per_meter 就失效**。選型由這條約束決定，不是價格。
  `plan_genai_size()` 負責協商合法畫布（比例誤差 <1%），拿回圖後**縮回來源原尺寸**，
  所以 `sat_genai.png` 與 `sat_raw.png` 共用同一組 px_per_meter。
- `--genai-quality`（**僅 openai 有效**）：`low` 試 prompt、`medium` 預設、`high` 定稿。
  （images API 沒有 temperature；`--genai-temp` 保留為已棄用的 no-op。Gemini 端固定 0.4。）
- **實測花費**（1280×1280 + 一張風格參考圖，2026-08-17）：

  | quality | 輸入（幾乎固定） | 輸出 | 合計 | $50 可跑 |
  | --- | --- | --- | --- | --- |
  | `low` | $0.0263 | $0.0070 | **$0.033** | ~1,500 張 |
  | `medium` | $0.0263 | $0.0629 | **$0.089** | ~560 張 |
  | `high` | $0.0263 | 約 $0.25 | 約 **$0.28** | ~175 張 |

  輸入那份**不隨 quality 變**（gpt-image-2 一律以 high fidelity 讀輸入圖），
  所以降 quality 省不到一半的錢；每次跑完會印出拆解，也寫進 `meta.json` 的 `genai_cost_usd`。
- prompt 三目標：
  1. **真實柏油路面**：自然中灰柏油色（不要太深、不要平塗），保留細微柏油質感像真馬路，
     不可變成死板的深色塊/剪影；整條路一致材質但乾淨（去髒污/補丁/輪胎痕）
  2. 道路輪廓（kerb / 路緣）銳利
  3. 既有標線保留但**不過度生成**：只留清楚可見的，渲成乾淨白色；不加粗、不增亮、不複製
- **不亂生規則**：模糊看不清的標線（機車停等格、看不清的箭頭）保持淡或省略，禁止模型猜/捏造/複製；
  只清理路面，不重畫建物/植被/人行道。
- **風格參考圖**（`--style-ref`，預設 `refs/road_style_ref.png`）：把真實空拍馬路一起餵給模型，
  只借它的**柏油材質質感**（深、粗糙、銳利），不借它的標線/佈局。
- ⚠ **這條路徑是「重畫」不是「修圖」**：尺寸現在守住了（兩家都縮回來源原尺寸），
  但標線位置仍會被重新詮釋而位移（見上表）。**沒有自動驗收，只能人眼比對**，
  且**不可用於 `--input` 座標關鍵路徑**（該路徑的存在理由就是保住座標）。
  好處：Google 浮水印會被一併重畫掉。

> 註：Gemini 端原本尺寸不可控（可能改長寬比），現已統一縮回來源原尺寸。
> 否決：不限制地讓模型重畫整張 → 會畫出不存在的圓環/公園/斑馬線。

---

## 座標系

- 影像左上角為原點，`px_per_meter` 記在 `meta.json`；平面尺寸 =
  `(img_w / px_per_meter) × (img_h / px_per_meter)` 公尺。
- `tools/build_scene.py` 讀 `meta.json` 換算場景包的 `size_m` 與 `origin_offset_m`。

---

## 檔案

| 檔案 | 角色 |
| --- | --- |
| `pipeline.py` | 一鍵編排 |
| `map_capture.py` | Google Static API 擷取 |
| `image_enhance.py` | Gemini 去車 + 銳化高清化；`--genai` 生圖（gemini／openai 雙供應商）|
| `measure_genai_drift.py` | 量生圖模型的幾何漂移（分塊相位相關）|
| `common.py` | 地點代號驗證 |
| `.env` | API keys（勿進版控） |
| `refs/` | genai 風格參考圖（road_style_ref.png） |
| `output/` | 各地點結果（gitignore） |
| `compare/` | 圖源比對圖（Esri vs Google、Apple vs Google） |
| `demo/` | 多地點範例對比圖（原圖 vs HD 處理後） |

---

## 範例（`demo/`）

5 個台灣路口的「原圖 vs HD 處理後」並排對比，示範 pipeline 換地點都能跑：
`taipei_sogo`（忠孝復興，斑馬線+車道箭頭）、`taipei_nanjing`（南京復興）、
`banqiao_xianmin`（板橋多線道）、`kaohsiung_wufu`（五福路口）、`chiayi_fountain`（嘉義噴水）。

> 選點經驗：座標要落在**真正的路口/路面**才有效；市中心地標常落在建物/停車場/公園。
> 用 zoom=21 時單張最大約 40m（1280px / 29px/m）。
