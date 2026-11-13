import React,{useLayoutEffect,useRef} from 'react';
import '../static/js/agent-avatar.js';

export function AgentAvatars({agents}){
  const host=useRef();
  const signature=JSON.stringify(agents.map(({id,name,thumbnail,color,runtime,classification})=>({id,name,thumbnail,color,runtime,classification})));
  useLayoutEffect(()=>{host.current.replaceChildren(...agents.map(agent=>globalThis.AgentAvatars.create(agent)));},[signature]);
  return <span ref={host} className="agent-avatar-group"/>;
}
