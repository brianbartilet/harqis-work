import {connectionRadius} from './graph-sizing.mjs';
// Fleet outputs use Activity's compact entry orbs; agent hubs remain degree-sized.
export const activityKind=kind=>({owner:'people',agent:'sources',subagent:'people',hud:'tools',configuration:'tools',workflow:'tools',trigger:'tools',task:'actions',action:'actions',idea:'ideas'}[kind]||'entries');
// Available agents remain visible across activity date, Space and object filters.
export function filterFleet(data,{query='',spaces=[],types=[],since='',until='',inactive=false,dismissed=false,includeOwnerActivity=true,range='0',now=Date.now(),service='',hideInactiveWorkflows=false,hideArchivedWorkflows=false}={}) {
  const q=query.trim().toLowerCase(), enabled=new Set(types), allowedAgents=new Map(data.agents.filter(a=>(inactive||a.active)&&(!service||a.runtime===service)).map(a=>[a.id,a]));
  const spaceMatch=n=>!spaces.length||(n.kind==='hud'&&!(n.workspace_ids||[]).length)||spaces.some(s=>(n.workspace_ids||[]).includes(s));
  const textMatch=n=>!q||[n.label,n.summary,n.source].some(v=>(v||'').toLowerCase().includes(q));
  const parents=n=>(n.agent_ids||[]).filter(id=>allowedAgents.has(id));
  const isIntent=n=>['action','idea'].includes(n.kind);
  const midnight=new Date(now);midnight.setHours(0,0,0,0);
  const definition=n=>n.source==='n8n'&&['workflow','application','configuration','trigger'].includes(n.kind);
  const dateMatch=n=>definition(n)||n.kind==='hud'||isIntent(n)||(['1','24h','today'].includes(range)?(Date.parse(n.created)>=(range==='today'?midnight.getTime():now-86400000)&&Date.parse(n.created)<=now):((!since||n.created?.slice(0,10)>=since)&&(!until||n.created?.slice(0,10)<=until)));
  const isClosedIntent=n=>isIntent(n)&&['done','dismissed','archived'].includes(n.state||n.status||n.record?.status);
  const objects=data.nodes.filter(n=>!['agent','owner'].includes(n.kind)&&enabled.has(n.kind)&&(parents(n).length||(!service&&!(n.agent_ids||[]).length))&&(definition(n)&&!(n.workspace_ids||[]).length||spaceMatch(n))&&textMatch(n)&&dateMatch(n)&&!(n.kind==='workflow'&&((hideInactiveWorkflows&&['inactive','draft'].includes(n.state))||(hideArchivedWorkflows&&n.state==='archived')))&&(includeOwnerActivity||n.kind!=='entry'||(n.agent_ids||[]).length>0)&&(dismissed||!isClosedIntent(n)));
  const owners=new Set(objects.flatMap(parents));
  const nodes=[...data.nodes.filter(n=>n.kind==='agent'&&allowedAgents.has(n.agent_id)&&(textMatch(n)||owners.has(n.agent_id))),...objects];
  const owner=data.nodes.find(n=>n.kind==='owner');if(owner&&(objects.length||(!query&&!spaces.length&&!since&&!until&&!service)))nodes.unshift(owner);
  const ids=new Set(nodes.map(n=>n.id));
  const links=data.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));
  const degree=new Map(nodes.map(n=>[n.id,0]));
  for(const edge of links){degree.set(edge.source,degree.get(edge.source)+1);degree.set(edge.target,degree.get(edge.target)+1);}
  return {nodes:nodes.map(n=>({...n,visibleDegree:degree.get(n.id),radius:['agent','owner'].includes(n.kind)?16+4*Math.log2(1+degree.get(n.id)):connectionRadius(n.kind==='subagent'?activityKind(n.kind):'entries',degree.get(n.id),nodes.length)})),links};
}
