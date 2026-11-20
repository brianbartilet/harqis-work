import {actionStatusNames} from './action-status.mjs';
// Presentation only: canonical provenance edges remain unchanged.
export function groupFleet(data,{showStatus=true,statusColor='#94a3b8'}={}){
 const nodes=data.nodes.map(n=>({...n})),links=data.links.map(e=>({...e}));
 const hubs=nodes.filter(n=>['agent','owner','connector'].includes(n.kind)).sort((a,b)=>a.id.localeCompare(b.id));
 const ids=new Set(hubs.map(n=>n.id)),owner=hubs.find(n=>n.kind==='owner')?.id;
 const parent=n=>ids.has('agent:'+n.assigned_agent_id)?'agent:'+n.assigned_agent_id:(n.agent_ids||[]).map(id=>'agent:'+id).filter(id=>ids.has(id)).sort()[0]||owner;
 const groups=new Map();
 for(const n of nodes){
  if(ids.has(n.id))continue;
  n.groupParent=parent(n);n.groupKind=['action','idea','entry'].includes(n.kind)?n.kind:'related';
  if(!['action','idea'].includes(n.kind))continue;
  const state=n.state||n.status||n.record?.status||'unknown';
  const key='fleet-status:'+JSON.stringify([n.kind,state]);
  if(!groups.has(key)){
   const label=n.kind==='action'?(actionStatusNames[state]||state):state.replaceAll('_',' ').replace(/^./,s=>s.toUpperCase());
   groups.set(key,{id:key,kind:'status',label,color:statusColor,groupParents:[],groupKind:n.kind,state,agent_ids:[],radius:13,count:0});
  }
  const group=groups.get(key);group.count++;
  if(n.groupParent&&!group.groupParents.includes(n.groupParent))group.groupParents.push(n.groupParent);
  n.statusGroup=key;
  links.push({source:n.id,target:key,relation:'has status',direction:'none',grouping:true});
 }
 for(const group of groups.values()){
  group.visibleDegree=group.count;
  group.summary=group.count+' visible '+(group.groupKind==='action'?'actions':'ideas')+'. Connections update with status changes.';
  nodes.push(group);
  for(const parent of group.groupParents.sort())links.push({source:parent,target:group.id,relation:'status group',direction:'none',grouping:true});
 }
 const locations=new Map(hubs.map((n,i)=>[n.id,{x:650*Math.cos(i*2*Math.PI/Math.max(hubs.length,1)),y:650*Math.sin(i*2*Math.PI/Math.max(hubs.length,1))}]));
 const angles={action:-Math.PI/2,idea:0,entry:Math.PI/2,related:Math.PI};
 const sectors=new Map();
 for(const group of groups.values()){const key=group.groupKind;if(!sectors.has(key))sectors.set(key,[]);sectors.get(key).push(group.id);}
 for(const sector of sectors.values())sector.sort();
 const byId=new Map(nodes.map(n=>[n.id,n]));
 for(const n of nodes){
  let base=locations.get(n.groupParent||n.id)||{x:0,y:0};
  // Status is a visual relationship, not a shared position for its members.
  if(n.kind!=='status'){
   const angle=angles[n.groupKind]||0,reach=ids.has(n.id)?0:320;
   n.clusterX=base.x+reach*Math.cos(angle);n.clusterY=base.y+reach*Math.sin(angle);
   continue;
  }
  const statusGroup=groups.get(n.id);
  if(statusGroup){const anchors=statusGroup.groupParents.map(id=>locations.get(id)).filter(Boolean);if(anchors.length)base={x:anchors.reduce((sum,p)=>sum+p.x,0)/anchors.length,y:anchors.reduce((sum,p)=>sum+p.y,0)/anchors.length};}
  if(ids.has(n.id)){n.clusterX=base.x;n.clusterY=base.y;continue;}
  const sector=sectors.get(n.groupKind)||[],group=n.statusGroup||n.id;
  const spread=sector.length>1?(sector.indexOf(group)/(sector.length-1)-.5)*1.1:0;
  const angle=angles[n.groupKind]+spread;
  const count=byId.get(group)?.count||1,reach=300+Math.sqrt(count)*20;
  n.clusterX=base.x+reach*Math.cos(angle);n.clusterY=base.y+reach*Math.sin(angle);
 }
 return {nodes:showStatus?nodes:nodes.filter(n=>n.kind!=='status'),links:showStatus?links:links.filter(e=>!e.grouping)};
}
export function configureFleetLinks(graph){
 graph.d3Force('link').strength(link=>link.grouping?0:link.relation==='belongs to corpus'?.012:.035).distance(220);
}
