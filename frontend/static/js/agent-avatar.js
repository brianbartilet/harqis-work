/* Shared native-image avatars: the browser preserves animated GIF playback. */
(() => {
  const services={hermes:'Hermes',codex:'Codex',claude:'Claude',chatgpt:'ChatGPT',n8n:'n8n',nod:'Nod',grokbot:'Grok Bot',service:'Other agent service'};
  const classifications={coding:'Coding agent',general:'General purpose',workflows:'Workflow agent'};
  function initials(name){return (name||'').split('·')[0].trim().split(/\s+/).filter(Boolean).slice(0,2).map(word=>Array.from(word)[0]).join('').toLocaleUpperCase()||'?';}
  function label(agent){return `${agent.name} · ${services[agent.runtime]||agent.runtime||'Agent'} · ${classifications[agent.classification]||agent.classification||'General purpose'}`;}
  function create(agent,{interactive=true}={}){
    const node=document.createElement('span');node.className='agent-avatar';
    node.style.setProperty('--agent-color',agent.color||'#67e8f9');
    const text=label(agent);node.setAttribute('aria-label',text);node.setAttribute('role','img');
    if(interactive){node.tabIndex=0;node.title=text;const tip=document.createElement('span');tip.className='agent-avatar-tooltip';tip.textContent=text;node.append(tip);}
    const fallback=document.createElement('span');fallback.className='agent-avatar-initials';fallback.textContent=initials(agent.name);fallback.setAttribute('aria-hidden','true');node.append(fallback);
    if(agent.thumbnail){const img=document.createElement('img');img.alt='';img.addEventListener('load',()=>{fallback.style.visibility='hidden';},{once:true});img.addEventListener('error',()=>{fallback.style.visibility='';img.remove();},{once:true});img.src='/agents/api/assets/'+encodeURIComponent(agent.thumbnail);node.append(img);}
    return node;
  }
  function group(agents){const node=document.createElement('span');node.className='agent-avatar-group';for(const agent of agents)node.append(create(agent));return node;}
  globalThis.AgentAvatars={initials,label,create,group};
})();
