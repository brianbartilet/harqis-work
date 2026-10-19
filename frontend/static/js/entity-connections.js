/* Shared, owner-only connection editor for the graph and entity directory. */
(() => {
  const el = (tag, text = '') => { const n = document.createElement(tag); n.textContent = text; return n; };
  async function api(path, payload) {
    const response = await fetch('/api/hfl/entities' + path, {method: payload === undefined ? 'GET' : 'POST', headers: {'Content-Type': 'application/json'}, body: payload === undefined ? undefined : JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check your details and try again.');
    return data;
  }
  const button = (text, click) => { const b = el('button', text); b.type = 'button'; b.onclick = click; return b; };
  const relations = ['related_to', 'colleague_of', 'works_at', 'member_of', 'owns', 'uses'];
  function field(parent, title, input) { const label = el('label', title); input.setAttribute('aria-label', title); label.append(input); parent.append(label); return input; }
  function open(entity, onSaved = async () => {}, onNavigate) {
    const dialog = el('dialog'); dialog.className = 'entity-connections-dialog';
    const heading = el('h2', 'Connections · ' + entity.label); heading.id = 'connections-' + crypto.randomUUID(); dialog.setAttribute('aria-labelledby', heading.id);
    const header = el('header'); header.append(heading, button('Close', () => dialog.close()));
    const status = el('p', 'Loading connections…'); status.setAttribute('role', 'status');
    const content = el('div'); dialog.append(header, status, content); document.body.append(dialog);
    const previousFocus = document.activeElement;
    let generation = 0, timer, busy = false;
    dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    dialog.addEventListener('close', () => { generation++; clearTimeout(timer); dialog.remove(); previousFocus?.focus(); });
    dialog.showModal();
    const navigate = (id, activity = false) => {
      if (onNavigate) { dialog.close(); onNavigate(id); }
      else { const url = activity ? '/hfl-corpus/entities/entry/' + encodeURIComponent(id.replace(/^entry:/, '')) : '/hfl-corpus/graph?select=' + encodeURIComponent(id); window.open(url, '_blank', 'noopener'); }
    };
    async function initialize() {
      try {
        const [saved, directory] = await Promise.all([api('/connections/' + encodeURIComponent(entity.id)), api('?limit=1')]);
        if (!dialog.isConnected) return;
        content.replaceChildren(); if(status.textContent !== 'Connections saved.')status.textContent = '';
        const changes = new Map(), selected = new Map();
        const form = el('form'), controls = el('div'); controls.className = 'connection-controls';
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
          try { const result = await api('/create', {name: search.value.trim(), kind: type.value}); add({id: result.id, label: search.value.trim(), kind: type.value}); searchStatus.textContent = 'Entity created. Save connections to link it.'; }
          catch (error) { searchStatus.textContent = error.message; }
          finally { create.disabled = false; }
        });
        const list = el('div'); list.className = 'connection-selected';
        const count = el('p'); count.setAttribute('role', 'status');
        form.append(searchStatus, results, create, el('h3', 'Selected connections'), count, list);
        const existing = el('div'); existing.className = 'connection-selected';
        const footer = el('footer'), save = el('button', 'Save connections'); save.type = 'submit';
        footer.append(button('Cancel', () => dialog.close()), save); form.append(footer);
        content.append(el('h3', 'Current connections'), existing, form);
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
            row.append(button(changes.has(key) ? 'Undo removal' : 'Remove connection', () => { changes.has(key) ? changes.delete(key) : changes.set(key, clean(connection, true)); renderExisting(); }));
            existing.append(row);
          }
        }
        function clean(c, remove = false) { return Object.fromEntries(Object.entries({...c, remove}).filter(([k]) => ['id', 'source_id', 'target_id', 'relation', 'since', 'until', 'evidence', 'activity', 'remove'].includes(k))); }
        function add(choice, original = null) {
          const activity = choice.kind === 'entries', key = (activity ? 'entry:' : '') + choice.id;
          if (selected.has(key)) return;
          const record = {id: crypto.randomUUID(), source_id: entity.id, target_id: choice.id, relation: 'related_to', since: '', until: '', evidence: '', activity, remove: false};
          if(original)Object.assign(record,clean(original));
          selected.set(key, record);
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
          row.append(button('Remove selection', () => { selected.delete(key); row.remove(); count.textContent = selected.size + ' selected'; searchOptions(); }));
          list.append(row); count.textContent = selected.size + ' selected'; searchOptions();
        }
        async function searchOptions() {
          const request = ++generation, activity = mode.value === 'activity';
          type.disabled = activity; create.hidden = activity; results.replaceChildren(); searchStatus.textContent = 'Searching…';
          try {
            const data = await api(activity ? '/connection-activities?' + new URLSearchParams({q: search.value}) : '?' + new URLSearchParams({q: search.value, kind: type.value, limit: 50}));
            if (request !== generation || !dialog.isConnected) return;
            searchStatus.textContent = `${data.total} matching ${activity ? 'activities' : 'entities'}; showing up to 50. Refine your search.`;
            const choices = data.entities.filter(e => e.id !== entity.id && !selected.has((activity ? 'entry:' : '') + e.id));
            for (const choice of choices) {
              const card = button('', () => add(choice)); card.className = 'connection-result-card';
              card.append(el('strong', choice.label), el('small', choice.kind + ' · ' + (choice.date || `${choice.entries?.length || 0} entries`))); results.append(card);
            }
            create.textContent = search.value.trim() ? `Create “${search.value.trim()}”` : 'Create entity';
            create.disabled = !search.value.trim() || data.entities.some(e => e.label.toLowerCase() === search.value.trim().toLowerCase());
          } catch (error) { if (request === generation) searchStatus.textContent = error.message; }
        }
        mode.onchange = type.onchange = searchOptions;
        search.oninput = () => { generation++; clearTimeout(timer); timer = setTimeout(searchOptions, 250); };
        form.onsubmit = async event => {
          event.preventDefault(); if (busy) return; busy = true;
          const controls = [...dialog.querySelectorAll('button, input, select, textarea')]; controls.forEach(c => { c.disabled = true; });
          status.textContent = 'Saving connections…';
          try {
            await api('/connections/' + encodeURIComponent(entity.id), {versions: saved.versions, changes: [...changes.values(), ...selected.values()]});
            await onSaved([...selected.values()]);
            status.textContent = 'Connections saved.'; await initialize();
          } catch (error) { status.textContent = error.message; }
          finally { busy = false; controls.forEach(c => { c.disabled = false; }); }
        };
        renderExisting(); await searchOptions();
      } catch (error) { status.textContent = error.message; content.replaceChildren(button('Retry', initialize)); }
    }
    initialize();
    return dialog;
  }
  window.EntityConnections = {open, api};
})();
