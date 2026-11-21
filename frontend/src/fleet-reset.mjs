import {isFleetAnchor} from './fleet-drag.mjs';

// Reset uses one graph-space layout regardless of camera zoom or animation.
// Reserve the same motion margin in every mode so changing modes never repacks it.
export function resetFleetChildren(nodes,links,layoutScale=1){
 const scale=layoutScale,motionPadding=23;
 const fixed=n=>isFleetAnchor(n)||n.manual;
 const endpoint=v=>typeof v==='object'?v.id:v;
 const byId=new Map(nodes.map(n=>[n.id,n]));
 const parents=nodes.filter(n=>['agent','owner','connector'].includes(n.kind));
 const parentIds=new Set(parents.map(n=>n.id));
 const adjacency=new Map(nodes.map(n=>[n.id,new Set()]));
 for(const link of links){
  if(link.grouping)continue;
  const a=endpoint(link.source),b=endpoint(link.target);
  if(a!==b&&byId.has(a)&&byId.has(b)){adjacency.get(a).add(b);adjacency.get(b).add(a);}
 }
 const degree=n=>adjacency.get(n.id).size;
 const rank=(a,b)=>degree(b)-degree(a)||a.id.localeCompare(b.id);
 parents.sort(rank);
 const groups=new Map();
 for(const n of nodes.filter(n=>!fixed(n)).sort((a,b)=>a.id.localeCompare(b.id))){
  const candidates=new Set([...adjacency.get(n.id)].filter(id=>parentIds.has(id)));
  for(const id of n.agent_ids||[])if(parentIds.has('agent:'+id))candidates.add('agent:'+id);
  if(parentIds.has(n.groupParent))candidates.add(n.groupParent);
  const parent=[...candidates].map(id=>byId.get(id)).sort(rank)[0]||parents.find(p=>p.kind==='owner')||parents[0];
  const key=parent?.id||'';
  if(!groups.has(key))groups.set(key,{parent,children:[]});
  groups.get(key).children.push(n);
 }
 const radius=n=>(n.radius||7)+(fixed(n)?0:motionPadding);
 const cellSize=Math.max(32,...nodes.map(n=>radius(n)*2+12)),grid=new Map();
 const insert=(n,x=n.x*scale,y=n.y*scale)=>{
  const key=Math.floor(x/cellSize)+':'+Math.floor(y/cellSize);
  if(!grid.has(key))grid.set(key,[]);
  grid.get(key).push({x,y,r:radius(n)});
 };
 const clear=(n,x,y)=>{
  const cx=Math.floor(x/cellSize),cy=Math.floor(y/cellSize);
  for(let i=cx-1;i<=cx+1;i++)for(let j=cy-1;j<=cy+1;j++)
   for(const p of grid.get(i+':'+j)||[])if(Math.hypot(x-p.x,y-p.y)<radius(n)+p.r+12)return false;
  return true;
 };
 for(const n of nodes.filter(fixed))insert(n);
 const moved=[];
 for(const {parent,children} of [...groups.values()].sort((a,b)=>a.parent&&b.parent?rank(a.parent,b.parent):0)){
  const x=(parent?.x||0)*scale,y=(parent?.y||0)*scale;
  const kinds=[...new Set(children.map(n=>n.kind))].sort();
  const step=Math.max(28,...children.map(n=>radius(n)*2+12));
  const start=(parent?radius(parent):0)+Math.max(...children.map(radius))+24;
  let sectorStart=-Math.PI/2;
  const sectors=kinds.map(kind=>{
   const members=children.filter(n=>n.kind===kind),span=2*Math.PI*members.length/children.length;
   const sector={members,next:0,angle:sectorStart,span};sectorStart+=span;return sector;
  });
  // Each ring tries the full available circumference before expanding. Occupied
  // sectors are skipped, leaving neighboring fixed hubs and earlier clusters intact.
  let remaining=children.length;
  for(let ring=0;remaining;ring++){
   const reach=start+ring*step;
   for(const sector of sectors){
    if(sector.next===sector.members.length)continue;
    const slots=Math.max(1,Math.floor(reach*sector.span/step));
    for(let slot=0;slot<slots&&sector.next<sector.members.length;slot++){
     const angle=sector.angle+sector.span*(slot+.5)/slots;
     const px=x+reach*Math.cos(angle),py=y+reach*Math.sin(angle),n=sector.members[sector.next];
     if(!clear(n,px,py))continue;
     Object.assign(n,{x:px/scale,y:py/scale,fx:px/scale,fy:py/scale,vx:0,vy:0,manual:false});
     insert(n,px,py);moved.push(n);sector.next++;remaining--;
    }
   }
  }
 }
 return moved;
}

// Fit is derived from the viewport size, never the previous camera or animation.
export function fitFleetReset(nodes,links,width,height){
 if(!nodes.length)return null;
 const fixed=n=>isFleetAnchor(n)||n.manual;
 const fit=()=>{
  const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y);
  const left=Math.min(...xs),right=Math.max(...xs),top=Math.min(...ys),bottom=Math.max(...ys);
  const padding=Math.max(...nodes.map(n=>n.radius||7))+55;
  return {x:(left+right)/2,y:(top+bottom)/2,zoom:Math.max(.01,Math.min(3,Math.max(40,width-2*padding)/Math.max(1,right-left),Math.max(40,height-2*padding)/Math.max(1,bottom-top)))};
 };
 let scale=1,best;
 for(let pass=0;pass<4;pass++){
  resetFleetChildren(nodes,links,scale);
  const view=fit();let overlap=0;
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
   const a=nodes[i],b=nodes[j];if(fixed(a)&&fixed(b))continue;
   const gap=(a.radius||7)+(b.radius||7)+12;
   overlap+=Math.max(0,gap-Math.hypot(a.x-b.x,a.y-b.y)*view.zoom);
  }
  if(!best||overlap<best.overlap)best={overlap,view,points:nodes.map(n=>({x:n.x,y:n.y}))};
  if(overlap===0)break;
  scale=view.zoom;
 }
 nodes.forEach((n,i)=>Object.assign(n,best.points[i],{fx:best.points[i].x,fy:best.points[i].y,vx:0,vy:0}));
 return best.view;
}
