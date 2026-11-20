import React from 'react';

export function AgentTypePill({agent,label}){
 const color=/^#[0-9a-f]{6}$/i.test(agent?.color||'')?agent.color:'#67e8f9';
 return <span className="action-agent-type" style={{'--agent-type-color':color}}>{label||agent?.runtime||'agent'}</span>;
}
