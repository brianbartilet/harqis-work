(() => {
  const root = document.querySelector('[data-roles-csrf]'); if (!root) return;
  const $ = s => document.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const help = $('#facets-help'), helpTrigger = $('#facets-help-open');
  helpTrigger.onclick = () => { help.showModal(); $('#facets-help-title').focus(); };
  help.querySelectorAll('[data-facets-help-close]').forEach(button => button.onclick = () => help.close());
  help.addEventListener('close', () => helpTrigger.focus());
  help.addEventListener('click', event => {
    const box = help.getBoundingClientRect();
    if (event.target === help && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) help.close();
  });
  let data = {roles:[], spaces:[], runs:[]}, current = null, controls = null;
  const status = text => { $('#role-status').textContent = text; };
  async function api(path, method='GET', body) {
    const headers = {'X-CSRF-Token':root.dataset.rolesCsrf};
    if (body && !(body instanceof FormData)) { headers['Content-Type']='application/json'; body=JSON.stringify(body); }
    const response = await fetch('/roles'+path, {method, headers, body});
    const value = await response.json(); if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : Array.isArray(value.detail) ? value.detail.map(e=>`${(e.loc||[]).slice(1).join(' ')}: ${e.msg}`).join('; ') : 'The request failed. Please try again.'); return value;
  }
  async function load() { data=await api('/data'); list(); }
  function list() {
    $('#roles-list').innerHTML=data.roles.filter(r=>!r.archived||$('#roles-archived').checked).map(r=>`<button class="role-card" data-role="${esc(r.id)}"><span style="color:${esc(r.color)}">●</span> ${esc(r.name)}<small>${r.archived?'Archived':`${r.workspace_ids.length} linked Spaces`} · revision ${r.revision}</small></button>`).join('') || '<p class="role-help">No facets yet.</p>';
    const expanded = new Set([...$('#roles-runs').querySelectorAll('details[open]')].map(e=>e.dataset.run));
    $('#roles-runs').innerHTML=data.runs.map(runCard).join('')||'<p class="role-help">No analysis runs yet. Analyze now checks active facets with linked Spaces.</p>';
    $('#roles-runs').querySelectorAll('details').forEach(e=>e.open=expanded.has(e.dataset.run));
  }
  function runCard(run) {
    const roles=run.roles||[], state=run.status;
    const labels={complete:'Completed',failed:'Failed',queued:'Queued',running:'Running'};
    const date=new Date(run.created_at);
    const when=Number.isNaN(date.getTime())?'Date unavailable':new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(date);
    const sources=roles.reduce((n,r)=>n+(Number(r.selected)||0),0), observations=roles.reduce((n,r)=>n+(Number(r.observations)||0),0);
    let summary=roles.length?`${roles.length} ${roles.length===1?'facet':'facets'} checked · ${sources} new or changed sources · ${observations} new observations`:'No facet results recorded.';
    if(state==='complete'&&!roles.length)summary='Nothing to analyze: no active facets had linked Spaces.';
    if(state==='queued')summary='Waiting for a worker to start the analysis.';
    if(state==='running')summary=roles.length?summary+' · analysis in progress':'Checking linked Space activity…';
    let delivery='Report delivery not recorded.';
    if(['queued','running'].includes(state))delivery='HFL report will be prepared after analysis.';
    else if(run.report_pending)delivery='HFL report pending delivery; it will be retried.';
    else if(run.report_delivery==='forwarded')delivery='HFL report queued for ingestion; not yet confirmed saved.';
    else if(run.report_delivery==='persisted')delivery='HFL report saved.';
    return `<article class="role-run"><header><span class="role-run-badge ${Object.hasOwn(labels,state)?state:''}">${esc(labels[state]||state||'Unknown')}</span><time datetime="${esc(run.created_at)}">${esc(when)}</time></header><p>${esc(summary)}</p>${run.error?`<p class="role-run-error">${esc(run.error)}</p>`:''}<p class="role-run-delivery">${esc(delivery)}</p><details data-run="${esc(run.id)}"><summary>Run details</summary>${roles.map(item=>`<section class="role-run-result"><strong>${esc(item.name)}</strong><p>${Number(item.selected)||0} sources checked · ${Number(item.observations)||0} new observations</p>${item.coverage?`<p class="role-help">${esc(item.coverage)}</p>`:''}${data.roles.some(r=>r.id===item.id)?`<button type="button" data-role="${esc(item.id)}" data-pane="journal">View agent journal</button>`:''}</section>`).join('')}<p class="role-help">Run ID <code>${esc(run.id)}</code></p></details></article>`;
  }
  function open(role, pane='soul') {
    current=role||{id:'',revision:0,name:'',color:'#3b82f6',soul:'',workspace_ids:[],entity_ids:[],archived:false,files:[],journal:[]};
    $('#role-editor').replaceChildren($('#role-form-template').content.cloneNode(true));
    for(const key of ['name','color','soul']) $('#role-form').elements[key].value=current[key];
    controls?.destroy();
    controls=window.RoleControls($('#role-form'), current, data, api, status);
    $('#role-archive').textContent=current.archived?'Restore facet':'Archive facet'; $('#role-archive').disabled=!current.id;
    $('#role-file-list').innerHTML=current.files.map(f=>`<article class="role-file"><strong><a href="/roles/data/${encodeURIComponent(current.id)}/attachments/${encodeURIComponent(f.id)}">${esc(f.name)}</a></strong><p>${esc(f.status)}${f.truncated?' · extraction truncated':''}</p>${f.error?`<p>${esc(f.error)}</p>`:''}<button type="button" data-preview-attachment="${esc(f.id)}" aria-label="Preview ${esc(f.name)}">Preview</button><button type="button" data-detach="${esc(f.id)}">Detach</button></article>`).join('');
    $('#role-journal').innerHTML=current.journal.map(n=>`<article class="role-observation"><small>${esc(n.created_at)} · ${esc(n.status)} · Agent inference</small><p>${esc(n.text)}</p><details><summary>Evidence</summary>${(n.evidence||[]).map(e=>`<p>${e.path?`<a href="/hfl-corpus/document/${esc(e.path.split('/').map(encodeURIComponent).join('/'))}#${encodeURIComponent(e.anchor||'')}" target="_blank" rel="noopener">${esc(e.title||e.id)}</a>`:esc(e.title||e.id)}</p>`).join('')}</details>${['approved','rejected','pending'].map(s=>`<button type="button" data-note="${esc(n.id)}" data-review="${s}">${s==='approved'?'Approve':s==='rejected'?'Reject':'Reset review'}</button>`).join('')}</article>`).join('')||'<p class="role-help">No observations yet. Link a Space, save, then run an analysis.</p>';
    root.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==pane);
    $('#role-files').addEventListener('change', updateUpload);
    $('#role-browse-files').onclick=()=>$('#role-files').click();
    $('#role-clear-files').onclick=()=>{$('#role-files').value='';updateUpload();};
    updateUpload();
    if(!current.files.length)$('#role-file-list').innerHTML='<p class="role-help">No attachments yet. Choose files above to add supporting context.</p>';
  }
  function updateUpload() {
    const files=[...$('#role-files').files];
    $('#role-pending-files').innerHTML=files.map((f,index)=>`<li><span>${esc(f.name)}</span><small>${(f.size/1024/1024).toFixed(2)} MB</small><button type="button" data-preview-file="${index}" aria-label="Preview ${esc(f.name)}">Preview</button></li>`).join('');
    const invalid=files.some(f=>f.size>20*1024*1024 || !/\.(pdf|docx|md|markdown|txt|png|jpe?g|webp|tiff?|bmp)$/i.test(f.name));
    const message=!current.id?'Save this facet before uploading files.':current.archived?'Restore this facet before adding files.':files.length>10?'Choose at most 10 files per upload.':files.length+current.files.length>20?'A facet can have up to 20 attachments.':invalid?'Use supported files of at most 20 MB each.':files.length?`${files.length} ${files.length===1?'file ready':'files ready'} to upload.`:'';
    $('#role-upload-status').textContent=message;
    $('#role-upload').disabled=!current.id||current.archived||!files.length||files.length>10||files.length+current.files.length>20||invalid;
    $('#role-clear-files').disabled=!files.length;
  }
  let previewUrl, previewVersion=0;
  const previewDialog=$('#role-file-preview'), previewContent=$('#role-file-preview-content');
  previewDialog.addEventListener('close',()=>{++previewVersion;previewContent.replaceChildren();if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=null;});
  $('#role-file-preview-close').onclick=()=>previewDialog.close();
  async function previewFile(index, attachment) {
    let file=attachment || $('#role-files')?.files[index];if(!file)return;
    if(previewUrl)URL.revokeObjectURL(previewUrl);
    const version=++previewVersion;
    $('#role-file-preview-title').textContent=file.name;
    previewContent.replaceChildren();previewDialog.showModal();
    if(attachment){
      previewContent.textContent='Loading preview…';
      try {
        const response=await fetch(`/roles/data/${encodeURIComponent(current.id)}/attachments/${encodeURIComponent(attachment.id)}`,{cache:'no-store'});
        if(!response.ok)throw Error('Unable to load this attachment. Try again.');
        const blob=await response.blob();if(version!==previewVersion)return;
        file=new File([blob],attachment.name,{type:blob.type});
        previewContent.replaceChildren();
      }catch(error){if(version===previewVersion)previewContent.textContent=error.message;return;}
    }
    if(/\.(png|jpe?g|webp|bmp)$/i.test(file.name)){
      previewUrl=URL.createObjectURL(file);const img=document.createElement('img');img.alt=file.name;img.src=previewUrl;
      img.onerror=()=>{if(version===previewVersion)previewContent.textContent='This image could not be displayed in your browser.';};previewContent.append(img);
    }else if(/\.pdf$/i.test(file.name)){
      previewUrl=URL.createObjectURL(new Blob([file],{type:'application/pdf'}));
      const frame=document.createElement('iframe');frame.title='PDF preview: '+file.name;frame.src=previewUrl;previewContent.append(frame);
      const link=document.createElement('a');link.href=previewUrl;link.target='_blank';link.rel='noopener';link.textContent='Open PDF in a new tab';previewContent.append(link);
    }else if(/\.(txt|md|markdown)$/i.test(file.name)){
      previewContent.textContent='Loading preview…';
      const text=await file.slice(0,200000).text();if(version!==previewVersion)return;
      const pre=document.createElement('pre');pre.textContent=text;previewContent.replaceChildren(pre);
      if(file.size>200000){const note=document.createElement('p');note.textContent='Preview limited to the first 200 KB.';previewContent.append(note);}
    }else if(attachment?.text){
      const note=document.createElement('p');note.textContent='Extracted text preview';
      const pre=document.createElement('pre');pre.textContent=attachment.text;previewContent.append(note,pre);
    }else previewContent.textContent='This format cannot be previewed in the browser. Open the original file on your device.';
  }
  async function save() {
    const form=$('#role-form'); if (!form.reportValidity()) return;
    const value={revision:current.revision,name:form.elements.name.value,color:form.elements.color.value,soul:form.elements.soul.value,archived:current.archived,
      workspace_ids:[...form.querySelectorAll('[name=spaces]:checked')].map(e=>e.value),entity_ids:controls.selectedIds()};
    current=await api('/data'+(current.id?'/'+current.id:''),current.id?'PUT':'POST',value); await load(); open(current); status('Facet saved. Existing shares retain their approved revision.');
  }
  root.addEventListener('submit',event=>{if(event.target.id==='role-form'){event.preventDefault();save().catch(e=>status(e.message));}});
  root.addEventListener('click',async event=>{const b=event.target.closest('button'); if(!b)return; try {
    if(b.hasAttribute('data-preview-file'))await previewFile(Number(b.dataset.previewFile));
    if(b.hasAttribute('data-preview-attachment'))await previewFile(null,current.files.find(f=>f.id===b.dataset.previewAttachment));
    if(b.dataset.role) open(data.roles.find(r=>r.id===b.dataset.role));
    if(b.id==='role-new') open();
    if(b.dataset.pane){root.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==b.dataset.pane); if(b.dataset.pane==='history'&&current.id){const h=await api('/data/'+current.id+'/history');$('#role-history').innerHTML=h.history.map(r=>`<details><summary>Revision ${r.revision} · ${esc(r.updated_at)}</summary><pre style="white-space:pre-wrap">${esc(r.soul)}</pre></details>`).join('');}}
    if(b.id==='role-archive'){current.archived=!current.archived;await save();}
    if(b.id==='role-upload'){
      const files=[...$('#role-files').files];if(!files.length){updateUpload();return;}
      const editor=$('#role-form'), draft={name:editor.elements.name.value,color:editor.elements.color.value,soul:editor.elements.soul.value,workspace_ids:[...editor.querySelectorAll('[name=spaces]:checked')].map(e=>e.value),entity_ids:controls.selectedIds()};
      const body=new FormData();files.forEach(f=>body.append('files',f));
      $('#role-upload-status').textContent='Uploading and extracting text… This may take a moment.';b.disabled=true;b.textContent='Processing…';$('#role-files').disabled=true;$('#role-clear-files').disabled=true;
      const identity=current.id;
      try {const updated=await api('/data/'+identity+'/attachments','POST',body);if(current.id===identity){open({...updated,...draft},'files');const failed=updated.files.filter(f=>f.status==='failed').length;$('#role-upload-status').textContent=failed?`Upload processed. ${failed} attachments need attention; review the errors below.`:'Files processed. Review the extracted text below before sharing.';}await load();}
      catch(error){if(current.id===identity){$('#role-upload-status').textContent=error.message;$('#role-files').disabled=false;b.textContent='Upload and extract';$('#role-clear-files').disabled=false;}return;}
    }
    if(b.dataset.detach){current=await api(`/data/${current.id}/attachments/${b.dataset.detach}/detach`,'POST',{revision:current.revision});await load();open(current);}
    if(b.dataset.note){current=await api(`/data/${current.id}/journal/${b.dataset.note}`,'POST',{revision:current.revision,status:b.dataset.review});await load();open(current);}
    if(b.id==='roles-analyze'){b.disabled=true;$('#role-analysis-status').textContent='Queueing analysis…';const r=await api('/analyze','POST',{});$('#role-analysis-status').textContent='Analysis queued. Run '+r.id;await load();}
  }catch(e){if(b.id==='roles-analyze')$('#role-analysis-status').textContent=e.message;else status(e.message);}finally{b.disabled=false;}});
  $('#roles-archived').addEventListener('change',list);
  load().catch(e=>status(e.message));
  setInterval(() => { if (data.runs.some(r=>['queued','running'].includes(r.status))) load().catch(e=>status(e.message)); }, 10000);
})();
