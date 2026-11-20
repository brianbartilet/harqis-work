/* User-scoped connections and provider operations. Provider text is always rendered as text. */
(() => {
  'use strict';
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const csrf=()=>JSON.parse(document.querySelector('[data-integration-csrf], [data-memory-csrf]')?.textContent||'""');
  async function api(path,payload){
    const response=await fetch('/integrations/api'+path,{method:payload===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
    let result;try{result=await response.json();}catch(_){throw new Error('The integration service is unavailable. Refresh before retrying.');}
    if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Check the fields and try again.');return result;
  }
  function button(parent,label,run){const b=el('button',label);b.type='button';parent.append(b);b.onclick=async()=>{b.disabled=true;try{await run();}catch(e){const alert=parent.closest('.github-action-controls')?.querySelector('[role=alert]')||[...document.querySelectorAll('.integration-dialog[open] [role=alert]')].at(-1)||parent.closest('dialog')?.querySelector('[role=alert]')||document.querySelector('[data-integration-error]')||parent.appendChild(el('p'));alert.setAttribute('role','alert');alert.textContent=e.message;}finally{if(!b.hasAttribute('data-managed-disabled'))b.disabled=false;}};return b;}
  function field(parent,label,type='text',value=''){const l=el('label',label),input=el(type==='textarea'?'textarea':type==='select'?'select':'input');if(input.tagName==='INPUT')input.type=type;input.value=value;input.setAttribute('aria-label',label);l.append(input);parent.append(l);return input;}
  function link(parent,label,url){const a=el('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);return a;}
  function dialog(title){const opener=document.activeElement,d=el('dialog',undefined,'integration-dialog'),h=el('header');d.setAttribute('aria-label',title);const heading=el('h2',title);heading.tabIndex=-1;h.append(heading);const close=button(h,'',()=>d.close());close.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"></path></svg>';close.classList.add('integration-dialog-close');close.setAttribute('aria-label','Close');close.title='Close';d.append(h);const body=el('div'),error=el('p');error.setAttribute('role','alert');d.append(body,error);document.body.append(d);d.addEventListener('close',()=>{d.remove();if(opener?.isConnected)opener.focus();},{once:true});d.showModal();heading.focus();return {d,body,error};}
  const controls=parent=>parent.appendChild(el('div',undefined,'integration-controls'));
  let current=[], cardLinks=[];
  function badges(parent,identity){parent.querySelectorAll("[data-connector-summary]").forEach(n=>n.remove());for(const row of cardLinks.filter(r=>r.action_id===identity&&r.provider==='jira')){const text=row.provider==='jira'?row.issue_key+' · '+row.jira_status:row.branch+(row.pr_number?' · PR #'+row.pr_number+' · '+row.pr_state:'');const badge=el('span',text,'action-status');badge.dataset.connectorSummary=identity;parent.append(badge);}}
  async function load(){
    const snapshot=await api('/connectors');current=snapshot.items;cardLinks=snapshot.links||[];
    const root=document.querySelector('[data-connector-cards]');
    document.querySelectorAll('[data-connector-count]').forEach(n=>n.textContent=current.length);
    if(root){root.replaceChildren();for(const item of current){
      const card=el('article',undefined,'connector-card'),header=el('header');const title=el('h2',undefined,'connector-title');
      const logoUrl={codex:root.dataset.codexLogo,nod:root.dataset.nodLogo,github:root.dataset.githubLogo,jira:root.dataset.jiraLogo,n8n:root.dataset.n8nLogo,grokbot:root.dataset.grokbotLogo}[item.provider];
      if(logoUrl){const logo=el('img',undefined,'connector-logo');logo.src=logoUrl;logo.alt='';logo.width=20;logo.height=20;logo.onerror=()=>logo.remove();title.append(logo);}
      title.append(document.createTextNode(item.name));header.append(title);
      const headerControls=el('div',undefined,'connector-header-controls');header.append(headerControls);
      const connectLabel=item.provider==='grokbot'?'Configure Grok Bot':item.status==='Connected'?'Reconnect / test':'Connect';
      const connect=button(headerControls,'',()=>setup(item));connect.classList.add('connector-connect');connect.setAttribute('aria-label',connectLabel);connect.title=connectLabel;
      connect.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m13 2-9 12h7l-1 8 10-12h-7l1-8Z"/></svg>';
      const disconnect=button(headerControls,'',async()=>{const confirm=dialog('Disconnect '+item.name);confirm.body.append(el('p','Remove this connection’s saved credentials? Imported cards and links remain; reconnect the same account to use them again.'));button(controls(confirm.body),'Disconnect account',async()=>{await api('/connectors/'+item.provider+'/disconnect',{});confirm.d.close();await load();});});
      disconnect.classList.add('connector-disconnect');disconnect.setAttribute('aria-label','Disconnect '+item.name);disconnect.title='Disconnect '+item.name;disconnect.disabled=!item.account;
      disconnect.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m19 5 3-3M2 22l3-3M6.3 20.3a2.4 2.4 0 0 0 3.4 0L12 18l-6-6-2.3 2.3a2.4 2.4 0 0 0 0 3.4ZM7.5 13.5 10 11m.5 5.5L13 14M18 12l2.3-2.3a2.4 2.4 0 0 0 0-3.4l-2.6-2.6a2.4 2.4 0 0 0-3.4 0L12 6Z"/></svg>';
      const toggle=el('button',undefined,'connector-switch');toggle.type='button';toggle.setAttribute('role','switch');toggle.setAttribute('aria-checked',String(item.enabled));toggle.setAttribute('aria-label','Enable '+item.name);
      const track=el('span',undefined,'connector-switch-track');track.setAttribute('aria-hidden','true');toggle.append(track);headerControls.append(toggle);card.append(header);
      toggle.onclick=async()=>{toggle.disabled=true;try{if(!item.enabled&&item.status!=='Connected'){setup(item);}else{const result=await api('/connectors/'+item.provider+'/toggle',{enabled:!item.enabled});await load();document.querySelector('[data-integration-error]').textContent=result.discovery_warning||(result.discovery?.warnings||[]).join(' ');}}catch(e){document.querySelector('[data-integration-error]').textContent=e.message;}finally{toggle.disabled=false;}};
      const status=el('span',item.status,'connector-status');status.dataset.connected=String(item.status==='Connected');status.dataset.error=String(Boolean(item.error));status.setAttribute('role','status');card.append(status);
      if(item.provider==='grokbot'&&item.last_sync)card.append(el('p','Last discovery: '+new Date(item.last_sync).toLocaleString()+' · '+item.bot_count+' Bots','connector-discovery'));
      if(item.account)card.append(el('p',item.account+' · '+item.auth_method),el('p','Connected since '+new Date(item.connected_since).toLocaleDateString()+' · Expiry: '+item.expiry));
      if(item.error)card.append(el('p',item.error));
      const capabilities=el('ul');item.capabilities.forEach(c=>capabilities.append(el('li',c)));card.append(capabilities);
      if(item.enabled&&item.provider==='jira'){const footer=el('footer',undefined,'connector-footer');card.append(footer);button(controls(footer),'Import assigned issues',jiraImport);}
      if(item.provider==='grokbot'){
        const footer=el('footer',undefined,'connector-footer');card.append(footer);const row=controls(footer);
        button(row,item.account?'Reconnect':'Connect',()=>setup(item));
        if(item.enabled){button(row,'Refresh Bots',async()=>{await api('/grokbot/sync',{});await load();});link(row,'View fleet','/agents?integration=grokbot');}
      }
      if(item.enabled&&item.provider==='codex'){const footer=el('footer',undefined,'connector-footer');card.append(footer);const row=controls(footer);button(row,'Open in Fleet',async()=>{const result=await api('/codex/link',{});location.href='/agents?agent='+encodeURIComponent(result.item.id);});}
      if(item.enabled&&item.provider==='nod'){const footer=el('footer',undefined,'connector-footer');card.append(footer);const row=controls(footer);button(row,'Open in Fleet',async()=>{const result=await api('/nod/link',{});location.href='/agents?agent='+encodeURIComponent(result.item.id);});link(row,'Open Nod',item.site);}
      if(item.enabled&&item.provider==='n8n'){
        const footer=el('footer',undefined,'connector-footer');card.append(footer);const row=controls(footer);
        link(row,'Open in Fleet','/agents?integration=n8n');
        button(row,'Sync inventory',async()=>{const view=dialog('Synchronize n8n inventory'),query=field(view.body,'Agent search');button(controls(view.body),'Search and synchronize',async()=>{const result=await api('/n8n/sync',{query:query.value});view.body.append(el('p',result.imported+' agents and '+result.workflows+' workflows synchronized. '+(result.warnings||[]).join(' ')));link(view.body,'Open agent fleet','/agents?integration=n8n');});});
        button(row,'Browse workflows',async()=>{const view=dialog('n8n workflows');let cursor='';const next=button(controls(view.body),'Load workflows',async()=>{const data=await api('/n8n/workflows?cursor='+encodeURIComponent(cursor));for(const workflow of data.items)link(view.body,workflow.name+(workflow.active?' · Active':''),(item.public_url||item.site)+'/workflow/'+encodeURIComponent(workflow.id));cursor=data.cursor;next.hidden=!cursor;});next.click();});
      }
      root.append(card);
    }}
    document.querySelectorAll('[data-connector-action]').forEach(b=>{b.hidden=!current.some(c=>c.provider==='jira'&&c.enabled);badges(b.parentElement,b.dataset.connectorAction);});
    window.dispatchEvent(new CustomEvent('integrations:changed',{detail:current}));
  }
  function grokbotSetup(){
    const {d,body,error}=dialog('Connect Grok Bot');
    body.append(el('p','Experimental read-only discovery. Sign in through Cursor or use a Cursor user API key. A successful connection immediately adds your Bots to the fleet.'));
    const state=el('p','Choose a sign-in method.','integration-warning');state.setAttribute('role','status');state.setAttribute('aria-live','polite');body.append(state);
    let attempt='',timer,closed=false,busy=false;
    const browserArea=el('div');body.append(browserArea);
    const links=el('div');browserArea.append(links);
    async function cancel(){clearTimeout(timer);retry.hidden=true;const id=attempt;attempt='';if(id)await api('/grokbot/login/'+id+'/cancel',{}).catch(()=>{});}
    async function poll(id){
      if(closed||!id||attempt!==id)return;
      clearTimeout(timer);error.textContent='';
      try{
        const result=await api('/grokbot/login/'+id+'/poll',{});
        if(closed||attempt!==id)return;
        if(result.status==='Connected'){attempt='';state.textContent=result.imported+' Bots discovered.';await load();d.close();return;}
        timer=setTimeout(()=>poll(id),3000);
      }catch(e){if(!closed&&attempt===id){error.textContent=e.message;state.textContent='Sign-in paused. Retry checking, or start again.';retry.hidden=false;}}
    }
    button(controls(browserArea),'Sign in with browser',async()=>{
      if(busy)return;busy=true;error.textContent='';await cancel();links.replaceChildren();
      try{
        const result=await api('/grokbot/login/start',{});
        if(closed){await api('/grokbot/login/'+result.attempt_id+'/cancel',{});return;}
        attempt=result.attempt_id;link(links,'Continue on Cursor',result.url);
        state.textContent='Open Continue on Cursor to sign in. This window will discover your Bots when you finish. Expires in 10 minutes.';
        retry.hidden=true;timer=setTimeout(()=>poll(attempt),3000);
      }finally{busy=false;}
    });
    const retry=button(controls(browserArea),'Check sign-in again',()=>poll(attempt));retry.hidden=true;
    const details=el('details',undefined,'grokbot-key-choice');const summary=el('summary','Use a Cursor API key instead');summary.insertAdjacentHTML('beforeend','<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 7.5 5 5 5-5"/></svg>');details.append(summary);body.append(details);
    details.append(el('p','Use a Cursor user API key. xAI inference keys do not provide Bot access. The key is exchanged for encrypted sign-in tokens and is not saved.'));
    const key=field(details,'Cursor API key','password');key.autocomplete='new-password';key.maxLength=4096;
    button(controls(details),'Connect with API key',async()=>{
      if(busy)return;busy=true;error.textContent='';await cancel();links.replaceChildren();state.textContent='Connecting and discovering Bots…';
      const value=key.value;key.value='';key.disabled=true;
      try{const result=await api('/grokbot/connect-key',{key:value});if(!closed){state.textContent=result.imported+' Bots discovered.';await load();d.close();}}
      catch(e){if(!closed)state.textContent='Connection failed. Your previous connection is unchanged.';throw e;}
      finally{busy=false;key.disabled=false;}
    });
    d.addEventListener('close',()=>{closed=true;key.value='';cancel();},{once:true});
  }
  function codexSetup(item){
    const {d,body,error}=dialog('Connect Codex');
    body.append(el('p','Observe Codex installed on the HARQIS server host. This reads saved tasks and installed local plugins using the host’s existing sign-in. It does not start tasks or control a desktop session.'));
    const setupHelp=el('div',undefined,'codex-setup-help');setupHelp.hidden=true;
    const helpButton=button(controls(body),'Host setup instructions',()=>{setupHelp.hidden=!setupHelp.hidden;helpButton.setAttribute('aria-expanded',String(!setupHelp.hidden));});helpButton.setAttribute('aria-expanded','false');
    setupHelp.append(el('p','An administrator can inspect a configured remote host with:'));
    setupHelp.append(el('code','python scripts/setup_codex.py --remote <machine-key>'));
    setupHelp.append(el('p','To install only if missing, add --install. On the HARQIS host itself, omit --remote <machine-key>. Existing installations are reused. Automatic installation supports macOS/Linux.'));
    setupHelp.append(el('p','If Codex is installed but cannot be found, set HARQIS_CODEX_BINARY in machines.local.toml under the frontend host’s [<machine-profile>.env_vars] section. Use an absolute path on that host, not the computer running this browser. For example:'));
    setupHelp.append(el('pre','[<machine-profile>.env_vars]\nHARQIS_CODEX_BINARY = "/absolute/path/to/codex"'));
    setupHelp.append(el('p','Managed macOS/Linux installs commonly use ~/.codex/packages/app-server-daemon/current/bin/codex or ~/.codex/packages/standalone/current/bin/codex. Expand ~ to the service user’s home directory. On Windows, use the native codex.exe; forward slashes work in TOML paths.'));
    setupHelp.append(el('p','Sync machines.local.toml to the host if edited elsewhere, then restart the frontend from its checkout:'));
    setupHelp.append(el('code','python scripts/deploy.py --restart frontend'));
    setupHelp.append(el('p','If setup reports that sign-in is required, run its login command on the host as the HARQIS service user. Return here, select Test local host, then Save and enable.'));
    body.append(setupHelp);
    const state=el('p','Not tested','connector-status');state.setAttribute('role','status');body.append(state);
    const row=controls(body);let tested=false;
    const test=button(row,'Test local host',async()=>{tested=false;save.disabled=true;state.textContent='Testing…';try{const value=await api('/connectors/codex/test',{transport:'local'});tested=true;state.textContent='Test passed · '+value.account;}catch(e){state.textContent='Connection unavailable';setupHelp.hidden=false;helpButton.setAttribute('aria-expanded','true');throw e;}finally{save.disabled=!tested;}});
    const save=button(row,'Save and enable',async()=>{if(!tested)return;test.disabled=true;save.disabled=true;try{await api('/connectors/codex/save',{transport:'local'});const result=await api('/connectors/codex/toggle',{enabled:true});d.close();await load();document.querySelector('[data-integration-error]').textContent=(result.discovery?.warnings||[]).join(' ');}catch(e){state.textContent='Save or discovery failed. Test the host again.';tested=false;throw e;}finally{test.disabled=false;save.disabled=!tested;}});
    save.setAttribute('data-managed-disabled','');save.disabled=true;
  }
  function setup(item){
    if(item.provider==='grokbot'){grokbotSetup();return;}
    if(item.provider==='codex'){codexSetup(item);return;}
    const {d,body,error}=dialog('Connect '+item.name);
    body.append(el('p','Test your credentials, then save the connection. Testing does not save credentials. Saved credentials are encrypted and separate from workflow accounts.'));
    if(item.provider==='github'){
      body.append(el('p','Create a fine-grained personal access token for the selected repositories. Grant Contents: read/write and Pull requests: read/write for branch and PR operations. Organization approval may be required. Account MFA stays on GitHub.'));
      link(body,'GitHub token setup instructions','https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens');
      body.append(el('p','Alternative for a later release: a GitHub App installation with short-lived tokens.'));
    }else if(item.provider==='nod'){body.append(el('p','Connect your self-hosted Nod server using its NOD_AUTH_TOKEN. Your desktop app’s private local runtime is separate. Messages in Fleet can start work using Nod’s connected apps.'));link(body,'Nod server setup','https://nod.n8n.io/docs/deploy/self-host/');}else if(item.provider==='n8n'){
      body.append(el('p','Use an n8n API key for workflows. Add a separate instance-level MCP token to discover first-class agents. Enable Agents and MCP access in n8n.'));
      link(body,'n8n connection documentation','https://docs.n8n.io/connect/connect-to-n8n-mcp-server/');
    }else{
      body.append(el('p','Create an Atlassian API token. Your Jira account needs Browse Projects and Transition Issues permissions. API tokens work with two-step verification; do not enter a password or MFA code. Scoped tokens also require your cloud ID.'));
      link(body,'Atlassian token setup instructions','https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/');
      body.append(el('p','Alternative for a later release: OAuth 2.0 authorization with refresh tokens.'));
    }
    const site=['jira','n8n','nod'].includes(item.provider)?field(body,item.provider==='nod'?'Nod server URL':item.provider==='n8n'?'n8n instance URL':'Jira Cloud site','url',item.site||''):null;
    const publicUrl=item.provider==='n8n'?field(body,'Browser URL (optional; used for opening n8n)','url',item.public_url||''):null;
    const email=item.provider==='jira'?field(body,'Atlassian email','email'):null;
    const cloud=item.provider==='jira'?field(body,'Cloud ID (scoped tokens only)'):null;
    const token=field(body,item.provider==='nod'?'Nod server token':'API token','password');token.autocomplete='new-password';token.maxLength=4096;
    const mcp=item.provider==='n8n'?field(body,'MCP token (optional)','password'):null;
    const state=el('span','Not tested','connector-status');state.setAttribute('role','status');state.setAttribute('aria-live','polite');body.append(state);
    const row=controls(body),inputs=[token,site,email,cloud,mcp,publicUrl].filter(Boolean);
    let tested=false,busy=false;
    function status(text,tone){state.textContent=text;state.dataset.tone=tone;}
    function lock(value){busy=value;inputs.forEach(input=>input.disabled=value);test.disabled=value;save.disabled=value||!tested;}
    const payload=()=>({token:token.value,...(site?{site:site.value}:{}),...(email?{email:email.value,cloud_id:cloud.value}:{}),...(mcp?{mcp_token:mcp.value}:{}),...(publicUrl?{public_url:publicUrl.value}:{})});
    const test=button(row,'Test',async()=>{
      error.textContent='';tested=false;lock(true);status('Testing…','pending');
      try{await api('/connectors/'+item.provider+'/test',payload());tested=true;status('Test passed · Not saved','success');}
      catch(e){status('Test failed','error');throw e;}
      finally{lock(false);}
    });
    const save=button(row,'Save',async()=>{
      if(!tested||busy)return;
      error.textContent='';lock(true);status('Saving…','pending');
      try{
        await api('/connectors/'+item.provider+'/save',payload());token.value='';if(mcp)mcp.value='';tested=false;status('Saved · Connected','success');
        lock(true);
        button(row,'Enable connector',async()=>{const result=await api('/connectors/'+item.provider+'/toggle',{enabled:true});d.close();await load();document.querySelector('[data-integration-error]').textContent=result.discovery_warning||(result.discovery?.warnings||[]).join(' ');});
        await load();
      }catch(e){tested=false;status('Save failed · Test again','error');lock(false);throw e;}
    });
    save.setAttribute('data-managed-disabled','');save.disabled=true;
    inputs.forEach(input=>input.addEventListener('input',()=>{tested=false;save.disabled=true;status('Not tested','neutral');error.textContent='';}));

  }
  async function repoPicker(parent){
    const select=field(parent,'Repository','select');select.append(new Option('Choose a repository',''));let page=1;
    const more=button(controls(parent),'More repositories',next);
    async function next(){const data=await api('/github/repositories?page='+page);for(const r of data.items){const o=new Option(r.name,r.name);o.dataset.base=r.default_branch;select.append(o);}page++;more.hidden=!data.more;}
    await next();return select;
  }
  async function jiraImport(){
    const {d,body}=dialog('Import assigned Jira issues');body.append(el('p','Import issues assigned to your connected Jira account. Jira To Do maps to Ready, In Progress maps to In Progress, and Done maps to Done. Repeated imports update the existing cards.'));
    const projects=field(body,'Project','select');projects.append(new Option('Choose a project',''));let offset=0;
    const more=button(controls(body),'More projects',nextProjects);
    async function nextProjects(){const data=await api('/jira/projects?start='+offset);for(const p of data.items)projects.append(new Option(p.name+' ('+p.key+')',p.key));offset+=data.items.length;more.hidden=!data.more;}
    await nextProjects();
    const boards=field(body,'Destination board','select');boards.append(new Option('All actions (no board)',''));
    for(const b of (await api('/boards')).items)boards.append(new Option(b.name,b.id));
    let cursor='',selection='';const status=el('p');status.setAttribute('role','status');body.append(status);
    const run=button(controls(body),'Import / refresh',async()=>{const nextSelection=projects.value+':'+boards.value;if(nextSelection!==selection)cursor='';selection=nextSelection;const data=await api('/jira/import',{project:projects.value,board_ids:boards.value?[boards.value]:[],cursor});cursor=data.cursor;status.textContent=data.items.length+' issues imported or refreshed.';run.textContent=cursor?'Import next page':'Import / refresh';window.dispatchEvent(new Event('hfl:actions-updated'));});
    link(body,'Open Kanban','/hfl-corpus/actions');
  }
  async function githubIdeas(){
    const {d,body}=dialog('Explore GitHub work');const repo=await repoPicker(body),list=el('div');body.append(list);let page=1,ticket=0;
    const more=button(controls(body),'More branches and PRs',()=>read(false));more.hidden=true;
    repo.onchange=()=>read(true).catch(e=>{d.querySelector('[role=alert]').textContent=e.message;});
    async function read(reset){const mine=++ticket;if(reset){page=1;list.replaceChildren();}const result=await api('/github/resources?'+new URLSearchParams({repository_name:repo.value,page}));if(mine!==ticket||!d.open)return;page++;more.hidden=!result.more;
      for(const [kind,value,title] of [...result.pulls.map(p=>['pr',p.number,'PR #'+p.number+' · '+p.title]),...result.branches.map(b=>['branch',b,'Branch · '+b])])button(list,title,async()=>{const raw={repository:repo.value,kind,value};const result=await api('/github/ideas',raw);const preview=dialog('Preview idea');preview.body.append(el('h3',result.draft.title),el('pre',result.draft.body));button(controls(preview.body),'Save idea',async()=>{await api('/github/ideas',{...raw,save:true});preview.d.close();window.dispatchEvent(new Event('hfl:ideas-updated'));});});
      if(!result.branches.length&&!result.pulls.length)list.append(el('p','No branches or open pull requests.','integration-empty'));
    }
  }
  function searchableBranches(select,label,noun='branches'){
    select.hidden=true;select.removeAttribute('aria-label');
    const host=select.parentElement;host.classList.add('github-search-picker');
    const input=el('input');input.type='text';input.autocomplete='off';input.placeholder='Search '+noun+'…';
    input.setAttribute('role','combobox');input.setAttribute('aria-label',label);input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');
    const list=el('div',undefined,'github-branch-options');list.id='branch-options-'+crypto.randomUUID();list.setAttribute('role','listbox');list.setAttribute('aria-label',label+' results');list.hidden=true;
    input.setAttribute('aria-controls',list.id);host.append(input,list);select.pickerInput=input;
    let matches=[],active=-1;
    function close(){list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');input.value=select.value?select.selectedOptions[0].text:'';}
    function choose(value){select.value=value;select.setCustomValidity('');input.setCustomValidity('');close();input.focus();select.dispatchEvent(new Event('change',{bubbles:true}));}
    function paint(){
      list.replaceChildren();active=-1;input.removeAttribute('aria-activedescendant');
      const query=input.value.toLocaleLowerCase();
      const all=[...select.options].filter(option=>option.value&&option.text.toLocaleLowerCase().includes(query));matches=all.slice(0,100);
      matches.forEach((option,index)=>{
        const row=el('button',option.text);row.type='button';row.tabIndex=-1;row.id=list.id+'-'+index;row.setAttribute('role','option');row.setAttribute('aria-selected',String(option.value===select.value));
        row.onpointerdown=event=>event.preventDefault();row.onclick=event=>{event.preventDefault();choose(option.value);};list.append(row);
      });
      if(!matches.length)list.append(el('p','No matching '+noun+'.'));
      if(all.length>matches.length)list.append(el('p','Type more to narrow the results.'));
      list.hidden=false;input.setAttribute('aria-expanded','true');
    }
    input.onfocus=()=>{input.value='';paint();};input.oninput=()=>{input.setCustomValidity('');paint();};input.onblur=close;
    input.onclick=()=>{if(list.hidden){input.value='';paint();}};
    input.onkeydown=event=>{
      if(event.key==='Escape'&&!list.hidden){event.preventDefault();event.stopPropagation();close();return;}
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){
        event.preventDefault();if(list.hidden)paint();if(!matches.length)return;
        active=(active+(event.key==='ArrowDown'?1:-1)+matches.length)%matches.length;
        const rows=[...list.querySelectorAll('[role=option]')];rows.forEach((row,i)=>row.setAttribute('aria-selected',String(i===active)));
        input.setAttribute('aria-activedescendant',rows[active].id);rows[active].scrollIntoView({block:'nearest'});
      }else if(event.key==='Enter'&&!list.hidden){event.preventDefault();if(active>=0)choose(matches[active].value);else if(matches.length===1)choose(matches[0].value);}
    };
    select.syncPicker=close;
  }
  async function githubControls(body,item,refresh){
    const refreshed=await api('/actions/'+item.id+'/github');
    body.append(el('p','Choose a repository → link a branch → open a pull request.','github-flow'));
    const add=el('details',undefined,'github-branch-picker');add.open=!refreshed.items.length;
    add.append(el('summary',refreshed.items.length?'Link another branch':'Repository and branch'));body.append(add);
    const form=el('div');add.append(form);
    const repo=await repoPicker(form);
    const fields=el('fieldset');fields.disabled=true;form.append(fields);
    fields.append(el('legend','Link a branch to this action'));
    const mode=field(fields,'Branch action','select');
    mode.append(new Option('Link an existing branch','link-branch'),new Option('Create a new branch','create-branch'));
    const branch=field(fields,'Branch');branch.placeholder='feature/my-change';
    const existing=field(fields,'Existing branch','select');
    const base=field(fields,'Base branch','select');
    searchableBranches(existing,'Existing branch');searchableBranches(base,'Base branch');
    const branchStatus=el('p');branchStatus.setAttribute('aria-live','polite');form.append(branchStatus);
    const paging=controls(form);paging.hidden=true;
    let revision=0,page=1;
    const retry=button(paging,'Retry loading branches',()=>readBranches(false));
    const explanation=el('p');fields.append(explanation);
    const submit=button(controls(fields),'Link',async()=>{
      const create=mode.value==='create-branch',source=create?branch:existing;
      if(!source.value.trim()){const input=source.pickerInput||source;input.setCustomValidity(create?'Enter a new branch name.':'Choose a branch.');input.reportValidity();return;}
      const target=create?base.value:repo.selectedOptions[0]?.dataset.base;
      if(!target){base.pickerInput.setCustomValidity('Choose a base branch.');base.pickerInput.reportValidity();return;}
      await api('/actions/'+item.id+'/github/branch',{repository:repo.value,branch:source.value,base:target,operation:mode.value});
      await load();await refresh();
    });
    for(const input of [branch,existing,base])input.oninput=()=>input.setCustomValidity('');
    function setMode(){
      const create=mode.value==='create-branch';branch.parentElement.hidden=!create;existing.parentElement.hidden=create;base.parentElement.hidden=!create;
      submit.textContent=create?'Save':'Link';
      explanation.textContent=create?'Creates a new branch from the selected base branch and links it to this action.':'Links the selected branch to this action.';
    }
    function resetBranches(){
      existing.replaceChildren(new Option('Choose a branch',''));base.replaceChildren(new Option('Choose a base branch',''));
      existing.syncPicker();base.syncPicker();
      page=1;paging.hidden=true;
    }
    async function readBranches(reset){
      const ticket=++revision,repository=repo.value;
      if(reset)resetBranches();
      if(!repository){fields.disabled=true;branchStatus.textContent='';return;}
      fields.disabled=true;paging.hidden=true;branchStatus.textContent='Loading branches…';
      try{
        let hasMore;
        do{
        const data=await api('/github/branches?'+new URLSearchParams({repository_name:repository,page}));
        if(ticket!==revision||!body.isConnected)return;
        for(const name of data.items){
          if(![...existing.options].some(option=>option.value===name)){
            existing.append(new Option(name,name));base.append(new Option(name,name));
          }
        }
        const defaultBranch=repo.selectedOptions[0]?.dataset.base;
        if(!base.value&&[...base.options].some(option=>option.value===defaultBranch))base.value=defaultBranch;
        existing.syncPicker();base.syncPicker();
        page++;hasMore=data.more;
        }while(hasMore);
        fields.disabled=existing.options.length===1;
        branchStatus.textContent=fields.disabled?'This repository has no branches. Create its first commit on GitHub to get started.':'';
      }catch(error){
        if(ticket!==revision||!body.isConnected)return;
        branchStatus.textContent=error.message;paging.hidden=false;
      }
    }
    mode.onchange=setMode;setMode();resetBranches();
    repo.onchange=()=>{branch.value='';for(const input of [branch,existing,base])input.setCustomValidity('');void readBranches(true);};
    body.append(el('h3','Linked branches and pull requests'));
    if(!refreshed.items.length)body.append(el('p','No branches linked yet.','integration-empty'));
    for(const branchLink of refreshed.items){
      const section=el('section',undefined,'connector-link github-branch-card');body.append(section);
      section.append(el('p',branchLink.repository,'github-repository-name'));
      link(section,branchLink.branch,branchLink.url);
      section.append(el('p',branchLink.branch+' → '+branchLink.base,'github-branch-target'));
      if(branchLink.pr_number){
        const row=controls(section);link(row,'PR #'+branchLink.pr_number,branchLink.pr_url);
        row.append(el('span',branchLink.pr_state==='open'&&branchLink.draft?'Draft':branchLink.pr_state,'connector-status'));
        if(branchLink.draft&&branchLink.pr_state==='open'){
          section.append(el('p','The draft is saved on GitHub. Mark it ready for review there when your changes are ready.'));
          link(section,'Review and publish on GitHub',branchLink.pr_url);
        }
        continue;
      }
      section.append(el('p','Branch linked · No pull request yet'));
      const details=el('details',undefined,'github-pr-editor');details.append(el('summary','Add a pull request'));section.append(details);
      const prMode=field(details,'Pull request action','select');
      prMode.append(new Option('Publish a pull request','create'),new Option('Link an existing pull request','link'));
      const number=field(details,'Pull request','select');number.append(new Option('Choose a pull request',''));
      searchableBranches(number,'Pull request','pull requests');
      const prStatus=el('p');prStatus.setAttribute('aria-live','polite');details.append(prStatus);
      const retryRow=controls(details);retryRow.hidden=true;
      button(retryRow,'Retry loading pull requests',readPulls);
      let prLoaded=false,prLoading=false,prFailed=false;
      async function readPulls(){
        if(prLoading||prLoaded)return;
        prLoading=true;prFailed=false;retryRow.hidden=true;number.pickerInput.disabled=true;
        prStatus.textContent='Loading pull requests…';
        try{
          let page=1,more;
          do{
            const result=await api('/github/pulls?'+new URLSearchParams({repository_name:branchLink.repository,branch_name:branchLink.branch,page}));
            if(!body.isConnected)return;
            for(const pr of result.items){
              if(![...number.options].some(option=>option.value===String(pr.number)))number.append(new Option('#'+pr.number+' · '+pr.title+' · '+(pr.draft&&pr.state==='open'?'Draft':pr.state),String(pr.number)));
            }
            more=result.more;page++;
          }while(more);
          prLoaded=true;prStatus.textContent=number.options.length===1?'No pull requests found for this branch.':'';
        }catch(error){if(body.isConnected){prFailed=true;prStatus.textContent=error.message;retryRow.hidden=prMode.value!=='link';}}
        finally{prLoading=false;number.pickerInput.disabled=!prLoaded||number.options.length===1;}
      }
      const description=field(details,'Description','textarea');description.rows=3;description.maxLength=10000;
      const hint=el('p');details.append(hint);
      const save=button(controls(details),'Publish pull request',async()=>{
        const existing=prMode.value==='link';
        if(existing&&(!prLoaded||!number.value)){number.pickerInput.setCustomValidity('Choose a pull request.');number.pickerInput.reportValidity();return;}
        await api('/actions/'+item.id+'/github/pr',{resource:branchLink.resource,number:existing?number.value:null,body:existing?'':description.value});
        await load();await refresh();
      });
      number.oninput=()=>number.setCustomValidity('');
      function setPrMode(){
        const existing=prMode.value==='link';number.parentElement.hidden=!existing;description.parentElement.hidden=existing;
        prStatus.hidden=!existing;retryRow.hidden=!existing||!prFailed;
        save.textContent=existing?'Link':'Publish pull request';
        hint.textContent=existing?'Choose a pull request for this repository and branch.':'Publishes a draft on GitHub using the action title. Commit and push your changes first, then mark the draft ready for review on GitHub.';
        if(existing&&!prFailed)void readPulls();
      }
      prMode.onchange=setPrMode;setPrMode();
    }
  }
  function attachGithub(parent,getItem){
    const section=el('details',undefined,'action-triage github-action-section');
    section.append(el('summary','Repository settings'));
    const body=el('div',undefined,'github-action-controls');section.append(body);parent.append(section);
    const provider=el('section',undefined,'repository-provider');provider.setAttribute('aria-label','Github');body.append(provider);
    provider.append(el('h4','Github'));
    const saved=el('div',undefined,'repository-provider-summary');saved.setAttribute('aria-live','polite');provider.append(saved);
    const settingsControls=controls(provider);settingsControls.classList.add('repository-provider-settings');
    let active=null,disposed=false;
    const eligible=()=>current.some(c=>c.provider==='github'&&c.enabled&&c.status==='Connected')&&getItem()?.kind==='action';
    const open=button(settingsControls,'Settings',async()=>{
      const item=getItem();if(!item?.id)return;
      const modal=dialog('Github settings');active={...modal,id:item.id};
      modal.d.classList.add('github-settings-dialog');
      const reset=el('div',undefined,'github-settings-reset');modal.error.after(reset);
      const feedback=el('p');feedback.setAttribute('role','status');reset.append(feedback);
      const clear=button(controls(reset),'Clear all settings',async()=>{
        modal.error.textContent='';feedback.textContent='';modal.body.inert=true;
        try{await api('/actions/'+item.id+'/github/clear',{});await render();feedback.textContent='GitHub settings cleared for this action.';await load();}
        finally{modal.body.inert=false;}
      });
      reset.append(el('p','Removes this action’s saved branch and PR links and resets the form. GitHub branches, pull requests, and your connector account are kept.'));
      modal.d.addEventListener('close',()=>{if(active?.d===modal.d)active=null;},{once:true});
      async function render(){
        if(disposed||!modal.d.open)return;
        clear.disabled=true;
        modal.body.replaceChildren();modal.error.textContent='';
        const content=el('div');modal.body.append(content);
        try{await githubControls(content,item,render);}
        catch(e){if(modal.d.open){modal.error.textContent=e.message;button(controls(content),'Retry',render);}}
        finally{clear.disabled=false;}
      }
      await render();
    });
    function renderSummary(){
      saved.replaceChildren();
      const item=getItem();
      if(!item?.id){saved.append(el('p','Save this action to link GitHub work.'));return;}
      const links=cardLinks.filter(row=>row.provider==='github'&&row.action_id===item.id);
      if(!links.length){saved.append(el('p','No GitHub repository or branch linked yet.'));return;}
      for(const row of links){
        const entry=el('div',undefined,'repository-summary-entry');saved.append(entry);
        entry.append(el('strong',row.repository));
        const branchLine=el('p');branchLine.append(document.createTextNode('Branch: '));link(branchLine,row.branch,row.url);entry.append(branchLine);
        if(row.base)entry.append(el('p','Target: '+row.base));
        const prLine=el('p');entry.append(prLine);
        if(row.pr_number){
          link(prLine,'PR #'+row.pr_number,row.pr_url);
          prLine.append(document.createTextNode(' · '+(row.draft&&row.pr_state==='open'?'Draft':row.pr_state||'Linked')));
        }else prLine.textContent='No pull request linked.';
      }
    }
    function update(){
      if(disposed)return;
      section.hidden=!eligible();open.disabled=!getItem()?.id;renderSummary();
      if(section.hidden)section.open=false;
      if(active&&(section.hidden||active.id!==getItem()?.id))active.d.close();
    }
    for(const event of ['integrations:changed','hfl:actions-updated'])window.addEventListener(event,update);
    update();
    return ()=>{disposed=true;active?.d.close();for(const event of ['integrations:changed','hfl:actions-updated'])window.removeEventListener(event,update);section.remove();};
  }
  async function actionDialog(item){
    const {d,body}=dialog('Integrations · '+item.title);const links=await api('/actions/'+encodeURIComponent(item.id));
    if(!d.open)return;
    if(links.jira?.length){
      body.append(el('h3','Jira'));const data=await api('/actions/'+item.id+'/jira');link(body,data.link.issue_key+' · '+data.link.jira_status,data.link.url);
      const transition=field(body,'Jira transition','select');transition.append(new Option('Choose a transition',''));for(const t of data.transitions)transition.append(new Option(t.name+' → '+t.to.name,t.id));
      button(controls(body),'Update Jira status',async()=>{await api('/actions/'+item.id+'/jira/transition',{version:data.item.version,expected_status:data.issue.fields.status.id,transition:transition.value});window.dispatchEvent(new Event('hfl:actions-updated'));await load();d.close();await actionDialog(item);});
      button(controls(body),'Refresh from Jira',async()=>{await api('/actions/'+item.id+'/jira/refresh',{});window.dispatchEvent(new Event('hfl:actions-updated'));await load();d.close();await actionDialog(item);});
      if(!data.transitions.length)body.append(el('p','No transitions are available for this issue.'));
    }
    if(!Object.keys(links).length)body.append(el('p','Enable a connector in Build → Integrations.'));
  }
  async function prepareAgent(raw,feedback){const data=await api('/agents/prepare',raw);if(feedback)feedback.textContent='Workspace prepared. Opening Hermes…';location.href=data.workspace_url;}
  document.querySelector('[data-add-application]')?.addEventListener('click',()=>{const {body}=dialog('Add workflow application');body.append(el('p','Prepare a development action and Hermes workspace. No files are created until you start the agent.'));const name=field(body,'App name'),description=field(body,'Initial README description','textarea');description.maxLength=3000;button(controls(body),'Prepare Hermes workspace',()=>prepareAgent({name:name.value,description:description.value,agent:'hermes',create:true}));});
  const tabs=[...document.querySelectorAll('.integration-tabs [role="tab"]')];
  if(tabs.length){
    function selectTab(tab,updateUrl=false){
      for(const candidate of tabs){
        const selected=candidate===tab;
        candidate.setAttribute('aria-selected',String(selected));
        candidate.tabIndex=selected?0:-1;
        document.getElementById(candidate.getAttribute('aria-controls')).hidden=!selected;
      }
      if(updateUrl)history.replaceState(history.state,'','#'+tab.getAttribute('aria-controls'));
    }
    function selectFromHash(){selectTab(tabs.find(tab=>'#'+tab.getAttribute('aria-controls')===location.hash)||tabs[0]);}
    tabs.forEach((tab,index)=>{
      tab.addEventListener('click',()=>selectTab(tab,true));
      tab.addEventListener('keydown',event=>{
        const next={ArrowRight:(index+1)%tabs.length,ArrowLeft:(index+tabs.length-1)%tabs.length,Home:0,End:tabs.length-1}[event.key];
        if(next===undefined)return;
        event.preventDefault();selectTab(tabs[next],true);tabs[next].focus();
      });
    });
    window.addEventListener('hashchange',selectFromHash);selectFromHash();
  }
  const search=document.getElementById('integration-search');
  if(search){let limit=24;const more=document.querySelector('[data-inventory-more]');function filter(){const query=search.value.trim().toLowerCase();let total=0;for(const card of document.querySelectorAll('[data-app-key]')){const match=(card.textContent+' '+(card.dataset.appDescription||'')).toLowerCase().includes(query);card.hidden=!match||total>=limit;if(match)total++;}document.querySelector('[data-inventory-count]').textContent=Math.min(limit,total)+' of '+total+' matching applications';more.hidden=total<=limit;}search.oninput=()=>{limit=24;filter();};more.onclick=()=>{limit+=24;filter();};filter();}
  const settingsForm=document.querySelector('[data-application-settings]');
  if(settingsForm){
    const name=settingsForm.elements.display_name,file=settingsForm.elements.icon,preview=settingsForm.querySelector('[data-icon-preview]');
    const feedback=settingsForm.querySelector('[data-settings-feedback]'),error=settingsForm.querySelector('[data-settings-error]');
    const filename=settingsForm.querySelector('[data-icon-filename]');
    settingsForm.querySelector('[data-upload-application-icon]').addEventListener('click',()=>file.click());
    let savedIcon=preview.src,previewUrl=null;
    function clearPreview(){if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl=null;}}
    file.addEventListener('change',()=>{
      clearPreview();error.textContent='';feedback.textContent='';
      const image=file.files[0];filename.textContent='No file selected';
      if(!image){preview.src=savedIcon;return;}
      if(image.size>2*1024*1024||!['image/png','image/jpeg','image/webp'].includes(image.type)){
        error.textContent='Choose a PNG, JPEG, or WebP image no larger than 2 MB.';file.value='';preview.src=savedIcon;return;
      }
      filename.textContent=image.name;previewUrl=URL.createObjectURL(image);preview.src=previewUrl;
    });
    preview.addEventListener('error',()=>{if(previewUrl){clearPreview();file.value='';filename.textContent='No file selected';preview.src=savedIcon;error.textContent='Choose a valid image.';}});
    async function update(reset){
      const payload=reset?undefined:new FormData(settingsForm);
      const controls=[...settingsForm.querySelectorAll('input,button')];controls.forEach(c=>c.disabled=true);
      error.textContent='';feedback.textContent=reset?'Resetting…':'Saving…';
      try{
        const response=await fetch('/applications/'+encodeURIComponent(settingsForm.dataset.applicationSettings)+'/settings'+(reset?'/reset':''),{method:'POST',headers:{'X-CSRF-Token':csrf()},body:payload});
        const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Unable to save settings.');
        clearPreview();name.value=data.display_name;file.value='';filename.textContent='No file selected';savedIcon=data.icon_url;preview.src=savedIcon;
        document.querySelectorAll('[data-application-display-name]').forEach(n=>n.textContent=data.display_name);
        document.querySelectorAll('[data-application-icon]').forEach(n=>n.src=savedIcon);
        document.title='HARQIS — '+data.display_name;feedback.textContent=reset?'Defaults restored.':'Settings saved.';
      }catch(e){feedback.textContent='';error.textContent=e.message;}
      finally{controls.forEach(c=>c.disabled=false);}
    }
    settingsForm.addEventListener('submit',event=>{event.preventDefault();update(false);});
    settingsForm.querySelector('[data-reset-application-settings]').addEventListener('click',()=>update(true));
    settingsForm.querySelector('[data-settings-fields]').disabled=false;
    window.addEventListener('pagehide',clearPreview);
  }
  const app=document.querySelector('[data-application-agent]');if(app)app.querySelector('[data-open-application-agent]').onclick=async event=>{event.target.disabled=true;const feedback=app.querySelector('[data-agent-feedback]');try{await prepareAgent({name:app.dataset.applicationAgent,agent:app.querySelector('[data-agent-choice]').value},feedback);}catch(e){feedback.textContent=e.message;}finally{event.target.disabled=false;}};
  window.HarqisIntegrations={attachGithub,actionButton(parent,item){const b=button(parent,'Integrations',()=>actionDialog(item));b.dataset.connectorAction=item.id;b.hidden=!current.some(c=>c.provider==='jira'&&c.enabled);badges(parent,item.id);return b;},refresh:load};
  load().catch(e=>{const error=document.querySelector('[data-integration-error]');if(error)error.textContent=e.message;});
})();
