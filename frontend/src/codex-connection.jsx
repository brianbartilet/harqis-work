import React,{useEffect,useState} from 'react';

export function CodexConnection({agent,selected,onChange,api,refreshed,busy,provider=agent?.runtime||'codex'}){
 const name=provider==='claude'?'Claude':'Codex';
 const [connector,setConnector]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[working,setWorking]=useState(false),[result,setResult]=useState('');
 useEffect(()=>{let disposed=false;api('/connectors',undefined,'/integrations/api').then(data=>{if(!disposed)setConnector(data.items.find(c=>c.provider===provider));}).catch(e=>{if(!disposed)setError(e.message);}).finally(()=>{if(!disposed)setLoading(false);});return()=>{disposed=true;};},[provider]);
 async function refresh(){setWorking(true);setError('');setResult('');try{const value=agent.connector_provider===provider?await api('/'+provider+'/agents/'+agent.id+'/refresh',{},'/integrations/api'):await api('/'+provider+'/link',{agent_id:agent.id},'/integrations/api');const discovery=value.discovery||value;setResult(Object.entries(discovery.counts||{}).map(([k,v])=>v+' '+k).join(' · ')+(discovery.warnings?.length?' · '+discovery.warnings.join(' '):' · Observations refreshed'));await refreshed();}catch(e){setError(e.message);}finally{setWorking(false);}}
 return <fieldset className="fleet-connection" disabled={busy||working}><legend>{name} connection</legend>
 {loading?<p role="status">Loading connector…</p>:<><p>{connector?.enabled?'Connected · '+connector.account:'Connect and enable the local host in Integrations first.'} {connector?.availability?.available===false&&<span> · {connector.availability.reason}</span>} <a href="/applications" target="_blank" rel="noopener noreferrer">Integrations</a></p>
 {!agent&&<label className="fleet-check"><input type="checkbox" checked={selected} onChange={e=>onChange(e.target.checked)}/>Link the existing {name} installation</label>}
 {agent&&<button type="button" disabled={!connector?.enabled} onClick={refresh}>{working?'Refreshing…':agent.connector_provider===provider?'Refresh observations':'Link this profile to '+name}</button>}
 <p>{!agent&&!selected?'Save a manual profile without discovery.':'Linking reuses the installation’s existing fleet identity and preserves its customizations.'} Tasks remain on the host. Fleet sessions use the matching CLI worker; Butler can inspect recorded work.</p></>}
 {result&&<p role="status">{result}</p>}{error&&<p role="alert">{error}</p>}
 </fieldset>;
}
