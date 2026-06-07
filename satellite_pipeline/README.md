# satellite_pipeline — 衛星底圖自動化

事故地點經緯度 → 衛星圖 → 去車 + 銳化高清化 → 自動貼進 Blender 地板。
獨立模組，與 `trafficlab-project/`（上游軌跡推論）分開。

```text
lat/lon
  → [1] map_capture.py    Google Static API      → sat_raw.png + meta.json
  → [2] image_enhance.py  Gemini 去車 + 銳化      → sat_clean.png
  → [3] blender_ground.py 貼 Blender 地板(MCP)    → GroundPlane_{code}
```

全部輸出在 `output/{code}/`。

---

## 用法

```bash
# 設 key（擇一）：環境變數 或 satellite_pipeline/.env
#   GOOGLE_MAPS_KEY=...   (Static API)
#   GEMINI_API_KEY=...    (去車偵測)

# 一鍵全流程
python3 satellite_pipeline/pipeline.py \
    --lat 23.026901 --lon 120.249615 --code tainan_yongkang --size 25

# 第 3 步「自動貼進正在開的 Blender」由 Claude Code 透過 Blender MCP
# execute_blender_code 執行 output/{code}/blender_ground_{code}.py 完成。

# 單步 / 重跑
python3 satellite_pipeline/map_capture.py  --lat .. --lon .. --code ..
python3 satellite_pipeline/image_enhance.py --code .. --genai     # 出 HD 版 sat_genai.png
python3 satellite_pipeline/pipeline.py --code .. --skip-capture   # 只重新增強
python3 satellite_pipeline/pipeline.py --code .. --skip-enhance   # 用 raw 貼

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
| `output/{code}/blender_ground_{code}.py` | 貼地腳本（給 MCP 或手動） |

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

**B. HD 版 `sat_genai.png`（`--genai`）— Gemini 圖像生成清理 + 銳化（定案參數）**

- 模型 `gemini-3.1-flash-image`，**來源用 `sat_raw.png`**（比 sat_clean 銳利，Gemini 會順手去車）。
- `temperature=0.4`。prompt 三目標：
  1. **真實柏油路面**：自然中灰柏油色（不要太深、不要平塗），保留細微柏油質感像真馬路，
     不可變成死板的深色塊/剪影；整條路一致材質但乾淨（去髒污/補丁/輪胎痕）
  2. 道路輪廓（kerb / 路緣）銳利
  3. 既有標線保留但**不過度生成**：只留清楚可見的，渲成乾淨白色；不加粗、不增亮、不複製
- **不亂生規則**：模糊看不清的標線（機車停等格、看不清的箭頭）保持淡或省略，禁止 Gemini 猜/捏造/複製；
  只清理路面，不重畫建物/植被/人行道。
- **風格參考圖**（`--style-ref`，預設 `refs/road_style_ref.png`）：把真實空拍馬路一起餵給 Gemini，
  只借它的**柏油材質質感**（深、粗糙、銳利），不借它的標線/佈局。
- 較高 temperature（≥0.5）會幻想假道路/廣場/公園，故壓在 0.4。
- 視覺最佳（接近乾淨空拍圖），但正式輸出注意左下角殘留 Google 浮水印。

> 否決：用 Gemini 重畫整張且不限制 → 高 temperature 會畫出不存在的圓環/公園/斑馬線。

---

## 座標系（與 design doc 2026-06-01 一致）

- 平面左上角對齊世界 **(0,0,0)**，往 +X/+Y 延伸，與 `position_m` 軌跡同源。
- 平面尺寸 = `(img_w / px_per_meter) × (img_h / px_per_meter)` 公尺。
- Emission（unlit）材質 + `bpy.ops.uv.reset()`（不可用 unwrap，已知 bug）。

```python
# sat 像素 → Blender 世界座標
world_x = sat_x / px_per_meter
world_y = sat_y / px_per_meter
```

---

## 檔案

| 檔案 | 角色 |
| --- | --- |
| `pipeline.py` | 一鍵編排 |
| `map_capture.py` | Google Static API 擷取 |
| `image_enhance.py` | Gemini 去車 + 銳化高清化 |
| `blender_ground.py` | 產生 / 注入 Blender 貼地腳本 |
| `.env` | API keys（勿進版控） |
| `refs/` | genai 風格參考圖（road_style_ref.png） |
| `output/` | 各地點結果（gitignore） |
| `compare/` | 圖源比對圖 |
