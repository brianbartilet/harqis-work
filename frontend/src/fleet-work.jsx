import React,{useState} from 'react';
import {agentWork} from './fleet-work.mjs';

export function AgentWork({nodes,agents,agent,selected,select,loaded,error,generated,limited,ask,scope}){
 const [expanded,setExpanded]=useState({});
 const groups=agentWork(nodes,agent?.id);
 const sections=[['attention','Needs attention'],['running','Running'],['queued','Queued'],['assigned','Assigned'],['recent','Recent results']];
 const count=Object.values(groups).reduce((n,rows)=>n+rows.length,0);
 return <aside className="fleet-work-panel" aria-label="Agent work">
  <header><div><h2>Agent work</h2><p>{agent?.name||scope}</p></div><button type="button" title="Ask Butler about this work" onClick={()=>ask(agent)}>Ask Butler</button></header>
  <p className="fleet-work-freshness">{generated?'Updated '+new Date(generated).toLocaleTimeString():'Waiting for recorded work'}</p>
  {error&&<p role="status">Some work could not refresh. Displayed records may be stale.</p>}
  {!loaded?<p role="status">Loading agent work…</p>:!count?<p>No matching recorded assignments or runs. Graph filters also apply.</p>:sections.map(([key,label])=>groups[key].length>0&&<section key={key} aria-label={label}>
   <h3>{label} <span>{groups[key].length}</span></h3>
   {groups[key].slice(0,expanded[key]?groups[key].length:5).map(node=>{
    const run=node.execution, names=[...new Set([...(node.agent_ids||[]),...(run?[run.agent_id]:[])])].map(id=>agents.find(a=>a.id===id)?.name).filter(Boolean);
    const status=node.record?.status||(!run?node.state:'');
    return <article key={node.id} data-selected={selected===node.id}><button type="button" className="fleet-work-title" onClick={()=>select(node.id)}>{node.label}</button>
     <small>{names.join(', ')}</small>
     {status&&<small>Action: {status.replaceAll('_',' ')}</small>}
     <small>Execution: {run?run.state.replaceAll('_',' '):'No recorded run in this snapshot'}</small>
     {run?.updated_at&&<time dateTime={run.updated_at}>{new Date(run.updated_at).toLocaleString()}</time>}
     {run?<a href={run.url}>{key==='attention'?'Review run':'Inspect run'}</a>:<button type="button" onClick={()=>select(node.id)}>Open action</button>}
    </article>;
   })}
   {groups[key].length>5&&<button type="button" onClick={()=>setExpanded(old=>({...old,[key]:!old[key]}))}>{expanded[key]?'Show less':'Show more ('+(groups[key].length-5)+')'}</button>}
  </section>)}
  <p className="fleet-work-freshness">{limited?'Recent execution history is limited to 200 runs. Older work may be missing.':'Showing recorded work matching the current view.'} Absence of a run does not mean an agent is idle.</p>
 </aside>;
}
