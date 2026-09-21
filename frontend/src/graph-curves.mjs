// ForceGraph uses curvature * distance as the quadratic control-point offset.
// Keep long connections subtle and ease the bend when orbs nearly touch.
export function boardCurvature(link, zoom = 1, lane = 0) {
  const a = link.source, b = link.target;
  if (![a?.x,a?.y,b?.x,b?.y,zoom].every(Number.isFinite) || zoom <= 0) return 0;
  const distance = Math.hypot(b.x-a.x,b.y-a.y)*zoom;
  if (!distance) return 0;
  const clearance = Math.max(0,distance-(a.radius||0)-(b.radius||0));
  const bend = Math.min(64,clearance*.24);
  // Reversing a relationship should not flip its visual route.
  const orientation = String(a.id)<String(b.id)?1:-1;
  return orientation*(bend/distance+lane*.16);
}
