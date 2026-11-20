import {AgentTypePill} from './agent-type-pill.jsx';
import semantics from '../static/entity-semantics.json';
import React,{useMemo,useState,useEffect} from 'react';
import {agentWork} from './fleet-work.mjs';

export function AgentWork({nodes,agents,agentId,setAgentId,Avatar,loaded,error,generated,limited,ask,scope,scopeColor}){
 const [expanded,setExpanded]=useState({}),[pending,setPending]=useState(''),[failure,setFailure]=useState(''),[updates,setUpdates]=useState({});
 async function move(node,status){
  const id=node.record_id||node.record?.id;if(!id)return;setPending(id);setFailure('');
  try{
   const path='/hfl-corpus/timeline/items/'+encodeURIComponent(id),csrf=JSON.parse(document.querySelector('[data-memory-csrf]')?.textContent||'""');
   const read=await fetch(path);if(!read.ok)throw Error('Could not load the Action.');const {item}=await read.json();
   const response=await fetch(path,{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({version:item.version,status})});
   const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Could not update the Action.');
   setUpdates(old=>({...old,[node.id]:result.item.status}));window.dispatchEvent(new CustomEvent('hfl:actions-updated',{detail:{fleetUpdate:{id:node.id,item:result.item}}}));
  }catch(e){setFailure(e.message);}finally{setPending('');}
 }
 const agent=agents.find(a=>a.id===agentId);
 const groups=useMemo(()=>agentWork(nodes,agentId),[nodes,agentId]);
 useEffect(()=>setExpanded({}),[agentId,scope]);
 useEffect(()=>setUpdates({}),[nodes]);
 const sections=[['attention','Needs attention'],['running','Running'],['queued','Queued'],['assigned','Assigned'],['recent','Recent results']];
 const count=Object.values(groups).reduce((n,rows)=>n+rows.length,0);
 return <aside className="fleet-work-panel" aria-label="Agent work">
  <header><h2>Agent work</h2><button type="button" className="fleet-work-ask" aria-label="Ask Butler" title="Ask Butler about this work" onClick={()=>ask(agent)}><svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/></svg></button></header>
  <div className="fleet-work-agent"><div className="fleet-work-agent-heading"><label htmlFor="fleet-work-agent-select">Agent</label><span className="activity-view-context fleet-work-scope"><span className="activity-view-name" title={scope} style={{borderLeft:scopeColor?'3px solid '+scopeColor:undefined}}>{scope}</span></span></div><select id="fleet-work-agent-select" aria-label="Work agent" value={agentId} onChange={event=>setAgentId(event.target.value)}><option value="">All matching agents</option>{agents.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></div>
  <p className="fleet-work-freshness">{generated?'Updated '+new Date(generated).toLocaleTimeString():'Waiting for recorded work'}</p>
  {failure&&<p role="alert">{failure}</p>}
  {error&&<p role="status">Some work could not refresh. Displayed records may be stale.</p>}
  {!loaded?<p role="status">Loading agent work…</p>:!count?<p>{agent?'No assigned work or recorded runs for '+agent.name+' in this Space.':'No assigned work or recorded agent runs in this Space.'}</p>:sections.map(([key,label])=>groups[key].length>0&&<section key={key} aria-label={label}>
   <h3>{label} <span>{groups[key].length}</span></h3>
   {groups[key].slice(0,expanded[key]||5).map(node=>{
    const run=node.execution, assigned=[...new Set([...(node.agent_ids||[]),...(run?.agent_id?[run.agent_id]:[])])].map(id=>agents.find(a=>a.id===id)).filter(Boolean);
    const status=updates[node.id]||node.record?.status||node.state, href=node.url||run?.url;
    return <article key={node.id}>
     <div className="fleet-work-card-meta">{status&&<span className="fleet-work-pill" data-status={status}>{semantics.action.labels[status]||status}</span>}<span className="fleet-work-avatars">{assigned.map(a=><span key={a.id} title={a.name}><Avatar agent={a}/></span>)}</span></div>
     <a className="fleet-work-title" href={href} onClick={node.kind==='action'?event=>{event.preventDefault();window.HflIdeas.openAction(node.record_id||node.record?.id);}:undefined}>{node.label}</a>
     <div className="fleet-work-agent-labels">{assigned.length?assigned.map(a=><span key={a.id}>{a.name} <AgentTypePill agent={a}/></span>):'Agent run'}</div>
     {run?<span className="fleet-work-pill fleet-run-pill" data-status={run.state}>Run: {run.state.replaceAll('_',' ')}</span>:<small>Not started</small>}
     {run?.updated_at&&<time dateTime={run.updated_at}>{new Date(run.updated_at).toLocaleString()}</time>}
     {node.kind==='action'?<div className="fleet-work-action-controls"><button type="button" onClick={()=>window.HflIdeas.openAction(node.record_id||node.record?.id)}>Open</button>{[['active','Ready'],['dismissed','Dismiss'],['done','Done']].filter(([value])=>value!==status).map(([value,label])=><button key={value} type="button" disabled={!!pending} onClick={()=>move(node,value)}>{label}</button>)}</div>:<a className="fleet-work-open" href={run?.url||href}>{key==='attention'?'Review run':'Inspect run'}</a>}
    </article>;
   })}
   {groups[key].length>5&&<button className="fleet-work-more" type="button" onClick={()=>setExpanded(old=>({...old,[key]:(old[key]||5)>=groups[key].length?5:(old[key]||5)+20}))}>{(expanded[key]||5)>=groups[key].length?'Show less':'Show more ('+(groups[key].length-(expanded[key]||5))+')'}</button>}
  </section>)}
  <p className="fleet-work-freshness">{limited?'Showing a limited snapshot of assigned work and agent runs.':'Assigned work and agent runs in the selected Spaces. Graph filters do not apply.'}</p>
 </aside>;
}
