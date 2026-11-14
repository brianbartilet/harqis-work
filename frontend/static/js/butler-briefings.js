/* Scheduled worker output stays separate from gateway conversation context. */
(() => {
  const $ = id => document.getElementById(id), panel = $('butler-panel');
  if (!panel) return;
  const tabs = ['briefings', 'conversation', 'settings'], list = $('butler-briefing-list');
  const error = $('butler-briefing-error'), refresh = $('butler-briefing-refresh');
  const demo = $('butler-briefing-demo-load');
  const csrf = JSON.parse($('butler-csrf').textContent);
  let timer, revision = 0;
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const playback = document.createElement('button');
  playback.type = 'button'; playback.id = 'butler-briefing-playback';
  refresh.before(playback);
  let playing = !motion.matches, lastTick = 0, loopAt = 0, carry = 0, rendered = '';
  function playbackState() {
    playback.setAttribute('aria-label', playing ? 'Pause briefing playback' : 'Play briefing playback');
    playback.title = playback.getAttribute('aria-label');
    playback.setAttribute('aria-pressed', String(playing));
    playback.innerHTML = '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">' + (playing ? '<path d="M8 5v14M16 5v14"/>' : '<path d="m8 5 11 7-11 7Z"/>') + '</svg>';
  }
  function pause(){playing=false;playbackState();}
  playback.onclick=()=>{playing=!playing;lastTick=0;loopAt=0;playbackState();};
  motion.addEventListener('change',()=>{if(motion.matches)pause();});
  for(const event of ['wheel','touchstart','pointerdown','keydown'])list.addEventListener(event,pause,{passive:true});
  list.tabIndex=0;
  function tick(time){
    const elapsed=Math.min(100,time-(lastTick||time));lastTick=time;
    if(playing&&visible()&&!document.hidden&&list.scrollHeight>list.clientHeight){
      if(list.scrollTop+list.clientHeight>=list.scrollHeight-1){if(!loopAt)loopAt=time+2500;if(time>=loopAt){list.scrollTop=0;loopAt=0;}}
      else{carry+=elapsed*.018;const pixels=Math.floor(carry);if(pixels){list.scrollTop+=pixels;carry-=pixels;}loopAt=0;}
    }
    requestAnimationFrame(tick);
  }
  playbackState();requestAnimationFrame(tick);
  const visible = () => !panel.hidden && panel.dataset.tab === 'briefings';
  function text(tag, value, className) {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  }
  function render(data) {
    const signature=JSON.stringify(data.items);
    if(signature===rendered)return;
    rendered=signature;
    const fragment = document.createDocumentFragment();
    for (const item of data.items) {
      const card = document.createElement('article');
      card.className = 'butler-briefing-card';
      card.dataset.state = item.state;
      const header = document.createElement('div');
      header.className = 'butler-briefing-card-heading';
      header.append(text('h3', item.title));
      const status = text('span', item.state[0].toUpperCase() + item.state.slice(1), 'butler-briefing-status');
      header.append(status);
      card.append(header);
      const meta = document.createElement('div');
      meta.className = 'butler-briefing-meta';
      const date = text('time', item.date + (item.timezone ? ' · ' + item.timezone : ''));
      date.dateTime = item.date;
      meta.append(date);
      if (item.mock) meta.append(text('span', 'Mock', 'butler-briefing-mock'));
      card.append(meta);
      if (item.answer) {
        const answer=text('div', item.answer, 'butler-briefing-answer markdown-body');
        // HTML is sanitized by the shared server Markdown renderer.
        if(item.answer_html)answer.innerHTML=item.answer_html;
        card.append(answer);
      }
      if (item.detail) card.append(text('p', item.detail, 'butler-briefing-detail'));
      fragment.append(card);
    }
    if (!data.items.length) {
      const empty = document.createElement('div');
      empty.className = 'butler-briefing-empty';
      empty.append(text('h3', 'No briefings yet'), text('p', 'Use the calendar button above to set a schedule. Your worker’s updates will appear here.'));
      fragment.append(empty);
    }
    // Preserve reading position across worker-status refreshes.
    const scroll = list.scrollTop;
    list.replaceChildren(fragment);
    list.scrollTop = scroll;
    $('butler-briefing-demo').hidden = !data.demo_available;
  }
  async function load(samples = false) {
    if (!visible()) return;
    const token = ++revision;
    clearTimeout(timer);
    refresh.disabled = demo.disabled = true;
    list.setAttribute('aria-busy', 'true');
    error.textContent = '';
    if (!list.childElementCount) list.append(text('p', 'Loading briefings…'));
    let repeat = false;
    try {
      const response = await fetch('/agents/api/butler/briefings' + (samples ? '/demo' : ''), {
        method: samples ? 'POST' : 'GET', cache: 'no-store', headers: {'X-CSRF-Token': csrf}
      });
      if (!response.ok) throw Error('Briefings are unavailable. Try Refresh again.');
      const data = await response.json();
      if (token !== revision || !visible()) return;
      render(data);
      repeat = data.items.some(item => !item.mock && ['pending', 'running'].includes(item.state));
    } catch (e) {
      if (token === revision) {
        error.textContent = e.message;
        if (list.textContent === 'Loading briefings…') list.replaceChildren();
        repeat = true;
      }
    } finally {
      if (token === revision) {
        refresh.disabled = demo.disabled = false;
        list.setAttribute('aria-busy', 'false');
        if (visible() && repeat) timer = setTimeout(() => load(), 4000);
      }
    }
  }
  function stop() {
    revision++;
    clearTimeout(timer);
    refresh.disabled = demo.disabled = false;
    list.setAttribute('aria-busy', 'false');
  }
  const tabButton = name => $(name === 'settings' ? 'butler-briefings-open' : 'butler-tab-' + name);
  const tabPane = name => $(name === 'settings' ? 'butler-briefings' : 'butler-' + name + '-pane');
  function select(name, focus = false) {
    stop();
    panel.dataset.tab = name;
    $('butler-connection').hidden = name !== 'conversation';
    $('butler-briefing-subtitle').hidden = name === 'conversation';
    $('butler-briefing-subtitle').textContent = name === 'settings' ? 'Schedule your updates' : 'Scheduled worker updates';
    for (const tab of tabs) {
      const selected = tab === name, button = tabButton(tab);
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      tabPane(tab).hidden = !selected;
    }
    panel.dispatchEvent(new Event('butler-tab-change'));
    if (focus) tabButton(name).focus();
    if (name === 'briefings') load();
  }
  for (const [index, name] of tabs.entries()) {
    const button = tabButton(name);
    button.onclick = () => select(name);
    button.onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      select(event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs.at(-1) : tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length], true);
    };
  }
  panel.addEventListener('butler-view-request', event => { if (tabs.includes(event.detail)) select(event.detail, true); });
  refresh.onclick = () => load();
  demo.onclick = () => load(true);
  panel.addEventListener('butler-opened', () => { if (visible()) load(); });
  panel.addEventListener('butler-closed', stop);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else if (visible()) load(); });
  select('briefings');
})();
