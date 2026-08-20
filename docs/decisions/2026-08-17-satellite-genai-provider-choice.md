# 決定：衛星底圖生圖改成雙供應商，預設仍是 Gemini

日期：2026-08-17　範圍：`satellite_pipeline/image_enhance.py` 的 `genai_enhance()`

> **一句話**：使用者給了 OpenAI key 要求把生圖那半換過去，換完發現 `gpt-image-2` 把幾何
> 搬得比 `gemini-3.1-flash-image` 更遠（0.30 m vs 0.20 m）。改成 `--genai-provider`
> 雙供應商、**預設留在 Gemini**。順帶把「HD 底圖只能人眼確認」這個長年缺口變成可量測的數字。

## 狀態

| 項目 | 狀態 |
|---|---|
| `--genai-provider {gemini,openai}` 雙供應商 | ✅ 已實作，預設 `gemini` |
| OpenAI 端 `gpt-image-2` + `plan_genai_size()` 尺寸協商 | ✅ 已實作 |
| 兩家產出都縮回來源原尺寸 | ✅ 已實作（原本 Gemini 會吐 1024×1024） |
| `genai_enhance()` 回寫 meta.json | ✅ 已實作（provider/model/size/cost） |
| 漂移量測腳本 `measure_genai_drift.py` | ✅ 新增，數字可重跑 |
| 單元測試 `tests/test_genai_size.py` | ✅ 6 測，satellite_pipeline 共 26 測全綠 |

**沒有改變的結論**：`--genai` 依然**不可用於 `--input` 座標關鍵路徑**，CLI 照舊擋下。
換供應商沒有讓它變安全，只是量清楚了不安全的程度。

---

## 一、起因

使用者提供 OpenAI 專案 service account key（`sk-svcacct-`，$50 credit），要求
「把生圖的那組 API 換成 OpenAI，挑一個 CP 值高的模型」。

先釐清這個 repo 裡「生圖」是哪一半——`image_enhance.py` 用了兩支 API 但只有一支在生圖：

```text
GEMINI_API_KEY → detect_vehicles()  gemini-2.5-flash 只回 bbox JSON      ← 不是生圖，沒動
OPENAI_API_KEY → genai_enhance()    重畫整張做 HD 化                      ← 這半才是
```

---

## 二、OpenAI 端選型：不是價格決定的，是尺寸

| 模型 | 輸出尺寸 | 判定 |
|---|---|---|
| `gpt-image-1-mini` | 只有 1024×1024 / 1024×1536 / 1536×1024 | ❌ 衛星圖不是這三種比例，送進去必被壓扁 |
| `gpt-image-1` | 同上三種，且更貴 | ❌ |
| **`gpt-image-2`** | 任意（16 倍數、長邊 ≤3840、比例 ≤3:1、總像素 655,360–8,294,400） | ✅ |

`gpt-image-1-mini` 的 token 單價便宜 4 倍（$8 vs $30 / 1M output），但**長寬比一變
`px_per_meter` 就失效**，車輛位置整個錯位。這條約束直接淘汰它，價格沒有參與決策。

`plan_genai_size()` 負責協商合法畫布（比例誤差 <1%），拿回圖後縮回來源原尺寸。

### 成本（1280×1280 + 一張風格參考圖，實測）

| quality | 輸入（幾乎固定） | 輸出 | 合計 | $50 可跑 |
|---|---|---|---|---|
| `low` | $0.0263 | $0.0070 | **$0.033** | ~1,500 張 |
| `medium` | $0.0263 | $0.0629 | **$0.089** | ~560 張 |
| `high` | $0.0263 | ~$0.25（外推） | ~**$0.28** | ~175 張 |

**輸入那份不隨 quality 變**——`gpt-image-2` 一律以 high fidelity 讀輸入圖，
所以降 quality 省不到一半。低估這點會以為 `low` 有官網說的 $0.006，實際是 $0.033。

---

## 三、量測方法

原本「HD 底圖無自動驗收，只能人眼確認」。人眼看不出 0.2 m 和 0.3 m 的差別，
也分不清「整張圖平移了」（可校正）和「內容被改寫了」（不可救）。

`satellite_pipeline/measure_genai_drift.py`：把兩張圖切成 128px 方塊，逐塊相位相關求位移。

```bash
python3 satellite_pipeline/measure_genai_drift.py --code tainan_yongkang
```

| 指標 | 意義 |
|---|---|
| 位移中位數 | 該塊結構被搬了多遠（÷ `px_per_meter` = 公尺） |
| 對位信心 | 低 ＝ 該塊根本對不上，結構已被改寫 |
| 全域相關 | 整張圖的結構相似度 |

---

## 四、結果

同一張 `tainan_yongkang/sat_raw.png`（728×728 @29.11 px/m）、同 prompt、同風格參考圖：

| 路徑 | 位移中位數 | >10px 區塊 | 對位信心 | 全域相關 |
|---|---|---|---|---|
| `sat_clean`（忠實路徑，不生圖） | **0.00 m** | 0% | 0.975 | **0.968** |
| `gemini-3.1-flash-image`（6/8 舊產物） | **0.20 m** | 37% | 0.167 | **0.876** |
| `gemini-3.1-flash-image`（8/17 重跑） | **0.21 m** | 39% | — | **0.854** |
| `gpt-image-2`（medium） | **0.30 m** | 47% | 0.081 | **0.746** |

Gemini 兩次獨立跑（相隔兩個月）都落在 0.20–0.21 m，不是運氣。

> ⚠ **不要用跨場景數字比較**。先前拿 `webtest_claude`（gpt-image-2, 21.0 px）對比
> `tainan_yongkang`（Gemini, 5.0 px）得到「差 4 倍」的結論是錯的——那是場景難度差異
> （webtest_claude 有高架橋、多層結構）。鎖定同一張來源圖後真實差距是 0.20 vs 0.30 m。

---

## 五、診斷：是內容被改寫，不是取景跑掉

如果只是整張圖平移縮放，理論上可以校正回來。對 `gpt-image-2` 的產物擬合最佳全域仿射：

```text
收斂：相關度 0.417，推出縮放 ≈1.050、平移 ≈(−33.7, −30.8) px
對齊後殘餘位移：21.0 px → 17.7 px（>10px 仍佔 80.6%）
```

**扣掉全域變換只降了 16%**。剩下的是逐塊各走各的，沒有單一變換能修——內容確實被重畫。

---

## 六、為什麼 prompt 救不了（三條路都試過／查過）

1. **加強 prompt**：現行 prompt 已經寫了 `Keep the EXACT same road layout, shapes and
   positions of every road, kerb, building, tree and structure`，模型照樣重畫。
   生成式模型是「重新畫一張像它的圖」，不是「修這張圖的像素」。
2. **用 `mask` 局部修圖**：官方文件明講 —— *"the entire image is regenerated rather than
   preserving unmasked pixels exactly. The model uses the mask as guidance, but may not
   follow its exact shape with complete precision."* 遮罩只是提示，不保證。
3. **調 `input_fidelity`**：對 `gpt-image-2` **不可調** —— *"the API doesn't allow changing
   it because the model processes every image input at high fidelity automatically."*
   已經在最高了。

結論：這是 API 的類別性質，不是可調參數。

---

## 七、決定

- `--genai-provider` 雙供應商，**預設 `gemini`**（實測較忠於原圖，且符合使用者長期使用經驗
  「路不會被亂砍亂生」）
- `openai` 保留為可選路徑，`OPENAI_API_KEY` 已配置，一個旗標切換
- `--genai-quality` 僅 `openai` 有效；Gemini 端固定 `temperature=0.4`（維持原定案參數，
  ≥0.5 會幻想假道路/廣場/公園）
- **承載座標的地面圖一律走 `sat_clean`**（實測 0.00 m）。生圖兩條路都只適合當示意圖

```bash
python3 satellite_pipeline/image_enhance.py --code <code> --genai                    # Gemini（預設）
python3 satellite_pipeline/image_enhance.py --code <code> --genai --genai-provider openai --genai-quality low
```

---

## 八、過程中修掉的真 bug

重構成雙供應商時把 client 寫成臨時物件：

```python
resp = genai.Client(api_key=key).models.generate_content(...)   # ✗
```

請求還沒發完，`Client` 就被 GC，底層 httpx 被關閉，拋
`RuntimeError: Cannot send a request, as the client has been closed.`
必須綁在區域變數上讓它活過整個請求。OpenAI 端同樣處理。

**單元測試抓不到這個**（不碰網路），只有實跑會現形——與 `verify_scenes.mjs` 存在的理由相同。

---

## 九、可重跑

```bash
# 產圖（兩家各一張，用同一張來源）
cp satellite_pipeline/output/tainan_yongkang/{sat_raw.png,meta.json} satellite_pipeline/output/ab_gem/
cp satellite_pipeline/output/tainan_yongkang/{sat_raw.png,meta.json} satellite_pipeline/output/ab_oai/
python3 satellite_pipeline/image_enhance.py --code ab_gem --genai --genai-provider gemini
python3 satellite_pipeline/image_enhance.py --code ab_oai --genai --genai-provider openai --genai-quality medium

# 量漂移
python3 satellite_pipeline/measure_genai_drift.py --code ab_gem
python3 satellite_pipeline/measure_genai_drift.py --code ab_oai
```

註：分塊邊長會影響絕對數字（`--tile 128` 對 728px 圖只切出 25 塊、`--tile 91` 切 64 塊），
**比較時務必固定 `--tile`**。上表用 91，`--code` 模式預設 128。

---

## 後記（2026-08-20）

兩件與本決定相關的後續，不改變本決定的量測結論：

1. **非確定性加碼**：同一張 sat_raw、同 prompt（sharp + gemini）連跑兩次，漂移
   0.04 m／22% 與 0.40 m／56%（>10px 區塊佔比）——生圖不只有誤差，而且**每次都不
   一樣**，事前無從得知。
2. **handoff 政策改動**：`/api/handoff` 改為交付「使用者在 ① 當下看的那張」
   （variant 隨 `S.tab`；沒指定仍 sat_clean → sat_raw、不自動挑 genai）。使用者以
   觀感優先明示選 genai 時放行，出處寫進 sat_meta（`geometry: rewritten_by_genai`）。
   「只能標 sat_clean」從硬約束改為預設值＋明示例外，理由與代價見
   `docs/specs/2026-08-16-web-onboarding-flow-design.md`「交給 ③ 標註的底圖」節。
