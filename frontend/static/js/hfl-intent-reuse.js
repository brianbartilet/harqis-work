/* Shared fields and commands for reusable planning objects. */
(() => {
  const element = (tag, text) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; return n; };
  const api = (...args) => window.HflIdeas.api(...args);
  window.HflIntentFields = (form, item={}, kind='actionable') => {
    let root=form.querySelector('[data-intent-fields]');
    if(!root){root=element('section');root.dataset.intentFields='';form.querySelector('[name=title]').closest('label').after(root);}
    root.replaceChildren();
    const label=element('label','Workspaces (optional)'), select=element('select');select.multiple=true;select.name='workspace_ids';select.size=4;select.setAttribute('aria-label','Workspaces');label.append(select);root.append(label);
    const selected=new Set(item?.workspace_ids||[]);
    for(const id of selected){const option=element('option',id);option.value=id;option.selected=true;select.append(option);}
    const status=element('small','Loading workspaces…');root.append(status);
    fetch('/hfl-corpus/workspace-views').then(async response=>{if(!response.ok)throw Error();return response.json();}).then(data=>{
      if(!select.isConnected)return;
      const current=new Set([...select.selectedOptions].map(o=>o.value));select.replaceChildren();
      for(const view of data.views){const option=element('option',view.name);option.value=view.id;option.selected=current.has(view.id);select.append(option);current.delete(view.id);}
      for(const id of current){const option=element('option','Unavailable workspace');option.value=id;option.selected=true;select.append(option);}
      status.textContent='Select several with Ctrl / Command. Leave empty for no assignment.';
    }).catch(()=>{status.textContent='Workspaces could not load. Existing assignments are preserved; reopen to retry.';});
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
