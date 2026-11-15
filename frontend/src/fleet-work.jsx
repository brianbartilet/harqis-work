import semantics from '../static/entity-semantics.json';
import React,{useMemo,useState} from 'react';
import {agentWork} from './fleet-work.mjs';

export function AgentWork({nodes,agents,agent,selected,select,loaded,error,generated,limited,ask,scope}){
 const [expanded,setExpanded]=useState({});
 const groups=useMemo(()=>agentWork(nodes,agent?.id),[nodes,agent?.id]);
 const sections=[['attention','Needs attention'],['running','Running'],['queued','Queued'],['assigned','Assigned'],['recent','Recent results']];
 const count=Object.values(groups).reduce((n,rows)=>n+rows.length,0);
 return <aside className="fleet-work-panel" aria-label="Agent work">
  <header><div><h2>Agent work</h2><p>{agent?.name||scope}</p></div><button type="button" title="Ask Butler about this work" onClick={()=>ask(agent)}>Ask Butler</button></header>
  <label className="fleet-work-agent">Agent<select aria-label="Work agent" value={agent?.id||''} onChange={event=>select(event.target.value?'agent:'+event.target.value:'')}><option value="">All matching agents</option>{nodes.filter(node=>node.kind==='agent').map(node=><option key={node.agent_id} value={node.agent_id}>{node.label}</option>)}</select></label>
  <p className="fleet-work-freshness">{generated?'Updated '+new Date(generated).toLocaleTimeString():'Waiting for recorded work'}</p>
  {error&&<p role="status">Some work could not refresh. Displayed records may be stale.</p>}
  {!loaded?<p role="status">Loading agent work…</p>:!count?<p>No open work in this Space. Graph display filters do not apply.</p>:sections.map(([key,label])=>groups[key].length>0&&<section key={key} aria-label={label}>
   <h3>{label} <span>{groups[key].length}</span></h3>
   {groups[key].slice(0,expanded[key]||5).map(node=>{
    const run=node.execution, names=[...new Set([...(node.agent_ids||[]),...(run?[run.agent_id]:[])])].map(id=>agents.find(a=>a.id===id)?.name).filter(Boolean);
    const status=node.record?.status;
    return <article key={node.id} data-selected={selected===node.id}><button type="button" className="fleet-work-title" onClick={()=>select(node.id)}>{node.label}</button>
     <small>{names.join(', ')||'Unassigned'}</small>
     {status&&<small>Action: {semantics.action.labels[status]||status}</small>}
     <small>{!node.record&&!run&&node.state?'Reported: '+node.state.replaceAll('_',' '):'Execution: '+(run?run.state.replaceAll('_',' '):'Not recorded')}</small>
     {run?.updated_at&&<time dateTime={run.updated_at}>{new Date(run.updated_at).toLocaleString()}</time>}
     {run?<a href={run.url}>{key==='attention'?'Review run':'Inspect run'}</a>:<button type="button" onClick={()=>select(node.id)}>{node.kind==='action'?'Open action':'Open record'}</button>}
    </article>;
   })}
   {groups[key].length>5&&<button type="button" onClick={()=>setExpanded(old=>({...old,[key]:(old[key]||5)>=groups[key].length?5:(old[key]||5)+20}))}>{(expanded[key]||5)>=groups[key].length?'Show less':'Show more ('+(groups[key].length-(expanded[key]||5))+')'}</button>}
  </section>)}
  <p className="fleet-work-freshness">{limited?'This work snapshot is limited. Open Kanban for all actions and run history.':'Showing open work in the selected Spaces; graph filters do not apply.'}</p>
 <a href="/hfl-corpus/actions">Open Kanban and Focus</a></aside>;
}
