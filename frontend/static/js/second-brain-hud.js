(() => {
  'use strict';
  const $ = id => document.getElementById(id), root = $('hud-surface'), grid = $('hud-grid');
  const config = JSON.parse($('hud-config').textContent), catalog = new Map(config.catalog.map(x => [x.operation_id, x]));
  let state, settingsId, saving = false, pendingSaves = 0, saveGeneration = 0, loading = false, moving = false, serial = Promise.resolve(), motionFrame;
  let lastData = '', lastLayout = '', lastActive = '', builderKey = crypto.randomUUID();
  let spaceDraft;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function el(tag, text, cls) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; }
  function button(text, fn, label) { const b=el('button',text); b.type='button'; if(label)b.setAttribute('aria-label',label); b.addEventListener('click',fn);return b; }
  function notice(message) { $('hud-notice').textContent=message; $('hud-notice').hidden=!message; }
  async function api(url, body, method='POST') {
    const response=await fetch(url,{method:body===undefined?'GET':method,cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:body===undefined?undefined:JSON.stringify(body)});
    let data; try { data=await response.json(); } catch { throw new Error('The server did not return data. Reload or sign in again.'); }
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:data.error||'Could not save. Reload and retry.');
    return data;
  }
  function safeLink(url) { try {const u=new URL(url);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;} }
  function link(label,url) {const a=el('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
  function visible(w) {return !w.hidden&&(!w.workspace_ids.length||w.workspace_ids.some(id=>state.spaces.active.includes(id)));}
  function dataKey(){const display=items=>items.map(({title,summary,details,source_at,status,links})=>({title,summary,details,source_at,status,links}));return JSON.stringify([Object.entries(state.items).map(([id,items])=>[id,display(items)]),display(state.context),state.kibana_url]);}
  function sized(card,size) {const [c,r]=size.split('x').map(Number);card.style.setProperty('--cols',c);card.style.setProperty('--rows',r);}
  function renderSpaces() {
    const spaces=state.spaces, names=spaces.active.map(id=>spaces.views.find(v=>v.id===id)?.name).filter(Boolean);
    $('hud-space-caption').textContent=names.join(', ')||(spaces.preferences.dynamic?'No scheduled Space':'All');
    if(!$('hud-spaces').open){
      $('hud-dynamic').checked=spaces.preferences.dynamic;
      renderChecks($('hud-space-list'),spaces.preferences.manual);
    }
  }
  function renderChecks(target,selected) {
    target.replaceChildren();
    if(!state.spaces.views.length)target.append(el('p','Create a Space in Activity Corpus to link widgets.'));
    for(const space of state.spaces.views){const label=el('label'),check=document.createElement('input');check.type='checkbox';check.value=space.id;check.checked=selected.includes(space.id);const dot=el('span','','hud-space-dot');dot.style.backgroundColor=space.color;label.append(check,dot,document.createTextNode(space.name));target.append(label);}
  }
  function selectedChecks(target) {return [...target.querySelectorAll('input:checked')].map(x=>x.value);}
  function rowHeight(){const mobile=matchMedia('(max-width:767px)').matches,top=grid.getBoundingClientRect().top+(document.fullscreenElement?root.scrollTop:scrollY);root.style.setProperty('--hud-row',(mobile?160:Math.max(145,(innerHeight-top-64)/4))+'px');}
  function persist() {
    const widgets=structuredClone(state.layout.widgets),generation=saveGeneration; pendingSaves++;saving=true;$('hud-save-state').textContent='Saving…';
    serial=serial.then(async()=>{
      if(generation!==saveGeneration)return;
      try {const saved=await api('/second-brain/hud/layout',{revision:state.layout.revision,widgets},'PUT');state.layout.revision=saved.revision;$('hud-save-state').textContent='Layout saved';}
      catch(e){saveGeneration++;notice(e.message);const fresh=await api('/second-brain/hud/data');state.layout=fresh.layout;render();throw e;}
    }).catch(()=>{}).finally(()=>{pendingSaves--;saving=pendingSaves>0;});
    return serial;
  }
  function changed(){render();return persist();}
  function reorder(id,direction) {const list=state.layout.widgets,i=list.findIndex(w=>w.id===id),j=i+direction;if(j<0||j>=list.length)return;[list[i],list[j]]=[list[j],list[i]];changed();grid.querySelector(`[data-id="${id}"] .hud-drag`)?.focus();}
  let settingsAnchor;
  function positionSettings() {
    const menu=$('hud-settings');if(!menu.matches(':popover-open')||!settingsAnchor?.isConnected)return;
    const box=settingsAnchor.getBoundingClientRect(),width=menu.offsetWidth,height=menu.offsetHeight;
    menu.style.left=Math.max(8,Math.min(innerWidth-width-8,box.right-width))+'px';
    menu.style.top=Math.max(8,Math.min(innerHeight-height-8,box.bottom+6))+'px';
  }
  function spaceCaption() {
    const target=$('hud-widget-space-caption'),ids=selectedChecks($('hud-widget-spaces'));target.replaceChildren();
    for(const id of ids){const space=state.spaces.views.find(v=>v.id===id);if(!space)continue;const pill=el('span',null,'hud-space-pill'),dot=el('span','','hud-space-dot');dot.style.backgroundColor=space.color;pill.append(dot,document.createTextNode(space.name));target.append(pill);}
    if(!ids.length)target.textContent='All Spaces';
  }
  function closeSettings() { $('hud-settings').hidePopover(); }
  function setOutput(pre,text) {
    if(!pre.classList.contains('hud-calendar-output')){pre.textContent=text;return;}
    // Keep legacy dividers, but clip each to the available width without wrapping.
    pre.replaceChildren();
    text.split(/(^[\t ]*=+[\t ]*\r?$)/gm).forEach(part=>{
      pre.append(/^[\t ]*=+[\t ]*\r?$/.test(part)?el('span',part,'hud-calendar-divider'):document.createTextNode(part));
    });
  }
  function output(w,text) {
    const pre=el('pre',null,'hud-output');
    if(w.operation==='hud.hud_calendar.show_calendar_information')pre.classList.add('hud-calendar-output');
    setOutput(pre,text);return pre;
  }
  function settings(w,anchor) {
    const menu=$('hud-settings');if(menu.matches(':popover-open')){closeSettings();if(settingsId===w.id)return;}
    settingsId=w.id;settingsAnchor=anchor;const form=$('hud-widget-form');
    form.elements.size.value=w.size;form.elements.animation.value=w.animation;form.elements.accent.value=w.accent||'';form.elements.dashboard_url.value=w.dashboard_url;
    $('hud-dashboard-field').hidden=w.operation!=='monitoring';renderChecks($('hud-widget-spaces'),w.workspace_ids);spaceCaption();$('hud-widget-space-picker').open=false;
    menu.showPopover();anchor.setAttribute('aria-expanded','true');positionSettings();form.querySelector('input:checked')?.focus();
  }
  function renderBody(card,w) {
    const body=card.querySelector('.hud-widget-body'),links=card.querySelector('.hud-links'),footer=card.querySelector('.hud-widget-footer');
    body.replaceChildren();links.replaceChildren();footer.replaceChildren();
    if(w.operation==='monitoring') {
      const url=safeLink(w.dashboard_url||state.kibana_url);
      if(url)links.append(link('OPEN KIBANA',url));
      if(w.dashboard_url&&url){const frame=el('iframe');frame.src=url;frame.title='Kibana dashboard';frame.loading='lazy';frame.referrerPolicy='no-referrer';frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-forms allow-popups');body.append(frame);}
      else body.append(el('p',url?'Choose a dashboard share URL in widget settings to embed a visualization. Kibana opens with your existing session.':'Set KIBANA_HOST on the frontend host, then choose a dashboard share URL in widget settings.','hud-placeholder'));
      footer.append(el('span','Interactive dashboard · separate Kibana session'));return;
    }
    const items=w.operation==='context'?state.context:(state.items[w.operation]||[]);
    if(!items.length){const p=el('p',null,'hud-placeholder');p.append(el('strong','Waiting for context'),document.createTextNode('No captured items yet. Feed & settings shows collection status and category controls.'));body.append(p);}
    for(const item of items){
      if(w.operation==='context'||items.length>1){const section=el('details',null,'hud-context-card');section.append(el('summary',item.title),el('p',item.summary));if(item.details)section.append(output(w,item.details));body.append(section);}
      else if(item.status==='awaiting_source'){const p=el('p',null,'hud-placeholder');p.append(el('strong','Waiting for the first capture'),document.createTextNode('This source has not published a result yet. Its existing workflow will supply this widget on the next successful run.'));body.append(p);}
      else {const pre=output(w,item.details||item.summary||'No output.');pre.dataset.fullText=pre.textContent;body.append(pre);}
      for(const [name,raw] of Object.entries(item.links||{})){const url=safeLink(raw);if(url)links.append(link(name.toUpperCase(),url));}
    }
    const item=items[0],health=el('span','','hud-health');health.dataset.state=item?.status||'awaiting_source';footer.append(health,el('span',item?.status?.replaceAll('_',' ')||'No captures'));
    if(item?.source_at){const t=el('time',new Date(item.source_at).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}));t.dateTime=item.source_at;t.title=item.source_at;footer.append(t);}
    if(w.animation!=='static'){const pause=button('Pause',()=>{card.classList.toggle('hud-motion-paused');pause.textContent=card.classList.contains('hud-motion-paused')?'Resume':'Pause';},'Pause or resume widget motion');footer.append(pause);}
  }
  function resize(handle,card,w) {
    handle.addEventListener('pointerdown',event=>{
      event.preventDefault();moving=true;handle.setPointerCapture(event.pointerId);
      const startX=event.clientX,startY=event.clientY,[startC,startR]=w.size.split('x').map(Number),cell=(grid.clientWidth-60)/6,row=parseFloat(getComputedStyle(card).height)/startR;
      let next=w.size;
      function move(e){const c=startC+(e.clientX-startX)/cell,r=startR+(e.clientY-startY)/row;next=Object.keys(config.sizes).sort((a,b)=>{const [ac,ar]=a.split('x').map(Number),[bc,br]=b.split('x').map(Number);return (ac-c)**2+(ar-r)**2-((bc-c)**2+(br-r)**2);})[0];sized(card,next);handle.title=next;}
      function finish(e){handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',finish);handle.removeEventListener('pointercancel',cancel);moving=false;w.size=next;changed();}
      function cancel(){handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',finish);handle.removeEventListener('pointercancel',cancel);moving=false;sized(card,w.size);}
      handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',cancel);
    });
  }
  function render() {
    const scrolls=new Map([...grid.children].map(c=>[c.dataset.id,c.querySelector('.hud-widget-body')?.scrollTop||0]));
    grid.replaceChildren();const widgets=state.layout.widgets.filter(visible);
    for(const w of widgets){
      const card=el('article',null,'hud-widget');card.dataset.id=w.id;card.dataset.animation=w.animation;sized(card,w.size);
      const header=el('header',null,'hud-widget-header'),drag=button('⠿',()=>{},'Drag widget');drag.className='hud-drag';drag.title='Drag to move · arrow keys to reorder';drag.setAttribute('aria-label','Move '+(catalog.get(w.operation)?.label||'widget')+'; use arrow keys to reorder');drag.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowUp','ArrowRight','ArrowDown'].includes(event.key)){event.preventDefault();reorder(w.id,['ArrowLeft','ArrowUp'].includes(event.key)?-1:1);}});
      drag.innerHTML='<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 2v16M2 10h16M7 5l3-3 3 3M7 15l3 3 3-3M5 7l-3 3 3 3M15 7l3 3-3 3"/></svg>';
      if(w.accent){header.style.backgroundColor=`color-mix(in srgb, ${w.accent} 24%, #0f172a)`;header.style.borderBottomColor=w.accent;header.style.boxShadow=`inset 3px 0 ${w.accent}`;}
      const menuButton=button('',event=>settings(w,event.currentTarget),'Settings for '+(catalog.get(w.operation)?.label||'widget'));menuButton.className='hud-widget-menu-button';menuButton.setAttribute('aria-haspopup','dialog');menuButton.setAttribute('aria-expanded','false');menuButton.setAttribute('aria-controls','hud-settings');
      menuButton.innerHTML='<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M4 5h12M4 10h12M4 15h12"/></svg>';
      header.append(el('h2',catalog.get(w.operation)?.label||w.operation),drag,menuButton);
      card.append(header,el('nav',null,'hud-links'),el('div',null,'hud-widget-body'),el('footer',null,'hud-widget-footer'));
      const handle=button('',()=>{},'Resize widget; use settings for keyboard resizing');handle.className='hud-resize';resize(handle,card,w);card.append(handle);renderBody(card,w);grid.append(card);card.querySelector('.hud-widget-body').scrollTop=scrolls.get(w.id)||0;
    }
    $('hud-empty').hidden=!!widgets.length;grid.setAttribute('aria-busy','false');lastLayout=JSON.stringify(state.layout.widgets);lastData=dataKey();lastActive=JSON.stringify(state.spaces.active);
    motionStart=performance.now();
  }
  let motionStart=performance.now(),lastTick=0;
  reduced.addEventListener('change',()=>{if(reduced.matches)grid.querySelectorAll('pre[data-full-text]').forEach(pre=>{setOutput(pre,pre.dataset.fullText);});else motionStart=performance.now();});
  function motion(now){
    if(now-lastTick>90){
      // Recheck here as well as on change: some embedded/browser contexts do
      // not deliver MediaQueryList change events during a live preference swap.
      if(matchMedia('(prefers-reduced-motion: reduce)').matches){
        grid.querySelectorAll('pre[data-full-text]').forEach(pre=>{if(pre.textContent!==pre.dataset.fullText)setOutput(pre,pre.dataset.fullText);});
      }else{
      grid.querySelectorAll('.hud-widget:not(.hud-motion-paused)').forEach(card=>{
        if(card.matches(':hover,:focus-within'))return;
        const body=card.querySelector('.hud-widget-body');
        if(card.dataset.animation==='marquee'&&body.scrollHeight>body.clientHeight){body.scrollTop+=.65;if(body.scrollTop>=body.scrollHeight-body.clientHeight)body.scrollTop=0;}
        if(card.dataset.animation==='typing'){const pre=body.querySelector('pre[data-full-text]');if(pre){const count=Math.floor((now-motionStart)/9),text=pre.dataset.fullText.slice(0,count);if(pre.textContent!==text)setOutput(pre,text);}}
      });
      }lastTick=now;
    }motionFrame=requestAnimationFrame(motion);
  }
  function catalogRows(){
    const target=$('hud-catalog-items'),q=$('hud-catalog-search').value.toLowerCase();target.replaceChildren();
    for(const item of config.catalog.filter(x=>x.label.toLowerCase().includes(q))){const row=el('div',null,'hud-catalog-row'),text=el('div');text.append(el('strong',item.label),el('small',item.schedules.length?'Scheduled collector · '+item.schedules.length+' schedule(s)':item.source_task?'On-demand source':'Built-in view'));row.append(text,button('Add',()=>add(item.operation_id)));for(const w of state.layout.widgets.filter(w=>w.operation===item.operation_id&&w.hidden))row.append(button('Restore',()=>{w.hidden=false;changed();$('hud-catalog').close();}));target.append(row);}
    if(!target.children.length)target.append(el('p','No widgets match this search.'));
  }
  function add(operation){state.layout.widgets.push({id:crypto.randomUUID(),operation,size:'2x2',hidden:false,animation:'static',workspace_ids:[...state.spaces.active],dashboard_url:''});changed();$('hud-catalog').close();}
  async function refresh(){
    if(loading||moving||saving)return;loading=true;
    try {const fresh=await api('/second-brain/hud/data');if(moving||saving)return;
      if(state&&$('hud-settings').matches(':popover-open'))return;
      state=fresh;renderSpaces();
      if(lastLayout!==JSON.stringify(state.layout.widgets)||lastData!==dataKey()||lastActive!==JSON.stringify(state.spaces.active))render();
      notice(state.source_error);
    }catch(e){notice(e.message);}finally{loading=false;}
  }
  $('hud-refresh').onclick=refresh;
  $('hud-add').onclick=()=>{if(!state)return;catalogRows();$('hud-catalog').showModal();};$('hud-catalog-search').oninput=catalogRows;
  $('hud-fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await root.requestFullscreen();}catch{notice('Full screen is unavailable in this browser.');}};
  document.addEventListener('fullscreenchange',()=>{$('hud-fullscreen').textContent=document.fullscreenElement?'Exit full screen':'Full screen';rowHeight();});
  $('hud-widget-form').onsubmit=async event=>{event.preventDefault();const w=state.layout.widgets.find(x=>x.id===settingsId),form=event.currentTarget;Object.assign(w,{size:form.elements.size.value,animation:form.elements.animation.value,accent:form.elements.accent.value,workspace_ids:selectedChecks($('hud-widget-spaces')),dashboard_url:form.elements.dashboard_url.value});closeSettings();await changed();grid.querySelector(`[data-id="${settingsId}"] .hud-widget-menu-button`)?.focus();};
  $('hud-hide').onclick=()=>{state.layout.widgets.find(w=>w.id===settingsId).hidden=true;closeSettings();changed();};
  $('hud-remove').onclick=()=>{state.layout.widgets=state.layout.widgets.filter(w=>w.id!==settingsId);closeSettings();changed();};
  $('hud-widget-spaces').onchange=spaceCaption;
  $('hud-widget-spaces-clear').onclick=()=>{renderChecks($('hud-widget-spaces'),[]);spaceCaption();};
  $('hud-widget-space-picker').addEventListener('toggle',positionSettings);
  $('hud-widget-space-picker').addEventListener('keydown',event=>{if(event.key==='Escape'&&event.currentTarget.open){event.preventDefault();event.stopPropagation();event.currentTarget.open=false;event.currentTarget.querySelector('summary').focus();}});
  $('hud-settings').addEventListener('toggle',event=>{if(event.newState==='closed')settingsAnchor?.setAttribute('aria-expanded','false');});
  window.addEventListener('resize',positionSettings);document.addEventListener('scroll',positionSettings,true);
  $('hud-spaces').addEventListener('toggle',()=>{if($('hud-spaces').open&&state){spaceDraft=structuredClone(state.spaces.preferences);renderChecks($('hud-space-list'),spaceDraft.manual);$('hud-dynamic').checked=spaceDraft.dynamic;}});
  $('hud-spaces-apply').onclick=async()=>{if(!state)return;try{await api('/hfl-corpus/view-preferences',{...(spaceDraft||state.spaces.preferences),manual:selectedChecks($('hud-space-list')),dynamic:$('hud-dynamic').checked},'PUT');$('hud-spaces').open=false;try{localStorage.setItem('corpus:workspace-change',Date.now());}catch{}await refresh();}catch(e){notice(e.message);}};
  $('hud-hotkeys').onclick=()=>$('hud-hotkeys-dialog').showModal();$('hud-add-hotkeys').onclick=()=>{if(!state)return;add('hud.hud_utils.show_ahk_bindings');$('hud-hotkeys-dialog').close();};
  $('hud-build').onclick=()=>$('hud-builder').showModal();
  $('hud-build-form').onsubmit=async event=>{
    event.preventDefault();if(!state)return;const form=event.currentTarget,submit=form.querySelector('button[type=submit]');submit.disabled=true;$('hud-build-status').textContent='Preparing action…';
    try{const context=await api('/second-brain/hud/build-context');const prompt=context.instructions+'\n\nSkill versions:\n'+context.skills.map(s=>s.name+': '+s.sha256).join('\n')+'\n\nWidget request:\n'+form.elements.prompt.value;
      const result=await api('/hfl-corpus/timeline/items',{request_id:builderKey,title:form.elements.title.value,prompt,expected_outcome:'A tested web HUD widget and a published draft pull request.',workspace_ids:state.spaces.active});
      location.href='/hfl-corpus/actions?integration_agent='+encodeURIComponent(result.item.id);
    }catch(e){$('hud-build-status').textContent=e.message;submit.disabled=false;}
  };
  new Sortable(grid,{handle:'.hud-drag',forceFallback:true,animation:reduced.matches?0:150,ghostClass:'hud-sort-ghost',onStart(){moving=true;},onEnd(event){moving=false;const ids=[...grid.children].map(c=>c.dataset.id),visibleSet=new Set(ids),ordered=ids.map(id=>state.layout.widgets.find(w=>w.id===id));state.layout.widgets=state.layout.widgets.map(w=>visibleSet.has(w.id)?ordered.shift():w);changed();}});
  document.addEventListener('click',event=>{if(!$('hud-spaces').contains(event.target))$('hud-spaces').open=false;});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});window.addEventListener('storage',event=>{if(event.key==='corpus:workspace-change')refresh();});
  new ResizeObserver(rowHeight).observe(root.querySelector('.hud-toolbar'));window.addEventListener('resize',rowHeight);rowHeight();
  const timer=setInterval(()=>{if(!document.hidden)refresh();},30000);motionFrame=requestAnimationFrame(motion);refresh();
  window.addEventListener('pagehide',()=>{clearInterval(timer);cancelAnimationFrame(motionFrame);});
})();
