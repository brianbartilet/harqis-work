/* Cached evidence and action history for the Activity Corpus heatmap. */
(() => {
  const root = document.getElementById('followup-agenda');
  if (!root) return;
  const editor = document.getElementById('followup-editor');
  const form = document.getElementById('followup-form');
  const historyDialog = document.getElementById('followup-history');
  let suggestionId = null, markerDays = {}, pollTimer;
  const startInput = document.getElementById('timeline-start'), endInput = document.getElementById('timeline-end');
  startInput.value = endInput.value = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(Date.now()-86400000));
  const initialParams=new URLSearchParams(location.search);
  if(initialParams.get('date_from'))startInput.value=initialParams.get('date_from');
  if(initialParams.get('date_to'))endInput.value=initialParams.get('date_to');
  let closed = false, editing = null, source = null, requestId = '', today = '', busy = false, sequence = 0;
  const node = (tag, text, className) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (className) el.className = className; return el; };
  const error = (id, message = '') => { const el = document.getElementById(id); el.textContent = message; el.hidden = !message; };
  async function api(path, options = {}) {
    const response = await fetch('/hfl-corpus/timeline/items' + path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
    let data; try { data = await response.json(); } catch (_) { throw new Error('The server returned an unreadable response. Try again.'); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not save this follow-up. Check the fields and try again.');
    return data;
  }
  function evidenceUrl(value) { return '/hfl-corpus/timeline/evidence?' + new URLSearchParams({path: value.path, entry_id: value.entry_id}); }
  function stateFields() { document.getElementById('followup-completion-label').hidden = form.elements.status.value !== 'done'; }
  function openEditor(item = null, desiredStatus = '') {
    suggestionId = null; editing = item; source = item?.source || null; requestId = crypto.randomUUID();
    form.reset();
    for (const name of ['title', 'expected_outcome', 'notes', 'review_date', 'due_date', 'completion_note']) form.elements[name].value = item?.[name] || '';
    form.elements.status.value = desiredStatus || item?.status || 'open';
    document.getElementById('followup-state-label').hidden = !item;
    document.getElementById('followup-editor-title').textContent = item ? (desiredStatus === 'done' ? 'Complete follow-up' : 'Edit follow-up') : 'New follow-up';
    showEvidence(); stateFields(); error('followup-save-error'); editor.showModal();
    form.elements.title.focus({preventScroll:true});
  }
  function showEvidence() {
    const el = document.getElementById('followup-evidence'); el.replaceChildren(); el.hidden = !source;
    if (source) { el.append(node('span','From HFL: ')); const a = node('a', source.title || source.entry_id); a.href = evidenceUrl(source); a.target='_blank'; a.rel='noopener'; el.append(a); }
  }
  function button(label, fn) { const b = node('button', label); b.type='button'; b.addEventListener('click',fn); return b; }
  async function patch(item, changes, trigger) {
    trigger.disabled = true; error('agenda-error');
    try { await api('/'+item.id, {method:'PATCH',body:JSON.stringify({version:item.version,...changes})}); await load(); }
    catch (e) { error('agenda-error',e.message); } finally {trigger.disabled=false;}
  }
  async function showHistory(item) {
    const list=document.getElementById('followup-history-items');list.replaceChildren(node('p','Loading history…'));historyDialog.showModal();
    try { const data=await api('/'+item.id+'/history'); list.replaceChildren(); data.history.forEach(row => {const el=node('section',null,'agenda-history-row');el.append(node('h3','Revision '+row.item.version+' · '+row.item.status),node('p',new Date(row.changed_at).toLocaleString('en-SG',{timeZone:'Asia/Singapore'})+' SGT'),node('p',row.item.title),node('p','Expected outcome: '+row.item.expected_outcome),node('p','Review: '+(row.item.review_date||'Unscheduled')+' · Deadline: '+(row.item.due_date||'None')));if(row.item.notes)el.append(node('p',row.item.notes));if(row.item.completion_note)el.append(node('p','Outcome: '+row.item.completion_note));list.append(el);}); }
    catch(e){list.replaceChildren(node('p',e.message,'agenda-error'));}
  }
  function card(item) {
    const el=node('article',null,'agenda-card');el.dataset.overdue=String(item.overdue);el.dataset.followupId=item.id;
    const meta=node('div',null,'agenda-card-meta');meta.append(node('span',item.status));
    if(item.review_date)meta.append(node('span','Review '+item.review_date));if(item.due_date)meta.append(node('span','Due '+item.due_date));
    if(item.events)meta.append(node('span',item.events.map(event=>event.date+' '+event.kind.replaceAll('-',' ')).join(' · ')));
    el.append(meta,node('h3',item.title),node('p',item.expected_outcome,'agenda-card-outcome'));
    if(item.notes || item.completion_note){const details=node('details');details.append(node('summary','Notes & outcome'));if(item.notes)details.append(node('p',item.notes));if(item.completion_note)details.append(node('p','Outcome: '+item.completion_note));el.append(details);}
    const actions=node('div',null,'agenda-card-actions');
    if(item.source){const a=node('a','Open HFL evidence ↗');a.href=evidenceUrl(item.source);a.target='_blank';a.rel='noopener';actions.append(a);}
    actions.append(button('Edit',()=>openEditor(item)),button('History',()=>showHistory(item)));
    if(!['done','dismissed'].includes(item.status)){actions.append(button('Done',()=>openEditor(item,'done')),button('Review tomorrow',e=>{const date=new Date(today+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+1);patch(item,{review_date:date.toISOString().slice(0,10)},e.currentTarget);}));actions.append(button('Dismiss',e=>patch(item,{status:'dismissed'},e.currentTarget)));}
    else actions.append(button('Reopen',e=>patch(item,{status:'open'},e.currentTarget)));
    el.append(actions);return el;
  }
  async function load() {
    const ticket=++sequence;error('agenda-error');
    try {
      const [data, periodData, markers] = await Promise.all([api('?closed='+closed), timelineApi('/period?'+new URLSearchParams({start:startInput.value,end:endInput.value})), timelineApi('/markers')]);
      if(ticket!==sequence)return;today=data.today;
      markerDays=markers.days;paintMarkers();renderSuggestions(periodData);
      if(!document.getElementById('timeline-all').checked) {data.items=periodData.items.filter(item=>['done','dismissed'].includes(item.status)===closed).map(item=>({...item,group:'This period'}));data.total=data.items.length;}
      const list=document.getElementById('agenda-items');
      const expanded=new Set(Array.from(list.querySelectorAll('details[open]')).map(el=>el.closest('[data-followup-id]').dataset.followupId));
      list.replaceChildren();const groups=new Map();
      data.items.forEach(item=>{if(!groups.has(item.group)){const section=node('section',null,'agenda-group');section.dataset.group=item.group;const cards=node('div');section.append(node('h2',item.group),cards);list.append(section);groups.set(item.group,cards);}const el=card(item);if(expanded.has(item.id))el.querySelector('details')?.setAttribute('open','');groups.get(item.group).append(el);});
      document.getElementById('agenda-status').textContent=(data.total>data.items.length ? 'Showing '+data.items.length+' of '+data.total : data.total)+' '+(closed?'completed or dismissed':'open')+' follow-up'+(data.total===1?'':'s')+' · '+today+' SGT';
      if(!data.items.length){const empty=node('div',null,'agenda-empty');empty.append(node('h2',closed?'No completed follow-ups yet.':'Give a memory a next step.'),node('p',closed?'Completed and dismissed items stay here with their history.':'Choose a suggestion above or make an HFL entry actionable.','agenda-description'));list.append(empty);}
    } catch(e){if(ticket===sequence){error('agenda-error',e.message);document.getElementById('agenda-status').textContent='Could not load the agenda. Use Refresh to retry.';}}
  }
  async function timelineApi(path, options={}) {
    const response=await fetch('/hfl-corpus/timeline'+path,{...options,headers:{'Content-Type':'application/json'}});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Timeline unavailable.');return data;
  }
  function paintMarkers() {
    document.querySelectorAll('[data-activity-day]').forEach(day=>{
      const markers=markerDays[day.dataset.activityDay];
      day.toggleAttribute('data-timeline-planned', Boolean(markers?.planned.length));
      day.toggleAttribute('data-timeline-action', Boolean(markers?.actions.length));
      if(!day.dataset.timelineLabel)day.dataset.timelineLabel=day.getAttribute('aria-label')||day.dataset.activityDay;
      const suffix=markers ? `; ${markers.planned.length} planned, ${markers.actions.length} linked actions` : '';
      day.setAttribute('aria-label',day.dataset.timelineLabel+suffix);day.title=day.dataset.timelineLabel+suffix;
    });
  }
  new MutationObserver(records=>{if(records.some(record=>Array.from(record.addedNodes).some(n=>n.nodeType===1&&(n.matches('[data-activity-day]')||n.querySelector('[data-activity-day]')))))paintMarkers();}).observe(document.body,{childList:true,subtree:true});
  function renderSuggestions(data) {
    const list=document.getElementById('timeline-suggestions');list.replaceChildren();
    const state=data.run?.state;
    const future=endInput.value>today;
    document.getElementById('timeline-explore').disabled=future||['queued','running'].includes(state);
    document.getElementById('timeline-run').textContent=state ? `Analysis: ${state} · ${data.run.updated_at.slice(0,10)}. ${data.run.result?.message||''} ${data.run.result?.selected_entries != null ? data.run.result.selected_entries+' entries checked.' : ''} ${data.run.result?.bounded ? 'Entry limit reached; coverage is partial.' : ''}` : 'No cached analysis for this exact period. Daily analysis covers yesterday; explore older dates when useful.';
    if(future)document.getElementById('timeline-run').textContent='Planned dates have no observed activity to analyze.';
    clearTimeout(pollTimer);if(['queued','running'].includes(state))pollTimer=setTimeout(load,4000);
    const suggestions=data.suggestions.filter(item=>item.status==='suggested');
    if(!suggestions.length)list.append(node('p','No cached suggestions for this period.','agenda-description'));
    suggestions.forEach(item=>{
      const el=node('article',null,'agenda-card');
      el.append(node('p',(item.category==='missed_commitments' ? 'Possibly missed' : item.category.replaceAll('_',' '))+' · '+item.confidence+' confidence'+((item.analysis_status||'uncertain')==='uncertain' ? ' · Uncertain' : ''),'agenda-eyebrow'),node('h3',item.title),node('p',item.recommendation||item.expected_outcome));
      const details=node('details');details.append(node('summary','Evidence & completion check'),node('p',item.observation||''),node('p',item.resolution_check));
      item.evidence.forEach(ref=>{const a=node('a',ref.date+' · '+ref.title);a.href=evidenceUrl(ref);a.target='_blank';a.rel='noopener';const p=node('p');p.append(a);details.append(p);});el.append(details);
      const actions=node('div',null,'agenda-card-actions');
      actions.append(button('Make actionable',()=>{openEditor();suggestionId=item.id;source=item.source;showEvidence();form.elements.title.value=item.title.slice(0,200);form.elements.expected_outcome.value=item.expected_outcome;}),button('Dismiss',async e=>{e.currentTarget.disabled=true;try{await timelineApi('/suggestions/'+item.id+'/dismiss',{method:'POST'});await load();}catch(err){error('agenda-error',err.message);e.currentTarget.disabled=false;}}));
      el.append(actions);list.append(el);
    });
    const pending=data.receipts.filter(receipt=>receipt.state==='pending'&&data.items.some(item=>item.id===receipt.followup_id));
    if(data.receipts.some(receipt=>receipt.state==='preview'&&data.items.some(item=>item.id===receipt.followup_id)))list.append(node('p','Preview completion saved locally. No entry was submitted to the corpus.','agenda-description'));
    if(pending.length)list.append(node('p',`${pending.length} completion record(s) awaiting HFL delivery; the daily job will retry.`,'agenda-description'));
  }
  document.getElementById('timeline-period-form').addEventListener('submit',e=>{e.preventDefault();load();});
  document.getElementById('timeline-all').addEventListener('change',load);
  window.addEventListener('hfl:timeline-period',e=>{startInput.value=e.detail.start;endInput.value=e.detail.end;document.getElementById('timeline-all').checked=false;load();if(e.detail.scroll)root.scrollIntoView({behavior:'smooth',block:'start'});});
  document.getElementById('timeline-explore').addEventListener('click',async e=>{
    const b=e.currentTarget;b.disabled=true;error('agenda-error');
    try{await timelineApi('/explore',{method:'POST',body:JSON.stringify({start:startInput.value,end:endInput.value})});await load();}catch(err){error('agenda-error',err.message);}finally{b.disabled=false;}
  });
  document.getElementById('followup-new')?.addEventListener('click',()=>openEditor());
  document.getElementById('agenda-refresh').addEventListener('click',load);
  document.querySelectorAll('[data-agenda-closed]').forEach(b=>b.addEventListener('click',()=>{closed=b.dataset.agendaClosed==='true';document.querySelectorAll('[data-agenda-closed]').forEach(v=>v.setAttribute('aria-pressed',String(v===b)));load();}));
  document.querySelectorAll('[data-agenda-close]').forEach(b=>b.addEventListener('click',()=>{if(!busy)editor.close();}));
  editor.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  document.getElementById('followup-history-close').addEventListener('click',()=>historyDialog.close());
  form.elements.status.addEventListener('change',stateFields);
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(busy)return;busy=true;error('followup-save-error');
    const save=form.querySelector('[type=submit]');save.disabled=true;save.textContent='Saving…';
    const payload=Object.fromEntries(new FormData(form));
    if(editing)payload.version=editing.version;else{payload.request_id=requestId;payload.source=source;if(suggestionId)payload.suggestion_id=suggestionId;}
    try {await api(editing?'/'+editing.id:'',{method:editing?'PATCH':'POST',body:JSON.stringify(payload)});editor.close();await load();}
    catch(err){error('followup-save-error',err.message);}
    finally{busy=false;save.disabled=false;save.textContent='Save follow-up';}
  });
  load();
  const params=new URLSearchParams(location.search);
  if(params.has('source_entry') && params.has('source_path')){
    timelineApi('/source?'+new URLSearchParams({path:params.get('source_path'),entry_id:params.get('source_entry')})).then(data=>{openEditor();source=data;showEvidence();form.elements.title.value=data.title.slice(0,200);form.elements.expected_outcome.focus();const url=new URL(location.href);url.searchParams.delete('source_path');url.searchParams.delete('source_entry');history.replaceState(null,'',url);}).catch(e=>error('agenda-error',e.message));
  }
})();
