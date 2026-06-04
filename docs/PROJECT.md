# 行車事故影片重建 3D 模型

## 專案目標

將路人手機影片、低畫質監控等碎片化素材，利用 AI 快速重建為 3D 碰撞動畫，生成第一視角重現影片。

**核心用途**：協助釐清責任歸屬、為新聞報導提供事實根據、輔助司法判決。

---

## 現階段做法（2025-05）

### 整體架構

```
真實事故影片
    │
    ├── [Track A] 軌跡提取（陳柏衡）
    │       影片 → 2D 路線軌跡 → 車輛位置/速度序列
    │       現況：80% 可行，需優化影片品質與路徑線性化
    │
    └── [Track B] 碰撞場景重建（本專案核心）
            自然語言描述碰撞規格
                → Claude Code + Blender MCP
                → 下載 3D 車輛模型（Sketchfab）
                → 生成碰撞動畫腳本
                → Blender 渲染輸出
```

### Track B 技術細節

**工具鏈**：Claude Code CLI → Blender MCP (`blender-mcp` port 9876) → Blender 5.x Python API

**已驗證可行**：
- 透過 Sketchfab 直接下載指定車型（Tesla Model 3 UID: `5ef9b845aaf44203b6d04e2c677e444f`）
- 正確複製整個物件 hierarchy（301 個子物件），非僅複製根節點
- 純 Y 軸正面碰撞動畫：等速接近 → 碰撞衝量 → 摩擦減速
- 物理正確：垂直撞擊無側向位移、無旋轉
- 在 3-4 次對話內完成完整 demo

**已踩過的坑**（Gemini 失敗點，Claude 已解決）：
- 搜尋 Tesla Model 3 卻跑出 Cybertruck → 需指定 Sketchfab UID
- Z 軸旋轉 180° 指令執行失敗 → 用 `math.radians(180)` 精確指定
- linked duplicate 只複製根物件，子物件不跟 → 需 select all children 再 duplicate
- **Tesla Model 3 前端在本地 +Y 方向**（非 -Y）→ 正面對撞設定：靜止車 Z-rot=180°（前端朝 -Y），撞擊車 Z-rot=0°（前端朝 +Y），從 Y=-15 往 +Y 推進
- **Sketchfab 匯入的根物件旋轉模式是 QUATERNION**，設定 `rotation_euler` 無效 → 須先 `obj.rotation_mode = 'XYZ'` 再設 euler，或直接設 `rotation_quaternion`
- Blender 5.x Action API 改版 → 用 `action.layers[0]` layered action 存取 fcurves

---

## Skills 規劃

### 1. `blender-collision-physics`（優先）
碰撞場景生成的物理規則，讓 Claude 不用每次重新推導：

- **垂直碰撞**：只有衝擊方向（Y 軸）有力，X/Z 無側向位移，無旋轉
- **斜角碰撞**：力的分量計算、碰撞角度 → 偏轉角度換算
- **動量傳遞**：靜止車被撞後初速 ≈ 撞擊車速 × 質量比
- **關鍵幀曲線**：接近段 LINEAR，衝量段 2-3 幀急劇，摩擦段漸近停止
- **Blender 5.x 注意事項**：layered action API、hierarchy duplicate 方法

### 2. `blender-vehicle-motion`
車輛啟動/停止/沿軌跡移動的規則：

- 啟動：0 → 最高速（慢到快，Ease-in）
- 停止：最高速 → 0（快到慢，Ease-out + 摩擦力）
- 轉彎時速度自動降低
- Track A 軌跡輸入格式：`[(frame, x, y, heading_deg)]` 序列

### 3. `blender-scene-setup`
場景初始化標準流程：

- 清除預設 Cube、保留 Camera/Light
- 從 Sketchfab 下載車型（維護常用車型 UID 表）
- 正確複製 hierarchy 的方法
- 地面、燈光、攝影機基本配置

---

## Agents 策略

**適合並行的任務（可用 agents）**：
1. **多場景並行**：同一起事故，同時生成「正面視角」和「俯視視角」兩個版本的場景腳本
2. **Track A + Track B 並行**：軌跡計算和場景初始化同時進行，軌跡完成後再注入場景

**不適合並行的任務**：
- 同一個 Blender session 內的步驟（sequential，共用 MCP 連線狀態）
- 模型下載 → 複製 → 設定動畫（有先後依賴）

---

## 競品分析摘要

| 競品 | 優勢 | 劣勢 |
|------|------|------|
| Forensic Architecture | 學術公信力強 | 成本高、速度慢（1-2個月） |
| SITU Research | Space-Timeline 完整 | 需專業團隊 |
| NYT Visual Investigations | 手動 Blender 功夫扎實 | 無自動化，難複製 |
| Amped FIVE / TEMA | 0.01px 追蹤精度 | 主要用於工業/軍事鑑識 |
| D4RT (Google DeepMind) | 2D→3D 即時查詢 | 研究階段，非產品 |

**我們的差異化**：碎片化素材（手機、監控）+ AI 自動化 + 數小時內產出，針對新聞媒體速度需求。

---

## 已知風險與待驗證

| 項目 | 狀態 | 風險等級 |
|------|------|----------|
| 直線正面碰撞重建 | ✅ 已驗證 | 低 |
| 斜角碰撞（T-bone、追尾偏轉）| ⏳ 未測試 | 中 |
| Track A 軌跡 → Blender 路徑整合 | ⏳ 未測試 | 中 |
| 複雜場景（多車、行人、障礙物）| ⏳ 未測試 | 高 |
| FoundationPose 碰撞後車體變形重建 | ❌ 技術限制 | 高（考慮 Dynamic 3DGS） |
| 整體品質依賴 Claude 模型表現 | ⚠️ 已知限制 | 中（現階段可控） |

---

## 常用資源

**Sketchfab 車型 UID**：
- Tesla 2018 Model 3：`5ef9b845aaf44203b6d04e2c677e444f`（684K faces，CC Attribution）

**MCP 連線**：`uvx blender-mcp --port 9876`（已設定在 `~/.claude.json` user scope）

**Blender 版本**：5.1.1
