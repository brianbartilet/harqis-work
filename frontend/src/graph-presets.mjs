export const PRESETS = {sources:'Sources', timeline:'Timeline', people:'People', tools:'Tools', companies:'Companies'};
const endpoint = value => typeof value === 'object' ? value.id : value;
export function phaseFor(id) {
  let hash=2166136261;
  for(const c of id) hash=Math.imul(hash ^ c.charCodeAt(0),16777619);
  return (hash>>>0)/4294967296*Math.PI*2;
}

// Mix the node identity so similar entry IDs do not produce similar offsets.
// Repeatable randomness keeps refreshes from reshuffling the user's graph.
function scatter(id, axis) {
  let value=(phaseFor(id+'|'+axis)/(Math.PI*2)*4294967296)>>>0;
  value=Math.imul(value^(value>>>16),0x21f0aaad);
  value=Math.imul(value^(value>>>15),0x735a2d97);
  return ((value^(value>>>15))>>>0)/4294967296;
}

// Stable, linear-space layouts. Multi-source BFS assigns shared activity to its
// nearest anchor without repeatedly scanning edges for every node.
export function randomizePresetNodes(nodes,seed){
  const radius=Math.max(240,Math.sqrt(nodes.length)*25);
  for(const node of nodes){
    const angle=scatter(node.id,seed+'|initial-angle')*Math.PI*2;
    const distance=radius*Math.sqrt(scatter(node.id,seed+'|initial-radius'));
    node.x=node.fx=distance*Math.cos(angle);node.y=node.fy=distance*Math.sin(angle);
    node.vx=node.vy=0;node.manual=false;
    delete node.dragOrigin;delete node.dragWeight;delete node.dragParent;delete node.dragParentOrigin;
  }
}

export function presetLayout(nodes, edges, requested='timeline', seed=0) {
  let preset=PRESETS[requested]?requested:'sources';
  let anchors=nodes.filter(n=>n.kind===(preset==='timeline'?'daily':preset));
  let notice='';
  if(!anchors.length && nodes.length) {
    notice=`No ${PRESETS[preset].toLowerCase()} nodes in this view. Using Sources layout.`;
    preset='sources';anchors=nodes.filter(n=>n.kind==='sources');
  }
  anchors.sort(preset==='timeline' ? (a,b)=>a.id.localeCompare(b.id) : preset==='sources'
    ? (a,b)=>(b.radius||0)-(a.radius||0)||(b.visibleDegree||0)-(a.visibleDegree||0)||a.id.localeCompare(b.id)
    : (a,b)=>(b.visibleDegree||0)-(a.visibleDegree||0)||a.id.localeCompare(b.id));
  const adjacency=new Map(nodes.map(n=>[n.id,[]])), owners=new Map(), queue=[];
  for(const edge of edges){const a=endpoint(edge.source),b=endpoint(edge.target);if(adjacency.has(a)&&adjacency.has(b)){adjacency.get(a).push(b);adjacency.get(b).push(a);}}
  anchors.forEach((n,i)=>{owners.set(n.id,i);queue.push(n.id);});
  for(let i=0;i<queue.length;i++)for(const next of adjacency.get(queue[i]))if(!owners.has(next)){owners.set(next,owners.get(queue[i]));queue.push(next);}
  const clustered=['sources','people','tools','companies'].includes(preset);
  const cell=2*Math.max(12,...anchors.map(n=>n.radius||12))+12;
  const positions=new Map(), radius=Math.max(240,Math.sqrt(nodes.length)*25,anchors.length*16,clustered?Math.sqrt(anchors.length)*cell*1.8:0);
  // Source cluster size depends on source orbs, not thousands of activity nodes.
  const sourceRadius=Math.max(120,Math.sqrt(anchors.reduce((sum,n)=>sum+((n.radius||12)+12)**2,0))*1.8);
  const occupied=new Map();
  anchors.forEach((n,i)=>{
    if(preset==='timeline'){
      const latest=Date.parse(anchors.at(-1).id.replace(/^daily:/,'')),date=Date.parse(n.id.replace(/^daily:/,''));
      positions.set(n.id,{x:Number.isFinite(date)&&Number.isFinite(latest)?(date-latest)/86400000*180:(i-anchors.length+1)*180,y:0,anchor:true});
    }
    else {
      let x=0,y=0,attempt=0;
      if(i)for(;attempt<256;attempt++){
        const angle=scatter(n.id,seed+'|cluster-angle|'+attempt)*Math.PI*2;
        const spread=preset==='sources' ? .35+.65*Math.sqrt(i/Math.max(1,anchors.length-1)) : .4;
        const r=(preset==='sources'?sourceRadius:radius)*spread*Math.sqrt(scatter(n.id,seed+'|cluster-radius|'+attempt));
        x=r*Math.cos(angle);y=r*Math.sin(angle);
        const cx=Math.floor(x/cell),cy=Math.floor(y/cell);
        let clear=true;
        for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)for(const p of occupied.get((cx+dx)+','+(cy+dy))||[]){
          if(Math.hypot(x-p.x,y-p.y)<(n.radius||12)+p.radius+12)clear=false;
        }
        if(clear)break;
      }
      const key=Math.floor(x/cell)+','+Math.floor(y/cell);
      if(!occupied.has(key))occupied.set(key,[]);
      occupied.get(key).push({x,y,radius:n.radius||12});
      positions.set(n.id,{x,y,anchor:true});
    }
  });
  if(['people','tools','companies'].includes(preset)){
    const sources=nodes.filter(n=>n.kind==='sources').sort((a,b)=>a.label.localeCompare(b.label)||a.id.localeCompare(b.id));
    const outerRadius=Math.max(radius*.65,sources.length*18);
    sources.forEach((n,i)=>{
      const angle=(i+.65*(scatter(n.id,seed+'|source-angle')-.5))*2*Math.PI/sources.length+scatter('sources',seed)*2*Math.PI;
      const r=outerRadius*(1+.22*scatter(n.id,seed+'|source-radius'));
      positions.set(n.id,{x:r*Math.cos(angle),y:r*Math.sin(angle),anchor:false});
    });
  }
  if(preset==='timeline'&&anchors.length){
    // Only visibly large hubs leave their date clouds (31 links at normal sizing).
    const span=Math.max(1260,positions.get(anchors.at(-1).id).x-positions.get(anchors[0].id).x);
    const middle=(positions.get(anchors[0].id).x+positions.get(anchors.at(-1).id).x)/2;
    const scale=Math.max(1,span/1400),clusters=[];
    for(const kind of ['sources','people','companies','tools']){
      const hubs=nodes.filter(n=>n.kind===kind&&(n.radius||0)>=24);
      if(!hubs.length)continue;
      // Source packing places the largest orb first, regardless of entity kind.
      const packed=presetLayout(hubs.map(n=>({...n,kind:'sources'})),[],'sources',seed).positions;
      const extent=Math.max(...hubs.map(n=>{const p=packed.get(n.id);return Math.hypot(p.x,p.y)+(n.radius||12);}))*scale;
      clusters.push({kind,hubs,packed,extent});
    }
    const extent=Math.max(0,...clusters.map(c=>c.extent));
    const vertical=Math.max(span*.24,extent*2+200,600);
    const right=middle+Math.max(span*.32,extent*2+200);
    const centers={sources:{x:middle,y:-vertical},tools:{x:middle,y:vertical},
      people:{x:right,y:-vertical*1.65},companies:{x:right,y:-vertical*.6}};
    for(const {kind,hubs,packed} of clusters)for(const n of hubs){
      const p=packed.get(n.id),center=centers[kind];
      positions.set(n.id,{x:center.x+p.x*scale,y:center.y+p.y*scale,anchor:false});
    }
  }

  const sourceExtent=preset==='sources'?Math.max(0,...anchors.map(n=>{
    const p=positions.get(n.id);return Math.hypot(p.x,p.y)+(n.radius||12);
  })):0;
  const groups=new Map();
  for(const n of [...nodes].sort((a,b)=>a.id.localeCompare(b.id)))if(!positions.has(n.id)){
    const owner=owners.get(n.id)??-1;if(!groups.has(owner))groups.set(owner,[]);groups.get(owner).push(n);
  }
  for(const [owner,group] of groups)group.forEach((n,i)=>{
    const angular=scatter(n.id,seed+'|angle'),radial=scatter(n.id,seed+'|radius');
    let x,y;
    if(preset==='sources'&&anchors.length){
      // Keep all other kinds outside the source cluster, including disconnected nodes.
      const inner=sourceExtent+(n.radius||12)+100;
      const outer=Math.max(radius,inner+Math.sqrt(nodes.length)*18);
      const r=Math.sqrt(inner*inner+radial*(outer*outer-inner*inner));
      const angle=angular*Math.PI*2;x=r*Math.cos(angle);y=r*Math.sin(angle);
    }
    else if(preset==='timeline'&&owner>=0){const anchor=positions.get(anchors[owner].id);x=anchor.x+(angular-.5)*130;y=(scatter(n.id,seed+'|side')<.5?-1:1)*(45+Math.sqrt(radial)*Math.max(100,Math.sqrt(group.length)*28));}
    else if(!anchors.length||owner<0){const fraction=Math.max(.01,radial);const r=radius*(preset==='sources'?.72*Math.sqrt(fraction):anchors.length?1.04+radial*.16:Math.sqrt(fraction));const angle=angular*2*Math.PI;x=r*Math.cos(angle);y=r*.8*Math.sin(angle);}
    else {const angle=angular*2*Math.PI;
      const fraction=Math.max(.01,radial);
      const r=radius*(preset==='sources'?.12+.60*Math.sqrt(fraction):.48+.48*Math.sqrt(fraction));x=r*Math.cos(angle);y=r*.8*Math.sin(angle);}
    positions.set(n.id,{x,y,anchor:false});
  });
  return {preset,positions,notice};
}

export function presetFitPoints(nodes,positions,preset) {
  if(preset==='timeline')return timelineFitPoints(nodes,positions);
  if(['sources','people','tools','companies'].includes(preset)){
    const cluster=nodes.filter(n=>n.kind===preset&&positions.has(n.id)).map(n=>positions.get(n.id));
    if(cluster.length)return cluster;
  }
  return [...positions.values()];
}

export function timelineFitPoints(nodes, positions) {
  const dates=nodes.filter(n=>n.kind==='daily'&&positions.has(n.id)).map(n=>({
    point:positions.get(n.id),time:Date.parse(n.id.replace(/^daily:/,''))
  })).filter(n=>Number.isFinite(n.time));
  if(!dates.length)return [...positions.values()];
  const latest=dates.reduce((a,b)=>a.time>b.time?a:b);
  // Frame seven calendar days across the viewport; hub clusters are revealed
  // by zooming out, rather than reducing the initial timeline detail.
  return [{x:latest.point.x-6*180-60,y:latest.point.y-220},{x:latest.point.x+60,y:latest.point.y+220}];
}

export function motionOffset(mode, point, time, phase, fixed=false) {
  if(fixed||mode==='off')return {x:0,y:0};
  const wave=time*2*Math.PI/12000;
  if(mode==='breathing'){const scale=.035*Math.sin(wave);return {x:point.x*scale,y:point.y*scale};}
  if(mode==='ripple'){const r=Math.hypot(point.x,point.y)||1,amplitude=8*Math.sin(wave-r/130);return {x:point.x/r*amplitude,y:point.y/r*amplitude};}
  return {x:8*Math.sin(wave+phase),y:6*Math.cos(wave*.8+phase)};
}
