/* HUD adapter for the shared Corpus Space menu, preferences and preview routes. */
(() => {
  'use strict';
  const host=document.querySelector('.hud-workspace-controls'),find=selector=>host.querySelector(selector);
  const menu=find('[data-workspace-menu]'),picker=find('[data-view-picker]'),choices=find('[data-view-choices]');
  const toggle=find('[data-dynamic-toggle]'),status=find('[data-workspace-status]');
  const csrf=JSON.parse(document.getElementById('hud-config').textContent).csrf;
  let current,draft,pending=[],busy=false,previewController,previewKey='';
  const node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
  const key=ids=>[...ids].sort().join(',');
  function caption(){find('[data-view-picker-caption]').textContent=current.views.filter(v=>pending.includes(v.id)).map(v=>v.name).join(' + ')||'All activity';}
  function renderChoices(){
    choices.replaceChildren();
    for(const view of current.views){
      const label=node('label'),input=node('input'),dot=node('span');input.type='checkbox';input.value=view.id;input.checked=pending.includes(view.id);
      dot.className='hud-space-dot';dot.style.backgroundColor=view.color;
      label.append(input,dot,document.createTextNode(view.name));choices.append(label);
      input.onchange=()=>{pending=[...choices.querySelectorAll('input:checked')].map(el=>el.value);caption();};
    }
    caption();
  }
  function indicators(){
    const badges=document.getElementById('hud-active-spaces');badges.replaceChildren();
    for(const view of current.views.filter(v=>current.active.includes(v.id))){const badge=node('strong',view.name);badge.setAttribute('data-active-view-name','');badge.style.borderLeft=`3px solid ${view.color}`;badges.append(badge);}
    if(!badges.children.length){const badge=node('strong','All activity');badge.setAttribute('data-active-view-name','');badges.append(badge);}
    const dynamic=document.getElementById('hud-dynamic-badge');dynamic.textContent='Dynamic '+(current.preferences.dynamic?'ON':'OFF');dynamic.dataset.on=String(current.preferences.dynamic);
    const hasSchedule=current.views.some(v=>v.schedule?.length);
    toggle.checked=current.preferences.dynamic;toggle.disabled=busy||(!hasSchedule&&!current.preferences.dynamic);
    find('[data-dynamic-hint]').hidden=hasSchedule;
  }
  function resetDraft(){draft=structuredClone(current.preferences);pending=[...current.active];renderChoices();}
  window.HudSpaces={update(data){
    if(busy)return;
    // Keep the open menu's revision so concurrent changes cannot overwrite one another.
    if(menu.open&&current)return;
    current=data;indicators();resetDraft();
  },select(index){
    if(!current||busy||index>current.views.length)return;
    resetDraft();
    return save({manual:index?[current.views[index-1].id]:[],dynamic:false});
  },toggleDynamic(){if(current&&!busy&&!toggle.disabled)toggle.click();}};
  async function save(changes){
    if(!current||busy)return;busy=true;status.textContent='Saving…';toggle.disabled=true;
    choices.querySelectorAll('input').forEach(el=>el.disabled=true);
    try{
      const response=await fetch('/hfl-corpus/view-preferences',{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({...draft,...changes})});
      const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Could not save Space selection.');
      current=data;resetDraft();status.textContent='Saved';
      try{localStorage.setItem('corpus:workspace-change',Date.now());}catch{}
      document.dispatchEvent(new Event('hud:spaces-changed'));
      return true;
    }catch(error){
      status.textContent=error.message;
      try{const response=await fetch('/hfl-corpus/workspace-views',{cache:'no-store'});if(response.ok){current=await response.json();resetDraft();}}catch{}
      return false;
    }finally{busy=false;indicators();choices.querySelectorAll('input').forEach(el=>el.disabled=false);}
  }
  function applySelection(){if(current&&key(pending)!==key(current.active))return save({manual:pending,dynamic:false});}
  menu.addEventListener('toggle',()=>{if(!current)return;if(menu.open){if(!busy)resetDraft();}else{picker.open=false;applySelection();}});
  picker.addEventListener('toggle',()=>{if(!picker.open)applySelection();});
  find('[data-view-all]').onclick=()=>{if(!current||busy)return;pending=[];renderChoices();picker.open=false;save({manual:[],dynamic:false});};
  toggle.onchange=()=>save({dynamic:toggle.checked});
  document.addEventListener('click',event=>{if(!menu.contains(event.target))menu.open=false;else if(!picker.contains(event.target))picker.open=false;});
  menu.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(picker.open){picker.open=false;picker.querySelector('summary').focus();}else{menu.open=false;menu.querySelector('summary').focus();}}});
  const help=find('#workspace-help');
  find('[data-workspace-help-open]').onclick=()=>{menu.open=false;help.showModal();help.querySelector('h2').focus();};
  host.querySelectorAll('[data-workspace-help-close]').forEach(button=>button.onclick=()=>help.close());
  help.addEventListener('close',()=>{menu.open=true;find('[data-workspace-help-open]').focus();});
  document.addEventListener('corpus:edit-scheduled-view',event=>location.assign('/spaces?edit='+encodeURIComponent(event.detail)));

  // Reuse the owner-only Corpus share handoff. This opens a draft, never publishes it.
  const share=find('[data-corpus-share-dialog]'),content=find('[data-corpus-share-content]'),shareStatus=find('[data-corpus-share-status]');
  const shareKey=()=>JSON.stringify([current.active,current.views,current.today]);
  function shareData(){
    const data=new FormData(),views=current.views.filter(v=>current.active.includes(v.id));
    data.set('csrf',csrf);data.set('state','{}');data.set('workspace',views.length===1?views[0].id:'');data.set('views',current.active.join(','));
    const clauses=views.map(view=>{const clause={...view.state};if(clause.rolling&&current.today){const start=new Date(current.today+'T12:00:00Z');start.setUTCDate(start.getUTCDate()-clause.rolling+1);clause.date_from=start.toISOString().slice(0,10);clause.date_to=current.today;clause.rolling=0;}return clause;});
    data.set('scope',JSON.stringify({any:clauses,all:{}}));
    if(previewKey===shareKey())content.querySelectorAll('[name="enabled_reference_ids"]:not(:checked)').forEach(input=>data.append('disabled_reference_ids',input.value));
    return data;
  }
  find('[data-corpus-share-preview]').onclick=async()=>{
    if(!current||busy)return;if(await applySelection()===false)return;menu.open=false;content.replaceChildren();previewKey=shareKey();share.showModal();find('#corpus-share-title').focus();shareStatus.textContent='Loading preview…';
    previewController?.abort();const controller=new AbortController();previewController=controller;
    try{
      const response=await fetch('/sharing/from-corpus?mode=preview',{method:'POST',body:shareData(),signal:controller.signal});
      if(response.redirected||(!response.ok&&response.status!==422))throw Error('Could not load sharing preview. Reopen to retry.');
      const html=await response.text();if(controller.signal.aborted)return;
      content.innerHTML=html;shareStatus.textContent='';
    }catch(error){if(error.name!=='AbortError')shareStatus.textContent=error.message;}
  };
  find('[data-corpus-share-close]').onclick=()=>share.close();
  share.addEventListener('close',()=>{previewController?.abort();menu.open=true;find('[data-corpus-share-preview]').focus();});
  find('[data-corpus-share-form]').onsubmit=event=>event.preventDefault();
  content.addEventListener('change',event=>{if(event.target.matches('[data-toggle-all-references]'))content.querySelectorAll('[name="enabled_reference_ids"]').forEach(input=>input.checked=event.target.checked);});
  host.querySelectorAll('[data-corpus-share-generate]').forEach(button=>button.onclick=async()=>{
    if(!current||busy)return;if(await applySelection()===false)return;const form=node('form');form.method='POST';form.action='/sharing/from-corpus';form.hidden=true;
    for(const [name,value] of shareData()){const input=node('input');input.type='hidden';input.name=name;input.value=value;form.append(input);}
    document.body.append(form);form.submit();
  });
})();
