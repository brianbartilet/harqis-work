import React,{useEffect,useState} from 'react';

export function CodexConnection({agent,selected,onChange,api,refreshed,busy}){
 const [connector,setConnector]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[working,setWorking]=useState(false),[result,setResult]=useState('');
 useEffect(()=>{let disposed=false;api('/connectors',undefined,'/integrations/api').then(data=>{if(!disposed)setConnector(data.items.find(c=>c.provider==='codex'));}).catch(e=>{if(!disposed)setError(e.message);}).finally(()=>{if(!disposed)setLoading(false);});return()=>{disposed=true;};},[]);
 async function refresh(){setWorking(true);setError('');setResult('');try{const value=agent.connector_provider==='codex'?await api('/codex/agents/'+agent.id+'/refresh',{},'/integrations/api'):await api('/codex/link',{agent_id:agent.id},'/integrations/api');const discovery=value.discovery||value;setResult(Object.entries(discovery.counts||{}).map(([k,v])=>v+' '+k).join(' · ')+(discovery.warnings?.length?' · '+discovery.warnings.join(' '):' · Observations refreshed'));await refreshed();}catch(e){setError(e.message);}finally{setWorking(false);}}
 return <fieldset className="fleet-connection" disabled={busy||working}><legend>Codex connection</legend>
 {loading?<p role="status">Loading connector…</p>:<><p>{connector?.enabled?'Connected · '+connector.account:'Connect and enable the local host in Integrations first.'} <a href="/applications" target="_blank" rel="noopener noreferrer">Integrations</a></p>
 {!agent&&<label className="fleet-check"><input type="checkbox" checked={selected} onChange={e=>onChange(e.target.checked)}/>Link the existing Codex installation</label>}
 {agent&&<button type="button" disabled={!connector?.enabled} onClick={refresh}>{working?'Refreshing…':agent.connector_provider==='codex'?'Refresh observations':'Link this profile to Codex'}</button>}
 <p>{!agent&&!selected?'Save a manual profile without discovery.':'Linking reuses the installation’s existing fleet identity and preserves its customizations.'} Tasks remain in Codex. Butler receives recorded results; live execution controls are unavailable.</p></>}
 {result&&<p role="status">{result}</p>}{error&&<p role="alert">{error}</p>}
 </fieldset>;
}
