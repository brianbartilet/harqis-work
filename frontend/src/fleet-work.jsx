import semantics from '../static/entity-semantics.json';
import React,{useMemo,useState,useEffect} from 'react';
import {agentWork} from './fleet-work.mjs';

export function AgentWork({nodes,agents,agentId,setAgentId,Avatar,loaded,error,generated,limited,ask,scope,scopeColor}){
 const [expanded,setExpanded]=useState({});
 const agent=agents.find(a=>a.id===agentId);
 const groups=useMemo(()=>agentWork(nodes,agentId),[nodes,agentId]);
 useEffect(()=>setExpanded({}),[agentId,scope]);
 const sections=[['attention','Needs attention'],['running','Running'],['queued','Queued'],['assigned','Assigned'],['recent','Recent results']];
 const count=Object.values(groups).reduce((n,rows)=>n+rows.length,0);
 return <aside className="fleet-work-panel" aria-label="Agent work">
  <header><h2>Agent work</h2><button type="button" title="Ask Butler about this work" onClick={()=>ask(agent)}>Ask Butler</button></header>
  <div className="activity-view-context fleet-work-scope"><span className="activity-view-name" style={{borderLeft:scopeColor?'3px solid '+scopeColor:undefined}}>{scope}</span></div>
  <label className="fleet-work-agent">Agent<select aria-label="Work agent" value={agentId} onChange={event=>setAgentId(event.target.value)}><option value="">All matching agents</option>{agents.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
  <p className="fleet-work-freshness">{generated?'Updated '+new Date(generated).toLocaleTimeString():'Waiting for recorded work'}</p>
  {error&&<p role="status">Some work could not refresh. Displayed records may be stale.</p>}
  {!loaded?<p role="status">Loading agent work…</p>:!count?<p>{agent?'No assigned work or recorded runs for '+agent.name+' in this Space.':'No assigned work or recorded agent runs in this Space.'}</p>:sections.map(([key,label])=>groups[key].length>0&&<section key={key} aria-label={label}>
   <h3>{label} <span>{groups[key].length}</span></h3>
   {groups[key].slice(0,expanded[key]||5).map(node=>{
    const run=node.execution, assigned=[...new Set([...(node.agent_ids||[]),...(run?.agent_id?[run.agent_id]:[])])].map(id=>agents.find(a=>a.id===id)).filter(Boolean);
    const status=node.record?.status||node.state, href=node.url||run?.url;
    return <article key={node.id}>
     <div className="fleet-work-card-meta">{status&&<span className="fleet-work-pill" data-status={status}>{semantics.action.labels[status]||status}</span>}<span className="fleet-work-avatars">{assigned.map(a=><span key={a.id} title={a.name}><Avatar agent={a}/></span>)}</span></div>
     <a className="fleet-work-title" href={href}>{node.label}</a>
     <small>{assigned.map(a=>a.name).join(', ')||'Agent run'}</small>
     {run?<span className="fleet-work-pill fleet-run-pill" data-status={run.state}>Run: {run.state.replaceAll('_',' ')}</span>:<small>Not started</small>}
     {run?.updated_at&&<time dateTime={run.updated_at}>{new Date(run.updated_at).toLocaleString()}</time>}
     <a className="fleet-work-open" href={run?.url||href}>{run?(key==='attention'?'Review run':'Inspect run'):'Open action'}</a>
    </article>;
   })}
   {groups[key].length>5&&<button className="fleet-work-more" type="button" onClick={()=>setExpanded(old=>({...old,[key]:(old[key]||5)>=groups[key].length?5:(old[key]||5)+20}))}>{(expanded[key]||5)>=groups[key].length?'Show less':'Show more ('+(groups[key].length-(expanded[key]||5))+')'}</button>}
  </section>)}
  <p className="fleet-work-freshness">{limited?'Showing a limited snapshot of assigned work and agent runs.':'Assigned work and agent runs in the selected Spaces. Graph filters do not apply.'}</p>
 </aside>;
}
