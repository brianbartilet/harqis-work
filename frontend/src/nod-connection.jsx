import React,{useEffect,useState} from 'react';
import {connectionPayload} from './fleet-connection.jsx';

export function NodConnection({value,onChange,identity,api,busy}){
  const [testing,setTesting]=useState(false),[result,setResult]=useState('');
  function change(key,next){setResult('');onChange({...value,[key]:next,mode:'setup',...(key==='url'?{key:'',has_key:false}:{})});}
  async function test(){setTesting(true);setResult('');try{await api(identity?'/items/'+identity+'/connection/test':'/connections/test',{...connectionPayload(value),provider:'nod',mode:'setup'});setResult('Nod server reachable · access verified. Chat and tasks remain in Nod.');}catch(e){setResult(e.message);}finally{setTesting(false);}}
  return <fieldset className="fleet-connection" disabled={busy||testing}><legend>Nod connection</legend>
    <label>Connection mode<select aria-label="Connection mode" value={value.enabled?'server':'profile'} onChange={e=>change('enabled',e.target.value==='server')}><option value="profile">Profile only</option><option value="server">Self-hosted Nod server</option></select></label>
    <p>Run Nod on your Mac host, finish its onboarding, then connect the server here. <a href="https://nod.n8n.io/docs/deploy/mac-mini/" target="_blank" rel="noopener noreferrer">Mac host setup</a></p>
    {value.enabled&&<><label>Nod server URL<input aria-label="Nod server URL" required type="url" maxLength={2000} placeholder="https://nod.example.com" value={value.url} onChange={e=>change('url',e.target.value)}/></label>
      <p>This address must be reachable from the HARQIS server. Use HTTPS or a local SSH tunnel, such as http://localhost:4310.</p>
      <label>Nod access token<input aria-label="Nod access token" type="password" autoComplete="new-password" maxLength={4096} value={value.key||''} placeholder={value.has_key?'Saved · leave blank to keep':'NOD_AUTH_TOKEN from the server'} onChange={e=>change('key',e.target.value)}/></label>
      <p>The token grants access to your Nod assistant. HARQIS stores it encrypted and uses it only to check server health in this scaffold.</p>
      <button type="button" onClick={test}>{testing?'Testing…':'Test connection'}</button><p role="status">{result}</p>
      <small>Saving verifies access again. Chat, tasks, approvals and schedules are managed in Nod. Choose Profile only to remove the saved token.</small></>}
  </fieldset>;
}

export function NodStatus({identity,api,configure}){
  const [value,setValue]=useState(null),[error,setError]=useState(''),[generation,setGeneration]=useState(0);
  useEffect(()=>{let disposed=false;setValue(null);setError('');api('/items/'+identity+'/connection/status').then(v=>{if(!disposed)setValue(v);}).catch(e=>{if(!disposed)setError(e.message);});return()=>{disposed=true;};},[identity,generation]);
  return <div className="fleet-connection"><p role="status">{error||(!value?'Checking Nod connection…':!value.enabled?'Nod server not configured.':value.connected?'Nod server reachable · setup only':value.detail||'Nod server unavailable.')}</p>
    <p>Chat and task execution are available in Nod.</p>
    {value?.enabled&&<a href={value.url} target="_blank" rel="noopener noreferrer">Open Nod</a>}
    <button onClick={configure}>Configure Nod</button><button disabled={!value&&!error} onClick={()=>setGeneration(n=>n+1)}>Check connection</button>
  </div>;
}
