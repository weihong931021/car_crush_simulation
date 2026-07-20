// 原始偵測幀 ↔ 動畫幀對映（碰撞幀對齊，前後段各自線性）。
export function makeFrameMapper(f) {
  return function origToAnim(orig) {
    if (orig <= f.source_collision) {
      const t = (orig - f.source_start) / (f.source_collision - f.source_start);
      return f.anim_start + t * (f.anim_collision - f.anim_start);
    }
    const t = (orig - f.source_collision) / (f.source_end - f.source_collision);
    return f.anim_collision + t * (f.anim_end - f.anim_collision);
  };
}
