/* Shared staged attachment editor for actions and pinned dates. */
window.HflInputAttachments = class {
  static previewSaved(kind, id, file) {
    return this.prototype.preview.call({url:()=>'/hfl-corpus/agent-bridge/inputs/'+encodeURIComponent(kind)+'/'+encodeURIComponent(id)}, file, true);
  }
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
    const form = root.closest('form') || root;
    const receive = event => {
      if (this.root.inert || form.inert || this.loading || this.failure) return;
      const transfer = event.clipboardData || event.dataTransfer;
      const files = [...(transfer?.files || [])];
      if (!files.length) return;
      event.preventDefault(); event.stopPropagation();
      this.pending.push(...files); this.render(); this.root.dispatchEvent(new Event('change', {bubbles:true}));
    };
    form.addEventListener('paste', receive);
    form.addEventListener('drop', receive);
    form.addEventListener('dragover', event => { if ([...(event.dataTransfer?.types || [])].includes('Files')) event.preventDefault(); });
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
      else if(saved&&['md','markdown'].includes(suffix)){
        content=document.createElement('iframe');content.title=file.name;content.className='agent-markdown-preview';content.setAttribute('sandbox','');
        // The preview endpoint sanitizes Markdown. Decode explicitly before embedding
        // so blob navigation cannot guess a legacy encoding for Unicode punctuation.
        const html=await blob.text();
        content.srcdoc='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; style-src &apos;unsafe-inline&apos;"><style>'+
          ':root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;padding:clamp(16px,4vw,36px);background:#0b1220;color:#e2e8f0;font:14px/1.7 system-ui,sans-serif;overflow-wrap:anywhere}main{max-width:80ch;margin:auto}h1,h2,h3,h4{line-height:1.3;color:#f1f5f9;margin:1.6em 0 .65em}h1{font-size:1.7rem}h2{font-size:1.3rem}main>:first-child{margin-top:0}a{color:#67e8f9}p,ul,ol{margin:.8em 0}li{margin:.3em 0}pre{padding:1rem;background:#111c2e;border:1px solid #334155;border-radius:8px;overflow:auto;white-space:pre}code{font-family:Consolas,monospace;font-size:.9em;background:#111c2e;padding:.1em .25em}pre code{padding:0}blockquote{margin:1em 0;padding:.2em 1em;border-left:3px solid #38bdf8;color:#94a3b8}table{display:block;max-width:100%;overflow:auto;border-collapse:collapse}td,th{padding:.5em .8em;border:1px solid #334155;text-align:left}th{background:#111c2e}img{max-width:100%}hr{border:0;border-top:1px solid #334155;margin:1.5em 0}'+
          '</style></head><body><main>'+html+'</main></body></html>';
      }
      else if(suffix==='pdf'){content=document.createElement('iframe');content.title=file.name;content.src=objectUrl(blob);}
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
