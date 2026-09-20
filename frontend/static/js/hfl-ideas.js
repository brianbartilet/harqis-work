/* Ideas, reusable object editors, and named map membership. No agent runs on save. */
window.HflObjectDescription = (item = {}) => {
  const body = item.body || '', description = item.description || '';
  return !description.trim() || description.trim() === body.trim() ? body : description + (body.trim() ? '\n\n' + body : '');
};
(() => {
  if (window.HflIdeas) return;
  document.addEventListener('invalid', event => {
    const section = event.target.closest('.action-details');
    if (section) section.open = true;
  }, true);
  document.addEventListener('reset', event => {
    event.target.querySelectorAll?.('.action-details').forEach(section => { section.open = false; });
  }, true);
  const base = '/hfl-corpus/timeline/ideas';
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const token = () => document.querySelector('[data-input-editor]')?.dataset.csrf || '';
  async function request(url, options = {}) {
    const response = await fetch(url, {...options, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': token(), ...options.headers}});
    let data; try { data = await response.json(); } catch { throw Error('The service could not respond. Retry shortly.'); }
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Could not save. Check the fields and retry.');
    return data;
  }
  const api = (path, method = 'GET', data) => request(base + path, {method, ...(data === undefined ? {} : {body: JSON.stringify(data)})});
  const button = (text, action) => { const b = el('button', text); b.type = 'button'; b.onclick = action; return b; };
  const changed = () => { window.dispatchEvent(new Event('hfl:ideas-updated')); window.dispatchEvent(new Event('hfl:actions-updated')); };
  function dialog(title) {
    const node = el('dialog', undefined, 'idea-dialog agenda-dialog'); const form = el('form');
    const heading = el('h2', title); const header = el('header', undefined, 'agenda-dialog-header'); header.append(heading); heading.id = 'idea-title-' + crypto.randomUUID(); node.setAttribute('aria-labelledby', heading.id);
    const body = el('div', undefined, 'agenda-form-body'), error = el('p', '', 'idea-error'); error.setAttribute('role', 'alert');
    const footer = el('footer', undefined, 'agenda-dialog-footer'); footer.append(button('Close', () => { if (!body.inert) node.close(); })); header.append(button('×', () => { if (!body.inert) node.close(); })); header.lastChild.setAttribute('aria-label', 'Close editor'); form.append(header, body, error, footer); node.append(form); document.body.append(node);
    node.addEventListener('cancel', event => { if (body.inert) event.preventDefault(); });
    node.addEventListener('close', () => node.remove()); node.showModal();
    return {node, form, body, error, footer};
  }
  function field(root, name, title, value = '', type = 'text', required = false, max = 50000) {
    const label = el('label', title), input = el(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    input.name = name; input.value = value || ''; input.required = required; input.maxLength = max; label.append(input); root.append(label); return input;
  }
  function selectField(root, name, title, values, value) {
    const label = el('label', title), select = el('select'); select.name = name;
    for (const [key, text] of values) { const option = el('option', text); option.value = key; select.append(option); }
    select.value = value; label.append(select); root.append(label); return select;
  }
  function attachmentEditor(root, kind, identity) {
    const wrap = document.querySelector('#followup-form [data-input-editor]').cloneNode(true);
    wrap.dataset.csrf = token(); wrap.querySelector('[data-input-list]').replaceChildren();
    wrap.querySelectorAll('[id]').forEach(n => n.removeAttribute('id'));
    root.append(wrap);
    const editor = new HflInputAttachments(wrap, kind); editor.reset(identity); return editor;
  }
  function markdownEditor(input) {
    if (input.dataset.markdownReady) return;
    input.dataset.markdownReady = 'true';
    const preview = el('div', undefined, 'markdown-inline-preview markdown-body'); preview.hidden = true; preview.tabIndex = 0; preview.setAttribute('role', 'button'); preview.setAttribute('aria-label', 'Edit Markdown description'); input.after(preview);
    let revision = 0;
    const edit = () => { ++revision; preview.hidden = true; input.hidden = false; input.focus(); };
    preview.onclick = event => { if (!event.target.closest('a')) edit(); }; preview.onkeydown = event => { if (['Enter',' '].includes(event.key)) { event.preventDefault(); edit(); } };
    input.onblur = async () => { const ticket = ++revision; if (!input.value.trim()) return; try { const data = await api('/render', 'POST', {body: input.value}); if (ticket !== revision || document.activeElement === input) return; preview.innerHTML = data.html; input.hidden = true; preview.hidden = false; } catch { /* Keep the editable text available on failure. */ } };
    input.form?.addEventListener('reset', () => { ++revision; preview.hidden = true; input.hidden = false; });
  }
  document.querySelectorAll('#followup-form textarea[name=body]').forEach(markdownEditor);
  async function sourceFor(parent) {
    if (parent?.kind !== 'entries') return null;
    const preview = await request('/api/hfl/entities/entry/' + encodeURIComponent(parent.id.replace(/^entry:/, '')) + '?' + new URLSearchParams({locator: parent.locator || ''}));
    const params = new URL(preview.action_url, location.origin).searchParams;
    return request('/hfl-corpus/timeline/source?' + new URLSearchParams({path: params.get('source_path'), entry_id: params.get('source_entry')}));
  }
  async function openEditor(kind, item = {}, parent = null, conversion = null) {
    const d = dialog(conversion ? 'Create actionable from idea' : item.id ? 'Edit ' + kind : 'New ' + kind);
    let current = item.id ? item : null, source = item.source || null, files, checklists, save;
    const requestId = crypto.randomUUID();
    try {
      if (!source) source = await sourceFor(parent);
      if (!d.node.open) return;
      const section = (title) => { const box = el('section', undefined, 'object-form-section'); box.append(el('h3', title)); d.body.append(box); return box; };
      let checklistRoot, checklistToolbar;
      if (kind === 'actionable') {
        const template = document.querySelector('#followup-form .agenda-form-body').cloneNode(true);
        template.querySelectorAll('[id]').forEach(n => { const old = n.id; n.id = old + '-' + requestId; template.querySelectorAll('[aria-describedby]').forEach(ref => { ref.setAttribute('aria-describedby', ref.getAttribute('aria-describedby').split(' ').map(id => id === old ? n.id : id).join(' ')); }); });
        template.querySelector('[data-input-editor]')?.remove();
        template.querySelector('[data-action-checklists]').replaceChildren();
        template.querySelectorAll('.markdown-inline-preview').forEach(n => n.remove());
        template.querySelectorAll('textarea').forEach(n => { n.hidden = false; delete n.dataset.markdownReady; });
        template.querySelectorAll('input,textarea,select').forEach(n => { if (n.name) n.value = item[n.name] || (n.name === 'status' ? 'open' : ''); });
        template.querySelector('[name=body]').value = window.HflObjectDescription(item);
        template.querySelectorAll('details').forEach(n => { n.open = false; });
        template.querySelector('[name=status]').closest('label').hidden = !current;
        const completion = template.querySelector('[name=completion_note]').closest('label');
        const status = template.querySelector('[name=status]'); const updateStatus = () => { completion.hidden = status.value !== 'done'; }; status.onchange = updateStatus; updateStatus();
        template.querySelector('[name=matrix]').onchange = event => { if (!event.target.value) for (const name of ['matrix_confidence','matrix_reason']) template.querySelector(`[name=${name}]`).value = ''; };
        template.querySelector('.agenda-evidence')?.remove(); template.querySelector('.agenda-error')?.remove();
        d.body.append(...template.children); checklistRoot = d.body.querySelector('[data-action-checklists]');
        checklistToolbar = d.body.querySelector('[data-checklist-toolbar]');
      } else {
        const details = section('Details');
        field(details, 'title', 'Idea', item.title, 'text', true, 200);
        field(details, 'body', 'Markdown description', window.HflObjectDescription(item), 'textarea', false, 60000);
        const attachments = el('div'); attachments.dataset.objectAttachments = ''; details.append(attachments);
        if (current) selectField(details, 'status', 'Status', [['suggested', 'Available / restored'], ['adopted', 'Has actionables'], ['dismissed', 'Dismissed']], item.status);
        const checklistSection = section('Checklists');
        const checklistHeader = el('div', undefined, 'idea-checklists-heading');
        checklistToolbar = el('div');
        checklistHeader.append(checklistSection.querySelector('h3'), checklistToolbar);
        checklistRoot = el('div'); checklistSection.append(checklistHeader, checklistRoot);
      }
      let savedState;
      const formState = () => JSON.stringify({fields: Object.fromEntries(new FormData(d.form)), checklists: checklists?.value});
      const canConvert = () => !!current && savedState !== undefined && !files?.changed && formState() === savedState;
      checklists = new HflChecklists(checklistRoot, kind === 'idea' ? {
        links: item.item_actions || [], openAction, addButtonRoot: checklistToolbar,
        canConvert,
        convert: (listId, itemId) => { if (canConvert()) { d.node.close(); convert(current.id, listId, itemId); } },
      } : {addButtonRoot: checklistToolbar}); checklists.set(item.checklists);
      d.form.querySelectorAll('textarea[name=body]').forEach(markdownEditor);
      const attachmentsSection = d.body.querySelector('[data-object-attachments]');
      const copiedFiles = [];
      if (conversion) {
        attachmentsSection.append(el('p', 'Copy supporting files. Changes to this action will remain independent of the idea.'));
        for (const file of conversion.attachments) {
          const label = el('label'), check = el('input'); check.type = 'checkbox'; check.checked = true; copiedFiles.push({check, id: file.id}); label.append(check, document.createTextNode(' ' + file.name)); attachmentsSection.append(label);
        }
      }
      files = attachmentEditor(attachmentsSection, kind === 'idea' ? 'idea' : 'actionable', current?.id);
      savedState = formState(); checklists.updateConversion();
      for (const event of ['input', 'change', 'click']) d.form.addEventListener(event, () => queueMicrotask(() => checklists.updateConversion()));
      save = el('button', 'Save'); save.type = 'submit'; d.footer.append(save);
      d.form.onsubmit = async event => {
        event.preventDefault(); save.disabled = true; d.error.textContent = ''; d.body.inert = true;
        try {
          files.validate();
          const values = Object.fromEntries(new FormData(d.form)); values.checklists = checklists.value;
          values.description = '';
          const prompt = values.prompt, filesChanged = files.changed;
          if (kind === 'actionable' && filesChanged) values.prompt = '';
          if (current) values.version = current.version;
          if (kind === 'idea') {
            if (!current) { values.request_id = requestId; values.source = source; if (parent?.kind === 'daily') values.source_date = parent.id.slice(6); }
            current = (await api('/objects' + (current ? '/' + current.id : ''), current ? 'PATCH' : 'POST', values)).item;
          } else if (conversion && !current) {
            current = (await api('/objects/' + conversion.id + '/convert', 'POST', {request_id: requestId, idea_version: conversion.idea_version, checklist_id: conversion.checklist_id || '', item_id: conversion.item_id || '', item: values, attachments: copiedFiles.filter(f => f.check.checked).map(f => f.id)})).item;
          } else {
            if (!current) { values.request_id = requestId; values.source = source; values.agent_enabled = false; }
            current = (await request('/hfl-corpus/timeline/items' + (current ? '/' + current.id : ''), {method: current ? 'PATCH' : 'POST', body: JSON.stringify(values)})).item;
          }
          await files.save(current.id);
          if (kind === 'actionable' && filesChanged && prompt) {
            current = (await request('/hfl-corpus/timeline/items/' + current.id, {method: 'PATCH', body: JSON.stringify({version: current.version, prompt})})).item;
          }
          const nodeId = (kind === 'idea' ? 'idea:' : 'action:') + current.id;
          if (parent) await api('/links', 'POST', {source: parent.id, target: nodeId, relation: parent.kind === 'daily' ? 'source-date' : 'related-to'});
          await maps.addMembers([nodeId, ...(parent ? [parent.id] : [])]);
          d.node.close(); changed();
        } catch (error) { d.error.textContent = error.message + (current ? ' The object is saved; retry to finish remaining changes.' : ''); }
        finally { save.disabled = false; d.body.inert = false; }
      };
    } catch (error) { d.error.textContent = error.message; }
  }
  async function editIdea(id) { try { const data = await api('/objects/' + id); await openEditor('idea', data.item); } catch (error) { const d = dialog('Idea unavailable'); d.error.textContent = error.message; } }
  async function openAction(id) { try { const {item} = await request('/hfl-corpus/timeline/items/' + id); await openEditor('actionable', item); } catch (error) { const d = dialog('Action unavailable'); d.error.textContent = error.message; } }
  async function convert(id, checklistId = '', itemId = '') {
    const d = dialog('Preparing action draft');
    try { const data = await api('/objects/' + id + '/conversion?' + new URLSearchParams({checklist_id: checklistId, item_id: itemId})); d.node.close(); await openEditor('actionable', data.item, null, {...data, id}); }
    catch (error) { d.error.textContent = error.message; }
  }
  async function chooseMapMembers(parent = null) {
    const d = dialog(parent ? 'Expand connected branches' : 'Add existing objects to map');
    const search = field(d.body, '', 'Search', '', 'search'), list = el('div', undefined, 'idea-choices'); d.body.append(list);
    try {
      const graph = await request('/api/hfl/entities/graph?limit=0');
      const neighbors = new Set(graph.edges.filter(e => e.source === parent?.id || e.target === parent?.id).flatMap(e => [e.source, e.target]));
      const render = () => {
        list.replaceChildren();
        graph.nodes.filter(n => n.id !== parent?.id && (parent ? neighbors.has(n.id) : ['ideas', 'actions', 'topics'].includes(n.kind)) && n.label.toLowerCase().includes(search.value.toLowerCase())).slice(0, 100).forEach(n => {
          list.append(button(n.label + ' · ' + n.kind, async () => {
            try { await maps.addMembers([n.id, ...(parent ? [parent.id] : [])]); d.node.close(); changed(); }
            catch (error) { d.error.textContent = error.message; }
          }));
        });
        if (!list.children.length) list.append(el('p', 'No matching objects.'));
      }; search.oninput = render; render();
    } catch (error) { d.error.textContent = error.message; }
  }
  function newTopic(parent) {
    const d = dialog('New topic'); const name = field(d.body, 'label', 'Topic', '', 'text', true, 120);
    const save = el('button', 'Create topic'); save.type = 'submit'; d.footer.append(save);
    d.form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try { const {item} = await api('/topics', 'POST', {label: name.value}); if (parent) await api('/links', 'POST', {source: parent.id, target: item.id}); await maps.addMembers([item.id, ...(parent ? [parent.id] : [])]); d.node.close(); changed(); } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
  }
  function inspect(node, root, edges) {
    if (!node) return;
    if (node.status) root.append(el('p', 'Status: ' + node.status.replaceAll('_', ' '), 'idea-inspector-status'));
    if (node.kind === 'ideas') root.append(button('Edit idea / checklists', () => editIdea(node.object_id)), button('Make actionable', () => convert(node.object_id)));
    if (node.kind === 'actions') root.append(button('Edit actionable / status', async () => { try { const {item} = await request('/hfl-corpus/timeline/items/' + node.object_id); openEditor('actionable', item); } catch (error) { const d = dialog('Action unavailable'); d.error.textContent = error.message; } }));
    if (['entries', 'daily', 'topics', 'tools', 'ideas', 'actions'].includes(node.kind)) {
      const menu = el('div', undefined, 'idea-add-menu'), panel = el('div', undefined, 'idea-add-options');
      panel.id = 'idea-add-' + crypto.randomUUID(); panel.hidden = true; panel.setAttribute('role', 'menu'); panel.setAttribute('aria-label', 'Add object');
      const toggle = button('Add', () => setOpen(panel.hidden)); toggle.className = 'idea-add-toggle';
      toggle.setAttribute('aria-label', 'Add object'); toggle.setAttribute('aria-haspopup', 'menu'); toggle.setAttribute('aria-controls', panel.id); toggle.setAttribute('aria-expanded', 'false');
      const setOpen = open => { panel.hidden = !open; toggle.setAttribute('aria-expanded', String(open)); if (open) panel.firstElementChild.focus(); };
      for (const [value, label] of [['idea', 'Idea'], ['actionable', 'Actionable'], ['topic', 'Topic']]) {
        const option = button(label, () => { setOpen(false); toggle.focus(); if (value === 'topic') newTopic(node); else openEditor(value, {}, node); });
        option.setAttribute('role', 'menuitem'); option.tabIndex = -1; panel.append(option);
      }
      menu.append(toggle, panel); root.append(menu);
      menu.addEventListener('keydown', event => {
        const options = [...panel.children], index = options.indexOf(document.activeElement);
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setOpen(false); toggle.focus(); }
        else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
          event.preventDefault(); setOpen(true);
          const target = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : index < 0 ? (event.key === 'ArrowUp' ? options.length - 1 : 0) : (index + (event.key === 'ArrowUp' ? -1 : 1) + options.length) % options.length;
          options[target].focus();
        }
      });
      menu.addEventListener('focusout', event => { if (event.relatedTarget && !menu.contains(event.relatedTarget)) setOpen(false); });
    }
    if (maps.current) root.append(button('Expand branches', () => chooseMapMembers(node)), button('Remove from this map', () => maps.removeMember(node.id)));
    const links = edges.filter(e => e.manual && (e.source === node.id || e.target === node.id));
    if (links.length) root.append(button('Manage links', () => {
      const d = dialog('Connections');
      for (const link of links) { const row = el('p', (link.source === node.id ? link.target : link.source) + ' · ' + link.relation); row.append(button('Unlink', async () => { try { await api('/links', 'DELETE', {source: link.source, target: link.target, relation: link.relation}); row.remove(); changed(); } catch (error) { d.error.textContent = error.message; } })); d.body.append(row); }
    }));
  }
  const maps = {
    current: null, loaded: [], pendingPositions: null, getPositions: () => ({}),
    async init(root) {
      if (!root) return;
      this.root = root; this.select = el('select'); this.select.setAttribute('aria-label', 'Named mind map');
      this.status = el('span', '', 'idea-map-status'); this.status.setAttribute('role', 'status');
      root.append(this.select, button('New map', () => this.edit()), button('Rename / instructions', () => this.edit(this.current)), button('Save layout', () => this.saveLayout()), button('Add idea', () => openEditor('idea')), button('Add existing', () => chooseMapMembers()), button('Brainstorm with agent', () => this.brainstorm()), this.status);
      this.select.onchange = () => { this.current = this.loaded.find(m => m.id === this.select.value) || null; this.pendingPositions = this.current?.positions || {}; const url = new URL(location.href); if (this.current) url.searchParams.set('map', this.current.id); else url.searchParams.delete('map'); history.replaceState(null, '', url); changed(); };
      try { const data = await api('/snapshot'); this.loaded = data.maps; this.current = this.loaded.find(m => m.id === new URL(location.href).searchParams.get('map')) || null; this.pendingPositions = this.current?.positions || {}; this.render(); }
      catch (error) { this.status.textContent = error.message; }
    },
    render() { this.select?.replaceChildren(); const all = el('option', 'All ideas and activity'); all.value = ''; this.select?.append(all); for (const m of this.loaded) { const o = el('option', m.name); o.value = m.id; this.select?.append(o); } if (this.select) this.select.value = this.current?.id || ''; },
    async reload() { if (!this.root) return; const id = this.current?.id; const data = await api('/snapshot'); this.loaded = data.maps; this.current = this.loaded.find(m => m.id === id) || null; this.pendingPositions = this.current?.positions || {}; this.render(); },
    async persist(fields) {
      if (!this.current) return;
      const {item} = await api('/maps/' + this.current.id, 'PATCH', {...fields, version: this.current.version}); this.current = item; this.loaded = this.loaded.map(m => m.id === item.id ? item : m); this.render(); if (this.status) this.status.textContent = 'Map saved';
    },
    async addMembers(ids) { if (this.current) { await this.persist({members: [...new Set([...this.current.members, ...ids])], positions: {...this.current.positions, ...this.getPositions()}}); this.pendingPositions = this.current.positions; } },
    async removeMember(id) { try { const positions = {...this.current.positions}; delete positions[id]; await this.persist({members: this.current.members.filter(i => i !== id), positions}); changed(); } catch (error) { this.status.textContent = error.message; } },
    async saveLayout() { if (!this.current) { this.status.textContent = 'Create or select a named map first.'; return; } try { await this.persist({positions: {...this.current.positions, ...this.getPositions()}}); } catch (error) { this.status.textContent = error.message; } },
    edit(current = null) {
      const d = dialog(current ? 'Mind-map settings' : 'New mind map'); const name = field(d.body, 'name', 'Map name', current?.name, 'text', true, 100);
      const prompt = field(d.body, 'prompt', 'Brainstorming instructions', current?.prompt, 'textarea', false, 20000);
      const save = el('button', 'Save map'); save.type = 'submit'; d.footer.append(save); const key = crypto.randomUUID();
      d.form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try {
        const {item} = await api('/maps' + (current ? '/' + current.id : ''), current ? 'PATCH' : 'POST', {name: name.value, prompt: prompt.value, ...(current ? {version: current.version} : {request_id: key, members: [], positions: {}})});
        this.loaded = [...this.loaded.filter(m => m.id !== item.id), item]; this.current = item; this.pendingPositions = item.positions; this.render(); const url = new URL(location.href); url.searchParams.set('map', item.id); history.replaceState(null, '', url); d.node.close(); changed();
      } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
    },
    async brainstorm() {
      if (!this.current) { this.status.textContent = 'Create or select a named map first.'; return; }
      const map = this.current; const d = dialog('Agent brainstorming · ' + map.name);
      d.body.append(el('p', 'The agent proposes ideas and connections for your review. Accept individual suggestions to save them.'));
      const output = el('div'), status = el('p'); d.body.append(status, output); let timer, busy = false;
      const sourceUrl = '/hfl-corpus/agent-bridge/sources/mindmap/' + map.id;
      const refresh = async () => {
        if (!d.node.open || busy || d.node.querySelector('textarea:focus') || document.querySelectorAll('.idea-dialog[open]').length > 1) return; busy = true;
        try {
          const data = await request(sourceUrl); const run = data.runs[0]; output.replaceChildren();
          status.textContent = run ? 'Agent status: ' + run.state : 'No brainstorming run yet. Save instructions in map settings, then request suggestions.';
          if (run) {
            output.append(el('p', run.result.summary || 'Queued work will start when an agent worker is available.'));
            if (run.state === 'review') {
              const proposals = run.result.ideas || [];
              if (!proposals.length) output.append(el('p', 'No structured ideas were returned. Ask the agent to return proposals using the brainstorming schema.'));
              proposals.forEach((idea, index) => {
                const row = el('section', undefined, 'idea-proposal'); row.append(el('h3', idea.title), el('p', window.HflObjectDescription(idea)));
                row.append(button('Review / add idea', async () => {
                  const review = dialog('Review suggested idea'); const title = field(review.body, 'title', 'Title', idea.title, 'text', true, 200), body = field(review.body, 'body', 'Markdown description', window.HflObjectDescription(idea), 'textarea', false, 60000);
                  const accept = el('button', 'Add to map'); accept.type = 'submit'; review.footer.append(accept);
                  review.form.onsubmit = async event => { event.preventDefault(); accept.disabled = true; try { await request('/hfl-corpus/agent-bridge/mindmaps/' + map.id + '/accept-proposal', {method: 'POST', body: JSON.stringify({run_id: run.id, index, item: {title: title.value, description: '', body: body.value}})}); const latest = await api('/snapshot'); this.loaded = latest.maps; this.current = latest.maps.find(m => m.id === map.id); this.render(); review.node.close(); row.remove(); changed(); } catch (error) { review.error.textContent = error.message; } finally { accept.disabled = false; } };
                })); output.append(row);
              });
              output.append(button('Finish review', async () => { try { await request('/hfl-corpus/agent-bridge/runs/' + run.id + '/accept', {method: 'POST', body: '{}'}); await refresh(); } catch (error) { d.error.textContent = error.message; } }));
            }
            if (['awaiting_input', 'failed'].includes(run.state)) {
              const reply = field(output, '', 'Reply / retry instructions', '', 'textarea'); output.append(button('Continue', async () => { try { await request('/hfl-corpus/agent-bridge/runs/' + run.id + '/continue', {method: 'POST', body: JSON.stringify({reply: reply.value})}); await refresh(); } catch (error) { d.error.textContent = error.message; } }));
            }
            if (['queued','running','awaiting_input','review'].includes(run.state)) output.append(button('Cancel run', async () => { try { await request('/hfl-corpus/agent-bridge/runs/' + run.id + '/cancel', {method: 'POST', body: '{}'}); await refresh(); } catch (error) { d.error.textContent = error.message; } }));
          }
        } catch (error) { d.error.textContent = error.message; } finally { busy = false; }
      };
      const key = crypto.randomUUID(); d.footer.append(button('Request suggestions', async () => { try { await request(sourceUrl + '/run', {method: 'POST', body: JSON.stringify({request_key: key, auto_complete: false})}); await refresh(); } catch (error) { d.error.textContent = error.message; } }));
      await refresh(); timer = setInterval(refresh, 5000); d.node.addEventListener('close', () => clearInterval(timer));
    }
  };
  window.HflIdeas = {openAction, openEditor, editIdea, convert, inspect, maps, api};
  document.addEventListener('click', async event => {
    document.querySelectorAll('.idea-add-menu').forEach(menu => {
      if (!menu.contains(event.target)) { menu.querySelector('.idea-add-options').hidden = true; menu.querySelector('.idea-add-toggle').setAttribute('aria-expanded', 'false'); }
    });
    const day = event.target.closest('[data-document-idea-date]');
    if (day) { openEditor('idea', {}, {id: 'daily:' + day.dataset.documentIdeaDate, kind: 'daily'}); return; }
    const target = event.target.closest('[data-create-idea-source]'); if (!target) return;
    event.preventDefault(); try { const params = new URL(target.href, location.origin).searchParams; const source = await request('/hfl-corpus/timeline/source?' + new URLSearchParams({path: params.get('source_path'), entry_id: params.get('source_entry')})); openEditor('idea', {source, title: source.title}, {id: 'daily:' + source.date, kind: 'daily'}); } catch (error) { const d = dialog('Idea unavailable'); d.error.textContent = error.message; }
  });
  window.addEventListener('hfl:create-idea', event => openEditor('idea', {}, event.detail?.date ? {id: 'daily:' + event.detail.date, kind: 'daily'} : null));
})();
