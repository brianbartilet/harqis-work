/* Roles adaptations of share-personalization's Space and entity pickers. */
window.RoleControls = (form, role, catalog, api, report) => {
  const $ = selector => form.querySelector(selector);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const color = value => /^#[\da-f]{6}$/i.test(value || '') ? value : '#3b82f6';
  let alive = true, sequence = 0, timer, markdownSequence = 0;
  const selected = new Map(role.entity_ids.map(id => [id, {id, label:'Loading entity…'}]));
  const palette = [...new Set([...(catalog.palette || []), role.color])];
  $('#role-colors').innerHTML = palette.map(c => `<button type="button" class="role-swatch" style="--swatch:${color(c)}" aria-label="Color ${escape(c)}" aria-pressed="${c === role.color}" data-color="${escape(c)}"></button>`).join('');
  $('#role-colors').onclick = event => {
    const button = event.target.closest('[data-color]'); if (!button) return;
    form.elements.color.value = button.dataset.color;
    $('#role-colors').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
  };
  const dot = c => `<span class="role-space-dot" style="background:${color(c)}" aria-hidden="true"></span>`;
  $('#role-spaces').innerHTML = catalog.spaces.map(s => `<label><input type="checkbox" name="spaces" value="${escape(s.id)}" ${role.workspace_ids.includes(s.id)?'checked':''}>${dot(s.color)}${escape(s.name)}</label>`).join('') || '<p class="role-help">Create a Space in Organize → Spaces first.</p>';
  const summarizeSpaces = () => {
    const ids = new Set([...form.querySelectorAll('[name=spaces]:checked')].map(e => e.value));
    $('#role-space-summary').innerHTML = catalog.spaces.filter(s => ids.has(s.id)).map(s => `<span>${dot(s.color)}${escape(s.name)}</span>`).join('') || 'Choose Spaces';
  };
  summarizeSpaces(); $('#role-spaces').onchange = summarizeSpaces;
  const picker = $('#role-space-picker');
  const closeOutside = event => { if (!picker.contains(event.target)) picker.open = false; };
  document.addEventListener('click', closeOutside);
  picker.onkeydown = event => { if (event.key === 'Escape') { picker.open = false; picker.querySelector('summary').focus(); } };
  $('#role-clear-spaces').onclick = () => { form.querySelectorAll('[name=spaces]').forEach(e => e.checked=false); summarizeSpaces(); picker.open=false; picker.querySelector('summary').focus(); };
  const renderSelected = () => {
    $('#role-entity-selected').textContent = selected.size ? `${selected.size} selected` : 'Choose entities related to this facet.';
    $('#role-selected-entities').innerHTML = [...selected.values()].map(e => `<div class="role-selected-entity" style="--entity-color:${color(e.color)}"><span><strong>${escape(e.label)}</strong>${e.kind?`<br><span class="role-entity-kind">${escape(e.kind)}</span>`:''}</span><button type="button" data-remove-entity="${escape(e.id)}" aria-label="Remove ${escape(e.label)}">Remove</button></div>`).join('');
    $('#role-clear-entities').disabled = !selected.size;
    $('#role-entities').querySelectorAll('[data-entity]').forEach(b => b.setAttribute('aria-pressed',String(selected.has(b.dataset.entity))));
  };
  let matches = [];
  async function search() {
    const request = ++sequence;
    $('#role-entity-status').textContent = 'Finding entities…';
    try {
      const result = await api('/entities?' + new URLSearchParams({q:$('#role-entity-search').value,kind:$('#role-entity-type').value,selected:[...selected.keys()].join(',')}));
      if (!alive || request !== sequence) return;
      const type = $('#role-entity-type'), value = type.value;
      type.replaceChildren(...[...new Set(['people',...result.types])].map(kind => new Option(kind,kind)),new Option('All types','')); type.value=value;
      const resolved = new Map(result.selected.map(e => [e.id, e]));
      selected.forEach((entity, id) => selected.set(id, resolved.get(id) || {
        id, label: 'Unavailable entity', kind: 'Merged or removed · remove or replace this link'
      }));
      matches = result.entities;
      $('#role-entities').innerHTML = matches.map(e => `<button type="button" data-entity="${escape(e.id)}" aria-pressed="${selected.has(e.id)}"><strong>${escape(e.label)}</strong><span class="role-entity-meta"><span style="--entity-color:${color(e.color)}">${escape(e.kind)}</span><small>${e.count} ${e.count===1?'entry':'entries'}</small></span></button>`).join('');
      $('#role-entity-status').textContent = `${result.total} matching entities${result.total>50?'; showing 50. Refine your search.':'.'}`;
      renderSelected();
    } catch (error) { if (alive && request===sequence) $('#role-entity-status').textContent=error.message+' Change the search to retry.'; }
  }
  $('#role-entities').onclick = event => {
    const button = event.target.closest('[data-entity]'); if (!button) return;
    const entity = matches.find(e => e.id===button.dataset.entity);
    if (selected.has(entity.id)) selected.delete(entity.id);
    else if (selected.size<100) selected.set(entity.id,entity);
    else report('Choose up to 100 related entities.');
    renderSelected();
  };
  $('#role-selected-entities').onclick = event => { const b=event.target.closest('[data-remove-entity]'); if(b){selected.delete(b.dataset.removeEntity);renderSelected();} };
  $('#role-clear-entities').onclick = () => {selected.clear();renderSelected();};
  $('#role-entity-type').onchange = search;
  $('#role-entity-search').oninput = () => {++sequence;clearTimeout(timer);timer=setTimeout(search,300);};
  $('#role-entity-search').onkeydown = event => {if(event.key==='Enter')event.preventDefault();};
  const textarea=form.elements.soul, markdown=$('#role-markdown');
  const edit = () => {++markdownSequence;markdown.hidden=true;textarea.hidden=false;textarea.focus();};
  markdown.onclick = event => {if(!event.target.closest('a'))edit();};
  markdown.onkeydown = event => {if(event.target===markdown && ['Enter',' '].includes(event.key)){event.preventDefault();edit();}};
  async function renderMarkdown() {
    const request=++markdownSequence, text=textarea.value;
    try {
      const result=await api('/markdown','POST',{text});
      if(!alive || request!==markdownSequence || document.activeElement===textarea || textarea.value!==text)return;
      markdown.innerHTML=result.html || '<p class="role-help">Click to write your Soul in Markdown.</p>';
      textarea.hidden=true;markdown.hidden=false;
    } catch(error){if(alive)report(error.message);}
  }
  textarea.onfocus=()=>{++markdownSequence;}; textarea.onblur=renderMarkdown;
  if(role.soul)renderMarkdown();
  renderSelected(); search();
  return {selectedIds:()=>[...selected.keys()],destroy:()=>{alive=false;clearTimeout(timer);document.removeEventListener('click',closeOutside);}};
};
