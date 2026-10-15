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
        const tags = document.createElement('div'); tags.className = 'corpus-feed-tags';
        for (const tag of entry.tags || []) {
          const chip = document.createElement('span'); chip.textContent = '#' + tag; tags.append(chip);
        }
        const meta = document.createElement('p'); meta.className = 'corpus-feed-source';
        if (entry.source) {
          meta.append('Source: ');
          const badge = document.createElement('span'); badge.textContent = entry.source; meta.append(badge);
        }
        const body = document.createElement('div'); body.className = 'markdown-body'; body.innerHTML = entry.html;
        const locations = document.createElement('section'); locations.className = 'corpus-feed-locations';
        const locationHeading = document.createElement('h4'); locationHeading.textContent = 'Location';
        const locationLinks = new Set();
        const attachments = document.createElement('div'); attachments.className = 'corpus-feed-attachments';
        for (const attachment of entry.attachments || []) {
          let locationUrl;
          try {
            const candidate = new URL(attachment.href);
            if (candidate.protocol === 'https:' && ['openstreetmap.org', 'www.openstreetmap.org'].includes(candidate.hostname)) locationUrl = candidate;
          } catch (_) { /* Other attachment types use local URLs. */ }
          if (locationUrl) {
            if (locationLinks.has(locationUrl.href)) continue;
            locationLinks.add(locationUrl.href);
            if (!locations.childElementCount) locations.append(locationHeading);
            const hash = locationUrl.hash.match(/^#map=\d+(?:\.\d+)?\/(-?\d+(?:\.\d+)?)\/(-?\d+(?:\.\d+)?)/);
            const latText = locationUrl.searchParams.get('mlat') ?? hash?.[1];
            const lonText = locationUrl.searchParams.get('mlon') ?? hash?.[2];
            const lat = Number(latText), lon = Number(lonText);
            if (latText && lonText && Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
              const map = document.createElement('iframe'); map.title = 'Location map'; map.loading = 'lazy';
              map.referrerPolicy = 'no-referrer';
              const bbox = [Math.max(-180, lon-.006), Math.max(-90, lat-.004), Math.min(180, lon+.006), Math.min(90, lat+.004)];
              const query = new URLSearchParams({bbox:bbox.join(','), layer:'mapnik', marker:lat + ',' + lon});
              map.src = 'https://www.openstreetmap.org/export/embed.html?' + query;
              locations.append(map);
            }
            const locationLink = document.createElement('a'); locationLink.href = locationUrl.href;
            locationLink.target = '_blank'; locationLink.rel = 'noopener noreferrer';
            locationLink.textContent = 'Open in OpenStreetMap'; locations.append(locationLink);
            continue;
          }
          const figure = document.createElement('figure');
          const download = document.createElement('a'); download.href = attachment.href;
          download.textContent = attachment.label;
          if (attachment.kind === 'external') { download.target = '_blank'; download.rel = 'noopener noreferrer'; }
          else { download.setAttribute('download', ''); download.textContent = 'Download ' + attachment.label; }
          if (['image', 'video', 'audio'].includes(attachment.kind) && attachment.media_url) {
            const media = document.createElement(attachment.kind === 'image' ? 'img' : attachment.kind);
            if (attachment.kind === 'image') { media.alt = attachment.label; media.loading = 'lazy'; media.decoding = 'async'; }
            else { media.controls = true; media.preload = 'none'; media.setAttribute('aria-label', attachment.label); if (attachment.kind === 'video') media.playsInline = true; }
            const fallback = document.createElement('p'); fallback.className = 'corpus-feed-meta'; fallback.hidden = true;
            fallback.textContent = 'Preview unavailable. Download the file to open it.';
            media.addEventListener('error', () => { media.hidden = true; fallback.hidden = false; });
            media.src = attachment.media_url;
            if (attachment.kind === 'video') {
              const frame = document.createElement('div'); frame.className = 'corpus-feed-video';
              const poster = document.createElement('img'); poster.className = 'corpus-feed-video-poster';
              poster.alt = ''; poster.loading = 'lazy'; poster.decoding = 'async';
              poster.src = attachment.media_url.replace(/\/media$/, '/thumbnail');
              poster.addEventListener('error', () => { poster.hidden = true; });
              const play = document.createElement('button'); play.type = 'button'; play.className = 'corpus-feed-video-play';
              play.setAttribute('aria-label', 'Play ' + attachment.label);
              play.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
              media.controls = false;
              const reveal = () => { poster.hidden = true; play.hidden = true; media.controls = true; };
              media.addEventListener('play', () => {
                items.querySelectorAll('video').forEach(other => {
                  if (other !== media) other.pause();
                });
                reveal();
              });
              play.addEventListener('click', async () => {
                reveal(); media.focus();
                try { await media.play(); }
                catch (_) {
                  if (!media.error) { play.hidden = false; media.controls = false; }
                }
              });
              media.addEventListener('error', () => { frame.hidden = true; });
              frame.append(media, poster, play); figure.append(frame, fallback);
            } else {
              figure.append(media, fallback);
            }
          }
          const caption = document.createElement('figcaption');
          if (['image', 'video'].includes(attachment.kind)) {
            caption.className = 'corpus-feed-media-download';
            download.textContent = 'Download';
            download.setAttribute('aria-label', 'Download ' + attachment.label);
            download.title = attachment.label;
          }
          caption.append(download); figure.append(caption); attachments.append(figure);
        }
        const link = document.createElement('a'); link.href = entry.href; link.textContent = 'Open entry'; link.target = '_blank'; link.rel = 'noopener';
        const header = document.createElement('header'); header.className = 'corpus-feed-card-header';
        header.append(heading, link);
        card.append(header, tags, meta, body, locations, attachments); items.append(card);
      }
      cursor = data.next_cursor; ended = !cursor;
      find('[data-feed-summary]').textContent = `${seen.size} of ${data.total} entries matched from applied filters`;
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
  dialog.addEventListener('close', () => { items.querySelectorAll('video,audio').forEach(media => media.pause()); generation++; controller?.abort(); loading = false; open.focus(); });
  more.onclick = () => load();
  order.onclick = () => {
    order.value = order.value === 'desc' ? 'asc' : 'desc';
    const newest = order.value === 'desc';
    find('[data-feed-order-label]').textContent = newest ? 'Newest' : 'Oldest';
    find('[data-feed-order-arrow]').style.transform = newest ? '' : 'rotate(180deg)';
    order.title = newest ? 'Switch to oldest first' : 'Switch to newest first';
    order.setAttribute('aria-label', (newest ? 'Newest first. ' : 'Oldest first. ') + order.title);
    load(true);
  };
  find('[data-feed-save]').onclick = () => {
    document.dispatchEvent(new CustomEvent('corpus:save-feed-space', {detail:{params:Object.fromEntries(params), sort:order.value}}));
  };
  window.addEventListener('hfl:view-replacing', () => { generation++; controller?.abort(); observer.disconnect(); }, {once:true});
})();
