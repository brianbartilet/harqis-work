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
  function button(parent,label,run){const b=el('button',label);b.type='button';parent.append(b);b.onclick=async()=>{b.disabled=true;try{await run();}catch(e){const alert=[...document.querySelectorAll('.integration-dialog[open] [role=alert]')].at(-1)||parent.closest('dialog')?.querySelector('[role=alert]')||document.querySelector('[data-integration-error]')||parent.appendChild(el('p'));alert.setAttribute('role','alert');alert.textContent=e.message;}finally{b.disabled=false;}};return b;}
  function field(parent,label,type='text',value=''){const l=el('label',label),input=el(type==='textarea'?'textarea':type==='select'?'select':'input');if(input.tagName==='INPUT')input.type=type;input.value=value;input.setAttribute('aria-label',label);l.append(input);parent.append(l);return input;}
  function link(parent,label,url){const a=el('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);return a;}
  function dialog(title){const opener=document.activeElement,d=el('dialog',undefined,'integration-dialog'),h=el('header');d.setAttribute('aria-label',title);h.append(el('h2',title));button(h,'Close',()=>d.close());d.append(h);const body=el('div'),error=el('p');error.setAttribute('role','alert');d.append(body,error);document.body.append(d);d.addEventListener('close',()=>{d.remove();if(opener?.isConnected)opener.focus();},{once:true});d.showModal();return {d,body,error};}
  const controls=parent=>parent.appendChild(el('div',undefined,'integration-controls'));
  let current=[], cardLinks=[];
  function badges(parent,identity){parent.querySelectorAll("[data-connector-summary]").forEach(n=>n.remove());for(const row of cardLinks.filter(r=>r.action_id===identity)){const text=row.provider==='jira'?row.issue_key+' · '+row.jira_status:row.branch+(row.pr_number?' · PR #'+row.pr_number+' · '+row.pr_state:'');const badge=el('span',text,'action-status');badge.dataset.connectorSummary=identity;parent.append(badge);}}
  async function load(){
    const snapshot=await api('/connectors');current=snapshot.items;cardLinks=snapshot.links||[];
    const root=document.querySelector('[data-connector-cards]');
    if(root){root.replaceChildren();for(const item of current){
      const card=el('article',undefined,'connector-card'),header=el('header');header.append(el('h2',item.name));
      const toggle=el('button',undefined,'connector-switch');toggle.type='button';toggle.setAttribute('role','switch');toggle.setAttribute('aria-checked',String(item.enabled));toggle.setAttribute('aria-label','Enable '+item.name);
      const track=el('span',undefined,'connector-switch-track');track.setAttribute('aria-hidden','true');toggle.append(track,el('span',item.enabled?'On':'Off'));header.append(toggle);card.append(header);
      toggle.onclick=async()=>{toggle.disabled=true;try{if(!item.enabled&&item.status!=='Connected'){setup(item);}else{await api('/connectors/'+item.provider+'/toggle',{enabled:!item.enabled});await load();}}catch(e){document.querySelector('[data-integration-error]').textContent=e.message;}finally{toggle.disabled=false;}};
      const status=el('span',item.status,'connector-status');status.dataset.connected=String(item.status==='Connected');status.dataset.error=String(Boolean(item.error));status.setAttribute('role','status');card.append(status);
      if(item.account)card.append(el('p',item.account+' · '+item.auth_method),el('p','Connected since '+new Date(item.connected_since).toLocaleDateString()+' · Expiry: '+item.expiry));
      if(item.error)card.append(el('p',item.error));
      const capabilities=el('ul');item.capabilities.forEach(c=>capabilities.append(el('li',c)));card.append(capabilities);
      const footer=el('footer',undefined,'connector-footer');card.append(footer);
      if(item.enabled){const actions=controls(footer);if(item.provider==='jira')button(actions,'Import assigned issues',jiraImport);else button(actions,'Explore branches and PRs',githubIdeas);}
      const row=controls(footer);row.classList.add('connector-connection-controls');
      if(item.status!=='Not connected')button(row,'Disconnect',async()=>{const confirm=dialog('Disconnect '+item.name);confirm.body.append(el('p','Remove this connection’s saved credentials? Imported cards and links remain; reconnect the same account to use them again.'));button(controls(confirm.body),'Disconnect account',async()=>{await api('/connectors/'+item.provider+'/disconnect',{});confirm.d.close();await load();});});
      button(row,item.status==='Connected'?'Reconnect / test':'Connect',()=>setup(item)).classList.add('connector-connect');
      root.append(card);
    }}
    document.querySelectorAll('[data-connector-action]').forEach(b=>{b.hidden=!current.some(c=>c.enabled);badges(b.parentElement,b.dataset.connectorAction);});
    window.dispatchEvent(new CustomEvent('integrations:changed',{detail:current}));
  }
  function setup(item){
    const {d,body,error}=dialog('Connect '+item.name);
    body.append(el('p','Not connected until the test succeeds. Credentials are encrypted on the server and are separate from workflow accounts.'));
    if(item.provider==='github'){
      body.append(el('p','Create a fine-grained personal access token for the selected repositories. Grant Contents: read/write and Pull requests: read/write for branch and PR operations. Organization approval may be required. Account MFA stays on GitHub.'));
      link(body,'GitHub token setup instructions','https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens');
      body.append(el('p','Alternative for a later release: a GitHub App installation with short-lived tokens.'));
    }else{
      body.append(el('p','Create an Atlassian API token. Your Jira account needs Browse Projects and Transition Issues permissions. API tokens work with two-step verification; do not enter a password or MFA code. Scoped tokens also require your cloud ID.'));
      link(body,'Atlassian token setup instructions','https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/');
      body.append(el('p','Alternative for a later release: OAuth 2.0 authorization with refresh tokens.'));
    }
    const site=item.provider==='jira'?field(body,'Jira Cloud site','url',item.site||''):null;
    const email=item.provider==='jira'?field(body,'Atlassian email','email'):null;
    const cloud=item.provider==='jira'?field(body,'Cloud ID (scoped tokens only)'):null;
    const token=field(body,'API token','password');token.autocomplete='new-password';token.maxLength=4096;
    const state=el('p','Not connected');state.setAttribute('role','status');body.append(state);
    button(controls(body),'Test and connect',async()=>{error.textContent='';state.textContent='Testing connection…';try{await api('/connectors/'+item.provider+'/connect',{token:token.value,...(site?{site:site.value,email:email.value,cloud_id:cloud.value}:{})});token.value='';state.textContent='Connected. You can now enable the connector.';await load();button(controls(body),'Enable connector',async()=>{await api('/connectors/'+item.provider+'/toggle',{enabled:true});d.close();await load();});}catch(e){token.value='';state.textContent='Connection failure';await load();throw e;}});
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
  async function actionDialog(item){
    const {d,body}=dialog('Integrations · '+item.title);const links=await api('/actions/'+encodeURIComponent(item.id));
    if(!d.open)return;
    if('github' in links){
      body.append(el('h3','GitHub'));const repo=await repoPicker(body),branch=field(body,'Branch'),base=field(body,'Base branch','text','main');
      repo.onchange=()=>{base.value=repo.selectedOptions[0]?.dataset.base||'main';};
      const options=el('div');body.append(options);
      button(controls(body),'Browse repository branches / PRs',async()=>{options.replaceChildren();const result=await api('/github/resources?'+new URLSearchParams({repository_name:repo.value}));const pick=field(options,'Existing branch','select');pick.append(new Option('Choose a branch',''));result.branches.forEach(b=>pick.append(new Option(b,b)));pick.onchange=()=>{branch.value=pick.value;};result.pulls.forEach(p=>options.append(el('p','#'+p.number+' · '+p.title+' · '+p.branch)));options.append(el('p','You can also enter any branch name or PR number directly.'));});
      const row=controls(body);for(const [label,operation] of [['Link branch','link-branch'],['Create branch','create-branch']])button(row,label,async()=>{await api('/actions/'+item.id+'/github/branch',{repository:repo.value,branch:branch.value,base:base.value,operation});await load();d.close();await actionDialog(item);});
      const refreshed=await api('/actions/'+item.id+'/github');
      for(const branchLink of refreshed.items){const section=el('section',undefined,'connector-link');body.append(section);link(section,branchLink.repository+' · '+branchLink.branch,branchLink.url);
        if(branchLink.pr_number){section.append(el('p',(branchLink.draft?'Draft · ':'')+branchLink.pr_state));link(section,'PR #'+branchLink.pr_number,branchLink.pr_url);}
        const number=field(section,'Existing PR number (optional)','number'),description=field(section,'PR description','textarea');
        button(controls(section),'Link PR / create draft PR',async()=>{await api('/actions/'+item.id+'/github/pr',{resource:branchLink.resource,number:number.value||null,body:description.value});await load();d.close();await actionDialog(item);});
      }
    }
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
  if(search){let limit=24;const more=document.querySelector('[data-inventory-more]');function filter(){const query=search.value.trim().toLowerCase();let total=0;for(const card of document.querySelectorAll('[data-app-key]')){const match=card.textContent.toLowerCase().includes(query);card.hidden=!match||total>=limit;if(match)total++;}document.querySelector('[data-inventory-count]').textContent=Math.min(limit,total)+' of '+total+' matching applications';more.hidden=total<=limit;}search.oninput=()=>{limit=24;filter();};more.onclick=()=>{limit+=24;filter();};filter();}
  const app=document.querySelector('[data-application-agent]');if(app)app.querySelector('[data-open-application-agent]').onclick=async event=>{event.target.disabled=true;const feedback=app.querySelector('[data-agent-feedback]');try{await prepareAgent({name:app.dataset.applicationAgent,agent:app.querySelector('[data-agent-choice]').value},feedback);}catch(e){feedback.textContent=e.message;}finally{event.target.disabled=false;}};
  window.HarqisIntegrations={actionButton(parent,item){const b=button(parent,'Integrations',()=>actionDialog(item));b.dataset.connectorAction=item.id;b.hidden=!current.some(c=>c.enabled);badges(parent,item.id);return b;},refresh:load};
  load().catch(e=>{const error=document.querySelector('[data-integration-error]');if(error)error.textContent=e.message;});
})();
