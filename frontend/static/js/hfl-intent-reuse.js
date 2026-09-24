/* Shared fields and commands for reusable planning objects. */
(() => {
  const element = (tag, text) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; return n; };
  const api = (...args) => window.HflIdeas.api(...args);
  window.HflWorkspacePicker = (host, {selected=[], empty='All activity', name='', onapply=()=>{}, onload=()=>{}}={}) => {
    host._disposeWorkspacePicker?.();
    const picker=element('details');picker.className='workspace-view-picker intent-workspace-picker';
    const summary=element('summary'),caption=element('span'),options=element('div'),choices=element('div');
    summary.setAttribute('aria-label',name?'Workspaces':'Focus on');summary.append(caption);options.className='workspace-view-options';
    const clear=element('button',empty);clear.type='button';options.append(clear,choices,element('p','Selections apply when you close this list.'));picker.append(summary,options);host.append(picker);
    let ids=new Set(selected),applied=[...ids].sort().join(','),views=[];
    const update=()=>{caption.textContent=views.filter(v=>ids.has(v.id)).map(v=>v.name).join(' + ')||([...ids].length?'Selected workspaces':empty);clear.setAttribute('aria-pressed',String(!ids.size));};
    const render=()=>{choices.replaceChildren();for(const view of views){const label=element('label'),input=element('input'),dot=element('span');input.type='checkbox';input.value=view.id;input.checked=ids.has(view.id);dot.className='view-color-dot';dot.style.backgroundColor=view.color||'#94a3b8';label.append(input,dot,document.createTextNode(view.name));choices.append(label);input.onchange=()=>{input.checked?ids.add(view.id):ids.delete(view.id);update();};}update();};
    const commit=()=>{const key=[...ids].sort().join(',');if(key===applied)return;applied=key;if(name){host.querySelectorAll('input[type=hidden]').forEach(n=>n.remove());for(const id of ids){const input=element('input');input.type='hidden';input.name=name;input.value=id;host.append(input);}host.dispatchEvent(new Event('change',{bubbles:true}));}onapply([...ids],views);};
    for(const id of ids){if(name){const input=element('input');input.type='hidden';input.name=name;input.value=id;host.append(input);}}
    clear.onclick=()=>{ids.clear();render();picker.open=false;applied=null;commit();};
    picker.addEventListener('toggle',()=>{if(!picker.open)commit();});
    picker.addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();picker.open=false;commit();summary.focus();}});
    const controller=new AbortController();host._disposeWorkspacePicker=()=>controller.abort();document.addEventListener('click',event=>{if(!picker.isConnected){controller.abort();return;}if(!picker.contains(event.target)){picker.open=false;commit();}},{signal:controller.signal});
    // Close/apply on submit too, so a pending checkbox selection is never lost.
    host.closest('form')?.addEventListener('submit',commit,{capture:true,signal:controller.signal});
    update();fetch('/hfl-corpus/workspace-views').then(async response=>{if(!response.ok)throw Error();return response.json();}).then(data=>{if(!picker.isConnected)return;views=data.views;for(const id of ids)if(!views.some(v=>v.id===id))views.push({id,name:'Unavailable workspace'});render();onload(views);}).catch(()=>{options.append(element('p','Workspaces unavailable. Reopen to retry.'));});
    return {close:()=>{picker.open=false;commit();}};
  };
  window.HflIntentFields = (form, item={}, kind='actionable') => {
    let root=form.querySelector('[data-intent-fields]');
    if(!root){root=element('section');root.dataset.intentFields='';}
    form.querySelector('[data-object-attachments]').after(root);root.replaceChildren(element('p','Workspaces (optional)'));
    window.HflWorkspacePicker(root,{selected:item?.workspace_ids||[],empty:'No workspace',name:'workspace_ids'});
    let recurrence=form.querySelector('[data-recurrence-fields]');recurrence?.remove();
    if(kind!=='actionable')return;
    recurrence=element('section');recurrence.dataset.recurrenceFields='';
    const add=(name,text,type,value)=>{const l=element('label',text),input=element(type==='select'?'select':'input');input.name=name;input.setAttribute('aria-label',text);if(type!=='select')input.type=type;input.value=value??'';l.append(input);recurrence.append(l);return input;};
    const frequency=add('repeat_frequency','Repeat','select','');
    for(const [value,text] of [['','Does not repeat'],['daily','Daily'],['weekly','Weekly'],['monthly','Monthly'],['yearly','Yearly']]){const option=element('option',text);option.value=value;frequency.append(option);}
    frequency.value=item?.recurrence?.frequency||'';
    const interval=add('repeat_interval','Every','number',item?.recurrence?.interval||1);interval.min=1;interval.max=365;
    const start=add('repeat_start','First planned date','date',item?.recurrence?.start||item?.due_date||'');
    const end=add('repeat_end','Repeat until (optional)','date',item?.recurrence?.end||'');
    const update=()=>{for(const input of [interval,start,end]){input.disabled=!frequency.value;input.closest('label').hidden=!frequency.value;}interval.required=start.required=!!frequency.value;};frequency.onchange=update;update();
    recurrence.append(element('small','Completing an occurrence creates the next future action with unchecked checklist items.'));
    form.querySelector('.action-triage-body').append(recurrence);
  };
  window.HflIntentValues = form => {
    const data=new FormData(form), result=Object.fromEntries(data);
    result.workspace_ids=data.getAll('workspace_ids').sort();
    if(form.querySelector('[data-recurrence-fields]'))result.recurrence=result.repeat_frequency?{frequency:result.repeat_frequency,interval:Number(result.repeat_interval),start:result.repeat_start,end:result.repeat_end||''}:null;
    for(const key of Object.keys(result))if(key.startsWith('repeat_'))delete result[key];
    return result;
  };
  const markdownCache=new Map();
  window.HflChecklistMarkdown = (root,text) => {
    root.textContent=text;
    if(!text.trim())return;
    if(!markdownCache.has(text))markdownCache.set(text,api('/render','POST',{body:text}).catch(error=>{markdownCache.delete(text);throw error;}));
    markdownCache.get(text).then(data=>{if(root.textContent===text)root.innerHTML=data.html;}).catch(()=>{});
  };
  window.HflCopyList = checklist => {
    const dialog=element('dialog');dialog.setAttribute('aria-label','Copy list to action or idea');dialog.className='agenda-dialog idea-dialog';
    const form=element('form'),body=element('div');body.className='agenda-form-body';
    body.append(element('h2','Copy list to action or idea'));
    const search=element('input');search.type='search';search.placeholder='Search actions and ideas';search.setAttribute('aria-label','Search actions and ideas');
    const rows=element('div'),status=element('p'),close=element('button','Close');close.type='button';close.onclick=()=>dialog.close();
    body.append(search,status,rows,close);form.append(body);dialog.append(form);document.body.append(dialog);dialog.showModal();search.focus();
    let sequence=0,timer;const key=crypto.randomUUID();
    async function load(){const ticket=++sequence;status.textContent='Loading…';try{
      const data=await api('/reuse/options?'+new URLSearchParams({query:search.value}));if(ticket!==sequence||!dialog.open)return;rows.replaceChildren();status.textContent=data.items.length?'Recently updated first':'No matching actions or ideas';
      for(const item of data.items){const b=element('button',item.title+' · '+(item.kind==='idea'?'Idea':'Action'));b.type='button';b.className='intent-copy-choice';b.onclick=async()=>{body.inert=true;try{await api('/reuse/copy-list','POST',{request_id:key,kind:item.kind,identity:item.id,version:item.version,checklist});window.dispatchEvent(new Event('hfl:actions-updated'));window.dispatchEvent(new CustomEvent('hfl:ideas-updated',{detail:{refreshShared:true}}));dialog.close();}catch(error){status.textContent=error.message;}finally{body.inert=false;}};rows.append(b);}
    }catch(error){if(ticket===sequence)status.textContent=error.message;}}
    search.oninput=()=>{clearTimeout(timer);timer=setTimeout(load,200);};form.onsubmit=event=>event.preventDefault();dialog.onclose=()=>{++sequence;clearTimeout(timer);dialog.remove();};load();
  };
})();
