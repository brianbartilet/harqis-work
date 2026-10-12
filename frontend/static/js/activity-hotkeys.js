/* Shared activity shortcuts. Commands reuse the page's existing controls. */
(() => {
  const controller=new AbortController(), handlers=[];
  const query=selector=>document.querySelector(selector);
  const click=element=>{if(element&&!element.disabled&&!element.closest('[inert]'))element.click();};
  const named=(root,pattern)=>[...(root?.querySelectorAll('button')||[])].find(button=>pattern.test(button.textContent.trim()));
  function confirmCommand(button,label){
    if(!button||button.disabled)return;
    const dialog=document.createElement('dialog');dialog.className='context-help';
    const body=document.createElement('div');body.className='context-help-body';
    const title=document.createElement('h2');title.id='hotkey-confirm-title';title.textContent=label+'?';
    dialog.setAttribute('aria-labelledby',title.id);
    const cancel=document.createElement('button');cancel.textContent='Cancel';cancel.onclick=()=>dialog.close();
    const accept=document.createElement('button');accept.textContent=label;accept.onclick=()=>{dialog.close();click(button);};
    body.append(title,cancel,accept);dialog.append(body);document.body.append(dialog);
    const previous=document.activeElement;dialog.onclose=()=>{dialog.remove();previous?.focus();};dialog.showModal();cancel.focus();
  }
  window.HflHotkeys={register:handler=>handlers.push(handler),click,confirm:confirmCommand};
  window.addEventListener('hfl:view-replacing',()=>controller.abort(),{once:true});
  document.addEventListener('DOMContentLoaded',()=>{
    const board=query('[data-actions-page]'), graph=query('.kg-shell'), corpus=query('[data-corpus-index]');
    if((!board&&!graph&&!corpus)||graph?.dataset.readonly==='true')return;
    const pageKeys=board?[['i','Ideas drawer'],['a','Create Action'],['d','Create Idea'],['m','Multiselect (Ideas when drawer is open)'],['Space','Refresh']]:graph?[['a','Explore Activity Graph'],['e','Entities'],['f','Filters'],['b','Board guide'],['r','Refresh'],['Space','Reapply preset and refresh / Attach existing on a Board'],['p','Fit view'],['[','Zoom in'],[']','Zoom out'],['\\','Toggle fullscreen']]:[['e','Create Entry'],['a','Create Action'],['d','Create Idea'],['x','Secrets'],['t','Tags'],['m','Memory Signal'],['c','Manage categories'],['Space','Go to today']];
    const contextKeys=board?[['e','Edit'],['o','Done (confirm)'],['a','Agents'],['i','Dismiss (confirm)'],['c','Connections'],['h','History'],['x','Expand / collapse all sections and checklists']]:graph?[['t','Add thought'],['c','Connect on this board'],['n','Clone'],['d','Dismiss (confirm)'],['r','Promote'],['e','Edit'],['u','Use as starting point'],['o','Board connections'],['x','Clear selection'],['f','Focus connections / overview'],['Delete','Remove selected from board'],['↑ / ↓','Increase / decrease orb size']]:[];
    const dialog=document.createElement('dialog');dialog.className='context-help';dialog.id='activity-hotkey-help';dialog.setAttribute('aria-labelledby','activity-hotkey-title');
    const header=document.createElement('header');header.className='context-help-header';
    const title=document.createElement('h2');title.id='activity-hotkey-title';title.textContent='Keyboard shortcuts';
    const close=document.createElement('button');close.type='button';close.className='context-icon-button';close.setAttribute('aria-label','Close keyboard shortcuts');close.title='Close';close.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';close.onclick=()=>dialog.close();header.append(title,close);
    const body=document.createElement('div');body.className='context-help-body';
    for(const [heading,rows] of [['Page',[['k','Keyboard help'],...pageKeys,['n','Toggle Dynamic'],['Alt + `','All activity'],['Alt + 1–9','Select Space in picker order']]], [board?'Focused or hovered card':'Selected orb',contextKeys]]){
      if(!rows.length)continue;
      const h=document.createElement('h3');h.textContent=heading;body.append(h);
      const list=document.createElement('dl');list.className='activity-hotkey-list';
      for(const [key,label] of rows){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=label;list.append(dt,dd);}body.append(list);
    }
    const note=document.createElement('p');note.textContent='Card and orb commands take priority. Shortcuts pause while typing or using a dialog. Edit, Clone and Promote require one selected orb. Unavailable actions do nothing.';body.append(note);dialog.append(header,body);document.body.append(dialog);
    const help=document.createElement('button');help.type='button';help.className='activity-hotkey-trigger';help.setAttribute('aria-label','Keyboard shortcuts');help.title='Keyboard shortcuts (K)';help.setAttribute('aria-haspopup','dialog');help.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="3"/><path d="M6 9h2m3 0h2m3 0h2M6 12h2m3 0h2m3 0h2M7 15h10"/></svg>';
    if(board)query('[data-board-bulk]').before(help);
    else if(graph)query('#kg-animation-menu').before(help);
    else query('.corpus-navigation-actions .corpus-create-menu').before(help);
    let opener;help.onclick=()=>{opener=document.activeElement;dialog.showModal();close.focus();};dialog.onclose=()=>opener?.focus();
    document.addEventListener('keydown',event=>{
      if(event.defaultPrevented||event.repeat||event.isComposing||event.ctrlKey||event.metaKey||event.shiftKey||event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"]),.xterm,[role="textbox"]')||query('dialog[open]:not(#followups-board):not(#activity-standalone)'))return;
      const key=event.key.toLowerCase();
      if(event.altKey){if((key==='`'||event.code==='Backquote'||/^[1-9]$/.test(key))&&window.HflSelectSpace){event.preventDefault();window.HflSelectSpace(event.code==='Backquote'||key==='`'?0:Number(key));}return;}
      if(key==='k'){event.preventDefault();help.click();return;}
      if(board){
        const card=document.activeElement?.closest('[data-followup-id]')||query('[data-board-lanes] [data-followup-id]:hover');
        const labels={e:'Edit',o:'Done',a:'Agents',i:'Dismiss',c:'Connections',h:'History'};
        if(card&&(labels[key]||key==='x')){event.preventDefault();if(key==='x'){const sections=[...card.querySelectorAll('details')],toggles=[...card.querySelectorAll('.checklist-cover-toggle')],open=sections.some(el=>!el.open)||toggles.some(el=>el.getAttribute('aria-expanded')==='false');sections.forEach(el=>el.open=open);toggles.forEach(el=>{if((el.getAttribute('aria-expanded')==='true')!==open)click(el);});}else{const button=named(card,new RegExp('^'+labels[key]+'$'));if(key==='o'||key==='i')confirmCommand(button,labels[key]+' this action');else click(button);}return;}
        const selectors={i:'.ideas-drawer-toggle',a:'[data-board-create-action]',d:'[data-board-create-idea]',' ':'[data-board-refresh]',m:`[data-bulk-kind="${query('.ideas-drawer')?'idea':'action'}"] [data-bulk-toggle]`};
        if(selectors[key]){event.preventDefault();click(query(selectors[key]));return;}
      }
      for(const handler of handlers)if(handler(key,event)){event.preventDefault();return;}
      if(key==='n'){event.preventDefault();click(query('[data-dynamic-toggle]'));return;}
      if(corpus){
        const selectors={e:'[data-create-entry-open]',a:'[data-create-action-open]',x:'[data-secrets-toggle], [data-secrets-setup]',t:'[data-tag-cloud] > summary',m:'[data-activity-toggle]',c:'[data-memory-category-new]',' ':'[data-activity-today]'};
        if(key==='d'){event.preventDefault();window.dispatchEvent(new CustomEvent('hfl:create-idea'));}
        else if(selectors[key]){event.preventDefault();click(query(selectors[key]));}
      }
    },{signal:controller.signal});
  },{once:true});
})();
