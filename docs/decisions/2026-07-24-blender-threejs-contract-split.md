# 決策：Blender 與 Three.js 的車規／座標契約分裂

日期：2026-07-24（記錄分裂）→ **2026-08-05 解決（移除 Blender）**
狀態：**已解決**

## 背景

程式碼審查（2026-07-24）發現同一場事故在 Blender 出版路徑與 Three.js 播放器路徑上，用的是
**不同的車輛尺寸與不同的座標原點約定**。兩邊各自內部一致、當時都能跑，所以不是會當掉的
bug，而是契約債務——它會在「Blender 讀同一份 scene.json 搭渲染場景」（原第二階段）那一刻爆開。

當時的決定是**延後統一**到第二階段。**2026-08-05 專案全面轉 Three.js 網頁渲染、移除整條
Blender 工具鏈，這個分裂因此直接消失**——不再有第二個消費端，兩個問題都不需要「統一」，
而是「另一半來源被刪掉」。以下保留原分析為記錄，並標註解決方式。

## 一、車輛尺寸曾有多個來源 → 現只剩一份

| 來源 | Car 長×寬 (m) | Two_Wheeler 長×寬 (m) | 現況 |
| --- | --- | --- | --- |
| `tools/build_scene.py` `CLASS_DEFAULTS` → `scenes/*/scene.json` | 4.69 × 1.85 | 1.85 × 0.70 | **保留＝唯一真相**（Three.js 物理讀這份） |
| `blender_scripts/vehicle_specs.py` | 3.8 × 1.8 | 1.7 × 0.6 | **已刪**（隨 Blender 移除） |
| `threejs/models/registry.json` `length_m` | 4.77 | 1.42 | 保留但執行期不讀（GLB 原生量測值，只作記錄） |

**解決**：`vehicle_specs.py` 已刪除，尺寸真相只剩 `scenes/*/scene.json` 的
`length_m`/`width_m`（`scene-loader.js` 驗證，`main.js` OBB 與 scale-to-length 讀取）。
分裂消失。日後 SUV/Van/Truck/Bus 若要細分尺寸，在 `CLASS_DEFAULTS` 補列即可
（目前都 fallback 到 car.glb）。

## 二、座標原點約定曾有三套 → 現只剩一套

| 來源 | 約定 | 現況 |
| --- | --- | --- |
| `satellite_pipeline/blender_ground.py` | 平面左上角對齊 (0,0,0)，+X/+Y，無置中、無 Y 反向 | **已刪** |
| `docs/reference.md` 的 Blender 公式 | 置中位移 **+ Y 反向** | **已刪**（遺留物，現行路徑本就不用它擺車） |
| Three.js（`scene.json` `origin_offset_m` → `main.js`/`waypoints.js`） | 置中位移、不反向（south = +Z） | **保留＝唯一約定** |

**解決**：兩套 Blender 座標約定的檔案都已刪除，只剩 Three.js 的 `origin_offset_m` 置中約定
（`scene.json` ↔ `waypoints.js` ↔ `reference.md` 的 JS 公式一致、自洽）。原本「Blender 那兩套
彼此就不一致」的隱患隨檔案移除消失。

## 三、一併記錄的觀察（Blender 相關者已隨移除失效）

- **`px_per_meter` 兩條路徑算法不同但結果一致**：`image_enhance` 2x 放大後只補 `enhanced_px`，
  沒更新 `px_per_meter`。當時 `blender_ground` 用 raw 分子除 raw 分母得 25.0m、`build_scene`
  用實際 PNG 寬重算 40.96px/m，兩者實體尺寸都正確。**Blender 那條已不存在**；`build_scene`
  的重算路徑保留且正確。這也駁回了審查「解析度不一致會讓地板尺度錯」的主張。
- **非方形 genai 輸出會拉伸地板貼圖**：這是 `blender_ground` 平面長寬比取自 meta 的問題，
  **已隨該檔刪除失效**。（Three.js 端無此問題。）
- **Gemini 產物沒有可稽核的 provenance**：`meta.json` 只記 `vehicles_removed` 與 `enhanced_px`，
  沒記模型版本/prompt/temperature/hash。此觀察**仍成立**（與 Blender 無關），列為 todonext。
- **輸出寫入非原子**：`map_capture`／`build_scene` 的多檔寫入無 temp+rename，中途失敗留混合
  狀態。此觀察**仍成立**，列為 todonext。
