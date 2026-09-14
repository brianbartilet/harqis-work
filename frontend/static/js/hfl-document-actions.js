/* Create linked actions without leaving the corpus document. */
(() => {
  const dialog = document.getElementById('followup-editor');
  const form = document.getElementById('followup-form');
  if (!dialog || !form) return;
  const save = form.querySelector('[type="submit"]');
  const error = document.getElementById('followup-save-error');
  const evidence = document.getElementById('followup-evidence');
  let source = null, requestId = '', trigger = null, busy = false, sequence = 0;
  function showError(message = '') {
    error.textContent = message;
    error.hidden = !message;
  }
  async function api(path, options = {}) {
    const response = await fetch('/hfl-corpus/timeline' + path, {
      ...options, headers: {'Content-Type': 'application/json', ...options.headers},
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not save this action. Please try again.');
    return data;
  }
  document.addEventListener('click', async event => {
    const link = event.target.closest('.corpus-followup-action');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (busy) return;
    trigger = link;
    const ticket = ++sequence;
    const params = new URL(link.href).searchParams;
    form.reset(); source = null; requestId = crypto.randomUUID(); showError();
    document.getElementById('followup-state-label').hidden = true;
    document.getElementById('followup-completion-label').hidden = true;
    evidence.hidden = false; evidence.textContent = 'Loading entry…';
    save.disabled = true;
    dialog.showModal();
    try {
      const data = await api('/source?' + new URLSearchParams({path: params.get('source_path'), entry_id: params.get('source_entry')}));
      if (ticket !== sequence || !dialog.open) return;
      source = data;
      evidence.replaceChildren(document.createTextNode('From HFL: '));
      const anchor = document.createElement('a');
      anchor.textContent = data.title || data.entry_id;
      anchor.href = '/hfl-corpus/timeline/evidence?' + new URLSearchParams({path: data.path, entry_id: data.entry_id});
      anchor.target = '_blank'; anchor.rel = 'noopener'; evidence.append(anchor);
      form.elements.title.value = (data.title || '').slice(0, 200);
      save.disabled = false;
      form.elements.expected_outcome.focus({preventScroll: true});
    } catch (err) {
      if (ticket === sequence && dialog.open) { evidence.hidden = true; showError(err.message); }
    }
  });
  dialog.querySelectorAll('[data-agenda-close]').forEach(button => button.addEventListener('click', () => {
    if (!busy) dialog.close();
  }));
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => { ++sequence; trigger?.focus({preventScroll: true}); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !source) return;
    busy = true; save.disabled = true; save.textContent = 'Saving…'; showError();
    try {
      await api('/items', {method: 'POST', body: JSON.stringify({
        ...Object.fromEntries(new FormData(form)), source, request_id: requestId,
      })});
      dialog.close();
      const entryTrigger = trigger;
      const header = entryTrigger.closest('.corpus-entry-header');
      if (header.nextElementSibling?.classList.contains('corpus-action-toast')) header.nextElementSibling.remove();
      const toast = document.createElement('div');
      toast.className = 'corpus-action-toast';
      const message = document.createElement('span');
      message.setAttribute('role', 'status');
      message.textContent = 'Action added. View it in the Activity Corpus.';
      const dismiss = document.createElement('button');
      dismiss.type = 'button'; dismiss.textContent = '×';
      dismiss.setAttribute('aria-label', 'Dismiss action confirmation');
      dismiss.addEventListener('click', () => {
        toast.remove();
        entryTrigger.focus({preventScroll: true});
      });
      toast.append(message, dismiss);
      header.after(toast);
    } catch (err) { showError(err.message); }
    finally { busy = false; save.disabled = false; save.textContent = 'Save'; }
  });
})();
