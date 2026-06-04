# 下一步

## 優先做

- [ ] 寫 `blender-collision-physics` skill（固定碰撞物理公式 + Blender 5.x API 細節，避免每次重推）
- [ ] 測試斜角碰撞（T-bone、追尾偏轉）：用自然語言描述碰撞角度，驗證力分量計算是否正確
- [ ] 測試 Track A 軌跡輸入格式 `[(frame, x, y, heading_deg)]` 注入 Blender 場景

## 之後

- [ ] 寫 `blender-scene-setup` skill（清場、下載模型、複製 hierarchy 標準流程）
- [ ] 寫 `blender-vehicle-motion` skill（沿軌跡移動、啟動/停止曲線）
- [ ] 多車、行人、障礙物複雜場景測試

## 已知坑（勿忘）

- Blender 5.x layered action：`action.layers[0].strips[0].channelbag(slot).fcurves`
- 複製 hierarchy：要先 `select children_recursive` 再 duplicate
- **Tesla Model 3 前端朝 +Y**（本地座標）→ 正面對撞：靜止車 Z-rot=180°，撞擊車 Z-rot=0°
- 斜角碰撞後有旋轉：角動量 = F × 力臂，轉動慣量 ≈ 1/12 × m × L²
