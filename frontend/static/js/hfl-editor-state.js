(() => {
/* One save at a time; failed edits stay in the form until explicitly resolved. */
class HflEditorState {
  constructor(options) {
    this.options = options; this.saved = options.snapshot(); this.timer = null;
    this.pending = null; this.error = null; this.stopped = false;
  }
  get dirty() { return this.options.snapshot() !== this.saved; }
  changed() {
    clearTimeout(this.timer);
    if (this.stopped || this.paused || !this.dirty || this.pending) return;
    this.options.status(this.error ? 'Couldn’t save · Retry or keep editing' : 'Unsaved changes');
    if (!this.error && this.options.exists()) this.timer = setTimeout(() => this.flush().catch(() => {}), 700);
  }
  async flush() {
    clearTimeout(this.timer);
    if (this.pending) { await this.pending; return this.flush(); }
    if (this.stopped || (!this.dirty && this.options.exists())) return;
    if (!this.options.valid()) {
      this.options.status('Unsaved · Complete the required fields before saving.');
      throw Error('Complete the required fields before saving.');
    }
    this.error = null;
    const sent = this.options.snapshot();
    this.pending = (async () => {
      this.options.status('Saving…');
      // Staged files are locked; text remains editable while this snapshot saves.
      this.options.lock(true);
      try {
        await this.options.save(); this.saved = this.options.acknowledge ? this.options.acknowledge(sent) : sent;
        this.options.status('Saved');
      } catch (error) {
        this.error = error; this.options.status('Couldn’t save · ' + error.message); throw error;
      } finally { this.options.lock(false); }
    })();
    try { await this.pending; } finally { this.pending = null; }
    if (this.dirty) {
      this.options.status('Unsaved changes');
      if (!this.paused) return this.flush();
      return;
    }
    this.options.settled?.();
  }
  stop() { this.stopped = true; clearTimeout(this.timer); }
}
if (typeof module !== 'undefined') module.exports = HflEditorState;
if (typeof window !== 'undefined') {
  window.HflEditorState = HflEditorState;
  window.HflEditorLocation = (kind, id) => {
    const url = new URL(location.href);
    if (id) { url.searchParams.set('edit_kind', kind); url.searchParams.set('edit', id); }
    else { url.searchParams.delete('edit_kind'); url.searchParams.delete('edit'); }
    history.replaceState(null, '', url);
  };
  window.HflBindEditor = (dialog, form, options) => {
    const status = document.createElement('span'); status.className = 'editor-save-status'; status.setAttribute('role', 'status');
    form.querySelector('.agenda-dialog-footer').prepend(status);
    const controller = new HflEditorState({...options,
      acknowledge: sent => { const data=JSON.parse(sent);data.files=[];data.removed=[];return JSON.stringify(data); },
      status: text => { status.textContent = text; }});
    const events = new AbortController();
    for (const type of ['input', 'change', 'click', 'hfl:checklists-changed']) form.addEventListener(type, () => queueMicrotask(() => controller.changed()), {signal: events.signal});
    const close = dialog.close.bind(dialog);
    let question;
    dialog.close = () => {
      if (question?.open) return;
      clearTimeout(controller.timer);
      if (!controller.dirty && !controller.pending) { close(); return; }
      controller.paused = true;
      question = document.createElement('dialog'); question.className = 'agenda-dialog editor-close-question';
      const title = document.createElement('h2'); title.textContent = 'Unsaved changes';
      const message = document.createElement('p'); message.textContent = 'Some changes have not been saved. Already saved edits will be kept.';
      const error = document.createElement('p'); error.setAttribute('role', 'alert');
      const footer = document.createElement('div'); footer.className = 'agenda-dialog-footer';
      const add = (label, fn) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.onclick = fn; footer.append(b); };
      add('Save and close', async () => { try { await controller.flush(); question.close(); close(); } catch (e) { error.textContent = e.message; } });
      add('Discard', async () => {
        // A request already sent cannot be undone. Wait for its result first.
        controller.stop();
        if (controller.pending) { try { await controller.pending; } catch (_) {} }
        question.close(); close();
      });
      add('Keep editing', () => question.close());
      question.append(title, message, error, footer); document.body.append(question);
      const closingQuestion = question;
      question.addEventListener('close', () => {
        closingQuestion.remove();
        if (question === closingQuestion) question = null;
        controller.paused = !!question?.open; controller.changed();
      }); question.showModal();
    };
    dialog.addEventListener('cancel', e => { e.preventDefault(); dialog.close(); }, {signal: events.signal});
    let outside = false;
    const isOutside = e => { const r = dialog.getBoundingClientRect(); return e.target === dialog && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom); };
    dialog.addEventListener('pointerdown', e => { outside = isOutside(e); }, {signal: events.signal});
    dialog.addEventListener('click', e => { if (outside && isOutside(e)) dialog.close(); outside = false; }, {signal: events.signal});
    window.addEventListener('beforeunload', e => { if (controller.dirty || controller.pending) { e.preventDefault(); e.returnValue = ''; } }, {signal: events.signal});
    dialog.addEventListener('close', () => { controller.stop(); events.abort(); status.remove(); dialog.close = close; window.HflEditorLocation('', null); }, {once: true});
    const itemId=new URLSearchParams(location.search).get('item');
    if(itemId)requestAnimationFrame(()=>form.querySelector(`[data-item-id="${CSS.escape(itemId)}"] input[type=text]`)?.focus());
    return controller;
  };
}

})();
