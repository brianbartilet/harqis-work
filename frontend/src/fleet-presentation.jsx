import React,{useState,useEffect} from 'react';
export function OwnerCard({node,onSelect}){return node&&<section className="fleet-owner"><h3>Corpus owner</h3><button className="fleet-relationship-card" onClick={()=>onSelect(node.id)}>{node.avatar_url?<img src={node.avatar_url} alt=""/>:<span className="fleet-owner-avatar">{node.label.slice(0,1)}</span>}<span><strong>{node.label}</strong><small>Activity, actions and ideas</small></span></button></section>;}
export function Description({node}){
 const [loaded,setLoaded]=useState(null),[error,setError]=useState('');
 useEffect(()=>{setLoaded(null);setError('');if(!node.corpus_entry)return;const controller=new AbortController();fetch('/agents/api/entries/'+encodeURIComponent(node.id.slice(6))+'/description',{signal:controller.signal}).then(async response=>{if(!response.ok)throw Error('Formatted description unavailable. Open the entry for details.');const data=await response.json();if(!controller.signal.aborted)setLoaded({id:node.id,html:data.html});}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[node.id,node.summary]);
 const html=node.summary_html||(loaded?.id===node.id?loaded.html:'');
 return <>{html?<div className="fleet-description markdown-body" dangerouslySetInnerHTML={{__html:html}}/>:<div className="fleet-description fleet-plain-description">{node.summary}</div>}{error&&<p role="status">{error}</p>}</>;
}
export function Relationships({node,data,onSelect}){
 const [limit,setLimit]=useState(30),groups=new Map(),nodes=new Map(data.nodes.map(n=>[n.id,n]));
 for(const edge of data.edges){if(edge.source!==node.id&&edge.target!==node.id)continue;const id=edge.source===node.id?edge.target:edge.source,related=nodes.get(id);if(!related)continue;if(!groups.has(id))groups.set(id,{related,relations:new Set()});groups.get(id).relations.add(edge.relation);}
 return <div className="fleet-relationships">{[...groups.values()].slice(0,limit).map(({related,relations})=><button className="fleet-relationship-card" key={related.id} onClick={()=>onSelect(related.id)}><span><strong>{related.label}</strong><small>{[...relations].map(value=>value.replaceAll('-', ' ')).join(' · ')}</small></span><span aria-hidden="true">›</span></button>)}{groups.size>limit&&<button onClick={()=>setLimit(v=>v+30)}>Show more ({groups.size-limit})</button>}</div>;
}
export function IdeaAssignment({node,agents,api}){
 const [selected,setSelected]=useState(node.assigned_agent_id||''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 return <form className="fleet-idea-assignment" onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{await api('/ideas/'+encodeURIComponent(node.record_id)+'/assignment',{agent_id:selected,previous_agent_id:node.assigned_agent_id||''});window.dispatchEvent(new Event('hfl:agent-updated'));}catch(e){setError(e.message);}finally{setBusy(false);}}}><label>Assign agent<select value={selected} onChange={e=>setSelected(e.target.value)} disabled={busy}><option value="">Unassigned</option>{agents.filter(a=>a.active||a.id===selected).map(a=><option key={a.id} value={a.id} disabled={!a.active}>{a.name}{!a.active?' (inactive)':''}</option>)}</select></label><button disabled={busy||selected===(node.assigned_agent_id||'')}>{busy?'Saving…':'Save assignment'}</button>{error&&<p role="alert">{error}</p>}</form>;
}
