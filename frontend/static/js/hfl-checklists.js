/* Shared checklists keep stable item IDs through reordering and conversion. */
window.HflChecklists = class {
  constructor(root, options = {}) { this.root = root; this.options = options; this.set([]); }
  notify() { this.root.dispatchEvent(new CustomEvent('hfl:checklists-changed', {bubbles: true})); }
  set(value) { this.value = structuredClone(value || []); this.render(); }
  addItem(list, index = list.items.length) {
    const item = {id: crypto.randomUUID(), text: '', done: false};
    list.items.splice(index, 0, item); this.render();
    this.root.querySelector(`[data-item-id="${CSS.escape(item.id)}"] input[type=text]`)?.focus();
  }
  button(text, action, label = text) { const b = document.createElement('button'); b.type = 'button'; b.textContent = text; b.setAttribute('aria-label', label); b.onclick = action; return b; }
  iconButton(icon, action, label) {
    const button = this.button('', action, label); button.title = label;
    const paths = {board: 'M3 3h18v18H3zM10 3v18M3 10h18', move: 'M4 12h16m-5-5 5 5-5 5', up: 'm6 15 6-6 6 6', down: 'm6 9 6 6 6-6', delete: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7', convert: 'm13 2-9 12h7l-1 8 10-12h-7l1-8Z', open: 'M14 3h7v7M21 3 10 14M10 3H3v18h18v-7'};
    Object.assign(paths, {copy:'M8 8h13v13H8zM16 8V3H3v13h5', sortAsc:'M4 4v16m-3-3 3 3 3-3M11 5h4M11 10h7M11 15h10', sortDesc:'M4 20V4m-3 3 3-3 3 3M11 5h10M11 10h7M11 15h4'});
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', paths[icon]);
    svg.append(path); button.append(svg); return button;
  }
  updateConversion() {
    for (const button of this.root.querySelectorAll('[data-convert-item]')) {
      button.disabled = this.options.canConvert ? !this.options.canConvert() : false;
      button.title = button.disabled ? 'Save the idea before creating an action from an item.' : 'Create action';
    }
  }
  render() {
    this.root.replaceChildren();
    for (const [index, list] of this.value.entries()) {
      const box = document.createElement('section'); box.className = 'idea-checklist'; box.dataset.listId = list.id;
      const title = document.createElement('input'); title.value = list.title; title.placeholder = 'Checklist name'; title.maxLength = 200; title.required = true; title.setAttribute('aria-label', 'Checklist name'); title.oninput = () => { list.title = title.value; this.notify(); };
      const completed = list.items.filter(i => i.done).length;
      const progress = document.createElement('div'); progress.className = 'checklist-progress';
      const percent = document.createElement('span'); percent.textContent = `${list.items.length ? Math.round(completed / list.items.length * 100) : 0}%`;
      const meter = document.createElement('progress'); meter.max = Math.max(1, list.items.length); meter.value = list.items.filter(i => i.done).length;
      meter.setAttribute('aria-label', `${list.title}: ${completed} of ${list.items.length} complete`); progress.append(percent, meter);
      const coverLabel = document.createElement('label'); coverLabel.className = 'checklist-cover-toggle';
      const cover = document.createElement('input'); cover.type = 'checkbox'; cover.checked = !!list.cover;
      cover.onchange = () => { list.cover = cover.checked; this.notify(); }; coverLabel.append(cover, document.createTextNode('Checklist cover'));
      const header = document.createElement('div'); header.className = 'idea-checklist-header';
      header.append(title);
      const moveList = delta => { const next = index + delta; if (next < 0 || next >= this.value.length) return; [this.value[index], this.value[next]] = [this.value[next], this.value[index]]; this.render(); };
      const grip = this.button('⠿', () => {}, 'Drag checklist to reorder'); grip.draggable = true;
      grip.ondragstart = event => { event.dataTransfer.setData('application/x-hfl-checklist', list.id); event.dataTransfer.effectAllowed = 'move'; };
      box.ondragover = event => { if ([...event.dataTransfer.types].includes('application/x-hfl-checklist')) event.preventDefault(); };
      box.ondrop = event => { const id = event.dataTransfer.getData('application/x-hfl-checklist'); const from = this.value.findIndex(l => l.id === id); if (from < 0 || id === list.id) return; event.preventDefault(); const [moved] = this.value.splice(from, 1); this.value.splice(this.value.indexOf(list), 0, moved); this.render(); };
      const up = this.iconButton('up', () => moveList(-1), 'Move checklist up'); up.disabled = index === 0;
      const down = this.iconButton('down', () => moveList(1), 'Move checklist down'); down.disabled = index === this.value.length - 1;
      header.prepend(grip);
      const listActions = document.createElement('div'); listActions.className = 'checklist-list-actions';
      if (this.options.addToBoard) listActions.append(this.iconButton('board', () => this.options.addToBoard(list, null), 'Add list to board'));
      listActions.append(this.iconButton('copy', () => window.HflCopyList(structuredClone(list)), 'Copy list'), up, down);
      if (!this.options.singleList) listActions.append(this.iconButton('delete', () => { this.value.splice(index, 1); this.render(); }, 'Remove checklist'));
      header.append(listActions);
      const sorting = document.createElement('div'); sorting.className = 'checklist-sort-actions';
      for (const [icon, direction, label] of [['sortAsc',1,'Sort items A–Z'],['sortDesc',-1,'Sort items Z–A']]) sorting.append(this.iconButton(icon, () => { list.items.sort((a,b) => direction * a.text.localeCompare(b.text, undefined, {sensitivity:'base'})); this.render(); }, label));
      const tools = document.createElement('div'); tools.className = 'checklist-tools'; tools.append(coverLabel, sorting);
      box.append(header, tools, progress);
      for (const [i, item] of list.items.entries()) {
        const row = document.createElement('div'); row.className = 'idea-check-row'; row.dataset.itemId = item.id;
        const check = document.createElement('input'); check.type = 'checkbox'; check.checked = item.done; check.setAttribute('aria-label', 'Complete ' + item.text);
        check.onchange = () => { item.done = check.checked; this.render(); };
        const text = document.createElement('input'); text.type = 'text'; text.value = item.text; text.required = true; text.maxLength = 2000; text.setAttribute('aria-label', 'Checklist item'); text.oninput = () => { item.text = text.value; check.setAttribute('aria-label', 'Complete ' + item.text); this.notify(); };
        text.onkeydown = event => {
          if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229) return;
          event.preventDefault(); event.stopPropagation();
          if (!event.repeat && text.value.trim()) { item.text = text.value; this.addItem(list, i + 1); }
        };
        const move = delta => { const target = i + delta; if (target >= 0 && target < list.items.length) { [list.items[i], list.items[target]] = [list.items[target], list.items[i]]; this.render(); } };
        row.tabIndex = 0; row.setAttribute('role', 'group'); row.setAttribute('aria-label', 'Checklist item; use arrow keys to reorder');
        row.classList.toggle('is-complete', !!item.done);
        row.onkeydown = event => { if (event.target === row && ['ArrowUp', 'ArrowDown'].includes(event.key)) { event.preventDefault(); move(event.key === 'ArrowUp' ? -1 : 1); this.root.querySelector(`[data-item-id="${CSS.escape(item.id)}"]`)?.focus(); } };
        row.onpointerdown = event => {
          if (event.button !== 0 || event.target.closest('button, select, a, input[type=checkbox]') || (event.target === text && document.activeElement === text)) return;
          event.preventDefault(); this.root.setPointerCapture(event.pointerId);
          let dragging = false, destination = list;
          const startX = event.clientX, startY = event.clientY;
          this.root.onpointermove = event => {
            if (!dragging && Math.hypot(event.clientX-startX, event.clientY-startY) < 5) return;
            dragging = true; row.classList.add('dragging');
            const target = document.elementFromPoint(event.clientX,event.clientY);
            const targetBox = target?.closest('.idea-checklist');
            if (!targetBox || !this.root.contains(targetBox)) return;
            destination = this.value.find(l => l.id === targetBox.dataset.listId);
            const targetRow = target.closest('.idea-check-row');
            if (targetRow === row) return;
            let before = targetRow && event.clientY < targetRow.getBoundingClientRect().top + targetRow.offsetHeight/2 ? targetRow : targetRow?.nextElementSibling;
            if (!before?.matches('.idea-check-row')) before = targetBox.querySelector('.checklist-add-item');
            targetBox.insertBefore(row,before);
          };
          const finish = end => {
            this.root.onpointermove = this.root.onpointerup = this.root.onpointercancel = this.root.onlostpointercapture = null;
            if (this.root.hasPointerCapture(event.pointerId)) this.root.releasePointerCapture(event.pointerId);
            if (!dragging) { if (end.type === 'pointerup') edit(); return; }
            if (end.type === 'pointerup') {
              list.items = list.items.filter(x => x.id !== item.id);
              const nextId = row.nextElementSibling?.dataset.itemId;
              const targetIndex = destination.items.findIndex(x => x.id === nextId);
              destination.items.splice(targetIndex < 0 ? destination.items.length : targetIndex, 0, item);
            }
            this.render(); this.root.querySelector(`[data-item-id="${CSS.escape(item.id)}"]`)?.focus();
          };
          this.root.onpointerup = finish; this.root.onpointercancel = finish; this.root.onlostpointercapture = finish;
        };
        const actions = document.createElement('div'); actions.className = 'checklist-item-actions';
        actions.append(this.iconButton('delete', () => { list.items.splice(i, 1); this.render(); }, 'Remove item'));
        const moveButton = this.iconButton('move', () => {
          const modal = document.createElement('dialog'); modal.className = 'agenda-dialog checklist-move-dialog';
          const heading = document.createElement('h2'); heading.textContent = 'Move checklist item';
          heading.id = 'checklist-move-' + crypto.randomUUID(); modal.setAttribute('aria-labelledby', heading.id);
          const header = document.createElement('header'); header.className = 'agenda-dialog-header';
          header.append(heading, this.button('×', () => modal.close(), 'Close move checklist item'));
          const body = document.createElement('div'); body.className = 'checklist-move-body';
          const mapping = document.createElement('p');
          mapping.textContent = 'From ' + list.title;
          const picker = document.createElement('select'); picker.setAttribute('aria-label', 'Move item to checklist');
          const placeholder = document.createElement('option'); placeholder.textContent = 'Choose destination checklist'; placeholder.value = ''; picker.append(placeholder);
          for (const target of this.value.filter(l => l !== list)) { const option = document.createElement('option'); option.value = target.id; option.textContent = 'to ' + target.title; picker.append(option); }
          const confirm = this.button('Confirm', () => { const target = this.value.find(l => l.id === picker.value && l !== list); if (!target) return; list.items = list.items.filter(x => x.id !== item.id); target.items.push(item); modal.close(); this.render(); });
          confirm.disabled = true; picker.onchange = () => { confirm.disabled = !picker.value; };
          confirm.className = 'agenda-primary';
          const destination = document.createElement('label'); destination.textContent = 'Destination checklist'; destination.append(picker);
          const footer = document.createElement('div'); footer.className = 'checklist-move-actions'; footer.append(confirm, this.button('Cancel', () => modal.close()));
          body.append(mapping, destination); modal.append(header, body, footer);
          modal.addEventListener('click', event => { const rect=modal.getBoundingClientRect(); if(event.target===modal && (event.clientX<rect.left || event.clientX>rect.right || event.clientY<rect.top || event.clientY>rect.bottom))modal.close(); });
          modal.addEventListener('close', () => modal.remove()); document.body.append(modal); modal.showModal(); picker.focus();
        }, 'Move item to another checklist'); moveButton.disabled = this.value.length < 2; actions.prepend(moveButton);
        if (this.options.addToBoard) actions.prepend(this.iconButton('board', () => this.options.addToBoard(list, item), 'Add checklist item to board'));
        row.append(check, text, actions);
        const preview = document.createElement('div'); preview.className = 'checklist-markdown markdown-body'; preview.tabIndex = 0; preview.setAttribute('aria-label', 'Edit checklist item');
        const show = () => { if (!text.value.trim()) return; preview.hidden=false; text.hidden=true; window.HflChecklistMarkdown?.(preview,text.value); };
        const edit = () => { preview.hidden=true; text.hidden=false; text.focus(); };
        preview.onclick = event => { if (!event.target.closest('a')) edit(); };
        preview.onkeydown = event => { if (event.target===preview && ['Enter',' '].includes(event.key)) {event.preventDefault();edit();} };
        text.onblur=show; text.after(preview); preview.hidden=true; show();
        if (this.options.convert) {
          const convert = this.iconButton('convert', () => { if (!this.options.canConvert || this.options.canConvert()) this.options.convert(list.id, item.id); }, 'Create action');
          convert.dataset.convertItem = item.id; actions.prepend(convert);
        }
        // Item IDs are unique across the object's lists; moves preserve provenance.
        for (const link of (this.options.links || []).filter(link => link.item_id === item.id)) actions.append(this.iconButton('open', () => this.options.openAction(link.action_id), 'Open action'));
        box.append(row);
      }
      const add = this.button('Add item', () => this.addItem(list));
      add.className = 'checklist-add-item'; box.append(add);
      this.root.append(box);
    }
    const addChecklist = this.button('Add new checklist', () => { this.value.push({id: crypto.randomUUID(), title: 'Checklist', cover: false, items: []}); this.render(); }, 'Add new checklist');
    if (this.options.addButtonRoot) this.options.addButtonRoot.replaceChildren(addChecklist);
    else if (!this.options.singleList) this.root.append(addChecklist);
    this.updateConversion(); this.notify();
  }
};
(() => {
  const form = document.getElementById('followup-form');
  if (form?.querySelector('[data-action-checklists]')) {
    window.hflActionChecklists = new HflChecklists(form.querySelector('[data-action-checklists]'), {addButtonRoot: form.querySelector('[data-checklist-toolbar]')});
    form.addEventListener('reset', () => window.hflActionChecklists.set([]));
  }
})();
window.HflChecklistCover = function(root, item, save, open) {
  for (const list of (item.checklists || []).filter(list => list.cover)) {
    const section = document.createElement('section'); section.className = 'checklist-card-cover';
    const heading = document.createElement('p'); heading.textContent = `${list.title} · ${list.items.filter(i => i.done).length}/${list.items.length}`; section.append(heading);
    for (const task of [...list.items].sort((a,b) => Number(a.done) - Number(b.done))) {
      const label = document.createElement('label'), check = document.createElement('input'); check.type = 'checkbox'; check.checked = task.done;
      check.onchange = async () => { section.inert = true; const lists = structuredClone(item.checklists); lists.find(l => l.id === list.id).items.find(i => i.id === task.id).done = check.checked;
        try { await save(lists); } catch (error) { check.checked = task.done; const message = document.createElement('p'); message.setAttribute('role', 'alert'); message.textContent = error.message; section.append(message); } finally { section.inert = false; }
      }; const text=document.createElement('span'); window.HflChecklistMarkdown?.(text,task.text); if(!window.HflChecklistMarkdown)text.textContent=task.text; label.append(check,text); section.append(label);
    }
    root.append(section);
  }
};

window.HflAgentInstructions = lists => { const value = structuredClone(lists || []); if (!value.some(l => l.title.trim().toLowerCase() === 'agent instructions')) value.push({id:crypto.randomUUID(),title:'Agent Instructions',cover:false,items:[]}); return value; };
