/* A read-only starting point; editing and execution stay in the existing tools. */
(() => {
  const root = document.querySelector('[data-distill]');
  if (!root) return;
  const recent = root.querySelector('[data-distill-recent]');
  const error = root.querySelector('[data-distill-error]');
  const retry = root.querySelector('[data-distill-retry]');
  const element = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
  function render(target, items, empty) {
    target.replaceChildren();
    for (const item of items.slice(0, 6)) {
      const link = document.createElement('a'); link.className = 'distill-action';
      link.href = '/hfl-corpus/actions?' + new URLSearchParams({edit_kind: 'actionable', edit: item.id});
      const status = {open:'Active', active:'Active', in_progress:'In progress', incomplete:'Incomplete', done:'Done'}[item.status] || item.status;
      const badge = element('span', status); badge.className = 'distill-action-status'; badge.dataset.status = item.status;
      link.append(badge, element('strong', item.title));
      if (item.expected_outcome || item.body) link.append(element('p', item.expected_outcome || item.body));
      const meta = element('div'); meta.className = 'distill-action-meta';
      if (item.matrix) meta.append(element('span', item.matrix));
      if (item.due_date) meta.append(element('span', (item.overdue && item.status !== 'done' ? 'Overdue · ' : 'Due ') + item.due_date));
      if (meta.children.length) link.append(meta);
      const updated = new Date(item.updated_at || item.created_at);
      if (!Number.isNaN(updated.valueOf())) {
        const time = element('time', 'Updated ' + new Intl.DateTimeFormat(undefined, {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}).format(updated));
        time.dateTime = updated.toISOString(); time.title = updated.toLocaleString(); link.append(time);
      }
      target.append(link);
    }
    if (!items.length) { const note = element('p', empty); note.className = 'distill-empty'; target.append(note); }
  }
  async function load() {
    error.hidden = true; retry.disabled = true;
    recent.setAttribute('aria-busy', 'true');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const items = [];
      let offset = 0;
      do {
        const response = await fetch('/hfl-corpus/timeline/items?include_closed=true&offset=' + offset, {signal:controller.signal});
        if (!response.ok) throw Error('Actions unavailable');
        const data = await response.json();
        if (!Array.isArray(data.items)) throw Error('Invalid actions');
        items.push(...data.items); offset += data.items.length;
        if (!data.items.length || offset >= data.total) break;
      } while (true);
      const visible = items.filter(item => item.status !== 'dismissed');
      visible.sort((a, b) => (b.updated_at || b.created_at || '').localeCompare(a.updated_at || a.created_at || '') || a.id.localeCompare(b.id));
      render(recent, visible, 'No recent action cards yet. Open Kanban to create your first action.');
    } catch (_) {
      recent.replaceChildren(); error.hidden = false;
    } finally {
      clearTimeout(timeout); retry.disabled = false;
      recent.setAttribute('aria-busy', 'false');
    }
  }
  retry.addEventListener('click', load);
  load();
})();
