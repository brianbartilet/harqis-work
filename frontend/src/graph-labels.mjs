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
    const old = previous.get(node.id);
    if (old && old.text === text && old.font === font) options.unshift({x:node.x+old.dx,y:node.y+old.dy});
    if (fullTitles) options.push(...options.map(b=>({x:Math.max(0,Math.min(width-w,b.x)),y:Math.max(0,Math.min(height-h,b.y))})));
    if (node.emphasis) options.push({x:Math.max(0,Math.min(width-w,node.x+gap)),y:Math.max(0,Math.min(height-h,node.y-h/2))});
    const box = options.find(b => b.x >= 0 && b.y >= 0 && b.x+w <= width && b.y+h <= height
      && ![...placed,...obstacles].some(p => b.x < p.x+p.w+4 && b.x+w+4 > p.x && b.y < p.y+p.h+4 && b.y+h+4 > p.y));
    if (box) placed.push({...box,w,h,text,lines,font,node});
  }
  return placed;
}

// One shared clock owns passive relayout. Cached offsets follow moving orbs.
export function createLabelLayout() {
  let current = new Map(), outgoing = new Map(), nextUpdate = 0, lastKey, changedAt = -Infinity;
  return (candidates, viewport, measure, now, key, reducedMotion = false) => {
    const byId = new Map(candidates.map(node => [node.id,node]));
    if (key !== lastKey || now >= nextUpdate) {
      const placed = placeLabels(candidates, {...viewport, previous:current}, measure);
      const next = new Map(); outgoing = new Map();
      for (const box of placed) {
        const old = current.get(box.node.id), dx=box.x-box.node.x, dy=box.y-box.node.y;
        const same = old && old.text===box.text && old.font===box.font && Math.abs(old.dx-dx)<0.5 && Math.abs(old.dy-dy)<0.5;
        next.set(box.node.id,{...box,dx,dy,fadeAt:same?old.fadeAt:now});
        if(old&&!same)outgoing.set(box.node.id,old);
      }
      for(const [id,box] of current)if(!next.has(id))outgoing.set(id,box);
      current=next;lastKey=key;nextUpdate=now+8000;changedAt=now;
    }
    const elapsed=now-changedAt, result=[];
    const append=(box,alpha)=>{
      const node=byId.get(box.node.id);
      if(node&&alpha>0)result.push({...box,node,x:node.x+box.dx,y:node.y+box.dy,alpha});
    };
    if(!reducedMotion&&elapsed<200)for(const box of outgoing.values())append(box,1-elapsed/200);
    for(const box of current.values())append(box,reducedMotion?1:Math.max(0,Math.min(1,(now-box.fadeAt-200)/200)));
    result.nextUpdate=nextUpdate;
    result.fadeUntil=reducedMotion?0:Math.max(outgoing.size?changedAt+200:0,...[...current.values()].map(box=>box.fadeAt+400));
    return result;
  };
}
