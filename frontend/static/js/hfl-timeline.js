/* Cached evidence and action history for the Activity Corpus heatmap. */
(() => {
  const root = document.getElementById('followup-agenda');
  if (!root) return;
  document.querySelector('[data-day-ideas]').append(root);root.hidden=false;
  const actionsRoot=document.getElementById('timeline-actions');
  document.querySelector('[data-day-actions]').append(actionsRoot);actionsRoot.hidden=false;
  document.querySelector('[data-activity-day-menu]').append(document.getElementById('agenda-error'));
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
    for (const name of ['title', 'expected_outcome', 'notes', 'prompt', 'review_date', 'due_date', 'completion_note']) form.elements[name].value = item?.[name] || '';
    form.elements.status.value = desiredStatus || item?.status || 'open';
    document.getElementById('followup-state-label').hidden = !item;
    document.getElementById('followup-editor-title').textContent = item ? (desiredStatus === 'done' ? 'Complete actionable' : 'Edit actionable') : 'New actionable';
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
  let historySequence = 0;
  async function showHistory(item) {
    const ticket = ++historySequence;
    const list=document.getElementById('followup-history-items');list.replaceChildren(node('p','Loading history…'));historyDialog.showModal();
    try { const data=await api('/'+item.id+'/history'); if(ticket !== historySequence)return; list.replaceChildren(); data.history.forEach(row => {const el=node('section',null,'agenda-history-row');el.dataset.changedAt=row.changed_at;el.append(node('h3','Revision '+row.item.version+' · '+statusLabel(row.item.status)),node('p',new Date(row.changed_at).toLocaleString('en-SG',{timeZone:'Asia/Singapore'})+' SGT'),node('p',row.item.title),node('p','Expected outcome: '+row.item.expected_outcome),node('p','Review: '+(row.item.review_date||'Unscheduled')+' · Complete by: '+(row.item.due_date||'None')));if(row.item.prompt)el.append(node('h4','Prompt'),node('pre',row.item.prompt,'action-prompt'));if(row.item.notes)el.append(node('p',row.item.notes));if(row.item.completion_note)el.append(node('p','Outcome: '+row.item.completion_note));list.append(el);}); }
    catch(e){list.replaceChildren(node('p',e.message,'agenda-error'));}
    try {
      const events = await window.hflAgentBridge.events('actionable',item.id);
      if(ticket !== historySequence || !historyDialog.open)return;
      const revisions = Array.from(list.children);

      const combined = revisions.map(el=>({el,time:el.dataset.changedAt || ''}));
      events.forEach(event=>combined.push({el:window.hflAgentBridge.eventCard(event),time:event.created_at}));
      combined.sort((a,b)=>(Date.parse(b.time)||0)-(Date.parse(a.time)||0)); list.replaceChildren(...combined.map(row=>row.el));
    } catch(e) { list.append(node('p','Agent history unavailable: '+e.message,'agenda-error')); }
  }
  const statusLabel = value => ({in_progress:'In Progress',waiting:'In Progress'}[value] || value[0].toUpperCase()+value.slice(1));
  window.addEventListener('hfl:agent-updated',()=>load());
  function card(item) {
    const el=node('article',null,'agenda-card');el.dataset.overdue=String(item.overdue);el.dataset.followupId=item.id;
    const meta=node('div',null,'agenda-card-meta');const status=node('span',statusLabel(item.status),'action-status');status.dataset.status=item.status;meta.append(status);
    if(item.creation_mode==='automatic'){const badge=node('span','Automatic','action-event');badge.title=item.automatic_basis||'Created from a high-confidence idea after review';meta.append(badge);}
    if(item.review_date)meta.append(node('span','Review '+item.review_date));if(item.due_date)meta.append(node('span','Complete by '+item.due_date));
    if(item.events){
      const labels={source:'Source',planned:'Planned'};
      const seen=new Set();
      item.events.forEach(event=>{
        if (!['source','planned'].includes(event.kind)) return;
        const key=event.date+':'+event.kind;if(seen.has(key))return;seen.add(key);
        const date=new Date(event.date+'T12:00:00');
        const short=Number.isNaN(date.getTime())?event.date:new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short'}).format(date);
        const pill=node('span',(labels[event.kind]||event.kind)+' · '+short,'action-event');
        pill.title=(event.kind==='source'?'Original HFL entry':'Scheduled review or completion')+' · '+event.date;
        meta.append(pill);
      });
    }
    el.append(meta,node('h3',item.title),node('p',item.expected_outcome,'agenda-card-outcome'));
    if(item.prompt){const details=node('details');details.append(node('summary','Prompt'),node('pre',item.prompt,'action-prompt'));el.append(details);}
    if(item.notes || item.completion_note){const details=node('details');details.append(node('summary','Notes & outcome'));if(item.notes)details.append(node('p',item.notes));if(item.completion_note)details.append(node('p','Outcome: '+item.completion_note));el.append(details);}
    if(item.source){const evidence=node('div',null,'action-evidence-link');const a=node('a','Open HFL evidence ↗');a.href=evidenceUrl(item.source);a.target='_blank';a.rel='noopener';evidence.append(a);el.append(evidence);}
    const actions=node('div',null,'agenda-card-actions action-controls');
    actions.append(button('Edit',()=>openEditor(item)));
    if(!['done','dismissed'].includes(item.status)){
      actions.append(button('Dismiss',e=>patch(item,{status:'dismissed'},e.currentTarget)),button('Done',e=>patch(item,{status:'done'},e.currentTarget)));
    } if(item.status !== 'open') actions.append(button('Reopen',e=>patch(item,{status:'open'},e.currentTarget)));
    actions.append(button('History',()=>showHistory(item)));
    const resultsButton = button('Results',()=>window.hflAgentBridge.open('actionable',item.id,item.title));
    resultsButton.className = 'action-results-button';
    actions.append(resultsButton);
    el.append(actions);return el;
  }
  async function load() {
    const ticket=++sequence;error('agenda-error');
    try {
      const [data, periodData, markers] = await Promise.all([api('?closed='+closed), timelineApi('/period?'+new URLSearchParams({start:startInput.value,end:endInput.value})), timelineApi('/markers')]);
      if(ticket!==sequence)return;today=data.today;
      markerDays=markers.days;reconcilePeriodMarkers(periodData.items);paintMarkers();paintActionsIndicator(periodData.items);renderSuggestions(periodData);
      if(!document.getElementById('timeline-all').checked) {data.items=periodData.items.filter(item=>['done','dismissed'].includes(item.status)===closed).map(item=>({...item,group:'This period'}));data.total=data.items.length;}
      const list=document.getElementById('agenda-items');
      const expanded=new Set(Array.from(list.querySelectorAll('details[open]')).map(el=>el.closest('[data-followup-id]').dataset.followupId));
      list.replaceChildren();const groups=new Map();
      data.items.forEach(item=>{if(!groups.has(item.group)){const section=node('section',null,'agenda-group');section.dataset.group=item.group;const cards=node('div');section.append(node('h2',item.group),cards);list.append(section);groups.set(item.group,cards);}const el=card(item);if(expanded.has(item.id))el.querySelector('details')?.setAttribute('open','');groups.get(item.group).append(el);});
      document.getElementById('agenda-status').textContent=(data.total>data.items.length ? 'Showing '+data.items.length+' of '+data.total : data.total)+' '+(closed?'completed or dismissed':'open')+' follow-up'+(data.total===1?'':'s')+' · '+today+' SGT';
      const actionsPanel=document.getElementById('timeline-actions');
      const isEmpty=!data.items.length;
      actionsPanel.querySelector('.agenda-toolbar').hidden=!periodData.items.length;
      document.getElementById('agenda-status').hidden=isEmpty;
      actionsPanel.querySelector('.agenda-footnote').hidden=isEmpty;
      if(isEmpty){
        const empty=node('div',null,'agenda-empty agenda-empty-actions');
        const hasIdeas=periodData.suggestions.some(item=>item.status==='suggested');
        const future=startInput.value>today;
        const running=['queued','running'].includes(periodData.run?.state);
        empty.append(node('h2',closed&&periodData.items.length?'Nothing completed yet.':'No actions yet.'),node('p',closed&&periodData.items.length?'Completed and dismissed actions will appear here.':hasIdeas?'Choose an idea and make it actionable, or explore this period for more.':future?'Select today or a past day to explore its activity for ideas.':'Explore this period’s activity for ideas, then make one actionable.','agenda-description'));
        const showIdeas=()=>{const toggle=document.querySelector('[data-activity-menu-ideas]');if(toggle?.getAttribute('aria-expanded')!=='true')toggle?.click();};
        if(!closed||!periodData.items.length){
          if(hasIdeas)empty.append(button('View ideas',showIdeas));
          if(!future){const explore=button(running?'View analysis':'Explore ideas',()=>{showIdeas();if(!running)document.getElementById('timeline-explore').click();});explore.classList.add('agenda-empty-explore');empty.append(explore);}
        }
        list.append(empty);
      }
      window.dispatchEvent(new Event('hfl:timeline-rendered'));
    } catch(e){if(ticket===sequence){error('agenda-error',e.message);document.querySelector('#timeline-actions .agenda-toolbar').hidden=false;document.getElementById('agenda-status').hidden=false;document.getElementById('agenda-status').textContent='Could not load the agenda. Use Refresh to retry.';}}
  }
  async function timelineApi(path, options={}) {
    const response=await fetch('/hfl-corpus/timeline'+path,{...options,headers:{'Content-Type':'application/json'}});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Timeline unavailable.');return data;
  }
  function actionDotStatus(statuses) {
    return statuses.has('incomplete') ? 'incomplete' : ['open','active'].some(value => statuses.has(value)) ? 'open' : ['in_progress','waiting'].some(value => statuses.has(value)) ? 'in_progress' : statuses.has('done') ? 'done' : null;
  }
  function reconcilePeriodMarkers(items) {
    // Remote marker services may still summarize only scheduled actions.
    // The complete period response is authoritative for each selected day.
    for (const [date, marker] of Object.entries(markerDays)) {
      if (date < startInput.value || date > endInput.value) continue;
      const statuses = new Set(items.filter(item => item.events?.some(event => event.date === date)).map(item => item.status));
      marker.dot_status = actionDotStatus(statuses);
    }
  }
  function paintActionsIndicator(items = null) {
    const indicator = document.querySelector('[data-actions-indicator]');
    if (!indicator) return;
    const days = Object.entries(markerDays).filter(([day]) => day >= startInput.value && day <= endInput.value).map(([, marker]) => marker);
    const statuses = new Set(days.map(marker => marker.dot_status).filter(Boolean));
    // Include every displayed action, even when a scheduled marker already exists.
    // An incomplete historical action must take priority over a completed schedule.
    if (items) items.forEach(item => statuses.add(item.status));
    const status = actionDotStatus(statuses) || 'dismissed';
    const available = items ? items.length > 0 : days.some(marker => marker.planned.length || marker.actions.length);
    indicator.hidden = !available;
    indicator.dataset.timelineStatus = status;
    const label = 'Actions available · ' + ({open:'Open or active',in_progress:'In progress',incomplete:'Incomplete',done:'Done',dismissed:'Dismissed or historical'}[status]);
    indicator.setAttribute('aria-label', label);
    indicator.title = label;
  }
  function paintMarkers() {
    document.querySelectorAll('[data-activity-day]').forEach(day=>{
      const markers=markerDays[day.dataset.activityDay];
      day.toggleAttribute('data-timeline-planned', Boolean(markers?.dot_status));
      if(markers?.dot_status)day.dataset.timelineStatus=markers.dot_status;else delete day.dataset.timelineStatus;
      day.toggleAttribute('data-timeline-action', Boolean(markers?.actions.length));
      if(!day.dataset.timelineLabel)day.dataset.timelineLabel=day.getAttribute('aria-label')||day.dataset.activityDay;
      const suffix=markers ? `; ${markers.planned.length} scheduled${markers.dot_status ? ' · '+({open:'Open or active',in_progress:'In progress',incomplete:'Incomplete',done:'All done'}[markers.dot_status]) : ''}, ${markers.actions.length} linked actions` : '';
      day.setAttribute('aria-label',day.dataset.timelineLabel+suffix);day.title=day.dataset.timelineLabel+suffix;
    });
  }
  new MutationObserver(records=>{if(records.some(record=>Array.from(record.addedNodes).some(n=>n.nodeType===1&&(n.matches('[data-activity-day]')||n.querySelector('[data-activity-day]')))))paintMarkers();}).observe(document.body,{childList:true,subtree:true});
  function analysisStatus(state, title, detail) {
    const status=document.getElementById('timeline-run');status.dataset.state=state||'idle';
    status.setAttribute('aria-busy',String(['queued','running'].includes(state)));
    document.getElementById('timeline-run-title').textContent=title;
    document.getElementById('timeline-run-detail').textContent=detail||'';
    document.getElementById('timeline-run-detail').hidden=!detail;
  }
  function renderSuggestions(data) {
    const list=document.getElementById('timeline-suggestions');list.replaceChildren();
    const state=data.run?.state;
    const future=endInput.value>today;
    document.getElementById('timeline-explore').disabled=future||['queued','running'].includes(state);
    const result=data.run?.result||{};
    if(future)analysisStatus('idle','Planned period','Explore becomes available after activity is recorded.');
    else if(['queued','running'].includes(state))analysisStatus(state,state==='queued'?'Waiting to explore…':'Reviewing activity…','Checking entries and related evidence.');
    else if(state==='complete'){
      const checked=result.selected_entries;
      const date=new Date(data.run.updated_at);
      const reviewed=Number.isNaN(date.getTime())?'':new Intl.DateTimeFormat('en-SG',{day:'numeric',month:'short',year:'numeric',timeZone:'Asia/Singapore'}).format(date);
      analysisStatus('complete','Review complete',[checked!=null?`${checked} ${checked===1?'entry':'entries'} reviewed`:'',reviewed,result.bounded?'Partial coverage':'',result.automatic_actions?.state==='complete'?`${result.automatic_actions.created} actions created · ${result.automatic_actions.duplicates} duplicates skipped · ${result.automatic_actions.deferred} left as ideas`:result.automatic_actions?.message||''].filter(Boolean).join(' · '));
    } else if(['failed','interrupted'].includes(state))analysisStatus(state,'Review unfinished',result.message||'Try Explore again. Previous suggestions are kept.');
    else analysisStatus('idle','Ready to explore','Find ideas and follow-ups in this period’s activity.');
    clearTimeout(pollTimer);if(['queued','running'].includes(state))pollTimer=setTimeout(load,4000);
    const suggestions=data.suggestions.filter(item=>item.status==='suggested');
    if(!suggestions.length&&!['queued','running'].includes(state))list.append(node('p',state==='complete'?'No new suggestions from this review.':'No suggestions yet.','timeline-empty-message'));
    suggestions.forEach(item=>{
      const el=node('article',null,'agenda-card agenda-idea-card');
      el.append(node('p',(item.category==='missed_commitments' ? 'Possibly missed' : item.category.replaceAll('_',' '))+' · '+item.confidence+' confidence'+((item.analysis_status||'uncertain')==='uncertain' ? ' · Uncertain' : ''),'agenda-eyebrow'),node('h3',item.title),node('p',item.recommendation||item.expected_outcome));
      const details=node('details');details.append(node('summary','Evidence & completion check'),node('p',item.observation||''),node('p',item.resolution_check));
      if(item.automatic_review?.reason)details.append(node('p','Automatic action review: '+item.automatic_review.reason));
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
  window.addEventListener('hfl:timeline-period',e=>{startInput.value=e.detail.start;endInput.value=e.detail.end;paintActionsIndicator();document.getElementById('timeline-all').checked=false;load();});
  document.getElementById('timeline-explore').addEventListener('click',async e=>{
    const b=e.currentTarget;b.disabled=true;error('agenda-error');analysisStatus('queued','Starting review…','Checking entries and related evidence.');
    try{await timelineApi('/explore',{method:'POST',body:JSON.stringify({start:startInput.value,end:endInput.value})});await load();}catch(err){error('agenda-error',err.message);analysisStatus('failed','Could not start review','Try Explore again.');b.disabled=false;}
  });
  document.getElementById('followup-new')?.addEventListener('click',()=>openEditor());
  window.addEventListener('hfl:create-action',event=>{
    openEditor();
    form.elements.due_date.value = event.detail?.date || '';
  });
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
    finally{busy=false;save.disabled=false;save.textContent='Save';}
  });
  timelineApi('/markers').then(data=>{markerDays=data.days;paintMarkers();}).catch(()=>{});
  window.addEventListener('hfl:timeline-close',()=>{clearTimeout(pollTimer);++sequence;});
  const params=new URLSearchParams(location.search);
  if(params.has('source_entry') && params.has('source_path')){
    timelineApi('/source?'+new URLSearchParams({path:params.get('source_path'),entry_id:params.get('source_entry')})).then(data=>{openEditor();source=data;showEvidence();form.elements.title.value=data.title.slice(0,200);form.elements.expected_outcome.focus();const url=new URL(location.href);url.searchParams.delete('source_path');url.searchParams.delete('source_entry');history.replaceState(null,'',url);}).catch(e=>error('agenda-error',e.message));
  }
})();
