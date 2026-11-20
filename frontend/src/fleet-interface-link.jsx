import React from 'react';
import {InspectorIcon} from './fleet-inspector.jsx';

export function OpenAgentInterface({url,provider,iconOnly=false}){
 try{const parsed=new URL(url);if(!['http:','https:'].includes(parsed.protocol)||parsed.username||parsed.password)return null;}catch{return null;}
 const label='Open '+provider+' in new window';
 return <a className={iconOnly?'fleet-inspector-icon fleet-connect-icon':'fleet-nod-button fleet-primary'} href={url} target="_blank" rel="noopener noreferrer" aria-label={label} title={label} onClick={event=>{
  if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
  const popup=window.open(url,'_blank','popup,width=1200,height=850');
  if(popup){popup.opener=null;event.preventDefault();popup.focus();}
 }}><InspectorIcon name="external"/>{!iconOnly&&<span>Open {provider}</span>}</a>;
}
