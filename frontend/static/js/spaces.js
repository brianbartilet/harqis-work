(() => {
  const root = document.querySelector('[data-spaces-csrf]'); if (!root) return;
  const $ = selector => root.querySelector(selector);
  const help = $('#spaces-help'), helpTrigger = $('#spaces-help-open');
  helpTrigger.onclick = () => { help.showModal(); $('#spaces-help-title').focus(); };
  help.querySelectorAll('[data-spaces-help-close]').forEach(button => button.onclick = () => help.close());
  help.addEventListener('close', () => helpTrigger.focus());
  help.addEventListener('click', event => {
    const box = help.getBoundingClientRect();
    if (event.target === help && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) help.close();
  });

  let viewData = JSON.parse($('#spaces-data').textContent), views = viewData.views, preferences = viewData.preferences;
  const sources = JSON.parse($('#spaces-sources').textContent).map(value => ({value}));
  const tagOptions = JSON.parse($('#spaces-tags').textContent);
  const queryInput = $('[data-edit-filter="q"]');
  function renderTags() {
    const tokens = queryInput.value.split(/\s+/).filter(Boolean);
    const selected = [...new Set(tokens.filter(token => token.startsWith('#') && token.length > 1).map(token => token.slice(1).toLowerCase()))];
    $('[data-space-tag-count]').textContent = selected.length ? `${selected.length} selected` : 'All tags';
    const selectedList = $('[data-space-tags-selected]'), list = $('[data-space-tags]');
    selectedList.replaceChildren(); list.replaceChildren();
    function chip(tag, count, active, destination) {
      const button = document.createElement('button');
      button.type = 'button'; button.dataset.spaceTag = tag;
      button.setAttribute('aria-pressed', String(active));
      button.textContent = '#' + tag + (count == null ? '' : ` ${count}`);
      button.onclick = () => {
        const matching = selected.filter(value => tag.toLowerCase().includes(value));
        queryInput.value = (matching.length ? tokens.filter(token => !token.startsWith('#') || !matching.includes(token.slice(1).toLowerCase())) : [...tokens, '#' + tag]).join(' ');
        queryInput.dispatchEvent(new Event('input', {bubbles:true}));
        const replacement = [...root.querySelectorAll('[data-space-tag]')].find(item => item.dataset.spaceTag === tag);
        (replacement || $('[data-space-tag-search]')).focus();
      };
      destination.append(button);
    }
    selected.forEach(tag => chip(tag, null, true, selectedList));
    selectedList.hidden = !selected.length;
    const search = $('[data-space-tag-search]').value.trim().toLowerCase().replace(/^#/, '');
    const visible = tagOptions.filter(([tag]) => !selected.includes(tag.toLowerCase()) && tag.toLowerCase().includes(search)).slice(0,100);
    visible.forEach(([tag,count]) => chip(tag, count, selected.some(value => tag.toLowerCase().includes(value)), list));
    $('[data-space-tags-empty]').hidden = !!visible.length;
  }
  queryInput.addEventListener('input', renderTags);
  $('[data-space-tags-clear]').onclick = () => {
    queryInput.value = queryInput.value.split(/\s+/).filter(token => token && !(token.startsWith('#') && token.length > 1)).join(' ');
    queryInput.dispatchEvent(new Event('input', {bubbles:true}));
  };
  $('[data-space-tag-search]').addEventListener('input', renderTags);
  $('[data-space-tag-search]').addEventListener('keydown', event => {
    if (event.key === 'Enter') event.preventDefault();
  });
  let editTarget = null, busy = false, baseline = '', draft = null;
  const form = $('#space-form');
  const defaults = {q:'',source:'',date_field:'created',date_from:'',date_to:'',rolling:0,sort:'desc',page_size:20};
  function payload() { return {name:form.elements.name.value.trim(), color:$('[data-view-colors]').dataset.selected, state:readViewEditor(),schedule:readSchedule(),revision:editTarget?.revision || 0}; }
  function dirty() { return editTarget && JSON.stringify(payload()) !== baseline; }
  function mayLeave() { return !dirty() || window.confirm('Discard unsaved Space changes?'); }
  window.addEventListener('beforeunload', event => { if(dirty()){event.preventDefault();event.returnValue='';} });
  async function request(path='', method='GET', body) {
    const response = await fetch('/hfl-corpus/workspace-views'+path, {method,cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':root.dataset.spacesCsrf},body:body?JSON.stringify(body):undefined});
    const value = await response.json();
    if (!response.ok) throw Error(typeof value.detail==='string'?value.detail:Array.isArray(value.detail)?value.detail.map(e=>e.msg).join(' '):'Unable to save this Space. Try again.');
    return value;
  }
  let noticeTimer;
  function announce(text, transient=false) {
    clearTimeout(noticeTimer);
    const notice=$('#space-status');
    notice.classList.toggle('role-save-notice',transient);
    notice.textContent=text;
    if(transient) noticeTimer=setTimeout(()=>{
      notice.textContent='';
      notice.classList.remove('role-save-notice');
    },4000);
  }
  function changed() { try { localStorage.setItem('corpus:workspace-change',String(Date.now())); } catch (_) {} }
  function summary(view) {
    const s=view.state;
    return [s.entry_scope ? 'Saved timeline filters' : '', s.has_media ? 'Has media' : '', s.exclude_tags ? 'Excluding: ' + s.exclude_tags : '', s.expression ? 'Additional expression conditions' : '', s.order_by ? 'Order by: ' + s.order_by : '', s.q, s.source || 'All sources', s.rolling?`Last ${s.rolling} days`:(s.date_from||s.date_to)?`${s.date_from||'Any start'} – ${s.date_to||'Today'}`:'All dates',`${view.schedule?.length||0} time blocks`].filter(Boolean).join(' · ');
  }
  function list() {
    const query=$('#space-search').value.toLowerCase();
    const matches=views.filter(v=>(v.name+' '+summary(v)).toLowerCase().includes(query));
    $('#space-count').textContent=`${matches.length} of ${views.length} Spaces`;
    const list=$('#space-list');list.replaceChildren();
    matches.forEach(view=>{
      const button=document.createElement('button');button.type='button';button.className='space-card';button.style.borderLeftColor=view.color;
      button.setAttribute('aria-pressed',String(editTarget?.id===view.id));
      const title=document.createElement('strong'), detail=document.createElement('small');title.textContent=view.name;detail.textContent=summary(view);button.append(title,detail);
      button.onclick=()=>{if(!busy&&mayLeave())open(view);};list.append(button);
    });
    if(!matches.length){const empty=document.createElement('p');empty.className='role-help';empty.textContent=views.length?'No matching Spaces.':'No Spaces yet. Create one to get started.';list.append(empty);}
  }
  function dates() { for(const key of ['date_from','date_to']) $(`[data-edit-filter="${key}"]`).disabled=!!Number($('[data-edit-filter="rolling"]').value); }
  function open(view) {
    editTarget=structuredClone(view||{name:'',state:defaults,schedule:[]});
    form.hidden=false;$('#space-empty').hidden=true;form.elements.name.value=editTarget.name;
    fillViewEditor(editTarget);dates();$('#space-remove').hidden=!editTarget.id;$('#space-error').textContent='';
    $('#space-discard').disabled=busy||!editTarget.id;
    $('#space-editor-title').textContent=editTarget.id?'Edit Space':'New Space';baseline=JSON.stringify(payload());list();form.elements.name.focus();
  }
  function lock(value) {busy=value;root.querySelectorAll('button').forEach(b=>b.disabled=value);form.querySelectorAll('input,select,textarea').forEach(e=>e.disabled=value);$('#space-discard').disabled=value||!editTarget?.id;if(!value){dates();const expression=form.querySelector('[data-expression-editor]');if(expression)expression.disabled=!form.querySelector('[data-expression-toggle]').checked;}}
  $('#space-discard').onclick=()=>{
    if(busy||!editTarget?.id)return;
    const saved=views.find(view=>view.id===editTarget.id);
    if(!saved)return;
    open(saved);
    announce('Changes discarded. Saved Space settings restored.');
    $('#space-discard').focus();
  };
  async function refresh() {viewData=await request();views=viewData.views;preferences=viewData.preferences;list();}
  $('#space-new').onclick=()=>{if(mayLeave())open();};$('#space-search').oninput=list;
  $('[data-edit-filter="rolling"]').onchange=dates;
  form.onsubmit=async event=>{
    event.preventDefault();if(busy||!form.reportValidity())return;
    const body=payload();lock(true);$('#space-error').textContent='';
    try {const saved=await request(editTarget.id?'/'+editTarget.id:'',editTarget.id?'PUT':'POST',body);
      views=[...views.filter(v=>v.id!==saved.id),saved].sort((a,b)=>a.name.localeCompare(b.name));
      open(saved);changed();announce('Space saved. Its filters and schedule are ready to use.',true);
      try {await refresh();} catch (_) {announce('Space saved. The list could not refresh; reload to see changes from other browsers.');}
    } catch(error){$('#space-error').textContent=error.message+' Your edits are still here. Reload the page to get the latest version if another browser changed this Space.';}
    finally{lock(false);}
  };
  const removeDialog=$('#space-delete');
  $('#space-remove').onclick=()=>{ $('#space-delete-description').textContent=`Remove “${editTarget.name}”? This removes its saved filters and schedule. Entries and other objects are kept. Review any linked Facets and object assignments afterward.`;$('#space-delete-error').textContent='';removeDialog.showModal();$('#space-delete-cancel').focus();};
  $('#space-delete-cancel').onclick=()=>removeDialog.close();
  $('#space-delete-confirm').onclick=async()=>{
    if(busy)return;lock(true);
    try{await request('/'+encodeURIComponent(editTarget.id)+'?revision='+editTarget.revision,'DELETE');views=views.filter(v=>v.id!==editTarget.id);editTarget=null;baseline='';changed();removeDialog.close();form.hidden=true;$('#space-empty').hidden=false;list();announce('Space removed. Your entries and objects are unchanged.');
      try {await refresh();} catch (_) {announce('Space removed. The list could not refresh; reload to see changes from other browsers.');}
    }
    catch(error){$('#space-delete-error').textContent=error.message;}finally{lock(false);}
  };
  const params=new URLSearchParams(location.search);
  if(params.has('draft')){
    try{const value=JSON.parse(sessionStorage.getItem('harqis:space-draft'));sessionStorage.removeItem('harqis:space-draft');if(value?.state&&Date.now()-value.at<30*60*1000)draft=value;}catch(_){}
    if(!draft)announce('The filter handoff expired or is unavailable. Return to your activity view and choose Manage Spaces again.');
  }
  if(draft){
    (draft.sources||[]).forEach(value=>sources.push({value}));$('#space-handoff').hidden=false;
    $('#space-handoff-text').textContent=draft.combined?'Several Spaces were selected. These are the additional filters only; their combined rules cannot be copied into a single Space. Choose a destination and review every filter before saving.':'Choose a destination to review these filters. Nothing is saved automatically.';
    if(draft.feed) $('#space-handoff-text').textContent='Save this timeline as a Space. Combined Space filters are preserved; the fields below can further narrow them.';
    const destination=$('#space-destination');views.forEach(v=>destination.add(new Option(v.name,v.id)));
    $('#space-apply-draft').onclick=()=>{
      if(!destination.value){announce('Choose New Space or an existing Space first.');destination.focus();return;}
      const target=views.find(v=>v.id===destination.value);
      if(destination.value!=='new'&&!target){announce('That Space is no longer available.');return;}
      if(!mayLeave())return;
      open({...target,name:target?.name||'',state:{...defaults,...draft.state},schedule:target?.schedule||[]});
      baseline='';$('[data-applied-filters]').open=true;$('#space-handoff').hidden=true;
      announce('Review the imported filters, then Save Space to apply them.');
    };
    $('#space-dismiss-draft').onclick=()=>{$('#space-handoff').hidden=true;draft=null;};
  }
  list();
  if(params.has('edit')){const target=views.find(v=>v.id===params.get('edit'));if(target)open(target);else announce('This Space is no longer available. Choose another Space.');}
  function fillViewEditor(view) {
    if (!view) return;
    const rules = $('[data-feed-rules]'), ruleList = $('[data-feed-rules-list]');
    rules.hidden = !view.state.entry_scope; ruleList.replaceChildren();
    function describeScope(raw) {
      const scope = JSON.parse(raw);
      for (const [prefix, states] of [['Match any', scope.any || []], ['Also require', [scope.all || {}]]]) {
        for (const state of states) {
          const labels = [state.q, state.source && 'Sources: ' + state.source,
            state.rolling ? `Last ${state.rolling} days` : [state.date_from, state.date_to].filter(Boolean).join(' to ')];
          if (labels.some(Boolean)) {
            const item = document.createElement('li'); item.textContent = prefix + ': ' + labels.filter(Boolean).join(' · '); ruleList.append(item);
          }
          if (state.entry_scope) describeScope(state.entry_scope);
        }
      }
    }
    if (view.state.entry_scope) describeScope(view.state.entry_scope);
    $('[data-schedule-timezone]').textContent = `Times use ${preferences.timezone}. Change it in Profile settings.`;
    document.querySelectorAll('[data-edit-filter]').forEach(input => input.value = view.state[input.dataset.editFilter] ?? (input.dataset.editFilter === 'has_media' ? 'false' : ''));
    document.querySelector('[data-advanced-filters]')?.refreshAdvanced?.();
    $('[data-space-tag-search]').value = '';
    renderTags();
    fillEditorSources(view.state.source || '');
    const palette = $('[data-view-colors]'); palette.replaceChildren();
    palette.dataset.selected = view.color || viewData.palette[views.length % viewData.palette.length];
    viewData.palette.forEach(color => {
      const button = document.createElement('button'); button.type = 'button';
      button.className = 'view-color-swatch'; button.style.backgroundColor = color;
      button.setAttribute('aria-label', `Color ${color}`); button.setAttribute('aria-pressed', String(palette.dataset.selected === color));
      button.onclick = () => { palette.dataset.selected = color; palette.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button))); };
      palette.append(button);
    });
    $('[data-schedule-blocks]').replaceChildren();
    (view.schedule || []).forEach(addBlock);
  }
  form.addEventListener('corpus:expression-state', event => { fillEditorSources(event.detail.source); renderTags(); });
  function fillEditorSources(value) {
    const selected = value.split(',').filter(Boolean);
    const names = [...new Set([...sources.map(input => input.value), ...selected])].sort((a,b) => a.localeCompare(b));
    const list = $('[data-edit-source-options]'); list.replaceChildren();
    names.forEach(name => {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.value = name; input.checked = selected.includes(name);
      input.onchange = syncEditorSources; label.append(input, name); list.append(label);
    });
    $('[data-edit-sources]').open = false;
    syncEditorSources();
  }
  function syncEditorSources() {
    const selected = [...$('[data-edit-source-options]').querySelectorAll('input:checked')].map(input => input.value);
    $('[data-edit-filter="source"]').value = selected.join(',');
    $('[data-edit-source-caption]').textContent = selected.length === 1 ? selected[0] : selected.length ? `${selected.length} selected` : 'All sources';
  }
  $('[data-edit-sources-clear]').onclick = () => {
    $('[data-edit-source-options]').querySelectorAll('input').forEach(input => input.checked = false);
    syncEditorSources();
  };
  document.addEventListener('click', event => { if (!$('[data-edit-sources]').contains(event.target)) $('[data-edit-sources]').open = false; });
  $('[data-edit-sources]').addEventListener('keydown', event => {
    if (event.key === 'Escape' && event.currentTarget.open) {
      event.preventDefault(); event.stopPropagation(); event.currentTarget.open = false; event.currentTarget.querySelector('summary').focus();
    }
  });
  function addBlock(block = {days:[0,1,2,3,4],start:'09:00',end:'17:00'}) {
    const box = document.createElement('div'); box.className = 'workspace-time-block';
    const dayGroup = document.createElement('fieldset'); dayGroup.className = 'space-schedule-days';
    const legend = document.createElement('legend'); legend.textContent = 'Repeat on';
    const shortcuts = document.createElement('div'); shortcuts.className = 'space-day-shortcuts';
    const days = document.createElement('div'); days.className = 'workspace-day-options';
    const fullNames = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
    fullNames.forEach((name, day) => {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.value = day; input.checked = block.days.includes(day);
      input.setAttribute('aria-label', fullNames[day]);
      const text = document.createElement('span'); text.textContent = name;
      label.append(input, text); days.append(label);
    });
    function updateDays() {
      const selected = [...days.querySelectorAll('input:checked')].map(input => Number(input.value));
      days.querySelector('input').setCustomValidity(selected.length ? '' : 'Choose at least one day.');
      shortcuts.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.days === selected.join(','))));
    }
    for (const [name, selection] of [['Weekdays',[0,1,2,3,4]], ['Weekends',[5,6]], ['All week',[0,1,2,3,4,5,6]]]) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = name;
      button.dataset.days = selection.join(',');
      button.onclick = () => {
        days.querySelectorAll('input').forEach(input => input.checked = selection.includes(Number(input.value)));
        days.querySelector('input').dispatchEvent(new Event('change', {bubbles:true}));
      };
      shortcuts.append(button);
    }
    days.addEventListener('change', updateDays);
    updateDays(); dayGroup.append(legend, shortcuts, days);
    const times = document.createElement('div'); times.className = 'workspace-block-times';
    ['start','end'].forEach(key => {
      const label = document.createElement('label'), input = document.createElement('input');
      label.textContent = key === 'start' ? 'From' : 'To'; input.type = 'time'; input.value = block[key]; input.dataset.blockTime = key;
      label.append(input); times.append(label);
    });
    const remove = document.createElement('button'); remove.type = 'button'; remove.dataset.removeBlock = ''; remove.textContent = 'Remove block'; remove.onclick = () => box.remove();
    box.append(dayGroup, times, remove); $('[data-schedule-blocks]').append(box);
  }
  $('[data-add-block]').onclick = () => addBlock();
  function readSchedule() {
    return [...document.querySelectorAll('.workspace-time-block')].map(box => ({
      days:[...box.querySelectorAll('input[type="checkbox"]:checked')].map(input => Number(input.value)),
      start:box.querySelector('[data-block-time="start"]').value, end:box.querySelector('[data-block-time="end"]').value,
    }));
  }
  function readViewEditor() {
    const state = {...editTarget.state};
    document.querySelectorAll('[data-edit-filter]').forEach(input => state[input.dataset.editFilter] = input.dataset.editFilter === 'has_media' ? input.value === 'true' : ['rolling','page_size'].includes(input.dataset.editFilter) ? Number(input.value) : input.value);
    return state;
  }

})();
