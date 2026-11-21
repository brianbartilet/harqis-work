// Orb artwork is fixed in screen pixels; reuse it as positions and zoom change.
export function createOrbPainter() {
  const cache = new Map();
  return (ctx, node, scale, ink, statusInk, emphasis) => {
    const ratio = Math.min(2, Math.max(1, globalThis.devicePixelRatio || 1));
    const radius = node.radius;
    const key = JSON.stringify([radius, ink, statusInk, !!emphasis, ratio]);
    let sprite = cache.get(key);
    if (!sprite) {
      const extent = Math.ceil(Math.max(emphasis ? 30 : 18, radius + 6) + 1);
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = Math.ceil(extent * 2 * ratio);
      const paint = canvas.getContext('2d');
      paint.scale(ratio, ratio);paint.translate(extent, extent);
      const glow = paint.createRadialGradient(0, 0, 0, 0, 0, emphasis ? 30 : 18);
      glow.addColorStop(0, (statusInk || ink) + (emphasis ? '75' : '35'));
      glow.addColorStop(1, (statusInk || ink) + '00');
      paint.fillStyle = glow;paint.beginPath();paint.arc(0, 0, emphasis ? 30 : 18, 0, 2 * Math.PI);paint.fill();
      const fill = paint.createRadialGradient(-radius * .3, -radius * .4, 0, 0, 0, radius * 1.6);
      fill.addColorStop(0, '#effbff');fill.addColorStop(.3, ink);fill.addColorStop(1, ink + '70');
      paint.beginPath();paint.arc(0, 0, radius, 0, 2 * Math.PI);paint.fillStyle = fill;paint.fill();
      paint.strokeStyle = ink;paint.lineWidth = .8;paint.stroke();
      if (statusInk) {
        paint.beginPath();paint.arc(0, 0, radius + 2, 0, 2 * Math.PI);
        paint.strokeStyle = statusInk;paint.lineWidth = 1.5;paint.stroke();
      }
      if (emphasis) {
        paint.beginPath();paint.arc(0, 0, radius + 5, 0, 2 * Math.PI);
        paint.strokeStyle = ink + 'aa';paint.lineWidth = 1;paint.stroke();
      }
      sprite = {canvas, extent};
      if (cache.size >= 256) cache.delete(cache.keys().next().value);
      cache.set(key, sprite);
    }
    const extent = sprite.extent / scale;
    ctx.drawImage(sprite.canvas, node.x - extent, node.y - extent, extent * 2, extent * 2);
  };
}
