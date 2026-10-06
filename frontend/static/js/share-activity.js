(() => {
  'use strict';
  const form = document.querySelector('[data-social-form]');
  let active = 'recipe';
  const labels = new Map();
  const savedLabels = form?.querySelector('[name="excluded_object_labels"]');
  if (savedLabels) Object.entries(JSON.parse(savedLabels.value)).forEach(([id,label])=>labels.set(id,label));
  const selectTab = key => {
    active = key;
    form?.querySelectorAll('[data-share-tab]').forEach(b => {
      b.setAttribute('aria-selected', String(b.dataset.shareTab === key));
      b.tabIndex = b.dataset.shareTab === key ? 0 : -1;
    });
    form?.querySelectorAll('[data-share-panel], [data-preview-tab]').forEach(p => {
      p.hidden = (p.dataset.sharePanel || p.dataset.previewTab) !== key;
    });
  };
  function renderGraphs() {
    document.querySelectorAll('[data-shared-graph]').forEach(container => {
      if (container.dataset.rendered) return;
      container.dataset.rendered = '1';
      const data = JSON.parse(container.querySelector('[data-graph-data]').textContent);
      const target = container.querySelector('[data-graph-canvas]');
      if (!data.nodes.length) { target.textContent = 'No approved connections in this scope.'; return; }
      const ns = 'http://www.w3.org/2000/svg';
      const make = (tag, attrs, text) => {
        const el = document.createElementNS(ns, tag);
        Object.entries(attrs).forEach(([k,v]) => el.setAttribute(k, v));
        if (text !== undefined) el.textContent = text;
        return el;
      };
      const svg = make('svg', {viewBox:'-500 -350 1000 700', role:'img', 'aria-label':'Read-only shared activity graph', tabindex:'0'});
      const group = make('g', {}); svg.append(group);
      const pos = new Map();
      const radius = Math.max(160, data.nodes.length * 13);
      data.nodes.forEach((n, i) => {
        const saved = data.positions?.[n.id];
        pos.set(n.id, saved || {x: radius*Math.cos(i*2*Math.PI/data.nodes.length), y: radius*Math.sin(i*2*Math.PI/data.nodes.length)});
      });
      data.edges.forEach(e => {
        const a = pos.get(e.source), b = pos.get(e.target); if (!a || !b) return;
        const line = make('line', {x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#64748b','stroke-width':1.5});
        line.append(make('title', {}, e.relation)); group.append(line);
      });
      const details = document.createElement('p'); details.setAttribute('aria-live','polite');
      data.nodes.forEach(n => {
        const p = pos.get(n.id), node = make('g', {transform:`translate(${p.x},${p.y})`,tabindex:0,role:'button','aria-label':n.label});
        node.append(make('circle',{r:10,fill:n.kind==='boards'?'#c084fc':n.kind==='actions'?'#fbbf24':'#38bdf8'}));
        node.append(make('text',{x:15,y:5,fill:'#e2e8f0','font-size':14},n.label.slice(0,65)));
        const show = () => { details.textContent = n.label + (n.body ? ' — '+n.body : ''); };
        node.addEventListener('click',show); node.addEventListener('keydown',e=>{if(e.key==='Enter')show();}); group.append(node);
      });
      let scale = Math.min(1, 260/radius), dx=0, dy=0;
      const draw = () => group.setAttribute('transform',`translate(${dx},${dy}) scale(${scale})`);
      const toolbar = document.createElement('div');
      [['Zoom in',1.3],['Zoom out',1/1.3],['Reset',0]].forEach(([label,factor])=>{
        const b=document.createElement('button');b.type='button';b.textContent=label;b.className='btn btn-soft';
        b.onclick=()=>{if(factor)scale=Math.max(.02,Math.min(8,scale*factor));else{scale=Math.min(1,260/radius);dx=dy=0;}draw();};toolbar.append(b);
      });
      let drag;
      svg.addEventListener('pointerdown',e=>{if(e.target.closest('[role="button"]'))return;drag={x:e.clientX,y:e.clientY,dx,dy};svg.setPointerCapture(e.pointerId);});
      svg.addEventListener('pointermove',e=>{if(!drag)return;const ratio=1000/svg.getBoundingClientRect().width;dx=drag.dx+(e.clientX-drag.x)*ratio;dy=drag.dy+(e.clientY-drag.y)*ratio;draw();});
      svg.addEventListener('pointerup',()=>{drag=null;});draw();target.append(toolbar,svg,details);
    });
  }
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
