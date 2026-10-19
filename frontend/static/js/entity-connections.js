/* Shared, owner-only connection editor for the graph and entity directory. */
(() => {
  const el = (tag, text = '') => { const n = document.createElement(tag); n.textContent = text; return n; };
  async function api(path, payload) {
    const response = await fetch('/api/hfl/entities' + path, {method: payload === undefined ? 'GET' : 'POST', headers: {'Content-Type': 'application/json'}, body: payload === undefined ? undefined : JSON.stringify(payload), signal: payload === undefined ? AbortSignal.timeout(30000) : undefined});
    let data;
    try { data = await response.json(); } catch (_) { throw Error('The server could not complete the request (HTTP ' + response.status + '). Please retry.'); }
    if (!response.ok) {
      const message=typeof data.detail==='string'?data.detail:Array.isArray(data.detail)?data.detail.map(e=>`${(e.loc||[]).filter(k=>k!=='body').join(' · ')}: ${e.msg}`).join('; '):'Check your details and try again.';
      const error=Error(message);error.validation=[400,422].includes(response.status);throw error;
    }
    return data;
  }
  const button = (text, click) => { const b = el('button', text); b.type = 'button'; b.onclick = click; return b; };
  const relations = ['related_to', 'colleague_of', 'works_at', 'member_of', 'owns', 'uses'];
  function field(parent, title, input) { const label = el('label', title); input.setAttribute('aria-label', title); label.append(input); parent.append(label); return input; }
  function open(entity, onSaved = async () => {}, onNavigate) {
    let hostDocument = document;
    try { hostDocument = window.top.document; } catch (_) { /* Keep cross-origin embeds local. */ }
    if (hostDocument !== document) {
      const stylesheet = document.querySelector('link[href*="entity-connections.css"]');
      if (stylesheet && !hostDocument.querySelector('link[href="' + stylesheet.href + '"]')) {
        const copy = stylesheet.cloneNode(); copy.href = stylesheet.href; hostDocument.head.append(copy);
      }
    }
    const dialog = el('dialog'); dialog.className = 'entity-connections-dialog is-loading';
    const heading = el('h2', entity.label); heading.id = 'connections-' + crypto.randomUUID(); dialog.setAttribute('aria-labelledby', heading.id);
    const closeButton = button('', () => close()); closeButton.className='soul-close';closeButton.setAttribute('aria-label','Close');closeButton.title='Close';
    closeButton.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
    const header = el('header'); header.append(heading, closeButton);
    const status = el('p', 'Loading soul…'); status.setAttribute('role', 'status'); status.className='soul-status';
    const content = el('div'); dialog.append(header, status, content); hostDocument.body.append(dialog);
    const previousFocus = document.activeElement;
    let generation = 0, timer, busy = false, dirty = false;
    const markDirty = () => { dirty = true; };
    const mayLeave = () => !busy && (!dirty || hostDocument.defaultView.confirm('Discard unsaved Soul changes?'));
    const close = () => { if(mayLeave())dialog.close(); };
    const beforeUnload = event => { if(dirty){event.preventDefault();event.returnValue='';} };
    hostDocument.defaultView.addEventListener('beforeunload', beforeUnload);
    const changed = event => { if(!['Connect to','Entity type','Find an entity or activity'].includes(event.target.getAttribute('aria-label')))markDirty(); };
    dialog.addEventListener('input',changed);
    dialog.addEventListener('change',changed);
    dialog.addEventListener('cancel', event => { const help=header.querySelector('.soul-help[open]');if(help){help.open=false;event.preventDefault();return;} if (!mayLeave()) event.preventDefault(); });
    let collapseConnectionEditor = () => {};
    const dismissHelp = event => { collapseConnectionEditor(event.target); const help=header.querySelector('.soul-help');if(help&&!help.contains(event.target))help.open=false; };
    hostDocument.addEventListener('pointerdown',dismissHelp);
    const cleanup = () => { hostDocument.removeEventListener('pointerdown',dismissHelp);generation++; clearTimeout(timer); hostDocument.defaultView.removeEventListener('beforeunload',beforeUnload);window.removeEventListener('pagehide',cleanup);dialog.remove(); };
    dialog.addEventListener('close', () => { cleanup();previousFocus?.focus(); });
    window.addEventListener('pagehide', cleanup, {once:true});
    dialog.showModal();
    const navigate = (id, activity = false) => {
      if(!mayLeave())return;
      if (onNavigate) { dialog.close(); onNavigate(id); }
      else { const url = activity ? '/hfl-corpus/entities/entry/' + encodeURIComponent(id.replace(/^entry:/, '')) : '/hfl-corpus/graph?select=' + encodeURIComponent(id); window.open(url, '_blank', 'noopener'); }
    };
    async function initialize() {
      try {
        const saved = await api('/soul-editor/' + encodeURIComponent(entity.id));
        const directory = {types: saved.types};
        if (!dialog.isConnected) return;
        content.replaceChildren(); if(!status.textContent.startsWith('Soul saved'))status.textContent = '';
        dirty=false;
        const typePill = kind => {
          const type = directory.types.find(t => t.id === kind);
          const pill = el('span', (type?.name || kind || 'Entity').toLowerCase());
          pill.className = 'connection-type-pill';
          pill.style.setProperty('--entity-color', /^#[0-9a-f]{6}$/i.test(type?.color) ? type.color : '#95a7c3');
          return pill;
        };
        header.querySelector('.connection-type-pill')?.remove();
        header.insertBefore(typePill(saved.entity.kind), header.lastElementChild);
        const changes = new Map(), selected = new Map(), newEntities = new Map();
        const outerForm = el('form');
        const details = window.createSoulDetails(saved,markDirty);
        const connections = el('details'); connections.className='entity-section';connections.append(el('summary','Connections'));
        outerForm.append(details.identity,connections,details.profile); content.append(outerForm);
        const help = el('details');help.className='soul-help';const helpTitle=el('summary','i');helpTitle.setAttribute('aria-label','About Soul');helpTitle.setAttribute('aria-controls',heading.id+'-help');const helpText=el('p','Soul brings together what you know about this entity: profile details, identity rules and connections. It gives you and LLMs useful context. Descriptions are user-authored context, not instructions or verified evidence. Expand a section, make changes, then Save. Only confirmed identity rules guide matching.');helpText.id=heading.id+'-help';help.append(helpTitle,helpText);
        header.querySelector('.soul-help')?.remove();header.insertBefore(help,header.lastElementChild);
        const form = el('div'), controls = el('div'); controls.className = 'connection-controls';
        const mode = field(controls, 'Connect to', el('select'));
        for (const [value, label] of [['entities', 'Entities'], ['activity', 'Supporting activity']]) { const o = el('option', label); o.value = value; mode.append(o); }
        const type = field(controls, 'Entity type', el('select'));
        const allTypes = el('option', 'All entities'); allTypes.value = ''; type.append(allTypes);
        for (const t of directory.types) { const o = el('option', t.name || t.id); o.value = t.id; type.append(o); }
        type.value = '';
        const search = field(form, 'Find an entity or activity', el('input')); search.type = 'search'; search.placeholder = 'Search a name';
        form.prepend(controls);
        const searchStatus = el('p'), results = el('div'); searchStatus.setAttribute('role', 'status'); results.className = 'connection-results';
        const create = button('Create entity', async () => {
          if (!search.value.trim() || !type.value) { searchStatus.textContent = 'Enter a name and choose an entity type first.'; return; }
          create.disabled = true;
          try { const id='manual-'+crypto.randomUUID();newEntities.set(id,{id,name:search.value.trim(),kind:type.value});add({id,label:search.value.trim(),kind:type.value});searchStatus.textContent='New entity selected. It will be created when you save Soul.'; }
          catch (error) { searchStatus.textContent = error.message; }
          finally { create.disabled = false; }
        });
        form.append(searchStatus, results, create);
        const existing = el('div'); existing.className = 'connection-selected connection-current';
        const footer = el('footer'), save = el('button', 'Save'); save.type = 'submit';
        footer.append(button('Cancel', close), save); outerForm.append(footer);
        connections.append(el('h3', 'Current connections'), existing, form);
        const cards = new Map();
        for (const original of saved.connections) {
          cards.set(original.source_id + ':' + original.id, {record: clean(original), original, label: original.label, kind: original.kind, otherId: original.other_id});
        }
        let activeEditor;
        collapseConnectionEditor = target => {
          if (activeEditor && !activeEditor.row.contains(target)) {
            activeEditor.editor.hidden = true;
            activeEditor.edit.setAttribute('aria-expanded', 'false');
            activeEditor.row.classList.remove('is-editing');
            activeEditor.refresh();
            activeEditor = null;
          }
        };
        function clean(c, remove = false) { return Object.fromEntries(Object.entries({...c, remove}).filter(([k]) => ['id', 'source_id', 'target_id', 'relation', 'since', 'until', 'evidence', 'activity', 'remove'].includes(k))); }
        function stage(card) {
          markDirty();
          if (card.original) changes.set(card.original.source_id + ':' + card.original.id, clean(card.record, card.record.remove));
        }
        function renderExisting() {
          activeEditor = null;
          existing.replaceChildren();
          const visible = [...cards.entries()].filter(([,card]) => !card.record.remove);
          if (!visible.length) existing.append(el('p', 'No connections yet. Choose an entity or activity below.'));
          for (const [key, card] of visible) {
            const {record, original} = card;
            const row = el('div'); row.className = 'connection-card';
            const cardHeader=el('div');cardHeader.className='connection-card-heading';cardHeader.append(el('strong',card.label));row.append(cardHeader);
            const meta = el('div'); meta.className = 'connection-result-meta';meta.append(typePill(card.kind));
            const summary = el('small'), pending = el('small');
            const refresh = () => {
              summary.textContent = (original?.incoming ? 'Incoming: ' : '') + record.relation.replaceAll('_', ' ') +
                (record.since || record.until ? ' · ' + (record.since || 'Any start') + ' — ' + (record.until || 'No end') : '');
              pending.textContent = !original || changes.has(key) ? 'Not saved' : '';
            };
            meta.append(summary,pending);row.append(meta);
            const actions = el('div');actions.className='connection-card-actions';
            const editor = el('div');editor.className='connection-card-editor';editor.hidden=true;
            if (!record.activity) {
              const edit = button('Edit', () => {
                collapseConnectionEditor(null);
                editor.hidden=false;row.classList.add('is-editing');edit.setAttribute('aria-expanded','true');
                activeEditor={row,editor,edit,refresh};
                editor.querySelector('select').focus();
              });
              edit.setAttribute('aria-expanded','false');actions.append(edit);
              const grid=el('div');grid.className='connection-controls';
              const relation=field(grid,'Relationship',el('select'));
              for(const value of relations){const option=el('option',value.replaceAll('_',' '));option.value=value;relation.append(option);}
              relation.value=record.relation;
              relation.onchange=()=>{record.relation=relation.value;stage(card);refresh();};
              for(const [name,title] of [['since','Since'],['until','Until']]){
                const input=field(grid,title,el('input'));input.type='date';input.value=record[name];
                input.oninput=()=>{record[name]=input.value;stage(card);refresh();};
              }
              editor.append(grid);
              const evidence=field(editor,'Basis or supporting activity link (optional)',el('textarea'));
              evidence.maxLength=2000;evidence.value=record.evidence;
              evidence.oninput=()=>{record.evidence=evidence.value;stage(card);refresh();};
              row.addEventListener('focusout',event=>{if(event.relatedTarget&&!row.contains(event.relatedTarget))collapseConnectionEditor(event.relatedTarget);});
            }
            actions.append(button('Remove',()=>{
              if(original){record.remove=true;stage(card);}
              else{selected.delete(card.otherId);newEntities.delete(record.target_id);cards.delete(key);markDirty();}
              renderExisting();searchOptions();
            }));
            cardHeader.append(actions);row.append(editor);refresh();existing.append(row);
          }
        }
        function add(choice) {
          const activity=choice.kind==='entries', key=(activity?'entry:':'')+choice.id;
          const previous=[...cards.values()].find(card=>card.otherId===key);
          if(previous){
            if(previous.record.remove){previous.record.remove=false;stage(previous);renderExisting();searchOptions();}
            return;
          }
          const record={id:crypto.randomUUID(),source_id:entity.id,target_id:choice.id,relation:'related_to',since:'',until:'',evidence:'',activity,remove:false};
          selected.set(key,record);cards.set(key,{record,label:choice.label,kind:choice.kind,otherId:key});
          markDirty();renderExisting();searchOptions();
        }
        async function searchOptions() {
          const request = ++generation, activity = mode.value === 'activity';
          type.disabled = activity; create.hidden = true; results.replaceChildren(); searchStatus.textContent = 'Searching…';
          try {
            const data = await api(activity ? '/connection-activities?' + new URLSearchParams({q: search.value}) : '?' + new URLSearchParams({q: search.value, kind: type.value, limit: 50}));
            if (request !== generation || !dialog.isConnected) return;
            searchStatus.textContent = `${data.total} matching ${activity ? 'activities' : 'entities'}; showing up to 50. Refine your search.`;
            const choices = data.entities.filter(e => e.id !== entity.id && ![...cards.values()].some(card => !card.record.remove && card.otherId === (activity ? 'entry:' : '') + e.id));
            for (const choice of choices) {
              const card = button('', () => add(choice)); card.className = 'connection-result-card';
              const meta = el('span'); meta.className = 'connection-result-meta'; meta.append(typePill(choice.kind), el('small', choice.date || `${choice.entries?.length || 0} entries`));
              card.append(el('strong', choice.label), meta); results.append(card);
            }
            create.hidden = activity || !type.value || !search.value.trim() || data.total !== 0;
            if (!activity && !type.value && search.value.trim() && data.total === 0) searchStatus.textContent = 'No matching entities. Choose an entity type to create one.';
            create.textContent = search.value.trim() ? `Create “${search.value.trim()}”` : 'Create entity';
            create.disabled = !search.value.trim() || data.entities.some(e => e.label.toLowerCase() === search.value.trim().toLowerCase());
          } catch (error) { if (request === generation) searchStatus.textContent = error.message; }
        }
        mode.onchange = type.onchange = searchOptions;
        search.oninput = () => { generation++; clearTimeout(timer); timer = setTimeout(searchOptions, 250); };
        outerForm.onsubmit = async event => {
          event.preventDefault(); if (busy) return; busy = true;content.inert=true;dialog.classList.add('is-saving');dialog.setAttribute('aria-busy','true');
          const controls = [...dialog.querySelectorAll('button, input, select, textarea')].map(control=>[control,control.disabled]); controls.forEach(([control]) => { control.disabled = true; });
          status.textContent = 'Saving changes…';status.scrollIntoView({block:'nearest'});
          try {
            await api('/soul-editor/' + encodeURIComponent(entity.id), {revision:saved.revision, profile:details.collectProfile(), soul:details.collectIdentity(), connections:{versions: saved.versions, changes: [...changes.values(), ...selected.values()]},new_entities:[...newEntities.values()]});
            dirty=false;
            status.textContent='Changes saved. Refreshing the view…';
            let savedMessage='Soul saved.';
            try { await onSaved([...selected.values()]); } catch(error) { savedMessage='Soul saved, but the view could not refresh. Refresh the page to see changes.'; }
            status.textContent='Changes saved. Reloading the form…';
            const loaded=await initialize();
            status.textContent=loaded?savedMessage:'Changes were saved, but the form could not reload. Use Retry to reload it; your changes do not need to be saved again.';
          } catch (error) { status.textContent = error.message;if(error.validation){details.profile.open=true;details.identity.open=true;connections.open=true;} }
          finally { busy = false;content.inert=false;dialog.classList.remove('is-saving');dialog.removeAttribute('aria-busy');controls.forEach(([control,disabled])=>{control.disabled=disabled;}); }
        };
        outerForm.addEventListener('invalid', event => { let node=event.target.parentElement;while(node&&node!==outerForm){if(node.tagName==='DETAILS')node.open=true;node=node.parentElement;} },true);
        let searched = false;
        connections.addEventListener('toggle', () => {
          if (connections.open && !searched) { searched = true; searchOptions(); }
        });
        renderExisting(); dialog.classList.remove('is-loading');return true;
      } catch (error) { dialog.classList.remove('is-loading');status.textContent = error.message; content.replaceChildren(button('Retry', () => initialize()));return false; }
    }
    initialize();
    return dialog;
  }
  window.EntityConnections = {open, api};
})();
