// Persist only view state, never fetched activity content or authentication data.
export function readGraphState(storage,key){
  try {
    const s=JSON.parse(storage.getItem(key));
    if(s?.version!==1||!s.filters||!Array.isArray(s.enabled)||!Array.isArray(s.sources))return null;
    const point=p=>p&&Number.isFinite(p.x)&&Number.isFinite(p.y)&&Math.abs(p.x)<1e7&&Math.abs(p.y)<1e7;
    s.positions=Object.fromEntries(Object.entries(s.positions||{}).filter(([id,p])=>point(p)).slice(0,10000));
    if(!point(s.viewport)||!Number.isFinite(s.viewport.zoom)||s.viewport.zoom<=0||s.viewport.zoom>1000)s.viewport=null;
    s.enabled=s.enabled.filter(v=>typeof v==='string');s.sources=s.sources.filter(v=>typeof v==='string');
    return s;
  } catch {return null;}
}
