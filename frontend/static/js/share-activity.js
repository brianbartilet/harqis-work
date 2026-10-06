(() => {
  'use strict';
  const form = document.querySelector('[data-social-form]');
  let active = window.location.pathname === '/sharing/preview/chat' ? 'agent' : 'recipe';
  const labels = new Map();
  const savedLabels = form?.querySelector('[name="excluded_object_labels"]');
  if (savedLabels) Object.entries(JSON.parse(savedLabels.value)).forEach(([id,label])=>labels.set(id,label));
  const selectTab = key => {
    active = key;
    const shell = form?.querySelector('[data-preview-shell]');
    if (shell) shell.hidden = key === 'filters' || key === 'recipe';
    const test = form?.querySelector('[data-test-agent]');
    if (test) test.hidden = key !== 'agent';
    form?.querySelectorAll('[data-share-tab]').forEach(b => {
      b.setAttribute('aria-selected', String(b.dataset.shareTab === key));
      b.tabIndex = b.dataset.shareTab === key ? 0 : -1;
    });
    form?.querySelectorAll('[data-share-panel], [data-preview-tab]').forEach(p => {
      p.hidden = (p.dataset.sharePanel || p.dataset.previewTab) !== key;
    });
    window.renderShareGraphs?.();
  };
  const renderGraphs = () => window.renderShareGraphs?.();
  window.refreshShareActivity = () => {
    if (form) {
      const excluded = [...form.querySelectorAll('[name="excluded_object_ids"]')];
      const summary = form.querySelector('[data-excluded-summary]');
      summary?.replaceChildren();
      if (excluded.length && summary) {
        const title=document.createElement('p');title.textContent='Excluded objects (remain excluded during live refresh):';summary.append(title);
        excluded.forEach(input=>{const b=document.createElement('button');b.type='button';b.className='btn btn-soft';b.textContent='Restore '+(labels.get(input.value)||input.value);b.onclick=()=>{input.remove();form.dispatchEvent(new Event('activitychange'));};summary.append(b);});
      }
      form.querySelectorAll('[data-share-object]').forEach(input=>labels.set(input.dataset.shareObject,input.parentElement.textContent.trim()));
      if (savedLabels) savedLabels.value=JSON.stringify(Object.fromEntries(excluded.map(input=>[input.value,labels.get(input.value)||'Excluded object'])));
      form.querySelectorAll('[data-outside-board]').forEach(input=>{input.checked=[...form.querySelectorAll('[name="outside_board_ids"]')].some(v=>v.value===input.dataset.outsideBoard);});
      const secrets=form.querySelector('[data-include-secrets]');
      form.querySelector('[data-share-secrets-status]').textContent=(secrets?.checked?'Secrets included across all sections':'Secrets excluded')+' · All recipient content is read-only.';
      selectTab(active);
    }
    renderGraphs();
  };
  if (form) {
    form.querySelectorAll('[data-field-help]').forEach(button => {
      const help = document.getElementById(button.getAttribute('aria-controls'));
      let pinned = false;
      const show = visible => {
        help.hidden = !visible;
        button.setAttribute('aria-expanded', String(visible));
      };
      button.addEventListener('pointerenter', () => show(true));
      button.addEventListener('pointerleave', () => { if (!pinned && document.activeElement !== button) show(false); });
      button.addEventListener('focus', () => show(true));
      button.addEventListener('blur', () => { pinned = false; show(false); });
      button.addEventListener('click', () => { pinned = !pinned; show(pinned); });
      button.addEventListener('keydown', event => {
        if (event.key === 'Escape') { pinned = false; show(false); }
      });
    });
    form.addEventListener('invalid', event => {
      const panel = event.target.closest('[data-share-panel]');
      if (panel) selectTab(panel.dataset.sharePanel);
    }, true);
    const recipe=form.querySelector('[data-recipe-fields]'), filters=form.querySelector('[data-filter-fields]'), entries=form.querySelector('[data-entry-fields]');
    // Reuse the existing controls and handlers, preserving saved-recipe behavior.
    [...form.children].forEach(el=>{if(el.matches('.two, .field, details.expand-panel'))recipe.append(el);});
    ['[data-source-selector]','#topic','#context-prompt'].forEach(sel=>{
      const el=form.querySelector(sel);if(el)filters.append(el.closest('details.expand-panel')||el.closest('.field'));
    });
    const scope=form.querySelector('[name="corpus_scope"]');
    if(scope){
      filters.prepend(scope);
      form.querySelector('[data-workspace-reset]').hidden = !scope.value;
      form.querySelector('details.message')?.remove();
      const inherited=JSON.parse(scope.value), editor=document.createElement('details');
      editor.dataset.inheritedRules='';editor.className='expand-panel';editor.open=true;
      const title=document.createElement('summary');title.textContent='Inherited workspace rules';editor.append(title);
      const rules=[...(inherited.any||[]).map((rule,index)=>({rule,label:`Included view ${index+1}`})),{rule:inherited.all||{},label:'Additional rules for every included view'}];
      rules.forEach(({rule,label})=>{
        const group=document.createElement('fieldset');group.className='field';
        const legend=document.createElement('legend');legend.textContent=label;group.append(legend);
        [['source','Sources (comma separated)','text'],['q','Tags','text'],['date_field','Date type','select'],['date_from','From date','date'],['date_to','To date','date']].forEach(([key,label,type])=>{
          const field=document.createElement('label');field.textContent=label;
          const input=document.createElement(type==='select'?'select':'input');input.className='control';
          if(type==='select') [['entry','Entry date'],['created','Created'],['updated','Updated']].forEach(([value,text])=>{const option=document.createElement('option');option.value=value;option.textContent=text;input.append(option);});else input.type=type;
          input.value=rule[key]||(key==='date_field'?'entry':'');input.setAttribute('aria-label',label+' for '+legend.textContent);
          input.addEventListener('change',()=>{rule[key]=input.value;if(!inherited.all)inherited.all=rules.at(-1).rule;scope.value=JSON.stringify(inherited);form.dispatchEvent(new Event('activitychange'));});field.append(input);group.append(field);
        });editor.append(group);
      });filters.append(editor);
    }
    const secret=form.querySelector('[data-include-secrets]');if(secret)entries.append(secret.closest('.field'));
    form.querySelectorAll('[data-share-tab]').forEach((b,i,all)=>{
      b.onclick=()=>selectTab(b.dataset.shareTab);
      b.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?all.length-1:(i+(e.key==='ArrowRight'?1:-1)+all.length)%all.length;all[next].click();all[next].focus();};
    });
    form.querySelector('[data-replace-workspace]').onclick=()=>{
      if(scope)scope.value='';form.querySelector('[name="workspace_ids"]').value='';
      filters.querySelector('[data-inherited-rules]')?.remove();
      form.querySelector('[data-workspace-reset]').hidden = true;
      form.dispatchEvent(new Event('activitychange'));
    };
    form.addEventListener('change',e=>{
      const input=e.target;
      if(input.matches('[data-share-object]')){
        const hidden=document.createElement('input');hidden.type='hidden';hidden.name='excluded_object_ids';hidden.value=input.dataset.shareObject;form.querySelector('[data-object-exclusions]').append(hidden);form.dispatchEvent(new Event('activitychange'));
      }
      if(input.matches('[data-outside-board]')){
        const box=form.querySelector('[data-outside-board-values]');[...box.children].filter(v=>v.value===input.dataset.outsideBoard).forEach(v=>v.remove());
        if(input.checked){const hidden=document.createElement('input');hidden.type='hidden';hidden.name='outside_board_ids';hidden.value=input.dataset.outsideBoard;box.append(hidden);}form.dispatchEvent(new Event('activitychange'));
      }
      if(input.matches('[data-activity-control]'))form.dispatchEvent(new Event('activitychange'));
      window.refreshShareActivity();
    });
  }
  window.refreshShareActivity();
})();
