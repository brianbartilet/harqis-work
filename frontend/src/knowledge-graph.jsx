import {exampleGraph} from './knowledge-graph-example.js';
import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ForceGraph2D from 'react-force-graph-2d';
import {forceCollide, forceX, forceY} from 'd3-force-3d';
// Bundled locally. Graph data is fetched only from the authenticated HARQIS API.
(() => {
  'use strict';
  const $ = id => document.getElementById('kg-' + id);
  let infoUrgent=true,infoPaused=false;
  function showInfo(channel,text,urgent=false) {
    $(channel).textContent=text;
    if(channel==='status')infoUrgent=urgent;
    if(channel==='status'||!infoUrgent){$('status').hidden=channel!=='status';$('view-status').hidden=channel!=='view-status';}
    $('info').title=$('status').textContent+' | '+$('view-status').textContent;
  }
  const infoRotation=setInterval(()=>{
    if(infoUrgent||infoPaused||document.hidden)return;
    $('status').hidden=!$('status').hidden;$('view-status').hidden=!$('status').hidden;
  },6000);
  $('info').addEventListener('mouseenter',()=>{infoPaused=true;});
  $('info').addEventListener('mouseleave',()=>{infoPaused=false;});
  $('info').addEventListener('focus',()=>{infoPaused=true;});
  $('info').addEventListener('blur',()=>{infoPaused=false;});
  const palette = {entries:'#77dcf5', people:'#ffbd91', companies:'#deafff', tools:'#70edbd', topics:'#9bafff', daily:'#95a7c3'};
  const color = kind => palette[kind] || '#e9c96c';
  const defaultLabelKinds = new Set(['sources', 'people', 'tools', 'companies']);
  let data = {nodes:[],edges:[]}, nodes = [], edges = [], selected = null, enabled = new Set();
  let exampleMode=new URLSearchParams(location.search).get('example')==='1';
  let requestVersion=0, requestController=null, backgroundController=null, appliedParams=null, graphSignature='', lastInteraction=0;
  const signature=value=>JSON.stringify(value,(key,item)=>key==='locator'?undefined:item);
  const selectedSources=new Set();
  let loading=false, graphData={nodes:[],links:[]}, graphApi=null, active=null, focusId=null;
  const host=$('canvas'), root=createRoot(host);
  const touchViewport=window.matchMedia('(pointer: coarse)').matches;
  const uiFont=getComputedStyle(host).fontFamily;
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const endpointId=value=>typeof value==='object'?value.id:value;
  const duration=reducedMotion?0:500;
  const storageKey='harqis.graph-view.v1:' + document.querySelector('[data-view-owner]').dataset.viewOwner;
  let savedViews={},saveTimer,restoring=false;
  const preferencesKey=storageKey + ':preferences';
  let namedViews=[],currentView=null,pendingState=null,dirty=false,viewOperation=false,editVersion=0;
  function markDirty(){if(!restoring){editVersion++;dirty=true;$('dirty').textContent='Unsaved changes';}}
  function savePreferences(){markDirty();}
  const viewUrl='/api/hfl/graph-views';
  async function viewRequest(url,method='GET',body){
    const response=await fetch(url,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
    if(!response.ok){const value=await response.json().catch(()=>({}));throw Error(typeof value.detail==='string'?value.detail:'Saved views unavailable. Please retry.');}
    return response.json();
  }
  function viewOptions(){
    $('saved-views').replaceChildren(new Option('Unsaved view',''));
    namedViews.forEach(view=>$('saved-views').add(new Option(view.name,view.id)));
    $('saved-views').value=currentView?.id||'';
    $('rename').disabled=$('delete').disabled=!currentView;
  }
  function syncDates(){for(const id of ['since','until'])$(id).disabled=$('rolling').value!=='0';}
  function applyRollingDates(params){
    const days=Number(params.get('rolling'));if(!days)return;
    const end=new Date(),start=new Date(end);start.setDate(start.getDate()-days+1);
    const date=value=>[value.getFullYear(),String(value.getMonth()+1).padStart(2,'0'),String(value.getDate()).padStart(2,'0')].join('-');
    params.set('since',date(start));params.set('until',date(end));
  }
  function requestParams(){
    const params=new URLSearchParams({since:$('since').value,until:$('until').value,rolling:$('rolling').value,limit:$('density').value,query:$('search').value,shared:String($('shared').checked)});
    selectedSources.forEach(source=>params.append('sources',source));applyRollingDates(params);return params;
  }
  function stateSnapshot(){
    saveView();const layout=savedViews[graphData.viewKey]||{};
    return {density:$('density').value,query:$('search').value,sources:[...selectedSources],since:$('since').value,until:$('until').value,
      rolling:Number($('rolling').value),shared:$('shared').checked,group:$('group').value,enabled:[...enabled],focus:focusId,
      layout:{positions:layout.positions||{},center:layout.center||{},zoom:layout.zoom||1}};
  }
  function applyState(state){
    for(const id of ['density','since','until','group','rolling'])$(id).value=String(state[id]??(id==='rolling'?0:''));
    $('search').value=state.query||'';$('shared').checked=state.shared;
    selectedSources.clear();state.sources.forEach(value=>selectedSources.add(value));syncDates();sourceOptions(data.sources||[]);
    pendingState=state;enabled=new Set(state.enabled);focusId=state.focus;dirty=false;$('dirty').textContent='';
  }
  function discardEdits(){return !dirty||window.confirm('Discard unsaved changes to this view?');}
  async function switchView(id,initial=false){
    if(viewOperation&&!initial){viewOptions();return;}
    if(!initial&&!discardEdits()){viewOptions();return;}
    backgroundController?.abort();requestController?.abort();requestVersion++;viewOperation=true;
    try{
      const result=await viewRequest(viewUrl);namedViews=result.views;
      const view=namedViews.find(item=>item.id===id);
      if(view){await viewRequest(viewUrl+'/'+view.id+'/select','POST');currentView=view;applyState(view.state);}
      else {currentView=null;applyState({density:'100',query:'',sources:[],since:'',until:'',rolling:0,shared:true,group:'relationships',enabled:['entries','sources','daily','people','companies','tools','topics','objects'],focus:null,layout:{}});}
      viewOptions();await load();
    }catch(error){$('dirty').textContent=error.message;viewOptions();}
    finally{viewOperation=false;}
  }
  async function persistView(asNew=false,renameOnly=false){
    if(loading||viewOperation)return;
    let name=currentView?.name;
    if(asNew||!name||renameOnly){name=window.prompt('View name',name||'My activity');if(!name?.trim())return;}
    viewOperation=true;
    try{
      const state=renameOnly?currentView.state:stateSnapshot(),id=asNew?null:currentView?.id,savingVersion=editVersion;
      const result=await viewRequest(viewUrl+(id?'/'+id:''),id?'PUT':'POST',{name:name.trim(),state,revision:id?currentView.revision:0});
      currentView=result;namedViews=namedViews.filter(item=>item.id!==result.id);namedViews.push(result);viewOptions();
      if(!renameOnly&&savingVersion===editVersion){dirty=false;$('dirty').textContent='Saved';}else if(!dirty)$('dirty').textContent='Renamed';
    }catch(error){$('dirty').textContent=error.message;}
    finally{viewOperation=false;}
  }
  async function initializeViews(){
    try{
      const result=await viewRequest(viewUrl);namedViews=result.views;viewOptions();
      try{$('import').hidden=!localStorage.getItem(preferencesKey);}catch{}
      if(result.last_used)await switchView(result.last_used,true);else await load();
    }catch(error){$('dirty').textContent=error.message;await load();}
  }
  $('saved-views').onchange=()=>switchView($('saved-views').value);
  $('save').onclick=()=>persistView();$('save-as').onclick=()=>persistView(true);$('rename').onclick=()=>persistView(false,true);
  $('delete').onclick=async()=>{
    if(!currentView||viewOperation||!window.confirm('Delete this saved view?'))return;
    viewOperation=true;
    try{await viewRequest(viewUrl+'/'+currentView.id+'?revision='+currentView.revision,'DELETE');dirty=false;await switchView('',true);}
    catch(error){$('dirty').textContent=error.message;}finally{viewOperation=false;}
  };
  $('import').onclick=async()=>{
    if(!discardEdits())return;restorePreferences();$('rolling').value='0';syncDates();
    try{
      const legacy=JSON.parse(localStorage.getItem(storageKey)||'{}');
      const prefix=[exampleMode,$('search').value,$('density').value,[...selectedSources].sort(),$('since').value,$('until').value,$('shared').checked,$('group').value];
      const match=Object.entries(legacy).sort((a,b)=>(b[1].time||0)-(a[1].time||0)).find(([key])=>JSON.stringify(JSON.parse(key).slice(0,8))===JSON.stringify(prefix));
      if(match){const key=JSON.parse(match[0]);pendingState={enabled:key[8],focus:key[9],layout:match[1]};}
    }catch{}
    currentView=null;viewOptions();await load();markDirty();$('import').hidden=true;
  };
  $('rolling').onchange=syncDates;
  document.querySelector('.kg-shell').addEventListener('change',event=>{if(event.target.closest('.kg-main-toolbar,.kg-filter-drawer'))markDirty();});
  $('search').addEventListener('input',markDirty);
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  function restorePreferences() {
    try {
      const value=JSON.parse(localStorage.getItem(preferencesKey)||'null');if(!value)return;
      const density=({'120':'100','300':'500','800':'1000'})[value.density]||value.density;
      if(['100','500','1000','0'].includes(density))$('density').value=density;
      if(typeof value.query==='string')$('search').value=value.query.slice(0,200);
      if(Array.isArray(value.sources))value.sources.filter(s=>typeof s==='string').forEach(s=>selectedSources.add(s));
      for(const field of ['since','until'])if(typeof value[field]==='string')$(field).value=value[field];
      if(typeof value.shared==='boolean')$('shared').checked=value.shared;
      if(['relationships','source','date'].includes(value.group))$('group').value=value.group;
    }catch{}
  }
  const viewKey=()=>JSON.stringify([exampleMode,$('search').value,$('density').value,[...selectedSources].sort(),$('rolling').value,$('since').value,$('until').value,$('shared').checked,$('group').value,[...enabled].sort(),focusId]);
  function saveView() {
    clearTimeout(saveTimer);
    if(loading||restoring||!graphApi||!graphData.nodes.length||!graphData.viewKey)return;
    const positions={};
    graphData.nodes.forEach(n=>{if(Number.isFinite(n.x)&&Number.isFinite(n.y))positions[n.id]={x:n.x,y:n.y,pinned:n.fx!=null&&n.fy!=null};});
    const center=graphApi.screen2GraphCoords(host.clientWidth/2,host.clientHeight/2);
    savedViews[graphData.viewKey]={positions,center,zoom:graphApi.zoom(),time:Date.now()};
    const keys=Object.keys(savedViews).sort((a,b)=>savedViews[b].time-savedViews[a].time);
    keys.slice(10).forEach(key=>delete savedViews[key]);

  }
  function scheduleSave(){if(!restoring){clearTimeout(saveTimer);saveTimer=setTimeout(saveView,500);}}
  window.addEventListener('pagehide',saveView);
  function fit(){
    if(!graphApi||!graphData.nodes.length||graphData.nodes.some(n=>!Number.isFinite(n.x)||!Number.isFinite(n.y)))return;
    const bounds=graphApi.getGraphBbox();
    if(bounds&&[...bounds.x,...bounds.y].every(Number.isFinite))graphApi.zoomToFit(duration,70);
  }
  function zoom(factor){markDirty();if(graphApi)graphApi.zoom(graphApi.zoom()*factor,duration);}
  function Graph({data,activeId,selectedId}) {
    const ref=useRef(),needsFit=useRef(!data.background),labelBoxes=useRef([]);
    const [size,setSize]=useState({width:host.clientWidth,height:host.clientHeight});
    useEffect(()=>{
      const observer=new ResizeObserver(()=>{setSize({width:host.clientWidth,height:host.clientHeight});needsFit.current=true;});
      observer.observe(host);return()=>observer.disconnect();
    },[]);
    useEffect(()=>{
      graphApi=ref.current;needsFit.current=!data.background;
      ref.current.d3Force('charge').strength(-230);
      ref.current.d3Force('link').distance(105);
      ref.current.d3Force('collide',forceCollide(n=>n.radius+30).iterations(2));
      ref.current.d3Force('x',forceX(n=>n.clusterX||0).strength(.065));
      ref.current.d3Force('y',forceY(n=>n.clusterY||0).strength(.065));
      ref.current.d3ReheatSimulation();
    },[data]);
    useEffect(()=>{
      const timer=setTimeout(()=>{
        const saved=savedViews[data.viewKey];
        if(saved&&Number.isFinite(saved.zoom)&&saved.zoom>0&&Number.isFinite(saved.center?.x)&&Number.isFinite(saved.center?.y)){
          restoring=true;needsFit.current=false;ref.current.zoom(saved.zoom,0);ref.current.centerAt(saved.center.x,saved.center.y,0);restoring=false;
          showInfo('view-status','Saved layout restored.');
        } else fit();
      },100);return()=>clearTimeout(timer);
    },[size,data]);
    const near=connected(activeId);
    const isLinked=link=>activeId&&(endpointId(link.source)===activeId||endpointId(link.target)===activeId);
    function paintNode(node,ctx,globalScale){
      if(!Number.isFinite(node.x)||!Number.isFinite(node.y)||!Number.isFinite(globalScale)||globalScale<=0)return;
      const visible=!activeId||node.id===activeId||near.has(node.id);
      const radius=node.radius/globalScale;
      const ink=color(node.kind),emphasis=node.id===activeId||node.id===selectedId;
      ctx.save();ctx.globalAlpha=visible?1:.075;
      const glow=ctx.createRadialGradient(node.x,node.y,0,node.x,node.y,(emphasis?30:18)/globalScale);
      glow.addColorStop(0,ink+(emphasis?'75':'35'));glow.addColorStop(1,ink+'00');
      ctx.fillStyle=glow;ctx.beginPath();ctx.arc(node.x,node.y,(emphasis?30:18)/globalScale,0,2*Math.PI);ctx.fill();
      const fill=ctx.createRadialGradient(node.x-radius*.3,node.y-radius*.4,0,node.x,node.y,radius*1.6);
      fill.addColorStop(0,'#effbff');fill.addColorStop(.3,ink);fill.addColorStop(1,ink+'70');
      ctx.beginPath();ctx.arc(node.x,node.y,radius,0,2*Math.PI);ctx.fillStyle=fill;ctx.fill();
      ctx.strokeStyle=ink;ctx.lineWidth=.8/globalScale;ctx.stroke();
      if(data.nodes.length<=35&&node.kind!=='entries'){
        const mark=node.kind==='people'?node.label.slice(0,1):node.kind==='tools'?'⌘':'◇';
        ctx.font=`600 ${14/globalScale}px ${uiFont}`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle='#10263c';ctx.fillText(mark,node.x,node.y);ctx.textAlign='left';
      }
      if(emphasis){ctx.beginPath();ctx.arc(node.x,node.y,radius+5/globalScale,0,2*Math.PI);ctx.strokeStyle=ink+'aa';ctx.lineWidth=1/globalScale;ctx.stroke();}
      const defaultLabel = !activeId && defaultLabelKinds.has(node.kind);
      if(defaultLabel||emphasis||(!activeId&&node.labelRank<(data.nodes.length<=35?35:9))||activeId&&near.has(node.id)&&near.size<16||globalScale>2.5&&visible){
        const fontSize=(emphasis?13:data.nodes.length<=35?12:11)/globalScale;ctx.font=`500 ${fontSize}px ${uiFont}`;
        const label=node.label.length>34?node.label.slice(0,32)+'…':node.label;
        const x=node.x+radius+9/globalScale,y=node.y,w=ctx.measureText(label).width;
        const box={x:x-6/globalScale,y:y-12/globalScale,w:w+12/globalScale,h:24/globalScale};
        const overlaps=labelBoxes.current.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y);
        if(defaultLabel||!overlaps||emphasis){
        labelBoxes.current.push(box);
        ctx.fillStyle=emphasis?'#142a42f5':'#0a1728dd';ctx.beginPath();ctx.roundRect(x-5/globalScale,y-11/globalScale,w+10/globalScale,22/globalScale,5/globalScale);ctx.fill();
        ctx.strokeStyle=ink+(emphasis?'90':'30');ctx.lineWidth=.6/globalScale;ctx.stroke();
        ctx.textBaseline='middle';ctx.fillStyle=emphasis?'#ffffff':'#d9e9fa';ctx.fillText(label,x,y);
        }
      }
      ctx.restore();
    }
    return <ForceGraph2D ref={ref} width={size.width} height={size.height}
      graphData={data} enableNodeDrag={!touchViewport} enablePanInteraction={true} enableZoomInteraction={true} backgroundColor="rgba(0,0,0,0)" nodeLabel={()=>''}
      onRenderFramePre={()=>{labelBoxes.current=[];}}
      nodeCanvasObject={paintNode}
      nodePointerAreaPaint={(node,paint,ctx)=>{ctx.fillStyle=paint;ctx.beginPath();ctx.arc(node.x,node.y,(node.radius+4)/(ref.current?.zoom()||1),0,2*Math.PI);ctx.fill();}}
      linkColor={link=>color(link.target.kind)+(activeId?(isLinked(link)?'df':'07'):(data.nodes.length<=35?'70':'32'))}
      linkWidth={link=>isLinked(link)?2:data.nodes.length<=35?1.1:.65} linkCurvature={.16}
      linkDirectionalParticles={link=>!reducedMotion&&isLinked(link)?2:0}
      linkDirectionalParticleWidth={2} linkDirectionalParticleSpeed={.004}
      onZoom={()=>{needsFit.current=false;if(Date.now()-lastInteraction<500)markDirty();scheduleSave();}}
      onNodeHover={node=>{host.style.cursor=node?'pointer':'grab';highlight(node?.id||selected);}}
      onNodeClick={node=>select(node.id)} onBackgroundClick={()=>select(null)}
      onNodeDrag={node=>{
        if(data.background||data.restored){data.background=false;data.restored=false;draw();}
        // Neighbors must be free to follow, including ones moved in an earlier drag.
        const neighbors=connected(node.id);
        data.nodes.forEach(other=>{if(neighbors.has(other.id)){delete other.fx;delete other.fy;}});
      }}
      onNodeDragEnd={node=>{markDirty();node.fx=node.x;node.fy=node.y;ref.current.d3ReheatSimulation();scheduleSave();}}
      warmupTicks={data.background||data.restored?0:data.nodes.length>1000?15:reducedMotion?150:80} cooldownTicks={data.background||data.restored?0:reducedMotion?0:data.nodes.length>1000?40:100}
      onEngineStop={()=>{if(needsFit.current){needsFit.current=false;fit();}scheduleSave();}}
    />;
  }
  function draw(){root.render(<Graph data={graphData} activeId={active} selectedId={selected}/>);}
  function highlight(id){active=id;draw();}
  function connected(id) {
    const result = new Set();
    edges.forEach(e => {if(e.source===id)result.add(e.target);if(e.target===id)result.add(e.source);});
    return result;
  }
  function nodeList(items) {
    $('list').replaceChildren();
    items.sort((a,b)=>Number(b.kind==='sources')-Number(a.kind==='sources') || b.visibleDegree-a.visibleDegree || a.label.localeCompare(b.label)).slice(0,200).forEach(n => {
      const button=document.createElement('button'),dot=document.createElement('span'),name=document.createElement('span'),meta=document.createElement('small');
      dot.className='kg-dot';dot.style.background=color(n.kind);name.textContent=n.label;meta.textContent=n.visibleDegree+' links';button.title=n.label+' · '+n.kind;
      if(selected){const link=edges.find(e=>(e.source===selected&&e.target===n.id)||(e.target===selected&&e.source===n.id));if(link){const evidence=document.createElement('small');evidence.textContent=(link.relation||'linked')+' · '+(link.evidence||'');evidence.style.cssText='grid-column:2 / 4;white-space:normal;font-size:11px';button.append(evidence);button.title=link.evidence||n.label;}}
      button.prepend(dot,name,meta);button.onclick=()=>select(n.id);$('list').append(button);
    });
    if(items.length>200){const note=document.createElement('p');note.textContent='Showing the first 200 neighbors. Search to narrow the graph.';$('list').append(note);}
  }
  let entryController=null;
  async function openEntry(id,locator) {
    entryController?.abort();entryController=new AbortController();const request=entryController;
    $('entry-title').textContent='Activity entry';$('entry-meta').textContent='';$('entry-body').setAttribute('aria-busy','true');
    $('entry-body').innerHTML='<div class="kg-entry-loading" role="status"><span class="kg-entry-spinner" aria-hidden="true"></span><div><strong>Opening activity entry</strong><p>Loading the story, metadata and references...</p></div></div><div class="kg-entry-skeleton" aria-hidden="true"><span></span><span></span><span></span><span></span></div>';
    $('entry-dialog').showModal();
    try {
      const response=await fetch('/api/hfl/entities/entry/'+encodeURIComponent(id)+(locator?'?locator='+encodeURIComponent(locator):''),{signal:request.signal,cache:'no-store'});
      if(!response.ok)throw Error(response.status===404?'This entry is no longer available.':'Entry could not load. Close and try again.');
      const item=await response.json();if(request!==entryController||!$('entry-dialog').open)return;
      $('entry-title').textContent=item.title;$('entry-meta').textContent=[item.date,item.source].filter(Boolean).join(' · ');
      // HTML is rendered and sanitized by the existing server Markdown service.
      $('entry-body').innerHTML=item.html;
      const article=$('entry-body'), fieldLabel=node=>node.matches('p')&&node.firstElementChild?.tagName==='STRONG'?node.firstElementChild.textContent.trim().toLowerCase():'';
      const metadata=document.createElement('div');metadata.className='kg-entry-metadata';
      for(const paragraph of Array.from(article.children)) {
        if(['source:','machine:','entry id:'].includes(fieldLabel(paragraph))){
          if(!metadata.parentElement)paragraph.before(metadata);
          if(fieldLabel(paragraph)==='entry id:')paragraph.classList.add('kg-entry-identity');
          metadata.append(paragraph);
        }
      }
      if(article.querySelector('h2')&&metadata.childElementCount)$('entry-meta').textContent='';
      for(const paragraph of Array.from(article.children)) {
        const field=fieldLabel(paragraph);
        if(field==='moment:')paragraph.remove();
        if(field==='references:'){
          let list=paragraph.nextElementSibling;
          while(list?.matches('ul')){list.classList.add('corpus-reference-list');list=list.nextElementSibling;}
        }
      }
      const endFields=new Set(['why it stayed:','possible use:','tags:','references:']);
      for(const paragraph of Array.from(article.children)) {
        if(paragraph.parentElement!==article||fieldLabel(paragraph)!=='what happened:')continue;
        const label=paragraph.firstElementChild,story=document.createElement('section'),value=document.createElement('p');
        story.className='corpus-entry-story';story.setAttribute('aria-label','What happened');paragraph.after(story);
        while(label.nextSibling)value.append(label.nextSibling);
        if(value.textContent.trim()||value.children.length)story.append(value);
        while(story.nextElementSibling){const next=story.nextElementSibling;if(next.matches('h1,h2,hr')||endFields.has(fieldLabel(next)))break;story.append(next);}
      }
      article.querySelectorAll('[data-reference-preview]').forEach(a=>{a.href=a.dataset.previewUrl||a.href;});
      $('entry-body').querySelectorAll('a').forEach(a=>{a.target='_blank';a.rel='noopener noreferrer';});
    }catch(error){if(error.name!=='AbortError'&&request===entryController)$('entry-body').textContent=error.message;}
    finally{if(request===entryController)$('entry-body').setAttribute('aria-busy','false');}
  }
  $('entry-close').onclick=()=>$('entry-dialog').close();
  $('entry-dialog').addEventListener('close',()=>{entryController?.abort();$('entry-body').replaceChildren();});
  $('entry-dialog').addEventListener('click',event=>{const b=$('entry-dialog').getBoundingClientRect();if(event.target===$('entry-dialog')&&(event.clientX<b.left||event.clientX>b.right||event.clientY<b.top||event.clientY>b.bottom))$('entry-dialog').close();});
  function select(id) {
    selected=id;const n=nodes.find(n=>n.id===id),near=connected(id);
    highlight(id);
    $('detail').replaceChildren();$('detail').classList.toggle('kg-detail-empty',!n);
    const heading=document.createElement('h2'),description=document.createElement('p');
    const eyebrow=document.createElement('span');eyebrow.className='kg-eyebrow';eyebrow.textContent=n?n.kind.replaceAll('_',' '):'Your knowledge, connected';$('detail').append(eyebrow);
    heading.textContent=n?n.label:'';
    description.textContent=n?[n.kind,n.date,n.source,near.size+' visible connections'].filter(Boolean).join(' · '):'Select a source to explore its linked entries and entities.';
    if(n)$('detail').append(heading);$('detail').append(description);
    if(n?.href&&n.kind==='entries') {const button=document.createElement('button');button.textContent='Open entry';button.className='kg-open-entry';button.onclick=()=>openEntry(n.id.replace(/^entry:/,''),n.locator);$('detail').append(button);}
    if(n){const focus=document.createElement('button');focus.textContent='Focus on this connection';focus.className='kg-focus-button';focus.onclick=()=>{focusId=n.id;markDirty();render();};$('detail').append(focus);}
    if(focusId){const back=document.createElement('button');back.textContent='Back to overview';back.onclick=()=>{focusId=null;markDirty();render();};$('detail').append(back);}
    if(n){const clear=document.createElement('button');clear.textContent='Show sources';clear.onclick=()=>select(null);$('detail').append(clear);}
    const items=n?nodes.filter(node=>near.has(node.id)):nodes.filter(node=>node.kind==='sources');
    $('list-title').textContent=(n?'Linked nodes':'Sources')+' · '+items.length;
    nodeList(items);
  }
  function render(preserveLayout=false) {
    const previousNodes=new Map(graphData.nodes.map(node=>[node.id,node]));
    $('legend').querySelectorAll('button[data-kind]').forEach(button=>button.setAttribute('aria-pressed',String(enabled.has(button.dataset.kind))));
    $('types').querySelectorAll('input[data-kind]').forEach(input=>{input.checked=enabled.has(input.dataset.kind);});
    const degrees=new Map();data.edges.forEach(e=>{degrees.set(e.source,(degrees.get(e.source)||0)+1);degrees.set(e.target,(degrees.get(e.target)||0)+1);});
    let filtered=data.nodes.filter(n=>enabled.has(n.kind)&&(!exampleMode||!$('shared').checked||n.kind==='entries'||degrees.get(n.id)>1));
    const query=exampleMode?$('search').value.trim().toLocaleLowerCase():'';
    if(query){const matches=new Set(filtered.filter(n=>n.label.toLocaleLowerCase().includes(query)).map(n=>n.id)),near=new Set(matches);data.edges.forEach(e=>{if(matches.has(e.source))near.add(e.target);if(matches.has(e.target))near.add(e.source);});filtered=filtered.filter(n=>near.has(n.id));}
    if(focusId){const keep=new Set([focusId]);data.edges.forEach(e=>{if(e.source===focusId)keep.add(e.target);if(e.target===focusId)keep.add(e.source);});filtered=filtered.filter(n=>keep.has(n.id));}
    const budget=Number($('density').value)||Infinity,limited=filtered.length>budget;
    const ranked=filtered.slice().sort((a,b)=>(degrees.get(b.id)||0)-(degrees.get(a.id)||0));
    // Reserve space for both sides of the bipartite graph so hubs retain their entries.
    let chosen=ranked;
    if(limited){
      const entries=ranked.filter(n=>n.kind==='entries').slice(0,Math.floor(budget*.5));
      const entryIds=new Set(entries.map(n=>n.id)),localDegrees=new Map();
      data.edges.forEach(e=>{if(entryIds.has(e.source))localDegrees.set(e.target,(localDegrees.get(e.target)||0)+1);});
      const others=ranked.filter(n=>n.kind!=='entries'&&localDegrees.has(n.id)).sort((a,b)=>(localDegrees.get(b.id)||0)-(localDegrees.get(a.id)||0)).slice(0,budget-entries.length);
      const used=new Set([...entries,...others].map(n=>n.id));
      chosen=[...entries,...others,...ranked.filter(n=>!used.has(n.id))].slice(0,budget);
      const ids=new Set(chosen.map(n=>n.id)),linked=new Set();
      data.edges.forEach(e=>{if(ids.has(e.source)&&ids.has(e.target)){linked.add(e.source);linked.add(e.target);}});
      if(linked.size)chosen=chosen.filter(n=>linked.has(n.id));
    }
    nodes=chosen.map((n,index)=>({...n,index,degree:degrees.get(n.id)||0}));
    const byId=new Map(nodes.map(n=>[n.id,n]));
    edges=data.edges.filter(e=>byId.has(e.source)&&byId.has(e.target)).map(e=>({...e,a:byId.get(e.source),b:byId.get(e.target)}));
    nodes.forEach(n=>n.visibleDegree=0);edges.forEach(e=>{e.a.visibleDegree++;e.b.visibleDegree++;});
    [...nodes].sort((a,b)=>b.visibleDegree-a.visibleDegree).forEach((n,i)=>n.labelRank=i);
    nodes.forEach(n=>{const smallGraph=nodes.length<=35;n.radius=n.kind==='entries'?(smallGraph?7:4.5):(smallGraph?16:Math.min(11,4+Math.sqrt(n.visibleDegree)));});
    // Separate neighborhoods around real, highly connected entity anchors.
    const anchors=[...nodes].filter(n=>n.kind!=='entries').sort((a,b)=>b.visibleDegree-a.visibleDegree).slice(0,4);
    const adjacency=new Map();edges.forEach(e=>{for(const [a,b] of [[e.source,e.target],[e.target,e.source]]){if(!adjacency.has(a))adjacency.set(a,[]);adjacency.get(a).push(b);}});
    nodes.forEach(n=>{const adjacent=adjacency.get(n.id)||[];const anchor=anchors.find(a=>a.id===n.id||adjacent.includes(a.id));const index=anchors.indexOf(anchor);n.clusterX=index<0?0:Math.cos(index*Math.PI/2)*220;n.clusterY=index<0?0:Math.sin(index*Math.PI/2)*160;});
    const grouping=$('group').value;
    if(grouping!=='relationships'){
      const groupOf=n=>grouping==='source'?n.source:(n.date||'').slice(0,7);
      const groups=[...new Set(nodes.filter(n=>n.kind==='entries').map(groupOf).filter(Boolean))].sort();
      nodes.forEach(n=>{let value=groupOf(n);if(!value){const neighbor=edges.find(e=>e.target===n.id);value=neighbor?groupOf(neighbor.a):'';}const i=groups.indexOf(value);n.clusterX=i<0?0:Math.cos(i*2*Math.PI/Math.max(1,groups.length))*350;n.clusterY=i<0?0:Math.sin(i*2*Math.PI/Math.max(1,groups.length))*250;});
    }
    const key=viewKey(),saved=savedViews[key];
    if(saved?.positions)nodes.forEach(n=>{const position=saved.positions[n.id];if(position&&Number.isFinite(position.x)&&Number.isFinite(position.y)){n.x=position.x;n.y=position.y;if(position.pinned){n.fx=n.x;n.fy=n.y;}else{delete n.fx;delete n.fy;}}});
    if(preserveLayout){
      nodes.forEach((node,index)=>{
        const previous=previousNodes.get(node.id);
        if(previous){node.x=previous.x;node.y=previous.y;node.vx=0;node.vy=0;if(previous.fx!=null){node.fx=previous.fx;node.fy=previous.fy;}else{delete node.fx;delete node.fy;}}
        else {const edge=edges.find(edge=>edge.source===node.id||edge.target===node.id),neighbor=edge&&previousNodes.get(edge.source===node.id?edge.target:edge.source);node.x=(neighbor?.x||0)+60*Math.cos(index*2.4);node.y=(neighbor?.y||0)+60*Math.sin(index*2.4);}
      });
    }
    graphData={nodes,background:preserveLayout,restored:!!saved?.positions,viewKey:key,links:edges.map(e=>({source:e.source,target:e.target}))};
    $('map-count').textContent=nodes.length+' nodes · '+edges.length+' links';
    showInfo('status',nodes.length+' / '+(data.total_nodes ?? data.nodes.length)+' matching nodes · '+Math.max(0,(data.total_nodes??data.nodes.length)-data.nodes.length)+' outside detail limit · '+(data.nodes.length-nodes.length)+' hidden by view filters · '+edges.length+' connections'+(data.omitted_sources?' · '+data.omitted_sources+' sources outside limit':'')+(limited||data.truncated?' · '+$('density').selectedOptions[0].text.split(' · ')[0]+'; search or increase detail to explore more.':'')+(!nodes.length?' · No matching nodes. Clear your search or change the filters.':''),!nodes.length);
    select(byId.has(selected)?selected:null);
  }
  function configureData(next,preserveLayout=false) {
    data=next;
    if(pendingState){
      enabled=new Set(pendingState.enabled);focusId=pendingState.focus;selected=null;
      savedViews[viewKey()]=pendingState.layout;pendingState=null;
    } else if(!enabled.size&&!currentView&&!graphData.viewKey){enabled=new Set(['entries','sources','daily','people','companies','tools','topics','objects']);}
    if(focusId&&!data.nodes.some(node=>node.id===focusId))focusId=null;
    if(selected&&!data.nodes.some(node=>node.id===selected))selected=null;
    const availableKinds=new Set(data.nodes.map(node=>node.kind));$('types').replaceChildren();
    $('legend').replaceChildren();
    const legendLabels={sources:'sources',entries:'entries',daily:'dates',people:'people',companies:'companies',tools:'tools',topics:'topics'};
    const legendKinds=[...Object.keys(legendLabels).filter(kind=>availableKinds.has(kind)),...[...availableKinds].filter(kind=>!legendLabels[kind]).sort()];
    legendKinds.forEach(kind=>{
      const item=document.createElement('li'),button=document.createElement('button'),dot=document.createElement('span');
      dot.className='kg-dot';dot.style.background=color(kind);dot.setAttribute('aria-hidden','true');
      button.type='button';button.dataset.kind=kind;button.title='Show or hide '+(legendLabels[kind]||kind.replaceAll('_',' ').toLowerCase());
      button.onclick=()=>{saveView();enabled.has(kind)?enabled.delete(kind):enabled.add(kind);markDirty();render();};
      button.append(dot,document.createTextNode(legendLabels[kind]||kind.replaceAll('_',' ').toLowerCase()));item.append(button);$('legend').append(item);
    });
    [...availableKinds].sort().forEach(kind=>{const label=document.createElement('label'),input=document.createElement('input'),dot=document.createElement('span');input.type='checkbox';input.dataset.kind=kind;input.checked=true;input.onchange=()=>{input.checked?enabled.add(kind):enabled.delete(kind);markDirty();render();};dot.className='kg-dot';dot.style.background=color(kind);label.append(input,dot,document.createTextNode(kind.replaceAll('_',' ')));$('types').append(label);});
    render(preserveLayout);
  }
  function showMode() {
    $('example-note').hidden=!exampleMode;
    const url=new URL(location.href);exampleMode?url.searchParams.set('example','1'):url.searchParams.delete('example');history.replaceState(null,'',url);
  }
  function setLoading(value) {
    loading=value; $('reload').disabled=value;
    $('loading').hidden=!value; $('stage').setAttribute('aria-busy',String(value));
    $('workspace').inert=value;
  }
  function sourceOptions(values) {
    $('source-options').replaceChildren();
    for(const value of ['',...new Set([...values,...selectedSources])]) {
      const label=document.createElement('label'),input=document.createElement('input');
      input.type='checkbox';input.checked=value?selectedSources.has(value):!selectedSources.size;
      input.onchange=()=>{if(!value)selectedSources.clear();else input.checked?selectedSources.add(value):selectedSources.delete(value);sourceOptions(values);};
      label.append(input,document.createTextNode(value||'All sources'));$('source-options').append(label);
    }
    $('source-caption').textContent=selectedSources.size?selectedSources.size+' sources selected':'All sources';
  }
  async function load() {
    backgroundController?.abort();
    saveView();
    requestController?.abort(); const version=++requestVersion;
    if(exampleMode){setLoading(false);configureData(exampleGraph());return;}
    requestController=new AbortController(); setLoading(true);showInfo('status','Loading your graph…',true);
    try {
      const params=requestParams();
      const response=await fetch('/api/hfl/entities/graph?'+params,{cache:'no-store',signal:requestController.signal});
      if(!response.ok)throw Error(response.status===401?'Sign in to view your knowledge graph.':'Graph could not load. Use Refresh to try again.');
      const next=await response.json();
      if(!exampleMode&&version===requestVersion){appliedParams=params.toString();graphSignature=signature(next);sourceOptions(next.sources||[]);configureData(next);}
    } catch(error){if(!exampleMode&&version===requestVersion&&error.name!=='AbortError')showInfo('status',error.message,true);} finally{if(version===requestVersion){setLoading(false);}}
  }
  // Poll only the applied query, without a loading overlay or interrupting interaction.
  const busy=()=>document.hidden||loading||exampleMode||viewOperation||!$('views-panel').hidden||$('filter-drawer').open||$('entry-dialog').open||document.activeElement===$('search')||Date.now()-lastInteraction<500;
  host.addEventListener('pointermove',event=>{if(event.buttons)lastInteraction=Date.now();});
  host.addEventListener('pointerdown',()=>{lastInteraction=Date.now();});
  host.addEventListener('wheel',()=>{lastInteraction=Date.now();},{passive:true});
  let refreshDelay=3000,nextRefresh=0;
  async function refreshInBackground(){
    if(busy()||backgroundController||!appliedParams||Date.now()<nextRefresh)return;
    const started=Date.now(),controller=new AbortController(),version=requestVersion,key=viewKey();backgroundController=controller;
    const timeout=setTimeout(()=>controller.abort('timeout'),45000);
    try{
      const liveParams=new URLSearchParams(appliedParams);applyRollingDates(liveParams);
      const response=await fetch('/api/hfl/entities/graph?'+liveParams,{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw Error(response.status===401?'Sign in again to resume automatic updates.':'Automatic update unavailable; reconnecting.');
      const next=await response.json();
      if(version!==requestVersion||key!==viewKey()||busy())return;
      const nextSignature=signature(next);
      if(nextSignature!==graphSignature){
        saveView();const snapshot=savedViews[graphData.viewKey];
        if(snapshot)savedViews[viewKey()]=snapshot;
        sourceOptions(next.sources||[]);configureData(next,true);graphSignature=nextSignature;
        $('live').textContent='Live · updated '+new Date().toLocaleTimeString();
      }
      refreshDelay=Math.max(3000,Math.min(60000,(Date.now()-started)*2));
      $('live').textContent='Live · checked '+new Date().toLocaleTimeString();
    }catch(error){if((error.name!=='AbortError'||controller.signal.reason==='timeout')&&version===requestVersion){$('live').textContent='Stale · '+error.message;refreshDelay=Math.min(60000,refreshDelay*2);}}
    finally{clearTimeout(timeout);nextRefresh=Date.now()+refreshDelay;if(backgroundController===controller)backgroundController=null;}
  }
  setInterval(refreshInBackground,1000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){nextRefresh=0;refreshInBackground();}});
  window.addEventListener('pagehide',()=>{backgroundController?.abort();});
  let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>exampleMode?render():load(),300);};
  $('filter').onclick=()=>{$('filter-drawer').close();if(!exampleMode)load();};$('group').onchange=()=>{savePreferences();render();};
  $('density').onchange=()=>exampleMode?render():load();$('shared').onchange=()=>exampleMode?render():load();$('in').onclick=()=>zoom(1.3);$('out').onclick=()=>zoom(1/1.3);$('fit').onclick=()=>{markDirty();fit();};$('reload').onclick=load;
  $('reset').onclick=()=>{clearTimeout(saveTimer);delete savedViews[graphData.viewKey];graphData.viewKey=null;markDirty();
    $('search').value='';$('density').value='100';$('rolling').value='0';$('since').value='';$('until').value='';selectedSources.clear();sourceOptions(data.sources||[]);syncDates();$('shared').checked=true;enabled=new Set(data.nodes.map(n=>n.kind));$('types').querySelectorAll('input').forEach(el=>el.checked=true);selected=null;focusId=null;exampleMode?render():load();};

  function setViewsOpen(open,restoreFocus=false){
    $('views-panel').hidden=!open;$('open-views').setAttribute('aria-expanded',String(open));
    if(restoreFocus)$('open-views').focus();
  }
  $('open-views').onclick=()=>setViewsOpen($('views-panel').hidden);
  document.addEventListener('click',event=>{if(!$('views-menu').contains(event.target))setViewsOpen(false);});
  $('views-menu').addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('views-panel').hidden){event.preventDefault();event.stopPropagation();setViewsOpen(false,true);}});
  $('views-menu').addEventListener('focusout',event=>{if(event.relatedTarget&&!$('views-menu').contains(event.relatedTarget))setViewsOpen(false);});
  $('open-filters').onclick=()=>{setViewsOpen(false);$('filter-drawer').showModal();$('open-filters').setAttribute('aria-expanded','true');};
  $('close-filters').onclick=()=>$('filter-drawer').close();
  $('filter-drawer').addEventListener('close',()=>{$('open-filters').setAttribute('aria-expanded','false');$('source-menu').open=false;$('open-filters').focus();});
  $('filter-drawer').addEventListener('click',event=>{const box=$('filter-drawer').getBoundingClientRect();if(event.target===$('filter-drawer')&&(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom))$('filter-drawer').close();});
  document.addEventListener('click',e=>{if(!$('source-menu').contains(e.target))$('source-menu').open=false;});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')$('source-menu').open=false;});
  sourceOptions([]);
  showMode();
  initializeViews();
})();
