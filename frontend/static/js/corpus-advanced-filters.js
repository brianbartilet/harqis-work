/* Shared corpus/Space expression editor. The backend owns parsing and validation. */
(() => {
  const fields = ['q','source','date_field','date_from','date_to','rolling','sort','page_size','has_media','exclude_tags','expression'];
  const defaults = {q:'',source:'',date_field:'created',date_from:'',date_to:'',rolling:0,sort:'desc',page_size:20,has_media:false,exclude_tags:'',expression:''};
  function initialize(panel) {
    if (panel.dataset.initialized) return;
    panel.dataset.initialized = 'true';
    const form = panel.closest('form');
    if (!form) return;
    const corpus = form.id === 'corpus-search-form';
    const find = selector => panel.querySelector(selector);
    const control = key => corpus ? form.elements[key] : form.querySelector(`[data-edit-filter="${key}"]`);
    const editor = find('[data-expression-editor]'), toggle = find('[data-expression-toggle]');
    const media = find('[data-media-toggle]'), error = find('[data-expression-error]');
    const suggestions = find('[data-expression-suggestions]'), apply = find('[data-expression-apply]');
    let generation = 0, timer, syncing = false, pending = false, checkingDraft = false, invalid = false, lastController;
    let choices = [], selected = -1;
    function snapshot() {
      const state = {...defaults};
      fields.forEach(key => { if (control(key)) state[key] = control(key).value; });
      ['rolling','page_size'].forEach(key => state[key] = Number(state[key]));
      state.has_media = String(state.has_media) === 'true';
      return state;
    }
    function tree(node, parent) {
      if (!node) return;
      const line = document.createElement('div'); line.className = 'expression-tree-node';
      if (node[0] === 'term') line.textContent = `${node[1]} ${node[2]} ${JSON.stringify(node[3])}`;
      else { const label = document.createElement('strong'); label.textContent = node[0].toUpperCase(); line.append(label); node.slice(1).forEach(child => tree(child, line)); }
      parent.append(line);
    }
    function updateSummary(data) {
      const summary = find('[data-expression-summary]'), target = find('[data-expression-tree]');
      target.replaceChildren(); summary.hidden = !data.state.expression; tree(data.tree, target);
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
        // Corpus sources are limited to the existing catalog by backend validation.
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
      });
      form.dispatchEvent(new CustomEvent('corpus:expression-state', {detail:state}));
      syncing = false;
    }
    async function translate(fromExpression) {
      const current = ++generation; lastController?.abort(); lastController = new AbortController();
      pending = true; checkingDraft = fromExpression; apply.disabled = true; error.textContent = 'Validating…';
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
        if (current === generation) { pending = false; apply.disabled = invalid; }
      }
    }
    function queue(fromExpression) {
      clearTimeout(timer); generation++; lastController?.abort(); pending = true; checkingDraft = fromExpression; if (!fromExpression) invalid=false; apply.disabled = true;
      timer = setTimeout(() => translate(fromExpression), 250);
    }
    function closeSuggestions() { suggestions.hidden = true; selected = -1; editor.setAttribute('aria-expanded','false'); editor.removeAttribute('aria-activedescendant'); }
    function suggest() {
      const prefix = editor.value.slice(0, editor.selectionStart), word = prefix.match(/[\w#-]*$/)?.[0] || '';
      const values = [...form.querySelectorAll('[data-source-option], [data-edit-source-options] input, [data-workspace-tag]')].map(el => el.dataset.workspaceTag || el.value);
      for (const id of ['spaces-sources','spaces-tags']) {
        try { JSON.parse(document.getElementById(id)?.textContent || '[]').forEach(v => values.push(typeof v === 'string' ? v : Array.isArray(v) ? v[0] : v.tag)); } catch (_) {}
      }
      let catalog;
      const fieldContext = prefix.match(/\b(source|tags)\s+(?:NOT\s+IN|IN|=|!=|~|!~)\s*\(?[^)]*$/i);
      if (fieldContext) catalog = [...new Set(values.filter(Boolean))].map(v => JSON.stringify(v));
      else if (/hasMedia\s*(?:=|!=)\s*\w*$/i.test(prefix)) catalog = ['true','false'];
      else catalog = ['q','text','tags','source','hasMedia','entryDate','created','updated','dateField','dateFrom','dateTo','rolling','sort','pageSize','AND','OR','NOT','IN','NOT IN','=','!=','~','!~','>=','<='];
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
      // Leaving edit mode discards an invalid draft, never the last valid filters.
      translate(false);
    };
    media.onchange = () => { control('has_media').value=String(media.checked); control('has_media').dispatchEvent(new Event('input',{bubbles:true})); };
    form.addEventListener('input', event => {
      if (syncing || event.target === editor || event.target === toggle || event.target === media) return;
      queue(false);
    });
    form.addEventListener('change', event => {
      if (syncing || panel.contains(event.target)) return;
      queue(false);
    });
    apply.onclick = async () => {
      clearTimeout(timer); closeSuggestions();
      if (!await translate(toggle.checked)) return;
      if (corpus) form.requestSubmit(); else error.textContent='Filters applied to this draft. Save Space to keep them.';
    };
    form.addEventListener('submit', event => {
      if ((pending && checkingDraft) || invalid) { event.preventDefault(); event.stopImmediatePropagation(); panel.open=true; error.textContent=pending ? 'Wait for expression validation before applying.' : 'Fix the expression or turn expression editing off to keep the last valid filters.'; }
    }, true);
    panel.advancedValid = () => !(pending && checkingDraft) && !invalid;
    panel.refreshAdvanced = () => { media.checked = control('has_media')?.value === 'true'; translate(false); };
    panel.refreshAdvanced();
  }
  window.initializeCorpusAdvanced = () => document.querySelectorAll('[data-advanced-filters]').forEach(initialize);
  window.initializeCorpusAdvanced();
})();
