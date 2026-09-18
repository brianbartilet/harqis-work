(() => {
  const form = document.getElementById('corpus-search-form');
  const menu = document.querySelector('[data-workspace-menu]');
  if (!form || !menu) return;
  const $ = selector => document.querySelector(selector);
  const select = $('[data-workspace-selection]');
  const status = $('[data-workspace-status]');
  const dialog = $('[data-workspace-dialog]');
  const nameForm = $('[data-workspace-name-form]');
  const csrf = JSON.parse($('[data-memory-csrf]').textContent);
  let views = JSON.parse($('[data-workspace-data]').textContent).views;
  let current = views.find(view => view.id === form.elements.workspace.value);
  let operation = '', busy = false;
  const sources = [...form.querySelectorAll('[data-source-option]')];
  function syncSources() {
    const values = sources.filter(input => input.checked).map(input => input.value);
    form.elements.source.value = values.join(',');
    $('[data-source-caption]').textContent = values.length ? `${values.length} selected` : 'All sources';
  }
  sources.forEach(input => input.addEventListener('change', syncSources));
  $('[data-sources-clear]').onclick = () => { sources.forEach(input => input.checked = false); syncSources(); };
  function dates() {
    const rolling = Number(form.elements.rolling.value);
    for (const key of ['date_from', 'date_to']) form.elements[key].disabled = !!rolling;
  }
  form.elements.rolling.addEventListener('change', dates);
  dates();
  function snapshot() {
    syncSources();
    const values = new FormData(form), state = {};
    for (const key of ['q','source','date_field','date_from','date_to','sort']) state[key] = String(values.get(key) || '');
    state.rolling = Number(values.get('rolling') || 0);
    state.page_size = Number(values.get('page_size') || 20);
    return state;
  }
  function options() {
    select.replaceChildren(new Option('Choose a workspace', ''));
    views.forEach(view => select.add(new Option(view.name, view.id)));
    select.value = current?.id || '';
    menu.querySelector('[data-workspace-action="edit"]').disabled = !current || busy;
    menu.querySelector('[data-workspace-action="remove"]').disabled = !current || busy;
  }
  function setBusy(value) {
    busy = value;
    menu.querySelectorAll('button,select').forEach(input => input.disabled = value);
    $('[data-workspace-confirm]').disabled = value;
    options();
  }
  async function request(path = '', method = 'GET', body) {
    const response = await fetch('/hfl-corpus/workspace-views' + path, {
      method, cache:'no-store', headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf},
      body:body ? JSON.stringify(body) : undefined,
    });
    const result = await response.json();
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Workspace could not be saved. Check the settings and retry.');
    return result;
  }
  function viewUrl(view) {
    return '/hfl-corpus?' + new URLSearchParams({...view.state, workspace:view.id});
  }
  select.onchange = async () => {
    const id = select.value;
    if (!id || busy) return;
    setBusy(true); status.textContent = 'Loading workspace…';
    try {
      const latest = await request();
      const view = latest.views.find(item => item.id === id);
      if (!view) throw Error('Workspace was removed. Reload the page.');
      await request('/' + id + '/select', 'POST');
      location.assign(viewUrl(view));
    } catch (error) { status.textContent = error.message; setBusy(false); }
  };
  function openDialog(action) {
    operation = action;
    $('[data-workspace-dialog-error]').textContent = '';
    document.getElementById('workspace-dialog-title').textContent = action === 'remove' ? 'Remove workspace?' : action === 'edit' ? 'Edit workspace name' : 'Save workspace';
    nameForm.elements.name.value = action === 'new' ? '' : current?.name || '';
    nameForm.elements.name.disabled = action === 'remove';
    $('[data-workspace-dialog-hint]').textContent = action === 'remove' ? 'This removes the saved profile. Your corpus entries are unchanged.' : action === 'edit' ? 'Rename this profile here. To update its filters, adjust them on the page and choose Save.' : 'Sources, tags, search text, dates and result settings will be saved.';
    $('[data-workspace-confirm]').textContent = action === 'remove' ? 'Remove' : 'Save';
    menu.open = false;
    dialog.showModal();
    if (action !== 'remove') nameForm.elements.name.focus();
  }
  async function persist(action, name) {
    setBusy(true); status.textContent = action === 'remove' ? 'Removing…' : 'Saving…';
    try {
      if (action === 'remove') {
        await request('/' + current.id + '?revision=' + current.revision, 'DELETE');
        location.assign('/hfl-corpus?reset=1'); return;
      }
      const existing = action === 'new' ? null : current;
      const view = await request(existing ? '/' + existing.id : '', existing ? 'PUT' : 'POST', {
        name, state:action === 'edit' ? current.state : snapshot(), revision:existing?.revision || 0,
      });
      views = views.filter(item => item.id !== view.id); views.push(view);
      views.sort((a,b) => a.name.localeCompare(b.name)); current = view;
      form.elements.workspace.value = view.id;
      const url = new URL(location.href); url.searchParams.set('workspace', view.id); history.replaceState(null, '', url);
      status.textContent = `Saved: ${view.name}`;
      dialog.close(); menu.open = true;
    } catch (error) {
      status.textContent = error.message;
      $('[data-workspace-dialog-error]').textContent = error.message;
    } finally { setBusy(false); }
  }
  menu.querySelectorAll('[data-workspace-action]').forEach(button => button.onclick = () => {
    if (busy) return;
    const action = button.dataset.workspaceAction;
    if (action === 'save' && current) persist(action, current.name);
    else openDialog(action);
  });
  nameForm.onsubmit = event => { event.preventDefault(); if (!busy) persist(operation, nameForm.elements.name.value.trim()); };
  $('[data-workspace-cancel]').onclick = () => dialog.close();
  document.addEventListener('click', event => { if (!menu.contains(event.target)) menu.open = false; });
  menu.addEventListener('keydown', event => { if (event.key === 'Escape') { menu.open = false; menu.querySelector('summary').focus(); } });
  // Tag clicks retain pending source/date selections as well as the existing
  // partial, case-insensitive tag matching rules.
  form.querySelectorAll('[data-workspace-tag]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    const tag = link.dataset.workspaceTag;
    const tokens = form.elements.q.value.split(/\s+/).filter(Boolean);
    const matching = tokens.filter(token => token.startsWith('#') && tag.toLowerCase().includes(token.slice(1).toLowerCase()));
    form.elements.q.value = (matching.length ? tokens.filter(token => !matching.includes(token)) : [...tokens, '#' + tag]).join(' ');
    form.requestSubmit();
  }));
  const search = $('[data-corpus-search]');
  form.addEventListener('submit', () => {
    syncSources(); search.disabled = true;
    search.setAttribute('aria-busy', 'true');
    search.querySelector('.workspace-spinner').hidden = false;
    $('[data-search-label]').textContent = 'Searching…';
  });
  window.addEventListener('pageshow', event => {
    search.disabled = false; search.removeAttribute('aria-busy');
    search.querySelector('.workspace-spinner').hidden = true;
    $('[data-search-label]').textContent = 'Search';
    if (event.persisted) location.replace(current ? viewUrl(current) : location.href);
  });
  options();
})();
