import {connectionRadius} from './graph-sizing.mjs';
// Fleet outputs use Activity's compact entry orbs; agent hubs remain degree-sized.
export const activityKind=kind=>({agent:'sources',subagent:'people',hud:'tools',configuration:'tools',workflow:'tools',trigger:'tools',task:'actions',action:'actions',idea:'ideas'}[kind]||'entries');
// Agent anchors survive object filters; a matching output brings its producer into view.
export function filterFleet(data,{query='',spaces=[],types=[],since='',until='',inactive=false,service=''}={}) {
  const q=query.trim().toLowerCase(), enabled=new Set(types), allowedAgents=new Map(data.agents.filter(a=>(inactive||a.active)&&(!service||a.runtime===service)).map(a=>[a.id,a]));
  const spaceMatch=n=>!spaces.length||spaces.some(s=>(n.workspace_ids||[]).includes(s));
  const textMatch=n=>!q||[n.label,n.summary,n.source].some(v=>(v||'').toLowerCase().includes(q));
  const parents=n=>(n.agent_ids||[]).filter(id=>allowedAgents.has(id));
  const objects=data.nodes.filter(n=>n.kind!=='agent'&&enabled.has(n.kind)&&parents(n).length&&spaceMatch(n)&&textMatch(n)&&(!since||n.created?.slice(0,10)>=since)&&(!until||n.created?.slice(0,10)<=until));
  const owners=new Set(objects.flatMap(parents));
  const nodes=[...data.nodes.filter(n=>n.kind==='agent'&&allowedAgents.has(n.agent_id)&&((spaceMatch(n)&&textMatch(n)&&!since&&!until)||owners.has(n.agent_id))),...objects];
  const ids=new Set(nodes.map(n=>n.id));
  const links=data.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));
  const degree=new Map(nodes.map(n=>[n.id,0]));
  for(const edge of links){degree.set(edge.source,degree.get(edge.source)+1);degree.set(edge.target,degree.get(edge.target)+1);}
  return {nodes:nodes.map(n=>({...n,visibleDegree:degree.get(n.id),radius:connectionRadius(['agent','subagent'].includes(n.kind)?activityKind(n.kind):'entries',degree.get(n.id),nodes.length)})),links};
}
