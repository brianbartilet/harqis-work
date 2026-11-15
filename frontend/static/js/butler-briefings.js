/* Scheduled worker output stays separate from gateway conversation context. */
(() => {
  const $ = id => document.getElementById(id), panel = $('butler-panel');
  if (!panel) return;
  const tabs = ['briefings', 'conversation', 'settings'], list = $('butler-briefing-list');
  const error = $('butler-briefing-error'), refresh = $('butler-briefing-refresh');
  const demo = $('butler-briefing-demo-load');
  const csrf = JSON.parse($('butler-csrf').textContent);
  let timer, revision = 0, latest=null, request=null, disposed=false;
  const owner=JSON.parse(document.getElementById('butler-owner')?.textContent||'"owner"');
  const reviewKey='harqis:butler:reviewed:v1:'+owner;
  let reviewed={};try{const saved=JSON.parse(localStorage.getItem(reviewKey)||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))reviewed=saved;}catch{}
  const controls=text('div',undefined,'butler-update-controls'), agentFilter=document.createElement('select');
  agentFilter.setAttribute('aria-label','Briefing agent');agentFilter.className='butler-agent-filter';
  const showReviewed=text('button','Show reviewed');showReviewed.type='button';
  showReviewed.setAttribute('aria-pressed','false');
  const reviewAll=text('button','Mark all as reviewed');reviewAll.type='button';
  const reviewActions=text('div',undefined,'butler-review-actions');reviewActions.append(reviewAll,showReviewed);
  controls.append(reviewActions);list.before(controls);
  refresh.before(agentFilter);
  agentFilter.onchange=()=>{rendered='';if(latest)render(latest);};
  showReviewed.onclick=()=>{showReviewed.setAttribute('aria-pressed',String(showReviewed.getAttribute('aria-pressed')!=='true'));rendered='';if(latest)render(latest);};
  const updateKey=item=>{let hash=2166136261;for(const character of (item.title+' '+item.answer)){hash=Math.imul(hash^character.charCodeAt(0),16777619);}return item.id+':'+item.date+':'+item.state+':'+(hash>>>0);};

  const launch=$('butler-launch'), unreadStatus=text('span',undefined,'sr-only');
  unreadStatus.id='butler-unread-status';unreadStatus.setAttribute('role','status');
  launch.after(unreadStatus);
  const reviewable=item=>!['pending','queued','running'].includes(item.state);
  const matchesAgent=item=>!agentFilter.value||(item.agent_name||'HARQIS Butler')===agentFilter.value;
  reviewAll.onclick=()=>{for(const item of latest?.items||[]){if(matchesAgent(item)&&reviewable(item))reviewed[updateKey(item)]=Date.now();}try{localStorage.setItem(reviewKey,JSON.stringify(Object.fromEntries(Object.entries(reviewed).slice(-500))));}catch{}rendered='';render(latest);};
  function updateIndicator(){
    const count=(latest?.items||[]).filter(item=>reviewable(item)&&!reviewed[updateKey(item)]).length;
    launch.dataset.unread=String(count>0);
    const description=count?count+' unread '+(count===1?'briefing or agent update':'briefings or agent updates'):'';
    if(unreadStatus.textContent!==description)unreadStatus.textContent=description;
    launch.title=description||'Open HARQIS Butler';
    if(count)launch.setAttribute('aria-describedby',unreadStatus.id);else launch.removeAttribute('aria-describedby');
  }
  function reviewChanged(event){
    if(event.key!==reviewKey&&event.key!==null)return;
    try{const value=JSON.parse(localStorage.getItem(reviewKey)||'{}');reviewed=value&&typeof value==='object'&&!Array.isArray(value)?value:{};}catch{return;}
    updateIndicator();if(visible()&&latest){rendered='';render(latest);}
  }
  window.addEventListener('storage',reviewChanged);

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
    latest=data;
    updateIndicator();
    const chosen=agentFilter.value;
    agentFilter.replaceChildren(...['All agents',...new Set(data.items.map(item=>item.agent_name||'HARQIS Butler'))].map((name,index)=>{const option=text('option',name);option.value=index?name:'';return option;}));
    agentFilter.value=[...agentFilter.options].some(o=>o.value===chosen)?chosen:'';
    const visibleItems=data.items.filter(item=>(!agentFilter.value||(item.agent_name||'HARQIS Butler')===agentFilter.value)&&(showReviewed.getAttribute('aria-pressed')==='true'||!reviewed[updateKey(item)]));
    reviewAll.disabled=!data.items.some(item=>matchesAgent(item)&&reviewable(item)&&!reviewed[updateKey(item)]);
    const signature=JSON.stringify(visibleItems);

    if(signature===rendered)return;
    rendered=signature;
    const fragment = document.createDocumentFragment();
    for (const item of visibleItems) {
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
      meta.append(text('span',item.agent_name||'HARQIS Butler'),date);
      if(item.workspace_ids)meta.append(text('span',item.workspace_ids.length?'Linked to '+item.workspace_ids.length+' Space(s)':'All activity'));
      if (item.mock) meta.append(text('span', 'Mock', 'butler-briefing-mock'));
      card.append(meta);
      if (item.answer) {
        const answer=text('div', item.answer, 'butler-briefing-answer markdown-body');
        // HTML is sanitized by the shared server Markdown renderer.
        if(item.answer_html)answer.innerHTML=item.answer_html;
        card.append(answer);
      }
      if (item.detail) card.append(text('p', item.detail, 'butler-briefing-detail'));
      if(item.url){const link=text('a','Open source');link.href=item.url;card.append(link);}
      if(reviewable(item)){
        const acknowledge=text('button',reviewed[updateKey(item)]?'Mark unread':'Reviewed');acknowledge.type='button';acknowledge.className='butler-review-button';
        acknowledge.onclick=()=>{const key=updateKey(item);if(reviewed[key])delete reviewed[key];else reviewed[key]=Date.now();try{localStorage.setItem(reviewKey,JSON.stringify(Object.fromEntries(Object.entries(reviewed).slice(-500))));}catch{}rendered='';render(latest);};card.append(acknowledge);
      }
      fragment.append(card);
    }
    if (!visibleItems.length) {
      const empty = document.createElement('div');
      empty.className = 'butler-briefing-empty';
      empty.append(text('h3', 'No unread updates'), text('p', 'Use the calendar button above to set a schedule. Agent results also appear here. Change the agent filter or enable Show reviewed to see earlier updates.'));
      fragment.append(empty);
    }
    // Preserve reading position across worker-status refreshes.
    const scroll = list.scrollTop;
    list.replaceChildren(fragment);
    list.scrollTop = scroll;
    $('butler-briefing-demo').hidden = !data.demo_available;
  }
  async function load(samples = false) {
    if (disposed||document.hidden) return;
    const token = ++revision;
    request?.abort();request=new AbortController();
    clearTimeout(timer);
    if(visible()){
      refresh.disabled = demo.disabled = true;
      list.setAttribute('aria-busy', 'true');
      error.textContent = '';
      if (!list.childElementCount) list.append(text('p', 'Loading briefings…'));
    }
    let repeat = false;
    try {
      const response = await fetch('/agents/api/butler/briefings' + (samples ? '/demo' : ''), {
        method: samples ? 'POST' : 'GET', cache: 'no-store', signal:request.signal, headers: {'X-CSRF-Token': csrf}
      });
      if (!response.ok) throw Error('Briefings are unavailable. Try Refresh again.');
      const data = await response.json();
      if (token !== revision || document.hidden) return;
      latest=data;updateIndicator();
      if(visible()){render(data);error.textContent=data.updates_error||'';}
      repeat = data.items.some(item => !item.mock && ['pending', 'running'].includes(item.state));
    } catch (e) {
      if (token === revision && e.name!=='AbortError') {
        if(visible())error.textContent = e.message;
        if (list.textContent === 'Loading briefings…') list.replaceChildren();
        repeat = true;
      }
    } finally {
      if (token === revision) {
        refresh.disabled = demo.disabled = false;
        list.setAttribute('aria-busy', 'false');
        if (!document.hidden) timer = setTimeout(() => load(), visible()&&repeat?4000:30000);
      }
    }
  }
  function stop() {
    revision++;
    request?.abort();request=null;
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
    $('butler-briefing-subtitle').textContent = name === 'settings' ? 'Schedule your updates' : 'All activity · recent briefings and updates';
    for (const tab of tabs) {
      const selected = tab === name, button = tabButton(tab);
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      tabPane(tab).hidden = !selected;
    }
    panel.dispatchEvent(new Event('butler-tab-change'));
    if (focus) tabButton(name).focus();
    load();
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
  panel.addEventListener('butler-opened', () => load());
  panel.addEventListener('butler-closed', () => {stop();if(!document.hidden)timer=setTimeout(()=>load(),30000);});
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else load(); });
  window.addEventListener('pagehide',stop);
  window.addEventListener('pageshow',event=>{if(event.persisted)load();});
  window.addEventListener('hfl:view-replacing',()=>{disposed=true;stop();window.removeEventListener('storage',reviewChanged);},{once:true});
  select('briefings');
})();
