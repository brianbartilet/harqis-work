(() => {
  const splash = document.getElementById('brain-page-loading');
  const main = document.querySelector('#agent-fleet, #hud-surface, #kanban-surface');
  let timer;
  function show(message) {
    clearTimeout(timer);
    document.getElementById('brain-page-loading-message').textContent = message;
    document.getElementById('brain-page-loading-slow').hidden = true;
    splash.hidden = false;
    main.inert = true;
    main.setAttribute('aria-busy', 'true');
    timer = setTimeout(() => { document.getElementById('brain-page-loading-slow').hidden = false; }, 20000);
  }
  function finish() {
    clearTimeout(timer);
    splash.hidden = true;
    main.inert = false;
    main.setAttribute('aria-busy', 'false');
  }
  window.BrainPageLoading = {show, finish};
  show(document.getElementById('brain-page-loading-message').textContent);
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
    const url = new URL(link.href, location.href);
    if (url.origin === location.origin && ['/agents', '/second-brain', '/hfl-corpus/actions'].includes(url.pathname)) {
      show(url.pathname === '/agents' ? 'Opening your workspace...' : url.pathname === '/hfl-corpus/actions' ? 'Opening your Kanban...' : 'Opening your dashboard...');
    }
  });
  window.addEventListener('pageshow', event => { if (event.persisted) finish(); });
})();
