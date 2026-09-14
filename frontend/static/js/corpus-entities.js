(() => {
  const $ = id => document.getElementById(id);
  let items = [], page = 0, loadLimit = 100, total = 0;
  const pageSize = 25;
  const selectedKinds = new Set(), selectedCategories = new Set(), selectedSources = new Set();
  const kinds = {people: 'People', companies: 'Companies', tools: 'Tools', topics: 'Topics', objects: 'Referenced objects'};
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
    for (const id of ['alias', 'canonical']) choices(id, items.map(e => [e.id, e.label + ' · ' + e.kind + ' · ' + e.id.slice(-6)]), 'Choose an entity');
  }
  function editor(entity) {
    const details = el('details'); details.className = 'profile-editor'; details.append(el('summary', 'Edit profile'));
    const form = el('form'), grid = el('div'); grid.className = 'profile-fields';
    const fields = {}, profile = entity.profile || {};
    for (const [key, title, multiline, value] of [
      ['name', 'Display name', false, profile.name || entity.label],
      ['categories', 'Categories (one per line)', true, (profile.categories || []).join('\n')],
      ['emails', 'Email addresses (one per line)', true, (profile.emails || []).join('\n')],
      ['phones', 'Phone numbers (one per line)', true, (profile.phones || []).join('\n')],
      ['notes', 'Notes', true, profile.notes || '']
    ]) {
      const label = el('label', title), input = el(multiline ? 'textarea' : 'input');
      input.name = key; input.value = value; input.maxLength = key === 'notes' ? 10000 : key === 'name' ? 120 : 4000;
      if (key === 'name') input.required = true;
      if (key === 'notes') label.className = 'profile-wide';
      fields[key] = input; label.append(input); grid.append(label);
    }
    const button = el('button', 'Save profile'), feedback = el('span'); feedback.className = 'profile-feedback'; feedback.setAttribute('role', 'status');
    form.append(grid, button, feedback, el('p', 'Your edits survive enrichment. Contact details are not automatically merged or overwritten.'));
    form.onsubmit = async event => {
      event.preventDefault(); button.disabled = true; feedback.textContent = 'Saving…';
      try {
        const data = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, ['categories', 'emails', 'phones'].includes(key) ? input.value.split('\n').map(v => v.trim()).filter(Boolean) : input.value]));
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
      const p = e.profile || {}, searchable = [e.label, e.kind, ...e.categories, ...(p.emails || []), ...(p.phones || []), p.notes || ''].join(' ').toLowerCase();
      return q.split(/\s+/).every(word => searchable.includes(word)) && (!selectedKinds.size || selectedKinds.has(e.kind)) && (!selectedCategories.size || [...selectedCategories].some(category => category === '__none__' ? !e.categories.length : e.categories.includes(category))) && (!selectedSources.size || e.entries.some(x => selectedSources.has(x.source))) && (!contact || (contact === 'contact' ? p.emails?.length || p.phones?.length : contact === 'curated' ? e.profile : !e.profile));
    });
    filtered.sort((a, b) => $('sort').value === 'activity' ? b.entries.length - a.entries.length || a.label.localeCompare(b.label) : $('sort').value === 'recent' ? (b.entries[0]?.date || '').localeCompare(a.entries[0]?.date || '') || a.label.localeCompare(b.label) : a.label.localeCompare(b.label));
    const pages = Math.max(1, Math.ceil(filtered.length / pageSize)); page = Math.max(0, Math.min(page, pages - 1));
    $('entity-status').textContent = `${filtered.length} matching entities · ${items.length} of ${total} loaded · ${pageSize} per page`;
    $('page-number').textContent = `Page ${page + 1} of ${pages}`; $('previous').disabled = page === 0; $('next').disabled = page + 1 >= pages;
    $('entity-list').replaceChildren();
    if (!filtered.length) $('entity-list').append(el('p', 'No entities match. Clear a filter or try another search.'));
    for (const e of filtered.slice(page * pageSize, (page + 1) * pageSize)) {
      const card = el('details'); card.className = 'entity-card';
      const summary = el('summary'), title = el('span'); title.className = 'entity-title-row';
      title.append(el('span', e.label), pill(kinds[e.kind] || e.kind));
      const meta = el('span'); meta.className = 'entity-detail-row';
      const count = el('span', `${e.entries.length} ${e.entries.length === 1 ? 'entry' : 'entries'}`); count.className = 'entity-count';
      meta.append(count, pill(e.resolution.replaceAll('-', ' ')));
      for (const category of e.categories.length ? e.categories : ['Uncategorized']) meta.append(pill(category));
      summary.append(title, meta); card.append(summary);
      if (e.profile) { const contactLine = el('p', [...e.profile.emails, ...e.profile.phones, e.profile.notes].filter(Boolean).join('\n')); contactLine.className = 'contact-line'; card.append(contactLine); }
      card.append(editor(e), el('h2', 'Supporting activity'));
      if (!e.entries.length) card.append(el('p', 'No current supporting entries. Your saved profile remains available.'));
      for (const entry of e.entries) { const row = el('div'), link = el('a', entry.date.slice(0, 10) + ' · ' + entry.title); link.href = entry.href; const meta = el('p', entry.source + ' · ' + entry.method); meta.className = 'entity-meta'; row.append(link, meta, el('blockquote', entry.evidence)); card.append(row); }
      $('entity-list').append(card);
    }
  }
  function setLoading(loading) {
    $('entity-loading').hidden = !loading;
    $('entity-list').setAttribute('aria-busy', String(loading));
    $('entity-filters').disabled = loading;
    $('entity-filters').inert = loading;
    $('entity-filters').setAttribute('aria-busy', String(loading));
    $('clear-filters').disabled = loading;
    $('load-more').disabled = loading;
    if (loading) {
      $('category-menu').open = false;
      $('source-menu').open = false;
    }
  }
  async function load() {
    setLoading(true);
    try {
      const data = await api('?limit=' + loadLimit);
      items = data.entities; total = data.total ?? items.length;
      facets(); render();
      $('load-more').hidden = items.length >= total;
      $('load-scope').textContent = items.length < total ? 'Search and filters apply to loaded entities. Load more to include additional records.' : '';
    }
    finally { setLoading(false); }
  }
  async function status() {
    const data = await api('/status'); $('job').textContent = JSON.stringify({job: data.job, enrichment: data.enrichment}, null, 2); $('decisions').replaceChildren();
    data.decisions.forEach(d => { const row = el('p', d.reason + ' · ' + (d.active ? 'active' : 'undone')); if (d.active) { const button = el('button', 'Undo'); button.onclick = () => run(async () => { await api('/decisions/' + d.id + '/undo', {}); await load(); await status(); }); row.append(button); } $('decisions').append(row); });
  }
  async function run(fn) { try { await fn(); } catch (e) { $('entity-status').textContent = e.message; } }
  for (const id of ['entity-query', 'filter-contact', 'sort']) $(id).addEventListener(id === 'entity-query' ? 'input' : 'change', () => { page = 0; render(); });
  $('clear-filters').onclick = () => { $('entity-query').value = ''; $('filter-contact').value = ''; selectedKinds.clear(); selectedCategories.clear(); selectedSources.clear(); page = 0; facets(); render(); };
  document.addEventListener('click', event => { for (const id of ['category-menu', 'source-menu']) if (!$(id).contains(event.target)) $(id).open = false; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') for (const id of ['category-menu', 'source-menu']) $(id).open = false; });
  $('load-more').onclick = () => run(async () => { loadLimit += 100; await load(); });
  $('previous').onclick = () => { page--; render(); }; $('next').onclick = () => { page++; render(); };
  $('status-refresh').onclick = () => run(status);
  $('backfill').onclick = () => run(async () => { $('job').textContent = JSON.stringify(await api('/backfill', {}), null, 2); });
  $('export').onclick = () => run(async () => { $('job').textContent = JSON.stringify(await api('/export', {}), null, 2); });
  $('merge-form').onsubmit = e => { e.preventDefault(); run(async () => { await api('/merge', {alias: $('alias').value, canonical: $('canonical').value, reason: $('reason').value}); await load(); await status(); }); };
  run(async () => { await load(); await status(); });
})();
