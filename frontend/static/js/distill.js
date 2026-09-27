/* A read-only starting point; editing and execution stay in the existing tools. */
(() => {
  const root = document.querySelector('[data-distill]');
  if (!root) return;
  const recent = root.querySelector('[data-distill-recent]');
  const important = root.querySelector('[data-distill-important]');
  const error = root.querySelector('[data-distill-error]');
  const retry = root.querySelector('[data-distill-retry]');
  const element = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
  function render(target, items, empty) {
    target.replaceChildren();
    for (const item of items.slice(0, 3)) {
      const link = document.createElement('a'); link.className = 'distill-action';
      link.href = '/hfl-corpus/actions?' + new URLSearchParams({edit_kind: 'actionable', edit: item.id});
      link.append(element('strong', item.title), element('p', item.expected_outcome || 'Open this action to choose its next step.'));
      const status = {open:'Ready', active:'Active', in_progress:'In progress', incomplete:'Needs follow-up'}[item.status] || item.status;
      link.append(element('small', status + (item.due_date ? ' · ' + (item.overdue ? 'Overdue ' : 'Due ') + item.due_date : '') ));
      target.append(link);
    }
    if (!items.length) { const note = element('p', empty); note.className = 'distill-empty'; target.append(note); }
  }
  async function load() {
    error.hidden = true; retry.disabled = true;
    [recent, important].forEach(node => node.setAttribute('aria-busy', 'true'));
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const items = [];
      let offset = 0;
      do {
        const response = await fetch('/hfl-corpus/timeline/items?offset=' + offset, {signal:controller.signal});
        if (!response.ok) throw Error('Actions unavailable');
        const data = await response.json();
        if (!Array.isArray(data.items)) throw Error('Invalid actions');
        items.push(...data.items); offset += data.items.length;
        if (!data.items.length || offset >= data.total) break;
      } while (true);
      const open = items.filter(item => !['done', 'dismissed'].includes(item.status));
      open.sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''));
      render(recent, open, 'Start with one useful outcome. Open Kanban to create your first action.');
      render(important, open.filter(item => item.matrix === 'Q2'), 'No Q2 actions yet. In Kanban, mark important, non-urgent work as Q2 to make space for it here.');
    } catch (_) {
      recent.replaceChildren(); important.replaceChildren(); error.hidden = false;
    } finally {
      clearTimeout(timeout); retry.disabled = false;
      [recent, important].forEach(node => node.setAttribute('aria-busy', 'false'));
    }
  }
  retry.addEventListener('click', load);
  load();
})();
