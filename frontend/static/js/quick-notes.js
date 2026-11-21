/* Shared checklist UI. Drafts survive failed saves; revisions prevent lost updates. */
(() => {
  const $=id=>document.getElementById(id), dialog=$('quick-notes-dialog');
  if(!dialog)return;
  const noteDialog=$('qn-note-dialog'), grid=$('qn-grid'), editor=$('qn-editor'), panel=$('butler-panel'), butler=$('butler-notes-list');
  const csrf=JSON.parse($('butler-csrf').textContent), base='/hfl-corpus/quick-notes';
  const lineDrafts=new Set(), notes=new Map(), dirty=new Set(), versions=new Map(), references=new Map();
  let selected=null, showArchived=false, loading=0, timer, saving=null, conflict=false, dragging=null, spaces=[], opener;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const button=(label,run,cls)=>{const b=el('button',label,cls);b.type='button';b.onclick=run;return b;};
  function iconButton(label,path,run){const b=button('',run,'qn-card-icon');b.title=label;b.setAttribute('aria-label',label);b.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'+path+'"/></svg>';return b;}

  function status(message,error=false){$('qn-status').textContent=message;$('qn-status').dataset.error=String(error);$('qn-retry').hidden=!error;$('qn-reload').hidden=!conflict;const s=$('butler-notes-status');if(s)s.textContent=message;}
  async function api(url,method='GET',body){const r=await fetch(url,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok){if(r.status===409)conflict=true;throw Error(typeof data.detail==='string'?data.detail:'Unable to save Quick Notes. Check the connection and retry.');}return data;}
  const payload=n=>({title:n.title,items:n.items.map(({id,text,completed,parent})=>({id,text,completed,parent})),workspace_ids:n.workspace_ids,references:n.references,color:n.color,pinned:n.pinned,archived:n.archived,order:n.order,revision:n.revision});
  function change(n,autosave=true){dirty.add(n.id);versions.set(n.id,(versions.get(n.id)||0)+1);status(autosave?'Saving…':'Editing…');clearTimeout(timer);if(autosave)timer=setTimeout(()=>flush().catch(()=>{}),450);}
  async function flush(){
    clearTimeout(timer);if(saving){await saving;if([...dirty].some(id=>!lineDrafts.has(id)))return flush();return;}
    if(conflict)throw Error('Reload the latest note to resolve the conflict.');
    saving=(async()=>{for(const id of [...dirty]){if(lineDrafts.has(id))continue;const n=notes.get(id),version=versions.get(id);const result=await api(base+'/'+encodeURIComponent(id),'PUT',payload(n));n.revision=result.revision;n.updated_at=result.updated_at;if(versions.get(id)===version){dirty.delete(id);for(const item of n.items){const rendered=result.items.find(i=>i.id===item.id);if(rendered)item.html=rendered.html;}} }status(dirty.size?'Editing…':'Saved');try{localStorage.setItem('harqis:quick-notes-change',String(Date.now()));}catch{}})();
    try{await saving;}catch(e){status(e.message,true);throw e;}finally{saving=null;}
    if([...dirty].some(id=>!lineDrafts.has(id)))return flush();
  }
  async function load(){
    const revision=++loading;references.clear();status('Loading…');
    try{const [data,context]=await Promise.all([api(base),api('/hfl-corpus/workspace-views')]);if(revision!==loading)return;spaces=context.views;for(const [id] of notes)if(!dirty.has(id)&&id!==selected)notes.delete(id);for(const n of data.notes)if(!dirty.has(n.id)&&n.id!==selected)notes.set(n.id,n);render();status(dirty.size?'Unsaved changes':'');}
    catch(e){status(e.message,true);}
  }
  function ordered(){return [...notes.values()].filter(n=>!n.archived||showArchived).sort((a,b)=>Number(a.archived)-Number(b.archived)||Number(b.pinned)-Number(a.pinned)||a.order-b.order||a.id.localeCompare(b.id));}
  function render(){grid.replaceChildren();for(const n of ordered())grid.append(card(n,false));if(!grid.childElementCount)grid.append(el('p','Nothing to remember yet. Create a checklist.','qn-empty'));renderButler();}
  function renderButler(){if(!butler)return;const scroll=butler.scrollTop;butler.replaceChildren();for(const n of [...notes.values()].filter(n=>!n.archived).sort((a,b)=>Number(b.pinned)-Number(a.pinned)||a.order-b.order||a.id.localeCompare(b.id)))butler.append(card(n,false,true));if(!butler.childElementCount)butler.append(el('p','No Quick Notes in these Spaces.','qn-empty'));butler.scrollTop=scroll;}
  function title(n){return n.title||'Untitled checklist';}
  function rerender(n){if(selected===n.id)edit(n);render();}
  function toggle(n,item,value){item.completed=value;for(const child of n.items)if(child.parent===item.id)child.completed=value;change(n);rerender(n);}
  function block(n,id){const i=n.items.findIndex(x=>x.id===id);let end=i+1;while(end<n.items.length&&n.items[end].parent===id)end++;return [i,end];}
  function moveItem(n,id,delta){const [i,end]=block(n,id),item=n.items[i];let target=i+delta;if(delta>0)target=end;if(target<0||target>=n.items.length)return;const other=n.items[target];if(item.parent!==other.parent){if(delta<0&&!item.parent&&other.parent)target=n.items.findIndex(x=>x.id===other.parent);else return;}const moved=n.items.splice(i,end-i);if(delta>0){const [,after]=block(n,other.id);n.items.splice(after,0,...moved);}else n.items.splice(target,0,...moved);change(n);rerender(n);}
  function indent(n,id,out=false){const [i,end]=block(n,id),item=n.items[i];if(out){if(!item.parent)return;const parent=item.parent;const siblings=n.items.filter(x=>x.parent===parent&&x.id!==id);n.items.splice(i,1);const at=siblings.length?n.items.findIndex(x=>x.id===siblings.at(-1).id)+1:n.items.findIndex(x=>x.id===parent)+1;item.parent=null;n.items.splice(at,0,item);}else{if(item.parent||end!==i+1||i===0)return;item.parent=n.items[i-1].parent||n.items[i-1].id;}change(n);rerender(n);}
  function dropItem(n,id,target,after,nested){
    if(id===target)return;
    const [i,end]=block(n,id),moved=n.items.slice(i,end);
    if(moved.some(x=>x.id===target))return;
    const remaining=n.items.filter(x=>!moved.includes(x)),to=remaining.findIndex(x=>x.id===target);
    let at=to+(after?1:0),parent=null;
    if(nested&&moved.length===1){const previous=remaining[at-1];parent=previous?(previous.parent||previous.id):null;}
    if(!parent){while(at<remaining.length&&remaining[at].parent)at++;}
    moved[0].parent=parent;remaining.splice(at,0,...moved);n.items=remaining;change(n);rerender(n);
  }
  function removeItem(n,id){const [i,end]=block(n,id),removed=n.items.splice(i,end-i);change(n);rerender(n);const undo=button('Undo removal',()=>{if(!n.items.some(x=>x.id===id)){if(removed[0].parent&&!n.items.some(x=>x.id===removed[0].parent))removed[0].parent=null;const at=removed[0].parent?block(n,removed[0].parent)[1]:Math.min(i,n.items.length);n.items.splice(at,0,...removed);change(n);rerender(n);}undo.remove();});$('qn-undo').replaceChildren(undo);}
  function line(n,item,editing,compact){
    const row=el('div',undefined,'qn-row');row.dataset.child=String(Boolean(item.parent));row.dataset.completed=String(item.completed);row.dataset.itemId=item.id;
    const check=el('input');check.type='checkbox';check.checked=item.completed;check.setAttribute('aria-label','Complete '+(item.text||'item'));check.onchange=()=>toggle(n,item,check.checked);
    const text=el('div',undefined,'qn-line');text.tabIndex=0;text.setAttribute('role','button');text.setAttribute('aria-label','Edit '+(item.text||'empty item'));if(item.html)text.innerHTML=item.html;else text.textContent=item.text||'Click to edit';
    const start=()=>{
      pause();clearTimeout(timer);lineDrafts.add(n.id);
      const input=el('textarea');let continuing=false;
      input.value=item.text;input.rows=1;input.maxLength=4000;input.setAttribute('aria-label','Checklist item');text.replaceWith(input);input.focus();
      input.oninput=()=>{item.text=input.value;delete item.html;change(n,false);};
      input.onblur=()=>{
        text.textContent=item.text||'Click to edit';text.setAttribute('aria-label','Edit '+(item.text||'empty item'));check.setAttribute('aria-label','Complete '+(item.text||'item'));input.replaceWith(text);
        if(continuing)return;
        lineDrafts.delete(n.id);
        flush().then(()=>{if(!input.isConnected){const current=n.items.find(x=>x.id===item.id);if(current?.html)text.innerHTML=current.html;}}).catch(()=>{});
      };
      input.onkeydown=e=>{
        if(e.isComposing)return;
        if(e.key==='Escape'){e.stopPropagation();input.blur();}
        if(e.key==='Enter'&&!e.shiftKey){
          e.preventDefault();e.stopPropagation();continuing=true;
          const next={id:crypto.randomUUID(),text:'',completed:false,parent:item.parent};
          const [,end]=block(n,item.id);n.items.splice(end,0,next);change(n,false);
          const nextRow=line(n,next,editing,compact),lastRow=row.parentElement.querySelector(`[data-item-id="${n.items[end-1].id}"]`);
          input.blur();lastRow.after(nextRow);nextRow.querySelector('.qn-line').click();
        }
      };
    };
    text.onclick=e=>{if(!e.target.closest('a'))start();};text.onkeydown=e=>{if(e.target.closest('a'))return;if(e.key==='Enter'||e.key===' '){e.preventDefault();start();}};row.append(check,text);
    if(editing&&!compact){
      const grip=button('⠿',()=>{},'qn-grip');grip.draggable=true;grip.title='Drag to reorder; move right to indent, left to outdent';grip.setAttribute('aria-label','Drag item');
      grip.onkeydown=e=>{if(!e.altKey)return;if(['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();moveItem(n,item.id,e.key==='ArrowUp'?-1:1);}if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();indent(n,item.id,e.key==='ArrowLeft');}};
      const clear=()=>editor.querySelectorAll('[data-item-drop]').forEach(r=>{delete r.dataset.itemDrop;delete r.dataset.dropNested;});
      grip.ondragstart=e=>{dragging={note:n.id,item:item.id};e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',item.id);};grip.ondragend=()=>{clear();dragging=null;};
      row.prepend(grip);
      const remove=iconButton('Remove item','m6 6 12 12M18 6 6 18',()=>removeItem(n,item.id));remove.classList.add('qn-remove-item');row.append(remove);
      row.ondragover=e=>{if(dragging?.note!==n.id)return;e.preventDefault();clear();const bounds=row.getBoundingClientRect(),left=row.parentElement.getBoundingClientRect().left;row.dataset.itemDrop=e.clientY>bounds.top+bounds.height/2?'after':'before';row.dataset.dropNested=String(e.clientX>left+42);};
      row.ondrop=e=>{e.preventDefault();if(dragging?.note===n.id){const bounds=row.getBoundingClientRect(),left=row.parentElement.getBoundingClientRect().left;dropItem(n,dragging.item,item.id,e.clientY>bounds.top+bounds.height/2,e.clientX>left+42);}clear();dragging=null;};
    }
    return row;
  }
  function addItem(n,parent=null){const item={id:crypto.randomUUID(),text:'',completed:false,parent};if(parent){const [,end]=block(n,parent);n.items.splice(end,0,item);}else n.items.push(item);change(n);edit(n);editor.querySelector(`[data-item-id="${item.id}"] .qn-line`).click();}
  function reorderCard(n,delta){const list=ordered().filter(x=>x.pinned===n.pinned&&x.archived===n.archived),i=list.indexOf(n),other=list[i+delta];if(!other)return;[list[i],list[i+delta]]=[other,n];list.forEach((x,index)=>{x.order=index;change(x);});render();}
  async function lifecycle(n,operation){try{await flush();if(operation==='delete'){if(!confirm('Delete “'+title(n)+'” permanently?'))return;await api(base+'/'+n.id,'DELETE',payload(n));notes.delete(n.id);}else{n.archived=operation==='archive';change(n);await flush();}selected=null;noteDialog.close();dialog.append($('qn-status').parentElement);editor.hidden=true;grid.hidden=false;render();}catch(e){status(e.message,true);}}
  function card(n,editing=false,compact=false){
    const root=el('article',undefined,'qn-root qn-card'+(editing?' qn-editor-card':''));root.dataset.color=n.color;root.dataset.noteId=n.id;root.dataset.archived=String(n.archived);
    const heading=el('div',undefined,'qn-card-heading');if(editing){const input=el('input');input.type='text';input.maxLength=200;input.value=n.title;input.placeholder='Checklist title';input.setAttribute('aria-label','Checklist title');input.oninput=()=>{n.title=input.value;change(n);};heading.append(input);}else heading.append(button(title(n),()=>openEditor(n),'qn-title'));
    const pin=button('',()=>{n.pinned=!n.pinned;change(n);rerender(n);},'qn-pin');pin.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="'+(n.pinned?'currentColor':'none')+'" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m8 3 8 0-1 7 4 4H5l4-4Z M12 14v7"/></svg>';pin.title=n.pinned?'Unpin note':'Pin note';pin.setAttribute('aria-label',pin.title);pin.setAttribute('aria-pressed',String(n.pinned));heading.append(pin);if(editing)heading.append(iconButton('Close note','m6 6 12 12M18 6 6 18',()=>back()));root.append(heading);
    const rows=el('div',undefined,'qn-rows');for(const i of n.items)rows.append(line(n,i,editing,compact));root.append(rows);if(!n.items.length)rows.append(el('p','No items yet.'));
    if(editing)root.append(button('＋ Add list item',()=>addItem(n),'qn-add-item'));
    const labels=n.workspace_ids.map(id=>spaces.find(s=>s.id===id)?.name||'Unavailable Space');root.append(el('div',(n.archived?'Archived · ':'')+(labels.join(' · ')||'All Spaces'),'qn-spaces'));
    if(editing){const host=el('div',undefined,'qn-linker');host.append(el('small','Link to Space'));root.append(host);if(window.HflWorkspacePicker)root._picker=window.HflWorkspacePicker(host,{selected:n.workspace_ids,name:'workspace_ids',empty:'All Spaces',onapply:ids=>{n.workspace_ids=ids;change(n);}});else host.append(el('p','Space linking unavailable. Reload this page.'));}
    const refs=el('section',undefined,'qn-references');root.append(refs);renderReferences(refs,n,editing);
    if(!compact){
      const footer=el('div',undefined,'qn-footer'),swatches=el('div',undefined,'qn-colors');
      swatches.setAttribute('role','group');swatches.setAttribute('aria-label','Note background');
      for(const [color,hex] of Object.entries({slate:'#1d2b40',blue:'#1b3856',mint:'#193f3c',plum:'#3a2a4c',amber:'#493b25'})){
        const b=button('',()=>{n.color=color;change(n);rerender(n);});b.style.background=hex;b.title=color+' background';b.setAttribute('aria-label',b.title);b.setAttribute('aria-pressed',String(n.color===color));swatches.append(b);
      }
      const actions=el('div',undefined,'qn-card-actions');
      actions.append(iconButton(n.archived?'Restore':'Archive',n.archived?'M4 9h16v12H4zM3 3h18v6H3zM12 18v-6m-3 3 3-3 3 3':'M4 9h16v12H4zM3 3h18v6H3zM10 13h4',()=>lifecycle(n,n.archived?'restore':'archive')),iconButton('Delete','M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',()=>lifecycle(n,'delete')));
      if(!editing){
        root.draggable=true;root.tabIndex=0;root.setAttribute('aria-label',title(n));root.setAttribute('aria-description','Drag to reorder within this pin group. Alt and arrow keys also move this note.');
        root.querySelector('.qn-title').draggable=true;
        const clearDrop=()=>grid.querySelectorAll('[data-drop-position]').forEach(card=>delete card.dataset.dropPosition);
        root.ondragstart=e=>{if(e.target.closest('input,textarea,a,button:not(.qn-title),.qn-line')){e.preventDefault();return;}dragging={card:n.id};e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',n.id);};
        root.ondragover=e=>{clearDrop();const source=notes.get(dragging?.card);if(!source||source.id===n.id||source.pinned!==n.pinned||source.archived!==n.archived){e.dataTransfer.dropEffect='none';return;}e.preventDefault();e.dataTransfer.dropEffect='move';const bounds=root.getBoundingClientRect();root.dataset.dropPosition=e.clientY>bounds.top+bounds.height/2?'after':'before';};
        root.ondragleave=e=>{if(!root.contains(e.relatedTarget))delete root.dataset.dropPosition;};
        root.ondragend=()=>{dragging=null;clearDrop();};
        root.ondrop=e=>{e.preventDefault();const source=notes.get(dragging?.card),after=root.dataset.dropPosition==='after';dragging=null;clearDrop();if(!source||source.id===n.id||source.pinned!==n.pinned||source.archived!==n.archived)return;const list=ordered().filter(x=>x.pinned===n.pinned&&x.archived===n.archived&&x.id!==source.id);list.splice(list.indexOf(n)+(after?1:0),0,source);list.forEach((x,index)=>{x.order=index;change(x);});render();};
        root.onkeydown=e=>{if(e.target===root&&e.altKey&&['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();reorderCard(n,e.key==='ArrowUp'?-1:1);grid.querySelector(`[data-note-id="${n.id}"]`)?.focus();}};
      }
      footer.append(swatches,actions);root.append(footer);
    }
    return root;
  }
  async function fetchReference(ref){const key=ref.kind+':'+ref.id;if(references.has(key))return references.get(key);const url=ref.kind==='idea'?'/hfl-corpus/timeline/ideas/objects/':'/hfl-corpus/timeline/items/';try{const data=await api(url+encodeURIComponent(ref.id));const item={...data.item,kind:ref.kind};references.set(key,item);return item;}catch{return {...ref,title:'Unavailable '+(ref.kind==='idea'?'idea':'action'),unavailable:true};}}
  async function renderReferences(host,n,editing){
    if(!n.references.length&&!editing)return;host.append(el('h4','Linked actions & ideas'));const list=el('div',undefined,'qn-reference-grid');host.append(list);if(n.references.length)list.textContent='Loading links…';
    if(editing){const search=el('input',undefined,'qn-reference-search');search.type='search';search.placeholder='Find actions or ideas';search.setAttribute('aria-label','Find actions or ideas');const results=el('div',undefined,'qn-reference-results'),more=button('More results',()=>find(page+1));more.hidden=true;list.before(search,results,more);let sequence=0,debounce,page=1;async function find(p=1){const seq=++sequence;results.textContent='Searching…';try{const data=await api('/hfl-corpus/timeline/ideas/reuse/options?query='+encodeURIComponent(search.value)+'&page='+p);if(seq!==sequence||!host.isConnected)return;page=p;results.replaceChildren();for(const item of data.items){const b=button(item.title,()=>{if(!n.references.some(r=>r.id===item.id&&r.kind===item.kind)){n.references.push({id:item.id,kind:item.kind});references.set(item.kind+':'+item.id,item);change(n);edit(n);}});b.disabled=n.references.some(r=>r.id===item.id&&r.kind===item.kind);results.append(b);}if(!data.items.length)results.textContent='No matching actions or ideas.';more.hidden=data.total<=page*10;}catch(e){if(seq===sequence)results.replaceChildren(el('p',e.message),button('Retry search',()=>find(p)));}}search.oninput=()=>{clearTimeout(debounce);sequence++;debounce=setTimeout(()=>find(),250);};search.onfocus=()=>{if(!results.childElementCount)find();};}
    const items=await Promise.all(n.references.map(fetchReference));if(!host.isConnected)return;list.replaceChildren();for(const item of items.sort((a,b)=>(b.updated_at||'').localeCompare(a.updated_at||''))){const row=el('div',undefined,'qn-ref'),open=button(item.title,async()=>{if(item.unavailable)return;try{await flush();selected=null;noteDialog.close();dialog.append($('qn-status').parentElement);dialog.close();if(item.kind==='idea'&&window.HflIdeas?.editIdea)window.HflIdeas.editIdea(item.id);else if(window.HflIdeas?.openAction)window.HflIdeas.openAction(item.id);else location.href='/hfl-corpus/actions?edit_kind='+item.kind+'&edit='+encodeURIComponent(item.id);}catch(e){status(e.message,true);}});open.disabled=Boolean(item.unavailable);open.append(el('small',(item.kind==='idea'?'Idea':'Action')+(item.updated_at?' · '+new Date(item.updated_at).toLocaleString():'')));row.append(open);if(editing)row.append(iconButton('Unlink','m10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l4-4m11 1 1-1a4 4 0 0 1 6 6l-4 4M3 3l18 18',()=>{n.references=n.references.filter(r=>!(r.id===item.id&&r.kind===item.kind));change(n);edit(n);}));list.append(row);}
  }
  function edit(n){editor.querySelector('.qn-card')?._picker?.close();selected=n.id;grid.hidden=false;editor.hidden=false;editor.replaceChildren(card(n,true));if(!noteDialog.open)noteDialog.showModal();noteDialog.append($('qn-status').parentElement);}
  async function openEditor(n){try{await flush();if(!dialog.open){opener=document.activeElement;dialog.showModal();}edit(n);}catch(e){status(e.message,true);}}
  async function back(){editor.querySelector('.qn-card')?._picker?.close();try{await flush();selected=null;noteDialog.close();dialog.append($('qn-status').parentElement);editor.hidden=true;grid.hidden=false;await load();}catch(e){status(e.message,true);}}
  async function close(){editor.querySelector('.qn-card')?._picker?.close();try{await flush();selected=null;noteDialog.close();dialog.append($('qn-status').parentElement);dialog.close();opener?.focus();}catch(e){status(e.message,true);}}
  async function open(){opener=document.activeElement;if(!dialog.open)dialog.showModal();grid.hidden=false;editor.hidden=true;selected=null;await load();}
  window.QuickNotes={open};document.addEventListener('click',e=>{if(e.target.closest('[data-quick-notes-open]'))open();});
  noteDialog.addEventListener('cancel',e=>{e.preventDefault();document.activeElement?.blur();back();});
  dialog.addEventListener('cancel',e=>{e.preventDefault();selected?back():close();});$('qn-close').onclick=close;
  function archiveControl(){$('qn-archive').setAttribute('aria-checked',String(showArchived));}
  $('qn-new').onclick=async()=>{try{await flush();const n={id:crypto.randomUUID(),title:'',items:[],workspace_ids:[],references:[],pinned:false,color:'slate',archived:false,order:Date.now(),revision:0};notes.set(n.id,n);change(n);edit(n);addItem(n);}catch(e){status(e.message,true);}};
  $('qn-archive').onclick=async()=>{await back();if(dirty.size)return;showArchived=!showArchived;archiveControl();render();};
  $('qn-retry').onclick=()=>dirty.size?flush().then(render).catch(()=>{}):load();
  $('qn-reload').onclick=()=>{if(!confirm('Discard your unsaved changes and reload the latest notes?'))return;dirty.clear();conflict=false;selected=null;noteDialog.close();dialog.append($('qn-status').parentElement);editor.hidden=true;grid.hidden=false;load();};
  document.addEventListener('keydown',e=>{if(!['/agents','/second-brain','/second-brain/hud','/hfl-corpus/actions'].includes(location.pathname)||e.defaultPrevented||e.repeat||e.ctrlKey||e.metaKey||e.altKey||e.isComposing||e.key.toLowerCase()!=='s'||e.target.closest('input,textarea,select,[contenteditable=true],.xterm')||document.querySelector('dialog[open]:not(#followups-board):not(#activity-standalone)'))return;e.preventDefault();open();});
  window.addEventListener('beforeunload',e=>{if(dirty.size){e.preventDefault();e.returnValue='';}});
  window.addEventListener('storage',e=>{if(['harqis:quick-notes-change','corpus:workspace-change'].includes(e.key)&&!dirty.size&&!selected&&!document.activeElement?.closest('.qn-root input,.qn-root textarea')&&(dialog.open||panel?.dataset.tab==='notes')){references.clear();load();}});
  const refreshContext=()=>{if(!dirty.size&&!selected&&!document.activeElement?.closest('.qn-root input,.qn-root textarea')&&(dialog.open||(!panel.hidden&&panel.dataset.tab==='notes')))load();};
  window.addEventListener('focus',refreshContext);document.addEventListener('hud:spaces-changed',refreshContext);window.addEventListener('hfl:workspace-context',refreshContext);
  setInterval(refreshContext,30000);
  const motion=matchMedia('(prefers-reduced-motion: reduce)');let playing=!motion.matches,last=0,carry=0,loop=0;
  function playback(){const b=$('butler-notes-playback');if(b){b.textContent=playing?'Pause scrolling':'Resume scrolling';b.setAttribute('aria-pressed',String(playing));}}
  function pause(){playing=false;playback();}
  if(butler){for(const event of ['pointerdown','keydown','wheel','touchstart'])butler.addEventListener(event,pause,{passive:true});$('butler-notes-playback').onclick=()=>{playing=!playing;playback();};$('butler-notes-refresh').onclick=()=>{references.clear();load();};motion.addEventListener('change',()=>{if(motion.matches)pause();});panel.addEventListener('butler-tab-change',()=>{if(panel.dataset.tab==='notes')load();});panel.addEventListener('butler-opened',()=>{if(panel.dataset.tab==='notes')load();});playback();function tick(time){const elapsed=Math.min(100,time-(last||time));last=time;if(playing&&!motion.matches&&!document.hidden&&!panel.hidden&&panel.dataset.tab==='notes'&&butler.scrollHeight>butler.clientHeight){if(butler.scrollTop+butler.clientHeight>=butler.scrollHeight-1){if(!loop)loop=time+2500;if(time>=loop){butler.scrollTop=0;loop=0;}}else{carry+=elapsed*.018;const pixels=Math.floor(carry);butler.scrollTop+=pixels;carry-=pixels;}}requestAnimationFrame(tick);}requestAnimationFrame(tick);}
})();
