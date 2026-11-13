/* Owner-only persistent Hermes conversations. No gateway credentials in the browser. */
(() => {
  const $=id=>document.getElementById(id), launch=$('butler-launch'), panel=$('butler-panel');
  if(!launch)return;
  const messages=$('butler-messages'), error=$('butler-error'), input=$('butler-message'), send=$('butler-send'), selector=$('butler-conversation');
  const csrf=JSON.parse($('butler-csrf').textContent), terminal=new Set(['completed','failed','cancelled','interrupted']);
  const partial=new Map();
  let conversation='', current=[], capabilities={}, pending=null, timer, stream=null, streamTurn='', generation=0, previewTurn=null, connected=false, polling=false;
  async function api(path,body){const r=await fetch('/agents/api/assistant'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body===undefined?{}:{body:JSON.stringify(body)})});const d=await r.json();if(!r.ok){const error=Error(typeof d.detail==='string'?d.detail:'Assistant unavailable.');error.status=r.status;throw error;}return d;}
  function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
  function button(text,fn){const b=element('button',text);b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){error.textContent=e.message;}finally{b.disabled=false;}};return b;}
  function closeStream(){stream?.close();stream=null;streamTurn='';}
  function context(){const query=new URLSearchParams(location.search), id=query.get('integration_agent');return {version:1,path:location.pathname,...(/^item-[a-f0-9]{32}$/.test(id||'')?{action_id:id}:{})};}
  function controls(){const active=current.find(t=>!terminal.has(t.state));send.disabled=!connected||Boolean(active&&!pending);send.textContent=pending?'Retry request':'Send';$('butler-stop').hidden=!(active?.run_id&&capabilities.run_stop);$('butler-stop').disabled=active?.state==='stopping';$('butler-steer').hidden=!(active?.run_id&&capabilities.run_steer&&active.state==='running');}
  function render(rows,proposals){messages.replaceChildren();for(const row of rows){const article=element('article');article.append(element('strong','You'),element('div',row.message),element('small',row.state));const answer=element('div',row.answer||partial.get(row.id)||'Waiting for Hermes…');answer.dataset.turn=row.id;article.append(answer);const ctx=row.context;article.append(element('small','Context captured '+new Date(ctx.resolved_at).toLocaleString()));for(const record of ctx.records){const a=element('a',record.title+' · revision '+record.version);a.href=record.url;article.append(a);}if(row.state==='completed')article.append(button('Preview action',()=>{previewTurn=row;$('butler-action-title').value=row.message.slice(0,160);$('butler-action-outcome').value=row.answer.slice(0,10000);$('butler-preview-error').textContent='';$('butler-preview').showModal();}));if(row.state==='submitting')article.append(button('Retry same request',async()=>{pending={request_id:row.id.slice(5),message:row.message,context:row.request_context};if(!pending.context)throw Error('Reopen this conversation after restoring the connection to reconcile admission.');await api('/conversations/'+conversation+'/messages',pending);pending=null;await refresh();}));messages.append(article);}
    for(const p of proposals){const card=element('article',undefined,'butler-approval');card.append(element('strong','Create action · '+p.state),element('div',p.payload.title),element('div',p.payload.expected_outcome),element('small','Task prompt: '+p.payload.prompt),element('small','Execution disabled'+(p.state==='pending'?' · approval expires '+new Date(p.expires*1000).toLocaleTimeString():'')));if(p.state==='pending'){for(const decision of ['approve','deny'])card.append(button(decision==='approve'?'Approve and save':'Deny',async()=>{await api('/proposals/'+p.id,{decision,version:p.version});await refresh();}));}if(['approved','unknown'].includes(p.state))card.append(button('Reconcile saved action',async()=>{await api('/proposals/'+p.id,{decision:'reconcile',version:p.version});await refresh();}));if(p.action_id){const a=element('a',p.state==='verified'?'Open verified action':'Review action');a.href=p.url||'/hfl-corpus/actions?integration_agent='+encodeURIComponent(p.action_id);card.append(a);}messages.append(card);}
    if(!rows.length)messages.append(element('p','Ask about the current page or prepare an action. Changes require an exact preview and your approval.'));
  }
  function attach(row){if(!row?.run_id||!capabilities.run_events_sse){closeStream();return;}if(streamTurn===row.id)return;closeStream();const captured=generation;streamTurn=row.id;stream=new EventSource('/agents/api/assistant/conversations/'+conversation+'/turns/'+row.id+'/events');let text='';stream.addEventListener('delta',e=>{if(captured!==generation)return;try{text=(text+JSON.parse(e.data).text).slice(0,50000);partial.set(row.id,text);const answer=messages.querySelector('[data-turn="'+row.id+'"]');if(answer)answer.textContent=text;}catch{}});stream.addEventListener('refresh',()=>{closeStream();refresh();});stream.onerror=()=>{closeStream();};}
  async function refresh(){if(!conversation||polling||panel.dataset.tab!=='conversation')return;polling=true;const captured=generation, id=conversation;try{const [data,proposals]=await Promise.all([api('/conversations/'+id),api('/conversations/'+id+'/proposals')]);if(captured!==generation)return;current=data.messages;capabilities=data.capabilities;if(data.detail)error.textContent=data.detail;render(current,proposals.items);controls();if(!panel.hidden&&panel.dataset.tab==='conversation')attach(current.find(t=>t.state==='running'));}catch(e){if(captured===generation)error.textContent=e.message;}finally{polling=false;clearTimeout(timer);if(!panel.hidden&&panel.dataset.tab==='conversation')timer=setTimeout(refresh,4000);}}
  async function list(){const data=await api('/conversations');selector.replaceChildren();for(const c of data.items){const option=element('option',c.name+' · '+new Date(c.created).toLocaleString());option.value=c.id;option.dataset.name=c.name;option.dataset.agent=c.agent_id;selector.append(option);}if(!data.items.some(c=>c.id===conversation))conversation=data.items[0]?.id||'';selector.value=conversation;showIdentity();}
  function showIdentity(){const option=selector.selectedOptions[0];if(option){$('butler-name').textContent='HARQIS Butler';$('butler-configure').href='/agents?agent='+encodeURIComponent(option.dataset.agent);}}
  async function newConversation(){const value=await api('/conversations',{request_id:crypto.randomUUID()});generation++;closeStream();pending=null;conversation=value.id;current=[];await list();await refresh();}
  async function openConversation(){error.textContent='';$('butler-context').textContent='Page context: '+location.pathname;try{const status=await api('');connected=status.connected&&status.active;$('butler-name').textContent='HARQIS Butler';$('butler-connection').textContent=(status.connected?'Connected to '+status.host:'Not connected')+' · separate frontend conversation';$('butler-configure').href='/agents?agent='+encodeURIComponent(status.agent_id);$('butler-new').disabled=!connected;error.textContent=status.detail||'';await list();if(conversation)await refresh();else controls();if(panel.dataset.tab==='conversation')input.focus();}catch(e){error.textContent=e.message;}}
  launch.onclick=()=>{panel.hidden=false;launch.setAttribute('aria-expanded','true');panel.dispatchEvent(new Event('butler-opened'));if(panel.dataset.tab==='conversation')openConversation();};
  panel.addEventListener('butler-tab-change',()=>{clearTimeout(timer);closeStream();if(panel.dataset.tab==='conversation'&&!panel.hidden)openConversation();});
  function closeButler(restoreFocus=true){panel.hidden=true;launch.setAttribute('aria-expanded','false');clearTimeout(timer);closeStream();panel.dispatchEvent(new Event('butler-closed'));if(restoreFocus)launch.focus();}
  document.addEventListener('keydown',async event=>{
    if(event.defaultPrevented||event.repeat||event.isComposing||event.ctrlKey||event.altKey||event.metaKey||event.shiftKey||event.key.toLowerCase()!=='b')return;
    if(event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],.xterm'))return;
    const dialogs=[...document.querySelectorAll('dialog[open]')];
    if(dialogs.some(dialog=>!['activity-hotkey-help','hud-hotkeys-dialog'].includes(dialog.id)))return;
    event.preventDefault();event.stopImmediatePropagation();dialogs.forEach(dialog=>dialog.close());
    if(document.fullscreenElement){try{await document.exitFullscreen();}catch{return;}}
    document.getElementById('fleet-exit-fullscreen')?.click();
    requestAnimationFrame(()=>{if(panel.hidden)launch.click();panel.querySelector('[role=tab][aria-selected=true]')?.focus();});
  },true);
  $('butler-close').onclick=()=>closeButler();
  document.addEventListener('pointerdown',event=>{
    if(panel.hidden||event.button!==0||$('butler-preview').open)return;
    const path=event.composedPath();
    if(!path.includes(panel)&&!path.includes(launch))closeButler(false);
  },true);
  panel.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('butler-preview').open){e.stopPropagation();if(panel.dataset.tab==='settings'){panel.dispatchEvent(new CustomEvent('butler-view-request',{detail:'briefings'}));}else $('butler-close').click();}});
  selector.onchange=()=>{generation++;closeStream();pending=null;conversation=selector.value;showIdentity();current=[];messages.replaceChildren();refresh();};
  $('butler-new').onclick=async()=>{try{await newConversation();}catch(e){error.textContent=e.message;}};
  $('butler-form').onsubmit=async e=>{e.preventDefault();send.disabled=true;error.textContent='';try{if(!conversation)await newConversation();if(!pending)pending={message:input.value,request_id:crypto.randomUUID(),context:context()};await api('/conversations/'+conversation+'/messages',pending);input.value='';pending=null;await refresh();}catch(e){if(e.status===422)pending=null;error.textContent=e.message+(pending?' Retry keeps the same request.':'');}finally{controls();}};
  async function control(operation){const active=current.find(t=>!terminal.has(t.state));if(!active)return;error.textContent='';try{await api('/conversations/'+conversation+'/turns/'+active.id+'/'+operation,operation==='steer'?{message:input.value}:{});if(operation==='steer')input.value='';await refresh();}catch(e){error.textContent=e.message;}}
  $('butler-stop').onclick=()=>control('stop');$('butler-steer').onclick=()=>control('steer');
  $('butler-preview-close').onclick=()=>$('butler-preview').close();
  $('butler-preview-form').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{await api('/conversations/'+conversation+'/proposals',{turn_id:previewTurn.id,title:$('butler-action-title').value,expected_outcome:$('butler-action-outcome').value});$('butler-preview').close();await refresh();}catch(e){$('butler-preview-error').textContent=e.message;}finally{b.disabled=false;}};
  // Shared schedule settings live with Butler, independent of the Fleet React app.
  const briefings=$('butler-briefings'), briefingFields=$('butler-briefings-fields'), briefingSave=$('butler-briefings-save');
  let briefingValue=null, briefingRevision=0;
  function briefingDay(){ $('butler-briefings-day').hidden=$('butler-briefings-cadence').value!=='weekly'; }
  async function schedule(body){
    const response=await fetch('/agents/api/butler/schedule',{method:body===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const value=await response.json();if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'Could not save or load the briefing schedule.');return value;
  }
  async function loadBriefingSettings(){
    const revision=++briefingRevision;briefingValue=null;briefingFields.disabled=true;briefingSave.disabled=true;
    $('butler-briefings-error').textContent='';$('butler-briefings-loading').hidden=false;
    try{const value=await schedule();if(revision!==briefingRevision||briefings.hidden||panel.hidden)return;briefingValue=value;
      for(const key of ['cadence','hour','weekday','timezone'])$('butler-briefings-'+key).value=value[key]??(key==='weekday'?0:'');
      briefingDay();briefingFields.disabled=false;briefingSave.disabled=false;
    }catch(e){if(revision===briefingRevision)$('butler-briefings-error').textContent=e.message;}
    finally{if(revision===briefingRevision)$('butler-briefings-loading').hidden=true;}
  };
  panel.addEventListener('butler-tab-change',()=>{briefingRevision++;if(panel.dataset.tab==='settings'&&!panel.hidden)loadBriefingSettings();});
  panel.addEventListener('butler-opened',()=>{if(panel.dataset.tab==='settings')loadBriefingSettings();});
  panel.addEventListener('butler-closed',()=>{briefingRevision++;});
  const backToBriefings=()=>panel.dispatchEvent(new CustomEvent('butler-view-request',{detail:'briefings'}));
  $('butler-briefings-cadence').onchange=briefingDay;
  $('butler-hour-up').onclick=()=>{ $('butler-briefings-hour').stepUp(); };
  $('butler-hour-down').onclick=()=>{ $('butler-briefings-hour').stepDown(); };
  $('butler-briefings-close').onclick=backToBriefings;
  $('butler-briefings-form').onsubmit=async event=>{
    event.preventDefault();if(!briefingValue||briefingSave.disabled)return;
    const revision=briefingRevision,body={...briefingValue,cadence:$('butler-briefings-cadence').value,hour:Number($('butler-briefings-hour').value),weekday:Number($('butler-briefings-weekday').value),timezone:$('butler-briefings-timezone').value};
    briefingFields.disabled=true;briefingSave.disabled=true;$('butler-briefings-error').textContent='';
    try{await schedule(body);if(revision===briefingRevision)backToBriefings();}
    catch(e){if(revision===briefingRevision)$('butler-briefings-error').textContent=e.message;}
    finally{if(revision===briefingRevision){briefingFields.disabled=false;briefingSave.disabled=false;}}
  };
})();
