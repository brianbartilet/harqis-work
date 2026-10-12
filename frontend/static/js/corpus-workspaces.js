(() => {
  const form = document.getElementById('corpus-search-form');
  const menu = document.querySelector('[data-workspace-menu]');
  if (!form || !menu) return;
  const $ = selector => document.querySelector(selector);
  const kanban=!!document.querySelector('[data-actions-page]');
  const graph=!!document.querySelector('.kg-shell');
  const workspacePath=graph?'/hfl-corpus/graph':kanban?'/hfl-corpus/actions':'/hfl-corpus';
  const createMenu = document.querySelector('.corpus-create-menu');
  if (createMenu) {
    const headerMenus = [...document.querySelectorAll('.corpus-create-menu, .corpus-workspace-controls > [data-workspace-menu]')];
    headerMenus.forEach(dropdown => dropdown.addEventListener('toggle', () => {
      if (dropdown.open) headerMenus.forEach(other => { if (other !== dropdown) other.open = false; });
    }));
    createMenu.addEventListener('click', event => {
      if (event.target.closest('[data-create-entry-open], [data-create-action-open]')) createMenu.open = false;
    });
    document.addEventListener('click', event => { if (!createMenu.contains(event.target)) createMenu.open = false; });
    createMenu.addEventListener('keydown', event => { if (event.key === 'Escape') { createMenu.open = false; createMenu.querySelector('summary').focus(); } });
  }

  $('[data-dismiss-corpus-error]')?.addEventListener('click', () => {
    $('[data-corpus-load-error]').hidden = true;
    menu.querySelector('summary').focus();
  });
  const picker = $('[data-view-picker]');
  let pendingIds = [], pickerChanged = false;
  const status = $('[data-workspace-status]');
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
  const csrf = JSON.parse($('[data-memory-csrf]').textContent);
  let viewData = JSON.parse($('[data-workspace-data]').textContent);
  let views = viewData.views;
  let preferences = viewData.preferences;
  const initialParams = new URLSearchParams(location.search);
  let activeIds = (initialParams.get('views') || initialParams.get('workspace_ids') || form.elements.workspace.value || '').split(',').filter(Boolean);
  const aggregateScope = JSON.parse(form.elements.scope?.value || '{"any":[]}');
  const sharedFingerprint = data => JSON.stringify([data.preferences, data.views, data.active, data.today],
    (key, value) => value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) : value);
  let observedShared = sharedFingerprint(viewData);
  let dynamicOn = initialParams.get('dynamic') === '1' && preferences.dynamic;

  let current = views.find(view => view.id === form.elements.workspace.value);
  let busy = false, disposed = false, arrivalMessage = '';
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
  const inheritedFilters = new Map();
  const editedFilters = new Set();
  form.addEventListener('formdata', event => {
    inheritedFilters.forEach((entry, key) => {
      if (key === 'date_field' && ['date_from','date_to','rolling'].some(field => editedFilters.has(field))) return;
      if (!editedFilters.has(key) && String(form.elements[key].value) === entry.display) event.formData.set(key, entry.original);
    });
  });
  form.addEventListener('input', event => {
    const key = event.target.matches('[data-source-option]') ? 'source' : event.target.name;
    if (key) editedFilters.add(key);
  }, true);
  function inheritViewFilters() {
    if (!aggregateScope.any.length) return;
    const selectedViews = views.filter(view => activeIds.includes(view.id));
    const states = aggregateScope.any.map((state, index) => ({...state,
      rolling:selectedViews.length === aggregateScope.any.length ? selectedViews[index].state.rolling || 0 : state.rolling || 0,
    }));
    const defaults = {q:'', source:'', date_field:'created', rolling:'0', date_from:'', date_to:''};
    const extraDates = form.elements.date_from.value || form.elements.date_to.value || Number(form.elements.rolling.value);
    for (const [key, fallback] of Object.entries(defaults)) {
      const control = form.elements[key], original = control.value;
      if (original !== fallback || (extraDates && ['date_field','rolling','date_from','date_to'].includes(key))) continue;
      const values = [...new Set(states.map(state => String(state[key] ?? fallback)))];
      let display = values.length === 1 ? values[0] : fallback;
      if (key === 'source') {
        display = values.some(value => !value) ? '' : [...new Set(values.flatMap(value => value.split(',').filter(Boolean)))].sort().join(',');
        display.split(',').filter(Boolean).forEach(value => {
          if (sources.some(input => input.value === value)) return;
          const label = document.createElement('label'), input = document.createElement('input');
          input.type = 'checkbox'; input.dataset.sourceOption = ''; input.value = value;
          input.addEventListener('change', syncSources); sources.push(input);
          label.append(input, document.createTextNode(value)); sourcesDropdown.querySelector('.workspace-source-options').append(label);
        });
        sources.forEach(input => input.checked = display.split(',').includes(input.value));
        $('[data-sources-clear]').textContent = 'Use view sources';
      } else if (values.length > 1 && control.tagName === 'SELECT') {
        const option = new Option('Varies by view', fallback); option.dataset.inheritedOption = '';
        control.prepend(option);
      } else if (values.length > 1 && key === 'q') {
        control.placeholder = 'Search within selected views';
        const hint = document.createElement('span'); hint.className = 'workspace-inherited-hint';
        hint.textContent = 'Search and tags vary by view';
        hint.title = values.map(value => value || 'Any').join(' / ');
        control.parentElement.insertAdjacentElement('afterend', hint);
        control.addEventListener('input', () => { hint.hidden = true; });
      }
      control.value = display;
      inheritedFilters.set(key, {original, display});
    }
    dates(); syncSources();
    if (inheritedFilters.has('source')) inheritedFilters.get('source').display = form.elements.source.value;
  }
  function syncSources() {
    const values = sources.filter(input => input.checked).map(input => input.value);
    form.elements.source.value = values.join(',');
    $('[data-source-caption]').textContent = values.length ? `${values.length} selected${inheritedFilters.has('source') && !editedFilters.has('source') ? ' from views' : ''}` : 'All sources';
  }
  sources.forEach(input => input.addEventListener('change', syncSources));
  $('[data-sources-clear]').onclick = () => { const values = inheritedFilters.get('source')?.display.split(',') || []; sources.forEach(input => input.checked = values.includes(input.value)); editedFilters.delete('source'); syncSources(); updateViewContext(); };
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
    name.style.borderLeft = applied.length === 1 ? `3px solid ${applied[0].color}` : '';
    name.style.paddingLeft = applied.length === 1 ? '.35rem' : '';
    name.textContent = applied.length > 1 ? applied.map(view => view.name).join(' + ') : applied[0]?.name || current?.name || 'All activity';
    const caption = $('[data-active-view-caption]');
    caption.dataset.expandable = 'false';
    caption.tabIndex = -1;
    $('[data-dynamic-badge]').textContent = dynamicOn ? 'Dynamic ON' : 'Dynamic OFF';
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
    if(kanban)window.dispatchEvent(new CustomEvent('hfl:workspace-context',{detail:{names:activeIds.map(id=>views.find(view=>view.id===id)?.name||'Unavailable Space')}}));
  }
  form.addEventListener('input', updateViewContext);
  form.addEventListener('change', updateViewContext);
  function options() {
    const selected = views.find(view => view.id === activeIds[0]);
    const resetUrl = dynamicOn || activeIds.length > 1
      ? combinedUrl(viewData, activeIds, dynamicOn)
      : selected ? viewUrl(selected) : workspacePath+'?reset=1';
    document.querySelectorAll('[data-workspace-reset]').forEach(link => { link.href = resetUrl; });
    updateViewContext();
    updateDynamicAvailability();
    pendingIds = [...activeIds]; pickerChanged = false;
    const choices = $('[data-view-choices]'); choices.replaceChildren();
    views.forEach(view => {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.value = view.id; input.checked = pendingIds.includes(view.id); input.disabled = busy;
      const dot = document.createElement('span'); dot.className = 'view-color-dot'; dot.style.backgroundColor = view.color;
      label.append(input, dot, document.createTextNode(view.name)); choices.append(label);
      input.onchange = () => {
        pendingIds = [...choices.querySelectorAll('input:checked')].map(el => el.value);
        pickerChanged = pendingIds.slice().sort().join(',') !== activeIds.slice().sort().join(',');
        pickerCaption();
      };
    });
    pickerCaption();
  }
  function setBusy(value) {
    busy = value;
    menu.querySelectorAll('button,select').forEach(input => input.disabled = value);
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
    return workspacePath+'?' + new URLSearchParams({...view.state, workspace:view.id, workspace_revision:preferences.revision});
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
  $('[data-manage-spaces]').addEventListener('click', event => {
    event.preventDefault();
    try {
      // Session-only handoff: filter text never goes in a URL or shared storage.
      const state = snapshot();
      const base = activeIds.length === 1 ? views.find(view => view.id === activeIds[0])?.state : null;
      if (base && aggregateScope.any.length) inheritedFilters.forEach((entry, key) => {
        if (!editedFilters.has(key) && String(form.elements[key].value) === entry.display) state[key] = base[key];
      });
      sessionStorage.setItem('harqis:space-draft', JSON.stringify({state, ids:activeIds, combined:activeIds.length > 1, sources:sources.map(input => input.value), at:Date.now()}));
      location.assign('/spaces?draft=1');
    } catch (error) { status.textContent = 'Could not carry filters to Spaces. Allow session storage and try again.'; }
  });
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
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || transitioning) return;
    syncSources();
    if (form.elements.scope) { const scope = JSON.parse(form.elements.scope.value); scope.all = snapshot(); form.elements.scope.value = JSON.stringify(scope); }
    search.disabled = true;
    search.setAttribute('aria-busy', 'true');
    search.querySelector('.workspace-spinner').hidden = false;
    $('[data-search-label]').textContent = 'Searching…';
    busy = true;
    try {
      const data = await savePreferences({manual:activeIds, dynamic:dynamicOn, applied:snapshot()});
      await loadCombined(data, data.active, data.preferences.dynamic);
    } catch (error) {
      status.textContent = error.message; menu.open = true;
    } finally {
      busy = false; search.disabled = false; search.removeAttribute('aria-busy');
      search.querySelector('.workspace-spinner').hidden = true;
      $('[data-search-label]').textContent = 'Search';
    }
  });
  window.addEventListener('pageshow', event => {
    search.disabled = false; search.removeAttribute('aria-busy');
    search.querySelector('.workspace-spinner').hidden = true;
    $('[data-search-label]').textContent = 'Search';
    if (event.persisted) checkDynamic(true);
  });


  function updateDynamicAvailability() {
    const hasSchedule = views.some(view => view.schedule?.length);
    $('[data-dynamic-hint]').hidden = hasSchedule;
    $('[data-dynamic-toggle]').disabled = busy || (!hasSchedule && !dynamicOn);
  }
  async function savePreferences(changes) {
    const response = await fetch('/hfl-corpus/view-preferences', {
      method:'PUT', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
      body:JSON.stringify({...preferences, ...changes}),
    });
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the timezone and selected views.');
    preferences = data.preferences; viewData = data;
    try { localStorage.setItem('corpus:workspace-change', String(Date.now())); } catch (_) {}
    return data;
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
    const applied = data.preferences.applied || {};
    const defaults = {q:'',source:'',date_field:'created',date_from:'',date_to:'',rolling:0,sort:'desc',page_size:20};
    if (!dynamic && ids.length === 1 && Object.entries(applied).every(([key,value]) => value === defaults[key])) {
      const view = data.views.find(view => view.id === ids[0]);
      if (view) return viewUrl(view);
    }
    return workspacePath+'?' + new URLSearchParams({...applied, workspace_revision:data.preferences.revision, views:ids.join(','), dynamic:dynamic ? '1' : '0', scope:JSON.stringify({any:clauses, all:applied})});
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
      if(kanban||graph)target.pathname=workspacePath;
      if(graph){
        await window.HflIdeas?.maps.flush();
        const board=window.HflIdeas?.maps.current;
        if(board&&(!ids.length||(board.workspace_ids||[]).some(id=>ids.includes(id))))target.searchParams.set('board',board.id);
      }
      if (automatic && new URL(location.href).searchParams.has('activity_year')) target.searchParams.set('activity_year', new URL(location.href).searchParams.get('activity_year'));
      const url = target.pathname + target.search;
      if(graph){
        // Validate the data transition while the previous canvas is still intact.
        // A failed read must not strand the user on an empty replacement page.
        const path=target.searchParams.has('board')
          ? '/hfl-corpus/timeline/ideas/maps/'+encodeURIComponent(target.searchParams.get('board'))+'/graph'
          : '/api/hfl/entities/graph';
        const probe=await fetch(path+'?'+new URLSearchParams({limit:'0',context:target.searchParams.toString()}),{signal:controller.signal,cache:'no-store'});
        if(!probe.ok)throw Error('The graph could not load. Your previous view and edits are retained.');
      }
      const response = await fetch(url, {signal:controller.signal, cache:'no-store'});
      if (!response.ok || response.redirected) throw Error('The views could not load. Please retry, or sign in again.');
      const html = await response.text();
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      if (!parsed.querySelector('#corpus-search-form') || parsed.querySelector('[data-corpus-load-error]')) throw Error('The corpus could not load. Your previous results are still shown.');
      const scroll = {window:window.scrollY, index:$('[data-corpus-index]')?.scrollTop || 0, results:$('[data-corpus-results-scroll]')?.scrollTop || 0};
      if (!automatic) form.dispatchEvent(new CustomEvent('corpus:view-search'));
      try { sessionStorage.setItem('corpus:view-transition', JSON.stringify({automatic, scroll, message:arrivalMessage || status.textContent, menuOpen:!!arrivalMessage && menu.open})); } catch (_) {}
      clearInterval(dynamicTimer);
      window.dispatchEvent(new Event('hfl:view-replacing'));
      disposed = true;
      if(graph){location[automatic?'replace':'assign'](url);return;}
      history[automatic ? 'replaceState' : 'pushState'](null, '', url);
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
  document.addEventListener('corpus:edit-scheduled-view', event => {
    location.assign('/spaces?edit=' + encodeURIComponent(event.detail));
  });
  function pickerCaption() {
    const names = views.filter(view => pendingIds.includes(view.id)).map(view => view.name);
    $('[data-view-picker-caption]').textContent = names.join(' + ') || 'All activity';
    $('[data-view-all]').setAttribute('aria-pressed', String(!pendingIds.length));
  }
  async function applyPicker() {
    if (!pickerChanged || busy || transitioning) return;
    const ids = [...pendingIds]; pickerChanged = false; busy = true;
    $('#view-loading-title').textContent = `Loading ${views.filter(view => ids.includes(view.id)).map(view => view.name).join(' + ') || 'All activity'}…`;
    $('#view-loading-detail').textContent = 'Applying selected views…'; viewLoading.showModal();
    try {
      const latest = await request(); preferences = latest.preferences;
      if (ids.some(id => !latest.views.some(view => view.id === id))) throw Error('A selected view was removed. Reopen Spaces and try again.');
      const data = await savePreferences({manual:ids, dynamic:false, applied:{}});
      await loadCombined(data, ids, false);
    } catch (error) { endViewLoading(); status.textContent = error.message; menu.open = true; }
    finally { if (!disposed) { busy = false; options(); } }
  }
  picker.addEventListener('toggle', () => { if (!picker.open) applyPicker(); });
  window.HflSelectSpace = number => {
    if (disposed || busy || transitioning || (number && !views[number-1])) return;
    pendingIds = number ? [views[number-1].id] : [];
    pickerChanged = true;
    pickerCaption();
    picker.open = false;
    void applyPicker();
  };
  menu.addEventListener('toggle', () => { if (!menu.open) picker.open = false; });
  $('[data-view-all]').onclick = () => {
    if (busy) return;
    pendingIds = []; pickerChanged = activeIds.length > 0 || dynamicOn || JSON.stringify(snapshot()) !== JSON.stringify({q:'',source:'',date_field:'created',date_from:'',date_to:'',sort:'desc',rolling:0,page_size:20});
    $('[data-view-choices]').querySelectorAll('input').forEach(input => input.checked = false);
    pickerCaption(); picker.open = false;
  };
  document.addEventListener('click', event => {
    if (!picker.open || picker.contains(event.target)) return;
    if (pickerChanged) { event.preventDefault(); event.stopImmediatePropagation(); }
    picker.open = false;
  }, true);
  picker.addEventListener('keydown', event => {
    if (event.key === 'Escape' && picker.open) { event.preventDefault(); event.stopPropagation(); picker.open = false; picker.querySelector('summary').focus(); }
  });
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
  let pollInFlight = false;
  async function checkDynamic(force = false) {
    if (transitioning || busy || pollInFlight || disposed || document.hidden || document.querySelector('#followups-board[data-busy=true]') || document.querySelector('dialog[open]:not(#followups-board)') || (menu.open && !(graph && dynamicOn && !picker.open && !pickerChanged))) return;
    // Applied filters are shared; unfinished typing stays local until submitted.
    if (JSON.stringify(snapshot()) !== initialFilterState) {
      $('[data-adaptive-status]').textContent = 'Space sync paused while filters are being edited. Apply your filters to sync.';
      return;
    }
    pollInFlight = true;
    try {
      const data = await request();
      // A bookmarked Dynamic URL may already lag the server's current block.
      const scheduleChanged = dynamicOn && data.preferences.dynamic && [...data.active].sort().join(',') !== [...activeIds].sort().join(',');
      if (force === true || scheduleChanged || sharedFingerprint(data) !== observedShared) {
        await loadCombined(data, data.active, data.preferences.dynamic, true);
      }
    } catch (error) {
      const notice = $('[data-adaptive-status]');
      notice.textContent = 'Could not sync Spaces. Will retry shortly. ';
      const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Retry';
      retry.onclick = () => checkDynamic(true); notice.append(retry);
    } finally { pollInFlight = false; }
  }
  document.addEventListener('click', async event => {
    const reset = event.target.closest('[data-workspace-reset]');
    if (disposed || busy || transitioning || !reset || event.ctrlKey || event.metaKey || event.shiftKey || event.button) return;
    event.preventDefault();
    try {
      const data = await savePreferences({applied:{}});
      await loadCombined(data, data.active, data.preferences.dynamic);
    } catch (error) { status.textContent = error.message; menu.open = true; }
  });
  const dynamicTimer = setInterval(checkDynamic, 15000);
  document.addEventListener('visibilitychange', checkDynamic);
  window.addEventListener('focus', checkDynamic);
  window.addEventListener('storage', event => { if (event.key === 'corpus:workspace-change') checkDynamic(); });
  window.addEventListener('popstate', () => checkDynamic(true));
  function restoreTransition() {
    try {
      const transition = JSON.parse(sessionStorage.getItem('corpus:view-transition') || 'null');
      sessionStorage.removeItem('corpus:view-transition');
      if (transition) requestAnimationFrame(() => {
        $('[data-workspace-status]').textContent = transition.message || '';
        $('[data-workspace-menu]').open = !!transition.menuOpen;
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
  // Explicit links keep their initial scope; subsequent shared changes sync in either mode.
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
      window.refreshShareActivity?.();
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
  inheritViewFilters();
  options();
})();
