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
  function eventCard(event) {
    const card = element('section'); card.className = 'agenda-history-row';
    card.append(element('h3', 'Agent · ' + event.kind.replaceAll('_', ' ')),
      element('p', new Date(event.created_at).toLocaleString('en-SG', {timeZone:'Asia/Singapore'}) + ' SGT · ' + event.actor),
      element('pre', event.payload.summary || ''), element('small', 'Run ' + event.run_id));
    card.querySelector('pre').className = 'action-prompt';
    if (event.payload.evidence?.length) card.append(element('p', 'Evidence: ' + event.payload.evidence.join(' · ')));
    return card;
  }
  async function open(kind, id, title) {
    const ticket = ++generation;
    dialog.replaceChildren();
    const header = element('header'); header.className = 'agenda-dialog-header';
    const heading = element('h2', 'Agent work'); heading.id = 'agent-bridge-title';
    const close = element('button', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Close agent work'); close.onclick = () => dialog.close();
    header.append(heading, close);
    const body = element('div'); body.className = 'agenda-form-body';
    body.append(element('h3', title), element('p', 'Research and drafts · Web reading only. Results and evidence stay attached to this item.'));
    const error = element('p'); error.className = 'agenda-error'; error.setAttribute('role', 'alert'); error.hidden = true;
    const cadenceLabel = element('label', 'Automatic runs');
    const cadence = element('select');
    for (const [value, label] of [['off','On demand only'],['daily',kind === 'pin' ? 'Daily during this period' : 'Daily while open'], ...(kind === 'pin' ? [['after_period','Once after this period']] : [])]) {
      const option = element('option', label); option.value = value; cadence.append(option);
    }
    cadenceLabel.append(cadence);
    const completionLabel = element('label', kind === 'actionable' ? 'Completion review' : 'Result review');
    const completion = element('select');
    for (const [value,label] of [['review','Review each result'],['auto','Accept evidence-backed results automatically']]) {
      const option = element('option', label); option.value = value; completion.append(option);
    }
    completionLabel.append(completion);
    const controls = element('div'); controls.className = 'agenda-card-actions';
    const runs = element('div');
    const path = sourcePath(kind, id);
    let requestKey = crypto.randomUUID();
    function button(label, fn) {
      const button = element('button', label); button.type = 'button';
      button.onclick = async () => { button.disabled = true; error.textContent = ''; error.hidden = true; try { await fn(); } catch (e) { error.textContent = e.message; error.hidden = false; button.disabled = false; } finally { if (button !== runButton) button.disabled = false; } };
      return button;
    }
    const runButton = button('Run now', async () => {
      await api(path + '/run', {request_key: requestKey, auto_complete: completion.value === 'auto'});
      requestKey = crypto.randomUUID(); await refresh();
    });
    controls.append(button('Save schedule', async () => {
      await api(path + '/configure', {cadence: cadence.value, auto_complete: completion.value === 'auto'});
      await refresh();
    }), runButton, button('Refresh', () => refresh()));
    body.append(cadenceLabel, completionLabel, controls, error, runs);
    dialog.append(header, body);
    if (!dialog.open) dialog.showModal();
    async function refresh() {
      const data = await api(path);
      if (ticket !== generation) return;
      cadence.value = data.subscription.cadence;
      completion.value = data.subscription.auto_complete ? 'auto' : 'review';
      runButton.disabled = data.runs.some(run => ['queued','running','awaiting_input','review','accepting'].includes(run.state));
      runs.replaceChildren();
      if (!data.runs.length) runs.append(element('p', 'No agent runs yet. Run now queues work for the local Hermes worker.'));
      for (const run of data.runs) {
        const card = element('section'); card.className = 'agenda-history-row';
        card.append(element('h3', run.state.replaceAll('_',' ')), element('small', 'Run ' + run.id));
        if (run.state === 'queued') card.append(element('p', 'Waiting for the Hermes worker.'));
        if (run.result.summary) { const output = element('pre', run.result.summary); output.className = 'action-prompt'; card.append(output); }
        if (run.result.evidence?.length) card.append(element('p', 'Evidence: ' + run.result.evidence.join(' · ')));
        if (['review','accepting'].includes(run.state)) card.append(button(run.state === 'accepting' ? 'Retry acceptance' : run.result.complete && kind === 'actionable' ? 'Accept and mark done' : 'Accept result', async () => { await api('/runs/' + run.id + '/accept', {}); await refresh(); window.dispatchEvent(new Event('hfl:agent-updated')); }));
        if (['queued','running','awaiting_input','review'].includes(run.state)) card.append(button('Cancel run', async () => { await api('/runs/' + run.id + '/cancel', {}); await refresh(); }));
        if (run.state === 'awaiting_input') card.append(element('p', 'Update the source instructions, cancel this attempt, then run again.'));
        const details = element('details'); details.append(element('summary', 'Instructions used'));
        const snapshot = element('pre', [run.snapshot.category_guidance, run.snapshot.source.prompt].filter(Boolean).join('\n\n')); snapshot.className = 'action-prompt'; details.append(snapshot); card.append(details);
        runs.append(card);
      }
      const history = element('details'); history.append(element('summary', 'Execution events'));
      data.events.forEach(event => history.append(eventCard(event))); runs.append(history);
    }
    try { await refresh(); } catch (e) { error.textContent = e.message; error.hidden = false; }
  }
  dialog.addEventListener('close', () => { ++generation; });
  window.hflAgentBridge = {open, events: async (kind, id) => (await api(sourcePath(kind,id))).events, eventCard};
})();
