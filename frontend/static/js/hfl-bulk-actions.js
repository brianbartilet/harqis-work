/* Independent Action/Idea selections; updates retain the existing per-object contracts. */
(() => {
  const node = (tag, text, cls) => {const el=document.createElement(tag);if(text)el.textContent=text;if(cls)el.className=cls;return el;};
  const icon = path => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
  window.HflBulkActions = ({root, signal, refresh, canStart=()=>true}) => {
    const groups = Object.fromEntries(['action','idea'].map(kind=>[kind,{enabled:false, selected:new Set(), rows:new Map()}]));
    let busy=false, activeDialog=null;
    const selector = kind => kind==='action'?'[data-followup-id]':'[data-idea-id]';
    function update(kind) {
      const group=groups[kind], controls=root.querySelector(`[data-bulk-kind="${kind}"]`);
      if(controls){
        controls.querySelector('[data-bulk-toggle]').setAttribute('aria-pressed',String(group.enabled));
        controls.querySelector('[data-bulk-toggle]').disabled=busy;
        const menu=controls.querySelector('[data-bulk-menu]');
        menu.disabled=busy||!group.enabled||!group.selected.size;
        if(menu.disabled)closeMenu(controls);
        controls.querySelector('[data-bulk-count]').textContent=`${group.selected.size} selected`;
      }
      root.querySelectorAll(selector(kind)).forEach(card=>{
        const id=kind==='action'?card.dataset.followupId:card.dataset.ideaId;
        let check=card.querySelector('[data-bulk-check]');
        if(!check){
          check=node('input');check.type='checkbox';check.dataset.bulkCheck='';check.className='bulk-card-check';
          check.addEventListener('change',()=>{check.checked?group.selected.add(id):group.selected.delete(id);update(kind);});
          const clone=card.querySelector('.action-clone-handle');
          if(clone)clone.before(check);else card.prepend(check);
        }
        check.setAttribute('aria-label','Select '+(group.rows.get(id)?.title||'card'));
        check.hidden=!group.enabled;check.disabled=busy;check.checked=group.selected.has(id);
        card.classList.toggle('bulk-selecting',group.enabled);
        card.classList.toggle('bulk-selected',group.enabled&&check.checked);
      });
      root.querySelectorAll(kind==='idea'?'.ideas-drawer':'.followups-lane:not(.ideas-drawer)').forEach(lane=>{
        let label=lane.querySelector('[data-bulk-list-select]');
        if(!label){
          label=node('label',null,'bulk-list-select');label.dataset.bulkListSelect='';
          const check=node('input');check.type='checkbox';check.dataset.bulkListCheck='';
          check.setAttribute('aria-label','Select all '+(lane.getAttribute('aria-label')||'cards'));
          check.addEventListener('change',()=>{
            lane.querySelectorAll(selector(kind)).forEach(card=>{
              const id=kind==='action'?card.dataset.followupId:card.dataset.ideaId;
              check.checked?group.selected.add(id):group.selected.delete(id);
            });
            update(kind);
          });
          label.append(check,node('span','Select all'));
          lane.firstElementChild.append(label);
        }
        const ids=[...lane.querySelectorAll(selector(kind))].map(card=>kind==='action'?card.dataset.followupId:card.dataset.ideaId);
        const count=ids.filter(id=>group.selected.has(id)).length,check=label.querySelector('input');
        label.hidden=!group.enabled;check.disabled=busy||!ids.length;
        check.checked=!!ids.length&&count===ids.length;
        check.indeterminate=count>0&&count<ids.length;
      });
    }
    function closeMenu(controls) {
      controls.querySelector('[data-bulk-options]').hidden=true;
      controls.querySelector('[data-bulk-menu]').setAttribute('aria-expanded','false');
    }
    function mount(host,kind) {
      host.className='bulk-controls';host.dataset.bulkKind=kind;
      const toggle=node('button');toggle.type='button';toggle.dataset.bulkToggle='';
      toggle.innerHTML=icon('M12.034 12.681a.498.498 0 0 1 .647-.647l9 3.5a.5.5 0 0 1-.033.943l-3.444 1.068a1 1 0 0 0-.66.66l-1.067 3.443a.5.5 0 0 1-.943.033zM21 11V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h6');
      toggle.title='Select '+(kind==='action'?'actions':'ideas');toggle.setAttribute('aria-label',toggle.title);
      toggle.onclick=()=>{groups[kind].enabled=!groups[kind].enabled;if(!groups[kind].enabled)groups[kind].selected.clear();update(kind);};
      const wrapper=node('div',null,'bulk-menu'), menu=node('button'), options=node('div',null,'board-create-options');
      menu.type='button';menu.dataset.bulkMenu='';menu.setAttribute('aria-label','Bulk update '+(kind==='action'?'actions':'ideas'));menu.title=menu.getAttribute('aria-label');
      menu.innerHTML=icon('M4 4h10v4H4zM4 10h10v4H4zM4 16h10v4H4zM18 8l3 4-3 4');
      options.dataset.bulkOptions='';options.id='bulk-options-'+kind;options.hidden=true;
      menu.setAttribute('aria-controls',options.id);menu.setAttribute('aria-expanded','false');
      menu.onclick=()=>{options.hidden=!options.hidden;menu.setAttribute('aria-expanded',String(!options.hidden));};
      for(const [operation,title] of [['status','Move to status'],['workspace_ids','Add to space'],['board_ids','Add to board'],['dismiss','Dismiss']]){
        const button=node('button',title);button.type='button';button.onclick=()=>{closeMenu(host);open(kind,operation,title,menu);};options.append(button);
      }
      wrapper.append(menu,options);
      const count=node('span',null,'bulk-selection-count');count.dataset.bulkCount='';count.setAttribute('role','status');
      host.replaceChildren(toggle,wrapper,count);update(kind);
    }
    async function json(url,options={}) {
      const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(45000),...options,headers:{'Content-Type':'application/json'}});
      let data;try{data=await response.json();}catch{throw Error('The service could not respond. Refresh before retrying.');}
      if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Could not save. Refresh and retry.');
      return data;
    }
    async function open(kind,operation,title,opener) {
      if(busy||activeDialog||!canStart())return;
      const group=groups[kind], selected=[...group.selected].map(id=>group.rows.get(id)).filter(Boolean);
      if(!selected.length)return;
      const d=window.HflIdeas.dialog(title);activeDialog=d;
      d.node.classList.add('bulk-dialog');
      d.node.addEventListener('close',()=>{activeDialog=null;const current=root.querySelector(`[data-bulk-kind="${kind}"] [data-bulk-menu]`);(current&&!current.disabled?current:root.querySelector(`[data-bulk-kind="${kind}"] [data-bulk-toggle]`)||opener)?.focus();},{once:true});
      d.footer.firstChild.textContent='Cancel';
      const summary=node('p',`${selected.length} ${kind==='action'?'action':'idea'}${selected.length===1?'':'s'} selected.`);
      summary.setAttribute('role','status');d.body.append(summary);
      const submit=node('button',operation==='status'?'Move':operation==='dismiss'?'Dismiss':'Add');submit.type='submit';d.footer.append(submit);
      let select=null;
      if(operation==='dismiss')d.body.append(node('p','Move all selected cards to Dismissed?'));
      else {
        const label=node('label',operation==='status'?'Status':operation==='board_ids'?'Board':'Space');
        select=node('select');select.required=true;select.name='target';label.append(select);d.body.append(label);
        if(operation==='status'){
          const choices=kind==='action'?[['open','In Review'],['active','Ready'],['in_progress','In Progress'],['incomplete','Incomplete'],['done','Done'],['dismissed','Dismissed']]:[['suggested','Open'],['adopted','Has actions'],['dismissed','Dismissed']];
          choices.forEach(([value,text])=>{const option=node('option',text);option.value=value;select.append(option);});
          if(kind==='idea')d.body.append(node('p','Has actions changes status only. These ideas will leave this drawer; no actions are created.','board-hint'));
        }else{
          if(operation==='board_ids'&&kind==='action')d.body.append(node('p','Adding actions to a new board returns them to In Review, matching individual card updates.','board-hint'));
          submit.disabled=true;select.disabled=true;select.append(node('option','Loading…'));
          try{
            const data=await json(operation==='board_ids'?'/hfl-corpus/timeline/ideas/boards':'/hfl-corpus/workspace-views');
            if(!d.node.isConnected)return;
            const choices=(operation==='board_ids'?data.maps.filter(item=>item.active!==false):data.views).sort((a,b)=>a.name.localeCompare(b.name));
            select.replaceChildren();const placeholder=node('option',choices.length?'Choose a '+(operation==='board_ids'?'board':'Space'):'No destinations available');placeholder.value='';select.append(placeholder);
            choices.forEach(item=>{const option=node('option',item.name);option.value=item.id;select.append(option);});
            select.disabled=!choices.length;select.onchange=()=>{submit.disabled=!select.value;};
          }catch(e){if(d.node.isConnected){select.replaceChildren(node('option','Unavailable'));d.error.textContent='Could not load destinations. Close and reopen to retry.';}}
        }
      }
      d.form.onsubmit=async event=>{
        event.preventDefault();if(busy||submit.disabled)return;
        busy=true;d.body.inert=true;submit.disabled=true;d.footer.firstChild.disabled=true;
        for(const name of Object.keys(groups))update(name);
        root.inert=true;
        const failures=[];let succeeded=0;
        for(const item of selected){
          summary.textContent=`Updating ${succeeded+failures.length+1} of ${selected.length}…`;
          const changes=operation==='dismiss'?{status:'dismissed'}:operation==='status'?{status:select.value}:{[operation]:[...new Set([...(item[operation]||[]),select.value])]};
          try{
            const path=kind==='action'?'/hfl-corpus/timeline/items/':'/hfl-corpus/timeline/ideas/objects/';
            await json(path+encodeURIComponent(item.id),{method:'PATCH',body:JSON.stringify({version:item.version,...changes})});
            succeeded++;group.selected.delete(item.id);
          }catch(e){failures.push({title:item.title,message:e.message});}
        }
        // Refresh before allowing retries, so retained selections use the current versions.
        busy=false;
        try{await refresh();}finally{root.inert=false;d.body.inert=false;}
        for(const name of Object.keys(groups))update(name);
        summary.textContent=`${succeeded} updated · ${failures.length} failed.`;
        if(failures.length){
          d.error.textContent='Failed cards remain selected. Close this dialog, review them, and retry the bulk action.';
          const list=node('ul',null,'bulk-failures');failures.forEach(failure=>list.append(node('li',`${failure.title}: ${failure.message}`)));d.body.append(list);
        }
        if(select)select.disabled=true;
        submit.remove();d.footer.firstChild.disabled=false;d.footer.firstChild.textContent='Close';d.footer.firstChild.focus();
      };
    }
    document.addEventListener('click',event=>root.querySelectorAll('[data-bulk-kind]').forEach(host=>{if(!host.contains(event.target))closeMenu(host);}),{signal});
    root.addEventListener('keydown',event=>{if(event.key!=='Escape')return;const host=event.target.closest('[data-bulk-kind]');if(host&&!host.querySelector('[data-bulk-options]').hidden){event.stopPropagation();closeMenu(host);host.querySelector('[data-bulk-menu]').focus();}},{signal});
    return {
      mount,
      get busy(){return busy;},
      get editing(){return !!activeDialog||!!root.querySelector('[data-bulk-options]:not([hidden])');},
      selecting:kind=>groups[kind].enabled,
      sync(kind,rows){const group=groups[kind];group.rows=new Map(rows.map(item=>[item.id,item]));for(const id of group.selected)if(!group.rows.has(id))group.selected.delete(id);update(kind);},
      clear(){for(const kind of Object.keys(groups)){groups[kind].selected.clear();update(kind);}},
      dispose(){if(!busy)activeDialog?.node.close();}
    };
  };
})();
