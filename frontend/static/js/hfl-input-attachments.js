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
  async preview(file, saved) {
    const dialog=document.createElement('dialog');dialog.className='agenda-dialog agent-input-preview';
    const header=document.createElement('header');header.className='agenda-dialog-header';
    const title=document.createElement('h2');title.textContent=file.name;title.id='attachment-preview-title';dialog.setAttribute('aria-labelledby',title.id);
    const close=document.createElement('button');close.type='button';close.textContent='Close';close.onclick=()=>dialog.close();header.append(title,close);
    const body=document.createElement('div');body.className='agent-input-preview-body';body.setAttribute('aria-busy','true');
    const loading=document.createElement('div');loading.className='agent-preview-loading';loading.setAttribute('role','status');loading.setAttribute('aria-live','polite');
    const spinner=document.createElement('span');spinner.className='agent-preview-spinner';spinner.setAttribute('aria-hidden','true');
    const progress=document.createElement('span');progress.textContent=saved?'Loading file…':'Preparing preview…';loading.append(spinner,progress);body.append(loading);
    const download=document.createElement('a');download.textContent='Download';download.download=file.name;
    const footer=document.createElement('footer');footer.className='agenda-dialog-footer';footer.append(download);
    dialog.append(header,body,footer);document.body.append(dialog);dialog.showModal();
    const urls=[];let cancelled=false;
    const controller=new AbortController();
    const slow=setTimeout(()=>{progress.textContent='Still loading the file… You can close this preview while it loads.';},8000);
    dialog.addEventListener('close',()=>{cancelled=true;clearTimeout(slow);controller.abort();urls.forEach(url=>URL.revokeObjectURL(url));dialog.remove();});
    const objectUrl=blob=>{const url=URL.createObjectURL(blob);urls.push(url);return url;};
    download.href=saved?this.url()+'/'+file.id:objectUrl(file);
    try {
      let blob=file;
      if(saved){const response=await fetch(this.url()+'/'+file.id+'?view=true',{signal:controller.signal});if(!response.ok){const data=await response.json();throw Error(data.detail||'Preview unavailable.');}progress.textContent='Receiving file…';blob=await response.blob();}
      if(cancelled)return;
      clearTimeout(slow);progress.textContent='Preparing preview…';
      const suffix=file.name.split('.').pop().toLowerCase();
      let content;
      if(['png','jpg','jpeg','gif','webp'].includes(suffix)){content=document.createElement('img');content.alt=file.name;content.src=objectUrl(blob);try{await content.decode();}catch(_){throw Error('This image could not be previewed. Try downloading it instead.');}}
      else if(['mp4','webm','mp3','wav','ogg'].includes(suffix)){content=document.createElement(['mp4','webm'].includes(suffix)?'video':'audio');content.controls=true;content.src=objectUrl(blob);}
      else if(suffix==='pdf'||(saved&&['md','markdown'].includes(suffix))){content=document.createElement('iframe');content.title=file.name;if(suffix!=='pdf')content.setAttribute('sandbox','');content.src=objectUrl(blob);}
      else if(['txt','csv','tsv','json','log','md','markdown'].includes(suffix)||(saved&&suffix==='docx')){if(blob.size>2*1024*1024)throw Error('This document is too large to preview. Download it instead.');content=document.createElement('pre');content.textContent=await blob.text();}
      else throw Error(saved?'Preview is unavailable for this file type. Download it instead.':'Save this document first to preview it.');
      if(!cancelled)body.replaceChildren(content);
    }catch(error){if(!cancelled)body.textContent=error.message;}
    finally{clearTimeout(slow);body.removeAttribute('aria-busy');}
  }
  validate() {
    // Unavailable file metadata must not block edits that leave files untouched.
    if (!this.changed) return;
    if (this.loading) throw new Error('Attachments are still loading. Try Save again shortly.');
    if (this.failure) throw new Error(this.failure + ' Reopen the editor to reload attachments.');
    const files = [...this.saved.filter(file => !this.removed.has(file.id)), ...this.pending];
    if (files.length > 50 || files.some(file => file.size > 500 * 1024 * 1024) || files.reduce((sum, file) => sum + file.size, 0) > 50 * 500 * 1024 * 1024)
      throw new Error('Use up to 50 attachments, 500 MB each and 25,000 MB total.');
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
      const preview=document.createElement('button');preview.type='button';preview.textContent='Preview';preview.setAttribute('aria-label','Preview '+file.name);preview.onclick=()=>this.preview(file,saved);
      const controls=document.createElement('div');controls.className='agent-input-controls';controls.append(preview,remove);
      row.append(label, controls); this.list.append(row);
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
