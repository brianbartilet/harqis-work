import {OwnerCard,Description,Relationships,IdeaAssignment} from './fleet-presentation.jsx';
import {statusLabel,statusColor,statusSuffix} from './action-status.mjs';
import {graphDateRange} from './graph-dates.mjs';
import {IntentControls,CreateIntent} from './fleet-intent.jsx';
import {NodConnection,NodStatus} from './nod-connection.jsx';
import {FleetConnection,emptyConnection,connectionPayload} from './fleet-connection.jsx';
import {FleetConversation} from './fleet-conversation.jsx';
import './agent-avatar.jsx';
import {AgentHud} from './fleet-hud.jsx';
import {IconButton,InspectorTabs,InspectorIcon} from './fleet-inspector.jsx';
import {fleetItemLink} from './fleet-item-link.mjs';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ForceGraph2D from 'react-force-graph-2d';
import {motionOffset, phaseFor} from './graph-presets.mjs';
import {configureDragForces, releaseDragNeighbors, settleDragNodes} from './graph-drag.mjs';
import {filterFleet, activityKind} from './fleet-graph.mjs';
import {createLabelLayout} from './graph-labels.mjs';

const csrf=()=>JSON.parse(document.getElementById('fleet-csrf').textContent);
async function api(path, data, base='/agents/api') {
  const response=await fetch(base+path,{method:data===undefined?'GET':'POST',headers:{'X-CSRF-Token':csrf(),...(data instanceof FormData?{}:{'Content-Type':'application/json'})},...(data===undefined?{}:{body:data instanceof FormData?data:JSON.stringify(data)})});
  const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Check the fields and try again.');return result;
}
const empty={runtime:'hermes',classification:'general',name:'',description:'',persona:'',instructions:'',active:true,color:'#3b82f6',thumbnail:'',workspace_ids:[],skills:[],tools:[],workflows:[],triggers:[],subagents:[],overrides:{}};
const fields=['runtime','classification','name','description','persona','instructions','active','color','thumbnail','workspace_ids','skills','tools','workflows','triggers','subagents','overrides'];
function Dialog({title,children,close,className='',id}){const ref=useRef();useEffect(()=>{const opener=document.activeElement;ref.current.showModal();return()=>opener?.focus();},[]);return <dialog ref={ref} className={className} id={id} aria-label={title} onCancel={e=>{e.preventDefault();close();}}><header className="fleet-dialog-head"><h2>{title}</h2><button type="button" onClick={close} aria-label="Close">✕</button></header>{children}</dialog>;}
function Choices({label,options,selected,onChange}){const [q,setQ]=useState('');const shown=options.filter(o=>o.name.toLowerCase().includes(q.toLowerCase())).slice(0,80);return <fieldset><legend>{label} · {selected.length} selected</legend><input aria-label={'Search '+label} placeholder={'Search '+label.toLowerCase()} value={q} onChange={e=>setQ(e.target.value)}/><div className="fleet-choices">{shown.map(o=><label className="fleet-check" key={o.id}><input type="checkbox" checked={selected.includes(o.id)} onChange={e=>onChange(e.target.checked?[...selected,o.id]:selected.filter(v=>v!==o.id))}/>{o.name}</label>)}{!shown.length&&<p>No matches</p>}</div>{selected.filter(id=>!options.some(o=>o.id===id)).map(id=><label className="fleet-check" key={id}><input type="checkbox" checked onChange={()=>onChange(selected.filter(v=>v!==id))}/>Unavailable selection · {id}</label>)}</fieldset>;}
function Editor({agent,catalog,agents,spaces,close,saved,reloadCatalog}){
 const [draft,setDraft]=useState({...empty,...agent,overrides:{...agent?.overrides}}),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [tools,setTools]=useState(agent?.tools.join(', ')||'');
 const [connection,setConnection]=useState(emptyConnection),[connectionLoading,setConnectionLoading]=useState(Boolean(['hermes','nod'].includes(agent?.runtime)&&!agent?.mock)),[connectionDirty,setConnectionDirty]=useState(false);const persisted=useRef(agent);
 useEffect(()=>{let disposed=false;if(['hermes','nod'].includes(agent?.runtime)&&!agent?.mock){api('/items/'+agent.id+'/connection').then(value=>{if(!disposed)setConnection({...value,key:''});}).catch(e=>{if(!disposed)setError(e.message);}).finally(()=>{if(!disposed)setConnectionLoading(false);});}return()=>{disposed=true;};},[]);
 const set=(k,v)=>setDraft(d=>({...d,[k]:v}));const override=(k,v)=>setDraft(d=>({...d,overrides:{...d.overrides,[k]:v}}));const external=draft.runtime!=='hermes';
 async function upload(file){if(!file)return;setBusy(true);try{const data=new FormData();data.append('file',file);const value=await api('/assets',data);if(value.media_type==='text/markdown'){await reloadCatalog();setDraft(d=>({...d,skills:[...d.skills,'upload:'+value.id]}));}else set('thumbnail',value.id);}catch(e){setError(e.message);}finally{setBusy(false);}}
 async function submit(e){e.preventDefault();setBusy(true);setError('');try{
   const useConnection=['hermes','nod'].includes(draft.runtime)&&!agent?.mock&&connectionDirty;
   const payload={...connectionPayload(connection),provider:draft.runtime};
   if(useConnection&&connection.enabled)await api(persisted.current?'/items/'+persisted.current.id+'/connection/test':'/connections/test',payload);
   const raw=Object.fromEntries(fields.map(k=>[k,draft[k]]));raw.tools=tools.split(',').map(s=>s.trim()).filter(Boolean);if(persisted.current)raw.version=persisted.current.version;
   const result=await api('/items'+(persisted.current?'/'+persisted.current.id:''),raw);persisted.current=result.item;
   if(useConnection){try{const savedConnection=await api('/items/'+result.item.id+'/connection',payload);setConnection({...savedConnection,key:''});setConnectionDirty(false);}catch(e){throw Error('Agent profile saved; connection was not saved. '+e.message);}}
   await saved();close();
 }catch(e){setError(e.message);}finally{setBusy(false);}}

 return <Dialog title={agent?'Edit '+agent.name:'Create agent'} className="fleet-agent-editor" close={close}><form className="fleet-form" onSubmit={submit}><div className="fleet-columns"><label>Name<input required maxLength={120} value={draft.name} onChange={e=>set('name',e.target.value)}/></label><label>Thumbnail · PNG or animated GIF<input type="file" accept="image/png,image/gif" onChange={e=>upload(e.target.files[0])}/></label></div>{draft.thumbnail&&<div className="fleet-actions"><img width="48" height="48" src={'/agents/api/assets/'+draft.thumbnail} alt="Agent thumbnail"/><button type="button" onClick={()=>set('thumbnail','')}>Remove thumbnail</button></div>}<div className="fleet-columns"><label>Agent service<select aria-label="Agent service" value={draft.runtime} disabled={Boolean(agent)||Boolean(persisted.current)} onChange={e=>{set('runtime',e.target.value);setConnection({...emptyConnection(),mode:e.target.value==='nod'?'setup':'chat'});setConnectionDirty(false);set('classification',catalog.services.find(s=>s.id===e.target.value).classification);}}>{catalog.services.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label><label>Classification<select value={draft.classification} onChange={e=>set('classification',e.target.value)}>{catalog.classifications.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label></div><p>Use a human name such as Ada · Senior developer. A service can have multiple agent instances.</p><label>Description<textarea maxLength={3000} value={draft.description} onChange={e=>set('description',e.target.value)}/></label><fieldset><legend>Orb color</legend><div className="fleet-swatch">{catalog.colors.map(c=><button key={c} type="button" style={{background:c}} aria-label={'Color '+c} aria-pressed={draft.color===c} onClick={()=>set('color',c)}/>)}</div></fieldset><Choices label="Spaces" options={spaces} selected={draft.workspace_ids} onChange={v=>set('workspace_ids',v)}/><label>Persona<textarea maxLength={3000} value={draft.persona} onChange={e=>set('persona',e.target.value)}/></label>
 {draft.runtime==='nod'&&!agent?.mock&&(connectionLoading?<p role="status">Loading connection settings…</p>:<NodConnection value={connection} onChange={value=>{setConnection(value);setConnectionDirty(true);}} identity={persisted.current?.id} api={api} busy={busy}/>)}
 {!external&&!agent?.mock&&(connectionLoading?<p role="status">Loading connection settings…</p>:<FleetConnection value={connection} onChange={value=>{setConnection(value);setConnectionDirty(true);}} identity={persisted.current?.id} api={api} busy={busy}/>)}
 {!external&&connection.enabled?<label>Gateway instructions<textarea maxLength={20000} value={draft.instructions} onChange={e=>set('instructions',e.target.value)}/></label>:!external?<><fieldset><legend>Hermes execution</legend><div className="fleet-columns"><label>Model provider<select value={draft.overrides.agent_provider||''} onChange={e=>override('agent_provider',e.target.value)}>{catalog.providers.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>Model<input placeholder="Worker default" value={draft.overrides.agent_model||''} onChange={e=>override('agent_model',e.target.value)}/></label></div><p>Use a model available to the configured worker account. Credentials stay on the worker.</p><label>Base instructions<textarea maxLength={20000} value={draft.instructions} onChange={e=>set('instructions',e.target.value)}/></label><div className="fleet-columns">{[['hermes_profile','Hermes profile'],['agent_host','Worker hostname'],['agent_repository','Repository'],['agent_base_branch','Base branch']].map(([key,label])=><label key={key}>{label}<input value={draft.overrides[key]||''} placeholder="Inherit shared defaults" onChange={e=>override(key,e.target.value)}/></label>)}</div></fieldset><Choices label="Skills" options={catalog.skills} selected={draft.skills} onChange={v=>set('skills',v)}/><label>Upload a skill<input type="file" accept=".md,text/markdown" onChange={e=>upload(e.target.files[0])}/></label><label>Tools / MCP toolsets<input placeholder="Comma-separated configured toolset names" value={tools} onChange={e=>setTools(e.target.value)}/></label><Choices label="Workflows" options={catalog.workflows} selected={draft.workflows} onChange={v=>set('workflows',v)}/><p>Linked workflows retain their existing scheduler. Linking one does not execute or reschedule it.</p><Choices label="Scheduled triggers" options={catalog.workflows.filter(w=>w.schedule&&w.owner!=='manual').map(w=>({...w,name:w.name+' · '+w.schedule}))} selected={draft.triggers} onChange={v=>set('triggers',v)}/><Choices label="Sub-agents" options={agents.filter(a=>a.id!==agent?.id&&a.active&&a.runtime==='hermes')} selected={draft.subagents} onChange={v=>set('subagents',v)}/><p>Sub-agent links describe delegation relationships; each child runs through its own configured session.</p></>:draft.runtime==='nod'?<p>Nod is an experimental, externally managed agent service. Configure its browser tasks, app connections and schedules in Nod. Connect a self-hosted server above to verify access. Chat, task dispatch and result capture remain in Nod.</p>:<p>Execution settings remain managed by the external provider. These changes customize its HARQIS presentation. Connect an account in Build → Integrations for provider discovery; a manual profile does not enable remote execution.</p>}
 <label className="fleet-check"><input type="checkbox" checked={draft.active} onChange={e=>set('active',e.target.checked)}/>Active</label>{error&&<p role="alert" className="fleet-alert">{error}</p>}<div className="fleet-actions"><button className="fleet-primary" disabled={busy||connectionLoading}>{busy?'Saving…':'Save agent'}</button><button type="button" onClick={close}>Cancel</button></div></form></Dialog>;
}
const DEFAULTS_SECTIONS = [
  {title:'Scheduling', fields:[
    ['actions_polling_minutes','Polling Interval (Minutes)'],
    ['pin_backfill_days','Pin Backfill (Days)'],
  ]},
  {title:'Model & Tools', fields:[
    ['agent_mode','Execution Mode'], ['hermes_profile','Hermes Profile'],
    ['agent_model','Model'], ['agent_provider','Provider'],
    ['agent_toolsets','Toolsets'],
  ]},
  {title:'Execution Limits', fields:[
    ['agent_timeout_seconds','Timeout (Seconds)'], ['agent_max_turns','Maximum Turns'],
    ['agent_concurrency','Concurrent Runs'], ['agent_session_expiry_minutes','Session Expiry (Minutes)'],
  ]},
  {title:'Workspace & Delivery', fields:[
    ['agent_repository','Repository'], ['agent_base_branch','Base Branch'],
    ['agent_host','Host'], ['agent_default_recipient','Default Recipient'],
  ]},
];
function Defaults({close}){
  const [values,setValues]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{api('/defaults').then(setValues).catch(e=>setError(e.message));},[]);
  return <Dialog title="Agent settings" className="fleet-defaults-dialog" close={close}>
    <form className="fleet-form" onSubmit={async e=>{e.preventDefault();setBusy(true);try{await api('/defaults',values);close();}catch(e){setError(e.message);}finally{setBusy(false);}}}>
      <p>Defaults for automated Hermes work. Agents and individual actions can override these settings.</p>
      {!values&&!error&&<p role="status">Loading settings…</p>}
      {values&&DEFAULTS_SECTIONS.map(section=><fieldset key={section.title}>
        <legend>{section.title}</legend>
        <div className="fleet-columns">{section.fields.map(([key,label])=><label key={key}>{label}
          {key==='agent_mode'?<select value={values[key]} onChange={e=>setValues({...values,[key]:e.target.value})}>
            <option value="trusted">Trusted Hermes</option><option value="restricted">Restricted tools</option>
          </select>:typeof values[key]==='number'?<span className="fleet-number-control">
            <input id={'fleet-default-'+key} type="number" value={values[key]} onChange={e=>setValues({...values,[key]:Number(e.target.value)})}/>
            <span className="fleet-number-steppers">{[1,-1].map(direction=><button key={direction} type="button" aria-label={(direction===1?'Increase ':'Decrease ')+label} onClick={()=>setValues(current=>({...current,[key]:current[key]+direction}))}>
              <svg aria-hidden="true" viewBox="0 0 20 20" fill="none"><path d={direction===1?'m5 12.5 5-5 5 5':'m5 7.5 5 5 5-5'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>)}</span>
          </span>:<input type="text" value={values[key]} onChange={e=>setValues({...values,[key]:e.target.value})}/>}
        </label>)}</div>
      </fieldset>)}
      {error&&<p role="alert">{error}</p>}
      <div className="fleet-defaults-actions"><button type="button" onClick={close}>Cancel</button><button type="submit" disabled={busy||!values}>{busy?'Saving…':'Save defaults'}</button></div>
    </form>
  </Dialog>;
}
function SpacePicker({selected,onApply}) {
 const host=useRef(), callback=useRef(onApply);callback.current=onApply;
 useEffect(()=>{const element=host.current;window.HflWorkspacePicker(element,{selected,empty:'All activity',onapply:ids=>callback.current(ids)});return()=>{element._disposeWorkspacePicker?.();element.replaceChildren();};},[selected.join(',')]);
 return <div ref={host}/>;
}
function Spaces({selected,onApply,modified}) {
 const [snapshot,setSnapshot]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[pendingDynamic,setPendingDynamic]=useState(null);
 const menu=useRef(),callback=useRef(onApply),saving=useRef(false),version=useRef(0);callback.current=onApply;
 useEffect(()=>{
   const element=menu.current,toolbar=element.closest('.fleet-toolbar');
   const position=()=>{if(element.open)element.style.setProperty('--fleet-space-top',Math.round(element.querySelector('summary').getBoundingClientRect().bottom+8)+'px');};
   const observer=new ResizeObserver(position);observer.observe(toolbar);
   element.addEventListener('toggle',position);window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
   return()=>{observer.disconnect();element.removeEventListener('toggle',position);window.removeEventListener('resize',position);window.removeEventListener('scroll',position,true);};
 },[]);
 useEffect(()=>{let disposed=false;async function load(){if(saving.current)return;const revision=++version.current;try{const response=await fetch('/hfl-corpus/workspace-views',{cache:'no-store'});if(!response.ok)throw Error('Spaces unavailable');const data=await response.json();if(disposed||revision!==version.current)return;setSnapshot(data);callback.current(data.active,data);setError('');}catch(e){if(!disposed){setError(e.message);window.BrainPageLoading?.finish();}}}load();const timer=setInterval(()=>{if(!document.hidden&&!menu.current?.open)load();},15000);const dismiss=e=>{if(menu.current&&!e.composedPath().includes(menu.current))menu.current.open=false;};const storage=e=>{if(e.key==='corpus:workspace-change')load();};const visible=()=>{if(!document.hidden)load();};window.addEventListener('storage',storage);document.addEventListener('visibilitychange',visible);document.addEventListener('click',dismiss);return()=>{disposed=true;clearInterval(timer);window.removeEventListener('storage',storage);document.removeEventListener('visibilitychange',visible);document.removeEventListener('click',dismiss);};},[]);
 async function save(changes){if('dynamic' in changes)setPendingDynamic(changes.dynamic);saving.current=true;version.current++;setBusy(true);setError('');try{const response=await fetch('/hfl-corpus/view-preferences',{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},body:JSON.stringify({...snapshot.preferences,...changes})});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Unable to save Spaces');setSnapshot(data);callback.current(data.active,data);try{localStorage.setItem('corpus:workspace-change',String(Date.now()));}catch{}}catch(e){setError(e.message);}finally{saving.current=false;setBusy(false);setPendingDynamic(null);}}
 useEffect(()=>{const select=e=>{const index=e.detail;if(!snapshot||busy||saving.current||index>snapshot.views.length)return;save({manual:index?[snapshot.views[index-1].id]:[],dynamic:false,applied:{}});};document.addEventListener('fleet-space-key',select);return()=>document.removeEventListener('fleet-space-key',select);},[snapshot,busy]);
 const active=snapshot?.views.filter(v=>selected.includes(v.id))||[],dynamic=pendingDynamic??Boolean(snapshot?.preferences.dynamic),scheduled=snapshot?.views.some(v=>v.schedule?.length);
 return <div className="fleet-spaces corpus-workspace-controls"><div className="activity-view-context"><span className="activity-view-name" style={{borderLeft:active.length===1?'3px solid '+active[0].color:undefined}}>{active.map(v=>v.name).join(' + ')||'All activity'}</span><span className="activity-dynamic-badge" data-on={dynamic}>{dynamic?'Dynamic ON':'Dynamic OFF'}</span><span className="activity-view-modified" data-state={modified?'modified':active.length?'saved':'default'}>{modified?'Modified':active.length?'Saved':'Default'}</span></div><details ref={menu} className="workspace-menu" onKeyDown={e=>{if(e.key==='Escape'){e.currentTarget.open=false;e.currentTarget.querySelector('summary').focus();}}}><summary className="corpus-header-link workspace-select">Space</summary><div className="workspace-menu-panel"><span className="workspace-focus-label">Focus on</span>{snapshot&&!busy?<SpacePicker selected={selected} onApply={ids=>save({manual:ids,dynamic:false,applied:{}})}/>:<p role="status">{busy?'Saving…':'Loading Spaces…'}</p>}<div className="workspace-dynamic-row"><span>Dynamic mode</span><label className="workspace-dynamic-toggle"><input aria-label="Dynamic mode" type="checkbox" role="switch" checked={dynamic} disabled={!snapshot||busy||(!scheduled&&!dynamic)} onChange={e=>save({dynamic:e.target.checked})}/></label></div>{snapshot&&!scheduled&&<p className="workspace-adaptive-status">Add a time block in Organize → Spaces to enable Dynamic mode.</p>}<a href="/spaces">Manage Spaces</a>{error&&<p role="alert">{error}</p>}</div></details></div>;
}
function AnimationMenu({value,onChange,open,setOpen}){
 const host=useRef(),trigger=useRef();
 useEffect(()=>{if(!open)return;const dismiss=e=>{if(!e.composedPath().includes(host.current))setOpen(false);};document.addEventListener('click',dismiss);return()=>document.removeEventListener('click',dismiss);},[open]);
 return <div className="fleet-animation-menu" ref={host} onKeyDown={e=>{if(e.key==='Escape'&&open){e.preventDefault();e.stopPropagation();setOpen(false);trigger.current.focus();}}}><button ref={trigger} type="button" className="fleet-animation-trigger" aria-label="Animation" aria-controls="fleet-animation-panel" aria-expanded={open} onClick={()=>setOpen(v=>!v)}>Animation<span className="fleet-animation-pill" data-mode={value}>{value.charAt(0).toUpperCase()+value.slice(1)}</span><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="m4 6 4 4 4-4"/></svg></button>{open&&<div id="fleet-animation-panel" className="fleet-animation-panel" role="region" aria-label="Animation modes"><div className="fleet-animation-options" role="group" aria-label="Animation mode">{['off','breathing','ripple','drift'].map(mode=><button key={mode} type="button" aria-pressed={value===mode} disabled={mode!=='off'&&matchMedia('(prefers-reduced-motion: reduce)').matches} onClick={()=>onChange(mode)}>{mode.charAt(0).toUpperCase()+mode.slice(1)}</button>)}</div><span role="status">Paused</span></div>}</div>;
}
function Icon({reset=false}){return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{reset?<><path d="M3 9V3h6M21 9V3h-6M3 15v6h6M21 15v6h-6"/><path d="M8 12h8M12 8v8"/></>:<><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 11-1l3 6M4 12l3 6a7 7 0 0 0 11-1"/></>}</svg>;}
const owner=JSON.parse(document.getElementById('fleet-owner').textContent);
const viewKey='harqis:fleet:graph:v2:'+owner;
function savedView(){try{const {demo,...view}=JSON.parse(localStorage.getItem(viewKey))||{};return view;}catch{return {};}}
const initialView=savedView();
function FleetGraph({data,selected,select,agents,animation,animationMenuOpen,reset,fullscreen,setFullscreen}) {
  const host=useRef(),graph=useRef(),positions=useRef(initialView.positions||{}),targets=useRef(new Map()),released=useRef(new Set()),dragging=useRef(false),avatarLayer=useRef(),avatarNodes=useRef(new Map()),fitted=useRef(false);
  const [size,setSize]=useState({width:800,height:640});
  const [dragActive,setDragActive]=useState(false),[hovered,setHovered]=useState(null),[keepDrawing,setKeepDrawing]=useState(true);
  const labelLayout=useRef(createLabelLayout()),labelClock=useRef({nextUpdate:0,fadeUntil:0}),pointers=useRef(new Set()),motionSettling=useRef(false);
  const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const active=hovered||selected;
  const near=useMemo(()=>new Set(data.links.flatMap(l=>l.source===active?[l.target]:l.target===active?[l.source]:[])),[data,active]);
  const visible=n=>!active||n.id===active||n.id===selected||near.has(n.id);
  const visibility=useRef();visibility.current=visible;
  const uiFont=host.current?getComputedStyle(host.current).fontFamily:'sans-serif';
  const motionTime=useRef(0),lastFrame=useRef(0),lastInteraction=useRef(0);
  const agentMap=useMemo(()=>new Map(agents.map(a=>[a.id,a])),[agents]);
  const model=useMemo(()=>{
    const anchors=data.nodes.filter(n=>n.kind==='agent'), location=new Map(anchors.map((a,i)=>[a.agent_id,{x:260*Math.cos(i*2*Math.PI/Math.max(1,anchors.length)),y:260*Math.sin(i*2*Math.PI/Math.max(1,anchors.length))}]));
    const nodes=data.nodes.map((n,i)=>{const parent=location.get(n.agent_id||n.agent_ids?.[0])||{x:0,y:0},phase=phaseFor(n.id),cached=positions.current[n.id],prior=Number.isFinite(cached?.x)&&Number.isFinite(cached?.y)?cached:null;const node={...n,radius:n.radius,...(prior||{x:parent.x+(n.kind==='agent'?0:100*Math.cos(phase+i)),y:parent.y+(n.kind==='agent'?0:100*Math.sin(phase+i))})};if(prior){node.fx=node.x;node.fy=node.y;}return node;});
    targets.current=new Map(nodes.map(n=>[n.id,{x:n.x,y:n.y}]));
    return {nodes,links:data.links.map(l=>({...l}))};
  },[data]);
  // Native images animate even when ForceGraph has paused canvas redraws.
  useEffect(()=>{
    const layer=avatarLayer.current;layer.replaceChildren();avatarNodes.current.clear();
    for(const node of model.nodes.filter(n=>n.kind==='agent')){
      const agent=agentMap.get(node.agent_id);if(!agent)continue;
      const avatar=globalThis.AgentAvatars.create(agent,{interactive:false});
      avatar.style.width=avatar.style.height=Math.max(12,node.radius*2-4)+'px';
      avatar.style.fontSize=Math.max(8,node.radius*.8)+'px';
      avatar.style.opacity=agent.active===false?'.35':'1';
      avatar.style.visibility='hidden';layer.append(avatar);avatarNodes.current.set(node.id,avatar);
    }
    let frame;
    function position(){
      if(!document.hidden)for(const node of model.nodes){
        const avatar=avatarNodes.current.get(node.id);if(!avatar||!graph.current||!Number.isFinite(node.x)||!Number.isFinite(node.y))continue;
        const point=graph.current.graph2ScreenCoords(node.x,node.y);
        avatar.style.opacity=String((agentMap.get(node.agent_id)?.active===false?.35:1)*(visibility.current(node)?1:.075));
        avatar.style.visibility=point.x<0||point.y<0||point.x>size.width||point.y>size.height?'hidden':'visible';
        avatar.style.transform=`translate(${point.x}px,${point.y}px) translate(-50%,-50%)`;
      }
      frame=requestAnimationFrame(position);
    }
    position();return()=>cancelAnimationFrame(frame);
  },[model,agentMap,size]);
  function savePositions(){const visible=Object.fromEntries(model.nodes.map(n=>[n.id,{...(targets.current.get(n.id)||{x:n.x,y:n.y}),manual:!!n.manual}]).filter(([,p])=>Number.isFinite(p.x)&&Number.isFinite(p.y)));positions.current={...positions.current,...visible};try{localStorage.setItem(viewKey,JSON.stringify({...savedView(),positions:positions.current}));}catch{}}
  function saveViewport(){if(!fitted.current||!graph.current||!model.nodes.length)return;const center=graph.current.centerAt(),zoom=graph.current.zoom();if(!Number.isFinite(center.x)||!Number.isFinite(center.y)||!Number.isFinite(zoom))return;try{localStorage.setItem(viewKey,JSON.stringify({...savedView(),viewport:{...center,zoom}}));}catch{}}
  const persist=useRef();persist.current=()=>{savePositions();saveViewport();};
  useEffect(()=>{const save=()=>persist.current();const hidden=()=>{if(document.hidden)save();};window.addEventListener('pagehide',save);document.addEventListener('visibilitychange',hidden);return()=>{window.removeEventListener('pagehide',save);document.removeEventListener('visibilitychange',hidden);};},[]);
  useEffect(()=>{const observer=new ResizeObserver(([entry])=>setSize({width:Math.floor(entry.contentRect.width),height:Math.floor(entry.contentRect.height)}));observer.observe(host.current);return()=>observer.disconnect();},[]);
  useEffect(()=>{if(!graph.current)return;dragging.current=false;released.current.clear();setDragActive(false);configureDragForces(graph.current,false);graph.current.d3ReheatSimulation();},[model]);
  useEffect(()=>{if(!reset)return;positions.current={};targets.current.clear();try{const view=savedView();delete view.viewport;view.positions={};localStorage.setItem(viewKey,JSON.stringify(view));}catch{}for(const n of model.nodes){delete n.fx;delete n.fy;n.manual=false;}released.current.clear();dragging.current=false;setDragActive(false);configureDragForces(graph.current,false);graph.current.d3ReheatSimulation();fitted.current=false;},[reset]);
  function stopped(){if(dragging.current||!model.nodes.length)return;if(released.current.size){settleDragNodes(released.current,targets.current,(n,target)=>motionOffset(animation,target,motionTime.current,phaseFor(n.id)));released.current.clear();lastFrame.current=performance.now();setDragActive(false);savePositions();return;}setDragActive(false);for(const n of model.nodes){n.fx=n.x;n.fy=n.y;targets.current.set(n.id,{x:n.x,y:n.y});}savePositions();if(!fitted.current){const view=savedView().viewport;fitted.current=true;if(view&&Number.isFinite(view.x)&&Number.isFinite(view.y)&&Number.isFinite(view.zoom)&&view.zoom>0){graph.current?.centerAt(view.x,view.y,0);graph.current?.zoom(view.zoom,0);}else graph.current?.zoomToFit(reducedMotion?0:1000,80);}}

  function animate(now){const elapsed=Math.min(100,now-(lastFrame.current||now));lastFrame.current=now;const paused=dragging.current||released.current.size||document.hidden||selected||animationMenuOpen||pointers.current.size||now-lastInteraction.current<250||document.querySelector('dialog[open]');
    const moving=!paused&&((animation!=='off'&&!reducedMotion)||motionSettling.current);
    const clock=labelClock.current;
    setKeepDrawing(!document.hidden&&(!!moving||now>=clock.nextUpdate||now<clock.fadeUntil+50));
    if(!moving)return;
    motionTime.current+=elapsed;let unsettled=false;const blend=1-Math.exp(-elapsed/120);for(const n of model.nodes){if(n.fx===undefined||n.manual)continue;const base=targets.current.get(n.id);if(!base)continue;const offset=motionOffset(reducedMotion?'off':animation,base,motionTime.current,phaseFor(n.id));if(Math.abs(base.x+offset.x-n.x)+Math.abs(base.y+offset.y-n.y)>.05)unsettled=true;n.x+=(base.x+offset.x-n.x)*blend;n.y+=(base.y+offset.y-n.y)*blend;n.fx=n.x;n.fy=n.y;}motionSettling.current=unsettled;}
  const animateRef=useRef();animateRef.current=animate;
  useEffect(()=>{let frame;const tick=now=>{animateRef.current(now);frame=requestAnimationFrame(tick);};frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame);},[]);
  useEffect(()=>{motionSettling.current=true;},[animation]);
  useEffect(()=>{const release=e=>{if(pointers.current.delete(e.pointerId))lastInteraction.current=performance.now();};window.addEventListener('pointerup',release);window.addEventListener('pointercancel',release);return()=>{window.removeEventListener('pointerup',release);window.removeEventListener('pointercancel',release);};},[]);
  function followDrag(n,delta={x:0,y:0}){lastInteraction.current=performance.now();if(dragging.current===n)return;dragging.current=n;releaseDragNeighbors(n,model.nodes,model.links,released.current,{x:n.x-delta.x,y:n.y-delta.y});configureDragForces(graph.current,true);setDragActive(true);}
  function endDrag(n){dragging.current=false;n.manual=true;n.fx=n.x;n.fy=n.y;targets.current.set(n.id,{x:n.x,y:n.y});lastInteraction.current=performance.now();savePositions();graph.current.d3ReheatSimulation();}

  const endpointId=n=>typeof n==='object'?n.id:n;
  const linked=l=>active&&(endpointId(l.source)===active||endpointId(l.target)===active);
  function draw(n,ctx,scale){
    if(!Number.isFinite(n.x)||!Number.isFinite(n.y)||!Number.isFinite(scale)||scale<=0)return;
    const isAgent=n.kind==='agent',agent=agentMap.get(n.agent_id),r=n.radius/scale,ink=n.color||'#60a5fa',statusInk=statusColor(n),emphasis=active===n.id||selected===n.id;
    ctx.save();ctx.globalAlpha=(agent?.active===false||n.state==='dismissed'?.35:1)*(visible(n)?1:.075);
    // Use Activity's screen-space halo and lighting.
    const halo=(emphasis?30:18)/scale;
    const glow=ctx.createRadialGradient(n.x,n.y,0,n.x,n.y,halo);
    glow.addColorStop(0,(statusInk||ink)+(emphasis?'75':'35'));glow.addColorStop(1,(statusInk||ink)+'00');
    ctx.fillStyle=glow;ctx.beginPath();ctx.arc(n.x,n.y,halo,0,Math.PI*2);ctx.fill();
    const fill=ctx.createRadialGradient(n.x-r*.3,n.y-r*.4,0,n.x,n.y,r*1.6);
    fill.addColorStop(0,'#effbff');fill.addColorStop(.3,ink);fill.addColorStop(1,ink+'70');
    ctx.beginPath();ctx.arc(n.x,n.y,r,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();
    ctx.beginPath();ctx.arc(n.x,n.y,r,0,Math.PI*2);ctx.strokeStyle=ink;ctx.lineWidth=.8/scale;ctx.stroke();
    if(statusInk){ctx.beginPath();ctx.arc(n.x,n.y,r+2/scale,0,Math.PI*2);ctx.strokeStyle=statusInk;ctx.lineWidth=1.5/scale;ctx.stroke();}
    if(emphasis){ctx.beginPath();ctx.arc(n.x,n.y,r+5/scale,0,Math.PI*2);ctx.strokeStyle=ink+'aa';ctx.lineWidth=1/scale;ctx.stroke();}
    if(isAgent&&['running','succeeded','failed','Mock'].includes(n.state)){ctx.beginPath();ctx.arc(n.x+r*.75,n.y+r*.75,4/scale,0,Math.PI*2);ctx.fillStyle={running:'#60a5fa',succeeded:'#4ade80',failed:'#facc15',Mock:'#c4b5fd'}[n.state];ctx.fill();}
    ctx.restore();}
  const labelRevision=useMemo(()=>JSON.stringify(model.nodes.map(n=>[n.id,n.label,n.state,n.radius])),[model]);
  const labelNodes=useMemo(()=>new Map(model.nodes.map(n=>[n.id,n])),[model]);
  function paintLabels(ctx,scale){
    if(!graph.current||!Number.isFinite(scale)||scale<=0)return;
    const origin=graph.current.screen2GraphCoords(0,0);
    const project=n=>({id:n.id,label:statusLabel(n),labelSuffix:statusSuffix(n),kind:activityKind(n.kind),x:(n.x-origin.x)*scale,y:(n.y-origin.y)*scale,radius:n.radius,degree:n.visibleDegree,preferred:['sources','people','tools','companies'].includes(activityKind(n.kind)),pinned:!!n.manual,emphasis:n.id===active||n.id===selected});
    ctx.save();
    const labels=labelLayout.current(()=>model.nodes.filter(visible).map(project),{width:size.width,height:size.height,zoom:scale,cameraKey:`${scale}:${origin.x}:${origin.y}`},(text,font)=>{ctx.font=`500 ${font}px ${uiFont}`;return ctx.measureText(text).width;},performance.now(),JSON.stringify([labelRevision,size,active,selected,dragActive]),reducedMotion,id=>{const n=labelNodes.get(id);return n?project(n):null;});
    labelClock.current={nextUpdate:labels.nextUpdate,fadeUntil:labels.fadeUntil};
    for(const box of labels){
      ctx.globalAlpha=box.alpha;
      const x=origin.x+box.x/scale,y=origin.y+box.y/scale,ink=labelNodes.get(box.node.id)?.color||'#60a5fa';
      ctx.fillStyle=box.node.emphasis?'#142a42f5':'#0a1728ee';ctx.beginPath();ctx.roundRect(x,y,box.w/scale,box.h/scale,5/scale);ctx.fill();
      ctx.strokeStyle=ink+(box.node.emphasis?'90':'30');ctx.lineWidth=.6/scale;ctx.stroke();
      ctx.font=`500 ${box.font/scale}px ${uiFont}`;ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillStyle=box.node.emphasis?'#ffffff':'#d9e9fa';
      box.lines.forEach((line,index)=>ctx.fillText(line,x+6/scale,y+(12+index*16)/scale));
    }
    ctx.restore();
  }
  return <div className="fleet-map" ref={host} onPointerDownCapture={e=>{pointers.current.add(e.pointerId);lastInteraction.current=performance.now();}} onWheel={()=>{lastInteraction.current=performance.now();}}><ForceGraph2D ref={graph} width={size.width} height={size.height} graphData={model} backgroundColor="transparent" nodeLabel={()=>''} nodeVal={n=>n.radius*n.radius/20} nodeCanvasObject={draw} nodePointerAreaPaint={(n,color,ctx)=>{ctx.fillStyle=color;ctx.beginPath();ctx.arc(n.x,n.y,(n.radius+4)/(graph.current?.zoom()||1),0,Math.PI*2);ctx.fill();}} linkColor={l=>(l.target.color||'#60a5fa')+(active?(linked(l)?'df':'07'):(model.nodes.length<=35?'70':'32'))} linkWidth={l=>linked(l)?2:model.nodes.length<=35?1.1:.65} linkCurvature={.16} linkDirectionalArrowLength={l=>l.direction==='none'?0:['delegates','triggers','produced'].includes(l.relation)?4:0} linkDirectionalArrowRelPos={.8} onNodeHover={n=>{setHovered(n?.id||null);if(host.current)host.current.style.cursor=n?'pointer':'grab';}} onNodeClick={n=>select(n.id)} onBackgroundClick={()=>select('')} onNodeDrag={followDrag} onNodeDragEnd={endDrag} onZoomEnd={saveViewport} onEngineStop={stopped} onRenderFramePost={paintLabels} autoPauseRedraw={!keepDrawing} cooldownTicks={dragActive?Infinity:90} d3VelocityDecay={dragActive?.2:.4} d3AlphaMin={.001} enableNodeDrag/><div ref={avatarLayer} className="fleet-graph-avatars" aria-hidden="true"/>{!model.nodes.length&&<div className="fleet-empty"><strong>No matching connections</strong><p>Adjust the text, dates, Spaces or object types.</p></div>}<div className="fleet-map-footer"><div className="fleet-viewport-controls" role="group" aria-label="Graph viewport"><button aria-label="Zoom in" title="Zoom in" onClick={()=>graph.current?.zoom(graph.current.zoom()*1.3,reducedMotion?0:1000)}>+</button><button aria-label="Zoom out" title="Zoom out" onClick={()=>graph.current?.zoom(graph.current.zoom()/1.3,reducedMotion?0:1000)}>−</button><button aria-label="Fit view" title="Fit view" onClick={()=>graph.current?.zoomToFit(reducedMotion?0:1000,80)}><svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/><rect x="7" y="7" width="10" height="10" rx="1"/></svg></button>{!fullscreen&&<button id="fleet-enter-fullscreen" aria-label="Fullscreen" title="Fullscreen" aria-expanded={fullscreen} onClick={()=>setFullscreen(true)}><svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/></svg></button>}</div></div></div>;
}
function FleetListAvatar({agent}){
 const host=useRef();
 useEffect(()=>{host.current.replaceChildren(globalThis.AgentAvatars.create(agent,{interactive:false}));},[agent.id,agent.name,agent.thumbnail,agent.color,agent.runtime,agent.classification]);
 return <span ref={host} className="fleet-list-avatar" aria-hidden="true"/>;
}
function App(){
 const [initialGraph,setInitialGraph]=useState(false),[initialSpaces,setInitialSpaces]=useState(false);
 const [data,setData]=useState({agents:[],nodes:[],edges:[],types:[],warnings:[]}),[primary,setPrimary]=useState(null),[catalog,setCatalog]=useState(null),[spaces,setSpaces]=useState([]),[selected,setSelected]=useState(()=>{const id=new URLSearchParams(location.search).get('agent');return id?'agent:'+id:'';});
 const [range,setRange]=useState(initialView.range||'0');
 const [query,setQuery]=useState(initialView.query||''),[space,setSpace]=useState(initialView.space||[]),[types,setTypes]=useState(initialView.types||null),[since,setSince]=useState(initialView.since||''),[until,setUntil]=useState(initialView.until||''),[runtime,setRuntime]=useState(initialView.runtime||''),[inactive,setInactive]=useState(initialView.inactive===true),[animation,setAnimation]=useState(matchMedia('(prefers-reduced-motion: reduce)').matches?'off':initialView.animation||'off'),[reset,setReset]=useState(0);
 const [editor,setEditor]=useState(null),[defaults,setDefaults]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false),[tab,setTab]=useState('outputs'),[filtersOpen,setFiltersOpen]=useState(false),[fullscreen,setFullscreen]=useState(false),[animationMenuOpen,setAnimationMenuOpen]=useState(false);const epoch=useRef(0),refreshing=useRef(false),refreshQueued=useRef(false);
 useEffect(()=>{if((initialGraph&&initialSpaces&&catalog)||error)window.BrainPageLoading?.finish();},[initialGraph,initialSpaces,catalog,error]);

 useEffect(()=>{if(!fullscreen)return;const shell=document.getElementById('agent-fleet');shell.classList.add('fleet-fullscreen');const outside=[...document.body.children].filter(el=>el!==shell&&el.id!=='activity-hotkey-help'&&!['SCRIPT','STYLE','DIALOG'].includes(el.tagName)).map(el=>[el,el.inert]);outside.forEach(([el])=>el.inert=true);document.getElementById('fleet-exit-fullscreen')?.focus();const escape=e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]')){e.preventDefault();setFullscreen(false);}};document.addEventListener('keydown',escape);return()=>{shell.classList.remove('fleet-fullscreen');outside.forEach(([el,wasInert])=>el.inert=wasInert);document.removeEventListener('keydown',escape);document.getElementById('fleet-enter-fullscreen')?.focus();};},[fullscreen]);
 async function refresh(){if(refreshing.current){refreshQueued.current=true;return;}refreshing.current=true;try{const id=++epoch.current;const [next,p]=await Promise.all([api('/graph'),api('/assistant?probe=false')]);if(id!==epoch.current)return;setData(old=>{if(next.corpus_available===false){const retained=old.nodes.filter(n=>n.record||n.corpus_entry),ids=new Set(retained.map(n=>n.id));next.nodes=[...next.nodes.filter(n=>!ids.has(n.id)),...retained];const keys=new Set(next.edges.map(e=>JSON.stringify(e)));next.edges.push(...old.edges.filter(e=>(ids.has(e.source)||ids.has(e.target))&&!keys.has(JSON.stringify(e))));}return JSON.stringify({...old,generated_at:''})===JSON.stringify({...next,generated_at:''})?old:next;});setPrimary(p);setInitialGraph(true);setTypes(old=>old||next.types.map(t=>t.id));}finally{refreshing.current=false;if(refreshQueued.current){refreshQueued.current=false;refresh().catch(e=>setError(e.message));}}}
 async function reloadCatalog(){setCatalog(await api('/catalogue'));}
 useEffect(()=>{Promise.all([refresh(),reloadCatalog(),fetch('/hfl-corpus/workspace-views').then(r=>r.json()).then(d=>setSpaces(d.views||[]))]).catch(e=>setError(e.message));const timer=setInterval(()=>{if(!document.hidden)refresh().catch(e=>setError(e.message));},15000);return()=>{clearInterval(timer);epoch.current++;};},[]);
 useEffect(()=>{try{localStorage.setItem(viewKey,JSON.stringify({...savedView(),query,space,types,since,until,range,runtime,animation,inactive}));}catch{}},[query,space,types,since,until,range,runtime,animation,inactive]);

 useEffect(()=>{refresh().catch(e=>setError(e.message));},[space.join(',')]);
 useEffect(()=>{const changed=()=>refresh().catch(e=>setError(e.message));const names=['hfl:actions-updated','hfl:ideas-updated','hfl:agent-updated','hfl:entry-created'];names.forEach(n=>window.addEventListener(n,changed));return()=>names.forEach(n=>window.removeEventListener(n,changed));},[]);
 useEffect(()=>{const update=()=>{const dates=graphDateRange(range);if(dates){setSince(dates.since);setUntil(dates.until);}};update();const timer=setInterval(update,60000);return()=>clearInterval(timer);},[range]);
 const filtered=useMemo(()=>filterFleet(data,{query,spaces:space,types:types||[],since,until,inactive,service:runtime}),[data,query,space,types,since,until,inactive,runtime]);
 const agent=selected.startsWith('agent:')?data.agents.find(a=>a.id===selected.slice(6)):null,node=data.nodes.find(n=>n.id===selected),outputs=filtered.nodes.filter(n=>n.kind!=='agent'&&n.agent_ids?.includes(agent?.id));
 const hudAgent=agent||data.agents.find(a=>a.id==='butler');
 const hud=useRef(),[hudNotice,setHudNotice]=useState('');
 useEffect(()=>{setHudNotice('');setTab('outputs');},[selected]);
 const sourceLink=fleetItemLink(node);
 const tabs=[{id:'outputs',label:'Outputs',count:outputs.length},{id:'profile',label:'Profile'},...(agent?.runtime==='hermes'&&!agent.mock&&!agent.managed_sharing?[{id:'conversation',label:'Conversation'}]:[])];
 const activeTab=tabs.some(item=>item.id===tab)?tab:'outputs';
 function viewHud(){setHudNotice(hud.current?.reveal(node.id)?'':'Not available in the current HUD view');}

 async function run(fn){setBusy(true);setError('');try{await fn();}catch(e){setError(e.message);}finally{setBusy(false);}}
 async function start(){const result=await api('/items/'+agent.id+'/prepare',{});window.hflAgentBridge.open('actionable',result.action_id,agent.name+' � Sessions');await refresh();}
 const serviceName=id=>catalog?.services.find(s=>s.id===id)?.name||id;
 return <><div className="fleet-toolbar"><a className="fleet-dashboard-link" href={hudAgent?'/second-brain?agent='+encodeURIComponent(hudAgent.id):'/second-brain'} aria-label="Show second brain dashboard" title="Show second brain dashboard"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="10" rx="1.5"/><rect x="14" y="3" width="7" height="6" rx="1.5"/><rect x="3" y="17" width="7" height="4" rx="1.5"/><rect x="14" y="13" width="7" height="8" rx="1.5"/></svg></a><a className="fleet-dashboard-link" href="/hfl-corpus/actions" aria-label="Show Kanban" title="Show Kanban"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16M5 8h2m4 0h2m4 0h2"/></svg></a><input aria-label="Search agents and outputs" type="search" placeholder="Search agents and outputs…" value={query} onChange={e=>setQuery(e.target.value)}/><button className="fleet-icon" aria-label="Refresh" title="Refresh" disabled={busy} onClick={()=>run(refresh)}><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8M21 3v5h-5"/></svg></button><button type="button" className="fleet-icon fleet-hotkeys" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (K)" aria-haspopup="dialog" aria-controls="activity-hotkey-help"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 9h.01M10 9h.01M14 9h.01M17 9h.01M7 12h.01M10 12h.01M14 12h.01M17 12h.01M8 15h8"/></svg></button><AnimationMenu value={animation} onChange={setAnimation} open={animationMenuOpen} setOpen={setAnimationMenuOpen}/><button aria-label="Reset positions" title="Reset positions" onClick={()=>setReset(v=>v+1)}>Reset</button><div className="fleet-actions fleet-toolbar-actions" role="group" aria-label="Fleet management"><CreateIntent/><button className="fleet-primary" disabled={!catalog} onClick={()=>setEditor({})}>Add agent</button><button title="Shared execution defaults for agents" onClick={()=>setDefaults(true)}>Agent settings</button><a className="fleet-connector-link" href="/applications?from=agents">Connect services</a></div><Spaces selected={space} modified={Boolean(query||since||until||runtime||inactive||(types&&types.length!==data.types.length))} onApply={(ids,snapshot)=>{setInitialSpaces(true);setSpaces(snapshot.views||[]);if(space.join(',')!==ids.join(',')){setSpace(ids);setQuery('');setRange('0');setSince('');setUntil('');}}}/><button className="fleet-filter-trigger" aria-haspopup="dialog" aria-controls="fleet-filter-drawer" aria-expanded={filtersOpen} onClick={()=>setFiltersOpen(true)}>Filters</button></div>
 {filtersOpen&&<Dialog title="Filters" id="fleet-filter-drawer" className="fleet-filter-drawer" close={()=>setFiltersOpen(false)}><div className="fleet-filter-fields"><label>Service<select aria-label="Service" value={runtime} onChange={e=>setRuntime(e.target.value)}><option value="">All services</option>{catalog?.services.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label><div className="fleet-date-fields"><label>Date range<select aria-label="Date range" value={range} onChange={e=>setRange(e.target.value)}>{[['0','Fixed dates'],['week','This week'],['7','Last 7 days'],['30','Last 30 days'],['90','Last 90 days'],['365','Last 365 days']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>From<input aria-label="From date" type="date" value={since} max={until||undefined} onChange={e=>{setRange('0');setSince(e.target.value);}}/></label><label>Through<input aria-label="Through date" type="date" value={until} min={since||undefined} onChange={e=>{setRange('0');setUntil(e.target.value);}}/></label></div><p className="fleet-filter-date-hint">Dates filter activity. Actions and ideas remain visible across dates; dismissed items are hidden.</p><fieldset className="fleet-filter-type-group"><legend>Node types</legend><div className="fleet-filter-types">{data.types.map(t=><label key={t.id}><input type="checkbox" checked={types?.includes(t.id)||false} onChange={e=>setTypes(old=>e.target.checked?[...old,t.id]:old.filter(v=>v!==t.id))}/><i style={{background:t.color}}/>{t.name}</label>)}</div></fieldset><label className="fleet-filter-toggle"><input type="checkbox" role="switch" checked={inactive} onChange={e=>setInactive(e.target.checked)}/>Show deactivated</label><button onClick={()=>{setQuery('');setRange('0');setSince('');setUntil('');setRuntime('');setTypes(data.types.map(t=>t.id));}}>Reset filters</button></div></Dialog>}
 {error&&<div role="alert" className="fleet-alert">{error}</div>}{data.warnings.map(w=><div className="fleet-alert" key={w}>{w}</div>)}
 <div className={"fleet-workspace"+((agent||node)?" fleet-has-selection":"")+(hudAgent?" fleet-has-hud":"")}>{fullscreen&&<button id="fleet-exit-fullscreen" className="fleet-exit-fullscreen" onClick={()=>setFullscreen(false)}>Exit fullscreen</button>}{hudAgent&&<AgentHud ref={hud} key={hudAgent.id} agents={data.agents} agent={hudAgent} nodes={data.nodes} owner={owner} spaceKey={space.join(',')}/>}<FleetGraph data={filtered} agents={data.agents} selected={selected} select={setSelected} animation={animation} animationMenuOpen={animationMenuOpen} reset={reset} fullscreen={fullscreen} setFullscreen={setFullscreen}/><aside className="fleet-inspector">{!agent&&!node&&<section className="fleet-agent-overview"><div className="fleet-detail-empty"><h2>Select an agent or output</h2><p>Explore connected work, review results and configure agents from one view.</p></div><OwnerCard node={data.nodes.find(n=>n.kind==='owner')} onSelect={setSelected}/><h3 className="fleet-list-title">Agents · {filtered.nodes.filter(n=>n.kind==='agent').length}</h3><div className="fleet-list" aria-label="Agent list">{filtered.nodes.filter(n=>n.kind==='agent').map(n=><button key={n.id} aria-label={'Select '+n.label} onClick={()=>setSelected(n.id)}><FleetListAvatar agent={data.agents.find(a=>a.id===n.agent_id)||{id:n.agent_id,name:n.label,color:n.color}}/><span className="fleet-list-name">{n.label}</span><small>{serviceName(data.agents.find(a=>a.id===n.agent_id)?.runtime)}</small></button>)}</div></section>}{!agent&&!node&&<section className="fleet-entity-legend" aria-labelledby="fleet-legend-title"><h3 id="fleet-legend-title">Entity orbs</h3><ul>{data.types.map(t=><li key={t.id}><button type="button" aria-pressed={types?.includes(t.id)||false} onClick={()=>setTypes(old=>(old||[]).includes(t.id)?old.filter(id=>id!==t.id):[...(old||[]),t.id])}><i aria-hidden="true" style={{background:t.color,color:t.color}}/>{t.name.toLowerCase()}</button></li>)}</ul></section>}
 {agent?<><span className="fleet-eyebrow">{serviceName(agent.runtime)} / {agent.id===primary?.agent_id?'PRIMARY ASSISTANT':'AGENT'}</span><h2>{agent.name}</h2><span className="fleet-badge">{agent.active?agent.state:'Deactivated'}</span>{agent.gateway?.enabled&&<span className="fleet-badge">Gateway configured · {agent.gateway.mode==='setup'?'setup only':agent.gateway.mode==='execute'?'tasks':'chat'}</span>}<span className="fleet-badge">{catalog?.classifications.find(c=>c.id===agent.classification)?.name||'General purpose'}</span>{agent.mock&&<span className="fleet-badge fleet-mock">Mock · no remote execution</span>}<p>{agent.description||'Configure this agent’s purpose and capabilities.'}</p><div className="fleet-actions fleet-agent-toolbar" role="group" aria-label="Agent controls">
 {agent.runtime==='hermes'?<><IconButton label="Open session" icon="terminal" disabled={busy||!agent.active||agent.mock||agent.managed_sharing} className="fleet-primary" onClick={()=>run(start)}/>{agent.id===primary?.agent_id&&<IconButton label="Chat with HARQIS Butler" icon="chat" onClick={()=>document.getElementById('butler-launch')?.click()}/>}</>:agent.runtime==='nod'?<NodStatus key={agent.id+agent.version} identity={agent.id} api={api} configure={()=>setEditor(agent)}/>:<a className="fleet-inspector-icon fleet-connect-icon" href="/applications" aria-label={agent.connector_user?'Manage connector':'Connect service'} title={agent.connector_user?'Manage connector':'Connect service'}><InspectorIcon name="connect"/></a>}
 <IconButton label="Edit" icon="settings" onClick={()=>setEditor(agent)}/><IconButton label={agent.active?'Deactivate':'Activate'} icon="power" title={agent.id==='butler'?'Butler is always available':agent.active?'Deactivate':'Activate'} disabled={busy||agent.id==='butler'} onClick={()=>run(async()=>{await api('/items/'+agent.id,{version:agent.version,active:!agent.active});await refresh();})}/></div>
 <InspectorTabs items={tabs} value={activeTab} onChange={setTab}/>
 <div id="fleet-agent-panel" className="fleet-agent-panel" role="tabpanel" aria-labelledby={'fleet-tab-'+activeTab} tabIndex={0}>
 {activeTab==='conversation'&&agent.runtime==='hermes'&&!agent.mock&&!agent.managed_sharing?<FleetConversation key={agent.id} agent={agent} configure={()=>setEditor(agent)}/>:activeTab==='outputs'?<><p>Produced work and monitored sources. Object filters also apply here.</p><div className="fleet-output-list">{outputs.map(o=><button key={o.id} onClick={()=>setSelected(o.id)}><span className="fleet-output-kind" style={{color:o.color}}>{o.kind}{o.mock?' · mock':''}</span><strong>{o.label}</strong><small>{o.state||o.source||'Configured'}{o.created?' · '+new Date(o.created).toLocaleDateString():''}</small></button>)}{!outputs.length&&<p>No matching recorded outputs yet.</p>}</div></>:<><h3>Persona</h3><p>{agent.persona||'No persona set'}</p><h3>Execution</h3><p>{agent.mock?'Simulated profile; execution is disabled.':agent.runtime==='hermes'?(agent.gateway?.enabled?'Per-agent gateway configured. Open Conversation to chat or run tasks; Open session uses the existing action bridge.':'Configured Hermes worker; task execution uses the existing action bridge.'):agent.runtime==='nod'?'Nod runs externally. Task dispatch, status polling and result capture are not connected yet. Manage execution and schedules in Nod.':'Execution is managed by the service. Activating or deactivating here controls visibility in this fleet; it does not stop the remote service.'}</p><h3>Capabilities</h3>{['skills','tools','workflows','triggers','subagents'].map(k=><div key={k}><h3>{k}</h3><div className="fleet-related">{agent[k].map(v=><span key={v} className="fleet-badge">{(catalog?.skills.find(s=>s.id===v)||catalog?.workflows.find(s=>s.id===v)||data.agents.find(a=>a.id===v))?.name||v}</span>)}{!agent[k].length&&<span className="fleet-status">None linked</span>}</div></div>)}<h3>Spaces</h3><p>{agent.workspace_ids.map(id=>spaces.find(s=>s.id===id)?.name||'Unavailable Space').join(', ')||'All activity'}</p></>}
 </div>
 </>:node?<><span className="fleet-eyebrow">{node.kind}{node.temporary?' / TEMPORARY SUBAGENT':''}</span><h2>{node.label}</h2>{node.mock&&<span className="fleet-badge fleet-mock">Simulated output</span>}<span className="fleet-badge">{({open:'In Review',active:'Ready',in_progress:'In Progress',incomplete:'Incomplete',done:'Done',dismissed:'Dismissed'}[node.state])||node.state||node.source||'Recorded'}</span><Description node={node}/>{node.created&&<time>{new Date(node.created).toLocaleString()}</time>}{node.kind==='hud'?<><button type="button" className="fleet-record-link" onClick={viewHud}>View</button>{hudNotice&&<p role="status">{hudNotice}</p>}</>:sourceLink&&!node.record&&<a className="fleet-record-link" href={sourceLink.href} target={sourceLink.external?'_blank':undefined} rel="noopener noreferrer">{sourceLink.label}</a>}{node.record&&<><IntentControls node={node}/>{node.kind==='idea'&&<IdeaAssignment key={node.id+node.assigned_agent_id} node={node} agents={data.agents} api={api}/>}</>}<h3>Provenance & relationships</h3><Relationships key={node.id} node={node} data={data} onSelect={setSelected}/></>:null}
</aside></div>
 {editor&&catalog&&<Editor agent={editor.id?editor:null} agents={data.agents} catalog={catalog} spaces={spaces} close={()=>setEditor(null)} saved={refresh} reloadCatalog={reloadCatalog}/>} {defaults&&<Defaults close={()=>setDefaults(false)}/>}</>;
}
createRoot(document.getElementById('agent-fleet')).render(<App/>);
