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
    const response = await fetch(url, {...options, signal:options.signal || AbortSignal.timeout(45000), headers: {'Content-Type': 'application/json', 'X-CSRF-Token': token(), ...options.headers}});
    let data; try { data = await response.json(); } catch { throw Error('The service could not respond. Retry shortly.'); }
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Could not save. Check the fields and retry.');
    return data;
  }
  const api = (path, method = 'GET', data) => request(base + path, {method, ...(data === undefined ? {} : {body: JSON.stringify(data)})});
  const button = (text, action) => { const b = el('button', text); b.type = 'button'; b.onclick = action; return b; };
  const changed = (selectId = null, boardSwitch = false, refreshShared = false) => { window.dispatchEvent(new CustomEvent('hfl:ideas-updated', {detail:{selectId,boardSwitch,refreshShared,boardLocal:!!maps.current}})); if(!maps.current)window.dispatchEvent(new Event('hfl:actions-updated')); };
  function dialog(title) {
    const node = el('dialog', undefined, 'idea-dialog agenda-dialog'); const form = el('form');
    const heading = el('h2', title); const header = el('header', undefined, 'agenda-dialog-header'); header.append(heading); heading.id = 'idea-title-' + crypto.randomUUID(); node.setAttribute('aria-labelledby', heading.id);
    const body = el('div', undefined, 'agenda-form-body'), error = el('p', '', 'idea-error'); error.setAttribute('role', 'alert');
    const footer = el('footer', undefined, 'agenda-dialog-footer'); footer.append(button('Close', () => { if (!body.inert) node.close(); })); header.append(button('×', () => { if (!body.inert) node.close(); })); header.lastChild.setAttribute('aria-label', 'Close editor'); form.append(header, body, error, footer); node.append(form); document.body.append(node);
    node.addEventListener('cancel', event => { if (body.inert) event.preventDefault(); });
    node.addEventListener('close', () => node.remove()); node.showModal();
    return {node, form, body, error, footer};
  }
  function openBoardGuide() {
    const d = dialog('Board guide');
    d.node.classList.add('board-guide');
    d.node.querySelector('.agenda-dialog-header button').setAttribute('aria-label', 'Close board guide');
    d.body.innerHTML = `
      <p class="board-guide-intro">A place to connect what you know, explore possibilities, and decide what to do next.</p>
      <section aria-labelledby="board-guide-basics">
        <h3 id="board-guide-basics">Your workspace and your outcome</h3>
        <dl class="board-guide-definitions">
          <div><dt>Board</dt><dd>A saved workspace around a question or project. It holds thoughts, attached objects, connections, and their layout. Attaching an existing object reuses it across boards.</dd></div>
          <div><dt>Goal</dt><dd>The outcome you want, with success criteria, status, a target date, and milestones. Associate a board with a goal in Settings; link supporting ideas and actions in the goal editor.</dd></div>
        </dl>
      </section>
      <section aria-labelledby="board-guide-flow">
        <h3 id="board-guide-flow">From a spark to a next step</h3>
        <ol class="board-guide-flow">
          <li><strong>Thought</strong><span>A rough note on this board.</span><small>Promote to shared Idea</small></li>
          <li><strong>Idea</strong><span>A reusable possibility to develop, with notes and checklists.</span><small>Make actionable</small></li>
          <li><strong>Actionable</strong><span>A concrete task with instructions, files, and progress to track.</span><small>Run separately when ready</small></li>
        </ol>
        <p>Promotion replaces the thought with a shared idea and keeps its board connections. Conversion creates an independent actionable linked to the idea as <strong>develops into</strong>. Saving instructions does not run an agent.</p>
      </section>
      <section aria-labelledby="board-guide-connections">
        <h3 id="board-guide-connections">Build the connections</h3>
        <ul class="board-guide-list">
          <li><strong>Bring in context.</strong> Use Attach existing for entries, ideas, actions, goals, or entities such as people, topics, and tools. Each orb is a node; attaching it alone does not connect it to every other node.</li>
          <li><strong>Link what belongs together.</strong> Select an orb and choose Connect on this board from its action panel. These connections stay on the board. Use Board connections to promote a connection between shared objects into the Activity Graph.</li>
          <li><strong>Arrange your thinking.</strong> Drag an orb to place it independently; its connections stay attached. Titles wrap in full. Hover over or select an orb for +/− controls, with twenty saved size levels to express how concrete it feels. Selecting an orb opens its action panel for editing, promotion, and more.</li>
          <li><strong>Explore with an agent.</strong> Ask agent proposes ideas and connections. Review and accept suggestions to save them.</li>
          <li><strong>Review the outcome.</strong> Track milestones in the goal editor. Completed actions do not automatically achieve a goal; assess its success criteria and update its status.</li>
        </ul>
      </section>
      <section aria-labelledby="board-guide-destinations">
        <h3 id="board-guide-destinations">Where your work goes</h3>
        <dl class="board-guide-routes">
          <div><dt>This board</dt><dd>Thoughts, layout, membership, and board-only connections stay here. Edits autosave; Save now flushes pending changes.</dd></div>
          <div><dt>Activity Graph</dt><dd>Shared ideas, actionables, goals, and shared connections are available beyond this board. Actionables also appear in your action list.</dd></div>
          <div><dt>HFL history</dt><dd>Creating or changing thoughts and goals queues an HFL memory entry with a link back. It appears after background delivery; moving nodes does not create an entry.</dd></div>
        </dl>
      </section>`;
  }
  function field(root, name, title, value = '', type = 'text', required = false, max = 50000) {
    const label = el('label', title), input = el(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    input.name = name; input.value = value || ''; input.required = required; input.maxLength = max; label.append(input); root.append(label); return input;
  }
  function selectField(root, name, title, values, value) {
    const label = el('label', title), select = el('select'); select.name = name; select.setAttribute('aria-label', title);
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
    const requestId = crypto.randomUUID(), editingBoard = maps.current?.id;
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
        attachmentsSection.append(el('p', 'Copy supporting files. Changes to this action will remain independent of the idea.', 'idea-copy-files-note'));
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
          maps.cacheNode({...current,id:nodeId,object_id:current.id,label:current.title,kind:kind === 'idea' ? 'ideas' : 'actions'});
          if(parent?.kind==='drafts') {
            if(maps.current?.id!==editingBoard)throw Error('Return to the original board to finish linking this saved object.');
            await maps.persist({members:[...new Set([...maps.current.members,nodeId])],edges:[...maps.current.edges.filter(e=>!(e.source===parent.id&&e.target===nodeId)),{source:parent.id,target:nodeId,relation:'related-to'}]});
          } else {
            if(parent)await api('/links','POST',{source:parent.id,target:nodeId,relation:parent.kind==='daily'?'source-date':'related-to'});
            await maps.addMembers([nodeId,...(parent?[parent.id]:[])]);
          }
          // Conversion also creates shared relationships and updates the source idea.
          if (conversion) await maps.flush();
          d.node.close(); changed(null, false, !!conversion);
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
  async function chooseMapMembers() {
    const boardId = maps.current?.id; if (!boardId) return;
    const d = dialog('Attach existing context');
    d.node.classList.add('idea-attach-dialog');
    const search = field(d.body, '', 'Search', '', 'search'), list = el('div', undefined, 'idea-choices');
    const status = el('div', '', 'idea-picker-status'), pages = el('div', undefined, 'idea-picker-pages');
    status.setAttribute('role', 'status'); d.body.append(status, list, pages);
    d.form.onsubmit = event => event.preventDefault();
    let offset = 0, timer, controller, generation = 0;
    const cancel = () => { generation++; controller?.abort(); clearTimeout(timer); };
    d.node.addEventListener('close', cancel);
    const loading = () => {
      list.replaceChildren(); pages.replaceChildren(); d.error.textContent = '';
      status.textContent = 'Loading items…';
      const progress = el('div', undefined, 'idea-picker-loading');progress.append(el('span', '', 'idea-picker-spinner'),el('span', 'Loading context…'));progress.setAttribute('aria-hidden','true');list.append(progress);
      list.setAttribute('aria-busy', 'true');
    };
    async function load() {
      cancel(); const current = generation; controller = new AbortController(); loading();
      try {
        const data = await request(base + '/maps/' + boardId + '/attach-options?' + new URLSearchParams({query:search.value.trim(),offset}),
          {signal:AbortSignal.any([controller.signal, AbortSignal.timeout(45000)])});
        if (current !== generation || !d.node.open) return;
        list.replaceChildren();list.scrollTop=0;
        status.textContent = data.total ? 'Most recently updated · ' + (offset + 1) + '–' + Math.min(offset + 50, data.total) + ' of ' + data.total : '';
        data.nodes.filter(n => !maps.current?.members.includes(n.id)).forEach(n => {
          const kind = window.HflGraphAppearance?.kindLabel(n.kind) || n.kind.replaceAll('_', ' ');
          const choice = button('', async () => {
            try {
              if (maps.current?.id !== boardId) throw Error('Return to this board before attaching.');
              maps.cacheNode(n); await maps.addMembers([n.id]); d.node.close(); changed();
            } catch (error) { d.error.textContent = error.message; }
          });
          choice.className='idea-attach-choice';choice.title=n.label;choice.setAttribute('aria-label',n.label+' · '+kind);
          const label=el('span',n.label,'idea-attach-title'),entity=el('span',kind,'idea-attach-entity'),dot=el('span',undefined,'idea-attach-dot');
          dot.style.background=window.HflGraphAppearance?.color(n.kind)||'#e9c96c';dot.setAttribute('aria-hidden','true');entity.append(dot);choice.append(label,entity);list.append(choice);
        });
        if (!list.children.length) list.append(el('p', 'No matching objects available to attach.'));
        if (offset) pages.append(button('Previous', () => { offset = Math.max(0, offset - 50); load(); }));
        if (data.has_more) pages.append(button('Next', () => { offset += 50; load(); }));
      } catch (error) {
        if (current !== generation || !d.node.open) return;
        list.replaceChildren();
        status.textContent = ''; d.error.textContent = error.name === 'TimeoutError' ? 'Loading took too long. Please retry.' : error.message;
        pages.append(button('Retry', load));
      } finally { if (current === generation) list.setAttribute('aria-busy', 'false'); }
    }
    search.oninput = () => { cancel(); offset = 0; loading(); timer = setTimeout(load, 250); };
    await load();
  }
  function newTopic(parent) {
    const d = dialog('New topic'); const name = field(d.body, 'label', 'Topic', '', 'text', true, 120);
    const save = el('button', 'Create topic'); save.type = 'submit'; d.footer.append(save);
    d.form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try { const {item} = await api('/topics', 'POST', {label: name.value}); if (parent) await api('/links', 'POST', {source: parent.id, target: item.id}); await maps.addMembers([item.id, ...(parent ? [parent.id] : [])]); d.node.close(); changed(); } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
  }
  function editThought(identity = null, parent = null) {
    const board = maps.current; if (!board) return;
    const existing = board.drafts.find(d => d.id === identity);
    const d = dialog(existing ? 'Edit thought' : 'Add thought');
    const title = field(d.body, 'title', 'Thought', existing?.title, 'text', true, 200);
    const body = field(d.body, 'body', 'Description', existing?.body, 'textarea', false, 60000);
    const id = identity || 'draft:' + crypto.randomUUID();
    const save = el('button', 'Save thought'); save.type = 'submit'; d.footer.append(save);
    d.form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try {
      if(maps.current?.id!==board.id)throw Error('Return to this board before saving.');
      const live=maps.current;
      if(existing&&JSON.stringify(live.drafts.find(t=>t.id===id))!==JSON.stringify(existing))throw Error('This thought changed. Reopen it before saving.');
      const edge = parent || live.root;
      await maps.persist({drafts: [...live.drafts.filter(t => t.id !== id), {id, title: title.value, body: body.value}], edges: [...live.edges, ...(!existing && edge && edge !== id ? [{source: edge, target: id, relation: 'related-to'}] : [])], root: live.root || id}); d.node.close(); changed();
    } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
  }
  async function connectThought(node) {
    const board = maps.current, d = dialog('Connect on this board');
    try {
      const choices = [...board.members.map(id=>({id,label:maps.nodes.get(id)?.label||id})), ...board.drafts.map(t => ({id: t.id, label: t.title}))].filter(n => n.id !== node.id);
      const target = selectField(d.body, 'target', 'Connect to', choices.map(n => [n.id, n.label]), choices[0]?.id || '');
      const relation = selectField(d.body, 'relation', 'Relationship', [['related-to','Related to'],['supports','Supports'],['alternative','Alternative'],['depends-on','Depends on']], 'related-to');
      d.body.append(el('p', 'This connection stays on this board.'));
      const save = el('button', 'Save connection'); save.type = 'submit'; save.disabled = !choices.length; d.footer.append(save);
      d.form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try {
        if(maps.current?.id!==board.id)throw Error('Return to this board before saving.');
        const edge = {source: node.id, target: target.value, relation: relation.value};
        await maps.persist({edges: [...maps.current.edges.filter(e => !(e.source === edge.source && e.target === edge.target && e.relation === edge.relation)), edge]}); d.node.close(); changed();
      } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
    } catch (error) { d.error.textContent = error.message; }
  }
  function colorField(parent,label,initial,hideLabel=false){
    let selected=initial||maps.palette[0]||'#f59e0b';
    const palette=el('fieldset',undefined,'board-palette');const legend=el('legend',label);if(hideLabel)legend.className='goal-visually-hidden';palette.append(legend);
    for(const value of maps.palette){const swatch=button('',()=>{selected=value;for(const option of palette.querySelectorAll('button'))option.setAttribute('aria-pressed',String(option.dataset.color===selected));});swatch.dataset.color=value;swatch.style.background=value;swatch.setAttribute('aria-label','Color '+value);swatch.setAttribute('aria-pressed',String(value===selected));palette.append(swatch);}
    parent.append(palette);return ()=>selected;
  }
  const statusLabel = value => value.charAt(0).toUpperCase() + value.slice(1);
  function linkPicker(parent, title) {
    const root = el('details', undefined, 'goal-link-picker'), summary = el('summary');
    const heading = el('span', title), count = el('span', '0 selected', 'goal-link-count'); summary.append(heading, count);
    const panel = el('div', undefined, 'goal-link-panel');
    const search = field(panel, '', 'Search', '', 'search');
    const list = el('div', undefined, 'goal-link-options'); panel.append(list); root.append(summary, panel); parent.append(root);
    let selected = new Set(), options = [], disabled = true;
    const updateCount = () => { count.textContent = selected.size + ' selected'; };
    const render = () => {
      list.replaceChildren();
      const matches = options.filter(n => (n.label + ' ' + n.kind).toLowerCase().includes(search.value.toLowerCase().trim()));
      for (const n of matches) {
        const label = el('label', undefined, 'goal-link-option'), check = el('input'); check.type = 'checkbox'; check.checked = selected.has(n.id); check.disabled = disabled;
        const text = el('span', n.label, 'goal-link-title'), type = el('small', n.kind === 'ideas' ? 'idea' : n.kind === 'actions' ? 'action' : 'existing link', 'goal-link-type');
        const dot=el('span',undefined,'idea-attach-dot');dot.style.background=window.HflGraphAppearance?.color(n.kind)||(n.kind==='ideas'?'#f9ca74':n.kind==='actions'?'#fb8ca6':'#94a3b8');dot.setAttribute('aria-hidden','true');type.append(dot);
        type.dataset.kind=n.kind;label.title=n.label;label.append(check, text, type); list.append(label);
        check.onchange = () => { if(check.checked)selected.add(n.id);else selected.delete(n.id);updateCount(); };
      }
      if (!matches.length) list.append(el('p', disabled ? 'Loading available links…' : options.length ? 'No matching items.' : 'No saved items available to link.', 'board-hint'));
    };
    search.oninput = render;
    root.addEventListener('keydown', event => { if(event.key === 'Escape'){event.preventDefault();event.stopPropagation();root.open=false;summary.focus();} });
    return {
      get selectedOptions(){return [...selected].map(value => ({value}));},
      get disabled(){return disabled;},
      set disabled(value){disabled=value;render();},
      setOptions(nodes, ids){options=nodes;selected=new Set(ids);updateCount();render();}
    };
  }
  async function editGoal(identity = null) {
    const d = dialog(identity ? 'Edit Goal' : 'Add Goal');
    const loading = el('p', identity ? 'Loading Goal…' : '', 'board-hint'); loading.setAttribute('role', 'status'); d.body.append(loading);
    try {
      let item = identity ? (await api('/goals/' + identity)).item : {};
      if (!d.node.open) return;
      loading.remove();
      const graph = {nodes: []};
      const choices = (select, kinds, selected) => {
        const available = graph.nodes.filter(n => kinds.includes(n.kind));
        const known = new Set(available.map(n => n.id));
        select.setOptions([...available, ...selected.filter(id => !known.has(id)).map(id => ({id, kind:'existing', label: 'Existing link (details unavailable)'}))], selected);
      };
      const title = field(d.body, 'title', 'Goal', item.title, 'text', true, 200);
      const body = field(d.body, 'body', 'Description', item.body, 'textarea', false, 60000);
      const criteria = field(d.body, 'criteria', 'Success criteria', item.success_criteria, 'textarea', false, 6000);
      const metadata = el('div', undefined, 'goal-form-row'); d.body.append(metadata);
      const status = selectField(metadata, 'status', 'Status', ['proposed','active','paused','achieved','dropped'].map(s => [s,statusLabel(s)]), item.status || 'proposed');
      const date = field(metadata, 'target_date', 'Target date', item.target_date, 'date');
      const getColor=colorField(d.body,'Goal color',item.color||maps.palette[maps.goals.length%maps.palette.length],true);
      const notes = field(d.body, 'progress_notes', 'Progress notes', item.progress_notes, 'textarea', false, 20000);
      d.body.append(el('p', 'Link saved Ideas that support this outcome and Actions that help achieve it. Available items are shared across boards; search by title or type and select any number.', 'board-hint'));
      const links = linkPicker(d.body, 'Supporting Ideas and Actions');
      choices(links, ['ideas','actions'], item.linked_objects || []); links.disabled = true;
      const linkStatus = el('p', 'Loading optional Idea and Action links…', 'board-hint'); linkStatus.setAttribute('role', 'status'); d.body.append(linkStatus);
      const milestones = el('section', undefined, 'goal-milestones'); milestones.append(el('h3', 'Milestones')); d.body.append(milestones);
      const rows = [];
      const add = (m = {}) => {
        const section = el('section', undefined, 'goal-milestone'); const row = {id: m.id || crypto.randomUUID(), section};
        row.title = field(section, '', 'Milestone', m.title, 'text', true, 300);
        const metadata = el('div', undefined, 'goal-form-row'); section.append(metadata);
        row.status = selectField(metadata, '', 'Milestone status', ['planned','active','achieved','dropped'].map(s => [s,statusLabel(s)]), m.status || 'planned');
        row.date = field(metadata, '', 'Milestone target date', m.target_date, 'date');
        row.actions = linkPicker(section, 'Linked Actions');
        choices(row.actions, ['actions'], m.actions || []); row.actions.disabled = links.disabled;
        section.append(button('Remove milestone', () => { rows.splice(rows.indexOf(row), 1); section.remove(); })); rows.push(row); milestones.append(section);
      };
      for (const milestone of item.milestones || []) add(milestone);
      const milestoneToolbar = el('div', undefined, 'goal-milestone-toolbar');milestoneToolbar.append(button('Add milestone', () => add()));
      d.body.append(milestoneToolbar, el('p', 'Completing Actions does not automatically achieve this Goal. Assess the success criteria when updating its status.', 'board-hint'));
      const save = el('button', 'Save Goal'); save.type = 'submit'; d.footer.append(save); const key = crypto.randomUUID();
      d.form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try {
        const values = {title: title.value, color:getColor(), body: body.value, success_criteria: criteria.value, status: status.value, target_date: date.value, progress_notes: notes.value, milestones: rows.map(r => ({id:r.id,title:r.title.value,status:r.status.value,target_date:r.date.value,actions:[...r.actions.selectedOptions].map(o=>o.value)})), ...(item.id ? {version:item.version} : {request_id:key})};
        values.linked_objects = [...links.selectedOptions].map(o => o.value);
        item = (await api('/goals' + (item.id ? '/' + item.id : ''), item.id ? 'PATCH' : 'POST', values)).item;
        maps.goals=maps.goals.some(g=>g.id===item.id)?maps.goals.map(g=>g.id===item.id?item:g):[...maps.goals,item];maps.goalsOpen=true;maps.render();maps.cacheNode({...item,id:'goal:'+item.id,object_id:item.id,label:item.title,kind:'goals'});
        if (maps.current && !identity) await maps.addMembers(['goal:' + item.id]); d.node.close(); changed();
      } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
      let controller;
      const loadLinks = async () => {
        controller?.abort(); controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 45000);
        linkStatus.replaceChildren(document.createTextNode('Loading optional Idea and Action links…'));
        try {
          const data = await request(base+'/goal-options', {signal:controller.signal});
          if (!d.node.open) return;
          graph.nodes = data.nodes;
          choices(links, ['ideas','actions'], [...links.selectedOptions].map(o => o.value)); links.disabled = false;
          for (const row of rows) { choices(row.actions, ['actions'], [...row.actions.selectedOptions].map(o => o.value)); row.actions.disabled = false; }
          linkStatus.textContent = graph.nodes.filter(n => ['ideas','actions'].includes(n.kind)).length + ' saved Ideas and Actions available. Only items you can access are listed.';
        } catch (error) {
          if (d.node.open) linkStatus.replaceChildren(document.createTextNode('Optional links could not load. You can still save this Goal. Existing links are preserved. '), button('Retry loading links', loadLinks));
        } finally { clearTimeout(timeout); }
      };
      d.node.addEventListener('close', () => controller?.abort(), {once:true});
      loadLinks();
    } catch (error) { d.error.textContent = error.message; }
  }
  function inspect(node, root, edges) {
    if (!node) return;
    if(['drafts','goals'].includes(node.kind)){
      const key=node.kind==='drafts'?maps.current.id+'/'+node.id:node.id;
      const memory=el('a','View memory history','idea-inspector-status');
      memory.href='/hfl-corpus?'+new URLSearchParams({q:key});memory.target='_blank';memory.rel='noopener';root.append(memory);
    }
    if (node.kind === 'drafts') {
      root.append(el('p', 'This thought belongs to this board. Saved content changes are recorded in HFL memory.'), button('Edit thought', () => editThought(node.id)), button('Promote to shared Idea', async () => {
        try { await maps.flush(); const result = await api('/maps/' + maps.current.id + '/promote', 'POST', {draft_id: node.id, version: maps.current.version}); await maps.reload(); const {item}=await api('/objects/'+result.idea_id); maps.cacheNode({...item,id:'idea:'+item.id,object_id:item.id,label:item.title,kind:'ideas'}); changed('idea:' + result.idea_id); }
        catch (error) { maps.status.textContent = error.message; }
      }));
    }
    if(node.kind==='drafts')root.append(button('Create linked Idea',()=>openEditor('idea',{title:node.label,body:node.body},node)),button('Create linked Actionable',()=>openEditor('actionable',{title:node.label,body:node.body},node)));
    if(node.kind==='boards')root.append(button('Open board',async()=>{try{await maps.selectBoard((await api('/maps/'+node.object_id)).item);}catch(error){maps.status.textContent=error.message;}}));
    if (node.kind === 'goals') root.append(el('p', node.success_criteria || 'Add success criteria to define achievement.'), button('Edit Goal / milestones', () => editGoal(node.object_id)));
    if (maps.current) root.append(button('Add thought', () => editThought(null, node.id)), button('Connect on this board', () => connectThought(node)), button('Use as starting point', async () => { try { await maps.persist({root: node.id}); changed(); } catch (error) { maps.status.textContent = error.message; } }));
    else root.append(button('Start board from this', () => maps.edit(null, node)));
    if (node.status) {
      const status = String(node.status).toLowerCase().replaceAll('_', ' ').replaceAll('-', ' ');
      const row = el('p', undefined, 'idea-inspector-status idea-inspector-status-row');
      const pill = el('span', status.replace(/\b\w/g, letter => letter.toUpperCase()), 'idea-status-pill');
      pill.dataset.status = status.replaceAll(' ', '-');
      row.append(el('span', 'Status'), pill);root.append(row);
    }
    if (node.kind === 'ideas') root.append(button('Edit idea / checklists', () => editIdea(node.object_id)), button('Make actionable', () => convert(node.object_id)));
    if (node.kind === 'actions') root.append(button('Edit actionable / status', async () => { try { const {item} = await request('/hfl-corpus/timeline/items/' + node.object_id); openEditor('actionable', item); } catch (error) { const d = dialog('Action unavailable'); d.error.textContent = error.message; } }));
    if (!maps.current && ['entries', 'daily', 'topics', 'tools', 'ideas', 'actions', 'goals'].includes(node.kind)) {
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
    if (maps.current) root.append(button('Remove from board', () => maps.removeMember(node.id)));
    const local = edges.filter(e => e.local && (e.source === node.id || e.target === node.id));
    if (local.length) root.append(button('Board connections', () => {
      const d = dialog('Board connections');
      for (const edge of local) { const row = el('p', edge.relation + ' · ' + (maps.nodeLabels?.[edge.source === node.id ? edge.target : edge.source] || (edge.source === node.id ? edge.target : edge.source))); row.append(button('Remove connection', async () => { try { await maps.persist({edges: maps.current.edges.filter(e => !(e.source === edge.source && e.target === edge.target && e.relation === edge.relation))}); row.remove(); changed(); } catch (error) { d.error.textContent = error.message; } })); if (!edge.source.startsWith('draft:') && !edge.target.startsWith('draft:')) row.append(button('Promote shared connection', async () => { try { await maps.flush(); await api('/maps/' + maps.current.id + '/promote-link', 'POST', {version:maps.current.version,edge:{source:edge.source,target:edge.target,relation:edge.relation}}); maps.sharedEdges.set(JSON.stringify([edge.source,edge.target,edge.relation]),{source:edge.source,target:edge.target,relation:edge.relation,manual:true}); await maps.reload(); row.remove(); changed(); } catch (error) { d.error.textContent = error.message; } })); d.body.append(row); }
    }));
    const links = edges.filter(e => e.manual && (e.source === node.id || e.target === node.id));
    if (links.length) root.append(button('Manage links', () => {
      const d = dialog('Connections');
      for (const link of links) { const row = el('p', (link.source === node.id ? link.target : link.source) + ' · ' + link.relation); row.append(button('Unlink', async () => { try { await api('/links', 'DELETE', {source: link.source, target: link.target, relation: link.relation});maps.sharedEdges.delete(JSON.stringify([link.source,link.target,link.relation])); row.remove(); changed(); } catch (error) { d.error.textContent = error.message; } })); d.body.append(row); }
    }));
  }
  const maps = {
    current: null, loaded: [], pendingPositions: null, getPositions: () => ({}),
    queues:new Map(),nodes:new Map(),sharedEdges:new Map(),goals:[],palette:[],listOpen:true,goalsOpen:false,ordering:false,
    cacheNode(node){this.nodes.set(node.id,node);},
    queue(board=this.current){
      if(!board)return null;
      if(!this.queues.has(board.id))this.queues.set(board.id,new HflBoardSaveQueue(board,
        async fields=>(await api('/maps/'+board.id,'PATCH',fields)).item,
        async ()=>(await api('/maps/'+board.id)).item,
        (item,status)=>{this.loaded=this.loaded.map(b=>b.id===item.id?item:b);if(this.current?.id===item.id){this.current=item;this.render();this.status.textContent=status;}}));
      return this.queues.get(board.id);
    },
    async flush(){return this.queue()?.flush();},
    async saveNow(){try{await this.flush();}catch(error){this.status.textContent=error.message+' · Unsaved edits retained.';}},
    resolveSave(){
      const q=this.queue(),d=dialog('Resolve unsaved changes');
      d.body.append(el('p','Your unsaved changes are retained below. Copy them before choosing to discard them and reload the saved board.'));
      const backup=field(d.body,'backup','Unsaved changes',JSON.stringify(q.pending,null,2),'textarea');backup.readOnly=true;
      d.footer.append(button('Discard pending changes and reload',async()=>{try{
        const {item}=await api('/maps/'+q.value.id);clearTimeout(q.timer);this.queues.delete(item.id);this.current=item;this.loaded=this.loaded.map(b=>b.id===item.id?item:b);this.pendingPositions=item.positions;this.render();d.node.close();changed(null,true);
      }catch(error){d.error.textContent=error.message;}}));
    },
    async init(root) {
      if (!root) return;
      this.root = root;
      this.status = el('p', '', 'idea-map-status'); this.status.setAttribute('role', 'status');
      try { const data = await api('/boards'); this.goals=data.goals; this.palette=data.palette; this.loaded = data.maps; const params = new URL(location.href).searchParams; this.current = this.loaded.find(m => m.id === (params.get('board') || params.get('map'))) || null; this.pendingPositions = this.current?.positions || {}; this.render(); }
      catch (error) { root.append(this.status); this.status.textContent = error.message; }
    },
    async selectBoard(board) {
      if(this.current&&this.current.id!==board?.id){try{await this.flush();}catch(error){this.status.textContent=error.message+' · Save this board before switching.';return;}}
      board=board?(this.queues.get(board.id)?.value||board):null;
      const search = document.getElementById('kg-search');
      if (!this.current && board) this.activityQuery = search.value;
      search.value = board ? '' : (this.activityQuery || '');
      this.current = board; this.pendingPositions = board?.positions || {};
      const url = new URL(location.href); url.searchParams.delete('map');
      if (board) url.searchParams.set('board', board.id); else url.searchParams.delete('board');
      history.replaceState(null, '', url); this.render(); changed(null, true);
    },
    render() {
      if (!this.root) return;
      const caption=document.getElementById('kg-map-title');if(caption)caption.textContent=this.current?.name||'EXPLORE ACTIVITY CONSTELLATION';
      this.root.replaceChildren(); document.querySelector('.kg-shell')?.classList.toggle('has-board', !!this.current); document.getElementById('kg-search').placeholder = this.current ? 'Search this board' : 'Search entries or entities';
      const toolbar=el('div',undefined,'board-toolbar');toolbar.setAttribute('role','group');toolbar.setAttribute('aria-label','Board navigation and tools');this.root.append(toolbar);
      const all = button('Explore Activity Graph', () => this.selectBoard(null)); all.className='board-explore';all.setAttribute('aria-pressed', String(!this.current)); toolbar.append(all);
      const addMenu=el('div',undefined,'idea-add-menu board-add-menu'),addOptions=el('div',undefined,'idea-add-options');addOptions.hidden=true;addOptions.id='board-add-options';
      const addToggle=button('Add',()=>{addOptions.hidden=!addOptions.hidden;addToggle.setAttribute('aria-expanded',String(!addOptions.hidden));});addToggle.className='idea-add-toggle';addToggle.setAttribute('aria-expanded','false');addToggle.setAttribute('aria-controls',addOptions.id);
      const closeAdd=()=>{addOptions.hidden=true;addToggle.setAttribute('aria-expanded','false');};
      addOptions.append(button('Board',()=>{closeAdd();this.edit();}),button('Goal',()=>{closeAdd();editGoal();}));addMenu.append(addToggle,addOptions);addMenu.onkeydown=event=>{if(event.key==='Escape'){closeAdd();addToggle.focus();}};toolbar.append(addMenu);
      const guide=button('Board guide',openBoardGuide);guide.className='board-guide-trigger';guide.setAttribute('aria-haspopup','dialog');toolbar.append(guide);
      this.root.append(this.objectList('boards'),this.objectList('goals'));
      if (!this.current) { this.root.append(this.status); return; }
      const board = this.current, section = el('section', undefined, 'board-controls');section.style.setProperty('--board-color',board.color||this.palette[0]||'#f59e0b'); section.append(el('h2', board.name), el('p', board.purpose, 'board-purpose'));
      const save=button('Save now',()=>this.saveNow());save.className='board-save-now';save.title='Save all pending board edits now';
      const layout=button('Save layout',()=>this.saveLayout());layout.title='Capture current node positions for autosave';
      const remove=button('Delete',()=>this.remove());remove.className='board-delete';
      const ask=button('Ask agent',()=>this.brainstorm());ask.className='board-ask-agent';
      section.append(this.status,button('Add thought', () => editThought()), button('Attach existing', () => chooseMapMembers()),ask,save,layout,button('Settings', () => this.edit(board)),remove);
      const pending=this.queues.get(board.id);
      if(pending?.error)section.append(button('Retry save',()=>this.saveNow()),button('Resolve unsaved changes',()=>this.resolveSave()));
      this.root.append(section);
    },
    objectList(kind){
      const goals=kind==='goals',items=goals?this.goals:this.loaded,openKey=goals?'goalsOpen':'listOpen';
      const details=el('details'),summary=el('summary',goals?'Goals':'Boards');details.dataset.section=kind;details.open=this[openKey];details.ontoggle=()=>{this[openKey]=details.open;};details.append(summary);
      const list=el('nav',undefined,'board-list');list.setAttribute('aria-label',goals?'Saved goals':'Saved boards');
      for(const object of items){
        const item=button(goals?object.title:object.name,()=>goals?editGoal(object.id):this.selectBoard(object));
        item.dataset[goals?'goalId':'boardId']=object.id;item.style.setProperty('--board-color',object.color||this.palette[0]||'#f59e0b');
        if(goals){
          item.className='goal-card';item.replaceChildren(el('span',object.title,'goal-card-title'));item.setAttribute('aria-label',object.title);
          const milestones=object.milestones||[],completed=milestones.filter(m=>m.status==='achieved').length,status=object.status||'proposed';
          const meta=el('span',undefined,'goal-card-meta'),pill=el('span',statusLabel(status),'goal-status-pill');pill.dataset.status=status;
          meta.append(pill,el('span',completed+'/'+milestones.length+' milestones','goal-card-count'));item.append(meta);
          const progress=el('progress');progress.max=milestones.length||1;progress.value=completed;progress.setAttribute('aria-label',completed+' of '+milestones.length+' milestones completed');item.append(progress);
        }
        if(!goals){
          const selected=object.id===this.current?.id;
          item.className='goal-card board-card';item.setAttribute('aria-current',String(selected));item.setAttribute('aria-label',object.name);
          item.replaceChildren(el('span',object.name,'goal-card-title'));
          const meta=el('span',undefined,'goal-card-meta'),pill=el('span',selected?'Selected':'Saved','goal-status-pill');pill.dataset.status=selected?'active':'saved';
          const count=new Set([...(object.members||[]),...(object.drafts||[]).map(d=>d.id)]).size;
          meta.append(pill,el('span',count+' '+(count===1?'node':'nodes'),'goal-card-count'));item.append(meta);
        }
        item.draggable=!this.ordering;item.title='Drag to reorder · Alt + Arrow keys to move';
        const type='text/'+kind+'-id';
        item.ondragstart=event=>{event.dataTransfer.setData(type,object.id);event.dataTransfer.effectAllowed='move';};
        item.ondragover=event=>{if([...event.dataTransfer.types].includes(type)){event.preventDefault();item.classList.add('drag-over');}};
        item.ondragleave=()=>item.classList.remove('drag-over');
        item.ondrop=event=>{event.preventDefault();item.classList.remove('drag-over');this.reorder(event.dataTransfer.getData(type),object.id,kind);};
        item.onkeydown=event=>{if(event.altKey&&['ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();const at=items.indexOf(object),other=items[at+(event.key==='ArrowUp'?-1:1)];if(other)this.reorder(object.id,other.id,kind);}};
        list.append(item);
      }
      if(!items.length)list.append(el('p',goals?'Add a goal to define an outcome.':'Start a board with a question, idea, or goal.','board-hint'));
      details.append(list);return details;
    },
    async reorder(source,target,kind='boards'){
      if(this.ordering||source===target)return;
      const key=kind==='goals'?'goals':'loaded',before=[...this[key]],from=before.findIndex(b=>b.id===source),to=before.findIndex(b=>b.id===target);if(from<0||to<0)return;
      const next=[...before];next.splice(to,0,next.splice(from,1)[0]);this[key]=next;this.ordering=true;this.render();
      try{await api('/'+kind+'/order','PUT',{ids:next.map(b=>b.id)});}
      catch(error){const rank=new Map(before.map((b,i)=>[b.id,i]));this[key].sort((a,b)=>(rank.get(a.id)??Infinity)-(rank.get(b.id)??Infinity));this.status.textContent=error.message;}
      finally{this.ordering=false;const status=this.status.textContent;this.render();this.status.textContent=status;this.root.querySelector('[data-'+(kind==='goals'?'goal':'board')+'-id="'+source+'"]')?.focus();}
    },
    async reload(){
      if(!this.root)return;
      if(!this.current){const data=await api('/boards');this.loaded=data.maps;this.goals=data.goals;this.render();return;}
      await this.flush();const {item}=await api('/maps/'+this.current.id);
      this.queues.delete(item.id);this.current=item;this.loaded=this.loaded.map(b=>b.id===item.id?item:b);this.render();
    },
    async persist(fields){if(this.current){this.queue().edit({positions:{...this.current.positions,...this.getPositions()},...fields});this.pendingPositions=this.current.positions;}},
    async addMembers(ids) { if (this.current) { await this.persist({members: [...new Set([...this.current.members, ...ids])], positions: {...this.current.positions, ...this.getPositions()}}); this.pendingPositions = this.current.positions; } },
    async removeMember(id) {
      try { const board = this.current, positions = {...board.positions}; delete positions[id];
        await this.persist({members: board.members.filter(i => i !== id), drafts: board.drafts.filter(d => d.id !== id), edges: board.edges.filter(e => e.source !== id && e.target !== id), positions, root: board.root === id ? '' : board.root, goal_id: 'goal:' + board.goal_id === id ? '' : board.goal_id}); changed();
      } catch (error) { this.status.textContent = error.message; }
    },
    async saveLayout() { if (!this.current) return; try { await this.persist({positions: {...this.current.positions, ...this.getPositions()}}); } catch (error) { this.status.textContent = error.message; } },
    remove() {
      const board = this.current, d = dialog('Delete board'); d.body.append(el('p', 'Delete “' + board.name + '” and its draft thoughts? Shared Goals, Ideas, and Actions will remain.'));
      const progress=el('div','','idea-picker-status');progress.setAttribute('role','status');d.body.append(progress);
      const remove = button('Delete board', async () => {
        if(remove.disabled)return;
        remove.disabled=true;d.body.inert=true;d.error.textContent='';
        const closeButtons=[...d.node.querySelectorAll('button')];closeButtons.forEach(b=>b.disabled=true);
        progress.replaceChildren(el('span','','idea-picker-spinner'),el('span','Deleting board…'));
        const queue=this.queue(board);
        try {
          const latest=await queue.prepareDelete();
          await api('/maps/'+board.id,'DELETE',{version:latest.version});
          this.queues.delete(board.id);this.loaded=this.loaded.filter(b=>b.id!==board.id);
          const nodeId='board:'+board.id;this.nodes.delete(nodeId);
          for(const [key,edge] of this.sharedEdges)if(edge.source===nodeId||edge.target===nodeId)this.sharedEdges.delete(key);
          this.current=null;this.deletionTransition=true;
          this.status.replaceChildren(el('span','','idea-picker-spinner'),el('span','Board deleted · Loading All activity…'));
          await this.selectBoard(null);d.node.close();
        } catch (error) {
          queue.resume();progress.replaceChildren();d.error.textContent=error.message+' Your board and pending edits are retained.';
          d.body.inert=false;closeButtons.forEach(b=>b.disabled=false);
        }
      }); d.footer.append(remove);
    },
    finishDeletionTransition(error=false){
      if(!this.deletionTransition)return;
      this.deletionTransition=false;
      this.status.textContent=error?'Board deleted. All activity could not load · Use Refresh to retry.':'Board deleted · All activity';
    },
    async edit(current = null, seed = null) {
      const d = dialog(current ? 'Settings' : 'Add Board');
      const name = field(d.body, 'name', 'Board name', current?.name || seed?.label, 'text', true, 100);
      const getColor=colorField(d.body,'Board color',current?.color||this.palette[this.loaded.length%this.palette.length]);
      const purpose = field(d.body, 'purpose', 'What are you exploring or trying to achieve?', current?.purpose || seed?.label, 'textarea', true, 3000);
      const starting = current || seed ? null : field(d.body, 'seed', 'Starting thought (optional)', '', 'text', false, 200);
      const goal = selectField(d.body, 'goal_id', 'Primary Goal (optional)', [['', 'No primary Goal']], '');
      for(const g of this.goals){const option=el('option',g.title);option.value=g.id;goal.append(option);}
      goal.value=current?.goal_id||(seed?.kind==='goals'?seed.object_id:'');
      const now=new Date(),today=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,10);
      const boardDate=field(d.body,'board_date','Board date',current?.board_date||today,'date',true);
      if(current)d.body.append(el('p','Created: '+(current.created_at||'Unknown (legacy board)')+' · Updated: '+(current.updated_at||'Unknown'),'board-hint'));
      const prompt = field(d.body, 'prompt', 'Agent instructions (optional)', current?.prompt, 'textarea', false, 20000);
      const agent = current ? null : selectField(d.body, 'agent', 'Start with', [['manual','My own thoughts'],['agent','An agent-generated draft board']], 'manual');
      const save = el('button', 'Save board'); save.type = 'submit'; d.footer.append(save); const key = crypto.randomUUID(), draftId = 'draft:' + crypto.randomUUID();
      d.form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try {
        if(current){await this.flush();current=this.current;}
        const members = [...new Set([...(current?.members || []), ...(seed ? [seed.id] : []), ...(goal.value ? ['goal:' + goal.value] : [])])];
        const root = current?.root || seed?.id || (goal.value ? 'goal:' + goal.value : draftId);
        const drafts = current?.drafts || (root === draftId ? [{id: draftId, title: starting?.value.trim() || name.value, body: purpose.value}] : []);
        const {item} = await api('/maps' + (current ? '/' + current.id : ''), current ? 'PATCH' : 'POST', {name: name.value, color:getColor(), purpose: purpose.value, board_date:boardDate.value, root, goal_id: goal.value, members, drafts, prompt: prompt.value || 'Develop this board toward its purpose. Propose alternatives, assumptions to test, and concrete next steps.', ...(current ? {version: current.version} : {request_id: key, positions: {}})});
        this.queues.delete(item.id);this.loaded=[...this.loaded.filter(m=>m.id!==item.id),item];if(seed)this.cacheNode(seed);const selectedGoal=this.goals.find(g=>g.id===goal.value);if(selectedGoal)this.cacheNode({...selectedGoal,id:'goal:'+selectedGoal.id,object_id:selectedGoal.id,label:selectedGoal.title,kind:'goals'});this.selectBoard(item); d.node.close(); if (agent?.value === 'agent') this.brainstorm();
      } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
    },
    async brainstorm() {
      if (!this.current) { this.status.textContent = 'Create or select a board first.'; return; }
      try{await this.flush();}catch(error){this.status.textContent=error.message;return;}
      const map = this.current; const d = dialog('Agent board planning');d.node.classList.add('board-agent-dialog');
      d.body.append(el('p', map.name, 'board-agent-context'),el('p', 'Review suggested ideas and connections before adding them to your board.', 'board-hint'));
      const output = el('div',undefined,'board-agent-output'), status = el('div',undefined,'board-agent-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');d.body.append(status, output); let timer, busy = false, pending = false, rendered = '';
      const perform = async (control, task) => {
        if(pending)return;pending=true;control.disabled=true;control.setAttribute('aria-busy','true');d.error.textContent='';
        try{await task();rendered='';}catch(error){d.error.textContent=error.message;}
        finally{pending=false;control.disabled=false;control.removeAttribute('aria-busy');await refresh();}
      };
      const sourceUrl = '/hfl-corpus/agent-bridge/sources/mindmap/' + map.id;
      const refresh = async () => {
        if (!d.node.open || busy || pending || d.node.querySelector('textarea:focus') || document.querySelectorAll('.idea-dialog[open]').length > 1) return; busy = true;
        try {
          const data = await request(sourceUrl);if(!d.node.open)return;const run = data.runs[0];
          const signature=JSON.stringify(run||null);if(signature===rendered)return;rendered=signature;
          const draft=output.querySelector('textarea')?.value||'';output.replaceChildren();status.replaceChildren();
          const state=run?.state||'ready',labels={ready:'Ready to plan',queued:'Queued',running:'Running',awaiting_input:'Needs your input',review:'Ready for review',failed:'Could not finish',succeeded:'Completed',cancelled:'Cancelled'};
          status.dataset.state=state;const heading=el('div',undefined,'board-agent-status-heading');
          if(['queued','running'].includes(state)){const spinner=el('span','','idea-picker-spinner');spinner.setAttribute('aria-hidden','true');heading.append(spinner);}
          heading.append(el('span',labels[state]||statusLabel(state),'board-agent-state'));status.append(heading);
          const hints={ready:'Request suggestions using the instructions in board settings.',queued:'Waiting for an agent worker. You can close this dialog and return later.',running:'The agent is reviewing your board and preparing suggestions.',awaiting_input:'Answer the question below to continue this run.',review:'Choose which suggestions to add to your board.',failed:'The run stopped before suggestions were ready. Retry below, with optional instructions.'};
          if(hints[state])status.append(el('p',hints[state],'board-hint'));
          requestSuggestions.hidden=['queued','running','awaiting_input','review','accepting'].includes(state);requestSuggestions.disabled=false;
          requestSuggestions.textContent=state==='failed'?'Start new run':'Request suggestions';requestSuggestions.classList.toggle('board-agent-primary',state!=='failed');
          if (run) {
            if(run.result?.summary&&!['queued','running'].includes(state))output.append(el('p',run.result.summary,'board-agent-summary'));
            if (run.state === 'review') {
              const proposals = run.result.ideas || [];
              if (proposals.length) output.append(button('Accept all as board drafts', async () => {
                const review = dialog('Review draft board');
                for (const proposal of proposals) review.body.append(el('h3', proposal.title), el('p', window.HflObjectDescription(proposal)));
                const accept = button('Add all thoughts', async () => { accept.disabled = true; try {
                  for (let index = 0; index < proposals.length; index++) {
                    const proposal = proposals[index];
                    await request('/hfl-corpus/agent-bridge/mindmaps/' + map.id + '/accept-proposal', {method:'POST',body:JSON.stringify({run_id:run.id,index,item:{title:proposal.title,body:window.HflObjectDescription(proposal)}})});
                  }
                  await this.reload(); changed(); review.node.close(); await refresh();
                } catch (error) { review.error.textContent = error.message + ' Already added thoughts are preserved; retry safely to finish.'; } finally { accept.disabled = false; } }); review.footer.append(accept);
              }));
              if (!proposals.length) output.append(el('p', 'No structured ideas were returned. Ask the agent to return proposals using the brainstorming schema.'));
              proposals.forEach((idea, index) => {
                const row = el('section', undefined, 'idea-proposal'); row.append(el('h3', idea.title), el('p', window.HflObjectDescription(idea)));
                row.append(button('Review / add thought', async () => {
                  const review = dialog('Review suggested thought'); const title = field(review.body, 'title', 'Title', idea.title, 'text', true, 200), body = field(review.body, 'body', 'Markdown description', window.HflObjectDescription(idea), 'textarea', false, 60000);
                  const accept = el('button', 'Add to board'); accept.type = 'submit'; review.footer.append(accept);
                  review.form.onsubmit = async event => { event.preventDefault(); accept.disabled = true; try { await request('/hfl-corpus/agent-bridge/mindmaps/' + map.id + '/accept-proposal', {method: 'POST', body: JSON.stringify({run_id: run.id, index, item: {title: title.value, description: '', body: body.value}})}); await this.reload(); review.node.close(); row.remove(); changed(); } catch (error) { review.error.textContent = error.message; } finally { accept.disabled = false; } };
                })); output.append(row);
              });
              output.append(button('Finish review', async () => { try { await request('/hfl-corpus/agent-bridge/runs/' + run.id + '/accept', {method: 'POST', body: '{}'}); await refresh(); } catch (error) { d.error.textContent = error.message; } }));
            }
            if (['awaiting_input', 'failed'].includes(run.state)) {
              if(run.result?.question)output.append(el('p',run.result.question,'board-agent-summary'));
              const reply = field(output, '', state==='failed'?'Retry instructions (optional)':'Your reply', draft, 'textarea');
              const retry=button(state==='failed'?'Retry suggestions':'Continue',()=>perform(retry,()=>request('/hfl-corpus/agent-bridge/runs/' + run.id + '/continue', {method:'POST',body:JSON.stringify({reply:reply.value})})));retry.className='board-agent-primary';output.append(retry);
            }
            if (['queued','running','awaiting_input','review'].includes(run.state)){const cancel=button('Cancel run',()=>perform(cancel,()=>request('/hfl-corpus/agent-bridge/runs/'+run.id+'/cancel',{method:'POST',body:'{}'})));cancel.className='board-agent-cancel';output.append(cancel);}
          }
        } catch (error) { d.error.textContent = error.message; } finally { busy = false; }
      };
      let key = crypto.randomUUID();const requestSuggestions=button('Request suggestions',()=>perform(requestSuggestions,async()=>{await request(sourceUrl+'/run',{method:'POST',body:JSON.stringify({request_key:key,auto_complete:false})});key=crypto.randomUUID();}));requestSuggestions.className='board-agent-primary';requestSuggestions.disabled=true;d.footer.append(requestSuggestions);
      status.textContent='Loading agent status…';
      await refresh(); timer = setInterval(refresh, 5000); d.node.addEventListener('close', () => clearInterval(timer));
    }
  };
  window.addEventListener('beforeunload',event=>{if([...maps.queues.values()].some(q=>q.dirty)){event.preventDefault();event.returnValue='';}});
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
