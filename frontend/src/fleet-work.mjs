const attention=new Set(['review','awaiting_input','failed','interrupted','accepting']);
export function agentWork(nodes, agentId='') {
  const groups={attention:[],running:[],queued:[],assigned:[],recent:[]};
  for(const node of nodes){
    if(!['action','task'].includes(node.kind))continue;
    const execution=node.execution;
    if(agentId&&!(node.agent_ids||[]).includes(agentId)&&execution?.agent_id!==agentId)continue;
    if(!(node.agent_ids||[]).length&&!execution)continue;
    const closed=['done','dismissed','archived'].includes(node.record?.status||node.state);
    const state=execution?.state||(!node.record?node.state:'');
    const group=attention.has(state)?'attention':state==='running'?'running':state==='queued'?'queued':closed||['succeeded','completed'].includes(state)?'recent':'assigned';
    groups[group].push(node);
  }
  for(const rows of Object.values(groups))rows.sort((a,b)=>(b.execution?.updated_at||b.created||'').localeCompare(a.execution?.updated_at||a.created||'')||a.id.localeCompare(b.id));
  return groups;
}
