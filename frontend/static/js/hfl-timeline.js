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
  const attachments = new window.HflInputAttachments(form.querySelector('[data-input-editor]'), 'actionable');
  const historyDialog = document.getElementById('followup-history');
  let suggestionId = null, markerDays = {}, pollTimer;
  const startInput = document.getElementById('timeline-start'), endInput = document.getElementById('timeline-end');
  startInput.value = endInput.value = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(Date.now()-86400000));
  const initialParams=new URLSearchParams(location.search);
  if(initialParams.get('date_from'))startInput.value=initialParams.get('date_from');
  if(initialParams.get('date_to'))endInput.value=initialParams.get('date_to');
  let editorState;
  let editing = null, source = null, requestId = '', today = '', busy = false, sequence = 0;
  const node = (tag, text, className) => { const el = document.createElement(tag); if (text != null) el.textContent = text; if (className) el.className = className; return el; };
  const error = (id, message = '') => {
    const el = document.getElementById(id); el.textContent = message; el.hidden = !message;
    if(id==='agenda-error' && document.querySelector('[data-actions-page]')) {
      const boardError=document.querySelector('[data-board-error]');
      if(boardError){boardError.textContent=message;boardError.hidden=!message;}
    }
  };
  async function api(path, options = {}) {
    const response = await fetch('/hfl-corpus/timeline/items' + (path.startsWith('?') ? scoped(path) : path), { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
    let data; try { data = await response.json(); } catch (_) { throw new Error('The server returned an unreadable response. Try again.'); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not save this follow-up. Check the fields and try again.');
    return data;
  }
  function scoped(path) {
    const url = new URL('/hfl-corpus/timeline'+path, location.origin);
    const current = new URLSearchParams(location.search);
    for (const key of ['scope','q','source','date_field','date_from','date_to','rolling']) if(current.has(key))url.searchParams.set(key,current.get(key));
    return path.split('?')[0]+'?'+url.searchParams;
  }
  function evidenceUrl(value) { return '/hfl-corpus/timeline/evidence?' + new URLSearchParams({path: value.path, entry_id: value.entry_id}); }
  function stateFields() { document.getElementById('followup-completion-label').hidden = form.elements.status.value !== 'done'; }
  function openEditor(item = null, desiredStatus = '') {
    suggestionId = null; editing = item; source = item?.source || null; requestId = crypto.randomUUID();
    form.reset();
    window.HflActionAgentSettings(form, item?.id);
    form.querySelectorAll('.action-triage').forEach(section => { section.open = false; });
    attachments.reset(item?.id);
    window.HflIntentFields(form,item||{});
    for (const name of ['title', 'body', 'expected_outcome', 'notes', 'prompt', 'review_date', 'due_date', 'completion_note', 'matrix', 'matrix_confidence', 'matrix_reason']) form.elements[name].value = item?.[name] || '';
    form.elements.body.value = window.HflObjectDescription(item || {});
    form.elements.hide_ticked.checked = !!item?.hide_ticked;
    window.hflActionChecklists?.set(item?.checklists || []);
    form.elements.status.value = desiredStatus || item?.status || 'open';
    document.getElementById('followup-state-label').hidden = !item;
    document.getElementById('followup-editor-title').textContent = item ? (desiredStatus === 'done' ? 'Complete action' : 'Edit action') : 'New action';
    showEvidence(); stateFields(); error('followup-save-error'); editor.showModal();
    editorState = window.HflBindEditor(editor, form, {
      creationLabel: 'Action',
      snapshot: () => JSON.stringify({fields:window.HflIntentValues(form),checklists:window.hflActionChecklists.value,files:attachments.pending.map(f=>[f.name,f.size,f.lastModified]),removed:[...attachments.removed]}),
      exists: () => !!editing, valid: () => form.checkValidity(),
      lock: value => { busy=value; attachments.root.inert=value; form.querySelector('[type=submit]').disabled=value; },
      save: saveEditor,
    });
    window.hflActionChecklists.options.addToBoard = async (list, task) => { try { await editorState.flush(); await window.HflIdeas.addToBoard('actionable',editing,list,task); } catch(e) { error('followup-save-error',e.message); } };
    window.hflActionChecklists.options.convert = async (listId, itemId) => {
      try { await editorState.flush(); const parent = editing; editor.close(); await window.HflIdeas.createChecklistAction(parent, listId, itemId); }
      catch(e) { error('followup-save-error',e.message); }
    };
    window.hflActionChecklists.render();
    form.querySelector('[type=submit]').textContent = 'Create';
    form.querySelector('[type=submit]').hidden = !!item;
    if(item)window.HflEditorLocation('actionable',item.id);
    form.elements.title.focus({preventScroll:true});
  }
  function showEvidence() {
    const el = document.getElementById('followup-evidence'); el.replaceChildren(); el.hidden = !source;
    if (source) { el.append(node('span','From HFL: ')); const a = node('a', source.title || source.entry_id); a.href = evidenceUrl(source); a.target='_blank'; a.rel='noopener'; el.append(a); }
  }
  function button(label, fn) { const b = node('button', label); b.type='button'; b.addEventListener('click',fn); return b; }
  async function patch(item, changes, trigger) {
    trigger.disabled = true; error('agenda-error');
    try { await api('/'+item.id, {method:'PATCH',body:JSON.stringify({version:item.version,...changes})}); await load(); window.dispatchEvent(new Event('hfl:actions-updated')); }
    catch (e) { error('agenda-error',e.message); window.dispatchEvent(new CustomEvent('hfl:action-error',{detail:e.message})); } finally {trigger.disabled=false;}
  }
  let historySequence = 0;
  async function showHistory(item) {
    const ticket = ++historySequence;
    const list=document.getElementById('followup-history-items');list.replaceChildren(node('p','Loading history…'));historyDialog.showModal();
    try { const data=await api('/'+item.id+'/history'); if(ticket !== historySequence)return; list.replaceChildren(); data.history.forEach(row => {const el=node('section',null,'agenda-history-row');el.dataset.changedAt=row.changed_at;el.append(node('h3','Revision '+row.item.version+' · '+statusLabel(row.item.status)),node('p',new Date(row.changed_at).toLocaleString('en-SG',{timeZone:'Asia/Singapore'})+' SGT'),node('p',row.item.title),node('p','Expected outcome: '+row.item.expected_outcome),node('p','Review: '+(row.item.review_date||'Unscheduled')+' · Complete by: '+(row.item.due_date||'None')));el.append(node('p','Matrix: '+(row.item.matrix||'Unclassified')+(row.item.matrix_confidence?' · '+row.item.matrix_confidence+' confidence':'')));if(row.item.matrix_reason)el.append(node('p',row.item.matrix_reason));if(row.item.prompt)el.append(node('h4','Initial prompt'),node('pre',row.item.prompt,'action-prompt'));if(row.item.notes)el.append(node('p',row.item.notes));if(row.item.completion_note){const output=node('div',null,'markdown-body');if(row.item.completion_note_html)output.innerHTML=row.item.completion_note_html;else output.textContent=row.item.completion_note;el.append(node('h4','Outcome'),output);}list.append(el);}); }
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
  const statusLabel = value => ({open:'In Review',active:'Ready',in_progress:'In Progress',waiting:'In Progress'}[value] || value[0].toUpperCase()+value.slice(1));
  window.addEventListener('hfl:agent-updated',()=>load());
  const priority = item => [({done:1,dismissed:2}[item.status]||0),({Q1:0,Q2:1,Q3:2,Q4:3}[item.matrix]??4),[item.due_date,item.review_date].filter(Boolean).sort()[0]||'9999',item.due_date||'9999',item.created_at||'',item.id].join('|');
  function card(item) {
    const el=node('article',null,'agenda-card');el.dataset.overdue=String(item.overdue);el.dataset.followupId=item.id;
    const meta=node('div',null,'agenda-card-meta');const status=node('span',statusLabel(item.status),'action-status');status.dataset.status=item.status;meta.append(status);
    const matrix=node('span',item.matrix ? item.matrix+(item.matrix_confidence ? ' · '+item.matrix_confidence+' confidence' : '') : 'Matrix unclassified','action-matrix');matrix.title=item.matrix_reason||'Put first things first';meta.append(matrix);
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
    for(const sourceName of item.sources || [])meta.append(node('span',sourceName,'action-source'));
    el.append(meta,node('h3',item.title));
    window.HflChecklistCover?.(el, item, async checklists => {
      window.dispatchEvent(new CustomEvent('hfl:action-saving',{detail:{saving:true}}));
      try { await api('/'+item.id, {method:'PATCH',body:JSON.stringify({version:item.version,checklists})}); await load(); }
      finally {
        window.dispatchEvent(new CustomEvent('hfl:action-saving',{detail:{saving:false}}));
        window.dispatchEvent(new Event('hfl:actions-updated'));
      }
    }, () => openEditor(item), (list, task) => window.HflIdeas.createChecklistAction(item, list.id, task.id));
    const outcome=node('details');outcome.append(node('summary','Expected outcome'),node('p',item.expected_outcome,'agenda-card-outcome'));el.append(outcome);
    if(item.prompt){const details=node('details');details.append(node('summary','Initial prompt'),node('pre',item.prompt,'action-prompt'));el.append(details);}
    if(item.notes || item.completion_note){const details=node('details');details.append(node('summary','Notes & outcome'));if(item.notes)details.append(node('p',item.notes));if(item.completion_note)details.append(node('p','Outcome: '+item.completion_note));el.append(details);}
    if(item.source){const evidence=node('div',null,'action-evidence-link');const available=item.evidence_available!==false;const a=node(available?'a':'span','Open HFL evidence ↗');if(available){a.href=evidenceUrl(item.source);a.target='_blank';a.rel='noopener';}else{a.setAttribute('aria-disabled','true');a.title='No linked evidence entry is available';}evidence.append(a);el.append(evidence);}
    const actions=node('div',null,'agenda-card-actions action-controls');
    const management=node('div',null,'action-management-controls');
    const views=node('div',null,'action-view-controls');
    actions.append(management,views);
    management.append(button('Edit',()=>openEditor(item)));
    if(!['done','dismissed'].includes(item.status)){
      management.append(button('Dismiss',e=>patch(item,{status:'dismissed'},e.currentTarget)));
      if(item.status !== 'incomplete') management.append(button('Done',e=>patch(item,{status:'done'},e.currentTarget)));
    } if(!['open','in_progress','waiting'].includes(item.status)) management.append(button('In Review',e=>patch(item,{status:'open'},e.currentTarget)));
    management.append(button('History',()=>showHistory(item)));
    const resultsButton = button('Agents',()=>window.hflAgentBridge.open('actionable',item.id,item.title));
    resultsButton.className = 'action-results-button';
    views.append(resultsButton);
    const connections = button('Connections', () => window.HflActionConnections.open(item, connections));
    connections.className = 'action-connections-button';
    views.append(connections);
    el.append(actions);return el;
  }
  async function load() {
    const ticket=++sequence;error('agenda-error');
    try {
      const [data, periodData, markers] = await Promise.all([api('?include_closed=true'), timelineApi('/period?'+new URLSearchParams({start:startInput.value,end:endInput.value})), timelineApi('/markers')]);
      if(ticket!==sequence)return;today=data.today;
      markerDays=markers.days;reconcilePeriodMarkers(periodData.items);paintMarkers();paintActionsIndicator(periodData.items);renderSuggestions(periodData);
      if(!document.getElementById('timeline-all').checked) {data.items=periodData.items;data.total=data.items.length;}
      const list=document.getElementById('agenda-items');
      const expanded=new Set(Array.from(list.querySelectorAll('details[open]')).map(el=>el.closest('[data-followup-id]').dataset.followupId+':'+el.querySelector('summary').textContent));
      list.replaceChildren();const groups=new Map();
      data.items.sort((a,b)=>priority(a).localeCompare(priority(b)));
      data.items=data.items.map(item=>({...item,group:item.status==='done'?'Completed':item.status==='dismissed'?'Dismissed':'To do'}));
      data.items.forEach(item=>{if(!groups.has(item.group)){const section=node('section',null,'agenda-group');section.dataset.group=item.group;const cards=node('div');section.append(node('h2',item.group),cards);list.append(section);groups.set(item.group,cards);}const el=card(item);el.querySelectorAll('details').forEach(details=>details.open=expanded.has(item.id+':'+details.querySelector('summary').textContent));groups.get(item.group).append(el);});
      document.getElementById('agenda-status').textContent=(data.total>data.items.length ? 'Showing '+data.items.length+' of '+data.total : data.total)+' action'+(data.total===1?'':'s')+' · '+today+' SGT';
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
        empty.append(node('h2','No actions yet.'),node('p',future?'Select today or a past day to explore its activity for ideas.':'Explore this period’s activity for ideas, then create an action.','agenda-description'));
        const showIdeas=()=>{const toggle=document.querySelector('[data-activity-menu-ideas]');if(toggle?.getAttribute('aria-expanded')!=='true')toggle?.click();};
        {
          if(hasIdeas)empty.append(button('View ideas',showIdeas));
          if(!future){const explore=button(running?'View analysis':'Explore ideas',()=>{showIdeas();if(!running)document.getElementById('timeline-explore').click();});explore.classList.add('agenda-empty-explore');empty.append(explore);}
        }
        list.append(empty);
      }
      window.dispatchEvent(new Event('hfl:timeline-rendered'));
    } catch(e){if(ticket===sequence){error('agenda-error',e.message);document.querySelector('#timeline-actions .agenda-toolbar').hidden=false;document.getElementById('agenda-status').hidden=false;document.getElementById('agenda-status').textContent='Could not load the agenda. Use Refresh to retry.';}}
  }
  async function timelineApi(path, options={}) {
    const response=await fetch('/hfl-corpus/timeline'+(['/markers','/period'].includes(path.split('?')[0])?scoped(path):path),{...options,headers:{'Content-Type':'application/json'}});
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
    const label = 'Actions available · ' + ({open:'In Review / Ready',in_progress:'In Progress',incomplete:'Incomplete',done:'Done',dismissed:'Dismissed or historical'}[status]);
    indicator.setAttribute('aria-label', label);
    indicator.title = label;
  }
  function paintMarkers() {
    if (window.HflActivityIndicators) { window.HflActivityIndicators.setActions(markerDays); return; }
    document.querySelectorAll('[data-activity-day]').forEach(day=>{
      const markers=markerDays[day.dataset.activityDay];
      day.toggleAttribute('data-timeline-planned', Boolean(markers?.dot_status));
      if(markers?.dot_status)day.dataset.timelineStatus=markers.dot_status;else delete day.dataset.timelineStatus;
      day.toggleAttribute('data-timeline-action', Boolean(markers?.actions.length));
      if(!day.dataset.timelineLabel)day.dataset.timelineLabel=day.getAttribute('aria-label')||day.dataset.activityDay;
      const suffix=markers ? `; ${markers.planned.length} scheduled${markers.dot_status ? ' · '+({open:'In Review / Ready',in_progress:'In Progress',incomplete:'Incomplete',done:'All done'}[markers.dot_status]) : ''}, ${markers.actions.length} linked actions` : '';
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
    document.getElementById('agenda-explore').disabled=document.getElementById('timeline-explore').disabled;
    for (const id of ['timeline-explore', 'agenda-explore']) {
      const explore = document.getElementById(id);
      explore.dataset.unavailable = String(future);
      explore.title = future ? 'Explore ideas is available for today and past dates.' : '';
    }
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
      el.append(node('p',(item.category==='missed_commitments' ? 'Possibly missed' : (item.category||'manual idea').replaceAll('_',' '))+(item.confidence?' · '+item.confidence+' confidence':'')+((item.analysis_status||'uncertain')==='uncertain' ? ' · Uncertain' : ''),'agenda-eyebrow'),node('h3',item.title),node('p',item.body||item.description||item.recommendation||item.expected_outcome));
      if(item.matrix)el.append(node('p',item.matrix+' · '+(item.matrix_confidence||'unassessed')+' matrix confidence'+(item.matrix_reason?' — '+item.matrix_reason:''),'agenda-description'));
      const details=node('details');details.append(node('summary','Evidence & completion check'),node('p',item.observation||''),node('p',item.resolution_check));
      if(item.automatic_review?.reason)details.append(node('p','Automatic action review: '+item.automatic_review.reason));
      (item.evidence||[]).forEach(ref=>{const a=node('a',ref.date+' · '+ref.title);a.href=evidenceUrl(ref);a.target='_blank';a.rel='noopener';const p=node('p');p.append(a);details.append(p);});el.append(details);
      const actions=node('div',null,'agenda-card-actions');
      window.HflChecklistCover?.(el, item, async checklists => { await window.HflIdeas.api('/objects/'+item.id, 'PATCH', {version:item.version,checklists}); await load(); window.dispatchEvent(new Event('hfl:ideas-updated')); }, () => window.HflIdeas.editIdea(item.id));
      actions.append(button('Add to board',()=>window.HflIdeas.addToBoard('idea',item)),button('Create action',()=>window.HflIdeas.convert(item.id)),button('Edit idea',()=>window.HflIdeas.editIdea(item.id)),button('Dismiss',async e=>{e.currentTarget.disabled=true;try{await timelineApi('/suggestions/'+item.id+'/dismiss',{method:'POST'});await load();}catch(err){error('agenda-error',err.message);e.currentTarget.disabled=false;}}));
      el.append(actions);list.append(el);
    });
    const pending=data.receipts.filter(receipt=>receipt.state==='pending'&&data.items.some(item=>item.id===receipt.followup_id));
    if(data.receipts.some(receipt=>receipt.state==='preview'&&data.items.some(item=>item.id===receipt.followup_id)))list.append(node('p','Preview completion saved locally. No entry was submitted to the corpus.','agenda-description'));
    if(pending.length)list.append(node('p',`${pending.length} completion record(s) awaiting HFL delivery; the daily job will retry.`,'agenda-description'));
  }
  document.getElementById('timeline-period-form').addEventListener('submit',e=>{e.preventDefault();load();});
  document.getElementById('timeline-all').addEventListener('change',load);
  window.addEventListener('hfl:ideas-updated',load);
  window.addEventListener('hfl:timeline-period',e=>{startInput.value=e.detail.start;endInput.value=e.detail.end;paintActionsIndicator();document.getElementById('timeline-all').checked=false;load();});
  document.getElementById('timeline-explore').addEventListener('click',async e=>{
    const b=e.currentTarget;b.disabled=true;error('agenda-error');analysisStatus('queued','Starting review…','Checking entries and related evidence.');
    try{await timelineApi('/explore',{method:'POST',body:JSON.stringify({start:startInput.value,end:endInput.value})});await load();}catch(err){error('agenda-error',err.message);analysisStatus('failed','Could not start review','Try Explore again.');b.disabled=false;}
  });
  document.getElementById('followup-new')?.addEventListener('click',()=>openEditor());
  document.querySelector('[data-create-action-open]')?.addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('hfl:create-action'));
  });
  window.addEventListener('hfl:create-action',event=>{
    openEditor();
    form.elements.due_date.value = event.detail?.date || '';
  });
  document.getElementById('agenda-refresh').addEventListener('click',load);
  document.getElementById('agenda-explore').addEventListener('click',()=>{const toggle=document.querySelector('[data-activity-menu-ideas]');if(toggle?.getAttribute('aria-expanded')!=='true')toggle?.click();document.getElementById('timeline-explore').click();});
  document.querySelectorAll('[data-agenda-close]').forEach(b=>b.addEventListener('click',()=>editor.close()));
  editor.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  document.getElementById('followup-history-close').addEventListener('click',()=>historyDialog.close());
  form.elements.status.addEventListener('change',stateFields);
  async function saveEditor() {
    error('followup-save-error');
    const payload=window.HflIntentValues(form);
    payload.description = '';
    payload.checklists=window.hflActionChecklists?.value||[];
    if(editing)payload.version=editing.version;else{payload.request_id=requestId;payload.source=source;if(suggestionId)payload.suggestion_id=suggestionId;}

      attachments.validate();

      const prompt = payload.prompt, changed = attachments.changed;
      if (changed) payload.prompt = '';
      const saved = await api(editing?'/'+editing.id:'',{method:editing?'PATCH':'POST',body:JSON.stringify(payload)});
      editing = saved.item;
      if (changed) {
        await attachments.save(editing.id, editorState.report);
        editing = (await api('/'+editing.id,{method:'PATCH',body:JSON.stringify({version:editing.version,prompt})})).item;
      }
      window.HflEditorLocation('actionable',editing.id);
      document.getElementById('followup-state-label').hidden=false;
      document.getElementById('followup-editor-title').textContent='Edit action';
      form.querySelector('[type=submit]').hidden=true;
      await load(); window.dispatchEvent(new Event('hfl:actions-updated'));
  }
  form.addEventListener('submit',async e=>{e.preventDefault();try{await editorState.submit();}catch(err){error('followup-save-error',err.message);}});
  window.hflActions = {card, openEditor, load};
  timelineApi('/markers').then(data=>{markerDays=data.days;paintMarkers();}).catch(()=>{});
  window.addEventListener('hfl:timeline-close',()=>{clearTimeout(pollTimer);++sequence;});
  const params=new URLSearchParams(location.search);
  if(params.get('edit') && params.get('edit_kind') === 'actionable') api('/'+encodeURIComponent(params.get('edit'))).then(data=>openEditor(data.item)).catch(e=>error('agenda-error',e.message));
  if(params.has('source_entry') && params.has('source_path')){
    timelineApi('/source?'+new URLSearchParams({path:params.get('source_path'),entry_id:params.get('source_entry')})).then(data=>{openEditor();source=data;showEvidence();form.elements.title.value=data.title.slice(0,200);form.elements.body.focus();const url=new URL(location.href);url.searchParams.delete('source_path');url.searchParams.delete('source_entry');history.replaceState(null,'',url);}).catch(e=>error('agenda-error',e.message));
  }
})();
