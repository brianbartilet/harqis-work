import React,{useState} from 'react';

const fresh=()=>({name:'',type:'github',location:'',ref:'main',paths:'*.md',enabled:true});
export function ProfileSources({items,api,changed,contextLabel="Add agent",initialOpen=false}){
 const [editing,setEditing]=useState(null),[draft,setDraft]=useState(fresh),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const set=(key,value)=>setDraft(old=>({...old,[key]:value}));
 function edit(source){setEditing(source?.id||'new');setDraft(source?{...source,paths:source.paths.join('\n')}:fresh());setError('');setNotice('');}
 async function run(action){setBusy(true);setError('');setNotice('');try{await action();await changed();}catch(e){setError(e.message);}finally{setBusy(false);}}
 function save(){return run(async()=>{const payload=Object.fromEntries(['name','type','location','ref','enabled'].map(key=>[key,draft[key]]));payload.paths=draft.paths.split('\n').map(v=>v.trim()).filter(Boolean);if(editing!=='new')payload.version=draft.version;await api('/profile-sources'+(editing==='new'?'':'/'+editing),payload);setEditing(null);setNotice('Source saved. Refresh metadata to discover profiles.');});}
 return <details className="fleet-profile-sources" open={initialOpen}><summary>Profile sources</summary>
  <p>Manage sources here without leaving {contextLabel}. Browsing uses metadata; opening a profile downloads its exact indexed version. Source changes are saved separately.</p>
  {items.map(item=><div key={item.id} className="fleet-specialist-selected"><strong>{item.name}</strong><p>{item.type==='github'?'GitHub repository':item.type==='manifest'?'HTTPS catalog':'Local directory'} · {item.enabled?'Enabled':'Disabled'} · {item.count||0} profiles</p>
   <p>{item.last_sync?'Last refreshed '+new Date(item.last_sync*1000).toLocaleString():item.count?'Bundled metadata · not yet refreshed':'Not refreshed yet'}</p>
   {item.changes&&<p>{item.changes.added} added · {item.changes.changed} changed · {item.changes.removed} removed. Saved agents retain their instructions.</p>}
   {item.error&&<p role="alert">{item.error}</p>}
   <div className="fleet-actions"><button type="button" disabled={busy} onClick={()=>edit(item)}>Settings for {item.name}</button><button type="button" disabled={busy} onClick={()=>run(async()=>{await api('/profile-sources/'+item.id+'/refresh',{version:item.version});setNotice('Metadata refreshed. Existing agents are unchanged.');})}>Refresh {item.name}</button>
   <button type="button" disabled={busy} onClick={()=>run(()=>api('/profile-sources/'+item.id,{...Object.fromEntries(['name','type','location','ref','paths','version'].map(k=>[k,item[k]])),enabled:!item.enabled}))}>{item.enabled?'Disable':'Enable'} {item.name}</button>
   {item.id!=='agency-agents'&&<button type="button" disabled={busy} onClick={()=>run(()=>api('/profile-sources/'+item.id+'/remove',{version:item.version}))}>Remove {item.name}</button>}</div></div>)}
  <button type="button" disabled={busy} onClick={()=>edit(null)}>Add profile source</button>
  {editing&&<fieldset disabled={busy}><legend>{editing==='new'?'New profile source':'Source settings'}</legend>
   <label>Source name<input aria-label="Source name" value={draft.name} maxLength={120} onChange={e=>set('name',e.target.value)}/></label>
   <label>Source type<select aria-label="Source type" value={draft.type} onChange={e=>set('type',e.target.value)}><option value="github">Public GitHub repository</option><option value="manifest">HTTPS metadata catalog</option><option value="local">Local directory</option></select></label>
   <label>{draft.type==='github'?'Repository (owner/repository)':draft.type==='manifest'?'Catalog URL':'Directory on the HARQIS host'}<input aria-label="Source location" value={draft.location} maxLength={2000} onChange={e=>set('location',e.target.value)}/></label>
   {draft.type==='github'&&<label>Branch, tag or commit<input aria-label="Source revision" value={draft.ref} maxLength={200} onChange={e=>set('ref',e.target.value)}/></label>}
   {draft.type!=='manifest'&&<label>Include patterns · one per line<textarea aria-label="Source include patterns" value={draft.paths} onChange={e=>set('paths',e.target.value)}/></label>}
   {draft.type==='local'&&<p>The directory must be inside a host-configured HARQIS_PROFILE_SOURCE_ROOTS location.</p>}
   {draft.type==='manifest'&&<p>Catalogs provide a revision and profiles with id, name, description, HTTPS url and SHA-256 hash. Downloads cannot target private networks.</p>}
   <p>Sources provide Markdown instruction profiles. This does not install executable skill packages or their scripts.</p>
   <label className="fleet-check"><input type="checkbox" checked={draft.enabled} onChange={e=>set('enabled',e.target.checked)}/>Source enabled</label>
   <div className="fleet-actions"><button type="button" disabled={!draft.name||!draft.location} onClick={save}>Save profile source</button><button type="button" onClick={()=>setEditing(null)}>Cancel source changes</button></div>
  </fieldset>}
  {busy&&<p role="status">Updating source…</p>}{notice&&<p role="status">{notice}</p>}{error&&<p role="alert">{error}</p>}
 </details>;
}
