export const isFleetParent = n => ['agent','owner','connector'].includes(n.kind);
const endpoint = n => typeof n === 'object' ? n.id : n;

// Ownership is independent of degree, camera, filtering order and status links.
export function fleetParents(nodes, links) {
 const hubs = new Map(nodes.filter(isFleetParent).map(n => [n.id,n]));
 const adjacent = new Map(nodes.map(n => [n.id,new Set()]));
 for (const l of links) {
  if (l.grouping || l.relation === 'belongs to corpus') continue;
  const a=endpoint(l.source), b=endpoint(l.target);
  if(hubs.has(a)) adjacent.get(b)?.add(a);
  if(hubs.has(b)) adjacent.get(a)?.add(b);
 }
 const owner=[...hubs.values()].filter(n=>n.kind==='owner').sort((a,b)=>a.id.localeCompare(b.id))[0]?.id;
 const result=new Map();
 for(const n of nodes) {
  if(isFleetParent(n)||n.kind==='status') continue;
  const assigned='agent:'+(n.assigned_agent_id||n.record?.assigned_agent_id||'');
  const direct='agent:'+(n.agent_id||'');
  const candidates=new Set([...adjacent.get(n.id)||[],...(n.agent_ids||[]).map(id=>'agent:'+id)].filter(id=>hubs.has(id)&&hubs.get(id).kind!=='owner'));
  if(hubs.has(n.groupParent)&&hubs.get(n.groupParent).kind!=='owner')candidates.add(n.groupParent);
  const parent=hubs.has(assigned)?assigned:hubs.has(direct)?direct:
   candidates.has(n.layoutParent)?n.layoutParent:candidates.has(n.groupParent)?n.groupParent:
   [...candidates].sort()[0]||owner||(hubs.has(n.groupParent)?n.groupParent:undefined);
  if(parent)result.set(n.id,parent);
 }
 return result;
}
