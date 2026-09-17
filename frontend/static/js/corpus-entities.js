(() => {
  const $ = id => document.getElementById(id);
  let items = [], page = 0, total = 0, hasLoaded = false;
  const pageSize = 50;
  const selectedEntities = new Set();
  let matchingItems = [], mergeBusy = false, mergePreview = null, mergeTarget = null, mergeRequest = '', submittedPayload = null;
  const selectedKinds = new Set(), selectedCategories = new Set(), selectedSources = new Set();
  const kinds = {people: 'People', companies: 'Organizations', tools: 'Tools', topics: 'Topics', objects: 'Referenced objects'};
  function pill(text) { const p = el('span', text); p.className = 'pill'; return p; }
  function refreshFilters() {
    $('filter-kind').replaceChildren();
    for (const [value, title] of [['', 'All types'], ...Object.entries(kinds)]) {
      const button = el('button', title); button.type = 'button'; button.className = 'pill';
      button.setAttribute('aria-pressed', String(value ? selectedKinds.has(value) : !selectedKinds.size));
      const count = el('span', String(items.filter(e => !value || e.kind === value).length)); count.className = 'pill-count'; button.append(count);
      button.onclick = () => { if (!value) selectedKinds.clear(); else if (selectedKinds.has(value)) selectedKinds.delete(value); else selectedKinds.add(value); page = 0; refreshFilters(); render(); };
      $('filter-kind').append(button);
    }
    for (const [id, selected, title] of [['category', selectedCategories, 'categories'], ['source', selectedSources, 'sources']]) {
      $(id + '-caption').textContent = selected.size ? `${selected.size} selected` : 'All ' + title;
    }
  }
  function checks(id, values, selected) {
    $(id).replaceChildren();
    for (const [value, title] of values) {
      const label = el('label'), input = el('input'); input.type = 'checkbox'; input.value = value; input.checked = selected.has(value);
      input.onchange = () => { if (input.checked) selected.add(value); else selected.delete(value); page = 0; refreshFilters(); render(); };
      label.append(input, el('span', title)); $(id).append(label);
    }
  }
  async function api(path = '', data) {
    const r = await fetch('/api/hfl/entities' + path, {method: data === undefined ? 'GET' : 'POST', headers: {'Content-Type': 'application/json'}, body: data === undefined ? undefined : JSON.stringify(data)});
    if (!r.ok) { const error = await r.json().catch(() => ({})); throw Error(typeof error.detail === 'string' ? error.detail : 'Request failed (' + r.status + '). Check your details and try again.'); }
    return r.json();
  }
  function el(tag, text = '') { const node = document.createElement(tag); node.textContent = text; return node; }
  function choices(id, values, first) {
    const selected = $(id).value; $(id).replaceChildren();
    for (const [value, label] of [['', first], ...values]) { const option = el('option', label); option.value = value; $(id).append(option); }
    if ([...$(id).options].some(o => o.value === selected)) $(id).value = selected;
  }
  function facets() {
    checks('filter-category', [['__none__', 'Uncategorized'], ...[...new Set(items.flatMap(e => e.categories))].sort().map(v => [v, v])], selectedCategories);
    checks('filter-source', [...new Set(items.flatMap(e => e.entries.map(x => x.source)))].sort().map(v => [v, v]), selectedSources);
    refreshFilters();
  }
  function editor(entity) {
    const details = el('details'); details.className = 'profile-editor'; details.append(el('summary', 'Edit profile'));
    const form = el('form'), grid = el('div'); grid.className = 'profile-fields';
    const fields = {}, profile = entity.profile || {};
    for (const [key, title, multiline, value] of [
      ['name', 'Display name', false, profile.name || entity.label],
      ['categories', 'Categories', true, (profile.categories || []).join('\n')],
      ['emails', 'Email addresses', true, (profile.emails || []).join('\n')],
      ['phones', 'Phone numbers', true, (profile.phones || []).join('\n')],
      ['references', 'References', true, (profile.references || []).join('\n')],
      ['notes', 'Notes', true, profile.notes || '']
    ]) {
      const label = el('label', title), input = el(multiline ? 'textarea' : 'input');
      input.name = key; input.value = value; input.defaultValue = value;
      if (multiline) input.rows = key === 'notes' ? 4 : 2;
      input.placeholder = {categories: 'One category per line', emails: 'One email address per line', phones: 'One phone number per line', references: 'One website, social-media URL, file link or absolute file path per line', notes: 'Add context, reminders or useful details…'}[key] || '';
      fields[key] = input;
      if (['emails', 'phones'].includes(key) && !['people', 'companies'].includes(entity.kind) && !(profile.emails?.length || profile.phones?.length)) continue;
      if (key === 'name') input.maxLength = 120;
      if (key === 'name') input.required = true;
      if (['notes', 'references'].includes(key)) label.className = 'profile-wide';
      fields[key] = input; label.append(input); grid.append(label);
    }
    const button = el('button', 'Save profile'), feedback = el('span'); feedback.className = 'profile-feedback'; feedback.setAttribute('role', 'status');
    const actions = el('div'); actions.className = 'profile-actions';
    const cancel = el('button', 'Cancel'); cancel.type = 'button'; cancel.className = 'profile-cancel';
    cancel.onclick = () => { form.reset(); feedback.textContent = ''; details.open = false; };
    button.className = 'profile-save'; actions.append(button, cancel, feedback);
    const hint = el('p', 'Saved details are kept when activity is refreshed.'); hint.className = 'profile-hint';
    form.append(grid, actions, hint);
    form.onsubmit = async event => {
      event.preventDefault(); button.disabled = true; feedback.textContent = 'Saving…';
      try {
        const data = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, ['categories', 'emails', 'phones', 'references'].includes(key) ? input.value.split('\n').map(v => v.trim()).filter(Boolean) : input.value]));
        entity.profile = (await api('/profile/' + encodeURIComponent(entity.id), data)).profile;
        entity.label = entity.profile.name; entity.categories = entity.profile.categories;
        facets(); render(); $('entity-status').textContent += ' Profile saved.';
      } catch (error) { feedback.textContent = error.message; } finally { button.disabled = false; }
    };
    details.append(form); return details;
  }
  function render() {
    const q = $('entity-query').value.trim().toLowerCase(), contact = $('filter-contact').value;
    const filtered = items.filter(e => {
      const p = e.profile || {}, searchable = [e.label, kinds[e.kind] || e.kind, ...e.categories, ...(p.emails || []), ...(p.phones || []), ...(p.references || []), p.notes || ''].join(' ').toLowerCase();
      return q.split(/\s+/).every(word => searchable.includes(word)) && (!selectedKinds.size || selectedKinds.has(e.kind)) && (!selectedCategories.size || [...selectedCategories].some(category => category === '__none__' ? !e.categories.length : e.categories.includes(category))) && (!selectedSources.size || e.entries.some(x => selectedSources.has(x.source))) && (!contact || (contact === 'contact' ? p.emails?.length || p.phones?.length : contact === 'curated' ? e.profile : !e.profile));
    });
    filtered.sort((a, b) => $('sort').value === 'activity' ? b.entries.length - a.entries.length || a.label.localeCompare(b.label) : $('sort').value === 'recent' ? (b.entries[0]?.date || '').localeCompare(a.entries[0]?.date || '') || a.label.localeCompare(b.label) : a.label.localeCompare(b.label));
    matchingItems = filtered;
    const selectionKind = items.find(e => selectedEntities.has(e.id))?.kind;
    $('selection-count').textContent = `${selectedEntities.size} selected${selectionKind ? ' · ' + kinds[selectionKind] : ''}`;
    $('merge-selected').disabled = selectedEntities.size < 2;
    const pages = Math.max(1, Math.ceil(filtered.length / pageSize)); page = Math.max(0, Math.min(page, pages - 1));
    $('entity-status').textContent = `${filtered.length} matching entities · ${items.length} of ${total} loaded · ${pageSize} per page`;
    $('page-number').textContent = `Page ${page + 1} of ${pages}`; $('previous').disabled = page === 0; $('next').disabled = page + 1 >= pages;
    $('entity-list').replaceChildren();
    if (!filtered.length) $('entity-list').append(el('p', 'No entities match. Clear a filter or try another search.'));
    for (const e of filtered.slice(page * pageSize, (page + 1) * pageSize)) {
      const card = el('details'); card.className = 'entity-card';
      const summary = el('summary'), title = el('span'); title.className = 'entity-title-row';
      const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.className = 'entity-select';
      checkbox.checked = selectedEntities.has(e.id); checkbox.disabled = Boolean(selectionKind && selectionKind !== e.kind);
      checkbox.setAttribute('aria-label', 'Select ' + e.label);
      checkbox.addEventListener('click', event => event.stopPropagation());
      checkbox.onchange = () => { checkbox.checked ? selectedEntities.add(e.id) : selectedEntities.delete(e.id); render(); };
      summary.append(checkbox);
      title.append(el('span', e.label), pill(kinds[e.kind] || e.kind));
      const meta = el('span'); meta.className = 'entity-detail-row';
      const count = el('span', `${e.entries.length} ${e.entries.length === 1 ? 'entry' : 'entries'}`); count.className = 'entity-count';
      meta.append(count, pill(e.resolution.replaceAll('-', ' ')));
      for (const category of e.categories.length ? e.categories : ['Uncategorized']) meta.append(pill(category));
      summary.append(title, meta); card.append(summary);
      if(e.merge?.active) meta.append(pill('Merged'));
      card.addEventListener('toggle', () => {
        if (!card.open || card.dataset.populated) return;
        card.dataset.populated = 'true';
        const mergeActions = el('div'); mergeActions.className = 'merge-card-actions';
        if (e.merge?.active) {
          const unmerge = el('button', 'Unmerge'); unmerge.type = 'button'; unmerge.onclick = () => openMerge(e); mergeActions.append(unmerge);
        }
        for (const decision of e.legacy_decisions || []) {
          const undo = el('button', 'Unmerge previous alias'); undo.type = 'button';
          undo.onclick = () => run(async () => { undo.disabled = true; undo.textContent = 'Unmerging…'; try { await api('/decisions/' + decision.id + '/undo', {}); await load(); } finally { undo.disabled = false; undo.textContent = 'Unmerge previous alias'; } });
          mergeActions.append(undo);
        }
        card.append(mergeActions);
        const audit = el('details'); audit.className = 'entity-audit'; audit.append(el('summary', 'Entity audit history'));
        audit.addEventListener('toggle', async () => {
          if (!audit.open || audit.dataset.loaded) return;
          audit.dataset.loaded = 'true'; const content = el('div', 'Loading history…'); content.setAttribute('role', 'status'); audit.append(content);
          try {
            const data = await api('/audit/' + encodeURIComponent(e.id)); content.replaceChildren();
            if (!data.events.length) content.append(el('p', 'No merge events recorded.'));
            for (const event of data.events) {
              content.append(el('p', `${event.created} · ${event.action} · ${event.actor}`));
              content.append(el('p', `${event.data.name} ← ${(event.data.members || []).map(m => m.label).join(', ')}`));
              if (event.data.evidence) content.append(el('p', event.data.evidence));
              const snapshot = el('details'); snapshot.append(el('summary', 'Preserved profile values'), el('pre', JSON.stringify(event.data, null, 2))); content.append(snapshot);
            }
          } catch (err) { content.textContent = err.message; audit.dataset.loaded = ''; }
        }); card.append(audit);
        if (e.profile) { const contactLine = el('p', [...(e.profile.emails || []), ...(e.profile.phones || []), e.profile.notes].filter(Boolean).join('\n')); contactLine.className = 'contact-line'; card.append(contactLine); }
        if (e.profile?.references?.length) {
          card.append(el('h2', 'References'));
          const list = el('ul');
          for (const reference of e.profile.references) {
            const row = el('li');
            if (/^https?:\/\//i.test(reference)) {
              const link = el('a', reference); link.href = reference; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link);
            } else { row.append(el('code', reference)); }
            list.append(row);
          }
          card.append(list);
        }
        card.append(editor(e), el('h2', 'Supporting activity'));
        if (!e.entries.length) card.append(el('p', 'No current supporting entries. Your saved profile remains available.'));
        for (const entry of e.entries) { const row = el('div'), link = el('a', entry.date.slice(0, 10) + ' · ' + entry.title); link.href = entry.href; const meta = el('p', entry.source + ' · ' + entry.method); meta.className = 'entity-meta'; row.append(link, meta, el('blockquote', entry.evidence)); card.append(row); }
      });
      $('entity-list').append(card);
    }
  }
  function setLoading(loading) {
    $('entity-loading').hidden = !loading;
    $('entity-results').hidden = loading || !hasLoaded;
    $('result-actions').hidden = loading || !hasLoaded;
    $('load-scope').hidden = loading || !hasLoaded;
    if (loading) $('entity-status').textContent = '';
    $('entity-list').setAttribute('aria-busy', String(loading));
    $('entity-filters').disabled = loading;
    $('entity-filters').inert = loading;
    $('entity-filters').setAttribute('aria-busy', String(loading));
    $('clear-filters').disabled = loading;
    $('reload-entities').disabled = loading;
    if (loading) {
      $('category-menu').open = false;
      $('source-menu').open = false;
    }
  }
  async function load() {
    setLoading(true);
    try {
      const data = await api();
      items = data.entities; total = data.total ?? items.length;
      const available = new Set(items.map(e => e.id));
      for (const id of selectedEntities) if (!available.has(id)) selectedEntities.delete(id);
      facets(); render();
      hasLoaded = true;
      $('load-scope').textContent = 'Search and filters cover the full directory. Type counts show all entities; results display 50 per page.';
    }
    finally { setLoading(false); }
  }
  function showJob(data, action = 'status') {
    $('job').textContent = JSON.stringify(data, null, 2);
    const summary = $('job-summary'); summary.replaceChildren();
    const job = data.job || (action === 'backfill' ? data : {});
    const state = job.state || (action === 'export' ? 'Export response received' : 'No active job');
    const heading = el('p', state.charAt(0).toUpperCase() + state.slice(1)); heading.className = 'job-state'; summary.append(heading);
    if (job.error) summary.append(el('p', job.error === 'RemoteCorpusError' ? 'The activity source could not be read. Check progress again after the source is available.' : 'Processing reported an error. Open technical details for more information.'));
    if (state === 'retrying') summary.append(el('p', 'The background worker is retrying this request.'));
    if (data.enrichment) {
      const e = data.enrichment;
      summary.append(el('p', `Last batch: ${e.processed ?? 0} processed · ${e.pending ?? 0} pending · ${e.removed ?? 0} removed.`));
    }
    if (action === 'export') summary.append(el('p', 'Open technical details to review the export result.'));
  }
  async function status() {
    const data = await api('/status'); showJob({job: data.job, enrichment: data.enrichment});
  }
  let matchingTimer;
  async function matchingStatus() {
    clearTimeout(matchingTimer);
    const data = await api('/matching');
    const running = data.jobs.some(job => ['pending','running'].includes(job.state));
    $('matching-status').textContent = !data.enabled ? 'Automatic matching is disabled.' : data.jobs.length ? data.jobs.map(job => {
      const counts = job.counts || {};
      return `${job.mode === 'history' ? 'Existing entities' : 'New enrichment'}: ${job.state} · ${counts.merged || 0} merged · ${counts.suggested || 0} for review · ${counts.pending || 0} pending${job.error ? ' · ' + job.error : ''}`;
    }).join('\n') : 'Ready. Future enrichment will trigger matching; start the one-time scan to check existing entities.';
    $('matching-suggestions').replaceChildren();
    for (const suggestion of data.suggestions) {
      const row = el('details'); row.append(el('summary', (suggestion.data.names || []).join(' ↔ ')));
      row.append(el('p', suggestion.data.decision?.reason || suggestion.data.review_reason || 'Review supporting evidence before merging.'));
      const evidence = el('pre', JSON.stringify(suggestion.data.decision?.facts || [], null, 2)); evidence.style.whiteSpace = 'pre-wrap'; row.append(evidence);
      const review = el('button', 'Review suggested merge'), dismiss = el('button', 'Keep separate');
      review.type = dismiss.type = 'button';
      review.onclick = () => {
        const ids = suggestion.data.entity_ids || [];
        if (ids.some(id => !items.some(item => item.id === id))) { $('matching-status').textContent = 'These entities have changed. Refresh entities and matching progress.'; return; }
        selectedEntities.clear(); ids.forEach(id => selectedEntities.add(id)); render(); openMerge();
        $('merge-evidence').value = suggestion.data.decision?.reason || '';
      };
      dismiss.onclick = async () => { dismiss.disabled = true; dismiss.textContent = 'Saving…'; try { await api('/matching/suggestions/' + suggestion.id + '/dismiss', {}); await matchingStatus(); } catch (err) { $('matching-status').textContent = err.message; dismiss.disabled = false; dismiss.textContent = 'Keep separate'; } };
      row.append(review, dismiss); $('matching-suggestions').append(row);
    }
    if (!data.suggestions.length) $('matching-suggestions').append(el('p', 'No uncertain matches awaiting review.'));
    if (data.suggestions_total > data.suggestions.length) $('matching-suggestions').prepend(el('p', `Showing ${data.suggestions.length} of ${data.suggestions_total} suggestions. Review or dismiss these to see more.`));
    if (running) matchingTimer = setTimeout(() => run(matchingStatus), 10000);
  }
  $('matching-refresh').onclick = () => run(matchingStatus);
  $('matching-scan').onclick = async () => {
    const button = $('matching-scan'); button.disabled = true; button.textContent = 'Queuing scan…';
    try { await api('/matching/scan', {}); await matchingStatus(); }
    catch (err) { $('matching-status').textContent = err.message; }
    finally { button.disabled = false; button.textContent = 'Scan existing entities once / resume'; }
  };
  async function run(fn) { try { await fn(); } catch (e) { $('entity-status').textContent = e.message; } }
  for (const id of ['entity-query', 'filter-contact', 'sort']) $(id).addEventListener(id === 'entity-query' ? 'input' : 'change', () => { page = 0; render(); });
  $('clear-filters').onclick = () => { $('entity-query').value = ''; $('filter-contact').value = ''; selectedKinds.clear(); selectedCategories.clear(); selectedSources.clear(); page = 0; facets(); render(); };
  document.addEventListener('click', event => { for (const id of ['category-menu', 'source-menu']) if (!$(id).contains(event.target)) $(id).open = false; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') for (const id of ['category-menu', 'source-menu']) $(id).open = false; });
  $('reload-entities').onclick = () => run(load);
  $('previous').onclick = () => { page--; render(); }; $('next').onclick = () => { page++; render(); };
  $('status-refresh').onclick = () => run(status);
  $('backfill').onclick = () => run(async () => { showJob(await api('/backfill', {}), 'backfill'); });
  $('export').onclick = () => run(async () => { showJob(await api('/export', {}), 'export'); });
  function selectMany(rows) {
    const kind = items.find(e => selectedEntities.has(e.id))?.kind;
    const eligible = kind ? rows.filter(e => e.kind === kind) : rows;
    if (new Set(eligible.map(e => e.kind)).size > 1) { $('selection-feedback').textContent = 'Filter to one entity type or select one entity first.'; return; }
    eligible.forEach(e => selectedEntities.add(e.id));
    $('selection-feedback').textContent = kind ? `Selected matching ${kinds[kind].toLowerCase()}; other types were excluded.` : '';
    render();
  }
  $('select-page').onclick = () => selectMany(matchingItems.slice(page * pageSize, (page + 1) * pageSize));
  $('select-matching').onclick = () => selectMany(matchingItems);
  $('clear-selection').onclick = () => { selectedEntities.clear(); $('selection-feedback').textContent = ''; render(); };
  function waiting(busy, message = '') {
    mergeBusy = busy; $('merge-wait').hidden = !busy; $('merge-wait-text').textContent = message;
    for (const id of ['merge-close','merge-review','merge-name','merge-evidence']) $(id).disabled = busy;
    $('merge-preview-content').querySelectorAll('[data-merge-field]').forEach(input => input.disabled = busy);
    $('merge-confirm').disabled = busy || (!mergeTarget && !mergePreview);
    $('entity-merge-form').setAttribute('aria-busy', String(busy));
  }
  function openMerge(target = null) {
    mergeTarget = target; mergePreview = null; submittedPayload = null; mergeRequest = crypto.randomUUID();
    $('merge-name').value = target?.label || items.find(e => selectedEntities.has(e.id))?.label || '';
    $('merge-name').required = !target; $('merge-name-label').hidden = Boolean(target); $('merge-evidence').value = '';
    $('merge-preview-content').replaceChildren(); $('merge-preview-content').hidden = true; $('merge-feedback').textContent = '';
    $('merge-review').hidden = Boolean(target);
    $('entity-merge-title').textContent = target ? 'Unmerge entity' : 'Merge entities';
    $('merge-confirm').textContent = target ? 'Confirm unmerge' : 'Confirm merge';
    $('merge-description').textContent = target ? `Restore the entities grouped into “${target.label}”. Later profile edits remain in audit history. Nested groups remain merged until separately unmerged.` : `Combine ${selectedEntities.size} entities into one. Original profiles and evidence remain available for reversal.`;
    waiting(false); $('entity-merge-dialog').showModal();
  }
  $('merge-selected').onclick = () => openMerge();
  $('merge-close').onclick = () => { if (!mergeBusy) $('entity-merge-dialog').close(); };
  $('entity-merge-dialog').addEventListener('cancel', event => { if (mergeBusy) event.preventDefault(); });
  for (const id of ['merge-name','merge-evidence']) $(id).oninput = () => { mergePreview = null; submittedPayload = null; mergeRequest = crypto.randomUUID(); $('merge-preview-content').hidden = true; waiting(false); };
  function mergeFieldValues() {
    return Object.fromEntries([...$('merge-preview-content').querySelectorAll('[data-merge-field]')].map(input => [input.dataset.mergeField,
      input.dataset.mergeField === 'notes' ? input.value : input.value.split('\n').map(v => v.trim()).filter(Boolean)]));
  }
  $('merge-review').onclick = async () => {
    if (!$('entity-merge-form').reportValidity()) return;
    const edits = mergeFieldValues();
    waiting(true, 'Reading entities and combining profile fields…'); $('merge-feedback').textContent = '';
    try {
      mergePreview = await api('/merge-preview', {entity_ids:[...selectedEntities], name:$('merge-name').value, evidence:$('merge-evidence').value});
      const preview = $('merge-preview-content'); preview.replaceChildren(); preview.hidden = false;
      preview.append(el('h3', `${mergePreview.members.length} entities · ${mergePreview.unique_entries} unique supporting entries`));
      const list = el('ul'); mergePreview.members.forEach(m => list.append(el('li', m.label))); preview.append(list);
      const review = el('section'); review.className = 'merged-details-review';
      preview.append(review);
      review.append(el('h2', 'Merged details review'));
      review.append(el('p', 'Edit the combined details below before confirming. Use one value per line for categories, emails, phones and references. Original profiles are retained for Unmerge.'));
      for (const key of ['categories','emails','phones','references','notes']) {
        const label = el('label', key.charAt(0).toUpperCase() + key.slice(1)), input = el('textarea');
        const value = Object.hasOwn(edits, key) ? edits[key] : mergePreview.profile[key];
        input.dataset.mergeField = key; input.rows = key === 'notes' ? 5 : 2;
        input.value = Array.isArray(value) ? value.join('\n') : value;
        input.placeholder = key === 'notes' ? 'Add or revise notes' : 'One value per line';
        input.oninput = () => { submittedPayload = null; mergeRequest = crypto.randomUUID(); };
        label.append(input); review.append(label);
      }
    } catch (err) { mergePreview = null; $('merge-feedback').textContent = err.message; }
    finally { waiting(false); }
  };
  $('entity-merge-form').onsubmit = async event => {
    event.preventDefault(); if (mergeBusy || (!mergeTarget && !mergePreview)) return;
    waiting(true, mergeTarget ? 'Restoring original entities and saving the audit event…' : 'Merging entities and saving the audit event…');
    $('merge-feedback').textContent = '';
    try {
      submittedPayload ||= mergeTarget ? {request_id:mergeRequest, evidence:$('merge-evidence').value} : {entity_ids:[...selectedEntities], name:$('merge-name').value, evidence:$('merge-evidence').value, profile:mergeFieldValues(), preview_token:mergePreview.preview_token, request_id:mergeRequest};
      const result = await api(mergeTarget ? '/merges/' + encodeURIComponent(mergeTarget.id) + '/unmerge' : '/merges', submittedPayload);
      selectedEntities.clear(); $('entity-merge-dialog').close();
      try { await load(); } catch (err) { $('entity-status').textContent = 'Operation completed, but the directory could not refresh: ' + err.message; }
      $('selection-feedback').textContent = result.action === 'unmerged' ? 'Unmerged. Original entities restored; audit event saved.' : 'Merged. New entity created; audit event saved. Clear search or filters if it is not visible.';
      run(matchingStatus);
    } catch (err) { $('merge-feedback').textContent = err.message; }
    finally { waiting(false); }
  };
  run(async () => { await load(); await status(); await matchingStatus(); });
})();
