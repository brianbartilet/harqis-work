import {readGraphState} from './graph-state.mjs';
import {placeLabels} from './graph-labels.mjs';
import {exampleGraph} from './knowledge-graph-example.js';
import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ForceGraph2D from 'react-force-graph-2d';
import {configureDragForces, releaseDragNeighbors, settleDragNodes} from './graph-drag.mjs';
import {PRESETS, randomizePresetNodes, presetLayout, presetFitPoints, motionOffset, phaseFor} from './graph-presets.mjs';
// Bundled locally. Graph data is fetched only from the authenticated HARQIS API.
(() => {
  'use strict';
  const $ = id => document.getElementById('kg-' + id);
  const ideasWorkspace=document.querySelector('.kg-shell').dataset.ideasWorkspace==='true';
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
  const kindLabel = kind => kind === 'companies' ? 'organizations' : kind.replaceAll('_', ' ');
  const palette = {entries:'#77dcf5', people:'#ffbd91', companies:'#deafff', tools:'#70edbd', topics:'#9bafff', daily:'#95a7c3', ideas:'#f9ca74', actions:'#fb8ca6'};
  const color = kind => palette[kind] || '#e9c96c';
  const defaultLabelKinds = new Set(['sources', 'people', 'tools', 'companies']);
  let data = {nodes:[],edges:[]}, nodes = [], edges = [], selected = null, enabled = new Set(['entries','sources','daily','people','companies','tools','topics','objects','ideas','actions']);
  let exampleMode=new URLSearchParams(location.search).get('example')==='1';
  let requestVersion=0, requestController=null, backgroundController=null, appliedParams=null, graphSignature='', lastInteraction=0;
  const activePointers=new Set();
  const signature=value=>JSON.stringify(value,(key,item)=>key==='locator'?undefined:item);
  const selectedSources=new Set();
  let loading=false, graphData={nodes:[],links:[]}, graphApi=null, active=null, focusId=null;
  const host=$('canvas'), root=createRoot(host);
  const touchViewport=window.matchMedia('(pointer: coarse)').matches;
  const uiFont=getComputedStyle(host).fontFamily;
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const endpointId=value=>typeof value==='object'?value.id:value;
  const duration=reducedMotion?0:500;
  let preset='timeline', animationMode='off', motionTime=0, transition=null, motionSettling=false;
  const animationKey='hfl:graph:animation:'+document.querySelector('.kg-shell').dataset.viewOwner;
  const detailKey='hfl:graph:detail:'+document.querySelector('.kg-shell').dataset.viewOwner;
  function saveDetail(){try {localStorage.setItem(detailKey,$('density').value);} catch {}}
  try {
    const detail=localStorage.getItem(detailKey);
    if(['100','500','1000','0'].includes(detail))$('density').value=detail;
  } catch {}
  function savedAnimation(){
    try {const mode=localStorage.getItem(animationKey);return !reducedMotion&&['off','breathing','ripple','drift'].includes(mode)?mode:'off';}
    catch {return 'off';}
  }
  let layoutTargets=new Map(), lastMotionFrame=0, lastClock=0;
  let layoutSeed=Math.random();
  let draggedNode=null, dragNodes=new Set();
  const stateKey='hfl:graph:state:v1:'+JSON.stringify([document.querySelector('.kg-shell').dataset.viewOwner,new URLSearchParams(location.search).get('context')||'',exampleMode,...(ideasWorkspace?['ideas']:[])]);
  let pendingState=null,stateReady=false,stateTimer;
  try {pendingState=readGraphState(localStorage,stateKey);} catch {}
  if(!ideasWorkspace&&pendingState?.preset==='mindmap')pendingState={...pendingState,preset:'timeline',positions:{},viewport:null,selected:null,focusId:null};
  function saveGraphState(){
    if(!stateReady||loading||!graphApi)return;
    const filters=Object.fromEntries(['search','density','rolling','since','until'].map(id=>[id,$(id).value]));
    filters.shared=$('shared').checked;
    const positions=Object.fromEntries(nodes.slice(0,10000).map(n=>[n.id,{...(layoutTargets.get(n.id)||{x:n.x,y:n.y}),manual:!!n.manual}]));
    const center=graphApi.screen2GraphCoords(host.clientWidth/2,host.clientHeight/2);
    try {localStorage.setItem(stateKey,JSON.stringify({version:1,layoutRevision:4,filters,enabled:[...enabled],sources:[...selectedSources],preset,animationMode,layoutSeed,selected,focusId,all:window.activityModals?.isAll(),positions,viewport:{...center,zoom:graphApi.zoom()}}));}
    catch { $('live').textContent='View could not be saved in this browser.'; }
  }
  function scheduleStateSave(){clearTimeout(stateTimer);stateTimer=setTimeout(saveGraphState,500);}
  document.addEventListener('click',scheduleStateSave);
  document.addEventListener('input',scheduleStateSave);
  document.addEventListener('change',scheduleStateSave);
  window.addEventListener('pagehide',saveGraphState);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)saveGraphState();});

  function followDrag(node,delta={x:0,y:0}){
    const starting=draggedNode!==node;
    if(starting&&transition){
      transition=null;
      for(const n of nodes)layoutTargets.set(n.id,{...layoutTargets.get(n.id),x:n.x,y:n.y});
    }
    draggedNode=node;
    if(starting){releaseDragNeighbors(node,nodes,edges,dragNodes,{x:node.x-delta.x,y:node.y-delta.y});configureDragForces(graphApi,true);draw();}
    lastInteraction=Date.now();
  }
  function finishDrag(){
    if(draggedNode||!dragNodes.size)return;
    settleDragNodes(dragNodes,layoutTargets,(node,target)=>motionOffset(animationMode,target,motionTime,node.phase,preset==='timeline'&&target.anchor));
    lastMotionFrame=performance.now();
    dragNodes.clear();
    draw();scheduleStateSave();
  }
  const viewKey=()=>JSON.stringify([preset,[...enabled].sort(),focusId]);
  function syncDates(){for(const id of ['since','until'])$(id).disabled=$('rolling').value!=='0';}
  function applyRollingDates(params){
    const days=Number(params.get('rolling'));if(!days)return;
    const end=new Date(),start=new Date(end);start.setDate(start.getDate()-days+1);
    const date=value=>[value.getFullYear(),String(value.getMonth()+1).padStart(2,'0'),String(value.getDate()).padStart(2,'0')].join('-');
    params.set('since',date(start));params.set('until',date(end));
  }
  function requestParams(){
    const params=new URLSearchParams({since:$('since').value,until:$('until').value,rolling:$('rolling').value,limit:$('density').value,query:$('search').value,shared:String($('shared').checked)});
    const context=window.activityModals?.context();if(context)params.set('context',context);
    if(window.HflIdeas?.maps.current)params.set('limit','0');
    selectedSources.forEach(source=>params.append('sources',source));applyRollingDates(params);return params;
  }
  $('rolling').onchange=syncDates;
  window.addEventListener('pageshow',event=>{if(event.persisted)window.location.reload();});
  function fit(animated=true){
    if(!graphApi||!graphData.nodes.length||graphData.nodes.some(n=>!Number.isFinite(n.x)||!Number.isFinite(n.y)))return;
    const bounds=graphApi.getGraphBbox();
    if(bounds&&[...bounds.x,...bounds.y].every(Number.isFinite))graphApi.zoomToFit(animated?duration:0,70);
  }
  function zoom(factor){lastInteraction=Date.now();if(graphApi)graphApi.zoom(graphApi.zoom()*factor,duration);}
  function fitTargets(animated=true,current=false){
    if(!graphApi||!layoutTargets.size)return;
    let left=Infinity,right=-Infinity,top=Infinity,bottom=-Infinity;
    const positions=current?new Map(nodes.map(n=>[n.id,{x:n.x,y:n.y}])):layoutTargets;
    const points=presetFitPoints(nodes,positions,preset);
    for(const p of points){left=Math.min(left,p.x);right=Math.max(right,p.x);top=Math.min(top,p.y);bottom=Math.max(bottom,p.y);}
    const scale=Math.max(.02,Math.min(preset==='mindmap'?1.3:4,(host.clientWidth-100)/Math.max(100,right-left),(host.clientHeight-100)/Math.max(100,bottom-top)));
    graphApi.zoom(scale,animated&&!reducedMotion?1000:0);
    graphApi.centerAt((left+right)/2,(top+bottom)/2,animated&&!reducedMotion?1000:0);
  }
  function updatePresetMenu(notice=''){
    host.dataset.preset=preset;
    document.querySelectorAll('[data-preset]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.preset===preset)));
    $('view-status').textContent=PRESETS[preset]+' preset';
    $('preset-notice').hidden=!notice;$('preset-notice').textContent=notice;
  }
  function choosePreset(next){
    draggedNode=null;dragNodes.clear();
    layoutSeed=Math.random();
    randomizePresetNodes(nodes,layoutSeed);
    if(graphApi)configureDragForces(graphApi);
    const layout=presetLayout(nodes,edges,next,layoutSeed);preset=layout.preset;layoutTargets=layout.positions;
    selected=null;active=null;transition={elapsed:0,from:new Map(nodes.map(n=>[n.id,{x:n.x,y:n.y}]))};
    nodes.forEach(n=>{n.manual=false;});motionTime=0;
    updatePresetMenu(layout.notice);setViewsOpen(false,true);select(null);
    fitTargets();
  }
  function setAnimation(mode,persist=true){
    animationMode=mode;motionSettling=true;
    const label=mode[0].toUpperCase()+mode.slice(1);
    $('animation-pill').textContent=label;
    $('animation-pill').dataset.mode=mode;
    if(persist)try {localStorage.setItem(animationKey,mode);} catch {}
    document.querySelectorAll('[data-animation]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.animation===mode)));
    host.dataset.animation=mode;
  }
  function motionPaused(){return document.hidden||loading||selected!==null||activePointers.size>0||Date.now()-lastInteraction<250||
    !!document.querySelector('dialog[open]:not(#activity-standalone)')||!$('views-panel').hidden||!$('animation-panel').hidden;}
  function animate(now){
    requestAnimationFrame(animate);
    const delta=Math.min(100,now-(lastClock||now));lastClock=now;
    const paused=motionPaused(),state=paused?'Paused':animationMode==='off'?'Motion is off':PRESETS[preset]+' · '+animationMode;
    if($('animation-status').textContent!==state)$('animation-status').textContent=state;
    host.dataset.motion=paused?'paused':animationMode;
    if(paused||draggedNode||dragNodes.size||!graphApi||(!transition&&animationMode==='off'&&!motionSettling)){lastMotionFrame=now;return;}
    motionTime+=delta;if(transition)transition.elapsed+=delta;
    if(now-lastMotionFrame<(nodes.length>1000?1000/15:1000/30))return;
    const elapsed=Math.min(100,now-lastMotionFrame);lastMotionFrame=now;
    const progress=transition?(reducedMotion?1:Math.min(1,transition.elapsed/1000)):1,ease=progress*progress*(3-2*progress);
    let unsettled=false;
    for(const n of nodes){
      if(n.manual)continue;
      const target=layoutTargets.get(n.id);if(!target)continue;
      const offset=motionOffset(animationMode,target,motionTime,n.phase,preset==='timeline'&&target.anchor);
      const from=transition?.from.get(n.id)||target;
      const x=from.x+(target.x-from.x)*ease+offset.x,y=from.y+(target.y-from.y)*ease+offset.y;
      const blend=transition||reducedMotion?1:1-Math.exp(-elapsed/120);
      n.x+=(x-n.x)*blend;n.y+=(y-n.y)*blend;n.fx=n.x;n.fy=n.y;
      if(Math.abs(x-n.x)+Math.abs(y-n.y)>.05)unsettled=true;
    }
    if(progress===1)transition=null;
    motionSettling=unsettled;
    graphApi.d3ReheatSimulation();
  }
  function Graph({data,activeId,selectedId}) {
    const ref=useRef();
    const [size,setSize]=useState({width:host.clientWidth,height:host.clientHeight});
    useEffect(()=>{
      const observer=new ResizeObserver(()=>setSize({width:host.clientWidth,height:host.clientHeight}));
      observer.observe(host);return()=>observer.disconnect();
    },[]);
    useEffect(()=>{
      graphApi=ref.current;
      configureDragForces(graphApi);
      if(data.viewport){const v=data.viewport;data.viewport=null;graphApi.zoom(v.zoom,0);graphApi.centerAt(v.x,v.y,0);}
      else if(data.fitOnce){data.fitOnce=false;requestAnimationFrame(()=>fitTargets(false));}
      stateReady=true;scheduleStateSave();
    },[data]);
    const near=connected(activeId);
    const isLinked=link=>activeId&&(endpointId(link.source)===activeId||endpointId(link.target)===activeId);
    function paintNode(node,ctx,globalScale){
      if(!Number.isFinite(node.x)||!Number.isFinite(node.y)||!Number.isFinite(globalScale)||globalScale<=0)return;
      const visible=!activeId||node.id===activeId||near.has(node.id);
      const radius=node.radius/globalScale;
      const ink=color(node.kind),emphasis=node.id===activeId||node.id===selectedId;
      ctx.save();ctx.globalAlpha=visible?(node.status==='dismissed'?.35:1):.075;
      // Thousands of per-entry gradients dominate mobile drawing time. Keep
      // detailed lighting for hubs and selected nodes, and compact activity dots.
      if(data.nodes.length>1000&&node.kind==='entries'&&!emphasis){
        ctx.fillStyle=ink;ctx.beginPath();ctx.arc(node.x,node.y,radius,0,2*Math.PI);ctx.fill();ctx.restore();return;
      }
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
      ctx.restore();
    }
    return <ForceGraph2D ref={ref} width={size.width} height={size.height}
      graphData={data} enableNodeDrag={!touchViewport} enablePanInteraction={true} enableZoomInteraction={true} backgroundColor="rgba(0,0,0,0)" nodeLabel={()=>''}
      onRenderFramePost={(ctx,scale)=>{
        if(!ref.current||!Number.isFinite(scale)||scale<=0)return;
        const origin=ref.current.screen2GraphCoords(0,0);
        const candidates=data.nodes.filter(n=>!activeId||n.id===activeId||n.id===selectedId||near.has(n.id)).map(n=>({
          id:n.id,label:n.label,kind:n.kind,x:(n.x-origin.x)*scale,y:(n.y-origin.y)*scale,
          radius:n.radius,degree:n.visibleDegree,preferred:n.kind===(preset==='timeline'?'daily':preset)||defaultLabelKinds.has(n.kind),
          pinned:!!n.manual,emphasis:n.id===activeId||n.id===selectedId
        }));
        ctx.save();
        const labels=placeLabels(candidates,{width:size.width,height:size.height,zoom:scale},(text,font)=>{
          ctx.font=`500 ${font}px ${uiFont}`;return ctx.measureText(text).width;
        });
        for(const box of labels){
          const x=origin.x+box.x/scale,y=origin.y+box.y/scale,ink=color(box.node.kind);
          ctx.fillStyle=box.node.emphasis?'#142a42f5':'#0a1728ee';ctx.beginPath();
          ctx.roundRect(x,y,box.w/scale,box.h/scale,5/scale);ctx.fill();
          ctx.strokeStyle=ink+(box.node.emphasis?'90':'30');ctx.lineWidth=.6/scale;ctx.stroke();
          ctx.font=`500 ${(box.node.emphasis?13:11)/scale}px ${uiFont}`;ctx.textAlign='left';ctx.textBaseline='middle';
          ctx.fillStyle=box.node.emphasis?'#ffffff':'#d9e9fa';ctx.fillText(box.text,x+6/scale,y+12/scale);
        }
        ctx.restore();
      }}
      nodeCanvasObject={paintNode}
      nodePointerAreaPaint={(node,paint,ctx)=>{ctx.fillStyle=paint;ctx.beginPath();ctx.arc(node.x,node.y,(node.radius+4)/(ref.current?.zoom()||1),0,2*Math.PI);ctx.fill();}}
      linkColor={link=>color(link.target.kind)+(activeId?(isLinked(link)?'df':'07'):(data.nodes.length<=35?'70':'32'))}
      linkDirectionalArrowLength={link=>['ideas','actions'].includes(link.source.kind)||['ideas','actions'].includes(link.target.kind)?4:0}
      linkDirectionalArrowRelPos={0.8}
      linkWidth={link=>isLinked(link)?2:data.nodes.length<=35?1.1:.65} linkCurvature={.16}
      linkDirectionalParticles={0}
      linkDirectionalParticleWidth={2} linkDirectionalParticleSpeed={.004}
      onZoom={()=>{if(activePointers.size)lastInteraction=Date.now();scheduleStateSave();}}
      onNodeHover={node=>{host.style.cursor=node?'pointer':'grab';if(!touchViewport)highlight(node?.id||selected);}}
      onNodeClick={node=>select(node.id)} onBackgroundClick={()=>select(null)}
      onNodeDrag={followDrag}
      onNodeDragEnd={node=>{draggedNode=null;node.manual=true;layoutTargets.set(node.id,{x:node.x,y:node.y,anchor:false});node.fx=node.x;node.fy=node.y;draw();graphApi.d3ReheatSimulation();}}
      warmupTicks={0} cooldownTicks={reducedMotion||(!draggedNode&&!dragNodes.size)?0:Infinity}
      d3VelocityDecay={dragNodes.size?.2:.4}
      d3AlphaMin={.001}
      onEngineStop={finishDrag}

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
      dot.className='kg-dot';dot.style.background=color(n.kind);name.textContent=n.label;meta.textContent=n.visibleDegree+' links';button.title=n.label+' · '+kindLabel(n.kind);
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
      const heading=article.querySelector('h2');
      if(item.action_url&&heading){
        const header=document.createElement('div'),action=document.createElement('a');
        header.className='corpus-entry-header';
        action.className='corpus-followup-action';action.href=item.action_url;action.textContent='Make actionable ↗';
        action.setAttribute('aria-label','Create a follow-up from this HFL entry');
        heading.before(header);header.append(heading,action);
      }
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
    const eyebrow=document.createElement('span');eyebrow.className='kg-eyebrow';eyebrow.textContent=n?kindLabel(n.kind):'Your knowledge, connected';$('detail').append(eyebrow);
    heading.textContent=n?n.label:'';
    description.textContent=n?[kindLabel(n.kind),n.date,n.source,near.size+' visible connections'].filter(Boolean).join(' · '):'Select an orb to explore its linked entries and entities.';
    if(n)$('detail').append(heading);$('detail').append(description);
    if(n?.href&&n.kind==='entries') {const button=document.createElement('button');button.textContent='Open entry';button.className='kg-open-entry';button.onclick=()=>openEntry(n.id.replace(/^entry:/,''),n.locator);$('detail').append(button);}
    if(!exampleMode)window.HflIdeas?.inspect(n,$('detail'),data.edges);
    if(n){const focus=document.createElement('button');focus.textContent='Focus on this connection';focus.className='kg-focus-button';focus.onclick=()=>{focusId=n.id;render();};$('detail').append(focus);}
    if(focusId){const back=document.createElement('button');back.textContent='Back to overview';back.onclick=()=>{focusId=null;render();};$('detail').append(back);}
    if(n){const clear=document.createElement('button');clear.textContent='Clear selection';clear.onclick=()=>select(null);$('detail').append(clear);}
    const items=n?nodes.filter(node=>near.has(node.id)):preset==='mindmap'?nodes:nodes.filter(node=>node.kind===(preset==='timeline'?'daily':preset));
    $('list-title').textContent=(n?'Linked nodes':preset==='mindmap'?'Map members':PRESETS[preset])+' · '+items.length;
    nodeList(items);
  }
  function render(preserveLayout=false) {
    draggedNode=null;dragNodes.clear();
    const previousNodes=new Map(graphData.nodes.map(node=>[node.id,node]));
    const previousTargets=layoutTargets;
    $('legend').querySelectorAll('button[data-kind]').forEach(button=>button.setAttribute('aria-pressed',String(enabled.has(button.dataset.kind))));
    $('types').querySelectorAll('input[data-kind]').forEach(input=>{input.checked=enabled.has(input.dataset.kind);});
    const degrees=new Map();data.edges.forEach(e=>{degrees.set(e.source,(degrees.get(e.source)||0)+1);degrees.set(e.target,(degrees.get(e.target)||0)+1);});
    let filtered=data.nodes.filter(n=>enabled.has(n.kind)&&(!exampleMode||!$('shared').checked||n.kind==='entries'||degrees.get(n.id)>1));
    const query=exampleMode?$('search').value.trim().toLocaleLowerCase():'';
    if(query){const matches=new Set(filtered.filter(n=>n.label.toLocaleLowerCase().includes(query)).map(n=>n.id)),near=new Set(matches);data.edges.forEach(e=>{if(matches.has(e.source))near.add(e.target);if(matches.has(e.target))near.add(e.source);});filtered=filtered.filter(n=>near.has(n.id));}
    if(focusId){const keep=new Set([focusId]);data.edges.forEach(e=>{if(e.source===focusId)keep.add(e.target);if(e.target===focusId)keep.add(e.source);});filtered=filtered.filter(n=>keep.has(n.id));}
    const budget=window.HflIdeas?.maps.current?Infinity:(Number($('density').value)||Infinity),limited=filtered.length>budget;
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
    nodes.forEach(n=>{const smallGraph=nodes.length<=35;n.radius=n.kind==='entries'?(smallGraph?7:4.5):(smallGraph?10:4)+4*Math.log2(1+n.visibleDegree);});
    const anchors=nodes.filter(n=>n.kind!=='entries').sort((a,b)=>b.visibleDegree-a.visibleDegree).slice(0,4);
    const adjacency=new Map(nodes.map(n=>[n.id,new Set()]));
    for(const e of edges){adjacency.get(e.source).add(e.target);adjacency.get(e.target).add(e.source);}
    for(const n of nodes){
      const index=anchors.findIndex(a=>a.id===n.id||adjacency.get(n.id).has(a.id));
      n.clusterX=index<0?0:Math.cos(index*Math.PI/2)*220;
      n.clusterY=index<0?0:Math.sin(index*Math.PI/2)*160;
    }
    if(!preserveLayout){if(!pendingState)layoutSeed=Math.random();randomizePresetNodes(nodes,layoutSeed);}
    const layout=presetLayout(nodes,edges,window.HflIdeas?.maps.current?'mindmap':preset,layoutSeed);preset=layout.preset;layoutTargets=layout.positions;
    nodes.forEach(node=>{
      const previous=previousNodes.get(node.id),target=layoutTargets.get(node.id);
      if(preserveLayout&&previous){Object.assign(node,{x:previous.x,y:previous.y,manual:previous.manual});layoutTargets.set(node.id,previousTargets.get(node.id)||{x:node.x,y:node.y});}
      else {node.x=target.x;node.y=target.y;}
      const saved=window.HflIdeas?.maps.pendingPositions?.[node.id]||pendingState?.positions?.[node.id];
      if(saved){node.x=saved.x;node.y=saved.y;node.manual=!!saved.manual;layoutTargets.set(node.id,{...target,x:saved.x,y:saved.y});}
      node.fx=node.x;node.fy=node.y;node.phase=phaseFor(node.id);
    });
    transition=null;if(!preserveLayout)motionTime=0;
    const restoredViewport=nodes.some(n=>pendingState?.positions?.[n.id])?pendingState?.viewport:null;
    pendingState=null;
    if(window.HflIdeas)window.HflIdeas.maps.pendingPositions=null;
    graphData={nodes,viewport:restoredViewport,fitOnce:!preserveLayout,links:edges.map(e=>({source:e.source,target:e.target}))};
    updatePresetMenu(layout.notice);
    $('map-count').textContent=nodes.length+' nodes · '+edges.length+' links';
    showInfo('status',nodes.length+' / '+(data.total_nodes ?? data.nodes.length)+' matching nodes · '+Math.max(0,(data.total_nodes??data.nodes.length)-data.nodes.length)+' outside detail limit · '+(data.nodes.length-nodes.length)+' hidden by view filters · '+edges.length+' connections'+(data.omitted_sources?' · '+data.omitted_sources+' sources outside limit':'')+(limited||data.truncated?' · '+$('density').selectedOptions[0].text.split(' · ')[0]+'; search or increase detail to explore more.':'')+(!nodes.length?' · No matching nodes. Clear your search or change the filters.':''),!nodes.length);
    select(byId.has(selected)?selected:null);
  }
  function configureData(next,preserveLayout=false) {
    const map=window.HflIdeas?.maps.current;
    if(map){const members=new Set(map.members);next={...next,nodes:next.nodes.filter(n=>members.has(n.id)),edges:next.edges.filter(e=>members.has(e.source)&&members.has(e.target))};next.total_nodes=next.nodes.length;next.truncated=false;}
    data=next;
    if(focusId&&!data.nodes.some(node=>node.id===focusId))focusId=null;
    if(selected&&!data.nodes.some(node=>node.id===selected))selected=null;
    const availableKinds=new Set(data.nodes.map(node=>node.kind));$('types').replaceChildren();
    $('legend').replaceChildren();
    const legendLabels={sources:'sources',entries:'entries',daily:'dates',people:'people',companies:'organizations',tools:'tools',topics:'topics'};
    const legendKinds=[...Object.keys(legendLabels).filter(kind=>availableKinds.has(kind)),...[...availableKinds].filter(kind=>!legendLabels[kind]).sort()];
    legendKinds.forEach(kind=>{
      const item=document.createElement('li'),button=document.createElement('button'),dot=document.createElement('span');
      dot.className='kg-dot';dot.style.background=color(kind);dot.setAttribute('aria-hidden','true');
      button.type='button';button.dataset.kind=kind;button.title='Show or hide '+(legendLabels[kind]||kind.replaceAll('_',' ').toLowerCase());
      button.onclick=()=>{enabled.has(kind)?enabled.delete(kind):enabled.add(kind);render();};
      button.append(dot,document.createTextNode(legendLabels[kind]||kind.replaceAll('_',' ').toLowerCase()));item.append(button);$('legend').append(item);
    });
    [...availableKinds].sort().forEach(kind=>{const label=document.createElement('label'),input=document.createElement('input'),dot=document.createElement('span');input.type='checkbox';input.dataset.kind=kind;input.checked=true;input.onchange=()=>{input.checked?enabled.add(kind):enabled.delete(kind);render();};dot.className='kg-dot';dot.style.background=color(kind);label.append(input,dot,document.createTextNode(kindLabel(kind)));$('types').append(label);});
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
    delete $('info').dataset.error;
    backgroundController?.abort();

    requestController?.abort(); const version=++requestVersion;
    if(exampleMode){setLoading(false);configureData(exampleGraph());return;}
    requestController=new AbortController(); setLoading(true);showInfo('status','Loading your graph…',true);
    try {
      const params=requestParams();
      const response=await fetch('/api/hfl/entities/graph?'+params,{cache:'no-store',signal:requestController.signal});
      if(!response.ok)throw Error(response.status===401?'Sign in to view your knowledge graph.':'Graph could not load. Use Refresh to try again.');
      const next=await response.json();
      if(!exampleMode&&version===requestVersion){appliedParams=params.toString();graphSignature=signature(next);sourceOptions(next.sources||[]);configureData(next);}
    } catch(error){if(!exampleMode&&version===requestVersion&&error.name!=='AbortError'){$('info').dataset.error='true';showInfo('status',error.message,true);}} finally{if(version===requestVersion){setLoading(false);}}
  }
  // Poll only the applied query, without a loading overlay or interrupting interaction.
  const busy=()=>document.hidden||!!transition||dragNodes.size>0||activePointers.size>0||document.querySelector('.activity-modal[open]:not(#activity-standalone)')||loading||exampleMode||!$('views-panel').hidden||!$('animation-panel').hidden||$('filter-drawer').open||$('entry-dialog').open||document.querySelector('.idea-dialog[open]')||document.activeElement===$('search')||Date.now()-lastInteraction<500;
  host.addEventListener('pointermove',event=>{if(event.buttons||activePointers.size)lastInteraction=Date.now();});
  host.addEventListener('pointerdown',event=>{activePointers.add(event.pointerId);lastInteraction=Date.now();},{capture:true});
  for(const name of ['pointerup','pointercancel'])window.addEventListener(name,event=>{
    if(activePointers.delete(event.pointerId))lastInteraction=Date.now();
  },{capture:true});
  window.addEventListener('blur',()=>activePointers.clear());
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
  $('filter').onclick=()=>{$('filter-drawer').close();if(!exampleMode)load();};
  $('density').onchange=()=>{saveDetail();exampleMode?render():load();};$('shared').onchange=()=>exampleMode?render():load();$('in').onclick=()=>zoom(1.3);$('out').onclick=()=>zoom(1/1.3);$('fit').onclick=()=>fitTargets(true,true);$('reload').onclick=async()=>{try{await window.HflIdeas?.maps.reload();await load();}catch(error){showInfo('status',error.message,true);}};
  $('reset').onclick=()=>{
    pendingState=null;try {localStorage.removeItem(stateKey);} catch {}
    window.activityModals?.reset();preset='timeline';setAnimation('off');
    $('search').value='';$('density').value='100';$('rolling').value='0';$('since').value='';$('until').value='';
    saveDetail();
    selectedSources.clear();sourceOptions(data.sources||[]);syncDates();$('shared').checked=false;
    enabled=new Set(['entries','sources','daily','people','companies','tools','topics','objects','ideas','actions']);selected=null;focusId=null;exampleMode?render():load();
  };


  function setViewsOpen(open,restoreFocus=false){
    $('views-panel').hidden=!open;$('open-views').setAttribute('aria-expanded',String(open));
    if(restoreFocus)$('open-views').focus();
  }
  $('open-views').onclick=()=>{setAnimationOpen(false);setViewsOpen($('views-panel').hidden);};
  document.querySelectorAll('[data-preset]').forEach(button=>button.onclick=()=>choosePreset(button.dataset.preset));
  function setAnimationOpen(open,restoreFocus=false){
    $('animation-panel').hidden=!open;$('open-animation').setAttribute('aria-expanded',String(open));
    if(restoreFocus)$('open-animation').focus();
  }
  $('open-animation').onclick=()=>{setViewsOpen(false);setAnimationOpen($('animation-panel').hidden);};
  document.querySelectorAll('[data-animation]').forEach(button=>button.onclick=()=>{setAnimation(button.dataset.animation);setAnimationOpen(false,true);});
  document.addEventListener('click',event=>{if(!$('animation-menu').contains(event.target))setAnimationOpen(false);});
  $('animation-menu').addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('animation-panel').hidden){event.preventDefault();event.stopPropagation();setAnimationOpen(false,true);}});
  $('animation-menu').addEventListener('focusout',event=>{if(event.relatedTarget&&!$('animation-menu').contains(event.relatedTarget))setAnimationOpen(false);});
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
  window.addEventListener('hfl:activity-scope',()=>{focusId=null;selected=null;load();});
  $('entities').onclick=()=>{
    const params=new URLSearchParams(appliedParams||requestParams());
    const context=params.get('context')||'';params.delete('context');
    window.activityModals.open('entities',context,params.toString());
  };
  if(pendingState){
    for(const id of ['search','density','rolling','since','until']){
      const value=pendingState.filters[id];
      if(typeof value==='string'&&($(id).tagName!=='SELECT'||[...$(id).options].some(o=>o.value===value)))$(id).value=value;
    }
    $('shared').checked=pendingState.filters.shared===true;
    enabled=new Set([...pendingState.enabled,'ideas','actions']);pendingState.sources.forEach(s=>selectedSources.add(s));
    if(PRESETS[pendingState.preset])preset=pendingState.preset;
    if(Number.isFinite(pendingState.layoutSeed))layoutSeed=pendingState.layoutSeed;
    selected=typeof pendingState.selected==='string'?pendingState.selected:null;
    focusId=typeof pendingState.focusId==='string'?pendingState.focusId:null;
    window.activityModals?.setAll(pendingState.all);syncDates();sourceOptions([]);
  }
  showMode();
  setAnimation(!reducedMotion&&['off','breathing','ripple','drift'].includes(pendingState?.animationMode)?pendingState.animationMode:savedAnimation(),false);
  requestAnimationFrame(animate);
  if(window.HflIdeas){
    window.HflIdeas.maps.getPositions=()=>Object.fromEntries(nodes.map(n=>[n.id,{x:n.x,y:n.y}]));
    window.addEventListener('hfl:ideas-updated',()=>{focusId=null;load();});
    if(ideasWorkspace)window.HflIdeas.maps.init(document.getElementById('idea-map-tools')).then(load);
    else load();
  }else load();
})();
