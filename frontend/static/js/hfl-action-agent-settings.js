/* Shared optional Action assignment editor; saved alongside Action changes. */
(() => {
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 async function api(path,payload,method){
  const csrf=JSON.parse(document.querySelector('[data-memory-csrf]')?.textContent||'""');
  const response=await fetch(path,{method:method||(payload===undefined?'GET':'POST'),headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
  const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Could not save Action assignment.');return data;
 }
 const base='/hfl-corpus/agent-bridge';
 window.HflActionAgentSettings=(form,sourceId,initialAssignment)=>{
  form.actionAssignment?.dispose();
  const section=form.querySelector('[data-action-agent-settings]');if(!section)return;
  section.open=false;
  const summary=section.querySelector('[data-agent-settings-summary]'),status=section.querySelector('[data-agent-settings-status]');
  const controls=section.querySelector('[data-agent-assignment-controls]');controls.replaceChildren();summary.replaceChildren();
  let alive=true,dirty=false,revision=0,config=null,load=null,closePicker=()=>{};
  const dialogs=new Set();
  let draft={assignment_mode:sourceId?'legacy':'manual',agent_id:'',specialist_mode:'inherit',specialist_profile:null,additional_instructions:''};
  const changed=()=>{dirty=true;revision++;paintSummary();form.dispatchEvent(new Event('input',{bubbles:true}));};
  function paintSummary(){
   if(!config)return;
   const s=config.effective;
   summary.replaceChildren();
   for(const [label,value] of [['Runtime profile',s.hermes_profile||'Worker profile'],['Permissions',s.agent_mode],['Idle expiry',s.agent_session_expiry_minutes+' minutes']]){const cell=el('div');cell.append(el('dt',label),el('dd',value));summary.append(cell);}
  }
  function select(label,options,value,change){const wrap=el('label',label),input=el('select');input.setAttribute('aria-label',label);for(const [v,n] of options)input.append(new Option(n,v));input.value=value;input.onchange=()=>{change(input.value);changed();};wrap.append(input);controls.append(wrap);return wrap;}
  function render(){
   closePicker();summary.remove();controls.replaceChildren();
   select('Work assignment',[['manual','No agent'],['butler','Butler coordination'],['agent','Fleet agent'],['legacy','Default worker']],draft.assignment_mode,v=>{draft.assignment_mode=v;draft.agent_id=v==='butler'?'butler':v==='agent'?draft.agent_id:'';render();});
   if(draft.assignment_mode==='agent'){
    const wrap=el('div'),heading=el('span','Assigned agent'),menu=el('details');menu.className='action-agent-picker';
    const trigger=el('summary');trigger.setAttribute('aria-label','Assigned agent');
    const current=config.agents.find(a=>a.id===draft.agent_id);
    function agentLabel(host,agent){host.append(el('span',agent.name));const pill=el('span',agent.runtime);pill.className='action-agent-type';if(/^#[0-9a-f]{6}$/i.test(agent.color||''))pill.style.setProperty('--agent-type-color',agent.color);host.append(pill);if(!agent.active)host.append(el('span','Inactive'));}
    if(current)agentLabel(trigger,current);else trigger.append(el('span',draft.agent_id?'Unavailable assigned agent':'Select an agent'));
    const options=el('div');options.className='action-agent-options';options.setAttribute('role','group');options.setAttribute('aria-label','Available agents');
    for(const a of config.agents.filter(a=>a.active)){const option=el('button');option.type='button';option.setAttribute('aria-pressed',String(a.id===draft.agent_id));agentLabel(option,a);option.onclick=()=>{draft.agent_id=a.id;render();changed();controls.querySelector('.action-agent-picker summary')?.focus();};options.append(option);}
    if(!config.agents.some(a=>a.active))options.append(el('p','No active Fleet agents available.'));
    const dismiss=event=>{if(!menu.contains(event.target))menu.open=false;};document.addEventListener('pointerdown',dismiss);closePicker=()=>document.removeEventListener('pointerdown',dismiss);
    menu.append(trigger,options);wrap.append(heading,menu);controls.append(wrap);
    menu.onkeydown=event=>{const buttons=[...options.querySelectorAll('button')];if(event.key==='Escape'){menu.open=false;trigger.focus();event.preventDefault();}else if(['ArrowDown','ArrowUp'].includes(event.key)&&buttons.length){menu.open=true;const i=buttons.indexOf(document.activeElement);buttons[(i+(event.key==='ArrowDown'?1:buttons.length-1)+buttons.length)%buttons.length].focus();event.preventDefault();}};
    const agent=config.agents.find(a=>a.id===draft.agent_id);
    if(agent&&!['hermes','nod'].includes(agent.runtime))controls.append(el('p','Assignment only: this connector cannot run Actions yet.'));
    if(agent?.runtime==='nod')controls.append(el('p','Nod runs one Action at a time in its shared conversation. Supporting files are not supported for Nod Actions yet.'));
   }
   if(draft.assignment_mode==='butler'){
    controls.append(el('p','The butler plans the work, reviews delegated results, and reports progress here.'));
    const permitted=el('fieldset');permitted.className='action-execution-options';permitted.append(el('legend','Permitted delegation targets'));
    for(const agent of config.agents.filter(a=>a.active&&a.id!=='butler'&&['hermes','nod'].includes(a.runtime))){
     const label=el('label'),input=el('input');input.type='checkbox';input.checked=(draft.permitted_agent_ids||[]).includes(agent.id);
     input.onchange=()=>{draft.permitted_agent_ids=input.checked?[...new Set([...(draft.permitted_agent_ids||[]),agent.id])]:(draft.permitted_agent_ids||[]).filter(id=>id!==agent.id);changed();};
     label.className='action-execution-check';label.append(input,document.createTextNode(agent.name));permitted.append(label);
    }
    controls.append(permitted);
   }
   if(draft.assignment_mode==='manual'){
    controls.append(el('p','You handle this Action. No agent will run automatically.'));return;
   }
   const schedule=el('fieldset');schedule.className='action-execution-options';schedule.append(el('legend','Action trigger'));
   const enabledLabel=el('label'),enabledInput=el('input');enabledInput.type='checkbox';enabledInput.checked=!!draft.schedule_enabled;
   enabledLabel.className='action-execution-check';enabledLabel.append(enabledInput,document.createTextNode('Scheduled discovery while Ready'));schedule.append(enabledLabel);
   const intervalLabel=el('label','Interval (minutes)'),interval=el('input');interval.type='number';interval.min='1';interval.max='10080';interval.value=draft.schedule_minutes||60;
   interval.oninput=()=>{draft.schedule_minutes=Number(interval.value);changed();};enabledInput.onchange=()=>{draft.schedule_enabled=enabledInput.checked;changed();};intervalLabel.append(interval);schedule.append(intervalLabel,el('small','Closed Actions stay closed. Without a schedule, Ready Actions are discovered within one minute.'));
   controls.append(schedule);
   function modal(title,trigger){
    const popup=el('dialog');popup.className='agenda-dialog action-profile-dialog';popup.setAttribute('aria-label',title);
    const header=el('header');header.className='agenda-dialog-header';header.append(el('h2',title));
    const close=el('button','×');close.type='button';close.setAttribute('aria-label','Close');close.onclick=()=>popup.close();header.append(close);
    const content=el('div');content.className='action-profile-content';content.setAttribute('data-agent-assignment-controls','');popup.append(header,content);document.body.append(popup);dialogs.add(popup);
    popup.addEventListener('close',()=>{dialogs.delete(popup);popup.cleanup?.();popup.remove();if(trigger?.isConnected)trigger.focus();},{once:true});popup.showModal();return {popup,content};
   }
   const guidance=el('details');guidance.className='action-guidance';guidance.open=Boolean(draft.additional_instructions);guidance.append(el('summary','Additional guidance'));
   const text=el('textarea');text.rows=3;text.maxLength=20000;text.value=draft.additional_instructions;text.placeholder='Instructions specific to this Action';text.setAttribute('aria-label','Additional Action guidance');text.oninput=()=>{draft.additional_instructions=text.value;changed();};guidance.append(text);controls.append(guidance);
   const preview=el('button','Preview instructions');preview.type='button';preview.className='action-preview-link';
   preview.onclick=async()=>{const {popup,content}=modal('Instructions for this Action',preview);content.append(el('p','Preparing preview…'));try{
    const result=await api(base+'/configuration/preview',{...config.card,...draft,source_id:sourceId||'',task_prompt:form.elements.prompt?.value||'',expected_outcome:form.elements.expected_outcome?.value||''});
    if(!popup.open)return;const rendered=await api('/hfl-corpus/timeline/ideas/render',{body:result.instructions||'No specialist or additional guidance. The Action prompt supplies the task.'});
    if(!popup.open)return;const output=el('div');output.className='action-instructions-text markdown-inline-preview markdown-body';output.innerHTML=rendered.html;content.replaceChildren(output);
   }catch(e){if(popup.open){const error=el('p',e.message);error.setAttribute('role','alert');content.replaceChildren(error);}}};
   controls.append(preview,el('p','Applies to this Action. Existing runs keep their saved instructions.'));
   const runtime=el('details');runtime.className='action-runtime-settings';runtime.append(el('summary','Execution settings'),summary);
   const defaults=el('a','Agent default settings');defaults.href='/agents';defaults.target='_blank';defaults.rel='noopener noreferrer';runtime.append(defaults);controls.append(runtime);
   paintSummary();
  }
  async function refresh(){
   if(load)return load;
   status.hidden=false;status.textContent='Loading agent settings…';
   load=(async()=>{try{
    const data=await api(base+(sourceId?'/actions/'+encodeURIComponent(sourceId)+'/configuration':'/configuration/defaults'));
    if(!alive)return;config=data;config.agents||=[];
    if(!dirty)draft={...draft,...config.card,schedule_enabled:!!config.schedule?.enabled,schedule_minutes:config.schedule?.minutes||60,assignment_mode:config.card.assignment_mode||(config.card.agent_id?'agent':'legacy'),...(!sourceId?initialAssignment:{})};
    render();status.hidden=true;
   }catch(e){if(alive){status.hidden=false;status.textContent=e.message;}}finally{load=null;}})();return load;
  }
  section.ontoggle=()=>{if(section.open&&!dirty)void refresh();};
  const dialog=form.closest('dialog'),closed=()=>form.actionAssignment?.dispose();
  dialog?.addEventListener('close',closed,{once:true});
  form.actionAssignment={
   snapshot:()=>dirty?JSON.stringify(draft):'',
   prepare(payload){if(dirty||!sourceId)payload.agent_enabled=false;},
   async save(item){
    if(!dirty&&sourceId)return item;
    if(!config)await refresh();if(!config)throw Error('Action saved without automation. Load agent settings and retry.');
    const saving=structuredClone(draft),version=revision;
    const result=await api(base+'/actions/'+encodeURIComponent(item.id)+'/configuration',{...config.card,...saving});
    const enabled=saving.assignment_mode!=='manual'&&result.effective.action_assignment.executable;
    if(enabled&&saving.schedule_enabled)await api(base+'/actions/'+encodeURIComponent(item.id)+'/schedule',{minutes:saving.schedule_minutes||60,enabled:true});
    else if(config.schedule?.enabled)await api(base+'/actions/'+encodeURIComponent(item.id)+'/schedule',{minutes:saving.schedule_minutes||60,enabled:false});
    const saved=await api('/hfl-corpus/timeline/items/'+encodeURIComponent(item.id),{version:item.version,agent_enabled:enabled},'PATCH');
    sourceId=item.id;config=result;if(version===revision){draft={...draft,...result.card};dirty=false;}paintSummary();window.dispatchEvent(new Event('hfl:agent-updated'));return saved.item;
   },
   dispose(){alive=false;for(const popup of [...dialogs])popup.close();closePicker();section.ontoggle=null;dialog?.removeEventListener('close',closed);}
  };
 };
})();
