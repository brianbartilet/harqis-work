/* Shared corpus/Space expression editor. The backend owns parsing and validation. */
(() => {
  const fields = ['q','source','date_field','date_from','date_to','rolling','sort','order_by','page_size','has_media','exclude_tags','expression'];
  const defaults = {q:'',source:'',date_field:'created',date_from:'',date_to:'',rolling:0,sort:'desc',order_by:'',page_size:20,has_media:false,exclude_tags:'',expression:''};
  function initialize(panel) {
    if (panel.dataset.initialized) return;
    panel.dataset.initialized = 'true';
    const form = panel.closest('form');
    if (!form) return;
    const corpus = form.id === 'corpus-search-form';
    const find = selector => panel.querySelector(selector);
    const control = key => corpus ? form.elements[key] : form.querySelector(`[data-edit-filter="${key}"]`);
    const editor = find('[data-expression-editor]'), toggle = find('[data-expression-toggle]');
    const media = form.querySelector('[data-media-toggle]'), error = find('[data-expression-error]');
    const suggestions = find('[data-expression-suggestions]'), apply = find('[data-expression-apply]');
    const reset = find('[data-expression-reset]');
    ['expression', 'exclude'].forEach(kind => {
      const help = find(`[data-${kind}-help-dialog]`);
      const trigger = find(`[data-${kind}-help-open]`);
      if (!trigger) return;
      function positionHelp() {
        if (!help.matches(':popover-open')) return;
        const anchor = trigger.getBoundingClientRect();
        const bounds = help.getBoundingClientRect();
        help.style.left = Math.max(12, Math.min(anchor.left, innerWidth - bounds.width - 12)) + 'px';
        help.style.top = Math.max(12, anchor.bottom + 8 + bounds.height <= innerHeight - 12 ? anchor.bottom + 8 : anchor.top - bounds.height - 8) + 'px';
      }
      help.addEventListener('toggle', positionHelp);
      help.addEventListener('keydown', event => { if (event.key === 'Escape') event.stopPropagation(); });
      window.addEventListener('resize', positionHelp);
      document.addEventListener('scroll', positionHelp, true);
    });
    let generation = 0, timer, syncing = false, pending = false, checkingDraft = false, invalid = false, lastController;
    let choices = [], selected = -1;
    function snapshot() {
      const state = {...defaults};
      fields.forEach(key => { if (control(key)) state[key] = control(key).value; });
      ['rolling','page_size'].forEach(key => state[key] = Number(state[key]));
      state.has_media = String(state.has_media) === 'true';
      return state;
    }
    function updateSummary(data) {
      const excludedPills = form.querySelector('[data-excluded-tag-pills]');
      if (excludedPills) excludedPills.replaceChildren(...data.state.exclude_tags.split(',').map(tag => tag.trim().replace(/^#/, '')).filter(Boolean).map(tag => {
        const pill = document.createElement('span');
        pill.className = 'corpus-excluded-tag'; pill.title = 'Excluded tag'; pill.textContent = '#' + tag;
        return pill;
      }));
      const orderSummary = find('[data-order-summary]');
      orderSummary.hidden = !data.state.order_by; orderSummary.textContent = data.state.order_by ? 'Order by: ' + data.state.order_by : '';
      if (control('order_by')) control('order_by').value = data.state.order_by || '';
      const sortControl = control('sort');
      if (sortControl?.tagName === 'SELECT') [...sortControl.options].forEach(option => {
        option.textContent = data.state.order_by ? (option.value === 'asc' ? 'Primary field ascending' : 'Primary field descending') : (option.value === 'asc' ? 'Oldest first' : 'Newest first');
      });
    }
    function write(state) {
      syncing = true;
      fields.forEach(key => {
        const input = control(key); if (!input) return;
        input.value = String(state[key] ?? defaults[key]);
      });
      media.checked = !!state.has_media;
      const container = form.querySelector('[data-edit-source-options], .workspace-source-options');
      state.source.split(',').filter(Boolean).forEach(value => {
        if ([...form.querySelectorAll('[data-source-option], [data-edit-source-options] input')].some(input => input.value === value)) return;
        // The host screen owns rebuilding its source picker after synchronization.
        if (!corpus && container) {
          const label=document.createElement('label'), input=document.createElement('input');
          input.type='checkbox'; input.value=value; label.append(input, document.createTextNode(value)); container.append(label);
        }
      });
      const sources = new Set(state.source.split(','));
      form.querySelectorAll('[data-source-option], [data-edit-source-options] input').forEach(input => { input.checked = sources.has(input.value); });
      const sourceCaption = form.querySelector('[data-source-caption], [data-edit-source-caption]');
      if (sourceCaption) sourceCaption.textContent = sources.has('') ? 'All sources' : `${sources.size} selected`;
      fields.forEach(key => control(key)?.dispatchEvent(new Event('input', {bubbles:true})));
      control('rolling')?.dispatchEvent(new Event('change', {bubbles:true}));
      form.querySelectorAll('[data-workspace-tag]').forEach(link => {
        const tags = state.q.split(/\s+/).filter(v => v.startsWith('#')).map(v => v.slice(1).toLowerCase());
        const active = tags.some(tag => link.dataset.workspaceTag.toLowerCase().includes(tag));
        link.setAttribute('aria-pressed', String(active));
        ['bg-emerald-950/70','text-emerald-200','ring-1','ring-emerald-700/60'].forEach(name => link.classList.toggle(name,active));
        ['bg-blue-950/50','text-blue-300','hover:bg-blue-900','hover:text-blue-100'].forEach(name => link.classList.toggle(name,!active));
      });
      form.dispatchEvent(new CustomEvent('corpus:expression-state', {detail:state}));
      syncing = false;
    }
    async function translate(fromExpression) {
      const current = ++generation; lastController?.abort(); lastController = new AbortController();
      pending = true; checkingDraft = fromExpression; apply.disabled = true; error.textContent = '';
      try {
        const response = await fetch('/hfl-corpus/expression', {method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify(fromExpression ? {expression:editor.value} : {state:snapshot()}), signal:lastController.signal});
        if (response.redirected) throw Error('Sign in again to edit expressions.');
        const data = await response.json();
        if (current !== generation) return false;
        if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the expression values.');
        if (fromExpression) write(data.state); else editor.value = data.expression;
        updateSummary(data); invalid = false; error.textContent = ''; editor.setAttribute('aria-invalid', 'false');
        return true;
      } catch (failure) {
        if (current !== generation || failure.name === 'AbortError') return false;
        invalid = true; error.textContent = failure.message; editor.setAttribute('aria-invalid', 'true'); return false;
      } finally {
        if (current === generation) { pending = false; apply.disabled = !toggle.checked || invalid; }
      }
    }
    function queue(fromExpression) {
      clearTimeout(timer); generation++; lastController?.abort(); pending = true; checkingDraft = fromExpression; if (!fromExpression) invalid=false; apply.disabled = true;
      timer = setTimeout(() => translate(fromExpression), 250);
    }
    const excludeMenu = corpus ? form.querySelector('[data-exclude-tags-menu]') : null;
    if (excludeMenu) {
      const draft = excludeMenu.querySelector('[data-exclude-tags-input]');
      const save = excludeMenu.querySelector('[data-exclude-tags-save]');
      const status = excludeMenu.querySelector('[data-exclude-tags-status]');
      excludeMenu.querySelector('[data-tags-clear]').onclick = () => { draft.value = ''; status.hidden = true; draft.focus(); };
      excludeMenu.addEventListener('toggle', () => {
        const fromHotkey = !!excludeMenu.dataset.hotkeyToggle;
        delete excludeMenu.dataset.hotkeyToggle;
        if (excludeMenu.open) {
          draft.value = control('exclude_tags').value; status.hidden = true; if (!fromHotkey) draft.focus();
          const popup = excludeMenu.querySelector('.corpus-quick-tags-editor');
          popup.style.transform = '';
          const bounds = popup.getBoundingClientRect();
          popup.style.transform = `translateX(${Math.max(12 - bounds.left, Math.min(0, innerWidth - bounds.right - 12))}px)`;
        }
      });
      draft.addEventListener('input', event => event.stopPropagation());
      draft.addEventListener('change', event => event.stopPropagation());
      excludeMenu.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.stopPropagation(); excludeMenu.open = false; excludeMenu.querySelector('summary').focus(); }
        if (event.key === 'Enter' && event.target === draft) { event.preventDefault(); save.click(); }
      });
      document.addEventListener('click', event => { if (!excludeMenu.contains(event.target)) excludeMenu.open = false; });
      save.onclick = async () => {
        save.disabled = true; status.hidden = true; clearTimeout(timer);
        const previous = control('exclude_tags').value;
        control('exclude_tags').value = draft.value;
        if (await translate(false)) {
          control('exclude_tags').dispatchEvent(new Event('change', {bubbles:true}));
          excludeMenu.open = false; form.requestSubmit();
        } else {
          status.textContent = error.textContent; status.hidden = false;
          control('exclude_tags').value = previous;
          await translate(false);
        }
        save.disabled = false;
      };
    }
    function closeSuggestions() { suggestions.hidden = true; selected = -1; editor.setAttribute('aria-expanded','false'); editor.removeAttribute('aria-activedescendant'); }
    function suggest() {
      const prefix = editor.value.slice(0, editor.selectionStart), word = prefix.match(/[\w#-]*$/)?.[0] || '';
      const sourceValues = [...form.querySelectorAll('[data-source-option], [data-edit-source-options] input')].map(el => el.value);
      const tagValues = [...form.querySelectorAll('[data-workspace-tag]')].map(el => el.dataset.workspaceTag);
      for (const id of ['spaces-sources','spaces-tags']) {
        try { JSON.parse(document.getElementById(id)?.textContent || '[]').forEach(v => (id === 'spaces-tags' ? tagValues : sourceValues).push(typeof v === 'string' ? v : Array.isArray(v) ? v[0] : v.tag)); } catch (_) {}
      }
      let catalog;
      const fieldContext = prefix.match(/\b(source|tags)\s+(?:NOT\s+IN|IN|=|!=|~|!~)\s*\(?[^)]*$/i);
      const operatorContext = prefix.match(/\b(q|text|tags|source|hasMedia|entryDate|created|updated)\s+$/);
      const orderContext = prefix.match(/\bORDER\s+BY\s+([^]*)$/i);
      if (orderContext) {
        const part = orderContext[1].split(',').pop();
        catalog = /^\s*(source|entryDate|created|updated)\s+/i.test(part) ? ['ASC','DESC'] : ['source','entryDate','created','updated'];
      }
      else if (operatorContext) catalog = operatorContext[1] === 'hasMedia' ? ['=', '!='] : operatorContext[1] === 'q' ? ['~', '!~'] : ['entryDate','created','updated'].includes(operatorContext[1]) ? ['=', '!=', '>', '>=', '<', '<='] : ['=', '!=', '~', '!~', 'IN', 'NOT IN'];
      else if (fieldContext) catalog = [...new Set((fieldContext[1].toLowerCase() === 'tags' ? tagValues : sourceValues).filter(Boolean))].map(v => JSON.stringify(v));
      else if (/hasMedia\s*(?:=|!=)\s*\w*$/i.test(prefix)) catalog = ['true','false'];
      else catalog = ['q','text','tags','source','hasMedia','entryDate','created','updated','dateField','dateFrom','dateTo','rolling','sort','pageSize','ORDER BY','AND','OR','NOT','IN','NOT IN','=','!=','~','!~','>=','<='];
      choices = catalog.filter(value => value.replace(/^"/, '').toLowerCase().startsWith(word.toLowerCase())).slice(0, 10);
      suggestions.replaceChildren(); selected = -1;
      choices.forEach((choice, i) => { const option = document.createElement('button'); option.type='button'; option.role='option'; option.id=`expression-option-${i}`; option.textContent=choice; option.tabIndex=-1;
        option.addEventListener('mousedown', event => event.preventDefault()); option.onclick=() => accept(i); suggestions.append(option); });
      suggestions.hidden = !choices.length; editor.setAttribute('aria-expanded', String(!!choices.length));
    }
    function accept(i) {
      const prefix = editor.value.slice(0, editor.selectionStart), token = prefix.match(/"?[^\s(),=~<>!]*$/)?.[0] || '';
      editor.setRangeText(choices[i], editor.selectionStart-token.length, editor.selectionStart, 'end'); closeSuggestions(); editor.focus(); queue(true);
    }
    editor.addEventListener('input', () => { queue(true); suggest(); });
    editor.addEventListener('keydown', event => {
      if (event.key === 'Escape') { closeSuggestions(); return; }
      if (!suggestions.hidden && ['ArrowDown','ArrowUp'].includes(event.key)) {
        event.preventDefault(); selected = (selected + (event.key === 'ArrowDown' ? 1 : choices.length-1) + choices.length) % choices.length;
        [...suggestions.children].forEach((el,i) => el.setAttribute('aria-selected', String(i===selected)));
        editor.setAttribute('aria-activedescendant', `expression-option-${selected}`);
      } else if (!suggestions.hidden && selected >= 0 && ['Enter','Tab'].includes(event.key)) { event.preventDefault(); accept(selected); }
      else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); apply.click(); }
    });
    document.addEventListener('click', event => { if (!panel.contains(event.target)) closeSuggestions(); });
    toggle.onchange = () => {
      editor.disabled = !toggle.checked; closeSuggestions(); clearTimeout(timer);
      if (reset) reset.disabled = !toggle.checked;
      // Leaving edit mode discards an invalid draft, never the last valid filters.
      translate(false);
    };
    media.onchange = () => { control('has_media').value=String(media.checked); control('has_media').dispatchEvent(new Event('input',{bubbles:true})); };
    form.addEventListener('input', event => {
      if (syncing || event.target === editor || event.target === toggle || event.target === media) return;
      queue(false);
    });
    form.addEventListener('click', event => { if (event.target.closest('[data-sources-clear], [data-edit-sources-clear]')) queue(false); });
    form.addEventListener('change', event => {
      if (syncing || panel.contains(event.target)) return;
      queue(false);
    });
    apply.onclick = async () => {
      if (!toggle.checked) return;
      clearTimeout(timer); closeSuggestions();
      if (!await translate(toggle.checked)) return;
      if (!toggle.checked) return;
      if (corpus) form.requestSubmit(); else error.textContent='Filters applied to this draft. Save Space to keep them.';
    };
    form.addEventListener('submit', event => {
      if ((pending && checkingDraft) || invalid) { event.preventDefault(); event.stopImmediatePropagation(); panel.open=true; error.textContent=pending ? 'Wait for expression validation before applying.' : 'Fix the expression or turn expression editing off to keep the last valid filters.'; }
    }, true);
    panel.advancedValid = () => !(pending && checkingDraft) && !invalid;
    panel.refreshAdvanced = () => { media.checked = control('has_media')?.value === 'true'; translate(false); };
    editor.disabled = !toggle.checked;
    if (reset) reset.disabled = !toggle.checked;
    panel.refreshAdvanced();
  }
  window.initializeCorpusAdvanced = () => document.querySelectorAll('[data-advanced-filters]').forEach(initialize);
  window.initializeCorpusAdvanced();
})();
