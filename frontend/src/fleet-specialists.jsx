import React,{useEffect,useRef,useState} from 'react';
import {ProfileSources} from './fleet-profile-sources.jsx';

export function SpecialistPicker({draft,onChange,catalog,api,previewPayload,agentId,actionContext=false,showSources=true}){
 const [items,setItems]=useState([]),[sources,setSources]=useState([]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0),[update,setUpdate]=useState(null);
 const [query,setQuery]=useState(''),[source,setSource]=useState(''),[choice,setChoice]=useState(''),[detail,setDetail]=useState(null),[detailLoading,setDetailLoading]=useState(false);
 const [replaceDescription,setReplaceDescription]=useState(false),[preview,setPreview]=useState(null),[previewBusy,setPreviewBusy]=useState(false);
 const [division,setDivision]=useState(''),[limit,setLimit]=useState(30);
 const selected=draft.specialist_profile;
 const previewVersion=useRef(0);
 useEffect(()=>{if(detail)document.querySelector('.fleet-specialization-dialog .fleet-specialist-detail')?.scrollIntoView({block:'start'});},[detail]);
 useEffect(()=>{let stale=false;setLoading(true);setError('');Promise.all([api('/specialists'),api('/profile-sources')]).then(([profiles,origins])=>{if(!stale){setItems(profiles.items);setSources(origins.items);}}).catch(e=>{if(!stale)setError(e.message);}).finally(()=>{if(!stale)setLoading(false);});return()=>{stale=true;};},[retry]);
 useEffect(()=>{let stale=false;setDetail(null);setReplaceDescription(false);setError('');setDetailLoading(Boolean(choice));if(choice)api('/specialists/'+encodeURIComponent(choice)).then(v=>{if(!stale)setDetail(v);}).catch(e=>{if(!stale)setError(e.message);}).finally(()=>{if(!stale)setDetailLoading(false);});return()=>{stale=true;};},[choice,retry]);
 useEffect(()=>{previewVersion.current++;setPreview(null);setUpdate(null);},[draft]);
 useEffect(()=>{setLimit(30);},[query,division,source]);
 const matches=source==='custom'?[]:items.filter(p=>(!source||p.source===source)&&(!division||p.division===division)&&query.trim().toLowerCase().split(/\s+/).every(term=>`${p.name} ${p.description} ${p.division} ${p.source_name}`.toLowerCase().includes(term))).sort((a,b)=>Number(b.classification===draft.classification)-Number(a.classification===draft.classification));
 function apply(){onChange({specialist_profile:{id:detail.id,revision:detail.revision,hash:detail.hash},...(!draft.description||replaceDescription?{description:detail.description}:{})},detail);setPreview(null);}
 async function inspect(){const version=previewVersion.current;setPreviewBusy(true);setError('');try{const value=await api('/specialist-preview',{agent_id:agentId,profile:{...previewPayload(),name:draft.name||'Preview agent'}});if(version===previewVersion.current)setPreview(value);}catch(e){if(version===previewVersion.current)setError(e.message);}finally{setPreviewBusy(false);}}
 const selectedId=selected?.id?.includes(':')?selected.id:'agency-agents:'+selected?.id;
 const available=items.find(p=>p.id===selectedId);
 const selectedName=selected?.name||available?.name||'Saved specialist';
 async function reviewUpdate(){setError('');try{setUpdate(await api('/specialist-update-preview',{agent_id:agentId}));}catch(e){setError(e.message);}}
 return <fieldset className={'fleet-specialists'+(choice?' is-previewing':'')}><legend>Specialist profile</legend>
  {showSources&&<ProfileSources contextLabel={actionContext?"this Action":"Add agent"} items={sources} api={api} changed={()=>{setRetry(v=>v+1);return Promise.resolve();}}/>}
  {!actionContext&&<p>Search enabled sources. Profiles matching your classification appear first. Opening a profile downloads and caches its indexed instructions.</p>}
  <label>Profile source<select aria-label="Profile source" value={source} onChange={e=>{setSource(e.target.value);setDivision('');setChoice('');}}><option value="">All enabled sources</option>{sources.filter(s=>s.enabled).map(s=><option key={s.id} value={s.id}>{s.name}</option>)}{source&&source!=='custom'&&!sources.some(s=>s.enabled&&s.id===source)&&<option value={source}>Unavailable source</option>}<option value="custom">Custom · no catalog browsing</option></select></label>
  {selected&&!actionContext&&<div className="fleet-specialist-selected"><strong>{selectedName}</strong><p>{actionContext?'Applied to new runs of this Action.':draft.runtime==='hermes'?'Applied when you save and start a new Hermes session.':'Provider setup required. Fleet stores this selection for reference.'}</p><p>Saved revision {selected.revision.slice(0,12)}</p><button type="button" onClick={()=>onChange({specialist_profile:null})}>Remove profile</button></div>}
  {selected&&available&&available.hash!==selected.hash&&agentId&&!actionContext&&<div><p>Update available. Your saved instructions have not changed.</p><button type="button" onClick={reviewUpdate}>Review profile update</button></div>}
  {selected&&!available&&!loading&&<p>This profile is no longer in an enabled source. Its saved instructions remain available.</p>}
  {update&&<details open><summary>Instruction changes</summary><pre className="fleet-specialist-preview">{update.diff}</pre><button type="button" onClick={()=>{onChange({specialist_profile:{id:update.profile.id,revision:update.profile.revision,hash:update.profile.hash}});setChoice(update.profile.id);}}>Apply reviewed update</button><p>Save agent to keep this change. Existing sessions retain their original instructions.</p></details>}
  {source!=='custom'&&<><label>Search specialist profiles<input type="search" value={query} placeholder="Search names or descriptions" onChange={e=>setQuery(e.target.value)}/></label>
  <label>Division<select aria-label="Specialist division" value={division} onChange={e=>setDivision(e.target.value)}><option value="">All divisions</option>{[...new Set(items.map(p=>p.division))].sort().map(name=><option key={name} value={name}>{name}</option>)}</select></label>
  {loading?<p role="status">Loading profiles…</p>:<><p role="status">Showing {Math.min(limit,matches.length)} of {matches.length} matching profiles · {items.length} profiles available</p><div className="fleet-specialist-results" role="group" aria-label="Available specialist profiles">{matches.slice(0,limit).map(p=><button type="button" key={p.id} aria-label={'Preview '+p.name} aria-pressed={choice===p.id} onClick={()=>setChoice(p.id)}><strong>{p.name}</strong><span>{p.description}</span><small>{p.source_name} · {p.division} · {catalog.classifications.find(c=>c.id===p.classification)?.name||p.classification}{p.classification===draft.classification?' · Matches classification':''}</small></button>)}</div>{!choice&&matches.length>limit&&<button type="button" onClick={()=>setLimit(v=>v+30)}>Show more profiles</button>}{!matches.length&&<p>No matching profiles. Try another search or division. Your saved selection is preserved.</p>}</>}
  {choice&&<button type="button" onClick={()=>setChoice('')}>Back to profiles</button>}
  {detailLoading&&<p role="status">Loading profile description…</p>}
  {detail&&<article className="fleet-specialist-detail"><h3>{detail.name}</h3><p>{detail.description}</p>{actionContext&&detail.kind!=='skill-package'&&<button type="button" onClick={apply}>Use this profile</button>}{detail.use?<dl><dt>Good for</dt><dd>{detail.use}</dd><dt>Expected output</dt><dd>{detail.output}</dd><dt>Example task · HARQIS helper</dt><dd>{detail.example}</dd></dl>:!actionContext&&<p>Read the full instructions for this profile’s workflow and deliverables. No HARQIS-specific helper or skill mapping has been curated yet.</p>}
   <details><summary>Full specialist instructions</summary><div className="fleet-specialist-markdown" dangerouslySetInnerHTML={{__html:detail.html}}/></details>
   {detail.source_url&&<a href={detail.source_url} target="_blank" rel="noopener noreferrer">Source documentation</a>}<p>{detail.source_name} · revision {detail.revision.slice(0,12)}.{!actionContext&&' Helpers and skill suggestions are curated separately by HARQIS.'}</p>
   {draft.description&&<label className="fleet-check"><input type="checkbox" checked={replaceDescription} onChange={e=>setReplaceDescription(e.target.checked)}/>Replace my description with this profile’s description</label>}
   {detail.kind==='skill-package'?<p>This is a skill package, available here for preview only. Install it through the native skill workflow so its supporting files are included.</p>:!actionContext&&<button type="button" onClick={apply}>Use this profile</button>}
   {!actionContext&&draft.runtime==='hermes'&&<fieldset><legend>Suggested HARQIS skills</legend>{detail.skills.map(id=>{const skill=catalog.skills.find(s=>s.id===id);return skill?<label className="fleet-check" key={id}><input type="checkbox" checked={draft.skills.includes(id)} onChange={e=>onChange({skills:e.target.checked?[...draft.skills,id]:draft.skills.filter(s=>s!==id)})}/>{skill.name}</label>:<p key={id}>Suggested skill unavailable: {id.replace('repo:','')}</p>;})}<p>Skills are optional. Profile selection does not grant tool access or start tasks.</p></fieldset>}
  </article>}</>}
  {selected&&!actionContext&&<><button type="button" disabled={previewBusy} onClick={inspect}>{previewBusy?'Preparing preview…':'Preview effective instructions'}</button>{preview&&<details open><summary>{preview.status}</summary><pre className="fleet-specialist-preview">{preview.instructions||'No locally applied execution instructions.'}</pre></details>}</>}
  {error&&<div role="alert"><p>{error}</p><button type="button" onClick={()=>setRetry(v=>v+1)}>Retry loading profiles</button></div>}
 </fieldset>;
}


// Keep the agent form focused; browsing owns a separate, keyboard-dismissable dialog.
export function AgentSpecialization(props){
 const {draft,onChange,api}=props;
 const [open,setOpen]=useState(false),[selectionInfo,setSelectionInfo]=useState(null),[manage,setManage]=useState(false),[sources,setSources]=useState([]),[error,setError]=useState(''),[version,setVersion]=useState(0);
 const dialog=useRef(null),opener=useRef(null);
 const [working,setWorking]=useState(draft);
 useEffect(()=>{if(!open)return;opener.current=document.activeElement;dialog.current.showModal();return()=>opener.current?.focus();},[open]);
 useEffect(()=>{if(!open||!manage)return;let stale=false;setError('');api('/profile-sources').then(v=>{if(!stale)setSources(v.items);}).catch(e=>{if(!stale)setError(e.message);});return()=>{stale=true;};},[open,manage,version]);
 const selected=draft.specialist_profile;
 useEffect(()=>{if(!selected||selected.description||selectionInfo?.id===selected.id)return;let stale=false;api('/specialists').then(v=>{const row=v.items.find(p=>p.id===selected.id||p.id==='agency-agents:'+selected.id);if(!stale&&row)setSelectionInfo(row);}).catch(()=>{});return()=>{stale=true;};},[selected?.id,selected?.description]);
 const info=selectionInfo?.id===selected?.id?selectionInfo:null;
 return <section className="fleet-specialization-summary" aria-label="Agent specialization">
  <h3>Specialization</h3>
  <div className={selected?'fleet-selected-specialization-card':'fleet-specialization-empty'}>
   {selected?<><strong className="fleet-specialization-name">{selected.name||info?.name||'Saved specialist profile'}</strong><p className="fleet-specialization-description">{selected.description||info?.description||'No description available for this saved profile.'}</p>{(selected.source_name||info?.source_name)&&<small>{selected.source_name||info.source_name}</small>}</>:<p>No specialization selected.</p>}
   <div className="fleet-actions"><button type="button" onClick={()=>{setWorking(draft);setManage(false);setOpen(true);}}>{selected?'Change specialization':'Choose specialization'}</button>{selected&&<button type="button" onClick={()=>onChange({specialist_profile:null})}>Remove profile</button>}</div>
  </div>
  <small>{draft.runtime==='hermes'?'New sessions and assigned Actions inherit this specialization.':'Saved with this agent. Applying it in the provider requires connector support.'}</small>
  {open&&<dialog ref={dialog} className="fleet-specialization-dialog" aria-label="Choose specialization" onCancel={e=>{e.preventDefault();e.stopPropagation();setOpen(false);}} onKeyDown={e=>{if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();e.stopPropagation();}}}>
   <header className="fleet-dialog-head"><h2>Choose specialization</h2><button type="button" aria-label="Close specialization chooser" onClick={()=>setOpen(false)}>{String.fromCharCode(215)}</button></header>
   <div className="fleet-form fleet-specialization-body"><div className="fleet-actions"><p>{manage?'Manage sources shared across Fleet.':'Preview a profile, then apply it to this agent.'}</p><button type="button" onClick={()=>setManage(v=>!v)}>{manage?'Back to profiles':'Manage sources'}</button></div>
   {manage?<>{error&&<p role="alert">{error}</p>}<ProfileSources initialOpen contextLabel="the profile chooser" items={sources} api={api} changed={()=>{setVersion(v=>v+1);return Promise.resolve();}}/></>:<SpecialistPicker {...props} draft={working} previewPayload={()=>({...props.previewPayload(),skills:working.skills,specialist_profile:working.specialist_profile})} key={version} showSources={false} onChange={(patch,detail)=>{setWorking(v=>({...v,...patch}));if(patch.specialist_profile){onChange({skills:working.skills,...patch},detail);setSelectionInfo(detail||null);setOpen(false);}}}/>}
   </div>
  </dialog>}
 </section>;
}
