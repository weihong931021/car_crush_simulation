# 下一步

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
- [x] 第二場景驗證（satellite_pipeline 既有地點 + 合成軌跡，`tools/synth_trajectory.py` +
  `scenes/tainan_yongkang/`，換場景零程式碼修改驗證通過）
- 第二階段：Blender 讀 scene.json 自動搭渲染場景（出版用高品質畫面）

## Track A：衛星圖自動化 pipeline（→ `satellite_pipeline/` 模組，✅ 已完成）

### 已完成（2025-06）

- **圖源鎖定**：Google Maps Static API `zoom=21 scale=2` = 29 px/m（此地點上限）
  - 全部來源實測過：Esri 台南無資料（舊 pipeline 用的，z19 僅 3.6px/m 糊 8 倍）、
    Bing/Earth KH/NLSC 皆不可用。換不同 Google API 不會更清楚（同一份底圖）
- **去車 + 增強定案**：Gemini 偵測 bbox + cv2 inpaint + PIL 銳化
  - 否決 Gemini 重畫整張（會幻想假道路/標線）
- **`satellite_pipeline/` 一鍵流程已完成並驗證**：
  `pipeline.py --lat --lon --code` → sat_raw → sat_clean(去車) → 自動貼 Blender
  - 台南永康點端到端通過（去 24 台車、GroundPlane 25×25m @ 29px/m）
- 詳細決策見 `satellite_pipeline/README.md`
- 圖源比對：`satellite_pipeline/compare/source_compare.png`

### 待辦（微調）

- [x] genai prompt 定案：真實深柏油 + 粗糙質感 + 標線最小化 + 風格參考圖（refs/road_style_ref.png，借柏油材質）（temp 0.4, raw 來源）
- [x] 多地點範例：`satellite_pipeline/demo/` 5 個台灣路口原圖 vs HD 對比圖
- [x] Codex 審查 #1 修正：`build_blender_code` 加 variant（auto>genai>clean>raw）；map_capture 重抓時清除過時 sat_clean/sat_genai（修「新地形配舊圖」bug）
- [ ] Codex 審查 #2（待軌跡接入時驗）：`uv.reset()` 沒明確指定哪個 UV 角=世界原點，image-y-down 映射是隱性的，衛星圖可能上下相反
- [x] Codex 審查 #3：px_per_meter 是「此緯度」專屬非通用常數（README 已註明「此地點 29px/m」）
- [x] Apple Maps 評估：網頁嵌入版 zoom 鎖死約 3.6px/m，不如 Google，維持現狀
- [ ] （選配）需更高解析度時，手動從 NLSC（maps.nlsc.gov.tw）截圖的標準流程
- 註：舊版 `trafficlab-project/scripts/{map_capture,image_enhance,blender_ground,
  pipeline_mapground}.py`（Esri 版）已被 `satellite_pipeline/` 取代

## Track B：TrafficLab 偵測優化（❄️ 凍結，隊友主導）

- [x] VisDrone 訓練完成（Colab 50 epochs，mAP50=0.400）→ 模型已放 `trafficlab-project/models/yolo11l-visdrone-ft.pt`
- [x] 測試 VisDrone 對機車偵測效果：二輪 ×21、汽車信心 +0.03，驗收見 `detection_tests/`
- 以下轉隊友，不在本 repo 追蹤：Kalman filter、輪胎辨識、Motorcycle 濾波器啟用、
  inference_config.yaml weights 更新（現指向不存在的舊檔，跑推論前需改指新模型）

## Track C：Blender 碰撞動畫（→ 退居出版渲染，第二階段）

- [ ] 第二階段：Blender 讀 `scene.json` 自動搭渲染場景（地面 + 車輛 + 軌跡動畫）
- [ ] 寫 `blender-collision-physics` skill（固定碰撞物理公式 + Blender 5.x API 細節，避免每次重推）
- [ ] 測試斜角碰撞（T-bone、追尾偏轉）：用自然語言描述碰撞角度，驗證力分量計算是否正確
- 註：MODEL_FLIP 待辦已併入主線；`archive/blender_scripts/` 為淘汰腳本（rigid body 版 setup_crash 等）

## 之後

- [ ] 寫 `blender-scene-setup` skill（清場、下載模型、複製 hierarchy 標準流程）
- [ ] 寫 `blender-vehicle-motion` skill（沿軌跡移動、啟動/停止曲線）
- [ ] 多車、行人、障礙物複雜場景測試

## 已知坑（勿忘）

- Blender 5.x layered action：`action.layers[0].strips[0].channelbag(slot).fcurves`
- 複製 hierarchy：要先 `select children_recursive` 再 duplicate
- **Tesla Model 3 前端朝 +Y**（本地座標）→ 正面對撞：靜止車 Z-rot=180°，撞擊車 Z-rot=0°
- 斜角碰撞後有旋轉：角動量 = F × 力臂，轉動慣量 ≈ 1/12 × m × L²
