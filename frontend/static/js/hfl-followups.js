/* The board shares cards and commands with the day/period Actions panel. */
(() => {
  const dialog = document.getElementById('followups-board');
  if (!dialog || !window.hflActions) return;
  const actions = window.hflActions;
  const $ = selector => dialog.querySelector(selector);
  const lanes = $('[data-board-lanes]'), all = $('[data-board-all]');
  Object.defineProperty(all,'checked',{get(){return this.getAttribute('aria-checked')==='true';},set(value){this.setAttribute('aria-checked',String(!!value));}});
  const status = $('[data-board-status]'), error = $('[data-board-error]');
  const states = ['open','active','in_progress','incomplete','done','dismissed'];
  const label = value => value === 'in_progress' ? 'In Progress' : value[0].toUpperCase()+value.slice(1);
  const listeners = new AbortController();
  let sequence = 0, pending = false, moving = false, dragging = null, disposed = false;
  let items = new Map(), rendered = '', timer;
  const node = (tag, text, className) => {const el=document.createElement(tag);if(text!=null)el.textContent=text;if(className)el.className=className;return el;};
  function context() {
    const caption = document.querySelector('[data-active-view-name]')?.textContent || 'All activity';
    const dynamic = document.querySelector('[data-dynamic-badge]')?.textContent || 'Dynamic OFF';
    const params=new URLSearchParams(location.search);
    const extra=['source','q','date_from','date_to'].filter(key=>params.get(key)).map(key=>({source:'Sources',q:'Search',date_from:'From',date_to:'To'}[key])+': '+params.get(key));
    $('[data-board-context]').textContent = (all.checked ? 'All activity · Current views: ' : 'Following views: ') + caption + ' · ' + dynamic + (!all.checked&&extra.length?' · '+extra.join(' · '):'');
  }
  async function request(path, options={}) {
    const response=await fetch('/hfl-corpus/timeline/items'+path,{cache:'no-store',...options,headers:{'Content-Type':'application/json'}});
    const data=await response.json();
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Could not load follow-ups. Retry.');
    return data;
  }
  function render(rows) {
    const signature=JSON.stringify(rows);
    if(signature===rendered)return;
    const expanded=new Set([...lanes.querySelectorAll('details[open]')].map(el=>el.closest('[data-followup-id]').dataset.followupId+':'+el.querySelector('summary').textContent));
    const scroll=new Map([...lanes.children].map(el=>[el.dataset.status,el.scrollTop]));
    const focused=document.activeElement;
    const focusId=focused?.closest('[data-followup-id]')?.dataset.followupId, focusText=focused?.textContent;
    items=new Map(rows.map(item=>[item.id,item]));
    lanes.replaceChildren();
    for(const state of states){
      const section=node('section',null,'followups-lane');section.dataset.status=state;section.setAttribute('aria-label',label(state));
      const matching=rows.filter(item=>item.status===state);
      section.append(node('h3',label(state)+' · '+matching.length));
      section.addEventListener('dragover',event=>{if(dragging&&!moving){event.preventDefault();event.dataTransfer.dropEffect='move';}});
      section.addEventListener('drop',event=>{event.preventDefault();const id=dragging;dragging=null;if(id)move(id,state);});
      for(const item of matching){
        const card=actions.card(item);card.draggable=true;
        card.addEventListener('dragstart',event=>{if(event.target.closest('button,a,input,summary')){event.preventDefault();return;}dragging=item.id;dialog.dataset.busy='true';event.dataTransfer.setData('text/plain',item.id);event.dataTransfer.effectAllowed='move';});
        card.addEventListener('dragend',()=>{dragging=null;if(!moving)delete dialog.dataset.busy;});
        card.querySelectorAll('details').forEach(el=>el.open=expanded.has(item.id+':'+el.querySelector('summary').textContent));
        section.append(card);
      }
      if(!matching.length)section.append(node('p','No actions','agenda-description'));
      lanes.append(section);section.scrollTop=scroll.get(state)||0;
    }
    if(focusId)[...lanes.querySelectorAll('[data-followup-id]')].find(el=>el.dataset.followupId===focusId)?.querySelectorAll('button,summary,a').forEach(el=>{if(el.textContent===focusText)el.focus({preventScroll:true});});
    rendered=signature;
  }
  async function refresh(force=false) {
    if(!dialog.open || disposed || moving || dragging || (pending&&!force))return;
    const ticket=++sequence;pending=true;context();status.textContent='Refreshing follow-ups…';lanes.setAttribute('aria-busy','true');
    try{
      const params=all.checked?new URLSearchParams():new URLSearchParams(location.search);
      params.set('include_closed','true');params.set('recent_dismissed','true');
      const rows=[];let total=0;
      do{
        params.set('offset',String(rows.length));
        const data=await request('?'+params);
        if(ticket!==sequence||disposed)return;
        rows.push(...data.items);total=data.total;
        if(!data.items.length)break;
      }while(rows.length<total);
      if(dragging||moving)return;
      render(rows);error.hidden=true;status.textContent=rows.length+' action'+(rows.length===1?'':'s')+' · Updates every 5 seconds';
    }catch(e){if(ticket===sequence){error.textContent=e.message;error.hidden=false;status.textContent='Could not refresh. Displayed actions may be out of date. Use Refresh to retry.';}}
    finally{if(ticket===sequence){pending=false;lanes.removeAttribute('aria-busy');}}
  }
  async function move(id,state){
    const item=items.get(id);if(!item||item.status===state||moving)return;
    moving=true;dialog.dataset.busy='true';++sequence;pending=false;lanes.inert=true;status.textContent='Saving status…';
    let failure='';
    try{await request('/'+id,{method:'PATCH',body:JSON.stringify({version:item.version,status:state})});}
    catch(e){failure=e.message;}
    finally{moving=false;delete dialog.dataset.busy;lanes.inert=false;}
    await refresh(true);actions.load();
    if(failure){error.textContent=failure+' The board has been reloaded; the move was not saved.';error.hidden=false;}
  }
  function open(){dialog.showModal();context();refresh(true);clearInterval(timer);timer=setInterval(()=>{if(!document.hidden&&!document.querySelector('dialog[open]:not(#followups-board)')){refresh();actions.load();}},5000);}
  document.querySelector('[data-followups-open]').onclick=()=>{document.querySelector('.corpus-tools').open=false;open();};
  $('[data-board-close]').onclick=()=>dialog.close();
  $('[data-board-create]').onclick=()=>actions.openEditor();
  $('[data-board-refresh]').onclick=()=>refresh(true);
  all.onclick=()=>{all.checked=!all.checked;refresh(true);};
  const toolsMenu=document.querySelector('.corpus-tools');
  toolsMenu.addEventListener('toggle',()=>{if(toolsMenu.open){const profile=document.querySelector('summary[aria-label="Profile menu"]')?.parentElement;if(profile)profile.open=false;}});
  document.addEventListener('click',event=>{if(!toolsMenu.contains(event.target))toolsMenu.open=false;},{signal:listeners.signal});
  toolsMenu.addEventListener('keydown',event=>{if(event.key==='Escape'){toolsMenu.open=false;toolsMenu.querySelector('summary').focus();}});
  dialog.addEventListener('close',()=>{++sequence;pending=false;clearInterval(timer);});
  window.addEventListener('hfl:actions-updated',()=>refresh(true),{signal:listeners.signal});
  window.addEventListener('hfl:agent-updated',()=>refresh(),{signal:listeners.signal});
  window.addEventListener('hfl:action-error',async event=>{if(dialog.open){await refresh(true);error.textContent=event.detail;error.hidden=false;}},{signal:listeners.signal});
  window.addEventListener('hfl:view-replacing',()=>{
    try{if(dialog.open)sessionStorage.setItem('hfl:followups-restore',JSON.stringify({all:all.checked}));}catch(_){}
    disposed=true;++sequence;clearInterval(timer);listeners.abort();
  },{signal:listeners.signal});
  try{const restore=JSON.parse(sessionStorage.getItem('hfl:followups-restore')||'null');sessionStorage.removeItem('hfl:followups-restore');if(restore){all.checked=restore.all;requestAnimationFrame(open);}}catch(_){}
})();
