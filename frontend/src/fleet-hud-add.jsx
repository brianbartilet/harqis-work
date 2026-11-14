import React,{useRef,useEffect,useState} from 'react';
async function request(path,body,method='POST'){
 const response=await fetch(path,{method:body===undefined?'GET':method,headers:{'Content-Type':'application/json','X-CSRF-Token':JSON.parse(document.getElementById('fleet-csrf').textContent)},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Could not save. Try again.');return data;
}
function Modal({title,mode,close,children}){const ref=useRef();useEffect(()=>{const opener=document.activeElement;ref.current.showModal();return()=>opener?.focus();},[]);return <dialog className={"fleet-hud-add-dialog fleet-hud-"+mode+"-dialog"} ref={ref} aria-label={title} onCancel={e=>{e.preventDefault();close();}}><header className="fleet-dialog-head"><h2>{title}</h2><button onClick={close} aria-label="Close">×</button></header>{children}</dialog>;}
export function HudAddControls({agent,linked,data,onSaved,spaceKey}){
 const [mode,setMode]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[query,setQuery]=useState('');const requestId=useRef(crypto.randomUUID()),created=useRef(null);
 const candidates=linked.filter(n=>n.id.startsWith('hud:'));
 const catalog=JSON.parse(document.getElementById('fleet-hud-config')?.textContent||'{}').catalog||[];
 const visible=candidates.filter(n=>n.label.toLowerCase().includes(query.trim().toLowerCase()));
 async function restore(node){setBusy(true);setError('');try{const fresh=await request('/agents/hud/data'),operation=node.id.slice(4),existing=fresh.layout.widgets.find(w=>w.operation===operation);const widgets=existing?fresh.layout.widgets.map(w=>w.operation===operation?{...w,hidden:false}:w):[...fresh.layout.widgets,{id:crypto.randomUUID(),operation,size:'2x2',hidden:false,animation:'static',workspace_ids:[],dashboard_url:''}];const layout=await request('/agents/hud/layout',{...fresh.layout,widgets},'PUT');onSaved({...fresh,layout});setMode('');}catch(e){setError(e.message);}finally{setBusy(false);}}
 async function build(event){event.preventDefault();const form=event.currentTarget;setBusy(true);setError('');try{if(!created.current){const context=await request('/second-brain/hud/build-context');const result=await request('/hfl-corpus/timeline/items',{request_id:requestId.current,title:form.elements.title.value,prompt:context.instructions+'\n\nSkill versions:\n'+context.skills.map(s=>s.name+': '+s.sha256).join('\n')+'\n\nWidget for '+agent.name+' (fleet agent '+agent.id+'):\n'+form.elements.prompt.value,expected_outcome:'A tested web HUD widget linked to '+agent.name+' and a published draft pull request.',workspace_ids:spaceKey.split(',').filter(Boolean)});created.current=result.item;}if(agent.runtime==='hermes'&&agent.active&&!agent.mock&&!agent.managed_sharing)await request('/hfl-corpus/agent-bridge/actions/'+created.current.id+'/configuration',{agent_id:agent.id,overrides:{}});const item=created.current;window.dispatchEvent(new Event('hfl:actions-updated'));setMode('');window.hflAgentBridge.open('actionable',item.id,item.title);created.current=null;requestId.current=crypto.randomUUID();}catch(e){setError(e.message);}finally{setBusy(false);}}
 return <><button type="button" className="fleet-hud-expand" aria-label="Add HUD items" title={candidates.length?'Add or restore HUD items':'No available HUD items for this agent'} disabled={!data||!candidates.length} onClick={()=>{setError('');setQuery('');setMode('add');}}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M17.5 13v9M13 17.5h9"/></svg></button><button type="button" className="fleet-hud-expand" aria-label="Build new HUD with agent" title="Build new HUD with agent" onClick={()=>{setError('');setMode('build');}}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m4 20 12-12 4 4L8 24M14 3v4m-2-2h4M4 5v6m-3-3h6M20 17v6m-3-3h6"/></svg></button>{mode&&<Modal mode={mode} title={mode==='add'?'Add a widget':'Build a HUD widget'} close={()=>!busy&&setMode('')}>
 {mode==='add'?<div className="fleet-hud-catalog-body">
  <input type="search" aria-label="Search widgets" placeholder="Search widgets" value={query} onChange={e=>setQuery(e.target.value)}/>
  <div className="fleet-hud-catalog">{visible.map(n=>{
   const item=catalog.find(item=>item.operation_id===n.id.slice(4));
   const widget=data.layout.widgets.find(w=>w.operation===n.id.slice(4)),added=widget&&!widget.hidden;
   const assigned=widget?.workspace_ids||[],spaces=assigned.map(id=>data.spaces?.views?.find(s=>s.id===id)).filter(Boolean);
   const elsewhere=added&&assigned.length&&!assigned.some(id=>spaceKey.split(',').includes(id));
   return <div key={n.id} className={'fleet-hud-catalog-card'+(added?' fleet-hud-catalog-added':'')}>
    <div><div className="fleet-hud-catalog-heading"><strong>{n.label}</strong><span className="fleet-hud-catalog-spaces" aria-label="Assigned workspaces">{spaces.length?spaces.map(s=><span className="hud-space-pill" key={s.id}><span className="hud-space-dot" style={{backgroundColor:s.color}}/>{s.name}</span>):<span className="hud-space-pill">{assigned.length?'Unavailable Space':'All Spaces'}</span>}</span></div>
    <small>{added?'Already added'+(elsewhere?' · in another Space':''):widget?'Hidden · restore to your dashboard':item?.schedules?.length?'Scheduled collector · '+item.schedules.length+' schedule(s)':item?.source_task?'On-demand source':'Built-in view'}</small></div>
    <button type="button" disabled={busy||!!added} onClick={()=>restore(n)}>{added?'Added':widget?'Restore':'Add'}</button>
   </div>;
  })}{!visible.length&&<p>No widgets match this search.</p>}</div>
 </div>:<form className="fleet-form" onSubmit={build}>
  <p>Describe a new widget or a change. Create an action with the HUD skills and current Space links, then continue in the existing agent workspace.</p>
  <label>Widget title<input name="title" required maxLength={150} placeholder="Weekly delivery pulse" disabled={busy||!!created.current}/></label>
  <label>What should it show?<textarea name="prompt" required maxLength={12000} rows={7} placeholder="Sources, information to show, update frequency, and when it should appear…" disabled={busy||!!created.current}/></label>
  <button type="submit" className="fleet-primary" disabled={busy}>{busy?'Preparing…':'Create action & open agent workspace'}</button>
 </form>}{error&&<p className="fleet-hud-dialog-error" role="alert">{error}</p>}</Modal>}</>;
}
