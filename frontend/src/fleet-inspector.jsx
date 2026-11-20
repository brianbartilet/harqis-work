import React from 'react';

export function InspectorIcon({name}) {
 const paths={external:'M14 3h7v7 M21 3 11 13 M10 3H3v18h18v-7',refresh:'M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8M21 3v5h-5',connect:'M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-12 0V8Zm6 9v4',terminal:'m5 7 5 5-5 5m8 0h6',chat:'M5 3h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H8l-5 3V5a2 2 0 0 1 2-2Z M7 8h10M7 12h7',settings:'M21.45 11.07 L21.45 12.93 L19.18 14.18 L18.61 15.54 L19.34 18.03 L18.03 19.34 L15.54 18.61 L14.18 19.18 L12.93 21.45 L11.07 21.45 L9.82 19.18 L8.46 18.61 L5.97 19.34 L4.66 18.03 L5.39 15.54 L4.82 14.18 L2.55 12.93 L2.55 11.07 L4.82 9.82 L5.39 8.46 L4.66 5.97 L5.97 4.66 L8.46 5.39 L9.82 4.82 L11.07 2.55 L12.93 2.55 L14.18 4.82 L15.54 5.39 L18.03 4.66 L19.34 5.97 L18.61 8.46 L19.18 9.82 Z M15.5 12a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0',power:'M12 2v10M6.3 5.3a9 9 0 1 0 11.4 0',expand:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5h5v-5',collapse:'M3 8h5V3m8 0v5h5M8 21v-5H3m18 0h-5v5'};
 return <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]}/></svg>;
}
export function IconButton({label,icon,...props}) {
 return <button type="button" {...props} className={'fleet-inspector-icon '+(props.className||'')} aria-label={label} title={props.title||label}><InspectorIcon name={icon}/></button>;
}
export function InspectorTabs({items,value,onChange}) {
 function keys(event){
  const index=items.findIndex(item=>item.id===value);
  const next=event.key==='Home'?0:event.key==='End'?items.length-1:event.key==='ArrowRight'?(index+1)%items.length:event.key==='ArrowLeft'?(index+items.length-1)%items.length:null;
  if(next===null)return;event.preventDefault();onChange(items[next].id);event.currentTarget.querySelectorAll('[role=tab]')[next].focus();
 }
 return <div className="fleet-inspector-tabs" role="tablist" aria-label="Agent details" onKeyDown={keys}>{items.map(item=><button type="button" role="tab" key={item.id} id={'fleet-tab-'+item.id} aria-selected={value===item.id} aria-controls="fleet-agent-panel" tabIndex={value===item.id?0:-1} onClick={()=>onChange(item.id)}>{item.label}{item.count!==undefined&&<span className="fleet-tab-count">{item.count}</span>}</button>)}</div>;
}
