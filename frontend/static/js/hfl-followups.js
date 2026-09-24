/* The board shares cards and commands with the day/period Actions panel. */
(() => {
  const dialog = document.getElementById('followups-board');
  if (!dialog || !window.hflActions) return;
  const page = !!document.querySelector('[data-actions-page]');
  if(page)Object.defineProperty(dialog,'open',{value:true});
  const actions = window.hflActions;
  const $ = selector => dialog.querySelector(selector);
  const lanes = $('[data-board-lanes]'), all = $('[data-board-all]');
  Object.defineProperty(all,'checked',{get(){return this.getAttribute('aria-checked')==='true';},set(value){this.setAttribute('aria-checked',String(!!value));}});
  const status = $('[data-board-status]'), error = $('[data-board-error]');
  const states = ['open','active','in_progress','incomplete','done','dismissed'];
  const label = value => value === 'in_progress' ? 'In Progress' : value[0].toUpperCase()+value.slice(1);
  const listeners = new AbortController();
  let sequence = 0, pending = false, moving = false, dragging = null, disposed = false;
  let items = new Map(), rendered = '', timer, sorters = [];
  let ideasOpen=false, ideaRows=[];
  let pointerHeld = false, savingCards = 0;
  lanes.addEventListener('pointerdown',()=>{pointerHeld=true;},{signal:listeners.signal});
  window.addEventListener('pointerup',()=>{pointerHeld=false;},{signal:listeners.signal});
  window.addEventListener('pointercancel',()=>{pointerHeld=false;},{signal:listeners.signal});
  window.addEventListener('hfl:action-saving',event=>{savingCards+=event.detail.saving?1:-1;},{signal:listeners.signal});
  const node = (tag, text, className) => {const el=document.createElement(tag);if(text!=null)el.textContent=text;if(className)el.className=className;return el;};
  function context() {
    const caption = document.querySelector('[data-active-view-name]')?.textContent || 'All activity';
    const dynamic = document.querySelector('[data-dynamic-badge]')?.textContent || 'Dynamic OFF';
    const params=new URLSearchParams(location.search);
    const extra=['source','q','date_from','date_to'].filter(key=>params.get(key)).map(key=>({source:'Sources',q:'Search',date_from:'From',date_to:'To'}[key])+': '+params.get(key));
    if(page){
      const scoped=params.has('scope')||params.has('workspace');
      $('[data-board-context]').textContent=all.checked?'All activity':[(scoped?'Workspace filters applied':extra.length?'Corpus filters':'All activity'),...extra].join(' · ');
      return;
    }
    $('[data-board-context]').textContent = (all.checked ? 'All activity · Current views: ' : 'Following views: ') + caption + ' · ' + dynamic + (!all.checked&&extra.length?' · '+extra.join(' · '):'');
  }
  async function request(path, options={}) {
    const response=await fetch('/hfl-corpus/timeline/items'+path,{cache:'no-store',...options,headers:{'Content-Type':'application/json'}});
    const data=await response.json();
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Could not load follow-ups. Retry.');
    return data;
  }
  function render(rows) {
    const signature=JSON.stringify([rows,ideasOpen,ideaRows]);
    if(signature===rendered)return;
    const expanded=new Set([...lanes.querySelectorAll('details[open]')].map(el=>el.closest('[data-followup-id]').dataset.followupId+':'+el.querySelector('summary').textContent));
    const scroll=new Map([...lanes.children].map(el=>[el.dataset.status,el.scrollTop]));
    const focused=document.activeElement;
    const focusId=focused?.closest('[data-followup-id]')?.dataset.followupId, focusText=focused?.textContent;
    const oldItems=items, oldCards=new Map([...lanes.querySelectorAll('[data-followup-id]')].map(el=>[el.dataset.followupId,el]));
    items=new Map(rows.map(item=>[item.id,item]));
    sorters.forEach(sorter=>sorter.destroy());sorters=[];
    dialog.querySelector('.ideas-drawer-overlay')?.remove();
    lanes.replaceChildren();
    for(const state of states){
      const section=node('section',null,'followups-lane');section.dataset.status=state;section.setAttribute('aria-label',label(state));
      const matching=rows.filter(item=>item.status===state).sort((a,b)=>(a.board_position??2147483647)-(b.board_position??2147483647));
      section.append(node('h3',label(state)+' · '+matching.length));
      for(const item of matching){
        if(oldCards.has(item.id)&&JSON.stringify(oldItems.get(item.id))===JSON.stringify(item)){
          section.append(oldCards.get(item.id));continue;
        }
        const card=actions.card(item);card.tabIndex=0;
        const clone=node('button','⧉','action-clone-handle');clone.type='button';clone.title='Clone action';clone.setAttribute('aria-label','Clone '+item.title);clone.onclick=()=>window.HflIdeas.cloneObject('actionable',item.id);card.prepend(clone);
        const grip=node('button','⠿','action-drag-handle');grip.type='button';grip.setAttribute('aria-label','Move '+item.title);grip.title='Drag to move card; Alt+Up/Down to reorder';card.prepend(grip);
        card.setAttribute('aria-keyshortcuts','Alt+ArrowUp Alt+ArrowDown');
        card.title='Drag to reorder or change status. Alt+Up/Down reorders within this column.';
        card.addEventListener('keydown',event=>{
          if(![card,grip].includes(event.target)||!event.altKey||!['ArrowUp','ArrowDown'].includes(event.key)||moving)return;
          event.preventDefault();
          const lane=card.parentElement, cards=[...lane.querySelectorAll('[data-followup-id]')], index=cards.indexOf(card), next=index+(event.key==='ArrowUp'?-1:1);
          if(next<0||next>=cards.length)return;
          lane.insertBefore(card,next<index?cards[next]:cards[next].nextSibling);
          move(item.id,state,[...lane.querySelectorAll('[data-followup-id]')].map(el=>el.dataset.followupId));
        });
        card.querySelectorAll('details').forEach(el=>el.open=expanded.has(item.id+':'+el.querySelector('summary').textContent));
        section.append(card);
      }
      if(!matching.length)section.append(node('p','No actions','agenda-description'));
      lanes.append(section);section.scrollTop=scroll.get(state)||0;
      sorters.push(new Sortable(section,{
        group:'hfl-actions',draggable:'.agenda-card',filter:'button:not(.action-drag-handle),a,input,summary,textarea,select,label',preventOnFilter:false,
        forceFallback:true,fallbackOnBody:false,fallbackTolerance:4,
        animation:150,delay:180,delayOnTouchOnly:true,touchStartThreshold:5,ghostClass:'followups-drag-placeholder',
        onMove:()=>!savingCards&&!moving,
        onStart:event=>{dragging=event.item.dataset.followupId;dialog.dataset.busy='true';},
        onEnd:event=>{
          if(event.item.dataset.ideaId){dragging=null;pointerHeld=false;delete dialog.dataset.busy;event.from.append(event.item);window.HflIdeas.convert(event.item.dataset.ideaId);return;}
          const id=event.item.dataset.followupId;dragging=null;pointerHeld=false;
          if(event.from===event.to&&event.oldIndex===event.newIndex){delete dialog.dataset.busy;return;}
          move(id,event.to.dataset.status,[...event.to.querySelectorAll('[data-followup-id]')].map(el=>el.dataset.followupId));
        }
      }));
    }
    if(ideasOpen){
      const section=node('section',null,'followups-lane ideas-drawer');section.dataset.status='ideas';section.setAttribute('aria-label','Ideas');
      const header=node('div',null,'ideas-drawer-header');header.append(node('h3','Ideas · '+ideaRows.length));
      const create=node('button','New idea');create.type='button';create.onclick=()=>window.HflIdeas.openEditor('idea');header.append(create);section.append(header);
      for(const item of ideaRows){const card=node('article',null,'agenda-card');card.dataset.ideaId=item.id;const title=node('button',item.title);title.onclick=()=>window.HflIdeas.editIdea(item.id);
        const grip=node('button','⠿','action-drag-handle');grip.setAttribute('aria-label','Drag idea '+item.title);
        const clone=node('button','⧉','action-clone-handle');clone.setAttribute('aria-label','Clone '+item.title);clone.onclick=()=>window.HflIdeas.cloneObject('idea',item.id);
        const convert=node('button','Create action');convert.onclick=()=>window.HflIdeas.convert(item.id);card.append(grip,clone,title,convert);section.append(card);}
      const overlay=node('div',null,'ideas-drawer-overlay'), backdrop=node('div',null,'ideas-drawer-backdrop');
      backdrop.onclick=()=>closeIdeasDrawer();
      const close=node('button','×','ideas-drawer-close');close.type='button';close.setAttribute('aria-label','Close ideas drawer');close.onclick=()=>closeIdeasDrawer();header.append(close);
      overlay.append(backdrop,section);dialog.append(overlay);
      sorters.push(new Sortable(section,{group:{name:'hfl-actions',pull:true,put:false},draggable:'.agenda-card',handle:'.action-drag-handle',forceFallback:true,animation:150,
        onStart:()=>{dragging='idea';backdrop.style.pointerEvents='none';},onEnd:event=>{backdrop.style.pointerEvents='';dragging=null;pointerHeld=false;if(event.to!==event.from){event.from.append(event.item);window.HflIdeas.convert(event.item.dataset.ideaId);}}}));
    }
    if(focusId){
      const card=[...lanes.querySelectorAll('[data-followup-id]')].find(el=>el.dataset.followupId===focusId);
      if(focused?.matches('[data-followup-id]'))card?.focus({preventScroll:true});
      else card?.querySelectorAll('button,summary,a').forEach(el=>{if(el.textContent===focusText)el.focus({preventScroll:true});});
    }
    rendered=signature;
  }
  async function refresh(force=false) {
    if(!dialog.open || disposed || moving || dragging || pointerHeld || savingCards || (pending&&!force))return;
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
      if(dragging||moving||pointerHeld||savingCards)return;
      if(ideasOpen){const ideaParams=new URLSearchParams(params);ideaParams.delete('offset');ideaParams.set('dismissed','0');ideaRows=(await window.HflIdeas.api('/reuse/board-ideas?'+ideaParams)).items;if(ticket!==sequence)return;}
      render(rows);error.hidden=true;status.textContent=rows.length+' action'+(rows.length===1?'':'s')+' · Updates every 5 seconds';
    }catch(e){if(ticket===sequence){error.textContent=e.message;error.hidden=false;status.textContent='Could not refresh. Displayed actions may be out of date. Use Refresh to retry.';}}
    finally{if(ticket===sequence){pending=false;lanes.removeAttribute('aria-busy');}}
  }
  async function move(id,state,order){
    const item=items.get(id);if(!item||moving)return;
    moving=true;dialog.dataset.busy='true';++sequence;pending=false;lanes.inert=true;status.textContent='Saving card order…';
    let failure='',statusSaved=false;
    try{
      if(item.status!==state){const data=await request('/'+id,{method:'PATCH',body:JSON.stringify({version:item.version,status:state})});items.set(id,data.item);statusSaved=true;}
      await request('/order',{method:'PUT',body:JSON.stringify({status:state,items:order.map(identity=>({id:identity,version:items.get(identity).version}))})});
    }
    catch(e){failure=e.message+(statusSaved?' Status changed, but the card order was not saved.':' The move was not saved.');}
    finally{moving=false;delete dialog.dataset.busy;lanes.inert=false;}
    rendered='';await refresh(true);actions.load();
    if(failure){error.textContent=failure+' The board has been reloaded.';error.hidden=false;}
  }
  function open(){if(!page){location.assign('/hfl-corpus/actions'+location.search);return;}context();refresh(true);clearInterval(timer);timer=setInterval(()=>{if(!document.hidden&&!document.querySelector('dialog[open]:not(#followups-board)')){refresh();actions.load();}},5000);}
  const opener=document.querySelector('[data-followups-open]');
  if(opener)opener.onclick=event=>{if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();document.querySelector('.corpus-tools').open=false;open();};
  $('[data-board-close]').onclick=()=>{if(page){const url=new URL(location.href);url.pathname='/hfl-corpus';url.searchParams.delete('edit');url.searchParams.delete('edit_kind');url.searchParams.delete('all');location.assign(url);}else dialog.close();};
  $('[data-board-create]').onclick=()=>actions.openEditor();
  $('[data-board-refresh]').onclick=()=>refresh(true);
  const workspaceFilter=node('div',null,'board-workspace-filter'), workspaceTitle=node('button','Workspaces'), workspaceChoices=node('div',null,'board-workspace-options');
  workspaceTitle.type='button';workspaceTitle.setAttribute('aria-expanded','false');workspaceTitle.setAttribute('aria-controls','board-workspace-options');
  workspaceChoices.id='board-workspace-options';workspaceChoices.hidden=true;workspaceChoices.setAttribute('role','group');workspaceChoices.setAttribute('aria-label','Filter by workspaces');
  workspaceFilter.append(workspaceTitle,workspaceChoices);$('[data-board-context]').before(workspaceFilter);
  const selectedWorkspaces=new Set((new URLSearchParams(location.search).get('workspace_ids')||'').split(',').filter(Boolean));
  const workspaceCaption=()=>{workspaceTitle.textContent='Workspaces';};
  const closeWorkspaces=()=>{workspaceChoices.hidden=true;workspaceTitle.setAttribute('aria-expanded','false');};
  workspaceCaption();
  workspaceTitle.onclick=()=>{workspaceChoices.hidden=!workspaceChoices.hidden;workspaceTitle.setAttribute('aria-expanded',String(!workspaceChoices.hidden));};
  document.addEventListener('click',event=>{if(!workspaceFilter.contains(event.target))closeWorkspaces();},{signal:listeners.signal});
  workspaceFilter.addEventListener('keydown',event=>{if(event.key==='Escape'){closeWorkspaces();workspaceTitle.focus();}});
  fetch('/hfl-corpus/workspace-views').then(async response=>{if(!response.ok)throw Error();return response.json();}).then(data=>{
    if(!data.views.length)workspaceChoices.append(node('p','No workspaces available'));
    for(const view of data.views){const label=node('label'),choice=node('input');choice.type='checkbox';choice.value=view.id;choice.checked=selectedWorkspaces.has(view.id);label.append(choice,document.createTextNode(view.name));workspaceChoices.append(label);
      choice.onchange=()=>{choice.checked?selectedWorkspaces.add(view.id):selectedWorkspaces.delete(view.id);workspaceCaption();const url=new URL(location.href);if(selectedWorkspaces.size)url.searchParams.set('workspace_ids',[...selectedWorkspaces].join(','));else url.searchParams.delete('workspace_ids');url.searchParams.delete('all');all.checked=false;history.replaceState(null,'',url);refresh(true);};
    }
  }).catch(()=>{workspaceTitle.textContent='Workspaces unavailable';});
  all.checked=new URLSearchParams(location.search).get('all')==='1';
  all.onclick=()=>{all.checked=!all.checked;const url=new URL(location.href);all.checked?url.searchParams.set('all','1'):url.searchParams.delete('all');history.replaceState(null,'',url);refresh(true);};
  const toolsMenu=document.querySelector('.corpus-tools');
  toolsMenu?.addEventListener('toggle',()=>{if(toolsMenu.open){const profile=document.querySelector('summary[aria-label="Profile menu"]')?.parentElement;if(profile)profile.open=false;}});
  document.addEventListener('click',event=>{if(toolsMenu&&!toolsMenu.contains(event.target))toolsMenu.open=false;},{signal:listeners.signal});
  toolsMenu?.addEventListener('keydown',event=>{if(event.key==='Escape'){toolsMenu.open=false;toolsMenu.querySelector('summary').focus();}});
  dialog.addEventListener('close',()=>{++sequence;pending=false;clearInterval(timer);});
  window.addEventListener('hfl:actions-updated',()=>refresh(true),{signal:listeners.signal});
  window.addEventListener('hfl:agent-updated',()=>refresh(),{signal:listeners.signal});
  window.addEventListener('hfl:action-error',async event=>{if(dialog.open){await refresh(true);error.textContent=event.detail;error.hidden=false;}},{signal:listeners.signal});
  window.addEventListener('hfl:view-replacing',()=>{
    try{if(dialog.open)sessionStorage.setItem('hfl:followups-restore',JSON.stringify({all:all.checked}));}catch(_){}
    disposed=true;++sequence;clearInterval(timer);listeners.abort();sorters.forEach(sorter=>sorter.destroy());
  },{signal:listeners.signal});
  function closeIdeasDrawer(){
    ideasOpen=false;dialog.querySelector('.ideas-drawer-toggle')?.setAttribute('aria-expanded','false');render([...items.values()]);dialog.querySelector('.ideas-drawer-toggle')?.focus();
  }
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&ideasOpen&&!document.querySelector('dialog[open]')){event.preventDefault();closeIdeasDrawer();}},{signal:listeners.signal});
  if(page){const toggle=node('button',null,'ideas-drawer-toggle');toggle.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18h6M9 21h6M9 15c0-2-3-3-3-7a6 6 0 0 1 12 0c0 4-3 5-3 7z"/></svg>';toggle.setAttribute('aria-label','Toggle ideas drawer');toggle.title='Ideas';toggle.setAttribute('aria-expanded','false');toggle.onclick=()=>{if(ideasOpen){closeIdeasDrawer();return;}ideasOpen=true;toggle.setAttribute('aria-expanded','true');render([...items.values()]);refresh(true);};dialog.append(toggle);open();}
  window.addEventListener('hfl:ideas-updated',()=>refresh(true),{signal:listeners.signal});
  try{const restore=JSON.parse(sessionStorage.getItem('hfl:followups-restore')||'null');sessionStorage.removeItem('hfl:followups-restore');if(restore){all.checked=restore.all;requestAnimationFrame(open);}}catch(_){}
})();
