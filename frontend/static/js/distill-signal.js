/* Read-only Corpus overview: cells never link, select dates, or open editors. */
(() => {
  const root = document.querySelector('[data-distill-signal]');
  if (!root) return;
  const find = name => root.querySelector(`[data-signal-${name}]`);
  const grid = find('grid'), summary = find('summary'), error = find('error');
  const currentYear = new Date().getFullYear();
  let year = currentYear, controller;
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  const toggle = find('toggle');
  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.setAttribute('aria-label', `${expanded ? 'Collapse' : 'Expand'} activity heatmap`);
    document.getElementById('distill-signal-body').hidden = !expanded;
  });
  async function load() {
    controller?.abort();
    const request = new AbortController(); controller = request;
    const timeout = setTimeout(() => request.abort(), 15000);
    grid.replaceChildren(); grid.setAttribute('aria-busy', 'true');
    error.hidden = true; summary.textContent = 'Loading activity…';
    find('year').textContent = year;
    find('next').disabled = year >= currentYear;
    try {
      const response = await fetch(`/distill/memory-signal?year=${year}`, {signal: request.signal});
      if (!response.ok) throw Error('Activity unavailable');
      const data = await response.json();
      if (controller !== request) return;
      summary.textContent = `${data.total.toLocaleString()} ${data.total === 1 ? 'entry' : 'entries'} in ${data.year}`;
      const labels = node('div', null, 'distill-signal-week distill-signal-days');
      ['', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', ''].forEach(day => labels.append(node('span', day)));
      grid.append(labels);
      for (const week of data.weeks) {
        const column = node('div', null, 'distill-signal-week');
        column.append(node('span', week.month, 'distill-signal-month'));
        for (const day of week.days) {
          const cell = node('span', null, day.in_year ? 'distill-signal-cell' : 'distill-signal-blank');
          if (day.in_year) {
            cell.dataset.level = day.level;
            cell.dataset.today = day.is_today;
            cell.dataset.future = day.is_future;
            cell.title = day.label;
            cell.setAttribute('role', 'img');
            cell.setAttribute('aria-label', day.label);
          }
          column.append(cell);
        }
        column.append(node('span', week.show_week ? String(week.week).padStart(2, '0') : '', 'distill-signal-week-number'));
        grid.append(column);
      }
    } catch (_) {
      if (controller !== request) return;
      summary.textContent = 'Activity unavailable'; error.hidden = false;
    } finally {
      clearTimeout(timeout);
      if (controller === request) grid.setAttribute('aria-busy', 'false');
    }
  }
  find('previous').addEventListener('click', () => { year--; load(); });
  find('next').addEventListener('click', () => { if (year < currentYear) { year++; load(); } });
  find('current').addEventListener('click', () => { year = currentYear; load(); });
  find('retry').addEventListener('click', load);
  load();
})();
