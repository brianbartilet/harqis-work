/* Shared, read-only action and idea overlays for every Memory Signal view. */
(() => {
  const panel = document.querySelector('[data-activity-panel]');
  if (!panel) return;
  let actions = {}, ideas = {};
  const labels = {open:'Active',in_progress:'In progress',incomplete:'Incomplete',done:'Done',historical:'Historical'};
  function paint() {
    panel.querySelectorAll('[data-activity-day]').forEach(cell => {
      const day = cell.dataset.activityDay, marker = actions[day];
      const count = new Set([...(marker?.planned || []), ...(marker?.actions || [])]).size;
      const status = marker?.dot_status || (count ? 'historical' : '');
      if (status) cell.dataset.timelineStatus = status; else delete cell.dataset.timelineStatus;
      cell.toggleAttribute('data-timeline-planned', Boolean(marker?.dot_status));
      cell.toggleAttribute('data-timeline-action', Boolean(marker?.actions?.length));
      if (ideas[day]) cell.dataset.ideaCount = ideas[day]; else delete cell.dataset.ideaCount;
      cell.dataset.indicatorLabel ||= cell.dataset.timelineLabel || cell.getAttribute('aria-label') || day;
      const label = cell.dataset.indicatorLabel + (count ? `; ${count} actions (${labels[status]})` : '') + (ideas[day] ? `; ${ideas[day]} ideas` : '');
      cell.title = label; cell.setAttribute('aria-label', label);
    });
  }
  window.HflActivityIndicators = {setActions(value) { actions = value || {}; paint(); }};
  let version = 0;
  async function load() {
    const ticket = ++version;
    const filters = panel.dataset.readonly === 'true' ? '' : window.location.search;
    const result = await Promise.allSettled(['/hfl-corpus/timeline/markers' + filters, '/hfl-corpus/timeline/ideas/snapshot'].map(async url => {
      const response = await fetch(url);
      if (!response.ok) throw Error('Indicators unavailable');
      return response.json();
    }));
    if (ticket !== version) return;
    if (result[0].status === 'fulfilled') actions = result[0].value.days || {};
    if (result[1].status === 'fulfilled') {
      ideas = {};
      for (const item of result[1].value.ideas || []) {
        if (item.status !== 'suggested') continue;
        const date = new Date(item.created_at);
        const captured = Number.isNaN(date.valueOf()) ? '' : new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
        for (const day of new Set([item.source_date, item.source?.date, captured].filter(Boolean))) ideas[day] = (ideas[day] || 0) + 1;
      }
    }
    panel.querySelector('[data-activity-indicators-error]').hidden = result.every(value => value.status === 'fulfilled');
    paint();
  }
  new MutationObserver(records => {
    if (records.some(record => record.addedNodes.length)) paint();
  }).observe(panel.querySelector('[data-activity-grid]'), {childList:true, subtree:true});
  window.addEventListener('hfl:actions-updated', load);
  window.addEventListener('hfl:ideas-updated', load);
  load();
})();
