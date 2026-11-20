import React,{useEffect,useState} from 'react';

const empty={id:'',name:'',description:'',color:'#a78bfa',keywords:[],equivalents:[],hidden:false,version:0};
export function EntityCatalog({api,refresh,Dialog,close}){
 const [data,setData]=useState(null),[query,setQuery]=useState(''),[draft,setDraft]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[removing,setRemoving]=useState(null);
 const load=()=>api('/entity-types').then(setData);
 useEffect(()=>{let disposed=false;api('/entity-types').then(v=>{if(!disposed)setData(v);}).catch(e=>{if(!disposed)setError(e.message);});return()=>{disposed=true;};},[]);
 async function run(fn){setBusy(true);setError('');setMessage('');try{await fn();await load();await refresh();}catch(e){setError(e.message);}finally{setBusy(false);}}
 const set=(key,value)=>setDraft(v=>({...v,[key]:value}));
 const mapping=(index,key,value)=>set('equivalents',draft.equivalents.map((v,i)=>i===index?{...v,[key]:value}:v));
 const items=(data?.items||[]).filter(v=>[v.name,v.description,...v.keywords,...v.equivalents.map(m=>m.agent_type+' '+m.source_object)].join(' ').toLowerCase().includes(query.toLowerCase()));
 return <Dialog title="Manage entity types" className="fleet-agent-editor fleet-type-manager" close={close}>
 <div className="fleet-form">
 <p>Shared Fleet types, with equivalents for each agent type. Mapping keywords help discovery; explicit equivalents control normalization.</p>
 {error&&<p role="alert" className="fleet-alert">{error}</p>}{message&&<p role="status">{message}</p>}
 {!data?<><p role="status">Loading entity types…</p>{error&&<button onClick={()=>run(load)}>Retry</button>}</>:draft?<form onSubmit={e=>{e.preventDefault();run(async()=>{await api('/entity-types',{...draft,keywords:draft.keywords.map(v=>v.trim()).filter(Boolean)});setDraft(null);setMessage('Entity type saved.');});}}>
 <div className="fleet-columns"><label>Name<input required maxLength={80} value={draft.name} onChange={e=>{const name=e.target.value;setDraft(v=>({...v,name,...(!v.version&&!v.builtin?{id:name.toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,'').slice(0,40)}:{})}));}}/></label><label>Type key<input required pattern="[a-z][a-z0-9_]{0,39}" disabled={Boolean(draft.version)||draft.builtin} value={draft.id} onChange={e=>set('id',e.target.value)}/></label></div>
 <label>Description<textarea required maxLength={1000} value={draft.description} onChange={e=>set('description',e.target.value)}/></label>
 <fieldset><legend>Color</legend><div className="fleet-swatch">{[...new Set([draft.color,...data.colors])].map(c=><button key={c} type="button" style={{background:c}} aria-label={'Color '+c} aria-pressed={draft.color===c} onClick={()=>set('color',c)}/>)}</div></fieldset>
 <label>Mapping keywords<input value={draft.keywords.join(',')} onChange={e=>set('keywords',e.target.value.split(','))}/></label>
 <fieldset><legend>Agent-type equivalents</legend><p>Use the source object's name, such as skills or schedules. A source object can map to one Fleet type.</p>
 {draft.equivalents.map((m,i)=><div className="fleet-type-mapping" key={i}><label>Agent type<select value={m.agent_type} onChange={e=>mapping(i,'agent_type',e.target.value)}>{data.agent_types.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label><label>Source object<input required maxLength={100} value={m.source_object} onChange={e=>mapping(i,'source_object',e.target.value)}/></label><button type="button" aria-label={'Remove equivalent '+(i+1)} onClick={()=>set('equivalents',draft.equivalents.filter((_,n)=>i!==n))}>Remove</button></div>)}
 <button type="button" onClick={()=>set('equivalents',[...draft.equivalents,{agent_type:data.agent_types[0].id,source_object:''}])}>Add equivalent</button></fieldset>
 <label className="fleet-check"><input type="checkbox" checked={draft.hidden} onChange={e=>set('hidden',e.target.checked)}/>Hide from the entity legend</label>
 <div className="fleet-actions"><button disabled={busy} className="fleet-primary">Save type</button><button type="button" disabled={busy} onClick={()=>setDraft(null)}>Cancel</button></div>
 </form>:<>
 <div className="fleet-actions"><button className="fleet-primary" disabled={busy} onClick={()=>{setDraft({...empty});setError('');}}>Add entity type</button><button disabled={busy} onClick={()=>run(async()=>{const result=await api('/entity-types/cleanup',{});setMessage(result.removed+' empty records removed. A recovery audit was saved.');})}>Clean empty records</button></div>
 <label>Find entity types<input type="search" value={query} onChange={e=>setQuery(e.target.value)}/></label>
 {removing&&<section aria-label="Remove entity type"><p>Remove {removing.name}? Choose another type to reassign existing objects and mappings. A recovery audit will be kept.</p><label>Reassign to<select value={removing.replacement||""} onChange={e=>setRemoving(v=>({...v,replacement:e.target.value}))}><option value="">Remove only if unused</option>{data.items.filter(v=>v.id!==removing.id).map(v=><option key={v.id} value={v.id}>{v.name}</option>)}</select></label><button disabled={busy} onClick={()=>run(async()=>{await api('/entity-types/remove',{id:removing.id,replacement:removing.replacement||null});setRemoving(null);setMessage('Entity type removed.');})}>Confirm removal</button><button onClick={()=>setRemoving(null)}>Cancel removal</button></section>}
 <div className="fleet-type-list">{items.slice(0,80).map(item=><article className="fleet-type-card" key={item.id}><h3><i style={{background:item.color}}/>{item.name}<small>{item.count} visible objects{item.hidden?' · Hidden':''}</small></h3><p>{item.description}</p><p className="fleet-type-keywords">{item.keywords.join(' · ')}</p>
 <ul>{item.equivalents.map(m=><li key={m.agent_type+':'+m.source_object}><strong>{data.agent_types.find(a=>a.id===m.agent_type)?.name||m.agent_type}</strong> · {m.source_object} → {item.name}<small>{m.scope} · {m.status==='documented'?'Documented; discovery unverified':m.status==='verified'?'Verified mapping':'Manual mapping'}</small></li>)}</ul>
 {!item.equivalents.length&&<p>No agent-type equivalents yet.</p>}<div className="fleet-actions"><button disabled={busy} aria-label={'Edit '+item.name} onClick={()=>{setDraft(structuredClone(item));setRemoving(null);setError('');}}>Edit</button>{!item.builtin&&<button disabled={busy} aria-label={'Remove '+item.name} onClick={()=>setRemoving(item)}>Remove</button>}</div></article>)}</div>
 {!items.length&&<p>No matching entity types.</p>}{items.length>80&&<p>Showing 80 matches. Refine your search.</p>}
 </>}
 </div></Dialog>;
}

export function GrokOutputRefresh({agent,api,refresh}){
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
 return <div className="fleet-grok-outputs"><div className="fleet-nod-toolbar"><button disabled={busy||!agent.active||agent.mock||agent.remote_available===false} onClick={async()=>{setBusy(true);setError('');setMessage('');try{const result=await api('/items/'+agent.id+'/grok-outputs',{});setMessage(result.recorded+' outputs refreshed from the latest '+result.scanned+' transcript entries. '+result.skipped+' non-output or unavailable entries skipped.'+(result.limited?' Older history is not included.':''));await refresh();}catch(e){setError(e.message);}finally{setBusy(false);}}}>{busy?'Refreshing…':'Refresh Grok outputs'}</button></div><p>Read-only retrieval of the latest 50 transcript entries. Saved replies can inform Butler briefings.</p>{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}</div>;
}
