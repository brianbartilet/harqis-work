(() => {
  'use strict';
  const $ = id => document.getElementById(id), root = $('hud-surface'), grid = $('hud-grid');
  const config = JSON.parse($('hud-config').textContent), catalog = new Map(config.catalog.map(x => [x.operation_id, x]));
  let state, settingsId, saving = false, pendingSaves = 0, saveGeneration = 0, loading = false, moving = false, serial = Promise.resolve(), motionFrame;
  let refreshVersion = 0;
  let lastData = '', lastLayout = '', lastActive = '', builderKey = crypto.randomUUID();
  const returnAgent = new URLSearchParams(location.search).get('agent');
  if(returnAgent)$('hud-workspace-return').href='/agents?agent='+encodeURIComponent(returnAgent);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const typingMsPerCharacter = 15;
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
  function dataKey(){const display=items=>items.map(({title,summary,details,source_at,status,links})=>({title,summary,details,source_at,status,links}));return JSON.stringify([Object.entries(state.items).map(([id,items])=>[id,display(items)]),display(state.context),state.kibana_url,state.agents]);}
  function sized(card,size) {const [c,r]=size.split('x').map(Number);card.style.setProperty('--cols',c);card.style.setProperty('--rows',r);}
  function renderSpaces() { window.HudSpaces.update(state.spaces); }
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
  function orderText(text) {
    // Compact legacy padded rows too; stored snapshots may predate the collector layout.
    return text.split('\n').map(line=>{
      const row=line.match(/^(\s*[WUBRGCLMX]\s+\d+\s+[FN]\s+\d+\s+)(.+?)\s{2,}([�*]*\d+)\s+(\d+(?:\.\d+)?)\s*$/);
      if(!row)return line;
      const name=row[2].length>44?row[2].slice(0,41)+'...':row[2];
      return row[1]+name.padEnd(44)+' '+row[3].padStart(8)+' '+Number(row[4]).toFixed(2).padStart(6)+'  ';
    }).join('\n');
  }
  function desktopLogText(text) {
    // Legacy snapshots wrap prose at 65 columns. Preserve paragraph and entry boundaries.
    const lines=text.replace(/\r\n/g,'\n').split('\n'),out=[];
    const boundary=line=>!line.trim()||/^\s*(?:[=\-]{3,}\s*$|\[|[-*] |\d+[.)] )/.test(line);
    for(const line of lines){
      if(out.length&&!boundary(line)&&!boundary(out[out.length-1]))out[out.length-1]+=' '+line.trim();
      else out.push(line);
    }
    return out.join('\n');
  }
  function setOutput(pre,text) {
    if(!pre.classList.contains('hud-calendar-output')&&!pre.classList.contains('hud-desktop-output')){pre.textContent=text;return;}
    // Keep legacy dividers, but clip each to the available width without wrapping.
    pre.replaceChildren();
    text.split(/(^[\t ]*=+[\t ]*\r?$)/gm).forEach(part=>{
      pre.append(/^[\t ]*=+[\t ]*\r?$/.test(part)?el('span',part,pre.classList.contains('hud-desktop-output')?'hud-desktop-divider':'hud-calendar-divider'):document.createTextNode(part));
    });
  }
  function output(w,text) {
    const pre=el('pre',null,'hud-output');
    if(w.operation==='hud.hud_calendar.show_calendar_information')pre.classList.add('hud-calendar-output');
    if(w.operation==='hud.hud_tcg.show_tcg_orders'){pre.classList.add('hud-orders-output');text=orderText(text);}
    if(w.operation==='hud.hud_gpt.get_desktop_logs'){pre.classList.add('hud-desktop-output');text=desktopLogText(text);}
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
      header.append(el('h2',catalog.get(w.operation)?.label||w.operation),window.AgentAvatars.group(state.agents?.[w.operation]||[]),drag,menuButton);
      card.append(header,el('nav',null,'hud-links'),el('div',null,'hud-widget-body'),el('footer',null,'hud-widget-footer'));
      const handle=button('',()=>{},'Resize widget; use settings for keyboard resizing');handle.className='hud-resize';resize(handle,card,w);card.append(handle);renderBody(card,w);grid.append(card);card.querySelector('.hud-widget-body').scrollTop=scrolls.get(w.id)||0;
    }
    $('hud-empty').hidden=!!widgets.length;grid.setAttribute('aria-busy','false');lastLayout=JSON.stringify(state.layout.widgets);lastData=dataKey();lastActive=JSON.stringify(state.spaces.active);
    motionStart=performance.now();
  }
  let motionStart=performance.now(),lastTick=0,motionPlaying=true;
  $('hud-motion').onclick=()=>{
    motionPlaying=!motionPlaying;motionStart=performance.now();
    const control=$('hud-motion'),label=motionPlaying?'Stop widget animations':'Play widget animations';
    control.title=label;control.setAttribute('aria-label',label);control.setAttribute('aria-pressed',String(motionPlaying));
    control.querySelector('path').setAttribute('d',motionPlaying?'M6 6h12v12H6Z':'m8 5 11 7-11 7Z');
    if(!motionPlaying)grid.querySelectorAll('pre[data-full-text]').forEach(pre=>setOutput(pre,pre.dataset.fullText));
  };
  reduced.addEventListener('change',()=>{if(reduced.matches)grid.querySelectorAll('pre[data-full-text]').forEach(pre=>{setOutput(pre,pre.dataset.fullText);});else motionStart=performance.now();});
  function motion(now){
    if(now-lastTick>90){
      // Recheck here as well as on change: some embedded/browser contexts do
      // not deliver MediaQueryList change events during a live preference swap.
      if(!motionPlaying||matchMedia('(prefers-reduced-motion: reduce)').matches){
        grid.querySelectorAll('pre[data-full-text]').forEach(pre=>{if(pre.textContent!==pre.dataset.fullText)setOutput(pre,pre.dataset.fullText);});
      }else{
      grid.querySelectorAll('.hud-widget').forEach(card=>{
        if(card.matches(':hover,:focus-within'))return;
        const body=card.querySelector('.hud-widget-body');
        if(card.dataset.animation==='marquee'&&body.scrollHeight>body.clientHeight){body.scrollTop+=.65;if(body.scrollTop>=body.scrollHeight-body.clientHeight)body.scrollTop=0;}
        if(card.dataset.animation==='typing'){
          const pre=body.querySelector('pre[data-full-text]');
          if(pre){
            const fullText=pre.dataset.fullText,typingDuration=fullText.length*typingMsPerCharacter;
            // Hold the completed output for three seconds before starting over.
            const elapsed=(now-motionStart)%(typingDuration+3000);
            const count=Math.min(fullText.length,Math.floor(elapsed/typingMsPerCharacter)),text=fullText.slice(0,count);
            if(pre.textContent!==text){
              setOutput(pre,text);
              // Follow the typing cursor once the output fills the widget viewport.
              body.scrollTop=body.scrollHeight;
            }
          }
        }
      });
      }lastTick=now;
    }motionFrame=requestAnimationFrame(motion);
  }
  function catalogRows(){
    const target=$('hud-catalog-items'),q=$('hud-catalog-search').value.toLowerCase();target.replaceChildren();
    for(const item of config.catalog.filter(x=>x.label.toLowerCase().includes(q))){
      const existing=state.layout.widgets.filter(w=>w.operation===item.operation_id),active=existing.find(w=>!w.hidden),hidden=existing.find(w=>w.hidden);
      const row=el('div',null,'hud-catalog-row'),text=el('div');
      text.append(el('strong',item.label),el('small',active?'Already added'+(visible(active)?'':' · in another Space'):hidden?'Hidden · restore to your dashboard':item.schedules.length?'Scheduled collector · '+item.schedules.length+' schedule(s)':item.source_task?'On-demand source':'Built-in view'));
      const heading=el('div',null,'hud-catalog-heading'),pills=el('span',null,'hud-catalog-spaces');
      pills.setAttribute('aria-label','Assigned workspaces');
      const assigned=(active||hidden)?.workspace_ids||[];
      for(const id of assigned){
        const space=state.spaces.views.find(view=>view.id===id);
        if(!space)continue;
        const pill=el('span',null,'hud-space-pill'),dot=el('span',null,'hud-space-dot');
        dot.style.backgroundColor=space.color;
        pill.append(dot,document.createTextNode(space.name));pills.append(pill);
      }
      if(!pills.children.length)pills.append(el('span','All Spaces','hud-space-pill'));
      heading.append(text.firstChild,pills);text.prepend(heading);
      row.append(text);
      if(active){const added=button('Added',()=>{});added.disabled=true;row.classList.add('hud-catalog-added');row.append(added);}
      else if(hidden){row.append(button('Restore',()=>{hidden.hidden=false;changed();$('hud-catalog').close();}));}
      else row.append(button('Add',()=>add(item.operation_id)));
      target.append(row);
    }
    if(!target.children.length)target.append(el('p','No widgets match this search.'));
  }
  function add(operation){if(state.layout.widgets.some(w=>w.operation===operation)){catalogRows();return;}state.layout.widgets.push({id:crypto.randomUUID(),operation,size:'2x2',hidden:false,animation:'static',workspace_ids:[...state.spaces.active],dashboard_url:''});changed();$('hud-catalog').close();}
  async function refresh(){
    if(loading||moving||saving)return;loading=true;const version=refreshVersion;
    if(!state){grid.setAttribute('aria-busy','true');$('hud-loading').hidden=false;$('hud-retry').hidden=true;window.BrainPageLoading?.show('Loading your dashboard...');}
    try {const fresh=await api('/second-brain/hud/data');if(moving||saving||version!==refreshVersion)return;
      if(state&&$('hud-settings').matches(':popover-open'))return;
      state=fresh;$('hud-loading').hidden=true;$('hud-retry').hidden=true;renderSpaces();
      if(lastLayout!==JSON.stringify(state.layout.widgets)||lastData!==dataKey()||lastActive!==JSON.stringify(state.spaces.active))render();
      if($('hud-catalog').open)catalogRows();
      notice(state.source_error);window.BrainPageLoading?.finish();
    }catch(e){window.BrainPageLoading?.finish();notice(e.message);$('hud-loading').hidden=true;$('hud-retry').hidden=false;grid.setAttribute('aria-busy','false');}finally{loading=false;if(version!==refreshVersion)refresh();}
  }
  function spacesChanged(){refreshVersion++;refresh();}
  $('hud-refresh').onclick=refresh;
  $('hud-retry').onclick=refresh;
  document.addEventListener('hud:spaces-changed',spacesChanged);
  $('hud-add').onclick=()=>{if(!state)return;catalogRows();$('hud-catalog').showModal();};$('hud-catalog-search').oninput=catalogRows;
  $('hud-fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await root.requestFullscreen();}catch{notice('Full screen is unavailable in this browser.');}};
  document.addEventListener('fullscreenchange',()=>{const control=$('hud-fullscreen'),active=!!document.fullscreenElement,label=active?'Exit full screen':'Full screen';control.title=label;control.setAttribute('aria-label',label);control.setAttribute('aria-pressed',String(active));control.querySelector('path').setAttribute('d',active?'M3 8h5V3m8 0v5h5M8 21v-5H3m18 0h-5v5':'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5');rowHeight();});
  $('hud-widget-form').onsubmit=async event=>{event.preventDefault();const w=state.layout.widgets.find(x=>x.id===settingsId),form=event.currentTarget;Object.assign(w,{size:form.elements.size.value,animation:form.elements.animation.value,accent:form.elements.accent.value,workspace_ids:selectedChecks($('hud-widget-spaces')),dashboard_url:form.elements.dashboard_url.value});closeSettings();await changed();grid.querySelector(`[data-id="${settingsId}"] .hud-widget-menu-button`)?.focus();};
  $('hud-hide').onclick=()=>{state.layout.widgets.find(w=>w.id===settingsId).hidden=true;closeSettings();changed();};
  $('hud-remove').onclick=()=>{state.layout.widgets=state.layout.widgets.filter(w=>w.id!==settingsId);closeSettings();changed();};
  $('hud-widget-spaces').onchange=spaceCaption;
  $('hud-widget-spaces-clear').onclick=()=>{renderChecks($('hud-widget-spaces'),[]);spaceCaption();};
  $('hud-widget-space-picker').addEventListener('toggle',positionSettings);
  $('hud-widget-space-picker').addEventListener('keydown',event=>{if(event.key==='Escape'&&event.currentTarget.open){event.preventDefault();event.stopPropagation();event.currentTarget.open=false;event.currentTarget.querySelector('summary').focus();}});
  $('hud-settings').addEventListener('toggle',event=>{if(event.newState==='closed')settingsAnchor?.setAttribute('aria-expanded','false');});
  window.addEventListener('resize',positionSettings);document.addEventListener('scroll',positionSettings,true);
  const hotkeysDialog=$('hud-hotkeys-dialog');
  $('hud-hotkeys').onclick=()=>hotkeysDialog.showModal();
  document.addEventListener('keydown',event=>{
    if(event.defaultPrevented||event.repeat||event.isComposing||event.ctrlKey||event.metaKey||event.shiftKey)return;
    if(event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],.xterm'))return;
    if(document.querySelector('#butler-panel:not([hidden])'))return;
    const key=event.key.toLowerCase(),dialog=document.querySelector('dialog[open]');
    if(dialog){if(dialog===hotkeysDialog&&key==='k'){event.preventDefault();hotkeysDialog.close();}return;}
    if(document.querySelector('[popover]:popover-open,.hud-workspace-controls details[open]'))return;
    if(event.altKey){
      if(key==='`'||event.code==='Backquote'||/^[1-9]$/.test(key)){
        event.preventDefault();window.HudSpaces.select(key==='`'||event.code==='Backquote'?0:Number(key));
      }
      return;
    }
    if(key==='n'){event.preventDefault();window.HudSpaces.toggleDynamic();return;}
    // Preserve native Space activation on focused buttons, links and summaries.
    if(key===' '&&event.target.closest('button,a,summary,[role="button"]'))return;
    const id={' ':'hud-workspace-return',a:'hud-motion',g:'hud-add',k:'hud-hotkeys',f:'hud-fullscreen',r:'hud-refresh'}[key];
    if(id){event.preventDefault();$(id).click();}
  });
  $('hud-build').onclick=()=>$('hud-builder').showModal();
  $('hud-build-form').onsubmit=async event=>{
    event.preventDefault();if(!state)return;const form=event.currentTarget,submit=form.querySelector('button[type=submit]');submit.disabled=true;$('hud-build-status').textContent='Preparing action…';
    try{const context=await api('/second-brain/hud/build-context');const prompt=context.instructions+'\n\nSkill versions:\n'+context.skills.map(s=>s.name+': '+s.sha256).join('\n')+'\n\nWidget request:\n'+form.elements.prompt.value;
      const result=await api('/hfl-corpus/timeline/items',{request_id:builderKey,title:form.elements.title.value,prompt,expected_outcome:'A tested web HUD widget and a published draft pull request.',workspace_ids:state.spaces.active});
      location.href='/hfl-corpus/actions?integration_agent='+encodeURIComponent(result.item.id);
    }catch(e){$('hud-build-status').textContent=e.message;submit.disabled=false;}
  };
  new Sortable(grid,{handle:'.hud-drag',forceFallback:true,animation:reduced.matches?0:150,ghostClass:'hud-sort-ghost',onStart(){moving=true;},onEnd(event){moving=false;const ids=[...grid.children].map(c=>c.dataset.id),visibleSet=new Set(ids),ordered=ids.map(id=>state.layout.widgets.find(w=>w.id===id));state.layout.widgets=state.layout.widgets.map(w=>visibleSet.has(w.id)?ordered.shift():w);changed();}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});window.addEventListener('storage',event=>{if(event.key==='corpus:workspace-change')spacesChanged();});
  new ResizeObserver(rowHeight).observe(root.querySelector('.hud-toolbar'));window.addEventListener('resize',rowHeight);rowHeight();
  const timer=setInterval(()=>{if(!document.hidden)refresh();},30000);motionFrame=requestAnimationFrame(motion);refresh();
  window.addEventListener('pagehide',()=>{clearInterval(timer);cancelAnimationFrame(motionFrame);});
})();
