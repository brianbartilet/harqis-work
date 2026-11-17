import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {SpecialistPicker} from './fleet-specialists.jsx';
import {ProfileSources} from './fleet-profile-sources.jsx';

async function api(path,payload){
 const csrf=JSON.parse(document.querySelector('[data-memory-csrf]')?.textContent||'""');
 const response=await fetch('/agents/api'+path,{method:payload===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
 const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Could not load specialist profiles.');return data;
}
window.HflActionSpecialistPicker=(host,selected,changed)=>{
 const root=createRoot(host);
 function Picker(){
  const [draft,setDraft]=useState({specialist_profile:selected,classification:'general',runtime:'hermes',skills:[],description:''});
  const [manage,setManage]=useState(false),[sources,setSources]=useState([]),[error,setError]=useState(''),[loading,setLoading]=useState(false),[version,setVersion]=useState(0);
  useEffect(()=>{if(!manage)return;let stale=false;setLoading(true);setError('');api('/profile-sources').then(data=>{if(!stale)setSources(data.items);}).catch(e=>{if(!stale)setError(e.message);}).finally(()=>{if(!stale)setLoading(false);});return()=>{stale=true;};},[manage,version]);
  return <>
   <div className="action-profile-toolbar"><p>{manage?'Source changes apply across Fleet and Actions.':'Choose specialist guidance for this Action.'}</p><button type="button" onClick={()=>setManage(v=>!v)}>{manage?'Back to profiles':'Manage sources'}</button></div>
   {manage?<>{loading?<p role="status">Loading sources…</p>:error?<div role="alert"><p>{error}</p><button type="button" onClick={()=>setVersion(v=>v+1)}>Retry</button></div>:<ProfileSources contextLabel="the profile picker" initialOpen items={sources} api={api} changed={()=>{setVersion(v=>v+1);return Promise.resolve();}}/>}</>:<SpecialistPicker actionContext showSources={false} draft={draft} catalog={{classifications:[],skills:[]}} api={api} onChange={(patch,detail)=>{setDraft(old=>({...old,...patch}));if('specialist_profile' in patch)changed(patch.specialist_profile,detail?.name);}}/>}
  </>;
 }
 root.render(<Picker/>);return ()=>root.unmount();
};
