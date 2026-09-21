/* Shared checklists keep stable item IDs through reordering and conversion. */
window.HflChecklists = class {
  constructor(root, options = {}) { this.root = root; this.options = options; this.set([]); }
  set(value) { this.value = structuredClone(value || []); this.render(); }
  addItem(list, index = list.items.length) {
    const item = {id: crypto.randomUUID(), text: '', done: false};
    list.items.splice(index, 0, item); this.render();
    this.root.querySelector(`[data-item-id="${CSS.escape(item.id)}"] input[type=text]`)?.focus();
  }
  button(text, action, label = text) { const b = document.createElement('button'); b.type = 'button'; b.textContent = text; b.setAttribute('aria-label', label); b.onclick = action; return b; }
  iconButton(icon, action, label) {
    const button = this.button('', action, label); button.title = label;
    const paths = {delete: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7', convert: 'm13 2-9 12h7l-1 8 10-12h-7l1-8Z', open: 'M14 3h7v7M21 3 10 14M10 3H3v18h18v-7'};
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
      const box = document.createElement('section'); box.className = 'idea-checklist';
      const title = document.createElement('input'); title.value = list.title; title.placeholder = 'Checklist name'; title.maxLength = 200; title.required = true; title.setAttribute('aria-label', 'Checklist name'); title.oninput = () => { list.title = title.value; };
      const completed = list.items.filter(i => i.done).length;
      const progress = document.createElement('div'); progress.className = 'checklist-progress';
      const percent = document.createElement('span'); percent.textContent = `${list.items.length ? Math.round(completed / list.items.length * 100) : 0}%`;
      const meter = document.createElement('progress'); meter.max = Math.max(1, list.items.length); meter.value = list.items.filter(i => i.done).length;
      meter.setAttribute('aria-label', `${list.title}: ${completed} of ${list.items.length} complete`); progress.append(percent, meter);
      const coverLabel = document.createElement('label'); coverLabel.className = 'checklist-cover-toggle';
      const cover = document.createElement('input'); cover.type = 'checkbox'; cover.checked = !!list.cover;
      cover.onchange = () => { list.cover = cover.checked; }; coverLabel.append(cover, document.createTextNode('Checklist cover'));
      const header = document.createElement('div'); header.className = 'idea-checklist-header';
      header.append(title, this.iconButton('delete', () => { this.value.splice(index, 1); this.render(); }, 'Remove checklist'));
      box.append(header, coverLabel, progress);
      for (const [i, item] of list.items.entries()) {
        const row = document.createElement('div'); row.className = 'idea-check-row'; row.dataset.itemId = item.id;
        const check = document.createElement('input'); check.type = 'checkbox'; check.checked = item.done; check.setAttribute('aria-label', 'Complete ' + item.text);
        check.onchange = () => { item.done = check.checked; this.render(); };
        const text = document.createElement('input'); text.type = 'text'; text.value = item.text; text.required = true; text.maxLength = 2000; text.setAttribute('aria-label', 'Checklist item'); text.oninput = () => { item.text = text.value; check.setAttribute('aria-label', 'Complete ' + item.text); };
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
          if (event.button !== 0 || event.target.closest('button, input[type=checkbox]') || (event.target === text && document.activeElement === text)) return;
          event.preventDefault(); this.root.setPointerCapture(event.pointerId);
          let dragging = false;
          const startX = event.clientX, startY = event.clientY;
          this.root.onpointermove = event => {
            if (!dragging && Math.hypot(event.clientX - startX, event.clientY - startY) < 5) return;
            dragging = true; row.classList.add('dragging');
            const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('.idea-check-row');
            if (target && target !== row && target.parentElement === box) box.insertBefore(row, event.clientY > target.getBoundingClientRect().top + target.offsetHeight / 2 ? target.nextSibling : target);
          };
          const finish = end => {
            list.items = [...box.querySelectorAll('[data-item-id]')].map(r => list.items.find(i => i.id === r.dataset.itemId));
            this.root.onpointermove = this.root.onpointerup = this.root.onpointercancel = this.root.onlostpointercapture = null;
            if (this.root.hasPointerCapture(event.pointerId)) this.root.releasePointerCapture(event.pointerId);
            if (!dragging) { if (end.type === 'pointerup') text.focus(); return; }
            this.render();
            this.root.querySelector(`[data-item-id="${CSS.escape(item.id)}"]`)?.focus();
          };
          this.root.onpointerup = finish; this.root.onpointercancel = finish; this.root.onlostpointercapture = finish;
        };
        const actions = document.createElement('div'); actions.className = 'checklist-item-actions';
        actions.append(this.iconButton('delete', () => { list.items.splice(i, 1); this.render(); }, 'Remove item'));
        row.append(check, text, actions);
        if (this.options.convert) {
          const convert = this.iconButton('convert', () => { if (!this.options.canConvert || this.options.canConvert()) this.options.convert(list.id, item.id); }, 'Create action');
          convert.dataset.convertItem = item.id; actions.prepend(convert);
        }
        for (const link of (this.options.links || []).filter(link => link.checklist_id === list.id && link.item_id === item.id)) actions.append(this.iconButton('open', () => this.options.openAction(link.action_id), 'Open action'));
        box.append(row);
      }
      const add = this.button('Add item', () => this.addItem(list));
      add.className = 'checklist-add-item'; box.append(add);
      this.root.append(box);
    }
    const addChecklist = this.button('Add', () => { this.value.push({id: crypto.randomUUID(), title: 'Checklist', cover: false, items: []}); this.render(); }, 'Add checklist');
    if (this.options.addButtonRoot) this.options.addButtonRoot.replaceChildren(addChecklist);
    else this.root.append(addChecklist);
    this.updateConversion();
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
    for (const task of list.items) {
      const label = document.createElement('label'), check = document.createElement('input'); check.type = 'checkbox'; check.checked = task.done;
      check.onchange = async () => { section.inert = true; const lists = structuredClone(item.checklists); lists.find(l => l.id === list.id).items.find(i => i.id === task.id).done = check.checked;
        try { await save(lists); } catch (error) { check.checked = task.done; const message = document.createElement('p'); message.setAttribute('role', 'alert'); message.textContent = error.message; section.append(message); } finally { section.inert = false; }
      }; label.append(check, document.createTextNode(task.text)); section.append(label);
    }
    root.append(section);
  }
};
