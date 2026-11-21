import {fleetParents,isFleetParent} from './fleet-parent.mjs';

export function fleetCamera(nodes,width,height){
 const points=nodes.filter(n=>Number.isFinite(n.x)&&Number.isFinite(n.y));if(!points.length)return null;
 const x=(Math.min(...points.map(n=>n.x))+Math.max(...points.map(n=>n.x)))/2;
 const y=(Math.min(...points.map(n=>n.y))+Math.max(...points.map(n=>n.y)))/2;
 let zoom=1;
 for(const n of points){
  if(n.x!==x)zoom=Math.min(zoom,Math.max(20,width/2-Math.min(150,width*.25))/Math.abs(n.x-x));
  if(n.y!==y)zoom=Math.min(zoom,Math.max(20,height/2-110)/Math.abs(n.y-y));
 }
 return {x,y,zoom:Math.max(.000001,zoom)};
}
// Keep every entity supplied by Fleet's existing search and type filters visible.
// Density must not replace selectable entities with synthetic count nodes.
export function fleetOverview(data){
 const parents=fleetParents(data.nodes,data.links),hubCounts=new Map();
 for(const parent of parents.values())hubCounts.set(parent,(hubCounts.get(parent)||0)+1);
 const nodes=data.nodes.map(n=>({...n,layoutParent:parents.get(n.id),groupParent:parents.get(n.id)||n.groupParent,childCount:hubCounts.get(n.id)||0}));
 const ids=new Set(nodes.map(n=>n.id));
 const links=data.links.filter(l=>ids.has(typeof l.source==='object'?l.source.id:l.source)&&ids.has(typeof l.target==='object'?l.target.id:l.target)).map(l=>({...l}));
 return {nodes,links,parents};
}

// Explicit arrangement repairs overlapping/legacy anchors. Camera is separate.
export function arrangeFleetClusters(nodes,links,{width=1000,height=700,childrenOnly=false,scale=1}={}){
 const ownership=fleetParents(nodes,links),hubs=nodes.filter(isFleetParent).sort((a,b)=>a.id.localeCompare(b.id));
 const children=parent=>nodes.filter(n=>ownership.get(n.id)===parent&&!n.manual&&!n.pinned).sort((a,b)=>a.kind.localeCompare(b.kind)||a.id.localeCompare(b.id));
 const maxCount=Math.max(1,...hubs.map(h=>children(h.id).length));
 const reach=180+Math.ceil(maxCount/12)*64;
 const spacing=reach*2+180,cols=Math.max(1,Math.ceil(Math.sqrt(hubs.length*Math.max(.5,width/height))));
 const fixed=nodes.filter(n=>n.manual||n.pinned);
 const occupy=[...fixed];
 const put=(n,x,y)=>Object.assign(n,{x,y,fx:x,fy:y,vx:0,vy:0});
 for(let i=0;i<hubs.length;i++){
  const h=hubs[i];
  if(!childrenOnly&&!h.manual&&!h.pinned){
   let x=(i%cols-(cols-1)/2)*spacing,y=(Math.floor(i/cols)-(Math.ceil(hubs.length/cols)-1)/2)*spacing;
   while(occupy.some(p=>Math.hypot(x-p.x,y-p.y)<spacing))x+=spacing;
   put(h,x,y);occupy.push(h);
  }
  const members=children(h.id),s=childrenOnly?Math.max(.000001,scale):1;
  let slot=0;
  for(const n of members){
   let x,y;
   do {
    const ring=Math.floor(slot/12),angle=(slot%12)*Math.PI/6-Math.PI/2,radius=180+ring*64;slot++;
    x=h.x+radius/s*Math.cos(angle);y=h.y+radius/s*Math.sin(angle);
   }while(fixed.some(p=>p!==h&&Math.hypot(x-p.x,y-p.y)*s<(n.radius||7)+(p.radius||7)+16));
   put(n,x,y);n.layoutParent=h.id;
  }
 }
 return ownership;
}
