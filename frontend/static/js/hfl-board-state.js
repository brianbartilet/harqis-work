/* Board edits remain in memory until the canonical server acknowledges them. */
class HflBoardSaveQueue {
  constructor(board, send, read, notify, delay = 500) {
    this.value = board; this.send = send; this.read = read; this.notify = notify;
    this.delay = delay; this.pending = {}; this.running = null; this.error = null;
  }
  get dirty() { return !!this.running || Object.keys(this.pending).length > 0; }
  edit(fields) {
    this.pending = {...this.pending, ...structuredClone(fields)};
    this.value = {...this.value, ...fields};
    this.notify(this.value, this.error ? 'Unsaved · Retry save' : 'Saving…');
    clearTimeout(this.timer);
    if (!this.error && !this.paused) this.timer = setTimeout(() => this.flush().catch(() => {}), this.delay);
    return this.value;
  }
  async flush() {
    clearTimeout(this.timer);
    if (this.paused) return this.value;
    if (this.running) { await this.running; return this.flush(); }
    if (!Object.keys(this.pending).length) return this.value;
    this.running = this.drain();
    try { return await this.running; } finally { this.running = null; if(!Object.keys(this.pending).length)clearTimeout(this.timer); }
  }
  async drain() {
    while (!this.paused && Object.keys(this.pending).length) {
      const fields = this.pending, version = this.value.version; this.pending = {};
      this.notify(this.value, 'Saving…');
      try {
        // A lost response may have committed. Reconcile only an exact match to
        // our previous request; never overwrite someone else's newer revision.
        if (this.error) {
          const remote = await this.read();
          if (remote.version !== version) {
            if (!this.failed || !Object.entries(this.failed).every(([k,v]) => JSON.stringify(remote[k]) === JSON.stringify(v))) {
              throw Error('Board changed elsewhere. Unsaved edits retained; resolve the conflict before retrying.');
            }
            this.value = {...remote, ...fields};
          }
        }
        const saved = await this.send({...fields, version: this.value.version});
        this.error = null; this.failed = null;
        this.value = {...saved, ...this.pending};
        this.notify(this.value, Object.keys(this.pending).length ? 'Saving…' : 'Saved');
      } catch (error) {
        this.pending = {...fields, ...this.pending}; this.failed = this.failed || fields; this.error = error;
        this.notify(this.value, 'Unsaved · ' + error.message + ' Use Retry save.');
        throw error;
      }
    }
    return this.value;
  }
  async prepareDelete() {
    this.paused = true;
    clearTimeout(this.timer);
    // Finish only the request already sent; don't save edits being deleted.
    if (this.running) await this.running;
    return this.value;
  }
  resume() {
    this.paused = false;
    if (!this.error && Object.keys(this.pending).length)
      this.timer = setTimeout(() => this.flush().catch(() => {}), this.delay);
  }
}
if (typeof module !== 'undefined') module.exports = HflBoardSaveQueue;
if (typeof window !== 'undefined') window.HflBoardSaveQueue = HflBoardSaveQueue;
