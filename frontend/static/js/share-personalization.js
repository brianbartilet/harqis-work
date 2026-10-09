(() => {
  'use strict';
  const form = document.querySelector('[data-social-form]');
  if (!form) return;
  const panel = form.querySelector('[data-personalization]');
  const field = name => form.elements.namedItem(name);
  const search = panel.querySelector('#entity-search');
  const type = panel.querySelector('#entity-type');
  const status = panel.querySelector('[data-entity-status]');
  const results = panel.querySelector('[data-entity-results]');
  const instant = form.querySelector('[data-personal-instant]');
  const allSources = panel.querySelector('[data-entity-all-sources]');
  let controller, timer, loaded = false, revision = 0, reviewed = -1;
  const update = () => {
    const bound = !!field('entity_id').value;
    field('recipient').readOnly = bound;
    instant.hidden = !bound;
    panel.querySelector('[data-entity-selected]').textContent = bound ?
      `Selected: ${field('entity_name').value} · ${field('entity_kind').value}` : 'Choose one entity to personalize this share.';
  };
  const clearExclusions = () => {
    form.querySelector('[data-object-exclusions]')?.replaceChildren();
    form.querySelectorAll('[data-disabled-reference]').forEach(el => el.remove());
    field('excluded_object_labels').value = '{}';
    form.querySelector('[data-outside-board-values]')?.replaceChildren();
  };
  const changed = () => { update(); form.dispatchEvent(new Event('activitychange')); };
  form.addEventListener('formdata', event => {
    if (allSources.checked && (field('entity_id').value || field('entity_template').checked)) {
      event.formData.delete('sources'); event.formData.append('sources', '__all__');
    }
  });
  allSources.addEventListener('change', changed);
  field('entity_template').addEventListener('change', changed);
  form.querySelectorAll('[data-specific-source]').forEach(input => input.addEventListener('change', () => { allSources.checked = false; }));
  const load = async () => {
    controller?.abort();
    const current = new AbortController(); controller = current;
    status.textContent = 'Finding entities…';
    try {
      const response = await fetch('/sharing/personalization-options?' + new URLSearchParams({q:search.value, kind:type.value}), {signal:current.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Entity search failed.');
      if (controller !== current) return;
      if (!loaded) {
        for (const kind of data.types) type.add(new Option(kind, kind));
        const container = panel.querySelector('[data-personal-workspaces]');
        const selected = new Set(field('workspace_ids').value.split(',').filter(Boolean));
        const available = new Set(data.workspaces.map(row => row.id));
        for (const id of selected) if (!available.has(id)) data.workspaces.push({id, name:`Unavailable workspace (${id})`});
        for (const workspace of data.workspaces) {
          const label = document.createElement('label'); label.className = 'check';
          const input = document.createElement('input'); input.type = 'checkbox'; input.value = workspace.id; input.checked = selected.has(workspace.id);
          input.addEventListener('change', () => {
            field('workspace_ids').value = [...container.querySelectorAll('input:checked')].map(el=>el.value).join(','); changed();
          });
          label.append(input, document.createTextNode(workspace.name)); container.append(label);
        }
        if (!data.workspaces.length) container.textContent = 'No saved workspaces. Create one in Activity Corpus first.';
        loaded = true;
      }
      results.replaceChildren();
      for (const entity of data.entities) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-soft';
        button.textContent = `${entity.label} · ${entity.kind} · ${entity.count} entries · ${entity.id.slice(-8)}`;
        button.addEventListener('click', () => {
          field('entity_id').value = entity.id; field('entity_name').value = entity.label; field('entity_kind').value = entity.kind;
          field('recipient').value = entity.label;
          results.replaceChildren(); status.textContent = 'Entity selected. Review the included content before sharing.'; changed();
        });
        results.append(button);
      }
      status.textContent = `${data.total} matching entities${data.total > 50 ? '; showing 50. Refine your search.' : '.'}`;
    } catch (error) { if (error.name !== 'AbortError') status.textContent = error.message; }
  };
  panel.addEventListener('toggle', () => { if (panel.open && !loaded) load(); });
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 300); });
  type.addEventListener('change', load);
  panel.querySelector('[data-clear-entity]').addEventListener('click', () => {
    for (const name of ['entity_id', 'entity_name', 'entity_kind', 'recipient']) field(name).value = '';
    changed();
  });
  panel.querySelector('#quick-template').addEventListener('change', event => {
    if (!event.target.value) return;
    field('entity_template').checked = true;
    field('configuration_id').value = '';
    clearExclusions();
    for (const name of ['entity_id','entity_name','entity_kind','recipient','topic','context_prompt','description']) field(name).value = '';
    if (field('corpus_scope')) field('corpus_scope').value = '';
    form.querySelector('[data-inherited-rules]')?.remove();
    form.querySelectorAll('input[name="tags"]').forEach(el=> { if (el.type === 'checkbox') el.checked = false; else el.remove(); });
    const days = form.querySelector('#share-from-days');
    if (days) { days.value = '0'; days.dispatchEvent(new Event('change', {bubbles:true})); }
    field('name').value = event.target.value === 'entity' ? 'Activity with an entity' : 'Entity activity and workspace context';
    form.querySelectorAll('[data-specific-source]').forEach(el=>el.checked = true);
    allSources.checked = true;
    form.querySelectorAll('input[type="checkbox"][name="activity_sections"]').forEach(el=>el.checked = true);
    form.querySelector('input[type="checkbox"][name="freeze_snapshot"]').checked = true;
    form.querySelector('input[type="checkbox"][name="freeze_snapshot"]').dispatchEvent(new Event('change', {bubbles:true}));
    field('include_completed').checked = false; field('include_dismissed').checked = false;
    if (field('include_secrets')) field('include_secrets').checked = false;
    field('references_enabled').checked = false;
    if (event.target.value === 'entity') {
      field('workspace_ids').value = '';
      panel.querySelectorAll('[data-personal-workspaces] input').forEach(el=>el.checked = false);
    }
    status.textContent = event.target.value === 'workspace' ? 'Choose an entity and the workspaces to add.' : 'Choose an entity.';
    changed();
  });
  const invalidate = () => { revision++; reviewed = -1; instant.disabled = true; };
  form.addEventListener('input', invalidate);
  form.addEventListener('change', invalidate);
  form.addEventListener('activitychange', invalidate);
  const preview = form.querySelector('[data-preview-content]');
  new MutationObserver(() => {
    if (preview.getAttribute('aria-busy') !== 'true' && preview.querySelector('[data-preview-ready]')) {
      instant.disabled = false;
    }
  }).observe(preview, {childList:true, subtree:true, attributes:true, attributeFilter:['aria-busy']});
  panel.querySelector('[data-personal-review]').addEventListener('click', event => {
    event.preventDefault(); form.querySelector('[data-share-tab="entries"]').click();
  });
  instant.addEventListener('click', async () => {
    if (!form.reportValidity()) return;
    if (reviewed !== revision) {
      form.querySelector('[data-share-tab="entries"]').click(); reviewed = revision;
      instant.textContent = 'Generate Instant Share QR';
      return;
    }
    instant.disabled = true;
    try {
      const response = await fetch('/sharing/instant', {method:'POST', body:new FormData(form), headers:{Accept:'application/json'}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Instant share failed.');
      window.openPersonalizedShare(data, instant);
    } catch(error) { window.alert(error.message); }
    finally { instant.disabled = false; }
  });
  update();
  if (panel.open) load();
})();
