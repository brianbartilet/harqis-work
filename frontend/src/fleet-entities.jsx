import React,{useEffect,useState} from 'react';

export function FleetEntities({agent,node,api,refresh}){
 const [data,setData]=useState(null),[query,setQuery]=useState(''),[kind,setKind]=useState('application'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[preview,setPreview]=useState(null);
 useEffect(()=>{let disposed=false;setData(null);setPreview(null);api('/entities').then(v=>{if(!disposed)setData(v);}).catch(e=>{if(!disposed)setError(e.message);});return()=>{disposed=true;};},[agent?.id,node?.id]);
 async function run(fn){setBusy(true);setError('');try{await fn();setData(await api('/entities'));await refresh();}catch(e){setError(e.message);}finally{setBusy(false);}}
 const items=(data?.items||[]).filter(v=>node?v.kind===node.kind&&v.id!==node.id:v.kind===kind);
 const matches=items.filter(v=>(v.label+' '+v.source+' '+v.namespace).toLowerCase().includes(query.toLowerCase())).slice(0,30);
 const selected=new Set((data?.edges||[]).filter(e=>e.source==='agent:'+agent?.id&&e.relation==='linked').map(e=>e.target));
 const suggestions=node?matches.filter(v=>v.label.toLowerCase()===node.label.toLowerCase()):[];
 return <details className="fleet-description-details"><summary>{agent?'Connected entities':'Review entity identity'}</summary>
 <div className="fleet-entity-controls">
 {error&&<p role="alert">{error}</p>}
 {agent?.connector_provider==='nod'&&<button disabled={busy} onClick={()=>run(async()=>{const result=await api('/nod/agents/'+agent.id+'/refresh',{},'/integrations/api');setError((result.warnings||[]).join(' '));})}>Refresh Nod entities</button>}
 <p>{agent?'Link existing entities for this agent. Associations do not grant account access. Discovered connections remain managed in their source app.':'Merge only identities you have verified represent the same object. Accounts remain separate from applications.'}</p>
 {!data?<p role="status">Loading entities…</p>:<>
 {agent&&<><p>{selected.size} manually linked</p><div className="fleet-related">{data.items.filter(v=>selected.has(v.id)).map(v=><span className="fleet-badge" key={v.id}>{v.label}</span>)}</div><label>Entity type<select aria-label="Entity type" value={kind} onChange={e=>setKind(e.target.value)}>{['application','account','schedule','connector'].map(k=><option key={k}>{k}</option>)}</select></label></>}
 <label>Find entities<input type="search" aria-label="Find entities" value={query} onChange={e=>setQuery(e.target.value)}/></label>
 {suggestions.length>0&&<p>Possible duplicate names found. Compare their source identities before merging.</p>}
 <div className="fleet-output-list">{matches.map(v=><div key={v.id} className="fleet-entity-option"><strong>{v.label}</strong><small>{v.kind} · {v.source} · {v.state}</small>{agent?<label className="fleet-check"><input type="checkbox" disabled={busy} checked={selected.has(v.id)} onChange={e=>run(()=>api('/entities/associate',{agent_id:agent.id,entity_id:v.id,linked:e.target.checked}))}/>Link to {agent.name}</label>:<button disabled={busy} onClick={()=>run(async()=>setPreview(await api('/entities/merge',{source:node.id,target:v.id})))}>Compare merge into {v.label}</button>}</div>)}</div>
 {!matches.length&&<p>No matching entities. Connect a source or refresh its inventory.</p>}{matches.length===30&&<p>Showing 30 matches. Narrow your search for more.</p>}
 {preview&&<section aria-label="Merge preview"><h3>Merge preview</h3><p>{preview.source.label} → {preview.target.label}</p><p>{preview.effect}</p><p>Source: {preview.source.namespace} / {preview.source.remote_id}</p><p>Target: {preview.target.namespace} / {preview.target.remote_id}</p><button disabled={busy} onClick={()=>run(async()=>{await api('/entities/merge',{source:preview.source.id,target:preview.target.id,confirmed:true});setPreview(null);})}>Confirm merge</button><button onClick={()=>setPreview(null)}>Cancel</button></section>}
 {data.merges.filter(m=>m.active&&(!node||m.target===node.id)).map(m=><div key={m.id}><p>Merged {new Date(m.created).toLocaleString()}</p><button disabled={busy} onClick={()=>run(()=>api('/entities/unmerge',{merge_id:m.id}))}>Undo merge</button></div>)}
 </>}
 </div></details>;
}
