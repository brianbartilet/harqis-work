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
  let generation = 0;
  function outputCard(payload) {
    const output = element('div'); output.className = 'markdown-body';
    if (payload.output_html) output.innerHTML = payload.output_html;
    else output.textContent = payload.summary || '';
    if (payload.evidence?.length) {
      const refs = element('p', 'Evidence: ');
      payload.evidence.forEach((ref, index) => {
        if(index) refs.append(document.createTextNode(' · '));
        if (/^https?:\/\//i.test(ref)) { const link = element('a', ref); link.href = ref; link.target = '_blank'; link.rel = 'noopener noreferrer'; refs.append(link); }
        else refs.append(document.createTextNode(ref));
      });
      output.append(refs);
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
    const ticket = ++generation;
    dialog.replaceChildren();
    const header = element('header'); header.className = 'agenda-dialog-header';
    const heading = element('h2', 'Agent results'); heading.id = 'agent-bridge-title';
    heading.tabIndex = -1; heading.setAttribute('autofocus', '');
    const close = element('button'); close.type = 'button'; close.className = 'agent-results-close'; close.setAttribute('aria-label', 'Close agent results'); close.title = 'Close (Esc)'; close.onclick = () => dialog.close();
    const closeIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    closeIcon.setAttribute('viewBox', '0 0 24 24'); closeIcon.setAttribute('aria-hidden', 'true'); closeIcon.setAttribute('focusable', 'false');
    const closePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    closePath.setAttribute('d', 'M6 6l12 12M18 6L6 18'); closeIcon.append(closePath); close.append(closeIcon);
    header.append(heading, close);
    const body = element('div'); body.className = 'agenda-form-body agent-results-body';
    const task = element('section'); task.className = 'agent-results-task';
    task.append(element('span', kind === 'actionable' ? 'ACTION' : 'PINNED PERIOD'), element('h3', title));
    body.append(task);
    const error = element('p'); error.className = 'agenda-error'; error.setAttribute('role', 'alert'); error.hidden = true;
    const cadenceLabel = element('label', 'Automatic runs');
    const cadence = element('select');
    for (const [value, label] of [['off','On demand only'],['daily',kind === 'pin' ? 'Daily during this period' : 'Daily while open'], ...(kind === 'pin' ? [['after_period','Once after this period']] : [])]) {
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
    const runButton = button('Run now', async () => {
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
    if (kind === 'pin') body.append(cadenceLabel);
    body.append(controls, error, runs);
    const footer = element('footer'); footer.className = 'agent-results-footer';
    footer.append(element('p', kind === 'actionable' ? 'To repeat a completed action, change its status to Open.' : 'Scheduled runs use the hour set on this pin.'));
    const settings = element('a', 'Agent settings'); settings.href = '/settings'; footer.append(settings);
    body.append(footer);
    dialog.append(header, body);
    if (!dialog.open) dialog.showModal();
    async function refresh() {
      const data = await api(path);
      if (ticket !== generation) return;
      cadence.value = data.subscription.cadence;
      runButton.disabled = data.runs.some(run => ['queued','running','review','accepting'].includes(run.state));
      runs.replaceChildren();
      if (!data.runs.length) {
        const empty = element('section'); empty.className = 'agent-results-empty';
        empty.append(element('h3', 'No results yet'), element('p', 'Run the saved prompt to get started. Output, sources and files will appear here.'));
        runs.append(empty);
      }
      for (const run of data.runs) {
        const card = element('section'); card.className = 'agenda-history-row agent-result-card';
        const meta = element('div'); meta.className = 'agent-result-meta';
        const state = element('h3', ({queued:'Queued',running:'In progress',succeeded:run.result.complete ? 'Completed' : 'Incomplete',failed:'Incomplete',awaiting_input:'Needs input',review:'Ready for review',accepting:'Applying result',cancelled:'Cancelled'})[run.state] || run.state);
        state.className = 'agent-result-state'; state.dataset.state = run.state;
        const time = element('time', new Date(run.created_at).toLocaleString('en-SG', {timeZone:'Asia/Singapore',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) + ' SGT'); time.dateTime = run.created_at;
        meta.append(state, time); card.append(meta);
        if (run.state === 'queued') card.append(element('p', 'Waiting for an agent to start. You can leave this dialog and check back later.'));
        if (run.result.summary) card.append(outputCard(run.result));
        if (['review','accepting'].includes(run.state)) card.append(button(run.state === 'accepting' ? 'Retry acceptance' : run.result.complete && kind === 'actionable' ? 'Accept and mark done' : 'Accept result', async () => { await api('/runs/' + run.id + '/accept', {}); await refresh(); window.dispatchEvent(new Event('hfl:agent-updated')); }));
        if (['queued','running','awaiting_input','review'].includes(run.state)) card.append(button('Cancel run', async () => { await api('/runs/' + run.id + '/cancel', {}); await refresh(); }));
        if (run.state === 'awaiting_input') card.append(element('p', 'Update the source instructions, cancel this attempt, then run again.'));
        const details = element('details'); details.append(element('summary', 'Run details'));
        const snapshot = element('pre', [run.snapshot.category_guidance, run.snapshot.source.prompt].filter(Boolean).join('\n\n')); snapshot.className = 'action-prompt'; details.append(element('p', 'Instructions used'), snapshot, element('small', 'Run ' + run.id));
        if (run.result.session_id) details.append(element('small', 'Hermes session: ' + run.result.session_id));
        if (run.result.model) details.append(element('p', 'Model: ' + run.result.model + (run.result.provider ? ' · Provider: ' + run.result.provider : '')));
        card.append(details);
        runs.append(card);
      }
      if (data.events.length) {
        const history = element('details'); history.className = 'agent-results-events'; history.append(element('summary', 'Execution history · ' + data.events.length + ' events'));
        data.events.forEach(event => history.append(eventCard(event))); runs.append(history);
      }
    }
    try { await refresh(); } catch (e) { error.textContent = e.message; error.hidden = false; }
  }
  dialog.addEventListener('close', () => { ++generation; window.dispatchEvent(new Event('hfl:agent-updated')); });
  window.hflAgentBridge = {open, events: async (kind, id) => (await api(sourcePath(kind,id))).events, eventCard};
})();
