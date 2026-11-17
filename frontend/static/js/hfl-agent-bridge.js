(() => {
  'use strict';
  const csrf = () => JSON.parse(document.querySelector('[data-memory-csrf]')?.textContent || '""');
  const element = (tag, text) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; };
  async function api(path, payload) {
    const response = await fetch('/hfl-corpus/agent-bridge' + path, {
      method: payload === undefined ? 'GET' : 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf()},
      ...(payload === undefined ? {} : {body: JSON.stringify(payload)})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Agent request failed.');
    return data;
  }
  const sourcePath = (kind, id) => '/sources/' + encodeURIComponent(kind) + '/' + encodeURIComponent(id);
  const dialog = element('dialog'); dialog.className = 'agenda-dialog agent-bridge-dialog';
  dialog.setAttribute('aria-labelledby', 'agent-bridge-title');
  document.body.append(dialog);
  let backdropPress = false;
  const onBackdrop = event => {
    const bounds = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom);
  };
  dialog.addEventListener('pointerdown', event => { backdropPress = event.button === 0 && onBackdrop(event); });
  dialog.addEventListener('pointercancel', () => { backdropPress = false; });
  dialog.addEventListener('click', event => {
    const dismiss = backdropPress && onBackdrop(event);
    backdropPress = false;
    if (dismiss && dialog.classList.contains('action-agent-dialog')) dialog.close();
  });
  let generation = 0;
  let disposeWorkspace = () => {};
  let resultsTimer;
  function outputCard(payload) {
    const output = element('div'); output.className = 'agent-output';
    const report = element('div'); report.className = 'markdown-body';
    if (payload.output_html) report.innerHTML = payload.output_html;
    else { report.textContent = payload.summary || ''; report.classList.add('agent-output-plain'); }
    output.append(report);
    report.querySelectorAll('table').forEach(table => {
      const scroll = element('div'); scroll.className = 'agent-report-table'; scroll.tabIndex = 0;
      scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', 'Report table');
      table.replaceWith(scroll); scroll.append(table);
    });
    // Compact only the bridge-generated file footer; retain authored report links.
    const headings = [...report.children].filter(node => node.tagName === 'H3' && node.textContent.trim() === 'Files');
    headings.forEach(heading => {
      const rows = [];
      for (let row = heading.nextElementSibling; row?.tagName === 'P'; row = row.nextElementSibling) {
        const links = [...row.querySelectorAll('a')];
        if (links.length !== 2 || links[1].textContent.trim() !== 'Download' ||
            links.some(link => !/^\/hfl-corpus\/agent-bridge\/artifacts\/[^/]+\/[^/?]+(?:\?view=true)?$/.test(link.getAttribute('href') || '')) ||
            row.textContent.replace(links[0].textContent, '').replace(links[1].textContent, '').trim() !== '·') break;
        rows.push(row);
      }
      if (!rows.length) return;
      const files = element('section'); files.className = 'agent-output-files';
      const title = element('h4', 'Files · ' + rows.length); files.append(title);
      rows.forEach(row => {
        row.className = 'agent-output-file';
        const links = [...row.querySelectorAll('a')];
        links[1].setAttribute('aria-label', 'Download ' + links[0].textContent);
        row.replaceChildren(...links); files.append(row);
      });
      heading.replaceWith(files);
    });
    if (payload.evidence?.length) {
      const refs = element('details'); refs.className = 'agent-output-evidence';
      const evidence = [...new Set(payload.evidence)];
      refs.append(element('summary', 'Sources and evidence · ' + evidence.length));
      const list = element('ul');
      evidence.forEach(ref => {
        const item = element('li');
        if (/^https?:\/\//i.test(ref)) {
          const link = element('a', ref); link.href = ref; link.target = '_blank'; link.rel = 'noopener noreferrer';
          try { const url = new URL(ref); link.textContent = url.hostname + (url.pathname === '/' ? '' : url.pathname); } catch (_) { /* Keep the original reference. */ }
          link.title = ref; item.append(link);
        } else item.append(element('code', ref));
        list.append(item);
      });
      refs.append(list); output.append(refs);
    }
    return output;
  }
  function eventCard(event) {
    const card = element('section'); card.className = 'agenda-history-row';
    card.append(element('h3', 'Agent · ' + event.kind.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase())),
      element('p', new Date(event.created_at).toLocaleString('en-SG', {timeZone:'Asia/Singapore'}) + ' SGT · ' + event.actor),
      outputCard(event.payload), element('small', 'Run ' + event.run_id));
    if (event.payload.plan) card.append(element('p', 'Agent analysis: ' + event.payload.plan));
    return card;
  }
  async function open(kind, id, title) {
    disposeWorkspace();
    clearTimeout(resultsTimer);
    const ticket = ++generation;
    dialog.replaceChildren();
    const workspaceLayout = kind === 'actionable' && !!window.actionAgentWorkspace;
    dialog.classList.toggle('action-agent-dialog', workspaceLayout);
    dialog.classList.remove('agent-sidebar-open');
    const header = element('header'); header.className = 'agenda-dialog-header';
    const heading = element('h2', kind === 'actionable' ? 'Agent session' : 'Agent results'); heading.id = 'agent-bridge-title';
    heading.tabIndex = -1; heading.setAttribute('autofocus', '');
    const close = element('button'); close.type = 'button'; close.className = 'agent-results-close'; close.setAttribute('aria-label', kind === 'actionable' ? 'Close Agent session' : 'Close agent results'); close.title = 'Close (Esc)'; close.onclick = () => dialog.close();
    const closeIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    closeIcon.setAttribute('viewBox', '0 0 24 24'); closeIcon.setAttribute('aria-hidden', 'true'); closeIcon.setAttribute('focusable', 'false');
    const closePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    closePath.setAttribute('d', 'M6 6l12 12M18 6L6 18'); closeIcon.append(closePath); close.append(closeIcon);
    header.append(heading, close);
    const body = element('div'); body.className = 'agenda-form-body agent-results-body';
    let information = body;
    let headerStatus;
    if (workspaceLayout) {
      const utilities=element('div');utilities.className='agent-header-utilities';
      headerStatus=element('span','Loading session…');headerStatus.className='agent-header-status';headerStatus.setAttribute('role','status');
      const help=element('details');help.className='agent-header-help';
      const helpToggle=element('summary','?');helpToggle.setAttribute('aria-label','Actions agent help');helpToggle.title='Session help';
      const helpBody=element('div');helpBody.className='agent-header-help-body';
      helpBody.append(element('strong','Working with this action'));
      for(const text of ['Start a session, then click inside the terminal to type. Press Enter to send; use /help for Hermes commands.',
        'If the session disconnects or expires, restore it to continue. Its old transcript is read-only.',
        'Session controls are above the terminal. Run initial prompt executes the card’s saved instructions. Generated files are in the left panel (Action details on mobile).',
        'Closing this dialog leaves the session running. End session stops it.'])helpBody.append(element('p',text));
      help.append(helpToggle,helpBody);utilities.append(headerStatus,help);header.insertBefore(utilities,close);
      information = element('aside'); information.className = 'agent-sidebar'; information.id = 'action-agent-sidebar';
      information.setAttribute('aria-label', 'Action information and controls');
      const toggle = element('button', 'Action details'); toggle.type = 'button'; toggle.className = 'agent-sidebar-toggle';
      toggle.setAttribute('aria-controls', information.id); toggle.setAttribute('aria-expanded', 'false');
      toggle.onclick = () => toggle.setAttribute('aria-expanded', String(dialog.classList.toggle('agent-sidebar-open')));
      header.insertBefore(toggle, close);
      body.append(information);
    }
    const task = element('section'); task.className = 'agent-results-task';
    task.append(element('span', kind === 'actionable' ? 'ACTION' : 'PINNED PERIOD'), element('h3', title));
    information.append(task);
    const attachmentArea=element('div');attachmentArea.className='agent-attachments-area';
    if (workspaceLayout) information.append(attachmentArea);
    if (workspaceLayout) disposeWorkspace = window.actionAgentWorkspace.mount(body, id, information, task, headerStatus);
    const error = element('p'); error.className = 'agenda-error'; error.setAttribute('role', 'alert'); error.hidden = true;
    const cadenceLabel = element('label', 'Automatic runs');
    const cadence = element('select');
    for (const [value, label] of [['off','On demand only'],['daily',kind === 'pin' ? 'Daily during this period' : 'Daily while ready'], ...(kind === 'pin' ? [['after_period','Once after this period']] : [])]) {
      const option = element('option', label); option.value = value; cadence.append(option);
    }
    cadenceLabel.append(cadence);
    const controls = element('div'); controls.className = 'agenda-card-actions agent-results-controls';
    const runs = element('div'); runs.className = 'agent-results-list';
    const loading = element('p', 'Loading results…'); loading.setAttribute('role', 'status'); runs.append(loading);
    const path = sourcePath(kind, id);
    let requestKey = crypto.randomUUID();
    function button(label, fn) {
      const button = element('button', label); button.type = 'button';
      button.onclick = async () => { button.disabled = true; error.textContent = ''; error.hidden = true; try { await fn(); } catch (e) { error.textContent = e.message; error.hidden = false; button.disabled = false; } finally { if (button !== runButton) button.disabled = false; } };
      return button;
    }
    const runButton = button(workspaceLayout ? 'Run initial prompt' : 'Run now', async () => {
      await api(path + '/run', {request_key: requestKey, auto_complete: true});
      requestKey = crypto.randomUUID(); await refresh();
    });
    runButton.className = 'agent-results-primary';
    runButton.disabled = true;
    const saveSchedule = button('Save schedule', async () => {
      await api(path + '/configure', {cadence: cadence.value, auto_complete: true});
      await refresh();
    });
    if (kind === 'pin') controls.append(saveSchedule);
    controls.append(runButton, button('Refresh', () => refresh()));
    if (kind === 'pin') information.append(cadenceLabel);
    const promptEmpty=element('p','The initial prompt field is empty. Use Edit to add instructions before running it.');promptEmpty.className='agent-initial-prompt-empty';promptEmpty.hidden=true;
    if (workspaceLayout) {
      const initialRuns=element('section');initialRuns.className='agent-initial-prompt-runs';initialRuns.setAttribute('aria-label','Initial prompt runs');
      initialRuns.append(element('h3','Action runs and outputs'),promptEmpty,controls,error,runs);
      information.append(initialRuns);
    } else information.append(controls,error,runs);
    const footer = element('footer'); footer.className = 'agent-results-footer';
    if (kind === 'pin') footer.append(element('p', 'Scheduled runs use the hour set on this pin.'));
    const settings = element('a', 'Agent settings'); settings.href = '/settings'; settings.target = '_blank'; settings.rel = 'noopener noreferrer'; footer.append(settings);
    if (!workspaceLayout) information.append(footer);
    dialog.append(header, body);
    if (!dialog.open) dialog.showModal();
    async function refresh() {
      const [data, attachments] = await Promise.all([
        api(path), kind === 'actionable' ? api('/inputs/actionable/' + encodeURIComponent(id)) : Promise.resolve({attachments:[]})
      ]);
      if (ticket !== generation) return;
      cadence.value = data.subscription.cadence;
      promptEmpty.hidden = data.has_initial_prompt !== false && data.assignment?.executable !== false;
      promptEmpty.textContent = data.assignment?.reason || 'The initial prompt field is empty. Use Edit to add instructions before running it.';
      if(workspaceLayout)runButton.textContent=data.assignment?.mode==='butler'?'Run with butler':'Run action';
      runButton.disabled = data.assignment?.executable === false || (kind==='actionable' && data.has_initial_prompt!==true) || ['done','dismissed'].includes(data.action_status) || data.runs.some(run => ['queued','running','review','accepting'].includes(run.state));
      runs.replaceChildren();
      attachmentArea.replaceChildren();
      if (attachments.attachments.length) {
        const files = element('section'); files.className = 'agent-output-files';
        files.append(element('h3', 'Attachments · ' + attachments.attachments.length));
        for (const file of attachments.attachments) {
          const row = element('p'); row.className = 'agent-output-file';
          const name = element('span', file.name);
          name.title=file.name;
          const view=element('button','View');view.type='button';view.setAttribute('aria-label','View '+file.name);
          view.onclick=()=>window.HflInputAttachments.previewSaved('actionable',id,file);
          const link = element('a', 'Download');
          link.href = '/hfl-corpus/agent-bridge/inputs/actionable/' + encodeURIComponent(id) + '/' + encodeURIComponent(file.id);
          link.setAttribute('download', ''); link.setAttribute('aria-label', 'Download ' + file.name);
          row.append(name, view, link); files.append(row);
        }
        (workspaceLayout ? attachmentArea : runs).append(files);
      }
      const outcomes=data.outcomes || [];
      if(data.outcomes_error){error.textContent=data.outcomes_error;error.hidden=false;}
      if ((workspaceLayout || !attachments.attachments.length) && !data.runs.length && !outcomes.length && !data.events.length && !data.outcomes_error) {
        const empty = element('section'); empty.className = 'agent-results-empty';
        empty.append(element('h3', 'No results yet'), element('p', 'Run the saved prompt to get started. Output, sources and files will appear here.'));
        runs.append(empty);
      }
      for(const outcome of outcomes){
        const card=element('section');card.className='agenda-history-row agent-result-card';
        card.append(element('h3','Saved action outcome'),element('small',new Date(outcome.created_at).toLocaleString('en-SG',{timeZone:'Asia/Singapore'})+' SGT · Revision '+outcome.version),outputCard(outcome));
        runs.append(card);
      }
      for (const run of data.runs) {
        const card = element('section'); card.className = 'agenda-history-row agent-result-card';
        const meta = element('div'); meta.className = 'agent-result-meta';
        const integrationBlocked = run.result.blocked_reason === 'integration';
        const state = element('h3', ({queued:'Queued',running:'In progress',succeeded:run.result.complete ? 'Completed' : 'Incomplete',failed:integrationBlocked ? 'Blocked by integration' : 'Incomplete',awaiting_input:integrationBlocked ? 'Blocked by integration' : 'Needs your answer',review:'Ready for review',accepting:'Applying result',cancelled:'Cancelled'})[run.state] || run.state);
        state.className = 'agent-result-state'; state.dataset.state = run.state;
        const time = element('time', new Date(run.created_at).toLocaleString('en-SG', {timeZone:'Asia/Singapore',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) + ' SGT'); time.dateTime = run.created_at;
        meta.append(state, time); card.append(meta);
        if (run.snapshot?.execution_settings) {
          const settings = run.snapshot.execution_settings;
          card.append(element('small', 'Execution: ' + settings.agent_mode + ' · Profile: ' + (settings.hermes_profile || 'Worker default')));
        }
        if (run.state === 'queued') card.append(element('p', 'Waiting for an agent to start. You can leave this dialog and check back later.'));
        if (run.snapshot?.continuation) {
          const reply = element('p', run.snapshot.continuation.reply ? 'Your reply: ' + run.snapshot.continuation.reply : 'Retry requested after a fix.');
          reply.className = 'agent-continuation-reply'; card.append(reply);
        }
        if (run.id === data.runs[0]?.id && ['awaiting_input','failed'].includes(run.state)) {
          const form = element('form'); form.className = 'agent-continuation-form';
          const label = element('label', integrationBlocked ? 'What changed? (optional)' : 'Your reply');
          const input = element('textarea'); input.id = 'agent-reply-' + run.id; input.rows = 3; input.maxLength = 8000;
          label.htmlFor = input.id;
          input.placeholder = integrationBlocked ? 'Describe the fix or add instructions for the retry.' : 'Answer the question or clarify what the agent should do next.';
          if (run.result.question) form.append(element('p', run.result.question));
          form.append(label, input, element('small', 'Continues with previous results and files. You do not need to edit the task or set it to Ready.'));
          const feedback = element('p'); feedback.setAttribute('role', 'alert'); feedback.hidden = true;
          input.addEventListener('input', () => { feedback.hidden = true; });
          const submit = element('button', integrationBlocked ? 'Retry after fix' : 'Answer and continue'); submit.type = 'submit';
          const actions = element('div'); actions.className = 'agent-result-actions'; actions.append(submit);
          // Legacy results have no blocker type; allow retrying them after an external fix.
          const retry = !run.result.blocked_reason ? element('button', 'Retry after fix') : null;
          if (retry) { retry.type = 'button'; actions.append(retry); }
          let continuationKey = crypto.randomUUID(), submittedReply = null;
          const send = async (allowEmpty) => {
            const reply = input.value.trim();
            if (!reply && !allowEmpty) { feedback.textContent = 'Enter your answer before continuing.'; feedback.hidden = false; input.focus(); return; }
            if (submittedReply !== null && submittedReply !== reply) continuationKey = crypto.randomUUID();
            submittedReply = reply; submit.disabled = true; if (retry) retry.disabled = true; feedback.hidden = true;
            try {
              await api('/runs/' + run.id + '/continue', {request_key: continuationKey, reply});
              await refresh(); window.dispatchEvent(new Event('hfl:agent-updated'));
            } catch (e) { feedback.textContent = e.message; feedback.hidden = false; }
            finally { submit.disabled = false; if (retry) retry.disabled = false; }
          };
          form.onsubmit = e => { e.preventDefault(); send(integrationBlocked || run.state === 'failed'); };
          if (retry) retry.onclick = () => send(true);
          form.append(actions, feedback); card.append(form);
        }
        if (run.result.summary) card.append(outputCard(run.result));
        const actions = element('div'); actions.className = 'agent-result-actions';
        if (['review','accepting'].includes(run.state)) actions.append(button(run.state === 'accepting' ? 'Retry acceptance' : run.result.complete && kind === 'actionable' ? 'Accept and mark done' : 'Accept result', async () => { await api('/runs/' + run.id + '/accept', {}); await refresh(); window.dispatchEvent(new Event('hfl:agent-updated')); }));
        if (['queued','running','awaiting_input','review'].includes(run.state)) actions.append(button('Cancel run', async () => { await api('/runs/' + run.id + '/cancel', {}); await refresh(); }));
        if (actions.childElementCount) card.append(actions);
        const details = element('details'); details.append(element('summary', 'Run details'));
        const snapshot = element('pre', [run.snapshot.category_guidance, run.snapshot.source.prompt].filter(Boolean).join('\n\n')); snapshot.className = 'action-prompt'; details.append(element('p', 'Instructions used'), snapshot, element('small', 'Run ' + run.id));
        if (run.snapshot.source.attachments?.length) {
          const inputs = element('div'); inputs.append(element('p', 'Supporting files used'));
          run.snapshot.source.attachments.forEach(file => {
            const link = element('a', file.name);
            link.href = '/hfl-corpus/agent-bridge/inputs/' + encodeURIComponent(run.snapshot.kind) + '/' + encodeURIComponent(run.snapshot.source_id) + '/' + encodeURIComponent(file.id);
            link.setAttribute('download', '');
            const row = element('p'); row.append(link); inputs.append(row);
          });
          details.append(inputs);
        }
        if (run.result.session_id) details.append(element('small', 'Hermes session: ' + run.result.session_id));
        if (run.result.model) details.append(element('p', 'Model: ' + run.result.model + (run.result.provider ? ' · Provider: ' + run.result.provider : '')));
        if (run.result.runtime) {
          const runtime = run.result.runtime;
          details.append(element('p', 'Profile: ' + runtime.profile + ' · Mode: ' + runtime.mode));
          details.append(element('p', 'Toolsets: ' + runtime.toolsets));
          if (runtime.configured_mcp_servers?.length) details.append(element('p', 'Configured MCP servers: ' + runtime.configured_mcp_servers.join(', ')));
        }
        card.append(details);
        runs.append(card);
      }
      if (data.events.length) {
        const history = element('details'); history.className = 'agent-results-events'; history.append(element('summary', 'Execution history · ' + data.events.length + ' events'));
        data.events.forEach(event => history.append(eventCard(event))); runs.append(history);
      }
    }
    async function pollResults() {
      if(ticket !== generation || !dialog.open)return;
      try { if(!runs.contains(document.activeElement))await refresh(); } catch(e) {error.textContent=e.message;error.hidden=false;}
      if(ticket === generation)resultsTimer=setTimeout(pollResults,3000);
    }
    await pollResults();
  }
  dialog.addEventListener('close', () => { disposeWorkspace(); clearTimeout(resultsTimer); ++generation; window.dispatchEvent(new Event('hfl:agent-updated')); });
  window.hflAgentBridge = {open, events: async (kind, id) => (await api(sourcePath(kind,id))).events, eventCard};
})();
