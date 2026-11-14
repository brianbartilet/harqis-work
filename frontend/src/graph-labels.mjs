// Label placement uses screen pixels, so spacing stays readable at every zoom.
export function placeLabels(candidates, {width, height, zoom, fullTitles = false, obstacles = [], previous = new Map()}, measure) {
  const budget = fullTitles ? Infinity : Math.max(6, Math.min(120, Math.floor(width * height * (0.3 + Math.sqrt(zoom)) / 18000)));
  const placed = [];
  const ranked = candidates.filter(n => Number.isFinite(n.x) && Number.isFinite(n.y)
    && n.x >= 0 && n.x <= width && n.y >= 0 && n.y <= height
    && (fullTitles || n.emphasis || n.preferred || n.pinned || zoom >= (n.kind === 'entries' ? 2.5 : 0.8)))
    .sort((a,b) => Number(!!b.emphasis)-Number(!!a.emphasis) || Number(previous.has(b.id))-Number(previous.has(a.id)) || b.degree-a.degree
      || Number(!!b.pinned)-Number(!!a.pinned) || Number(b.preferred)-Number(a.preferred) || a.id.localeCompare(b.id));
  for (const node of ranked) {
    if (placed.length >= budget && !node.emphasis) continue;
    const suffix=node.labelSuffix||'';
    const text = !fullTitles && node.label.length > 34 ? node.label.slice(0,Math.max(8,32-suffix.length))+'…'+suffix : node.label;
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
    const old = previous.get(node.id);
    if (old && old.text === text && old.font === font) options.unshift({x:node.x+old.dx,y:node.y+old.dy});
    if (fullTitles) options.push(...options.map(b=>({x:Math.max(0,Math.min(width-w,b.x)),y:Math.max(0,Math.min(height-h,b.y))})));
    if (node.emphasis) options.push({x:Math.max(0,Math.min(width-w,node.x+gap)),y:Math.max(0,Math.min(height-h,node.y-h/2))});
    const collides = (b, p) => b.x < p.x+p.w+4 && b.x+w+4 > p.x && b.y < p.y+p.h+4 && b.y+h+4 > p.y;
    const box = options.find(b => b.x >= 0 && b.y >= 0 && b.x+w <= width && b.y+h <= height
      && !placed.some(p => collides(b,p)) && !obstacles.some(p => collides(b,p)));
    if (box) placed.push({...box,w,h,text,lines,font,node});
  }
  return placed;
}

// One shared clock owns passive relayout. Cached offsets follow moving orbs.
export function createLabelLayout() {
  let current = new Map(), outgoing = new Map(), nextUpdate = 0, lastKey, changedAt = -Infinity;
  let cameraKey, cameraUpdate = Infinity, fadeUntil = 0;
  const widths = new Map();
  // A lazy source plus resolver lets animation touch only displayed labels.
  return (candidates, viewport, measure, now, key, reducedMotion = false, resolveNode) => {
    if (viewport.cameraKey !== cameraKey) {
      cameraKey = viewport.cameraKey;
      cameraUpdate = now + 120;
    }
    let byId;
    const measured = (text, font) => {
      const key = JSON.stringify([font, text]);
      if (!widths.has(key)) {
        if (widths.size >= 4096) widths.clear();
        widths.set(key, measure(text, font));
      }
      return widths.get(key);
    };
    if (key !== lastKey || now >= nextUpdate || now >= cameraUpdate) {
      const source = typeof candidates === 'function' ? candidates() : candidates;
      if (!resolveNode) byId = new Map(source.map(node => [node.id,node]));
      const placed = placeLabels(source, {...viewport, previous:current}, measured);
      const next = new Map(); outgoing = new Map();
      for (const box of placed) {
        const old = current.get(box.node.id), dx=box.x-box.node.x, dy=box.y-box.node.y;
        const same = old && old.text===box.text && old.font===box.font && Math.abs(old.dx-dx)<0.5 && Math.abs(old.dy-dy)<0.5;
        next.set(box.node.id,{...box,dx,dy,fadeAt:same?old.fadeAt:now});
        if(old&&!same)outgoing.set(box.node.id,old);
      }
      for(const [id,box] of current)if(!next.has(id))outgoing.set(id,box);
      current=next;lastKey=key;nextUpdate=now+8000;changedAt=now;cameraUpdate=Infinity;
      fadeUntil = outgoing.size ? now+200 : 0;
      for (const box of current.values()) fadeUntil = Math.max(fadeUntil, box.fadeAt+400);
    }
    if (!resolveNode && !byId) byId = new Map(candidates.map(node => [node.id,node]));
    const elapsed=now-changedAt, result=[];
    const append=(box,alpha)=>{
      const node=resolveNode ? resolveNode(box.node.id) : byId.get(box.node.id);
      if(node&&alpha>0)result.push({...box,node,x:node.x+box.dx,y:node.y+box.dy,alpha});
    };
    if(!reducedMotion&&elapsed<200)for(const box of outgoing.values())append(box,1-elapsed/200);
    for(const box of current.values())append(box,reducedMotion?1:Math.max(0,Math.min(1,(now-box.fadeAt-200)/200)));
    if (elapsed>=200) outgoing.clear();
    result.nextUpdate=Math.min(nextUpdate,cameraUpdate);
    result.fadeUntil=reducedMotion?0:fadeUntil;
    return result;
  };
}
