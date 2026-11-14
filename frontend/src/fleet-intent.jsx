import React, {useEffect,useRef,useState} from 'react';

// Keep the mature card/editor implementations as the single command surface.
export function IntentControls({node}) {
 const host=useRef(),[error,setError]=useState('');
 useEffect(()=>{
  const root=host.current;root.replaceChildren();setError('');
  if(!node.record)return;
  if(node.kind==='action'){
   const card=window.hflActions.card(node.record);
   for(const part of card.querySelectorAll('.action-evidence-link,.action-controls'))root.append(part);
   return;
  }
  const item=node.record, buttons=[
   ['Promote',()=>window.HflIdeas.convert(item.id)],
   ['Create connected action',()=>window.HflIdeas.openEditor('actionable',{}, {id:'idea:'+item.id,kind:'ideas',object_id:item.id,label:item.title})],
   ['Clone',()=>window.HflIdeas.cloneObject('idea',item.id)],
   ['Edit',()=>window.HflIdeas.editIdea(item.id)],
   [item.status==='dismissed'?'Restore':'Dismiss',async()=>{
    const {item:latest}=await window.HflIdeas.api('/objects/'+item.id);
    await window.HflIdeas.api('/objects/'+item.id,'PATCH',{version:latest.version,status:latest.status==='dismissed'?'suggested':'dismissed'});
    window.dispatchEvent(new Event('hfl:ideas-updated'));
   }]
  ];
  for(const [label,action] of buttons){const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=async()=>{button.disabled=true;try{await action();setError('');}catch(e){setError(e.message);}finally{button.disabled=false;}};root.append(button);}
 },[node]);
 return <><div className="fleet-intent-controls" ref={host}/>{error&&<p role="alert">{error}</p>}</>;
}

export function CreateIntent() {
 const menu=useRef();
 useEffect(()=>{const outside=e=>{if(!menu.current?.contains(e.target))menu.current.open=false;};document.addEventListener('click',outside);return()=>document.removeEventListener('click',outside);},[]);
 function create(kind){menu.current.open=false;if(kind==='entry')document.getElementById('fleet-create-entry').click();else window.HflIdeas.openEditor(kind);}
 return <details ref={menu} className="fleet-create" onKeyDown={e=>{if(e.key==='Escape'){menu.current.open=false;menu.current.querySelector('summary').focus();}}}><summary className="fleet-primary">Create<svg aria-hidden="true" viewBox="0 0 20 20" width="20" height="20"><path d="m5 7.5 5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg></summary><div>{[['entry','Entry'],['actionable','Action'],['idea','Idea']].map(([kind,label])=><button key={kind} onClick={()=>create(kind)}>{label}</button>)}</div></details>;
}
