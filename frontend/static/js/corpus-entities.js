(() => {
  const $ = id => document.getElementById(id);
  let items = [], page = 0, total = 0, hasLoaded = false;
  let loadVersion = 0;
  const pageSize = 50;
  const selectedEntities = new Set();
  let typeBusy = false, typeSelection = [];
  let matchingItems = [], mergeBusy = false, mergePreview = null, mergeTarget = null, mergeRequest = '', submittedPayload = null;
  const selectedKinds = new Set(), selectedCategories = new Set(), selectedSources = new Set();
  let suggestions = [], suggestionEntities = [], visibleSuggestions = [], suggestionLimit = 100, batchGroups = [], batchBusy = false;
  const selectedSuggestions = new Set();
  let dismissBusy = false;
  let suggestionEntityById = new Map(), entityById = new Map();
  const suggestionNodes = new Map();
  const kinds = {people: 'People', companies: 'Organizations', tools: 'Tools', topics: 'Topics', objects: 'Referenced objects'};
  const kindColors = {people:'#ffbd91', companies:'#deafff', tools:'#70edbd', topics:'#9bafff', objects:'#e9c96c'};
  const sourceValue = entry => String(entry.source || '').trim();
  function pill(text) { const p = el('span', text); p.className = 'pill'; return p; }
  function typePill(kind) { const node = pill((kinds[kind] || kind || 'Unavailable').toLowerCase()); node.classList.add('entity-kind'); node.style.setProperty('--entity-color', kindColors[kind] || '#95a7c3'); return node; }
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
    const filterEntities = [...items, ...suggestionEntities];
    checks('filter-category', [['__none__', 'Uncategorized'], ...[...new Set(filterEntities.flatMap(e => e.categories))].sort().map(v => [v, v])], selectedCategories);
    checks('filter-source', [...new Set(filterEntities.flatMap(e => e.entries.map(sourceValue)))].sort().map(v => [v, v || 'Unspecified source']), selectedSources);
    refreshFilters();
  }
  function editor(entity) {
    const details = el('details'); details.className = 'profile-editor'; details.append(el('summary', 'Edit profile'));
    const form = el('form'), grid = el('div'); grid.className = 'profile-fields';
    const fields = {}, profile = entity.profile || {};
    for (const [key, title, multiline, value] of [
      ['name', 'Display name', false, profile.name || entity.label],
      ['aliases', 'Aliases (one per line)', true, (profile.aliases || []).join('\n')],
      ['partial_aliases', 'Partial matching hints (one per line)', true, (profile.partial_aliases || []).join('\n')],
      ['categories', 'Categories', true, (profile.categories || []).join('\n')],
      ['emails', 'Email addresses', true, (profile.emails || []).join('\n')],
      ['phones', 'Phone numbers', true, (profile.phones || []).join('\n')],
      ['references', 'References', true, (profile.references || []).join('\n')],
      ['notes', 'Notes', true, profile.notes || '']
    ]) {
      const label = el('label', title), input = el(multiline ? 'textarea' : 'input');
      input.name = key; input.value = value; input.defaultValue = value;
      if(key==='name'&&entity.is_owner){input.readOnly=true;input.title='Update your owner name in /profile';}
      if (multiline) input.rows = key === 'notes' ? 4 : 2;
      input.placeholder = {categories: 'One category per line', emails: 'One email address per line', phones: 'One phone number per line', references: 'One website, social-media URL, file link or absolute file path per line', notes: 'Add context, reminders or useful details…'}[key] || '';
      fields[key] = input;
      if (['emails', 'phones'].includes(key) && !['people', 'companies'].includes(entity.kind) && !(profile.emails?.length || profile.phones?.length)) continue;
      if (key === 'name') input.maxLength = 120;
      if (key === 'name') input.required = true;
      if (['notes', 'references'].includes(key)) label.className = 'profile-wide';
      fields[key] = input; label.append(input); grid.append(label);
    }
    const preferredLabel = el('label', 'Prefer this display name during automatic merges'), preferred = el('input'); preferred.type = 'checkbox'; preferred.checked = !!profile.preferred_name; preferred.defaultChecked = preferred.checked; preferredLabel.prepend(preferred); grid.append(preferredLabel);
    const provenance = el('p', Object.entries(profile.alias_sources || {}).map(([name, source]) => `${name}: ${source}`).join(' · ')); grid.append(provenance);
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
        const data = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, ['categories', 'emails', 'phones', 'references', 'aliases', 'partial_aliases'].includes(key) ? input.value.split('\n').map(v => v.trim()).filter(Boolean) : input.value]));
        data.preferred_name = preferred.checked;
        entity.profile = (await api('/profile/' + encodeURIComponent(entity.id), data)).profile;
        entity.label = entity.profile.name; entity.categories = entity.profile.categories;
        for (const input of Object.values(fields)) input.defaultValue = input.value;
        facets(); render(); $('entity-status').textContent += ' Profile saved.';
      } catch (error) { feedback.textContent = error.message; } finally { button.disabled = false; }
    };
    details.append(form); return details;
  }
  function matchesFilters(e) {
    const q = $('entity-query').value.trim().toLowerCase(), contact = $('filter-contact').value;
    const p = e.profile || {}, searchable = [e.label, kinds[e.kind] || e.kind, ...e.categories, ...(p.aliases || []), ...(p.partial_aliases || []), ...(p.emails || []), ...(p.phones || []), ...(p.references || []), p.notes || ''].join(' ').toLowerCase();
    return q.split(/\s+/).every(word => searchable.includes(word)) && (!selectedKinds.size || selectedKinds.has(e.kind)) && (!selectedCategories.size || [...selectedCategories].some(category => category === '__none__' ? !e.categories.length : e.categories.includes(category))) && (!selectedSources.size || e.entries.some(x => selectedSources.has(sourceValue(x)))) && (!contact || (contact === 'contact' ? p.emails?.length || p.phones?.length : contact === 'curated' ? e.profile : !e.profile));
  }
  function compareEntities(a, b) { return $('sort').value === 'activity' ? b.entries.length - a.entries.length || a.label.localeCompare(b.label) : $('sort').value === 'recent' ? (b.entries[0]?.date || '').localeCompare(a.entries[0]?.date || '') || a.label.localeCompare(b.label) : $('sort').value === 'name-desc' ? b.label.localeCompare(a.label) : a.label.localeCompare(b.label); }
  function render() {
    const filtered = items.filter(matchesFilters).sort(compareEntities);
    renderSuggestions();
    matchingItems = filtered;
    const selectedItems = items.filter(e => selectedEntities.has(e.id));
    const selectionKinds = new Set(selectedItems.map(e => e.kind));
    const selectionKind = selectionKinds.size === 1 ? selectedItems[0].kind : '';
    $('selection-count').textContent = `${selectedEntities.size} selected${selectionKind ? ' · ' + kinds[selectionKind] : selectionKinds.size > 1 ? ' · Mixed types' : ''}`;
    $('merge-selected').disabled = selectedEntities.size < 2 || selectionKinds.size !== 1 || selectedItems.length !== selectedEntities.size;
    $('change-type-selected').disabled = !selectedEntities.size || selectedItems.length !== selectedEntities.size;
    const pages = Math.max(1, Math.ceil(filtered.length / pageSize)); page = Math.max(0, Math.min(page, pages - 1));
    $('entity-status').textContent = `${filtered.length} matching entities · ${items.length} of ${total} loaded · ${pageSize} per page`;
    $('page-number').textContent = `Page ${page + 1} of ${pages}`; $('previous').disabled = page === 0; $('next').disabled = page + 1 >= pages;
    const previousCards = new Map([...$('entity-list').children].map(node => [node.dataset.entityId, node]));
    $('entity-list').replaceChildren();
    if (!filtered.length) $('entity-list').append(el('p', 'No entities match. Clear a filter or try another search.'));
    for (const e of filtered.slice(page * pageSize, (page + 1) * pageSize)) {
      const previous = previousCards.get(e.id), signature = JSON.stringify([e, kinds]);
      const dirty = previous && [...previous.querySelectorAll('input:not([type=checkbox]),textarea')].some(input => input.value !== input.defaultValue);
      if (previous && (previous.dataset.signature === signature || dirty)) {
        const checkbox = previous.querySelector('.entity-select'); checkbox.checked = selectedEntities.has(e.id);
        $('entity-list').append(previous); continue;
      }
      const card = el('details'); card.className = 'entity-card'; card.dataset.entityId = e.id; card.dataset.signature = signature;
      const summary = el('summary'), title = el('span'); title.className = 'entity-title-row';
      const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.className = 'entity-select';
      checkbox.checked = selectedEntities.has(e.id);
      checkbox.setAttribute('aria-label', 'Select ' + e.label);
      checkbox.addEventListener('click', event => event.stopPropagation());
      checkbox.onchange = () => { checkbox.checked ? selectedEntities.add(e.id) : selectedEntities.delete(e.id); render(); };
      const kindPill = pill((kinds[e.kind] || e.kind).toLowerCase());
      kindPill.classList.add('entity-kind'); kindPill.style.setProperty('--entity-color', kindColors[e.kind] || '#95a7c3');
      title.append(el('span', e.label));
      const meta = el('span'); meta.className = 'entity-detail-row';
      const count = el('span', `${e.entries.length} ${e.entries.length === 1 ? 'entry' : 'entries'}`); count.className = 'entity-count';
      meta.append(count, pill(e.resolution.replaceAll('-', ' ')));
      for (const status of e.identity_status || []) {
        const badge = pill(status.state.replaceAll('-', ' ')); badge.title = status.reason; meta.append(badge);
      }
      for (const category of e.categories.length ? e.categories : ['Uncategorized']) meta.append(pill(category));
      title.append(meta);
      summary.append(title, kindPill, checkbox); card.append(summary);
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
        const management = el('div'); management.className = 'entity-management-row'; management.append(mergeActions); card.append(management);
        const audit = el('details'); audit.className = 'entity-audit entity-section'; audit.append(el('summary', 'Entity audit history'));
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
        });
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
        const typeLabel = el('label', 'Entity type'), typeSelect = el('select'), typeSave = el('button', 'Change type'), typeFeedback = el('p');
        for (const [value, title] of Object.entries(kinds)) { const option = el('option', title); option.value = value; typeSelect.append(option); }
        typeSelect.value = e.kind; typeSave.type = 'button';
        typeSave.onclick = async () => { typeSave.disabled = true; try { await api('/type/' + encodeURIComponent(e.id), {kind:typeSelect.value}); await load(); await matchingStatus(); } catch (err) { typeFeedback.textContent = err.message; } finally { typeSave.disabled = false; } };
        const typeControls = el('div'); typeControls.className = 'entity-type-controls';
        typeLabel.append(typeSelect); typeControls.append(typeLabel, typeSave);
        management.prepend(typeControls);
        if (e.is_owner) {
          const owner = el('a', 'Corpus owner · Managed in /profile'); owner.href = '/profile'; owner.className = 'entity-owner-link'; management.prepend(owner);
          typeSelect.disabled = true; typeSave.disabled = true;
        } else if (e.owner_candidate) {
          const bind = el('button', 'This is my owner profile'); bind.type = 'button';
          bind.onclick = async () => { try { await api('/owner-binding', {identity:e.id}); await load(); } catch(error) { typeFeedback.textContent=error.message; } }; card.append(bind);
        }
        const soulActions=el('div');soulActions.className='entity-soul-actions';
        const updateSoul=el('button','Update soul');updateSoul.type='button';updateSoul.className='update-soul-button';
        updateSoul.onclick=()=>window.EntityConnections.open(e,async()=>{await load();});soulActions.append(updateSoul);
        const supporting = el('details'); supporting.className = 'entity-section'; supporting.append(el('summary', 'Supporting activity'));
        management.insertBefore(soulActions,mergeActions);
        card.append(typeFeedback,supporting,audit);
        if (!e.entries.length) supporting.append(el('p', 'No current supporting entries. Your saved profile remains available.'));
        for (const entry of e.entries) {
          const row = el('div'), link = el('a', entry.date.slice(0, 10) + ' · ' + entry.title); link.href = entry.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
          const meta = el('p', entry.source + ' · ' + entry.method); meta.className = 'entity-meta'; row.append(link, meta, el('blockquote', entry.evidence));
          for (const assignment of entry.assignments || []) {
            row.append(el('p', `Resolved from “${assignment.original_label}”: ${assignment.reason}`));
            const undo = el('button', 'Keep this mention separate'); undo.type = 'button';
            undo.onclick = async () => { undo.disabled = true; try { await api('/resolutions/' + encodeURIComponent(entry.id) + '/' + encodeURIComponent(assignment.mention_id) + '/undo', {}); await load(); } catch (error) { meta.textContent = error.message; undo.disabled = false; } }; row.append(undo);
          }
          supporting.append(row);
        }
      });
      $('entity-list').append(card);
      if (previous?.open) card.open = true;
    }
  }
  function setLoading(loading) {
    $('entity-loading').hidden = !loading;
    $('entity-results').hidden = loading || !hasLoaded;
    // Refresh remains available after an initial failure as well as later failures.
    $('result-actions').hidden = loading;
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
    const version = ++loadVersion;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      const context = window.activityModals?.context();
      if(context) params.set('context',context);
      if(!window.activityModals?.isAll()) {
        const graph = new URLSearchParams(new URLSearchParams(location.search).get('graph_filters') || '');
        for(const key of ['since','until','sources']) for(const value of graph.getAll(key)) if(value) params.append(key,value);
        if(graph.get('query')) params.set('graph_query',graph.get('query'));
      }
      const data = await api(params.size ? '?' + params : '');
      if(version !== loadVersion) return;
      if (data.types) { for (const key of Object.keys(kinds)) { delete kinds[key]; delete kindColors[key]; } for (const type of data.types) { kinds[type.id] = type.name; kindColors[type.id] = type.color; } }
      choices('create-entity-kind', Object.entries(kinds), 'Choose a type');
      items = data.entities; entityById = new Map(items.map(e => [e.id, e])); total = data.total ?? items.length;
      const available = new Set(items.map(e => e.id));
      for (const id of selectedEntities) if (!available.has(id)) selectedEntities.delete(id);
      facets(); render();
      hasLoaded = true;
      $('load-scope').textContent = 'Search and filters cover the current activity scope; results display 50 per page.';
    }
    finally { if(version === loadVersion) setLoading(false); }
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
    if (data.resolution) summary.append(el('p', `Mention resolution: ${data.resolution.pending} entries pending${data.resolution.enabled === false ? ' · automatic matching is disabled' : ''}.`));
    if (action === 'export') summary.append(el('p', 'Open technical details to review the export result.'));
  }
  async function status() {
    const data = await api('/status'); showJob(data);
  }
  let matchingTimer, matchingInFlight = null;
  function matchingStatus() {
    if (matchingInFlight) return matchingInFlight;
    matchingInFlight = refreshMatching().finally(() => { matchingInFlight = null; });
    return matchingInFlight;
  }
  async function refreshMatching() {
    clearTimeout(matchingTimer);
    try {
      const data = await api('/matching?all=true');
      suggestions = data.suggestions; suggestionEntities = data.entities || items; suggestionEntityById = new Map(suggestionEntities.map(e => [e.id, e]));
      const available = new Set(suggestions.map(s => s.id));
      for (const id of selectedSuggestions) if (!available.has(id)) selectedSuggestions.delete(id);
      const active = data.jobs.filter(job => ['pending','running'].includes(job.state)).length;
      const status = $('matching-status');
      let caption = status.querySelector(':scope > p'), history = status.querySelector('details');
      if (!caption || !history) { status.replaceChildren(); caption = el('p'); history = el('details'); history.append(el('summary'), el('div')); history.lastChild.className = 'matching-jobs'; status.append(caption, history); }
      caption.textContent = data.owner === 'hermes' ? `Daily Hermes consolidation · Run: ${data.consolidation_run || 'not started'} · Legacy suggestions: ${data.suggestions_total ?? suggestions.length}` : !data.enabled ? 'Automatic matching is disabled.' : `${active ? active + ' matching jobs active' : 'No matching jobs active'} · Awaiting review: ${data.suggestions_total ?? suggestions.length}`;
      history.firstChild.textContent = `Recent matching jobs (${data.jobs.length})`;
      const jobs = history.lastChild, scroll = jobs.scrollTop; jobs.replaceChildren();
      for (const job of data.jobs) {
        const counts = job.counts || {}, row = el('div'); row.className = 'matching-job';
        row.append(el('strong', `${job.mode === 'history' ? 'Existing entities' : 'New enrichment'} · ${job.state}`), el('p', `${counts.merged || 0} merged · ${counts.suggested || 0} for review · ${counts.pending || 0} candidate pairs pending`));
        if (job.error) row.append(el('p', job.error)); jobs.append(row);
      }
      jobs.scrollTop = scroll;
      facets(); renderSuggestions();
      if (active) matchingTimer = setTimeout(() => run(matchingStatus), 10000);
    } catch (err) { matchingTimer = setTimeout(() => run(matchingStatus), 10000); throw err; }
  }
  function suggestionMembers(suggestion) {
    return (suggestion.data.entity_ids || []).map(id => suggestionEntityById.get(id) || entityById.get(id)).filter(Boolean);
  }
  function renderSuggestions() {
    const filtersActive = $('entity-query').value.trim() || selectedKinds.size || selectedCategories.size || selectedSources.size || $('filter-contact').value;
    const filtered = suggestions.filter(s => suggestionMembers(s).some(matchesFilters) || (!filtersActive && !suggestionMembers(s).length));
    filtered.sort((a, b) => { const first = s => suggestionMembers(s).filter(matchesFilters).sort(compareEntities)[0] || {label:(s.data.names || []).join(' '), entries:[]}; return compareEntities(first(a), first(b)); });
    visibleSuggestions = filtered.slice(0, suggestionLimit);
    const visible = new Set(visibleSuggestions.map(s => s.id));
    const selectedHidden = [...selectedSuggestions].filter(id => !visible.has(id)).length;
    $('suggestions-selection').textContent = `${selectedSuggestions.size} selected${selectedHidden ? ` · ${selectedHidden} hidden by filters or pagination` : ''}`;
    $('suggestions-submit').disabled = !selectedSuggestions.size || batchBusy || dismissBusy;
    $('suggestions-dismiss').disabled = !selectedSuggestions.size || batchBusy || dismissBusy;
    $('suggestions-count').textContent = `Showing ${visibleSuggestions.length} of ${filtered.length} matching suggestions · ${suggestions.length} awaiting review overall`;
    $('suggestions-more').hidden = filtered.length <= suggestionLimit;
    const container = $('matching-suggestions');
    for (const suggestion of visibleSuggestions) {
      const members = suggestionMembers(suggestion), names = members.length === (suggestion.data.entity_ids || []).length ? members.map(e => e.label) : suggestion.data.names || [];
      const signature = JSON.stringify([suggestion.data, names, members.map(e => e.kind)]);
      let row = suggestionNodes.get(suggestion.id);
      if (!row || row.dataset.signature !== signature) {
        const wasOpen = row?.open;
        row = el('details'); row.className = 'matching-suggestion'; row.dataset.signature = signature;
        const summary = el('summary'), title = el('span', names.join(' ↔ ')); title.className = 'matching-title';
        summary.append(title);
        for (const kind of new Set(members.map(e => e.kind))) summary.append(typePill(kind));
        const check = el('input'); check.type = 'checkbox'; check.className = 'suggestion-select'; check.setAttribute('aria-label', 'Select merge ' + names.join(' and '));
        check.onclick = event => event.stopPropagation();
        check.onchange = () => { check.checked ? selectedSuggestions.add(suggestion.id) : selectedSuggestions.delete(suggestion.id); renderSuggestions(); };
        summary.append(check); row.append(summary);
        if (members.length !== (suggestion.data.entity_ids || []).length) row.append(el('p', 'Some entities are unavailable. You can keep this suggestion separate.'));
        row.append(el('p', suggestion.data.decision?.reason || suggestion.data.review_reason || 'Review supporting evidence before merging.'));
        for (const fact of suggestion.data.decision?.facts || []) {
          const evidence = el('div'); evidence.className = 'matching-evidence';
          if (typeof fact === 'string') evidence.append(el('p', fact));
          else if (fact && typeof fact === 'object') for (const [key, value] of Object.entries(fact)) evidence.append(el('strong', key === 'left_quote' ? names[0] || 'First entity' : key === 'right_quote' ? names[1] || 'Second entity' : key.replaceAll('_', ' ')), el(key.endsWith('quote') ? 'blockquote' : 'p', typeof value === 'string' ? value : JSON.stringify(value)));
          row.append(evidence);
        }
        const review = el('button', 'Review suggested merge'), dismiss = el('button', 'Keep separate'), feedback = el('p'); feedback.setAttribute('role', 'status');
        review.type = dismiss.type = 'button';
        review.onclick = async () => {
          review.disabled = true;
          try {
            await matchingStatus();
            const current = suggestions.find(s => s.id === suggestion.id);
            if (!current) throw Error('This suggestion has already been resolved.');
            const ids = current.data.entity_ids || [], currentMembers = suggestionMembers(current);
            if (currentMembers.length !== ids.length || new Set(currentMembers.map(e => e.kind)).size !== 1) throw Error('These entities are unavailable or have different types. Refresh or keep them separate.');
            selectedEntities.clear(); ids.forEach(id => selectedEntities.add(id)); render();
            // The suggestion can be outside the directory activity scope. Preview reads current IDs on the server.
            openMerge(null, currentMembers[0].label);
            $('merge-evidence').value = current.data.decision?.reason || '';
          } catch (err) { feedback.textContent = err.message; } finally { review.disabled = false; }
        };
        dismiss.onclick = async () => { dismiss.disabled = true; try { await api('/matching/suggestions/' + suggestion.id + '/dismiss', {}); selectedSuggestions.delete(suggestion.id); await matchingStatus(); } catch (err) { feedback.textContent = err.message; } finally { dismiss.disabled = false; } };
        const actions = el('div'); actions.className = 'matching-actions'; actions.append(review, dismiss); row.append(actions, feedback);
        row.open = Boolean(wasOpen); suggestionNodes.set(suggestion.id, row);
      }
      row.querySelector('.suggestion-select').checked = selectedSuggestions.has(suggestion.id);
    }
    // Leave unchanged nodes in place, preserving open details, focus and scroll positions.
    const desired = visibleSuggestions.map(s => suggestionNodes.get(s.id));
    for (const child of [...container.children]) if (!desired.includes(child)) child.remove();
    desired.forEach((node, index) => { if (container.children[index] !== node) container.insertBefore(node, container.children[index] || null); });
    if (!desired.length) container.append(el('p', suggestions.length ? 'No suggestions match the current filters.' : 'No uncertain matches awaiting review.'));
    const allIds = new Set(suggestions.map(s => s.id));
    for (const id of suggestionNodes.keys()) if (!allIds.has(id)) suggestionNodes.delete(id);
  }
  $('suggestions-select').onclick = () => { visibleSuggestions.forEach(s => selectedSuggestions.add(s.id)); renderSuggestions(); };
  $('suggestions-clear').onclick = () => { selectedSuggestions.clear(); renderSuggestions(); };
  function operationProgress(id, value, total, label) {
    const progress = $(id);
    progress.hidden = false; progress.max = Math.max(1, total);
    if (value === null) progress.removeAttribute('value');
    else progress.value = value;
    progress.setAttribute('aria-label', label);
  }
  $('suggestions-dismiss').onclick = async () => {
    if (dismissBusy || batchBusy || !selectedSuggestions.size) return;
    const chosen = [...selectedSuggestions], completed = new Set(), failures = [];
    const panel = $('matching-panel'), feedback = $('suggestions-feedback');
    dismissBusy = true; panel.inert = true; renderSuggestions();
    operationProgress('suggestions-progress', 0, chosen.length, `Keeping separate: 0 of ${chosen.length} processed`);
    try {
      if (matchingInFlight) await matchingInFlight;
      for (const [index, id] of chosen.entries()) {
        feedback.textContent = `Keeping separate ${index + 1} of ${chosen.length}…`;
        try {
          await api('/matching/suggestions/' + encodeURIComponent(id) + '/dismiss', {});
          completed.add(id); selectedSuggestions.delete(id);
        } catch (error) { failures.push(error.message); }
        operationProgress('suggestions-progress', index + 1, chosen.length, `Keeping separate: ${index + 1} of ${chosen.length} processed`);
      }
      suggestions = suggestions.filter(s => !completed.has(s.id));
      await matchingStatus();
      feedback.textContent = `${completed.size} suggestions kept separate.${failures.length ? ` ${failures.length} failed and remain selected for retry. ${failures[0]}` : ''}`;
    } catch (error) {
      feedback.textContent = `${completed.size} suggestions kept separate. Could not refresh matching suggestions: ${error.message}`;
    } finally {
      dismissBusy = false; panel.inert = false; $('suggestions-progress').hidden = true; renderSuggestions();
    }
  };
  $('suggestions-more').onclick = () => { suggestionLimit += 100; renderSuggestions(); };
  function batchWaiting(busy) {
    batchBusy = busy;
    $('batch-close').disabled = busy; $('batch-confirm').disabled = busy || !batchGroups.some(g => !g.complete);
    $('batch-groups').querySelectorAll('input,textarea').forEach(input => input.disabled = busy || Boolean(input.closest('.batch-group').dataset.submitted));
  }
  $('batch-close').onclick = () => { if (!batchBusy) $('batch-merge-dialog').close(); };
  $('batch-merge-dialog').addEventListener('cancel', event => { if (batchBusy) event.preventDefault(); });
  $('suggestions-submit').onclick = async () => {
    $('suggestions-feedback').textContent = ''; $('suggestions-submit').disabled = true;
    try {
      await matchingStatus();
      const chosen = suggestions.filter(s => selectedSuggestions.has(s.id));
      if (!chosen.length) throw Error('The selected suggestions have already been resolved.');
      const groups = [];
      for (const suggestion of chosen) {
        const ids = new Set(suggestion.data.entity_ids), matches = groups.filter(g => [...ids].some(id => g.ids.has(id)));
        const group = {ids, suggestions:[suggestion.id]};
        for (const match of matches) { match.ids.forEach(id => group.ids.add(id)); group.suggestions.push(...match.suggestions); groups.splice(groups.indexOf(match), 1); }
        groups.push(group);
      }
      if (groups.length > 100) throw Error('Review at most 100 independent merge groups per batch.');
      batchGroups = []; $('batch-groups').replaceChildren(); $('batch-feedback').textContent = 'Preparing current profiles…';
      $('batch-merge-dialog').showModal(); batchWaiting(true);
      operationProgress('batch-progress', 0, groups.length, 'Preparing merge previews');
      for (const group of groups) {
        const first = suggestionEntities.find(e => group.ids.has(e.id)) || items.find(e => group.ids.has(e.id));
        const node = el('section'); node.className = 'batch-group';
        const result = el('p'); result.setAttribute('role', 'status'); node.append(result); $('batch-groups').append(node);
        try {
          if (!first) throw Error('Selected entities are unavailable.');
          const evidence = [...new Set(chosen.filter(s => group.suggestions.includes(s.id)).map(s => s.data.decision?.reason || 'Reviewed matching suggestion'))].join('\n').slice(0,10000);
          const body = {entity_ids:[...group.ids], name:first.label, evidence};
          const preview = await api('/merge-preview', body);
          node.prepend(el('h3', `${kinds[preview.kind] || preview.kind} · ${preview.members.length} entities`), el('p', preview.members.map(m => m.label).join(' + ')));
          const fields = {}, profileDetails = el('details'), profileGrid = el('div');
          profileDetails.append(el('summary', 'Review combined profile')); profileGrid.className = 'profile-fields'; profileDetails.append(profileGrid);
          for (const key of ['name','categories','emails','phones','references','notes']) {
            const label = el('label', key === 'name' ? 'Resulting name' : key.charAt(0).toUpperCase() + key.slice(1));
            const input = el(key === 'name' ? 'input' : 'textarea'); input.value = Array.isArray(preview.profile[key]) ? preview.profile[key].join('\n') : preview.profile[key] || '';
            input.dataset.batchField = key;
            if (key === 'name') { input.required = true; input.maxLength = 120; } else input.rows = key === 'notes' ? 4 : 2;
            label.append(input); (key === 'name' ? node : profileGrid).append(label); if (key === 'notes') label.className = 'profile-wide'; fields[key] = input;
          }
          node.append(profileDetails);
          batchGroups.push({...group, body, preview, fields, node, result, requestId:crypto.randomUUID()});
        } catch (err) { result.textContent = err.message; }
        operationProgress('batch-progress', $('batch-groups').children.length, groups.length, `Preparing merge previews: ${$('batch-groups').children.length} of ${groups.length}`);
      }
      $('batch-feedback').textContent = `${batchGroups.length} groups ready. Any unavailable groups above remain selected for later review.`;
    } catch (err) { $('suggestions-feedback').textContent = err.message; }
    finally { $('batch-progress').hidden = true; batchWaiting(false); renderSuggestions(); }
  };
  $('batch-merge-form').onsubmit = async event => {
    event.preventDefault(); if (batchBusy) return;
    batchWaiting(true); $('batch-feedback').textContent = 'Merging reviewed groups…';
    const pending = batchGroups.filter(g => !g.complete);
    operationProgress('batch-progress', 0, pending.length, 'Checking reviewed groups');
    try {
      const ready = [];
      for (const [index, group] of pending.entries()) {
        try {
          if (!group.payload) {
            const body = {...group.body, name:group.fields.name.value.trim()};
            const fresh = await api('/merge-preview', body);
            if (fresh.selection_hash !== group.preview.selection_hash) throw Error('An entity changed since review. Close this dialog and review the selection again.');
            const profile = Object.fromEntries(Object.entries(group.fields).filter(([key]) => key !== 'name').map(([key, input]) => [key, key === 'notes' ? input.value : input.value.split('\n').map(v => v.trim()).filter(Boolean)]));
            group.payload = {...body, profile, preview_token:fresh.preview_token, request_id:group.requestId};
            group.node.dataset.submitted = 'true';
          }
          ready.push(group); group.result.textContent = 'Submitting…';
        } catch (err) { group.result.textContent = err.message; }
        operationProgress('batch-progress', index + 1, pending.length, `Checking reviewed groups: ${index + 1} of ${pending.length}`);
      }
      if (ready.length) {
        // The batch endpoint returns all outcomes together, so do not invent a percentage.
        operationProgress('batch-progress', null, ready.length, `Merging ${ready.length} reviewed groups`);
        const response = await api('/merges/batch', {groups:ready.map(g => g.payload)});
        for (const outcome of response.results) {
          const group = ready.find(g => g.requestId === outcome.request_id);
          if (outcome.error) group.result.textContent = outcome.error;
          else { group.complete = true; group.result.textContent = 'Merged successfully.'; group.suggestions.forEach(id => selectedSuggestions.delete(id)); }
        }
      }
      const completed = batchGroups.filter(g => g.complete).length;
      $('batch-feedback').textContent = `${completed} of ${batchGroups.length} groups merged. Failed groups remain selected; retry or close and review again.`;
      if (completed === batchGroups.length && completed) { $('batch-merge-dialog').close(); $('suggestions-feedback').textContent = `${completed} groups merged successfully.`; }
      await load(); await matchingStatus();
    } catch (err) { $('batch-feedback').textContent = err.message + ' Retry to recover the result safely.'; }
    finally { $('batch-progress').hidden = true; batchWaiting(false); renderSuggestions(); }
  };
  for (const [id, path] of [['entity-type-form','/types'], ['entity-create-form','/create']]) {
    $(id).onsubmit = async event => {
      event.preventDefault(); const button = $(id).querySelector('button[type=submit]'); button.disabled = true;
      $('type-feedback').textContent = 'Checking…';
      try {
        const payload = Object.fromEntries(new FormData($(id)));
        const result = await api(path, payload);
        if (result.state === 'possible-existing') {
          if (JSON.stringify(Object.fromEntries(new FormData($(id)))) !== JSON.stringify(payload)) {
            $('type-feedback').textContent = 'The form changed. Check for existing entities again.'; return;
          }
          $('type-feedback').textContent = '';
          const panel = $('create-entity-suggestions'); panel.replaceChildren(); panel.hidden = false;
          panel.append(el('p', 'Possible existing entities. Open one to reuse it, or confirm this is a different identity.'));
          for (const candidate of result.suggestions) {
            const reuse = el('button', `${candidate.name} · ${candidate.entries} entries${candidate.integrity_review ? ' · identity review required' : ''}`);
            reuse.type = 'button';
            reuse.onclick = () => {
              $('entity-query').value = candidate.name; selectedKinds.clear(); selectedCategories.clear(); selectedSources.clear();
              $('filter-contact').value = ''; page = 0; facets(); render();
              const card = [...$('entity-list').children].find(node => node.dataset.entityId === candidate.id);
              if (card) { card.open = true; card.scrollIntoView({block:'center'}); card.querySelector('summary')?.focus(); }
              $('type-feedback').textContent = 'Existing entity selected. No new entity created.';
            };
            panel.append(reuse);
          }
          const distinct = el('button', 'Create a distinct entity'); distinct.type = 'button';
          distinct.onclick = async () => {
            distinct.disabled = true;
            try {
              if (JSON.stringify(Object.fromEntries(new FormData($(id)))) !== JSON.stringify(payload)) {
                panel.hidden = true; $('type-feedback').textContent = 'The form changed. Check for existing entities again.'; return;
              }
              await api(path, {...payload, confirm_distinct:true}); panel.hidden = true; $(id).reset(); await load();
              $('type-feedback').textContent = 'Distinct entity created.';
            } catch (err) { $('type-feedback').textContent = err.message; } finally { distinct.disabled = false; }
          };
          panel.append(distinct); return;
        }
        $(id).reset(); if (id === 'entity-create-form') $('create-entity-suggestions').hidden = true;
        await load(); $('type-feedback').textContent = id === 'entity-type-form' ? 'Type added. Future enrichment will use it; historical backfill is optional.' : 'Entity added. Open its profile to add details.';
      }
      catch (err) { $('type-feedback').textContent = err.message; } finally { button.disabled = false; }
    };
  }
  $('types-backfill').onclick = async () => {
    $('types-backfill').disabled = true;
    try { const result = await api('/backfill?include_new_types=true', {}); showJob(result, 'backfill'); $('type-feedback').textContent = `Historical backfill ${result.state}. Check processing progress below.`; }
    catch (err) { $('type-feedback').textContent = err.message; } finally { $('types-backfill').disabled = false; }
  };
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
    rows.forEach(e => selectedEntities.add(e.id));
    $('selection-feedback').textContent = '';
    render();
  }
  $('select-page').onclick = () => selectMany(matchingItems.slice(page * pageSize, (page + 1) * pageSize));
  $('select-matching').onclick = () => selectMany(matchingItems);
  $('clear-selection').onclick = () => { selectedEntities.clear(); $('selection-feedback').textContent = ''; render(); };
  function typeWaiting(busy) {
    typeBusy = busy;
    for (const id of ['batch-type-close', 'batch-type-kind', 'batch-type-confirm']) $(id).disabled = busy;
    $('batch-type-form').setAttribute('aria-busy', String(busy));
  }
  $('change-type-selected').onclick = () => {
    typeSelection = items.filter(e => selectedEntities.has(e.id));
    if (!typeSelection.length) return;
    const typeSource = new Set(typeSelection.map(e => e.kind)).size === 1 ? typeSelection[0].kind : '';
    choices('batch-type-kind', Object.entries(kinds).filter(([kind]) => kind !== typeSource), 'Choose a type');
    $('batch-type-kind').value = '';
    $('batch-type-description').textContent = `Change ${typeSelection.length} ${typeSource ? kinds[typeSource] : 'mixed-type'} entities, including selections on other pages or hidden by filters. Profiles and connections are preserved. Entities already of the chosen type stay unchanged.`;
    $('batch-type-feedback').textContent = '';
    typeWaiting(false); $('entity-type-dialog').showModal();
  };
  $('batch-type-close').onclick = () => { if (!typeBusy) $('entity-type-dialog').close(); };
  $('entity-type-dialog').addEventListener('cancel', event => { if (typeBusy) event.preventDefault(); });
  $('batch-type-form').onsubmit = async event => {
    event.preventDefault();
    if (typeBusy || !$('batch-type-form').reportValidity()) return;
    const kind = $('batch-type-kind').value;
    typeWaiting(true); $('batch-type-feedback').textContent = 'Changing selected entity types…';
    try {
      const result = await api('/types/batch', {entity_ids:typeSelection.map(e => e.id), source_kinds:Object.fromEntries(typeSelection.map(e => [e.id, e.kind])), kind});
      typeSelection.forEach(e => selectedEntities.delete(e.id));
      $('entity-type-dialog').close();
      try { await load(); } catch (err) { $('entity-status').textContent = 'Types changed, but the directory could not refresh: ' + err.message; }
      $('selection-feedback').textContent = `${result.updated} entities changed to ${kinds[kind]}. Clear search or filters if they are not visible.`;
      run(matchingStatus);
    } catch (err) { $('batch-type-feedback').textContent = err.message; }
    finally { typeWaiting(false); }
  };
  function waiting(busy, message = '') {
    mergeBusy = busy; $('merge-wait').hidden = !busy; $('merge-wait-text').textContent = message;
    for (const id of ['merge-close','merge-review','merge-name','merge-evidence']) $(id).disabled = busy;
    $('merge-preview-content').querySelectorAll('[data-merge-field]').forEach(input => input.disabled = busy);
    $('merge-confirm').disabled = busy || (!mergeTarget && !mergePreview);
    $('entity-merge-form').setAttribute('aria-busy', String(busy));
  }
  function openMerge(target = null, suggestedName = '') {
    mergeTarget = target; mergePreview = null; submittedPayload = null; mergeRequest = crypto.randomUUID();
    $('merge-name').value = target?.label || suggestedName || items.find(e => selectedEntities.has(e.id))?.label || '';
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
  window.addEventListener('hfl:activity-scope',()=>run(load));
  run(async () => { await load(); await status(); await matchingStatus(); });
})();
