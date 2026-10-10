(() => {
  const root = document.querySelector('[data-roles-csrf]'); if (!root) return;
  const $ = s => document.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let data = {roles:[], spaces:[], runs:[]}, current = null;
  const status = text => { $('#role-status').textContent = text; };
  async function api(path, method='GET', body) {
    const headers = {'X-CSRF-Token':root.dataset.rolesCsrf};
    if (body && !(body instanceof FormData)) { headers['Content-Type']='application/json'; body=JSON.stringify(body); }
    const response = await fetch('/roles'+path, {method, headers, body});
    const value = await response.json(); if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : 'Please check the fields and try again.'); return value;
  }
  async function load() { data=await api('/data'); list(); }
  function list() {
    $('#roles-list').innerHTML=data.roles.filter(r=>!r.archived||$('#roles-archived').checked).map(r=>`<button class="role-card" data-role="${esc(r.id)}"><span style="color:${esc(r.color)}">●</span> ${esc(r.name)}<small>${r.archived?'Archived':`${r.workspace_ids.length} linked Spaces`} · revision ${r.revision}</small></button>`).join('') || '<p class="role-help">No roles yet.</p>';
    $('#roles-runs').innerHTML=data.runs.map(r=>`<p>${esc(r.created_at)} · ${esc(r.status)}<br>${esc(r.error||'')}${r.report_pending?' · HFL report pending':''}</p>`).join('')||'<p>No analysis runs yet.</p>';
  }
  function open(role) {
    current=role||{id:'',revision:0,name:'',color:'#38bdf8',soul:'',workspace_ids:[],entity_ids:[],archived:false,files:[],journal:[]};
    $('#role-editor').replaceChildren($('#role-form-template').content.cloneNode(true));
    for(const key of ['name','color','soul']) $('#role-form').elements[key].value=current[key];
    $('#role-spaces').innerHTML=data.spaces.map(s=>`<label><input type="checkbox" name="spaces" value="${esc(s.id)}" ${current.workspace_ids.includes(s.id)?'checked':''}>${esc(s.name)}</label>`).join('')||'<p class="role-help">Create a Space in Activity Corpus first.</p>';
    $('#role-entities').innerHTML=current.entity_ids.map(id=>`<label><input type="checkbox" name="entities" value="${esc(id)}" checked>${esc(id)}</label>`).join('');
    $('#role-revision').textContent=current.id?`Revision ${current.revision}`:'New role';
    $('#role-archive').textContent=current.archived?'Restore role':'Archive role'; $('#role-archive').disabled=!current.id;
    $('#role-file-list').innerHTML=current.files.map(f=>`<article class="role-file"><strong>${esc(f.name)}</strong><p>${esc(f.status)}${f.truncated?' · extraction truncated':''}</p>${f.error?`<p>${esc(f.error)}</p>`:''}<details><summary>Review extraction</summary><pre>${esc(f.text)}</pre></details><button type="button" data-detach="${esc(f.id)}">Detach</button></article>`).join('');
    $('#role-journal').innerHTML=current.journal.map(n=>`<article class="role-observation"><small>${esc(n.created_at)} · ${esc(n.status)} · Agent inference</small><p>${esc(n.text)}</p><details><summary>Evidence</summary>${(n.evidence||[]).map(e=>`<p>${esc(e.title||e.id)}</p>`).join('')}</details>${['approved','rejected','pending'].map(s=>`<button type="button" data-note="${esc(n.id)}" data-review="${s}">${s==='approved'?'Approve':s==='rejected'?'Reject':'Reset review'}</button>`).join('')}</article>`).join('')||'<p class="role-help">No observations yet. Link a Space, save, then run an analysis.</p>';
  }
  async function save() {
    const form=$('#role-form'); if (!form.reportValidity()) return;
    const value={revision:current.revision,name:form.elements.name.value,color:form.elements.color.value,soul:form.elements.soul.value,archived:current.archived,
      workspace_ids:[...form.querySelectorAll('[name=spaces]:checked')].map(e=>e.value),entity_ids:[...form.querySelectorAll('[name=entities]:checked')].map(e=>e.value)};
    current=await api('/data'+(current.id?'/'+current.id:''),current.id?'PUT':'POST',value); await load(); open(current); status('Role saved. Existing shares retain their approved revision.');
  }
  root.addEventListener('submit',event=>{if(event.target.id==='role-form'){event.preventDefault();save().catch(e=>status(e.message));}});
  root.addEventListener('click',async event=>{const b=event.target.closest('button'); if(!b)return; try {
    if(b.dataset.role) open(data.roles.find(r=>r.id===b.dataset.role));
    if(b.id==='role-new') open();
    if(b.dataset.pane){root.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==b.dataset.pane); if(b.dataset.pane==='history'&&current.id){const h=await api('/data/'+current.id+'/history');$('#role-history').innerHTML=h.history.map(r=>`<details><summary>Revision ${r.revision} · ${esc(r.updated_at)}</summary><pre style="white-space:pre-wrap">${esc(r.soul)}</pre></details>`).join('');}}
    if(b.id==='role-preview'){const r=await api('/markdown','POST',{text:$('#role-form').elements.soul.value});$('#role-markdown').innerHTML=r.html;$('#role-markdown').hidden=false;}
    if(b.id==='role-archive'){current.archived=!current.archived;await save();}
    if(b.id==='role-load-entities'){const r=await api('/entities');$('#role-entities').innerHTML=r.entities.map(e=>`<label><input type="checkbox" name="entities" value="${esc(e.id)}" ${current.entity_ids.includes(e.id)?'checked':''}>${esc(e.label)}</label>`).join('');}
    if(b.id==='role-upload'){if(!current.id)throw Error('Save the role before uploading files.');const form=new FormData();for(const f of $('#role-files').files)form.append('files',f);status('Extracting attachments…');b.disabled=true;current=await api('/data/'+current.id+'/attachments','POST',form);await load();open(current);status('Attachments processed. Review their extraction before sharing.');}
    if(b.dataset.detach){current=await api(`/data/${current.id}/attachments/${b.dataset.detach}/detach`,'POST',{revision:current.revision});await load();open(current);}
    if(b.dataset.note){current=await api(`/data/${current.id}/journal/${b.dataset.note}`,'POST',{revision:current.revision,status:b.dataset.review});await load();open(current);}
    if(b.id==='roles-analyze'){b.disabled=true;const r=await api('/analyze','POST',{});status('Analysis queued. Run '+r.id);await load();}
  }catch(e){status(e.message);}finally{b.disabled=false;}});
  $('#roles-archived').addEventListener('change',list);
  load().catch(e=>status(e.message));
})();
