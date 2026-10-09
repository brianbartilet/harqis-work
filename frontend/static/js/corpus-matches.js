(() => {
  if (window.corpusMatchesInitialized) return;
  window.corpusMatchesInitialized = true;
  const panelFor = event => event.detail.elt?.matches('[data-document-matches]') ? event.detail.elt : null;
  document.addEventListener('htmx:beforeRequest', event => {
    const panel = panelFor(event);
    if (!panel) return;
    if (!panel.open || panel.dataset.loaded === 'true' || panel.getAttribute('aria-busy') === 'true') {
      event.preventDefault();
      return;
    }
    panel.setAttribute('aria-busy', 'true');
    panel.querySelector('.matching-entry-results').textContent = 'Loading matching entries…';
  });
  document.addEventListener('htmx:afterRequest', event => {
    const panel = panelFor(event);
    if (!panel) return;
    panel.removeAttribute('aria-busy');
    if (event.detail.successful) {
      panel.dataset.loaded = 'true';
      return;
    }
    const content = panel.querySelector('.matching-entry-results');
    content.textContent = 'Matching entries could not be loaded. ';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'text-cyan-300 underline';
    retry.textContent = 'Retry';
    retry.addEventListener('click', () => window.htmx.trigger(panel, 'toggle'));
    content.append(retry);
  });
})();
