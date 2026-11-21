import {isFleetAnchor} from './fleet-drag.mjs';

// Reset uses one graph-space layout regardless of camera zoom or animation.
// Use compact resting positions; Reset turns ambient animation off.
export function resetFleetChildren(nodes,links,{scale=1,bounds=null}={}){
 const motionPadding=0;
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
 const clear=(n,x,y,gap=12)=>{
  const cx=Math.floor(x/cellSize),cy=Math.floor(y/cellSize);
  for(let i=cx-1;i<=cx+1;i++)for(let j=cy-1;j<=cy+1;j++)
   for(const p of grid.get(i+':'+j)||[])if(Math.hypot(x-p.x,y-p.y)<radius(n)+p.r+gap)return false;
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
  // Try the preferred type sectors inside the fitted viewport first. If space
  // is tight, reduce the gap before allowing overflow; never hide any nodes.
  for(const gap of bounds?[12,4,0,-1]:[-1]){
   const spacing=gap<0?step:Math.max(12,...children.map(n=>radius(n)*2+gap));
   const maxRing=bounds&&gap>=0?Math.ceil(Math.max(...[bounds.left,bounds.right].flatMap(px=>[bounds.top,bounds.bottom].map(py=>Math.hypot(px-x,py-y))))/spacing)+1:Infinity;
   for(let ring=0;remaining&&ring<=maxRing;ring++){
    const reach=start+ring*spacing;
    for(const sector of sectors){
     if(sector.next===sector.members.length)continue;
     const slots=Math.max(1,Math.floor(reach*sector.span/spacing));
     for(let slot=0;slot<slots&&sector.next<sector.members.length;slot++){
      const angle=sector.angle+sector.span*(slot+.5)/slots;
      const px=x+reach*Math.cos(angle),py=y+reach*Math.sin(angle),n=sector.members[sector.next];
      const r=radius(n)+8;
      if(bounds&&gap>=0&&(px-r<bounds.left||px+r>bounds.right||py-r<bounds.top||py+r>bounds.bottom))continue;
      if(!clear(n,px,py,gap<0?12:gap))continue;
      Object.assign(n,{x:px/scale,y:py/scale,fx:px/scale,fy:py/scale,vx:0,vy:0,manual:false});
      insert(n,px,py);moved.push(n);sector.next++;remaining--;
     }
    }
   }
   if(!remaining)break;
  }
 }
 return moved;
}

// Establish the camera from fixed anchors only, then pack in that viewport.
// This avoids both collapsed children and a repeated expand/refit feedback loop.
export function resetFleetView(nodes,links,width,height){
 if(!nodes.length)return null;
 const anchors=nodes.filter(n=>isFleetAnchor(n)||n.manual);
 const base=anchors.length?anchors:[{x:0,y:0}];
 const xs=base.map(n=>n.x),ys=base.map(n=>n.y);
 const left=Math.min(...xs),right=Math.max(...xs),top=Math.min(...ys),bottom=Math.max(...ys);
 const x=(left+right)/2,y=(top+bottom)/2;
 const scale=Math.max(.000001,Math.min(1,Math.max(40,width*.55)/(right-left||1),Math.max(40,height*.55)/(bottom-top||1)));
 const bounds={left:x*scale-width/2+16,right:x*scale+width/2-16,top:y*scale-height/2+16,bottom:y*scale+height/2-16};
 resetFleetChildren(nodes,links,{scale,bounds});
 // Only genuinely over-capacity views need a final camera reduction.
 let zoom=scale;
 for(const n of nodes){
  const margin=(n.radius||7)+24;
  if(n.x!==x)zoom=Math.min(zoom,Math.max(1,width/2-margin)/Math.abs(n.x-x));
  if(n.y!==y)zoom=Math.min(zoom,Math.max(1,height/2-margin)/Math.abs(n.y-y));
 }
 return {x,y,zoom:Math.max(.000001,zoom)};
}
