/* Isolated documents preserve graph state while a child directory is open. */
(() => {
  if (window.activityModals) return;
  const embedded = window.parent !== window;
  const params = new URLSearchParams(location.search);
  const inherited = params.get('context') || '';
  let all = false;
  const scopeButton = document.querySelector('[data-activity-all]');
  const scopeText = document.querySelector('[data-activity-context]');
  function updateScope() {
    scopeButton?.setAttribute('aria-checked', String(all));
    if (scopeText) scopeText.textContent = all || !inherited ? 'All activity' : 'Following workspace and activity filters';
  }
  async function close() {
    try { await window.HflIdeas?.maps.flush(); }
    catch (error) { window.HflIdeas.maps.status.textContent='Not closed: '+error.message+' · Unsaved edits retained.'; return; }
    if (embedded) parent.postMessage({type:'hfl:activity-close'}, location.origin);
    else location.assign('/hfl-corpus' + (inherited ? '?' + inherited : ''));
  }
  function open(kind, context, extra = '', navigation = '') {
    const dialog = document.createElement('dialog'); dialog.className = 'activity-modal';
    dialog.setAttribute('aria-label', kind === 'graph' ? 'Activity Graph' : 'Activity Corpus Entities');
    const loading = document.createElement('div'); loading.className = 'activity-modal-loading';
    const status = document.createElement('span'); status.setAttribute('role','status'); status.textContent = 'Loading ' + (kind === 'graph' ? 'Activity Graph…' : 'Entities…');
    const button = document.createElement('button'); button.textContent = 'Close'; button.onclick = () => dialog.close();
    loading.append(status, button);
    const frame = document.createElement('iframe'); frame.title = dialog.getAttribute('aria-label');
    dialog.addEventListener('cancel',async event=>{
      event.preventDefault();
      try { await frame.contentWindow.HflIdeas?.maps.flush(); dialog.close(); }
      catch(error){const maps=frame.contentWindow.HflIdeas?.maps;if(maps?.status)maps.status.textContent='Not closed: '+error.message+' · Unsaved edits retained.';}
    });
    const url = new URL('/hfl-corpus/' + kind, location.origin);
    url.searchParams.set('embed','1'); if(context) url.searchParams.set('context',context);
    if(extra) url.searchParams.set('graph_filters',extra);
    const destination=new URLSearchParams(navigation);
    for(const key of ['board','select'])if(destination.has(key))url.searchParams.set(key,destination.get(key));
    frame.src = url;
    frame.onload = () => { loading.hidden = true; frame.contentWindow.focus(); };
    const listener = event => {
      if(event.origin === location.origin && event.source === frame.contentWindow && event.data?.type === 'hfl:activity-close') dialog.close();
    };
    window.addEventListener('message',listener);
    dialog.addEventListener('close',()=>{window.removeEventListener('message',listener);dialog.remove();});
    dialog.append(loading,frame);document.body.append(dialog);dialog.showModal();
    return dialog;
  }
  window.activityModals = {open, context:()=>all ? '' : inherited, isAll:()=>all,
    setAll:value=>{all=value===true;updateScope();},
    reset:()=>{all=false;updateScope();}};
  document.querySelector('[data-activity-close]')?.addEventListener('click',close);
  document.getElementById('activity-standalone')?.addEventListener('cancel',event=>{event.preventDefault();close();});
  scopeButton?.addEventListener('click',()=>{all=!all;updateScope();window.dispatchEvent(new Event('hfl:activity-scope'));});
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape' && !event.defaultPrevented && !document.querySelector('dialog[open]') && document.querySelector('[data-activity-close]')) {event.preventDefault();close();}
  });
  document.addEventListener('click',event=>{
    const link = event.target.closest('a[href]');
    if(!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
    const url = new URL(link.href,location.href);
    if(url.origin !== location.origin || !['/hfl-corpus/graph','/hfl-corpus/entities'].includes(url.pathname)) return;
    if(link.id === 'kg-entities') return; // Graph supplies its applied filters.
    event.preventDefault();
    document.querySelector('.corpus-tools')?.removeAttribute('open');
    const navigation=url.searchParams.has('board')||url.searchParams.has('select');
    open(url.pathname.endsWith('/graph')?'graph':'entities',navigation?'':(document.querySelector('#corpus-search-form') ? location.search.slice(1) : window.activityModals.context()),'',navigation?url.search:'');
  });
  updateScope();
})();
