import {fleetParents,isFleetParent} from './fleet-parent.mjs';

export const fleetGroupId=(parent,kind)=>'fleet-group:'+JSON.stringify([parent,kind]);
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
export function fleetOverview(data,{selected,group='',query='',page=0,limit=24,compact=false}={}){
 const parents=fleetParents(data.nodes,data.links),groups=new Map();
 const hubCounts=new Map();
 for(const n of data.nodes){
  const parent=parents.get(n.id);if(!parent)continue;
  hubCounts.set(parent,(hubCounts.get(parent)||0)+1);
  const id=fleetGroupId(parent,n.kind);
  if(!groups.has(id))groups.set(id,{id,parent,kind:n.kind,members:[]});
  groups.get(id).members.push(n);
 }
 const hidden=new Set(),extra=[],shown=new Set();
 for(const g of groups.values()){
  g.members.sort((a,b)=>(a.label||a.id).localeCompare(b.label||b.id)||a.id.localeCompare(b.id));
  // Bound total children per parent, not just each individual type.
  if(hubCounts.get(g.parent)<=limit)continue;
  g.label=g.kind.replaceAll('_',' ')+' · '+g.members.length;
  const matches=g.members.filter(n=>(n.label||n.id).toLowerCase().includes(query.toLowerCase()));
  g.matches=matches;g.page=Math.max(0,Math.min(page,Math.ceil(matches.length/limit)-1));
  g.visible=group===g.id?matches.slice(g.page*limit,(g.page+1)*limit):[];
  for(const n of g.members)if(n.id!==selected&&!g.visible.includes(n)&&!n.manual&&!n.pinned)hidden.add(n.id);else shown.add(n.id);
  extra.push({id:g.id,kind:'group',label:g.label,groupParent:g.parent,layoutParent:g.parent,radius:16,color:g.members[0].color||'#60a5fa',count:g.members.length,clusterX:0,clusterY:0});
 }
 const nodes=data.nodes.filter(n=>!hidden.has(n.id)).map(n=>({...n,layoutParent:parents.get(n.id),groupParent:parents.get(n.id)||n.groupParent,childCount:hubCounts.get(n.id)||0}));
 const ids=new Set(nodes.map(n=>n.id));
 const links=data.links.filter(l=>ids.has(typeof l.source==='object'?l.source.id:l.source)&&ids.has(typeof l.target==='object'?l.target.id:l.target)).map(l=>({...l}));
 for(const n of extra)links.push({source:n.groupParent,target:n.id,relation:'contains',direction:'none'});
 const focusParent=compact?(nodes.find(n=>n.id===selected&&isFleetParent(n))?.id||parents.get(selected)||groups.get(group)?.parent||nodes.find(n=>n.kind==='agent')?.id||nodes.find(isFleetParent)?.id):null;
 const shownNodes=focusParent?[...nodes,...extra].filter(n=>n.id===focusParent||n.layoutParent===focusParent||n.groupParent===focusParent):[...nodes,...extra];
 const shownIds=new Set(shownNodes.map(n=>n.id));
 return {nodes:shownNodes,links:links.filter(l=>shownIds.has(typeof l.source==='object'?l.source.id:l.source)&&shownIds.has(typeof l.target==='object'?l.target.id:l.target)),groups:[...groups.values()].filter(g=>g.label),parents,focusParent};
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
