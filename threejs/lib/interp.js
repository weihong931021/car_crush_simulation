const lerp = (a, b, t) => a + (b - a) * t;

function lerpAngle(a, b, t) {
  let d = (b - a) % (2 * Math.PI);
  if (d > Math.PI) d -= 2 * Math.PI;
  if (d < -Math.PI) d += 2 * Math.PI;
  return a + d * t;
}

export function segHeading(wps, i) {
  const n = Math.min(i + 1, wps.length - 1);
  const p = Math.max(i - 1, 0);
  const dx = wps[n][1] - wps[p][1];
  const dz = wps[n][2] - wps[p][2];
  if (Math.abs(dx) < 1e-6 && Math.abs(dz) < 1e-6) return 0;
  return Math.atan2(dx, dz);
}

export function getState(wps, frame) {
  if (frame <= wps[0][0]) {
    return { x: wps[0][1], z: wps[0][2], h: wps[0][3] ?? segHeading(wps, 0) };
  }
  const last = wps[wps.length - 1];
  if (frame >= last[0]) {
    return { x: last[1], z: last[2], h: last[3] ?? segHeading(wps, wps.length - 1) };
  }
  for (let i = 0; i < wps.length - 1; i++) {
    const a = wps[i], b = wps[i + 1];
    if (frame >= a[0] && frame <= b[0]) {
      const t = (frame - a[0]) / (b[0] - a[0]);
      const dx = b[1] - a[1], dz = b[2] - a[2];
      const h = (a[3] != null && b[3] != null)
        ? lerpAngle(a[3], b[3], t)
        : (Math.abs(dx) < 1e-6 && Math.abs(dz) < 1e-6 ? segHeading(wps, i) : Math.atan2(dx, dz));
      return { x: lerp(a[1], b[1], t), z: lerp(a[2], b[2], t), h };
    }
  }
  return { x: last[1], z: last[2], h: last[3] ?? segHeading(wps, wps.length - 1) };
}
