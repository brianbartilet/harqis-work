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
  const changed = (selectId = null, boardSwitch = false) => { window.dispatchEvent(new CustomEvent('hfl:ideas-updated', {detail:{selectId,boardSwitch,boardLocal:!!maps.current}})); if(!maps.current)window.dispatchEvent(new Event('hfl:actions-updated')); };
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
          maps.cacheNode({...current,id:nodeId,object_id:current.id,label:current.title,kind:kind === 'idea' ? 'ideas' : 'actions'});
          if(parent?.kind==='drafts') {
            if(maps.current?.id!==editingBoard)throw Error('Return to the original board to finish linking this saved object.');
            await maps.persist({members:[...new Set([...maps.current.members,nodeId])],edges:[...maps.current.edges.filter(e=>!(e.source===parent.id&&e.target===nodeId)),{source:parent.id,target:nodeId,relation:'related-to'}]});
          } else {
            if(parent)await api('/links','POST',{source:parent.id,target:nodeId,relation:parent.kind==='daily'?'source-date':'related-to'});
            await maps.addMembers([nodeId,...(parent?[parent.id]:[])]);
          }
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
  async function chooseMapMembers() {
    const d = dialog('Attach existing context');
    const search = field(d.body, '', 'Search', '', 'search'), list = el('div', undefined, 'idea-choices'); d.body.append(list);
    try {
      const graph = await request('/api/hfl/entities/graph?limit=0');
      const render = () => {
        list.replaceChildren();
        graph.nodes.filter(n => !maps.current.members.includes(n.id) && n.label.toLowerCase().includes(search.value.toLowerCase())).slice(0, 100).forEach(n => {
          list.append(button(n.label + ' · ' + n.kind, async () => {
            try { maps.cacheNode(n); await maps.addMembers([n.id]); d.node.close(); changed(); }
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
  async function editGoal(identity = null) {
    const d = dialog(identity ? 'Edit Goal' : 'New Goal');
    const loading = el('p', identity ? 'Loading Goal…' : '', 'board-hint'); loading.setAttribute('role', 'status'); d.body.append(loading);
    try {
      let item = identity ? (await api('/goals/' + identity)).item : {};
      if (!d.node.open) return;
      loading.remove();
      const graph = {nodes: []};
      const choices = (select, kinds, selected) => {
        const available = graph.nodes.filter(n => kinds.includes(n.kind));
        const known = new Set(available.map(n => n.id));
        select.replaceChildren();
        for (const n of [...available, ...selected.filter(id => !known.has(id)).map(id => ({id, label: 'Existing link (details unavailable)'}))]) {
          const option = el('option', n.label); option.value = n.id; option.selected = selected.includes(n.id); select.append(option);
        }
      };
      const title = field(d.body, 'title', 'Goal', item.title, 'text', true, 200);
      const body = field(d.body, 'body', 'Description', item.body, 'textarea', false, 60000);
      const criteria = field(d.body, 'criteria', 'Success criteria', item.success_criteria, 'textarea', false, 6000);
      const status = selectField(d.body, 'status', 'Status', ['proposed','active','paused','achieved','dropped'].map(s => [s,s]), item.status || 'proposed');
      const date = field(d.body, 'target_date', 'Target date', item.target_date, 'date');
      const notes = field(d.body, 'progress_notes', 'Progress notes', item.progress_notes, 'textarea', false, 20000);
      const links = selectField(d.body, '', 'Supporting Ideas and Actions', graph.nodes.filter(n => ['ideas','actions'].includes(n.kind)).map(n => [n.id,n.label]), ''); links.multiple = true;
      choices(links, ['ideas','actions'], item.linked_objects || []); links.disabled = true;
      const linkStatus = el('p', 'Loading optional Idea and Action links…', 'board-hint'); linkStatus.setAttribute('role', 'status'); d.body.append(linkStatus);
      const milestones = el('section', undefined, 'goal-milestones'); milestones.append(el('h3', 'Milestones')); d.body.append(milestones);
      const rows = [];
      const add = (m = {}) => {
        const section = el('section', undefined, 'goal-milestone'); const row = {id: m.id || crypto.randomUUID(), section};
        row.title = field(section, '', 'Milestone', m.title, 'text', true, 300);
        row.status = selectField(section, '', 'Milestone status', ['planned','active','achieved','dropped'].map(s => [s,s]), m.status || 'planned');
        row.date = field(section, '', 'Milestone target date', m.target_date, 'date');
        row.actions = selectField(section, '', 'Linked Actions', graph.nodes.filter(n => n.kind === 'actions').map(n => [n.id, n.label]), ''); row.actions.multiple = true;
        choices(row.actions, ['actions'], m.actions || []); row.actions.disabled = links.disabled;
        section.append(button('Remove milestone', () => { rows.splice(rows.indexOf(row), 1); section.remove(); })); rows.push(row); milestones.append(section);
      };
      for (const milestone of item.milestones || []) add(milestone);
      d.body.append(button('Add milestone', () => add()), el('p', 'Completing Actions does not automatically achieve this Goal. Assess the success criteria when updating its status.'));
      const save = el('button', 'Save Goal'); save.type = 'submit'; d.footer.append(save); const key = crypto.randomUUID();
      d.form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try {
        const values = {title: title.value, body: body.value, success_criteria: criteria.value, status: status.value, target_date: date.value, progress_notes: notes.value, milestones: rows.map(r => ({id:r.id,title:r.title.value,status:r.status.value,target_date:r.date.value,actions:[...r.actions.selectedOptions].map(o=>o.value)})), ...(item.id ? {version:item.version} : {request_id:key})};
        values.linked_objects = [...links.selectedOptions].map(o => o.value);
        item = (await api('/goals' + (item.id ? '/' + item.id : ''), item.id ? 'PATCH' : 'POST', values)).item;
        maps.goals=[...maps.goals.filter(g=>g.id!==item.id),item];maps.cacheNode({...item,id:'goal:'+item.id,object_id:item.id,label:item.title,kind:'goals'});
        if (maps.current) await maps.addMembers(['goal:' + item.id]); d.node.close(); changed();
      } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
      let controller;
      const loadLinks = async () => {
        controller?.abort(); controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 45000);
        linkStatus.replaceChildren(document.createTextNode('Loading optional Idea and Action links…'));
        try {
          const data = await request('/api/hfl/entities/graph?limit=0', {signal:controller.signal});
          if (!d.node.open) return;
          graph.nodes = data.nodes;
          choices(links, ['ideas','actions'], [...links.selectedOptions].map(o => o.value)); links.disabled = false;
          for (const row of rows) { choices(row.actions, ['actions'], [...row.actions.selectedOptions].map(o => o.value)); row.actions.disabled = false; }
          linkStatus.textContent = 'Optional links ready.';
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
    if (node.status) root.append(el('p', 'Status: ' + node.status.replaceAll('_', ' '), 'idea-inspector-status'));
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
    queues:new Map(),nodes:new Map(),sharedEdges:new Map(),goals:[],
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
      this.root = root; if (matchMedia('(max-width:760px)').matches) root.closest('details').open = false;
      this.status = el('p', '', 'idea-map-status'); this.status.setAttribute('role', 'status');
      try { const data = await api('/boards'); this.goals=data.goals; this.loaded = data.maps; const params = new URL(location.href).searchParams; this.current = this.loaded.find(m => m.id === (params.get('board') || params.get('map'))) || null; this.pendingPositions = this.current?.positions || {}; this.render(); }
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
      this.root.replaceChildren(); document.querySelector('.kg-shell')?.classList.toggle('has-board', !!this.current); document.getElementById('kg-search').placeholder = this.current ? 'Search this board' : 'Search entries or entities';
      const all = button('All activity', () => this.selectBoard(null)); all.setAttribute('aria-pressed', String(!this.current)); this.root.append(all);
      const list = el('nav', undefined, 'board-list'); list.setAttribute('aria-label', 'Saved boards');
      for (const board of this.loaded) { const item = button(board.name, () => this.selectBoard(board)); item.setAttribute('aria-current', String(board.id === this.current?.id)); list.append(item); }
      this.root.append(list, button('New board', () => this.edit()), button('New Goal', () => editGoal()), this.status);
      if (!this.loaded.length) this.root.append(el('p', 'Start a board with a question, idea, or goal.', 'board-hint'));
      if (!this.current) return;
      const board = this.current, section = el('section', undefined, 'board-controls'); section.append(el('h2', board.name), el('p', board.purpose, 'board-purpose'));
      section.append(button('Add thought', () => editThought()), button('Attach existing', () => chooseMapMembers()), button('Board settings', () => this.edit(board)), button('Save now',()=>this.saveNow()), button('Save layout', () => this.saveLayout()), button('Ask agent', () => this.brainstorm()), button('Delete board', () => this.remove()));
      const pending=this.queues.get(board.id);
      if(pending?.error)section.append(button('Retry save',()=>this.saveNow()),button('Resolve unsaved changes',()=>this.resolveSave()));
      this.root.append(section);
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
      const remove = button('Delete board', async () => { remove.disabled = true; try { await this.flush(); await api('/maps/' + board.id, 'DELETE', {version:this.current.version});this.queues.delete(board.id);this.loaded=this.loaded.filter(b=>b.id!==board.id);this.current=null;this.selectBoard(null); d.node.close(); } catch (error) { d.error.textContent = error.message; remove.disabled = false; } }); d.footer.append(remove);
    },
    async edit(current = null, seed = null) {
      const d = dialog(current ? 'Board settings' : 'New board');
      const name = field(d.body, 'name', 'Board name', current?.name || seed?.label, 'text', true, 100);
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
        const {item} = await api('/maps' + (current ? '/' + current.id : ''), current ? 'PATCH' : 'POST', {name: name.value, purpose: purpose.value, board_date:boardDate.value, root, goal_id: goal.value, members, drafts, prompt: prompt.value || 'Develop this board toward its purpose. Propose alternatives, assumptions to test, and concrete next steps.', ...(current ? {version: current.version} : {request_id: key, positions: {}})});
        this.queues.delete(item.id);this.loaded=[...this.loaded.filter(m=>m.id!==item.id),item];if(seed)this.cacheNode(seed);const selectedGoal=this.goals.find(g=>g.id===goal.value);if(selectedGoal)this.cacheNode({...selectedGoal,id:'goal:'+selectedGoal.id,object_id:selectedGoal.id,label:selectedGoal.title,kind:'goals'});this.selectBoard(item); d.node.close(); if (agent?.value === 'agent') this.brainstorm();
      } catch (error) { d.error.textContent = error.message; } finally { save.disabled = false; } };
    },
    async brainstorm() {
      if (!this.current) { this.status.textContent = 'Create or select a board first.'; return; }
      try{await this.flush();}catch(error){this.status.textContent=error.message;return;}
      const map = this.current; const d = dialog('Agent board planning · ' + map.name);
      d.body.append(el('p', 'The agent proposes ideas and connections for your review. Accept individual suggestions to save them.'));
      const output = el('div'), status = el('p'); d.body.append(status, output); let timer, busy = false;
      const sourceUrl = '/hfl-corpus/agent-bridge/sources/mindmap/' + map.id;
      const refresh = async () => {
        if (!d.node.open || busy || d.node.querySelector('textarea:focus') || document.querySelectorAll('.idea-dialog[open]').length > 1) return; busy = true;
        try {
          const data = await request(sourceUrl); const run = data.runs[0]; output.replaceChildren();
          status.textContent = run ? 'Agent status: ' + run.state : 'No brainstorming run yet. Save instructions in board settings, then request suggestions.';
          if (run) {
            output.append(el('p', run.result.summary || 'Queued work will start when an agent worker is available.'));
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
