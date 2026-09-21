// Label placement uses screen pixels, so spacing stays readable at every zoom.
export function placeLabels(candidates, {width, height, zoom, fullTitles = false, obstacles = []}, measure) {
  const budget = fullTitles ? Infinity : Math.max(6, Math.min(120, Math.floor(width * height * (0.3 + Math.sqrt(zoom)) / 18000)));
  const placed = [];
  const ranked = candidates.filter(n => Number.isFinite(n.x) && Number.isFinite(n.y)
    && n.x >= 0 && n.x <= width && n.y >= 0 && n.y <= height
    && (fullTitles || n.emphasis || n.preferred || n.pinned || zoom >= (n.kind === 'entries' ? 2.5 : 0.8)))
    .sort((a,b) => Number(!!b.emphasis)-Number(!!a.emphasis) || b.degree-a.degree
      || Number(!!b.pinned)-Number(!!a.pinned) || Number(b.preferred)-Number(a.preferred) || a.id.localeCompare(b.id));
  for (const node of ranked) {
    if (placed.length >= budget && !node.emphasis) continue;
    const text = !fullTitles && node.label.length > 34 ? node.label.slice(0,32)+'…' : node.label;
    const font = node.emphasis ? 14 : 12, lines = [];
    if (fullTitles) {
      const maxWidth = Math.max(40, Math.min(240, width - 24));
      let line = '';
      for (const word of text.split(/\s+/)) {
        if (line && measure(line + ' ' + word, font) > maxWidth) { lines.push(line); line = ''; }
        for (const char of (line ? ' ' : '') + word) {
          if (line && measure(line + char, font) > maxWidth) { lines.push(line); line = ''; }
          line += char;
        }
      }
      if (line) lines.push(line);
    } else lines.push(text);
    const w = Math.max(...lines.map(line => measure(line, font)), 0) + 12, h = lines.length * 16 + 8, gap = node.radius + 8;
    const options = [
      {x:node.x+gap,y:node.y-h/2}, {x:node.x-gap-w,y:node.y-h/2},
      {x:node.x-w/2,y:node.y-gap-h}, {x:node.x-w/2,y:node.y+gap}
    ];
    if (fullTitles) options.push(...options.map(b=>({x:Math.max(0,Math.min(width-w,b.x)),y:Math.max(0,Math.min(height-h,b.y))})));
    if (node.emphasis) options.push({x:Math.max(0,Math.min(width-w,node.x+gap)),y:Math.max(0,Math.min(height-h,node.y-h/2))});
    const box = options.find(b => b.x >= 0 && b.y >= 0 && b.x+w <= width && b.y+h <= height
      && ![...placed,...obstacles].some(p => b.x < p.x+p.w+4 && b.x+w+4 > p.x && b.y < p.y+p.h+4 && b.y+h+4 > p.y));
    if (box) placed.push({...box,w,h,text,lines,font,node});
  }
  return placed;
}
