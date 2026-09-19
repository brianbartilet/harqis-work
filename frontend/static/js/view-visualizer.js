(() => {
  const dialog = document.getElementById('view-visualizer');
  const trigger = document.querySelector('[data-visualize-open]');
  if (!dialog || !trigger) return;
  const find = selector => dialog.querySelector(selector);
  const grid = find('[data-visualize-grid]'), detail = find('[data-visualize-detail]');
  const status = find('[data-visualize-status]'), retry = find('[data-visualize-retry]');
  let snapshot, timer, weekStart, displayedDate, loading = false;
  const minutes = value => Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
  const time = value => `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  const dateAt = offset => new Date(weekStart + offset * 86400000).toISOString().slice(0, 10);
  const node = (tag, text, className) => {
    const el = document.createElement(tag); if (text !== undefined) el.textContent = text;
    if (className) el.className = className; return el;
  };
  function localNow() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
      timeZone:snapshot.preferences.timezone, year:'numeric', month:'2-digit', day:'2-digit',
      hour:'2-digit', minute:'2-digit', hourCycle:'h23',
    }).formatToParts(new Date()).map(part => [part.type, part.value]));
    return {date:`${parts.year}-${parts.month}-${parts.day}`, minute:Number(parts.hour) * 60 + Number(parts.minute)};
  }
  function showDetail(segment) {
    const {view, block, origin} = segment;
    grid.querySelectorAll('.visualizer-block').forEach(el => el.setAttribute('aria-pressed', String(el === segment.button)));
    detail.replaceChildren(); detail.hidden = false;
    const title = node('h3', view.name); title.style.borderLeft = `4px solid ${view.color}`;
    detail.append(title, node('p', `${dateAt(origin)} ${block.start} → ${dateAt(origin + (block.end < block.start ? 1 : 0))} ${block.end} · ${snapshot.preferences.timezone}`));
    const state = view.state, list = node('dl');
    const fields = [ ['Sources', state.source || 'All sources'], ['Search and tags', state.q || 'No restriction'],
      ['Date type', {created:'Document created', updated:'Document updated', entry:'Entry date'}[state.date_field]],
      ['Date range', state.rolling ? `Last ${state.rolling} days (rolling)` : `${state.date_from || 'Any date'} → ${state.date_to || 'Any date'}`] ];
    for (const [label, value] of fields) list.append(node('dt', label), node('dd', value));
    const edit = node('button', 'Edit view'); edit.type = 'button';
    edit.onclick = () => { dialog.close(); document.dispatchEvent(new CustomEvent('corpus:edit-scheduled-view', {detail:view.id})); };
    detail.append(list, edit); detail.focus({preventScroll:true}); detail.scrollIntoView({block:'nearest'});
  }
  function render() {
    const now = localNow(), today = Date.parse(now.date + 'T00:00:00Z');
    displayedDate = now.date; weekStart = today - ((new Date(today).getUTCDay() + 6) % 7) * 86400000;
    grid.replaceChildren(); detail.hidden = true;
    const days = Array.from({length:7}, () => []);
    for (const view of snapshot.views) for (const block of view.schedule || []) for (const day of block.days) {
      const start = minutes(block.start), end = minutes(block.end);
      days[day].push({view, block, origin:day, start, end:end > start ? end : 1440});
      if (end < start && end > 0) days[(day + 1) % 7].push({view, block, origin:day === 6 ? -1 : day, start:0, end});
    }
    grid.append(node('div', 'Time', 'visualizer-corner'));
    const names = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
    names.forEach((name, day) => {
      const heading = node('div', `${name} ${dateAt(day).slice(8)}`, 'visualizer-day-heading');
      heading.dataset.date = dateAt(day); if (dateAt(day) === now.date) heading.setAttribute('aria-current', 'date');
      grid.append(heading);
    });
    const hours = node('div', undefined, 'visualizer-hours');
    for (let hour=0; hour<24; hour++) { const label = node('span', time(hour*60)); label.style.top = `${hour*48}px`; hours.append(label); }
    grid.append(hours);
    days.forEach((segments, day) => {
      const column = node('div', undefined, 'visualizer-day'); column.dataset.date = dateAt(day);
      column.setAttribute('aria-label', `${names[day]} ${dateAt(day)}`);
      segments.sort((a,b) => a.start-b.start || b.end-a.end);
      // Longer periods form the background. Identical periods share equal lanes;
      // shorter periods are inset above them, leaving longer blocks selectable.
      let group = [], groupEnd = -1;
      function placeGroup() {
        const periods = new Map();
        for (const segment of group) {
          const key = `${segment.start}:${segment.end}`;
          if (!periods.has(key)) periods.set(key, []);
          periods.get(key).push(segment);
        }
        const layers = [...periods.values()].sort((a,b) =>
          (b[0].end-b[0].start)-(a[0].end-a[0].start) || a[0].start-b[0].start);
        layers.forEach((peers, layer) => {
          const first = peers[0];
          const underneath = layers.slice(0,layer).filter(items => items[0].start < first.end && first.start < items[0].end).length;
          const inset = Math.min(underneath * 12, 36);
          peers.forEach((segment, lane) => {
            const button = node('button', undefined, 'visualizer-block'); button.type = 'button'; segment.button = button;
            button.style.cssText = `top:${segment.start*.8}px;height:${Math.max(20,(segment.end-segment.start)*.8)}px;left:calc(${inset + lane*(100-inset)/peers.length}% + 2px);width:calc(${(100-inset)/peers.length}% - 4px);z-index:${layer+1};--view-color:${segment.view.color}`;
            const labelContent = node('span', undefined, 'visualizer-block-label');
            labelContent.append(node('strong', segment.view.name), node('span', `${segment.block.start}–${segment.block.end}`));
            button.append(labelContent);
            const label = `${segment.view.name}, ${dateAt(segment.origin)} ${segment.block.start} to ${dateAt(segment.origin + (segment.block.end < segment.block.start ? 1 : 0))} ${segment.block.end}`;
            button.title = label; button.setAttribute('aria-label', label); button.setAttribute('aria-pressed', 'false');
            button.onclick = () => showDetail(segment); column.append(button);
          });
        });
      }
      for (const segment of segments) {
        if (segment.start >= groupEnd) { placeGroup(); group=[]; groupEnd=-1; }
        group.push(segment); groupEnd=Math.max(groupEnd, segment.end, segment.start+25);
      }
      placeGroup(); grid.append(column);
    });
    status.textContent = snapshot.preferences.dynamic ? 'Dynamic ON' : 'Dynamic OFF';
    status.dataset.on = String(snapshot.preferences.dynamic);
    status.title = snapshot.preferences.dynamic ? 'Schedules apply automatically. Gaps show all entries.' : 'Schedule preview only. Enable Dynamic mode to apply schedules.';
    find('[data-visualize-empty]').hidden = days.some(day => day.length);
    updateClock();
  }
  function updateClock() {
    if (!snapshot || !dialog.open) return;
    const now = localNow();
    if (now.date !== displayedDate) { render(); return; }
    find('[data-visualize-zone]').textContent = `${snapshot.preferences.timezone} · ${now.date} · ${time(now.minute)}`;
    grid.querySelectorAll('.visualizer-now').forEach(el => el.remove());
    const day = [...grid.querySelectorAll('.visualizer-day')].find(el => el.dataset.date === now.date);
    if (day) { const line = node('div', undefined, 'visualizer-now'); line.style.top = `${now.minute*.8}px`; line.setAttribute('aria-label', `Current time ${time(now.minute)}`); day.append(line); }
  }
  async function load() {
    if (loading) return;
    loading=true; status.textContent='Loading schedules…'; retry.hidden=true; dialog.setAttribute('aria-busy','true');
    try {
      const response = await fetch('/hfl-corpus/workspace-views', {cache:'no-store', signal:AbortSignal.timeout(15000)});
      if (!response.ok || response.redirected) throw Error();
      snapshot=await response.json(); if (!dialog.open) return; render();
      find('.visualizer-scroll').scrollTop=Math.max(0, localNow().minute*.8-100);
      clearInterval(timer); timer=setInterval(updateClock, 30000);
    } catch (_) { status.textContent='Schedules could not load. Retry or reopen the dialog.'; retry.hidden=false; }
    finally { loading=false; dialog.removeAttribute('aria-busy'); }
  }
  trigger.onclick = () => { document.querySelector('[data-workspace-menu]').open=false; dialog.showModal(); find('#view-visualizer-title').focus(); load(); };
  retry.onclick=load; find('[data-visualize-close]').onclick=() => dialog.close();
  let backdropPress = false;
  const outsideDialog = event => {
    const box = dialog.getBoundingClientRect();
    return event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom;
  };
  dialog.addEventListener('pointerdown', event => { backdropPress = event.target === dialog && outsideDialog(event); });
  dialog.addEventListener('click', event => {
    if (backdropPress && event.target === dialog && outsideDialog(event)) dialog.close();
    backdropPress = false;
  });
  dialog.addEventListener('close', () => { clearInterval(timer); document.querySelector('[data-workspace-menu]').open=true; trigger.focus(); });
})();
