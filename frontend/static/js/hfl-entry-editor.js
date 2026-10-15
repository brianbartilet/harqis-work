(() => {
  const dialog = document.querySelector('[data-entry-editor]');
  if (!dialog) return;
  const form = dialog.querySelector('form');
  const fields = dialog.querySelector('fieldset');
  const status = dialog.querySelector('[data-entry-editor-status]');
  const error = dialog.querySelector('[data-entry-editor-error]');
  const save = dialog.querySelector('[data-entry-editor-save]');
  const input = dialog.querySelector('[data-entry-editor-files]');
  const endpoint = '/hfl-corpus/entry-edit/' + dialog.dataset.path.split('/').map(encodeURIComponent).join('/');
  const keys = ['date', 'time', 'moment', 'what_happened', 'why_it_stayed', 'possible_use', 'tags'];
  let snapshot, pending = [], existing = [], ticket = 0, saving = false, saved = false;
  const showError = message => { error.textContent = message; error.hidden = !message; };
  const close = () => { if (!saving) dialog.close(); };
  dialog.querySelectorAll('[data-entry-editor-close]').forEach(button => button.addEventListener('click', close));
  dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => { ++ticket; snapshot = null; pending = []; existing = []; form.reset(); });
  function renderFiles() {
    for (const [selector, files, stored] of [['existing', existing, true], ['pending', pending, false]]) {
      const list = dialog.querySelector('[data-entry-editor-' + selector + ']');
      list.replaceChildren();
      files.forEach((file, index) => {
        const row = document.createElement('li'), label = document.createElement('span'), remove = document.createElement('button');
        label.textContent = stored ? file.split(/[\\/]/).pop() || file : file.name;
        if (stored) label.title = file;
        remove.type = 'button'; remove.textContent = 'Remove';
        remove.setAttribute('aria-label', 'Remove ' + label.textContent);
        remove.addEventListener('click', () => { files.splice(index, 1); renderFiles(); });
        row.append(label, remove); list.append(row);
      });
    }
  }
  function addFiles(files) {
    if (saving || saved || fields.disabled) return;
    if (pending.length + files.length > 50 || [...pending, ...files].some(file => file.size > 500 * 1024 * 1024)) {
      showError('Choose up to 50 files, no larger than 500 MB each.'); return;
    }
    pending.push(...files); renderFiles(); showError('');
  }
  dialog.querySelector('[data-entry-editor-choose]').addEventListener('click', () => input.click());
  input.addEventListener('change', () => { addFiles([...input.files]); input.value = ''; });
  for (const name of ['paste', 'drop']) form.addEventListener(name, event => {
    const files = [...((event.clipboardData || event.dataTransfer)?.files || [])];
    if (files.length) { event.preventDefault(); addFiles(files); }
  });
  form.addEventListener('dragover', event => { if ([...(event.dataTransfer?.types || [])].includes('Files')) event.preventDefault(); });
  async function responseBody(response) {
    const body = await response.json();
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'The entry could not be saved.');
    return body;
  }
  async function open(anchor) {
    const sequence = ++ticket;
    snapshot = null; pending = []; existing = []; saved = false;
    form.reset(); dialog.querySelector('.entry-editor-more').open = false;
    renderFiles(); fields.disabled = true; save.disabled = true;
    dialog.querySelector('[data-entry-editor-source]').textContent = '';
    showError(''); status.textContent = 'Loading entry…';
    if (!dialog.open) dialog.showModal();
    try {
      let response = await fetch(endpoint + '?anchor=' + encodeURIComponent(anchor));
      if (sequence !== ticket) return;
      if (response.status === 403) {
        dialog.close();
        if (await window.requestHflSecretsUnlock()) return open(anchor);
        return;
      }
      const body = await responseBody(response);
      if (sequence !== ticket) return;
      snapshot = body;
      keys.forEach(key => { form.elements[key].value = body[key] || ''; });
      form.elements.web_references.value = body.references.filter(ref => /^https?:\/\//i.test(ref)).join('\n');
      existing = body.references.filter(ref => !/^https?:\/\//i.test(ref));
      dialog.querySelector('[data-entry-editor-source]').textContent = [body.source, body.machine].filter(Boolean).join(' · ');
      renderFiles(); fields.disabled = false; save.disabled = false; status.textContent = '';
      form.elements.moment.focus();
    } catch (failure) { if (sequence === ticket) { status.textContent = ''; showError(failure.message || 'Could not load entry. Close and try again.'); } }
  }
  document.querySelectorAll('[data-entry-edit]').forEach(button => {
    button.addEventListener('click', () => open(button.dataset.entryEdit));
    button.disabled = false;
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!snapshot || saving || saved) return;
    const payload = {anchor: snapshot.anchor, entry_id: snapshot.entry_id, expected_updated_at: snapshot.expected_updated_at};
    keys.forEach(key => { payload[key] = form.elements[key].value; });
    const web = form.elements.web_references.value.split('\n').map(ref => ref.trim()).filter(Boolean);
    // Keep reference order for unchanged values, then append newly entered URLs.
    const selected = new Set([...existing, ...web]);
    payload.references = [...snapshot.references.filter(ref => selected.has(ref)), ...web.filter(ref => !snapshot.references.includes(ref))];
    const data = new FormData(); data.append('payload', JSON.stringify(payload));
    pending.forEach(file => data.append('files', file));
    saving = true; fields.disabled = true; save.disabled = true;
    dialog.querySelectorAll('[data-entry-editor-close]').forEach(button => { button.disabled = true; });
    showError(''); status.textContent = 'Saving entry…';
    try {
      const body = await responseBody(await fetch(endpoint, {method:'POST', headers:{'X-CSRF-Token':dialog.dataset.csrf}, body:data}));
      saved = true;
      if (body.warning) sessionStorage.setItem('hfl-entry-save-warning', body.warning);
      const url = new URL(location.href); url.hash = body.anchor;
      history.replaceState(null, '', url); location.reload();
    } catch (failure) {
      status.textContent = ''; showError(failure.message || 'Save could not be confirmed. Reload and check before retrying.');
      fields.disabled = false; save.disabled = false;
    } finally {
      saving = false;
      dialog.querySelectorAll('[data-entry-editor-close]').forEach(button => { button.disabled = false; });
    }
  });
  const warning = sessionStorage.getItem('hfl-entry-save-warning');
  if (warning) {
    sessionStorage.removeItem('hfl-entry-save-warning');
    const notice = document.createElement('p'); notice.className = 'corpus-action-toast'; notice.role = 'status'; notice.textContent = warning;
    document.querySelector('[data-document-header]')?.after(notice);
  }
  const url = new URL(location.href), pendingEdit = url.searchParams.get('edit_entry');
  if (pendingEdit) { url.searchParams.delete('edit_entry'); history.replaceState(null, '', url); open(pendingEdit); }
})();
