// Presentation only: retain assignment and entity-kind placement, never status hubs.
export function groupFleet(data){
 const nodes=data.nodes.map(n=>({...n})),links=data.links.map(e=>({...e}));
 const hubs=nodes.filter(n=>['agent','owner'].includes(n.kind)).sort((a,b)=>a.id.localeCompare(b.id));
 const ids=new Set(hubs.map(n=>n.id)),owner=hubs.find(n=>n.kind==='owner')?.id;
 const parent=n=>ids.has('agent:'+n.assigned_agent_id)?'agent:'+n.assigned_agent_id:(n.agent_ids||[]).map(id=>'agent:'+id).filter(id=>ids.has(id)).sort()[0]||owner;
 const locations=new Map(hubs.map((n,i)=>[n.id,{x:650*Math.cos(i*2*Math.PI/Math.max(hubs.length,1)),y:650*Math.sin(i*2*Math.PI/Math.max(hubs.length,1))}]));
 const angles={action:-Math.PI/2,idea:0,entry:Math.PI/2,related:Math.PI};
 for(const n of nodes){
  if(!ids.has(n.id)){n.groupParent=parent(n);n.groupKind=['action','idea','entry'].includes(n.kind)?n.kind:'related';}
  const base=locations.get(n.groupParent||n.id)||{x:0,y:0};
  const angle=angles[n.groupKind]||0,reach=ids.has(n.id)?0:320;
  n.clusterX=base.x+reach*Math.cos(angle);n.clusterY=base.y+reach*Math.sin(angle);
 }
 return {nodes,links};
}
export function configureFleetLinks(graph){
 graph.d3Force('link').strength(link=>link.relation==='belongs to corpus'?.012:.035).distance(220);
}
