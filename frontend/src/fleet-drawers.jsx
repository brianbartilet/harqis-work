import React,{useRef,useState} from 'react';

export function FleetDrawers({work,hud,open:controlledOpen,onOpenChange}){
 const [localOpen,setLocalOpen]=useState('work'),buttons=useRef({});
 const open=controlledOpen??localOpen;
 function setOpen(next){const value=typeof next==='function'?next(open):next;if(onOpenChange)onOpenChange(value);else setLocalOpen(value);}
 function close(){const previous=open;setOpen('');buttons.current[previous]?.focus();}
 return <div className="fleet-left-drawers" data-open={open} onKeyDown={event=>{
  if(event.key!=='Escape'||event.defaultPrevented||event.target.closest('dialog,[role=dialog]')||event.currentTarget.querySelector('details[open]'))return;
  if(open){event.preventDefault();event.stopPropagation();close();}
 }}>
  <nav className="fleet-drawer-nav" aria-label="Workspace drawers">
   {[['work','Agent work','M4 5h16v15H4z M8 3v4m8-4v4M8 11h8m-8 4h5'],['hud','HUD','M3 3h7v10H3z M14 3h7v6h-7z M3 17h7v4H3z M14 13h7v8h-7z']].map(([id,label,path])=><button key={id} ref={el=>buttons.current[id]=el} type="button" aria-label={label} title={label} aria-expanded={open===id} aria-controls={'fleet-'+id+'-drawer'} onClick={()=>setOpen(id)}>
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={path}/></svg>
   </button>)}
  </nav>
  {[['work','Agent work',work],['hud','HUD',hud]].map(([id,label,content])=><section key={id} id={'fleet-'+id+'-drawer'} className="fleet-left-drawer" aria-label={label+' drawer'} hidden={open!==id}>

   <div className="fleet-drawer-content">{content}</div>
  </section>)}
 </div>;
}
