/* Read the applied result scope, not unsent form edits. */
(() => {
  const open = document.querySelector('[data-curated-feed-open]');
  const dialog = document.querySelector('[data-curated-feed]');
  if (!open || !dialog) return;
  const find = selector => dialog.querySelector(selector);
  const scroller = find('[data-feed-scroll]'), items = find('[data-feed-items]');
  const status = find('[data-feed-status]'), more = find('[data-feed-more]'), order = find('[data-feed-order]');
  const form = document.getElementById('corpus-search-form');
  const params = new URLSearchParams(location.search);
  // Initial page context can contain restored filters not present in the URL.
  for (const key of ['q','source','date_field','date_from','date_to','rolling','scope','show_secrets']) {
    if (!params.has(key) && form.elements[key]) params.set(key, form.elements[key].value);
  }
  const meaningful = state => ['q','source','date_from','date_to'].some(key => String(state[key] || '').trim()) || Number(state.rolling || 0) > 0 || !!state.entry_scope;
  let scope;
  try { scope = JSON.parse(params.get('scope') || '{"any":[]}'); } catch (_) { scope = {any:[]}; }
  open.disabled = !(meaningful(Object.fromEntries(params)) || scope.any?.some(meaningful) || meaningful(scope.all || {}));
  let controller, cursor = null, loading = false, ended = false, generation = 0, seen = new Set();
  async function load(reset = false) {
    if (!dialog.open || (loading && !reset) || (ended && !reset)) return;
    if (reset) {
      controller?.abort(); generation++; cursor = null; ended = false; seen = new Set(); items.replaceChildren(); scroller.scrollTop = 0;
    }
    const current = generation;
    controller = new AbortController(); const activeController = controller; loading = true; more.hidden = true;
    status.textContent = 'Loading entries…'; items.setAttribute('aria-busy', 'true');
    const query = new URLSearchParams(params);
    query.delete('page_size'); query.delete('page'); query.set('order', order.value);
    if (cursor) query.set('cursor', cursor); else query.delete('cursor');
    const timeout = setTimeout(() => activeController.abort(), 30000);
    try {
      const response = await fetch('/hfl-corpus/curated-feed?' + query, {signal:controller.signal, cache:'no-store'});
      const data = await response.json();
      if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Could not load entries. Try again.');
      if (current !== generation || !dialog.open) return;
      for (const entry of data.entries) {
        if (seen.has(entry.id)) continue;
        seen.add(entry.id);
        const card = document.createElement('article'); card.className = 'corpus-feed-card';
        const heading = document.createElement('h3'); heading.textContent = entry.title;
        const meta = document.createElement('p'); meta.className = 'corpus-feed-meta'; meta.textContent = [entry.date?.replace('T', ' ') || 'Undated', entry.source].filter(Boolean).join(' · ');
        const body = document.createElement('div'); body.className = 'markdown-body'; body.innerHTML = entry.html;
        const link = document.createElement('a'); link.href = entry.href; link.textContent = 'Open original entry'; link.target = '_blank'; link.rel = 'noopener';
        card.append(heading, meta, body, link); items.append(card);
      }
      cursor = data.next_cursor; ended = !cursor;
      find('[data-feed-summary]').textContent = `${seen.size} of ${data.total} matching entries`;
      status.textContent = !seen.size ? 'No entries match these filters.' : ended ? 'You’ve reached the end.' : 'Scroll for more entries.';
      more.textContent = 'Load more'; more.hidden = ended;
    } catch (error) {
      if (current !== generation || !dialog.open) return;
      status.textContent = error.name === 'AbortError' ? 'Loading timed out. Try again.' : error.message;
      more.textContent = 'Retry'; more.hidden = false;
    } finally {
      clearTimeout(timeout);
      if (current === generation) { loading = false; items.removeAttribute('aria-busy'); }
    }
  }
  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting) && more.textContent !== 'Retry') load();
  }, {root:scroller, rootMargin:'250px'});
  observer.observe(more);
  open.onclick = () => { if (!open.disabled) { dialog.showModal(); find('[data-feed-close]').focus(); load(true); } };
  find('[data-feed-close]').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { generation++; controller?.abort(); loading = false; open.focus(); });
  more.onclick = () => load();
  order.onchange = () => load(true);
  find('[data-feed-save]').onclick = () => {
    document.dispatchEvent(new CustomEvent('corpus:save-feed-space', {detail:{params:Object.fromEntries(params), sort:order.value}}));
  };
  window.addEventListener('hfl:view-replacing', () => { generation++; controller?.abort(); observer.disconnect(); }, {once:true});
})();
