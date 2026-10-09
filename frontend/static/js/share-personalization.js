(() => {
  'use strict';
  const form = document.querySelector('[data-share-with-form]');
  const editor = document.querySelector('[data-social-form]');
  if (!form || !editor) return;
  const panel = form.closest('[data-personalization]');
  const field = name => form.elements.namedItem(name);
  const type = form.querySelector('#entity-type'), search = form.querySelector('#entity-search');
  const entityColor = color => /^#[0-9a-f]{6}$/i.test(color || '') ? color : '#95a7c3';
  const colorEntity = (element, color) => element.style.setProperty('--entity-color', entityColor(color));
  const status = form.querySelector('[data-entity-status]'), results = form.querySelector('[data-entity-results]');
  const error = form.querySelector('[data-share-with-error]');
  const workspaceSelector = form.querySelector('[data-workspace-selector]');
  const workspaceDot = color => {
    const dot = document.createElement('span'); dot.className = 'share-workspace-dot'; dot.setAttribute('aria-hidden', 'true');
    dot.style.backgroundColor = /^#[0-9a-f]{6}$/i.test(color || '') ? color : '#3b82f6'; return dot;
  };
  const updateWorkspaceSummary = () => {
    const inputs = [...form.querySelectorAll('[name="share_with_workspaces"]:checked')];
    const summary = form.querySelector('[data-workspace-summary]');
    summary.replaceChildren();
    if (!inputs.length) summary.textContent = field('workspace_confirmed').value ? 'No workspace context' : 'Choose workspaces';
    inputs.forEach(input => {
      const item = document.createElement('span'); item.className = 'share-workspace-name';
      item.append(workspaceDot(input.dataset.color), document.createTextNode(input.dataset.label)); summary.append(item);
    });
  };
  document.addEventListener('click', event => {
    if (!workspaceSelector.contains(event.target)) workspaceSelector.open = false;
  });
  workspaceSelector.addEventListener('keydown', event => {
    if (event.key === 'Escape') { workspaceSelector.open = false; workspaceSelector.querySelector('summary').focus(); }
  });
  const template = JSON.parse(form.querySelector('[data-personal-template]')?.textContent || 'null');
  if (template) {
    field('all_sources').checked = template.sources.includes('__all__');
    form.querySelector('[data-share-with-sources]').hidden = field('all_sources').checked;
    form.querySelectorAll('[name="sources"]').forEach(el => el.checked = template.sources.includes(el.value));
  }
  let controller, timer, loaded = false, selected = new Map(), busy = false;
  const showError = message => { error.textContent = message; error.hidden = !message; };
  const renderSelected = () => {
    const cards = form.querySelector('[data-selected-entities]'), values = form.querySelector('[data-selected-entity-values]');
    cards.replaceChildren(); values.replaceChildren();
    field('entity_id').value = selected.keys().next().value || '';
    for (const entity of selected.values()) {
      const input = document.createElement('input'); input.type='hidden'; input.name='entity_ids'; input.value=entity.id; values.append(input);
      const card=document.createElement('div'); card.className='selected-entity-card';
      colorEntity(card, entity.color);
      const content=document.createElement('span'), name=document.createElement('strong'), kind=document.createElement('span');
      name.className='entity-result-name'; name.textContent=entity.label;
      kind.className='entity-result-kind'; kind.textContent=entity.kind;
      content.append(name,document.createElement('br'),kind);
      const remove=document.createElement('button'); remove.type='button'; remove.className='btn btn-soft'; remove.textContent='Remove'; remove.setAttribute('aria-label','Remove '+entity.label);
      remove.onclick=()=>{selected.delete(entity.id);renderSelected();load();};
      card.append(content,remove);cards.append(card);
    }
    form.querySelector('[data-entity-selected]').textContent=selected.size ? `${selected.size} selected · matching activity will be combined.` : 'Choose entities to personalize this share.';
  };
  const load = async () => {
    controller?.abort(); const current = new AbortController(); controller = current;
    results.replaceChildren();
    status.textContent = 'Finding entities…';
    try {
      const response = await fetch('/sharing/personalization-options?' + new URLSearchParams({q:search.value,kind:type.value}), {signal:current.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Entity search failed.');
      if (controller !== current) return;
      if (!loaded) {
        for (const kind of data.types) if (kind !== 'people') type.add(new Option(kind, kind));
        type.add(new Option('All types', ''));
        const container = form.querySelector('[data-personal-workspaces]');
        const defaults = data.workspaces.filter(row => row.name.trim().toLowerCase() === 'default');
        for (const workspace of data.workspaces) {
          const label = document.createElement('label'); label.className = 'check';
          const input = document.createElement('input'); input.type = 'checkbox'; input.name = 'share_with_workspaces'; input.value = workspace.id; input.dataset.label = workspace.name; input.dataset.color = workspace.color || '#3b82f6';
          input.checked = template ? (template.activity.workspace_ids || []).includes(workspace.id) : defaults.length === 1 && workspace.id === defaults[0].id;
          input.addEventListener('change', () => { field('workspace_confirmed').value = 'on'; updateWorkspaceSummary(); showError(''); });
          label.append(input, workspaceDot(input.dataset.color), document.createTextNode(workspace.name)); container.append(label);
        }
        const missingSavedWorkspace = template && (template.activity.workspace_ids || []).some(id => !data.workspaces.some(row => row.id === id));
        if (missingSavedWorkspace) showError('A saved workspace is unavailable. Choose a workspace or No workspace context.');
        else if (template || defaults.length === 1) field('workspace_confirmed').value = 'on';
        else showError('Default workspace is unavailable or ambiguous. Choose a workspace or No workspace context.');
        updateWorkspaceSummary();
        loaded = true;
      }
      results.replaceChildren();
      for (const entity of data.entities) {
        if (selected.has(entity.id)) continue;
        const button = document.createElement('button'); button.type = 'button'; button.className = 'entity-result-card';
        colorEntity(button, entity.color);
        const name = document.createElement('span'); name.className = 'entity-result-name'; name.textContent = entity.label;
        const meta = document.createElement('span'); meta.className = 'entity-result-meta';
        const kind = document.createElement('span'); kind.className = 'entity-result-kind'; kind.textContent = entity.kind;
        const count = document.createElement('span'); count.className = 'entity-result-count'; count.textContent = `${entity.count} ${entity.count === 1 ? 'entry' : 'entries'}`;
        meta.append(kind, count); button.append(name, meta);
        button.addEventListener('click', () => {
          if (!selected.size && !field('recipient').value) field('recipient').value=entity.label;
          selected.set(entity.id, entity); renderSelected(); button.remove();
          status.textContent = 'Add more entities, review, or share.'; showError('');
        }); results.append(button);
      }
      status.textContent = `${data.total} matching entities${data.total > 50 ? '; showing 50. Refine your search.' : '.'}`;
    } catch (e) { if (e.name !== 'AbortError') showError(e.message); }
  };
  panel.addEventListener('toggle', () => { if (panel.open && !loaded) load(); });
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 300); });
  search.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
  type.addEventListener('change', load);
  field('all_sources').addEventListener('change', () => { form.querySelector('[data-share-with-sources]').hidden = field('all_sources').checked; });
  form.querySelector('[data-clear-entity]').addEventListener('click', () => {
    selected.clear(); field('recipient').value=''; renderSelected(); load();
  });
  form.querySelector('[data-no-workspace]').addEventListener('click', () => {
    form.querySelectorAll('[name="share_with_workspaces"]').forEach(el => el.checked = false);
    field('workspace_confirmed').value = 'on'; updateWorkspaceSummary(); showError('');
    workspaceSelector.open = false; workspaceSelector.querySelector('summary').focus();
  });
  const applyReview = data => {
    const cfg = data.configuration;
    for (const name of ['name','recipient','entity_id','entity_name','entity_kind','description','topic','context_prompt','date_from','date_to','date_field','from_days','auth_mode','allowed_email','device_limit','browser_redemption_limit']) {
      const input = editor.elements.namedItem(name); if (input) input.value = cfg[name] ?? '';
    }
    editor.elements.namedItem('configuration_id').value = '';
    editor.closest('.recipe-editor').querySelector('.recipe-heading h2').textContent = 'New recipe';
    editor.querySelector('[data-bound-entity-note]')?.remove();
    editor.elements.namedItem('recipient').readOnly = false;
    editor.querySelectorAll('[name="entity_ids"], [name="entity_template"], [data-bound-all-sources], [name="share_name"], [data-disabled-reference]').forEach(el => el.remove());
    const hidden = (name,value,attribute) => { const input=document.createElement('input'); input.type='hidden'; input.name=name; input.value=value; if(attribute) input.setAttribute(attribute,''); editor.append(input); };
    for (const id of cfg.entity_ids || []) hidden('entity_ids',id);
    if (cfg.entity_template) hidden('entity_template','on');
    if (cfg.sources.includes('__all__')) hidden('sources','__all__','data-bound-all-sources');
    editor.querySelectorAll('[data-specific-source]').forEach(el => el.checked = cfg.sources.includes('__all__') || cfg.sources.includes(el.value));
    editor.querySelectorAll('input[name="tags"]').forEach(el => {if (el.type === 'checkbox') el.checked=cfg.tags.includes(el.value); else el.remove();});
    for (const tag of cfg.tags) if (![...editor.querySelectorAll('input[name="tags"]')].some(el=>el.value===tag)) hidden('tags',tag);
    if (editor.elements.namedItem('corpus_scope')) editor.elements.namedItem('corpus_scope').value=cfg.corpus_scope || '';
    else if(cfg.corpus_scope) hidden('corpus_scope',cfg.corpus_scope);
    editor.querySelector('[data-inherited-rules]')?.remove();
    editor.querySelector('[data-workspace-reset]').hidden=!cfg.corpus_scope;
    editor.querySelector('[data-object-exclusions]').replaceChildren();
    editor.querySelector('[data-outside-board-values]').replaceChildren();
    editor.querySelectorAll('[name="excluded_object_ids"], [name="outside_board_ids"]').forEach(el=>el.remove());
    for (const id of cfg.activity.excluded_ids || []) { hidden('excluded_object_ids',id); editor.querySelector('[data-object-exclusions]').append(editor.lastElementChild); }
    for (const id of cfg.activity.outside_board_ids || []) { hidden('outside_board_ids',id); editor.querySelector('[data-outside-board-values]').append(editor.lastElementChild); }
    for (const id of cfg.disabled_reference_ids || []) hidden('disabled_reference_ids',id,'data-disabled-reference');
    editor.elements.namedItem('excluded_object_labels').value=JSON.stringify(cfg.activity.excluded_labels || {});
    editor.elements.namedItem('workspace_ids').value=cfg.activity.workspace_ids.join(',');
    editor.elements.namedItem('graph_view').value=JSON.stringify(cfg.activity.graph_view);
    editor.querySelectorAll('[name="activity_sections"][type="checkbox"]').forEach(el => el.checked=cfg.activity.sections.includes(el.value));
    editor.querySelectorAll('[name="automatic_sections"]').forEach(el => {el.checked=(cfg.activity.automatic || []).includes(el.value);el.disabled=true;});
    for (const name of ['references_enabled','include_secrets','include_completed','include_dismissed','single_use','no_expiry']) {
      const el=editor.querySelector(`input[type="checkbox"][name="${name}"]`); if(el) el.checked=!!(cfg.activity[name] ?? cfg[name]);
    }
    editor.querySelector('input[type="checkbox"][name="freeze_snapshot"]').checked=true;
    const expiry=editor.elements.namedItem('expires_at'), when=new Date(Date.now()+86400000);
    when.setMinutes(when.getMinutes()-when.getTimezoneOffset()); expiry.value=when.toISOString().slice(0,16); expiry.disabled=false; expiry.required=true;
    editor.querySelector('[data-preview-content]').innerHTML=data.preview;
    editor.dispatchEvent(new Event('recipeloaded'));
    editor.dispatchEvent(new Event('activitychange'));
    window.refreshShareActivity?.();
    editor.querySelector('[data-share-tab="entries"]').click();
    editor.scrollIntoView({behavior:'smooth',block:'start'});
  };
  const submit = async instant => {
    if (busy) return;
    if (!selected.size) { showError('Choose an entity first.'); return; }
    if (!field('workspace_confirmed').value) { showError('Choose a workspace or No workspace context.'); return; }
    controller?.abort(); clearTimeout(timer);
    busy=true; showError(''); status.textContent=instant ? 'Generating one-time QR…' : 'Loading the recipe preview…';
    const controls=[...form.elements]; const disabled=controls.map(el=>el.disabled);
    const body=new FormData(form); controls.forEach(el=>el.disabled=true);
    try {
      const response=await fetch('/sharing/share-with/' + (instant ? 'instant' : 'review'), {method:'POST',body,headers:{Accept:'application/json'}});
      const data=await response.json(); if(!response.ok) throw new Error(data.detail || 'Sharing could not complete.');
      if(instant) window.openPersonalizedShare(data,form.querySelector('[data-personal-instant]')); else applyReview(data);
      status.textContent=instant ? 'QR ready.' : 'Recipe loaded. Review and refine it in the editor.';
    } catch(e) { showError(e.message); status.textContent='Your selections are preserved.'; }
    finally { controls.forEach((el,index)=>el.disabled=disabled[index]); busy=false; }
  };
  form.addEventListener('submit', e=>{e.preventDefault();submit(false);});
  form.querySelector('[data-personal-instant]').addEventListener('click', ()=>submit(true));
  editor.querySelectorAll('[data-specific-source]').forEach(el=>el.addEventListener('change',()=>editor.querySelector('[data-bound-all-sources]')?.remove()));
  editor.elements.namedItem('recipient').readOnly=false;
})();
