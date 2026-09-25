(() => {
  'use strict';
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const fields = [
    ['agent_mode','Execution permissions','select'], ['hermes_profile','Hermes profile'],
    ['agent_toolsets','Toolsets / MCP servers'], ['agent_model','Model'], ['agent_provider','Provider'],
    ['agent_repository','Repository on worker'], ['agent_base_branch','Base branch'], ['agent_host','Worker hostname'],
    ['agent_timeout_seconds','Turn timeout (seconds)','number'], ['agent_max_turns','Maximum turns','number'],
    ['agent_default_recipient','Default email recipient']
  ];
  async function api(path, payload) {
    const csrf = JSON.parse(document.querySelector('[data-memory-csrf]')?.textContent || '""');
    const response = await fetch('/hfl-corpus/agent-bridge' + path, {
      method: payload === undefined ? 'GET' : 'POST', headers: {'Content-Type':'application/json','X-CSRF-Token':csrf},
      ...(payload === undefined ? {} : {body:JSON.stringify(payload)})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Agent request failed.');
    return data;
  }
  function mount(container, sourceId, sidebar, summary) {
    const source = '/actions/' + encodeURIComponent(sourceId);
    let disposed = false, session = null, cursor = 0, config, terminal, fit, polling, sessionList = [];
    let inputQueue = [], inputTimer, sendingInput = false, lastInputAt = 0;
    async function flushInput() {
      if(sendingInput || !inputQueue.length)return;
      sendingInput=true;
      const item=inputQueue.shift();
      try { await api('/sessions/'+item.identity+'/input',{data:item.data,key:item.key}); }
      catch(e) {error.textContent='Input was not delivered: '+e.message;error.hidden=false;}
      finally {sendingInput=false;if(inputQueue.length)void flushInput();}
    }
    const root = el('section', undefined, 'action-agent-workspace'); container.append(root);
    const status = el('p','Loading last session…','agent-terminal-status'); status.setAttribute('role','status');
    const error = el('p','', 'agenda-error'); error.setAttribute('role','alert'); error.hidden = true;
    const details = el('details', undefined, 'agent-details'); details.append(el('summary','Agent details'));
    const description = el('p'); details.append(description);
    const controls = el('div', undefined, 'agent-terminal-controls');
    const sessions = el('select'); sessions.setAttribute('aria-label','Agent session'); controls.append(sessions);
    function button(label, fn, parent=controls) {
      const node = el('button',label); node.type='button';
      node.onclick=async()=>{node.disabled=true;error.hidden=true;try{await fn();}catch(e){error.textContent=e.message;error.hidden=false;}finally{node.disabled=false;}};
      parent.append(node); return node;
    }
    button('Configure agent', configure, details);
    button('New / reconnect', async()=>attach(await api(source+'/sessions',{})));
    button('Save session', async()=>{if(!session)throw new Error('Start a session first.');await api('/sessions/'+session.id,{saved:true});await refreshList();});
    button('Restore selected',async()=>{const id=sessions.value;if(!id)throw new Error('Select a session.');const selected=sessionList.find(s=>s.id===id);if(['queued','starting','idle','waiting','running'].includes(selected.state))attach(selected);else attach(await api(source+'/sessions',{restore:id}));});
    button('Remove from history',async()=>{if(!session)return;if(!window.confirm('Remove this session from history? Attached files remain on the action.'))return;await api('/sessions/'+session.id+'/forget',{});session=null;cursor=0;terminal.reset();download.hidden=true;await refreshList();});
    button('End session',async()=>{if(session)await api('/sessions/'+session.id,{closed:true});});
    const download = el('a','Download transcript'); download.hidden=true; controls.append(download);
    const viewport = el('div',undefined,'agent-terminal'); viewport.setAttribute('aria-label','Native Hermes terminal');
    const hint = el('p','Native Hermes CLI · use /help for commands. Closing this dialog leaves execution running.','agent-terminal-hint');
    if (sidebar) {
      const section = el('section', undefined, 'agent-session-section');
      section.append(el('h3','Sessions'),controls,status,error);
      sidebar.append(details,section);
      root.setAttribute('aria-label','Agent session');
      root.append(viewport,hint);
    } else root.append(details,controls,status,error,viewport,hint);
    function showConfig() {
      const s=config.effective;
      description.textContent = 'Hermes · '+(config.card.preset || 'App Settings defaults')+' · '+(s.hermes_profile || 'Worker profile')+' · '+s.agent_mode+' permissions · '+(s.agent_repository || 'Worker checkout (isolated worktree)')+' · Idle expiry '+s.agent_session_expiry_minutes+' minutes';
      if (summary && config.action) {
        const action=config.action;
        summary.replaceChildren(el('span','ACTION'),el('h3',action.title));
        const values=el('dl',undefined,'agent-action-summary');
        for(const [key,label] of [['status','Status'],['due_date','Due'],['description','Description'],['prompt','Initial prompt'],['expected_outcome','Expected outcome'],['notes','Notes'],['completion_note','Outcome']]) {
          const value=action[key];
          if(!value && key!=='prompt')continue;
          values.append(el('dt',label),el('dd',key==='status'?value.replaceAll('_',' '):(value||'No initial prompt saved.')));
        }
        summary.append(values);
      }
    }
    async function configure() {
      config=await api(source+'/configuration');
      const dialog=el('dialog',undefined,'agenda-dialog agent-config-dialog');
      const header=el('header',undefined,'agenda-dialog-header');header.append(el('h2','Configure action agent'));
      button('Close',()=>dialog.close(),header);
      const form=el('form',undefined,'agenda-form-body');
      const presetLabel=el('label','Named preset');const preset=el('select');
      preset.append(new Option('App Settings defaults',''));
      Object.keys(config.presets).forEach(name=>preset.append(new Option(name,name)));
      preset.value=config.card.preset;presetLabel.append(preset);form.append(presetLabel);
      form.append(el('p','Unchecked fields inherit the preset or App Settings and follow future changes. Checked fields are fixed for this action. Running sessions retain their current settings.'));
      const inputs={};
      for(const [key,label,type] of fields){
        const row=el('label',undefined,'agent-config-field');const override=el('input');override.type='checkbox';override.checked=Object.hasOwn(config.card.overrides,key);override.setAttribute('aria-label','Override '+label);
        const input=el(type==='select'?'select':'input');
        if(type==='select'){input.append(new Option('Trusted Hermes','trusted'),new Option('Restricted tools (local shell available)','restricted'));}else{input.type=type||'text';}
        input.setAttribute('aria-label',label);input.value=config.effective[key];input.disabled=!override.checked;
        override.onchange=()=>{input.disabled=!override.checked;};
        row.append(override,el('span',label),input);form.append(row);inputs[key]={override,input,type};
      }
      preset.onchange=()=>{for(const [key,item] of Object.entries(inputs)){if(!item.override.checked)item.input.value=config.presets[preset.value]?.overrides[key]??config.defaults[key];}};
      const values=()=>Object.fromEntries(Object.entries(inputs).filter(([,v])=>v.override.checked).map(([k,v])=>[k,v.type==='number'?Number(v.input.value):v.input.value]));
      const feedback=el('p','');feedback.setAttribute('role','alert');form.append(feedback);
      const actions=el('div',undefined,'agent-terminal-controls');form.append(actions);
      const save=el('button','Save action configuration');save.type='submit';actions.append(save);
      const presetName=el('input');presetName.placeholder='Name for reusable preset';presetName.setAttribute('aria-label','New preset name');actions.append(presetName);
      button('Save as preset',async()=>{
        try {const result=await api('/presets',{name:presetName.value,overrides:{...(config.presets[preset.value]?.overrides||{}),...values()}});config=await api(source+'/configuration');if(![...preset.options].some(o=>o.value===result.name))preset.append(new Option(result.name,result.name));preset.value=result.name;Object.values(inputs).forEach(item=>{item.override.checked=false;item.input.disabled=true;});feedback.textContent='Preset saved. Save action configuration to assign it.';}catch(e){feedback.textContent=e.message;}
      },actions);
      form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{config=await api(source+'/configuration',{preset:preset.value,overrides:values()});showConfig();dialog.close();}catch(e){feedback.textContent=e.message;}finally{save.disabled=false;}};
      dialog.append(header,form);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
    }
    function attach(item){
      session=item;cursor=0;terminal?.reset();download.hidden=false;download.href='/hfl-corpus/agent-bridge/sessions/'+item.id+'/transcript';
      if(![...sessions.options].some(o=>o.value===item.id))sessions.append(new Option(new Date(item.created).toLocaleString()+' · '+item.state,item.id));
      sessions.value=item.id;status.textContent='Loading session…';
      if(terminal)api('/sessions/'+item.id,{cols:Math.max(10,Math.min(300,terminal.cols)),rows:Math.max(10,Math.min(300,terminal.rows))}).catch(()=>{});
    }
    async function refreshList(){
      const data=await api(source+'/sessions');if(disposed)return;
      sessionList=data.sessions;const selected=sessions.value;sessions.replaceChildren();
      sessions.append(new Option('Select a session',''));
      for(const item of data.sessions)sessions.append(new Option((item.saved?'Saved · ':'')+new Date(item.created).toLocaleString()+' · '+item.state,item.id));
      sessions.value=selected||session?.id||'';
      return data;
    }
    let lastListRefresh=0, pollingBusy=false;
    async function poll(){
      if(disposed||pollingBusy)return;
      pollingBusy=true;
      try{
        if(session){
          const identity=session.id;
          const data=await api('/sessions/'+identity+'?after='+cursor);
          if(disposed||session?.id!==identity)return;
          session=data.session;
          for(const chunk of data.output){terminal.write(chunk.data);cursor=chunk.seq;}
          const labels={queued:'Waiting for a worker to connect…',starting:'Starting Hermes…',idle:'Ready for commands',waiting:'Worker capacity reached — waiting for an execution slot…',running:'Running — waiting for reply',expired:'Session expired — transcript archived',closed:'Session closed — transcript archived',failed:'Session stopped — transcript available'};
          status.textContent=session.error||labels[session.state]||session.state;
          terminal.options.disableStdin=!['starting','idle','waiting','running'].includes(session.state);
        }
        if(Date.now()-lastListRefresh>=4000){lastListRefresh=Date.now();const data=await refreshList();if(data&&session&&session.state==='waiting')status.textContent+=' '+data.busy+'/'+data.capacity+' executions active.';}
      }catch(e){status.textContent='Reconnecting…';error.textContent=e.message;error.hidden=false;}
      finally{pollingBusy=false;if(!disposed)polling=setTimeout(poll,Date.now()-lastInputAt<3000||session?.state==='running'?75:400);}
    }
    const observer=new ResizeObserver(()=>{
      if(!terminal||!fit||disposed)return;
      fit.fit();terminal.resize(Math.max(10,Math.min(300,terminal.cols)),Math.max(10,Math.min(300,terminal.rows)));if(session)api('/sessions/'+session.id,{cols:terminal.cols,rows:terminal.rows}).catch(()=>{});
    });
    (async()=>{
      try{
        config=await api(source+'/configuration');if(disposed)return;showConfig();
        terminal=new Terminal({cursorBlink:true,convertEol:false,scrollback:10000,fontSize:14,fontFamily:'Consolas, "Liberation Mono", Menlo, monospace',lineHeight:1.15,theme:{background:'#080f1e',foreground:'#e2e8f0'}});
        fit=new FitAddon.FitAddon();terminal.loadAddon(fit);terminal.open(viewport);fit.fit();observer.observe(viewport);
        terminal.onData(data=>{
          if(!session)return;lastInputAt=Date.now();
          if(!pollingBusy){clearTimeout(polling);polling=setTimeout(poll,0);}
          const pending=inputQueue.at(-1);
          if(pending?.identity===session.id && pending.data.length+data.length<=65536)pending.data+=data;
          else inputQueue.push({identity:session.id,key:crypto.randomUUID(),data});
          clearTimeout(inputTimer);inputTimer=setTimeout(flushInput,16);
        });
        sessions.onchange=()=>{const item=sessionList.find(s=>s.id===sessions.value);if(item)attach(item);};
        const data=await refreshList();if(disposed)return;
        if(data.sessions.length)attach(data.sessions[0]);else status.textContent='Start a native Hermes session, or use Run now for the Initial prompt.';
        await poll();
      }catch(e){error.textContent=e.message;error.hidden=false;status.textContent='Workspace could not be loaded.';}
    })();
    return ()=>{disposed=true;clearTimeout(polling);clearTimeout(inputTimer);void flushInput();observer.disconnect();terminal?.dispose();};
  }
  window.actionAgentWorkspace={mount};
})();
