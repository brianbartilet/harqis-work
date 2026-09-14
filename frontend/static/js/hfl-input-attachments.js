/* Shared staged attachment editor for actions and pinned dates. */
window.HflInputAttachments = class {
  constructor(root, kind) {
    this.root = root; this.kind = kind; this.sequence = 0;
    this.input = root.querySelector('[data-input-files]');
    this.choose = root.querySelector('[data-input-choose]');
    this.choose.addEventListener('click', () => this.input.click());
    this.retry = root.querySelector('[data-input-retry]');
    this.retry.addEventListener('click', () => this.reset(this.id));
    this.list = root.querySelector('[data-input-list]');
    this.error = root.querySelector('[data-input-error]');
    this.input.addEventListener('change', () => {
      this.pending.push(...this.input.files); this.input.value = ''; this.render();
    });
    this.reset();
  }
  url(id = this.id) { return '/hfl-corpus/agent-bridge/inputs/' + this.kind + '/' + encodeURIComponent(id); }
  async request(url, options = {}) {
    const token = this.root.dataset.csrf || JSON.parse(document.querySelector('[data-memory-csrf]')?.textContent || '""');
    const response = await fetch(url, {...options, headers: {'X-CSRF-Token': token}});
    if (response.status === 404) throw new Error('Attachments are unavailable for this task. The task or attachment service may no longer be available.');
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error('Could not load attachments. Please try again.'); }
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save attachments.');
    return result;
  }
  reset(id = null) {
    const ticket = ++this.sequence;
    this.id = id; this.saved = []; this.pending = []; this.removed = new Set(); this.failure = ''; this.loading = !!id;
    this.input.value = ''; this.render();
    if (id) this.request(this.url()).then(data => {
      if (ticket === this.sequence) { this.saved = data.attachments; this.loading = false; this.render(); }
    }).catch(error => { if (ticket === this.sequence) { this.failure = error.message; this.loading = false; this.render(); } });
  }
  get changed() { return this.pending.length > 0 || this.removed.size > 0; }
  validate() {
    // Unavailable file metadata must not block edits that leave files untouched.
    if (!this.changed) return;
    if (this.loading) throw new Error('Attachments are still loading. Try Save again shortly.');
    if (this.failure) throw new Error(this.failure + ' Reopen the editor to reload attachments.');
    const files = [...this.saved.filter(file => !this.removed.has(file.id)), ...this.pending];
    if (files.length > 10 || files.some(file => file.size > 50 * 1024 * 1024) || files.reduce((sum, file) => sum + file.size, 0) > 200 * 1024 * 1024)
      throw new Error('Use up to 10 attachments, 50 MB each and 200 MB total.');
  }
  render() {
    this.list.replaceChildren();
    const add = (file, saved, index) => {
      const row = document.createElement('div'); row.className = 'agent-input-row';
      const label = document.createElement(saved ? 'a' : 'span');
      label.textContent = file.name + ' · ' + Math.max(1, Math.ceil(file.size / 1024)) + ' KB' + (saved ? '' : ' · Pending');
      if (saved) { label.href = this.url() + '/' + file.id; label.setAttribute('download', ''); }
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove';
      remove.setAttribute('aria-label', 'Remove ' + file.name);
      remove.onclick = () => { if (saved) this.removed.add(file.id); else this.pending.splice(index, 1); this.render(); };
      row.append(label, remove); this.list.append(row);
    };
    this.saved.filter(file => !this.removed.has(file.id)).forEach(file => add(file, true));
    this.pending.forEach((file, index) => add(file, false, index));
    this.error.textContent = this.failure ? 'Couldn’t load saved files.' : (this.loading ? 'Loading files…' : '');
    this.error.hidden = !this.error.textContent;
    this.root.querySelector('[data-input-status]').hidden = !this.error.textContent;
    this.retry.hidden = !this.failure;
    this.choose.disabled = this.input.disabled = this.loading || !!this.failure;
  }
  async save(id) {
    this.validate(); this.id = id;
    for (const attachmentId of [...this.removed]) {
      const data = await this.request(this.url() + '/' + attachmentId, {method: 'DELETE'});
      this.saved = data.attachments; this.removed.delete(attachmentId);
    }
    if (this.pending.length) {
      const form = new FormData(); this.pending.forEach(file => form.append('files', file));
      const data = await this.request(this.url(), {method: 'POST', body: form});
      this.saved = data.attachments; this.pending = [];
    }
    this.render();
  }
};
