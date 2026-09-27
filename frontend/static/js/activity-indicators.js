/* Shared, read-only action status overlays for every Memory Signal view. */
(() => {
  let panel = document.querySelector('[data-activity-panel]');
  if (!panel) return;
  let actions = {};
  const labels = {open:'Active',in_progress:'In progress',incomplete:'Incomplete',done:'Done'};
  function paint() {
    panel.querySelectorAll('[data-activity-day]').forEach(cell => {
      const day = cell.dataset.activityDay, marker = actions[day];
      const count = new Set([...(marker?.planned || []), ...(marker?.actions || [])]).size;
      const status = marker?.dot_status || '';
      if (status) cell.dataset.timelineStatus = status; else delete cell.dataset.timelineStatus;
      cell.toggleAttribute('data-timeline-planned', Boolean(marker?.dot_status));
      cell.toggleAttribute('data-timeline-action', Boolean(marker?.actions?.length));
      cell.dataset.indicatorLabel ||= cell.dataset.timelineLabel || cell.getAttribute('aria-label') || day;
      const label = cell.dataset.indicatorLabel + (count ? `; ${count} actions${status ? ' (' + labels[status] + ')' : ''}` : '');
      cell.title = label; cell.setAttribute('aria-label', label);
    });
  }
  window.HflActivityIndicators = {setActions(value) { actions = value || {}; paint(); }};
  let version = 0;
  async function load() {
    const ticket = ++version;
    const filters = panel.dataset.readonly === 'true' ? '' : window.location.search;
    const result = await Promise.allSettled(['/hfl-corpus/timeline/markers' + filters].map(async url => {
      const response = await fetch(url);
      if (!response.ok) throw Error('Indicators unavailable');
      return response.json();
    }));
    if (ticket !== version) return;
    if (result[0].status === 'fulfilled') actions = result[0].value.days || {};
    panel.querySelector('[data-activity-indicators-error]').hidden = result.every(value => value.status === 'fulfilled');
    paint();
  }
  const observer = new MutationObserver(records => {
    if (records.some(record => record.addedNodes.length)) paint();
  });
  observer.observe(panel.querySelector('[data-activity-grid]'), {childList:true, subtree:true});
  window.addEventListener('hfl:activity-refreshed', () => {
    observer.disconnect();
    panel = document.querySelector('[data-activity-panel]');
    observer.observe(panel.querySelector('[data-activity-grid]'), {childList:true, subtree:true});
    load();
  });
  window.addEventListener('hfl:actions-updated', load);
  load();
})();
