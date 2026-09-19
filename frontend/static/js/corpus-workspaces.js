(() => {
  const form = document.getElementById('corpus-search-form');
  const menu = document.querySelector('[data-workspace-menu]');
  if (!form || !menu) return;
  const $ = selector => document.querySelector(selector);
  $('[data-dismiss-corpus-error]')?.addEventListener('click', () => {
    $('[data-corpus-load-error]').hidden = true;
    menu.querySelector('summary').focus();
  });
  const select = $('[data-workspace-selection]');
  const status = $('[data-workspace-status]');
  const dialog = $('[data-workspace-dialog]');
  const help = document.getElementById('workspace-help');
  const helpOpen = $('[data-workspace-help-open]');
  helpOpen.onclick = () => {
    menu.open = false;
    help.showModal();
    document.getElementById('workspace-help-title').focus();
  };
  help.querySelectorAll('[data-workspace-help-close]').forEach(button => {
    button.onclick = () => help.close();
  });
  help.addEventListener('close', () => { menu.open = true; helpOpen.focus(); });
  help.addEventListener('click', event => {
    const box = help.getBoundingClientRect();
    if (event.target === help && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) help.close();
  });
  const nameForm = $('[data-workspace-name-form]');
  const csrf = JSON.parse($('[data-memory-csrf]').textContent);
  let viewData = JSON.parse($('[data-workspace-data]').textContent);
  let views = viewData.views;
  let preferences = viewData.preferences;
  const initialParams = new URLSearchParams(location.search);
  let activeIds = (initialParams.get('views') || form.elements.workspace.value || '').split(',').filter(Boolean);
  const aggregateScope = JSON.parse(form.elements.scope?.value || '{"any":[]}');
  let dynamicOn = initialParams.get('dynamic') === '1' && preferences.dynamic;
  let editTarget = null;

  let current = views.find(view => view.id === form.elements.workspace.value);
  let operation = '', busy = false, disposed = false;
  const sources = [...form.querySelectorAll('[data-source-option]')];
  const sourcesDropdown = $('[data-workspace-sources]');
  document.addEventListener('click', event => {
    if (!sourcesDropdown.contains(event.target)) sourcesDropdown.open = false;
  });
  sourcesDropdown.addEventListener('keydown', event => {
    if (event.key === 'Escape' && sourcesDropdown.open) {
      event.preventDefault();
      sourcesDropdown.open = false;
      sourcesDropdown.querySelector('summary').focus();
    }
  });
  function syncSources() {
    const values = sources.filter(input => input.checked).map(input => input.value);
    form.elements.source.value = values.join(',');
    $('[data-source-caption]').textContent = values.length ? `${values.length} selected` : 'All sources';
  }
  sources.forEach(input => input.addEventListener('change', syncSources));
  $('[data-sources-clear]').onclick = () => { sources.forEach(input => input.checked = false); syncSources(); updateViewContext(); };
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
  const initialFilterState = JSON.stringify(snapshot());
  function updateViewContext() {
    const name = $('[data-active-view-name]');
    if (!name) return;
    const applied = views.filter(view => activeIds.includes(view.id));
    name.textContent = applied.length > 1 ? `${applied[0].name} +${applied.length-1}` : applied[0]?.name || current?.name || 'All activity';
    $('[data-view-prefix]').textContent = applied.length > 1 ? 'Current Views:' : 'Current View:';
    const caption = $('[data-active-view-caption]');
    caption.dataset.expandable = String(applied.length > 1);
    caption.tabIndex = applied.length > 1 ? 0 : -1;
    caption.onclick = () => { if (applied.length > 1) { const summary = $('[data-scope-summary]'); summary.open = !summary.open; } };
    caption.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); caption.click(); } };
    $('[data-dynamic-badge]').textContent = dynamicOn ? 'Dynamic on' : 'Dynamic off';
    $('[data-dynamic-badge]').dataset.on = String(dynamicOn);
    $('[data-active-view-caption]').title = applied.map(view => view.name).join(' + ') || name.textContent;
    const normalized = state => JSON.stringify([
      (state.q || '').trim(), (state.source || '').split(',').filter(Boolean).sort(),
      state.date_field || 'created', Number(state.rolling || 0),
      state.rolling ? '' : state.date_from || '', state.rolling ? '' : state.date_to || '',
      state.sort || 'desc', Number(state.page_size || 20),
    ]);
    const badge = $('[data-active-view-modified]');
    const modified = normalized(snapshot()) !== normalized(aggregateScope.any.length ? {} : current?.state || {});
    badge.textContent = modified ? 'Modified' : current || applied.length ? 'Saved' : 'Default';
    badge.dataset.state = modified ? 'modified' : current || applied.length ? 'saved' : 'default';
  }
  form.addEventListener('input', updateViewContext);
  form.addEventListener('change', updateViewContext);
  function options() {
    updateViewContext();
    updateDynamicAvailability();
    select.replaceChildren(new Option('Choose a view', ''));
    views.forEach(view => select.add(new Option(view.name, view.id)));
    if (aggregateScope.any.length) {
      select.add(new Option(activeIds.length > 1 ? `${activeIds.length} views combined` : views.find(view => activeIds.includes(view.id))?.name || 'Applied view', '__combined'));
      select.value = '__combined';
    } else select.value = current?.id || '';
    menu.querySelector('[data-workspace-action="edit"]').disabled = (!current && !activeIds.length) || busy;
    menu.querySelector('[data-workspace-action="remove"]').disabled = (!current && !activeIds.length) || busy;
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
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : Array.isArray(result.detail) ? result.detail.map(item => item.msg).join(' ') : 'View could not be saved. Check the settings and retry.');
    return result;
  }
  function viewUrl(view) {
    return '/hfl-corpus?' + new URLSearchParams({...view.state, workspace:view.id});
  }
  const viewLoading = $('[data-view-loading]');
  let viewLoadingTimer;
  viewLoading.addEventListener('cancel', event => event.preventDefault());
  function endViewLoading() {
    clearTimeout(viewLoadingTimer);
    if (viewLoading.open) viewLoading.close();
    $('[data-corpus-results]')?.removeAttribute('aria-busy');
  }
  window.addEventListener('pageshow', endViewLoading);
  select.onchange = async () => {
    const id = select.value;
    if (!id || id === '__combined' || busy) return;
    const selectedName = select.selectedOptions[0]?.textContent || 'view';
    setBusy(true); status.textContent = `Loading ${selectedName}…`;
    $('#view-loading-title').textContent = `Loading ${selectedName}…`;
    $('#view-loading-detail').textContent = 'Preparing your filters…';
    $('[data-corpus-results]')?.setAttribute('aria-busy', 'true');
    viewLoading.showModal();
    $('#view-loading-title').focus();
    viewLoadingTimer = setTimeout(() => {
      $('#view-loading-detail').textContent = 'Still loading activity. Larger views can take a little longer.';
    }, 8000);
    try {
      const latest = await request();
      const view = latest.views.find(item => item.id === id);
      if (!view) throw Error('View was removed. Reload the page.');
      await request('/' + id + '/select', 'POST');
      if (preferences.revision || preferences.dynamic) await savePreferences({manual:[id], dynamic:false});
      $('#view-loading-detail').textContent = 'Searching documents with this view’s filters…';
      await loadCombined(latest, [id], false, false, viewUrl(view));
      if (!disposed) setBusy(false);
    } catch (error) { endViewLoading(); status.textContent = error.message; setBusy(false); menu.open = true; select.focus(); }
  };
  function openDialog(action) {
    operation = action;
    const editing = action === 'edit' || action === 'remove' || (['save','new'].includes(action) && aggregateScope.any.length);
    $('[data-view-edit-options]').hidden = !editing;
    $('[data-view-edit-options]').querySelectorAll('details').forEach(details => details.hidden = action === 'remove');
    editTarget = action === 'new' && editing ? {state:snapshot(), schedule:[]} : editing ? current || views.find(view => activeIds.includes(view.id)) : null;
    const target = $('[data-edit-target]');
    target.parentElement.hidden = !editing || action === 'new';
    $('[data-applied-filters]').open = false;
    $('[data-assigned-schedules]').open = true;
    target.replaceChildren(...views.map(view => new Option(view.name, view.id)));
    if (editTarget) { target.value = editTarget.id; fillViewEditor(editTarget); }
    target.onchange = () => { editTarget = views.find(view => view.id === target.value); fillViewEditor(editTarget); nameForm.elements.name.value = editTarget.name; };
    $('[data-workspace-dialog-error]').textContent = '';
    document.getElementById('workspace-dialog-title').textContent = action === 'remove' ? 'Remove view?' : action === 'edit' ? 'Edit view' : 'Save view';
    nameForm.elements.name.value = action === 'new' ? '' : (editTarget || current)?.name || '';
    nameForm.elements.name.disabled = action === 'remove';
    $('[data-workspace-dialog-hint]').textContent = action === 'remove' ? 'This removes the saved view. Your corpus entries are unchanged.' : action === 'edit' ? 'Edit this view’s name, filters, and recurring time blocks. Other selected views are unchanged.' : 'Sources, tags, search text, dates and result settings will be saved.';
    $('[data-workspace-confirm]').textContent = action === 'remove' ? 'Remove' : 'Save';
    if (action === 'new' && aggregateScope.any.length) {
      $('[data-workspace-dialog-hint]').textContent = 'Create a separate view using the additional filters. Combined views are not copied. Review Filters above before saving.';
    }
    menu.open = false;
    dialog.showModal();
    if (action !== 'remove') nameForm.elements.name.focus();
  }
  async function persist(action, name) {
    setBusy(true); status.textContent = action === 'remove' ? 'Removing…' : 'Saving…';
    try {
      if (action === 'remove') {
        const removed = (editTarget || current).id;
        await request('/' + removed + '?revision=' + (editTarget || current).revision, 'DELETE');
        if (aggregateScope.any.length) {
          dialog.close();
          const updated = await request();
          await loadCombined(updated, dynamicOn ? updated.active : activeIds.filter(id => id !== removed), dynamicOn);
        } else location.assign('/hfl-corpus?reset=1');
        return;
      }
      const existing = action === 'new' ? null : editTarget || current;
      const view = await request(existing ? '/' + existing.id : '', existing ? 'PUT' : 'POST', {
        name, state:editTarget ? readViewEditor() : snapshot(), schedule:editTarget ? readSchedule() : undefined, revision:existing?.revision || 0,
      });
      viewData = await request(); preferences = viewData.preferences;
      if (action === 'new') { dynamicOn = false; $('[data-dynamic-toggle]').checked = false; }
      views = views.filter(item => item.id !== view.id); views.push(view);
      views.sort((a,b) => a.name.localeCompare(b.name)); current = view;
      if (!aggregateScope.any.length) { activeIds = [view.id]; form.elements.workspace.value = view.id; }
      const url = new URL(location.href); url.searchParams.set('workspace', view.id); history.replaceState(null, '', url);
      status.textContent = `Saved: ${view.name}`;
      dialog.close(); menu.open = true;
      if (action === 'new' && aggregateScope.any.length) { await loadCombined(viewData, [view.id], false); }
      else if (editTarget && aggregateScope.any.length && activeIds.includes(view.id)) {
        const updated = await request();
        await loadCombined(updated, activeIds, dynamicOn, true);
      }
    } catch (error) {
      status.textContent = error.message;
      $('[data-workspace-dialog-error]').textContent = error.message;
    } finally { if (!disposed) setBusy(false); }
  }
  menu.querySelectorAll('[data-workspace-action]').forEach(button => button.onclick = () => {
    if (busy) return;
    const action = button.dataset.workspaceAction;
    if (action === 'save' && current && !aggregateScope.any.length) { editTarget = null; persist(action, current.name); }
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
    syncSources();
    if (form.elements.scope) { const scope = JSON.parse(form.elements.scope.value); scope.all = snapshot(); form.elements.scope.value = JSON.stringify(scope); }
    search.disabled = true;
    search.setAttribute('aria-busy', 'true');
    search.querySelector('.workspace-spinner').hidden = false;
    $('[data-search-label]').textContent = 'Searching…';
  });
  window.addEventListener('pageshow', event => {
    search.disabled = false; search.removeAttribute('aria-busy');
    search.querySelector('.workspace-spinner').hidden = true;
    $('[data-search-label]').textContent = 'Search';
    if (event.persisted) location.replace(aggregateScope.any.length ? location.href : current ? viewUrl(current) : location.href);
  });


  function fillViewEditor(view) {
    if (!view) return;
    $('[data-schedule-timezone]').textContent = `Times use ${preferences.timezone}. Change the timezone in Select multiple views.`;
    document.querySelectorAll('[data-edit-filter]').forEach(input => input.value = view.state[input.dataset.editFilter] ?? '');
    fillEditorSources(view.state.source || '');
    $('[data-schedule-blocks]').replaceChildren();
    (view.schedule || []).forEach(addBlock);
  }
  function fillEditorSources(value) {
    const selected = value.split(',').filter(Boolean);
    const names = [...new Set([...sources.map(input => input.value), ...selected])].sort((a,b) => a.localeCompare(b));
    const list = $('[data-edit-source-options]'); list.replaceChildren();
    names.forEach(name => {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.value = name; input.checked = selected.includes(name);
      input.onchange = syncEditorSources; label.append(input, name); list.append(label);
    });
    $('[data-edit-sources]').open = false;
    syncEditorSources();
  }
  function syncEditorSources() {
    const selected = [...$('[data-edit-source-options]').querySelectorAll('input:checked')].map(input => input.value);
    $('[data-edit-filter="source"]').value = selected.join(',');
    $('[data-edit-source-caption]').textContent = selected.length === 1 ? selected[0] : selected.length ? `${selected.length} selected` : 'All sources';
  }
  $('[data-edit-sources-clear]').onclick = () => {
    $('[data-edit-source-options]').querySelectorAll('input').forEach(input => input.checked = false);
    syncEditorSources();
  };
  dialog.addEventListener('click', event => { if (!$('[data-edit-sources]').contains(event.target)) $('[data-edit-sources]').open = false; });
  $('[data-edit-sources]').addEventListener('keydown', event => {
    if (event.key === 'Escape' && event.currentTarget.open) {
      event.preventDefault(); event.stopPropagation(); event.currentTarget.open = false; event.currentTarget.querySelector('summary').focus();
    }
  });
  function updateDynamicAvailability() {
    const hasSchedule = views.some(view => view.schedule?.length);
    $('[data-dynamic-hint]').hidden = hasSchedule;
    $('[data-dynamic-toggle]').disabled = busy || (!hasSchedule && !dynamicOn);
  }
  function addBlock(block = {days:[0,1,2,3,4],start:'09:00',end:'17:00'}) {
    const box = document.createElement('div'); box.className = 'workspace-time-block';
    const days = document.createElement('div'); days.className = 'workspace-day-options';
    ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].forEach((name, day) => {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.value = day; input.checked = block.days.includes(day);
      label.append(input, name); days.append(label);
    });
    const times = document.createElement('div'); times.className = 'workspace-block-times';
    ['start','end'].forEach(key => {
      const label = document.createElement('label'), input = document.createElement('input');
      label.textContent = key === 'start' ? 'From' : 'To'; input.type = 'time'; input.value = block[key]; input.dataset.blockTime = key;
      label.append(input); times.append(label);
    });
    const remove = document.createElement('button'); remove.type = 'button'; remove.dataset.removeBlock = ''; remove.textContent = 'Remove block'; remove.onclick = () => box.remove();
    box.append(days, times, remove); $('[data-schedule-blocks]').append(box);
  }
  $('[data-add-block]').onclick = () => addBlock();
  function readSchedule() {
    return [...document.querySelectorAll('.workspace-time-block')].map(box => ({
      days:[...box.querySelectorAll('input[type="checkbox"]:checked')].map(input => Number(input.value)),
      start:box.querySelector('[data-block-time="start"]').value, end:box.querySelector('[data-block-time="end"]').value,
    }));
  }
  function readViewEditor() {
    const state = {...editTarget.state};
    document.querySelectorAll('[data-edit-filter]').forEach(input => state[input.dataset.editFilter] = input.dataset.editFilter === 'rolling' ? Number(input.value) : input.value);
    return state;
  }
  async function savePreferences(changes) {
    const response = await fetch('/hfl-corpus/view-preferences', {
      method:'PUT', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
      body:JSON.stringify({...preferences, ...changes}),
    });
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the timezone and selected views.');
    preferences = data.preferences; viewData = data; return data;
  }
  function combinedUrl(data, ids, dynamic) {
    const localDate = new Intl.DateTimeFormat('en-CA', {timeZone:data.preferences.timezone, year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const parts = Object.fromEntries(localDate.map(part => [part.type, part.value]));
    const today = data.today || `${parts.year}-${parts.month}-${parts.day}`;
    const clauses = data.views.filter(view => ids.includes(view.id)).map(view => {
      const state = {...view.state};
      if (state.rolling) {
        const start = new Date(today+'T12:00:00Z'); start.setUTCDate(start.getUTCDate()-state.rolling+1);
        state.date_to = today; state.date_from = start.toISOString().slice(0,10); state.rolling = 0;
      }
      return state;
    });
    return '/hfl-corpus?' + new URLSearchParams({views:ids.join(','), dynamic:dynamic ? '1' : '0', scope:JSON.stringify({any:clauses})});
  }
  let transitioning = false;
  async function loadCombined(data, ids, dynamic, automatic = false, explicitUrl = null) {
    if (transitioning) return;
    transitioning = true;
    const name = data.views.filter(view => ids.includes(view.id)).map(view => view.name).join(' + ') || 'All activity';
    $('#view-loading-title').textContent = `Loading ${name}…`;
    $('#view-loading-detail').textContent = 'Searching documents with the selected views…';
    viewLoading.showModal();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 120000);
    const slow = setTimeout(() => { $('#view-loading-detail').textContent = 'Still searching. Larger views can take a little longer.'; }, 8000);
    try {
      const target = new URL(explicitUrl || combinedUrl(data, ids, dynamic), location.origin);
      if (automatic && new URL(location.href).searchParams.has('activity_year')) target.searchParams.set('activity_year', new URL(location.href).searchParams.get('activity_year'));
      const url = target.pathname + target.search;
      const response = await fetch(url, {signal:controller.signal, cache:'no-store'});
      if (!response.ok || response.redirected) throw Error('The views could not load. Please retry, or sign in again.');
      const html = await response.text();
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      if (!parsed.querySelector('#corpus-search-form') || parsed.querySelector('[data-corpus-load-error]')) throw Error('The corpus could not load. Your previous results are still shown.');
      const scroll = {window:window.scrollY, index:$('[data-corpus-index]')?.scrollTop || 0, results:$('[data-corpus-results-scroll]')?.scrollTop || 0};
      if (!automatic) form.dispatchEvent(new CustomEvent('corpus:view-search'));
      try { sessionStorage.setItem('corpus:view-transition', JSON.stringify({automatic, scroll})); } catch (_) {}
      clearInterval(dynamicTimer);
      disposed = true;
      history.pushState(null, '', url);
      document.open(); document.write(html); document.close();
    } catch (error) {
      endViewLoading();
      const feedback = $('[data-adaptive-status]');
      feedback.textContent = error.name === 'AbortError' ? 'Loading timed out. Previous results retained. ' : error.message+' ';
      const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Retry';
      retry.onclick = () => loadCombined(data, ids, dynamic, automatic, explicitUrl); feedback.append(retry);
      menu.open = true;
    } finally { clearTimeout(timeout); clearTimeout(slow); transitioning = false; }
  }
  const multiDialog = $('[data-multi-dialog]');
  $('[data-select-views]').onclick = async () => {
    try {
      viewData = await request(); views = viewData.views; preferences = viewData.preferences;
      const list = $('[data-multi-options]'); list.replaceChildren();
      views.forEach(view => {
        const label = document.createElement('label'), input = document.createElement('input');
        input.type = 'checkbox'; input.value = view.id; input.checked = activeIds.includes(view.id);
        label.append(input, view.name); list.append(label);
      });
      $('[data-multi-form]').elements.timezone.value = preferences.timezone;
      $('[data-multi-error]').textContent = ''; menu.open = false; multiDialog.showModal();
    } catch (error) { status.textContent = error.message; }
  };
  $('[data-multi-close]').onclick = () => multiDialog.close();
  multiDialog.addEventListener('close', () => { menu.open = true; $('[data-select-views]').focus(); });
  $('[data-multi-form]').onsubmit = async event => {
    event.preventDefault();
    const submit = event.currentTarget.querySelector('[type="submit"]'); submit.disabled = true;
    try {
      const manual = [...$('[data-multi-options]').querySelectorAll('input:checked')].map(input => input.value);
      const data = await savePreferences({manual, dynamic:false, timezone:event.currentTarget.elements.timezone.value.trim()});
      multiDialog.close(); await loadCombined(data, manual, false);
    } catch (error) { $('[data-multi-error]').textContent = error.message; }
    finally { submit.disabled = false; }
  };
  const dynamicToggle = $('[data-dynamic-toggle]'); dynamicToggle.checked = dynamicOn;
  dynamicToggle.onchange = async () => {
    dynamicToggle.disabled = true;
    try {
      const requested = dynamicToggle.checked;
      const latest = await request(); views = latest.views; preferences = latest.preferences;
      if (requested && !views.some(view => view.schedule?.length)) {
        dynamicToggle.checked = false; updateDynamicAvailability(); return;
      }
      const data = await savePreferences({dynamic:requested});
      await loadCombined(data, data.active, data.preferences.dynamic);
    } catch (error) { status.textContent = error.message; }
    finally { dynamicToggle.checked = dynamicOn; if (!disposed) updateDynamicAvailability(); }
  };
  if (aggregateScope.any.length) {
    $('[data-scope-summary]').hidden = false;
    const applied = views.filter(view => activeIds.includes(view.id));
    aggregateScope.any.forEach((state, index) => {
      const p = document.createElement('p');
      p.textContent = `${applied[index]?.name || 'View'}: ${state.source || 'All sources'} · ${state.q || 'All tags/text'} · ${state.date_field}: ${state.date_from || 'Any'}–${state.date_to || 'Any'}`;
      $('[data-scope-details]').append(p);
    });
  }
  $('[data-clear-narrowing]').onclick = () => loadCombined(viewData, activeIds, dynamicOn);
  let pollInFlight = false;
  async function checkDynamic() {
    if (!dynamicOn || transitioning || busy || pollInFlight || document.hidden || document.querySelector('dialog[open]') || menu.open) return;
    const modified = $('[data-active-view-modified]').dataset.state === 'modified' || JSON.stringify(snapshot()) !== initialFilterState;
    if (modified) { $('[data-adaptive-status]').textContent = 'Dynamic paused while filters are modified. Clear additional filters to resume.'; return; }
    pollInFlight = true;
    try {
      const data = await request();
      const wanted = data.preferences.dynamic ? data.active : data.preferences.manual;
      const url = new URL(combinedUrl(data, wanted, data.preferences.dynamic), location.origin);
      if (url.searchParams.get('scope') !== initialParams.get('scope') || [...wanted].sort().join(',') !== [...activeIds].sort().join(',') || !data.preferences.dynamic) {
        await loadCombined(data, wanted, data.preferences.dynamic, true);
      }
    } catch (error) { $('[data-adaptive-status]').textContent = 'Could not check the schedule. Will retry shortly.'; }
    finally { pollInFlight = false; }
  }
  const dynamicTimer = setInterval(checkDynamic, 15000);
  document.addEventListener('visibilitychange', checkDynamic);
  window.addEventListener('focus', checkDynamic);
  window.addEventListener('popstate', () => location.reload());
  function restoreTransition() {
    try {
      const transition = JSON.parse(sessionStorage.getItem('corpus:view-transition') || 'null');
      sessionStorage.removeItem('corpus:view-transition');
      if (transition) requestAnimationFrame(() => {
        $('[data-activity-body]')?.classList.add('workspace-arrive');
        if (transition.automatic) {
          window.scrollTo(0, transition.scroll.window);
          if ($('[data-corpus-index]')) $('[data-corpus-index]').scrollTop = transition.scroll.index;
          if ($('[data-corpus-results-scroll]')) $('[data-corpus-results-scroll]').scrollTop = transition.scroll.results;
        } else {
          ($('[data-corpus-result]') || $('[data-corpus-results]'))?.scrollIntoView({block:'center', behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
        }
      });
    } catch (_) {}
  }
  window.addEventListener('pageshow', restoreTransition);
  window.addEventListener('load', restoreTransition, {once:true});
  // Explicit links keep their scope; only dynamic-mode visits follow the schedule.
  if (dynamicOn) setTimeout(checkDynamic, 500);

  const shareDialog = $('[data-corpus-share-dialog]');
  const shareContent = $('[data-corpus-share-content]');
  const shareStatus = $('[data-corpus-share-status]');
  let previewKey = '', previewState = null, disabledReferences = [], shareController = null;
  let shareOpener = null;
  const contextKey = () => JSON.stringify(snapshot());
  function captureReferences() {
    if (shareContent.querySelector('[data-preview-ready]')) {
      disabledReferences = [...shareContent.querySelectorAll('[name="enabled_reference_ids"]')]
        .filter(input => !input.checked).map(input => input.value);
    }
  }
  function shareData() {
    const data = new FormData();
    data.set('csrf', csrf);
    data.set('state', JSON.stringify(previewState || snapshot()));
    data.set('workspace', form.elements.workspace.value);
    data.set('scope', JSON.stringify(aggregateScope));
    data.set('views', activeIds.join(','));
    disabledReferences.forEach(id => data.append('disabled_reference_ids', id));
    return data;
  }
  async function loadSharePreview() {
    shareController?.abort();
    const controller = new AbortController();
    shareController = controller;
    captureReferences();
    shareStatus.textContent = 'Loading preview…';
    shareContent.setAttribute('aria-busy', 'true');
    try {
      const data = shareData();
      const response = await fetch('/sharing/from-corpus?mode=preview', {
        method:'POST', body:data, signal:controller.signal,
      });
      if (response.redirected) throw Error('Sign in again to preview this recipe.');
      const html = await response.text();
      if (controller.signal.aborted) return;
      if (!response.ok && response.status !== 422) throw Error('The preview could not load. Please try again.');
      shareContent.innerHTML = html;
      shareStatus.textContent = '';
    } catch (error) {
      if (error.name !== 'AbortError') shareStatus.textContent = error.message;
    } finally {
      if (shareController === controller) shareContent.removeAttribute('aria-busy');
    }
  }
  $('[data-corpus-share-preview]').onclick = event => {
    shareOpener = event.currentTarget;
    const key = contextKey();
    if (key !== previewKey) {
      previewKey = key; previewState = snapshot(); disabledReferences = [];
      // Resolve rolling ranges once for this preview and its subsequent handoff.
      if (previewState.rolling) {
        const end = new Date(), start = new Date(end);
        start.setDate(start.getDate() - previewState.rolling + 1);
        const iso = value => [value.getFullYear(), String(value.getMonth()+1).padStart(2,'0'), String(value.getDate()).padStart(2,'0')].join('-');
        previewState.date_from = iso(start); previewState.date_to = iso(end); previewState.rolling = 0;
      }
      shareContent.replaceChildren();
    }
    menu.open = false;
    shareDialog.showModal();
    document.getElementById('corpus-share-title').focus();
    loadSharePreview();
  };
  $('[data-corpus-share-close]').onclick = () => shareDialog.close();
  shareDialog.addEventListener('close', () => {
    shareController?.abort(); menu.open = true; shareOpener?.focus();
  });
  shareDialog.addEventListener('click', event => {
    const box = shareDialog.getBoundingClientRect();
    if (event.target === shareDialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) shareDialog.close();
  });
  $('[data-corpus-share-form]').onsubmit = event => event.preventDefault();
  shareContent.addEventListener('change', event => {
    if (event.target.matches('[data-toggle-all-references]')) {
      shareContent.querySelectorAll('[name="enabled_reference_ids"]').forEach(input => { input.checked = event.target.checked; });
    }
    const refs = [...shareContent.querySelectorAll('[name="enabled_reference_ids"]')];
    const toggle = shareContent.querySelector('[data-toggle-all-references]');
    if (toggle) { toggle.checked = refs.every(input => input.checked); toggle.indeterminate = refs.some(input => input.checked) && !toggle.checked; }
    captureReferences();
  });
  document.querySelectorAll('[data-corpus-share-generate]').forEach(button => button.onclick = () => {
    if (contextKey() !== previewKey) { previewState = null; disabledReferences = []; }
    else captureReferences();
    const transfer = document.createElement('form');
    transfer.method = 'POST'; transfer.action = '/sharing/from-corpus'; transfer.hidden = true;
    for (const [name, value] of shareData()) {
      const input = document.createElement('input'); input.type = 'hidden'; input.name = name; input.value = value; transfer.append(input);
    }
    document.body.append(transfer); transfer.submit();
  });
  options();
})();
