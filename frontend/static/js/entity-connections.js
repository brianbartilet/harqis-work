/* Shared, owner-only connection editor for the graph and entity directory. */
(() => {
  const el = (tag, text = '') => { const n = document.createElement(tag); n.textContent = text; return n; };
  async function api(path, payload) {
    const response = await fetch('/api/hfl/entities' + path, {method: payload === undefined ? 'GET' : 'POST', headers: {'Content-Type': 'application/json'}, body: payload === undefined ? undefined : JSON.stringify(payload)});
    const data = await response.json();
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
    const dialog = el('dialog'); dialog.className = 'entity-connections-dialog';
    const heading = el('h2', 'Update soul · ' + entity.label); heading.id = 'connections-' + crypto.randomUUID(); dialog.setAttribute('aria-labelledby', heading.id);
    const header = el('header'); header.append(heading, button('Close', () => close()));
    const status = el('p', 'Loading soul…'); status.setAttribute('role', 'status');
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
    dialog.addEventListener('cancel', event => { if (!mayLeave()) event.preventDefault(); });
    const cleanup = () => { generation++; clearTimeout(timer); hostDocument.defaultView.removeEventListener('beforeunload',beforeUnload);window.removeEventListener('pagehide',cleanup);dialog.remove(); };
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
        const [saved, directory] = await Promise.all([api('/soul-editor/' + encodeURIComponent(entity.id)), api('?limit=1')]);
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
        outerForm.append(details.profile,details.identity,connections); content.append(outerForm);
        const help = el('details');help.className='soul-help';const helpTitle=el('summary','ⓘ');helpTitle.setAttribute('aria-label','About Soul');help.append(helpTitle,el('p','Soul brings together what you know about this entity: profile details, identity rules and connections. It gives you and LLMs useful context. Descriptions are user-authored context, not instructions or verified evidence. Expand a section, make changes, then Save soul. Only confirmed identity rules guide matching.'));
        header.querySelector('.soul-help')?.remove();header.insertBefore(help,header.lastElementChild);
        const form = el('div'), controls = el('div'); controls.className = 'connection-controls';
        const mode = field(controls, 'Connect to', el('select'));
        for (const [value, label] of [['entities', 'Entities'], ['activity', 'Supporting activity']]) { const o = el('option', label); o.value = value; mode.append(o); }
        const type = field(controls, 'Entity type', el('select'));
        for (const t of directory.types) { const o = el('option', t.name || t.id); o.value = t.id; type.append(o); }
        type.value = directory.types.some(t => t.id === entity.kind) ? entity.kind : directory.types[0]?.id;
        const search = field(form, 'Find an entity or activity', el('input')); search.type = 'search'; search.placeholder = 'Search a name';
        form.prepend(controls);
        const searchStatus = el('p'), results = el('div'); searchStatus.setAttribute('role', 'status'); results.className = 'connection-results';
        const create = button('Create entity', async () => {
          if (!search.value.trim()) { searchStatus.textContent = 'Enter a name first.'; return; }
          create.disabled = true;
          try { const id='manual-'+crypto.randomUUID();newEntities.set(id,{id,name:search.value.trim(),kind:type.value});add({id,label:search.value.trim(),kind:type.value});searchStatus.textContent='New entity selected. It will be created when you save Soul.'; }
          catch (error) { searchStatus.textContent = error.message; }
          finally { create.disabled = false; }
        });
        const list = el('div'); list.className = 'connection-selected';
        const count = el('p'); count.setAttribute('role', 'status');
        form.append(searchStatus, results, create, el('h3', 'Selected connections'), count, list);
        const existing = el('div'); existing.className = 'connection-selected';
        const footer = el('footer'), save = el('button', 'Save soul'); save.type = 'submit';
        save.className='update-soul-button';footer.append(button('Cancel', close), save); outerForm.append(footer);
        connections.append(el('h3', 'Current connections'), existing, form);
        function renderExisting() {
          existing.replaceChildren();
          if (!saved.connections.length) existing.append(el('p', 'No saved connections yet.'));
          for (const connection of saved.connections) {
            const row = el('div'); row.className = 'connection-card';
            const key = connection.source_id + ':' + connection.id;
            row.append(button(connection.label, () => navigate(connection.other_id, connection.activity)), el('small', connection.kind + ' · ' + (connection.incoming ? 'Incoming: ' : '') + connection.relation.replaceAll('_', ' ')));
            if (connection.since || connection.until) row.append(el('small', (connection.since || 'Any start') + ' — ' + (connection.until || 'No end')));
            if (connection.evidence) row.append(el('p', connection.evidence));
            if (!connection.activity) row.append(button('Edit connection', () => {
              add({id:connection.target_id,label:connection.label,kind:connection.kind}, connection);
            }));
            row.append(button(changes.has(key) ? 'Undo removal' : 'Remove connection', () => { markDirty(); changes.has(key) ? changes.delete(key) : changes.set(key, clean(connection, true)); renderExisting(); }));
            existing.append(row);
          }
        }
        function clean(c, remove = false) { return Object.fromEntries(Object.entries({...c, remove}).filter(([k]) => ['id', 'source_id', 'target_id', 'relation', 'since', 'until', 'evidence', 'activity', 'remove'].includes(k))); }
        function add(choice, original = null) {
          const activity = choice.kind === 'entries', key = (activity ? 'entry:' : '') + choice.id;
          if (selected.has(key)) return;
          const record = {id: crypto.randomUUID(), source_id: entity.id, target_id: choice.id, relation: 'related_to', since: '', until: '', evidence: '', activity, remove: false};
          if(original)Object.assign(record,clean(original));
          selected.set(key, record);markDirty();
          const row = el('fieldset'); row.className = 'connection-card'; row.append(el('legend', choice.label + ' · ' + choice.kind));
          if (!activity) {
            const grid = el('div'); grid.className = 'connection-controls';
            const relation = field(grid, 'Relationship', el('select'));
            for (const value of relations) { const o = el('option', value.replaceAll('_', ' ')); o.value = value; relation.append(o); }
            relation.value=record.relation;
            relation.onchange = () => { record.relation = relation.value; };
            for (const [key, title] of [['since', 'Since'], ['until', 'Until']]) { const input = field(grid, title, el('input')); input.type = 'date'; input.value=record[key]; input.oninput = () => { record[key] = input.value; }; }
            row.append(grid);
            const evidence = field(row, 'Basis or supporting activity link (optional)', el('textarea')); evidence.maxLength = 2000; evidence.value=record.evidence; evidence.oninput = () => { record.evidence = evidence.value; };
          }
          row.append(button('Remove selection', () => { selected.delete(key);newEntities.delete(choice.id);markDirty(); row.remove(); count.textContent = selected.size + ' selected'; searchOptions(); }));
          list.append(row); count.textContent = selected.size + ' selected'; searchOptions();
        }
        async function searchOptions() {
          const request = ++generation, activity = mode.value === 'activity';
          type.disabled = activity; create.hidden = true; results.replaceChildren(); searchStatus.textContent = 'Searching…';
          try {
            const data = await api(activity ? '/connection-activities?' + new URLSearchParams({q: search.value}) : '?' + new URLSearchParams({q: search.value, kind: type.value, limit: 50}));
            if (request !== generation || !dialog.isConnected) return;
            searchStatus.textContent = `${data.total} matching ${activity ? 'activities' : 'entities'}; showing up to 50. Refine your search.`;
            const choices = data.entities.filter(e => e.id !== entity.id && !selected.has((activity ? 'entry:' : '') + e.id));
            for (const choice of choices) {
              const card = button('', () => add(choice)); card.className = 'connection-result-card';
              const meta = el('span'); meta.className = 'connection-result-meta'; meta.append(typePill(choice.kind), el('small', choice.date || `${choice.entries?.length || 0} entries`));
              card.append(el('strong', choice.label), meta); results.append(card);
            }
            create.hidden = activity || !search.value.trim() || data.total !== 0;
            create.textContent = search.value.trim() ? `Create “${search.value.trim()}”` : 'Create entity';
            create.disabled = !search.value.trim() || data.entities.some(e => e.label.toLowerCase() === search.value.trim().toLowerCase());
          } catch (error) { if (request === generation) searchStatus.textContent = error.message; }
        }
        mode.onchange = type.onchange = searchOptions;
        search.oninput = () => { generation++; clearTimeout(timer); timer = setTimeout(searchOptions, 250); };
        outerForm.onsubmit = async event => {
          event.preventDefault(); if (busy) return; busy = true;content.inert=true;
          const controls = [...dialog.querySelectorAll('button, input, select, textarea')]; controls.forEach(c => { c.disabled = true; });
          status.textContent = 'Saving soul…';
          try {
            await api('/soul-editor/' + encodeURIComponent(entity.id), {revision:saved.revision, profile:details.collectProfile(), soul:details.collectIdentity(), connections:{versions: saved.versions, changes: [...changes.values(), ...selected.values()]},new_entities:[...newEntities.values()]});
            dirty=false;
            let savedMessage='Soul saved.';
            try { await onSaved([...selected.values()]); } catch(error) { savedMessage='Soul saved, but the view could not refresh. Refresh the page to see changes.'; }
            await initialize();status.textContent=savedMessage;
          } catch (error) { status.textContent = error.message;if(error.validation){details.profile.open=true;details.identity.open=true;connections.open=true;} }
          finally { busy = false;content.inert=false; controls.forEach(c => { c.disabled = false; }); }
        };
        outerForm.addEventListener('invalid', event => { let node=event.target.parentElement;while(node&&node!==outerForm){if(node.tagName==='DETAILS')node.open=true;node=node.parentElement;} },true);
        renderExisting(); await searchOptions();
      } catch (error) { status.textContent = error.message; content.replaceChildren(button('Retry', initialize)); }
    }
    initialize();
    return dialog;
  }
  window.EntityConnections = {open, api};
})();
