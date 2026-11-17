import React,{useEffect,useRef,useState} from 'react';

export function SpecialistPicker({draft,onChange,catalog,api,previewPayload,agentId}){
 const [items,setItems]=useState([]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const [query,setQuery]=useState(''),[source,setSource]=useState('agency-agents'),[choice,setChoice]=useState(''),[detail,setDetail]=useState(null),[detailLoading,setDetailLoading]=useState(false);
 const [replaceDescription,setReplaceDescription]=useState(false),[preview,setPreview]=useState(null),[previewBusy,setPreviewBusy]=useState(false);
 const [division,setDivision]=useState(''),[limit,setLimit]=useState(30);
 const selected=draft.specialist_profile;
 const previewVersion=useRef(0);
 useEffect(()=>{let stale=false;setLoading(true);setError('');api('/specialists').then(v=>{if(!stale)setItems(v.items);}).catch(e=>{if(!stale)setError(e.message);}).finally(()=>{if(!stale)setLoading(false);});return()=>{stale=true;};},[retry]);
 useEffect(()=>{let stale=false;setDetail(null);setReplaceDescription(false);setError('');setDetailLoading(Boolean(choice));if(choice)api('/specialists/'+encodeURIComponent(choice)).then(v=>{if(!stale)setDetail(v);}).catch(e=>{if(!stale)setError(e.message);}).finally(()=>{if(!stale)setDetailLoading(false);});return()=>{stale=true;};},[choice,retry]);
 useEffect(()=>{previewVersion.current++;setPreview(null);},[draft]);
 useEffect(()=>{setLimit(30);},[query,division]);
 const matches=source==='custom'?[]:items.filter(p=>(!division||p.division===division)&&query.trim().toLowerCase().split(/\s+/).every(term=>`${p.name} ${p.description} ${p.division}`.toLowerCase().includes(term))).sort((a,b)=>Number(b.classification===draft.classification)-Number(a.classification===draft.classification));
 function apply(){onChange({specialist_profile:{id:detail.id,revision:detail.revision,hash:detail.hash},...(!draft.description||replaceDescription?{description:detail.description}:{})});setPreview(null);}
 async function inspect(){const version=previewVersion.current;setPreviewBusy(true);setError('');try{const value=await api('/specialist-preview',{agent_id:agentId,profile:{...previewPayload(),name:draft.name||'Preview agent'}});if(version===previewVersion.current)setPreview(value);}catch(e){if(version===previewVersion.current)setError(e.message);}finally{setPreviewBusy(false);}}
 const selectedName=selected?.name||items.find(p=>p.id===selected?.id)?.name||'Saved specialist';
 return <fieldset className="fleet-specialists"><legend>Specialist profile</legend>
  <p>Search the full pinned catalog. Profiles matching your classification appear first. HARQIS skill recommendations are available for selected profiles.</p>
  <label>Profile source<select value={source} onChange={e=>{setSource(e.target.value);setChoice('');}}><option value="agency-agents">Agency Agents · full catalog</option><option value="custom">Custom · no catalog browsing</option></select></label>
  {selected&&<div className="fleet-specialist-selected"><strong>{selectedName}</strong><p>{draft.runtime==='hermes'?'Applied when you save and start a new Hermes session.':'Provider setup required. Fleet stores this selection for reference.'}</p><p>Saved revision {selected.revision.slice(0,12)}</p><button type="button" onClick={()=>onChange({specialist_profile:null})}>Remove profile</button></div>}
  {source!=='custom'&&<><label>Search specialist profiles<input type="search" value={query} placeholder="Search names or descriptions" onChange={e=>setQuery(e.target.value)}/></label>
  <label>Division<select aria-label="Specialist division" value={division} onChange={e=>setDivision(e.target.value)}><option value="">All divisions</option>{[...new Set(items.map(p=>p.division))].sort().map(name=><option key={name} value={name}>{name}</option>)}</select></label>
  {loading?<p role="status">Loading profiles…</p>:<><p role="status">Showing {Math.min(limit,matches.length)} of {matches.length} matching profiles · {items.length} profiles available</p><div className="fleet-specialist-results" role="group" aria-label="Available specialist profiles">{matches.slice(0,limit).map(p=><button type="button" key={p.id} aria-label={'Preview '+p.name} aria-pressed={choice===p.id} onClick={()=>setChoice(p.id)}><strong>{p.name}</strong><span>{p.description}</span><small>{p.division} · {catalog.classifications.find(c=>c.id===p.classification)?.name||p.classification}{p.classification===draft.classification?' · Matches classification':''}</small></button>)}</div>{matches.length>limit&&<button type="button" onClick={()=>setLimit(v=>v+30)}>Show more profiles</button>}{!matches.length&&<p>No matching profiles. Try another search or division. Your saved selection is preserved.</p>}</>}
  {detailLoading&&<p role="status">Loading profile description…</p>}
  {detail&&<article className="fleet-specialist-detail"><h3>{detail.name}</h3><p>{detail.description}</p>{detail.use?<dl><dt>Good for</dt><dd>{detail.use}</dd><dt>Expected output</dt><dd>{detail.output}</dd><dt>Example task · HARQIS helper</dt><dd>{detail.example}</dd></dl>:<p>Read the full instructions for this profile’s workflow and deliverables. No HARQIS-specific helper or skill mapping has been curated yet.</p>}
   <details><summary>Full specialist instructions</summary><div className="fleet-specialist-markdown" dangerouslySetInnerHTML={{__html:detail.html}}/></details>
   <a href={detail.source_url} target="_blank" rel="noopener noreferrer">Source documentation</a><p>Agency Agents · MIT · revision {detail.revision.slice(0,12)}. Helpers and skill suggestions are curated by HARQIS.</p>
   {draft.description&&<label className="fleet-check"><input type="checkbox" checked={replaceDescription} onChange={e=>setReplaceDescription(e.target.checked)}/>Replace my description with this profile’s description</label>}
   <button type="button" onClick={apply}>Use this profile</button>
   {draft.runtime==='hermes'&&<fieldset><legend>Suggested HARQIS skills</legend>{detail.skills.map(id=>{const skill=catalog.skills.find(s=>s.id===id);return skill?<label className="fleet-check" key={id}><input type="checkbox" checked={draft.skills.includes(id)} onChange={e=>onChange({skills:e.target.checked?[...draft.skills,id]:draft.skills.filter(s=>s!==id)})}/>{skill.name}</label>:<p key={id}>Suggested skill unavailable: {id.replace('repo:','')}</p>;})}<p>Skills are optional. Profile selection does not grant tool access or start tasks.</p></fieldset>}
  </article>}</>}
  {selected&&<><button type="button" disabled={previewBusy} onClick={inspect}>{previewBusy?'Preparing preview…':'Preview effective instructions'}</button>{preview&&<details open><summary>{preview.status}</summary><pre className="fleet-specialist-preview">{preview.instructions||'No locally applied execution instructions.'}</pre></details>}</>}
  {error&&<div role="alert"><p>{error}</p><button type="button" onClick={()=>setRetry(v=>v+1)}>Retry loading profiles</button></div>}
 </fieldset>;
}
