import {readGraphState} from './graph-state.mjs';
import {createLabelLayout} from './graph-labels.mjs';
import {boardCurvature} from './graph-curves.mjs';
import {exampleGraph} from './knowledge-graph-example.js';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ForceGraph2D from 'react-force-graph-2d';
import {configureDragForces, releaseDragNeighbors, settleDragNodes} from './graph-drag.mjs';
import {PRESETS, randomizePresetNodes, presetLayout, presetFitPoints, motionOffset, phaseFor} from './graph-presets.mjs';
// Bundled locally. Graph data is fetched only from the authenticated HARQIS API.
(() => {
  'use strict';
  const $ = id => document.getElementById('kg-' + id);
  const readOnly = document.querySelector('.kg-shell').dataset.readonly === 'true';
  const capacityEnabled=!readOnly&&new URLSearchParams(location.search).get('embed')!=='1';
  const capacityKey='hfl:graph:capacity:v1:'+document.querySelector('.kg-shell').dataset.viewOwner;
  const recommendedCapacity={nodes:500,edges:2000};
  let capacityLimits={...recommendedCapacity},capacityBlocked=false,capacityPreview=false;
  try {
    const saved=JSON.parse(localStorage.getItem(capacityKey));
    if(Number.isInteger(saved?.nodes)&&saved.nodes>=100&&saved.nodes<=1000&&Number.isInteger(saved?.edges)&&saved.edges>=100&&saved.edges<=4000)capacityLimits=saved;
  } catch {}
  function syncCapacitySettings(){
    $('node-limit').value=capacityLimits.nodes;$('edge-limit').value=capacityLimits.edges;
    $('capacity-settings').hidden=!capacityEnabled||!!window.HflIdeas?.maps.current;
  }
  syncCapacitySettings();
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
  const kindLabel = kind => ({companies:'organizations', drafts:'thoughts', thoughts:'list thoughts'}[kind] || kind.replaceAll('_', ' '));
  const palette = {entries:'#77dcf5', people:'#ffbd91', companies:'#deafff', tools:'#70edbd', topics:'#9bafff', daily:'#95a7c3', ideas:'#f9ca74', actions:'#fb8ca6', goals:'#a7f3d0', drafts:'#c4b5fd', lists:'#5eead4', thoughts:'#c4b5fd', boards:'#93c5fd'};
  const color = kind => palette[kind] || '#e9c96c';
  window.HflGraphAppearance = {color, kindLabel};
  const defaultLabelKinds = new Set(['sources', 'people', 'tools', 'companies']);
  let data = {nodes:[],edges:[]}, nodes = [], edges = [], selected = null, enabled = new Set(['entries','sources','daily','people','companies','tools','topics','objects','ideas','actions','goals','drafts','boards','lists','thoughts']);
  let exampleMode=new URLSearchParams(location.search).get('example')==='1';
  let requestVersion=0, requestController=null, backgroundController=null, appliedParams=null, graphSignature='', lastInteraction=0;
  const activePointers=new Set();
  const signature=value=>JSON.stringify(value,(key,item)=>key==='locator'?undefined:item);
  const selectedSources=new Set();
  let loading=false, graphData={nodes:[],links:[]}, graphApi=null, active=null, focusId=null;
  let nodeActions=[];
  let labelRevision=0;
  let labelRefreshAt=0,labelFadeUntil=0,arrivalFadeUntil=0;
  let setGraphRedraw=null,graphRedraw=true;
  const nodeArrivals=new Map(),edgeArrivals=new Map();
  const arrivalKey=edge=>[endpointId(edge.source),endpointId(edge.target),edge.relation||'',!!edge.local].join('|');
  const arrivalAlpha=(time)=>reducedMotion||time===undefined?1:Math.min(1,Math.max(0,(performance.now()-time)/400));
  const host=$('canvas'), root=createRoot(host);
  const touchViewport=window.matchMedia('(pointer: coarse)').matches;
  const uiFont=getComputedStyle(host).fontFamily;
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let connectionInteraction=false, graphEscapePending=false;
  const endpointId=value=>typeof value==='object'?value.id:value;
  const duration=reducedMotion?0:500;
  let preset='timeline', animationMode='off', motionTime=0, transition=null, motionSettling=false;
  const animationKey='hfl:graph:animation:'+document.querySelector('.kg-shell').dataset.viewOwner;
  function savedAnimation(){
    try {const mode=localStorage.getItem(animationKey);return !reducedMotion&&['off','breathing','ripple','drift'].includes(mode)?mode:'off';}
    catch {return 'off';}
  }
  let layoutTargets=new Map(), lastMotionFrame=0, lastClock=0;
  let renderedBoardId=null, boardLayoutPositions={};
  let layoutSeed=Math.random();
  let draggedNode=null, dragNodes=new Set();
  const stateKey='hfl:graph:state:v1:'+JSON.stringify([document.querySelector('.kg-shell').dataset.viewOwner,new URLSearchParams(location.search).get('context')||'',exampleMode]);
  let pendingState=null,stateReady=false,stateTimer;
  try {if(!readOnly)pendingState=readGraphState(localStorage,stateKey);} catch {}
  if(pendingState?.preset==='mindmap')pendingState={...pendingState,preset:'timeline',positions:{},viewport:null,selected:null,focusId:null};
  function saveGraphState(){
    if(readOnly)return;
    if(!stateReady||loading||capacityBlocked||!graphApi||window.HflIdeas?.maps.current)return;
    const filters=Object.fromEntries(['search','rolling','since','until'].map(id=>[id,$(id).value]));
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

  const shell=document.querySelector('.kg-shell');
  let fullscreen=false, fullscreenScroll={x:0,y:0}, previousOverflow='', fullscreenFitPending=false;
  function updateFullscreen() {
    if(readOnly)return;
    shell.classList.toggle('kg-has-selection',!!selected);
    const chips=[window.HflIdeas?.maps.current?.name||PRESETS[preset]];
    chips.push(document.querySelector('[data-active-view-name]')?.textContent||'All activity');
    if($('search').value)chips.push('Search: '+$('search').value);
    chips.push(capacityBlocked?'Graph exceeds capacity':data.capacity?.preview?'Limited preview':'All matching nodes');
    if($('rolling').value!=='0')chips.push($('rolling').selectedOptions[0].textContent);
    else for(const id of ['since','until'])if($(id).value)chips.push(id+': '+$(id).value);
    if(selectedSources.size)chips.push('Sources: '+[...selectedSources].join(', '));
    if($('shared').checked)chips.push('Shared connections only');
    const excluded=[...$('types').querySelectorAll('input:not(:checked)')].map(input=>input.closest('label').textContent.trim());
    if(excluded.length)chips.push('Hidden types: '+excluded.join(', '));
    if(focusId)chips.push('Focused connection');
    $('fullscreen-filters').replaceChildren(...chips.filter(Boolean).map(text=>{const chip=document.createElement('span');chip.textContent=text;return chip;}));
  }
  function setFullscreen(value) {
    if(readOnly||fullscreen===value)return;
    fullscreenFitPending=true;
    fullscreen=value;
    if(value){fullscreenScroll={x:scrollX,y:scrollY};previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';}
    else document.body.style.overflow=previousOverflow;
    shell.classList.toggle('kg-fullscreen',value);
    shell.classList.remove('kg-show-boards');
    $('toggle-boards').setAttribute('aria-expanded','false');
    $('fullscreen').setAttribute('aria-expanded',String(value));
    $('fullscreen-bar').hidden=!value;$('fullscreen-filters').hidden=!value;
    updateFullscreen();
    if(value)$('exit-fullscreen').focus({preventScroll:true});
    else {window.scrollTo(fullscreenScroll.x,fullscreenScroll.y);$('fullscreen').focus({preventScroll:true});}
  }
  if(!readOnly){
    $('fullscreen').onclick=()=>setFullscreen(true);
    $('exit-fullscreen').onclick=()=>setFullscreen(false);
    $('toggle-boards').onclick=()=>{
      const open=shell.classList.toggle('kg-show-boards');
      $('toggle-boards').setAttribute('aria-expanded',String(open));
    };
    // Capture dialog/gesture state before their own Escape handlers consume it.
    document.addEventListener('keydown',event=>{
      if(!fullscreen||event.key!=='Escape')return;
      if(document.querySelector('dialog[open]')||graphEscapePending||event.target.closest?.('[role="menu"]')||!$('views-panel').hidden||!$('animation-panel').hidden||$('source-menu').open)return;
      event.preventDefault();event.stopImmediatePropagation();setFullscreen(false);
    },true);
    document.addEventListener('focusin',event=>{
      if(fullscreen&&!shell.contains(event.target)&&!document.querySelector('dialog[open]'))$('exit-fullscreen').focus();
    });
    shell.addEventListener('input',updateFullscreen);
    shell.addEventListener('change',updateFullscreen);
  }

  function followDrag(node,delta={x:0,y:0}){
    labelRevision++;
    const starting=draggedNode!==node;
    if(starting&&transition){
      transition=null;
      for(const n of nodes)layoutTargets.set(n.id,{...layoutTargets.get(n.id),x:n.x,y:n.y});
    }
    draggedNode=node;
    if(window.HflIdeas?.maps.current){
      node.manual=true;node.fx=node.x;node.fy=node.y;
      const previous=layoutTargets.get(node.id)||{x:node.x-delta.x,y:node.y-delta.y};
      const movement={x:node.x-previous.x,y:node.y-previous.y};
      if(node.kind==='lists')for(const child of nodes.filter(n=>n.list_id===node.id)){
        const origin=layoutTargets.get(child.id)||child;
        child.x=origin.x+movement.x;child.y=origin.y+movement.y;child.fx=child.x;child.fy=child.y;child.manual=true;
        layoutTargets.set(child.id,{...layoutTargets.get(child.id),x:child.x,y:child.y});
        boardLayoutPositions[child.id]={x:child.x,y:child.y};
      }
      layoutTargets.set(node.id,{...previous,x:node.x,y:node.y});
      lastInteraction=Date.now();return;
    }
    if(starting){releaseDragNeighbors(node,nodes,edges,dragNodes,{x:node.x-delta.x,y:node.y-delta.y});configureDragForces(graphApi,true);draw();}
    lastInteraction=Date.now();
  }
  function finishDrag(){
    if(draggedNode||!dragNodes.size)return;
    settleDragNodes(dragNodes,layoutTargets,(node,target)=>motionOffset(animationMode,target,motionTime,node.phase,preset==='timeline'&&target.anchor));
    lastMotionFrame=performance.now();
    dragNodes.clear();
    draw();scheduleStateSave();if(window.HflIdeas?.maps.current)window.HflIdeas.maps.saveLayout();
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
    const params=new URLSearchParams({since:$('since').value,until:$('until').value,rolling:$('rolling').value,limit:'0',query:$('search').value,shared:String($('shared').checked)});
    const context=window.activityModals?.context();if(context)params.set('context',context);
    if(window.HflIdeas?.maps.current)return new URLSearchParams({limit:'0'});
    if(capacityEnabled){
      params.set('capacity_guard','true');params.set('node_limit',capacityLimits.nodes);params.set('edge_limit',capacityLimits.edges);
      params.set('preview',String(capacityPreview));
    }
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
  let lastChosenPreset=preset;
  function choosePreset(next){
    lastChosenPreset=next;
    labelRevision++;
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
  function motionPaused(){return capacityBlocked||connectionInteraction||document.hidden||loading||selected!==null||activePointers.size>0||Date.now()-lastInteraction<250||
    !!document.querySelector('dialog[open]:not(#activity-standalone)')||!$('views-panel').hidden||!$('animation-panel').hidden;}
  function animate(now){
    requestAnimationFrame(animate);
    const paused=motionPaused();
    const moving=!paused&&!draggedNode&&!dragNodes.size&&!!graphApi&&(!!transition||animationMode!=='off'||motionSettling);
    // Motion owns continuous drawing; label refreshes only wake an idle graph.
    const redraw=!document.hidden&&(moving||now>=labelRefreshAt||now<labelFadeUntil+50||now<arrivalFadeUntil+50);
    if(setGraphRedraw&&redraw!==graphRedraw){graphRedraw=redraw;setGraphRedraw(redraw);}
    const delta=Math.min(100,now-(lastClock||now));lastClock=now;
    const state=paused?'Paused':animationMode==='off'?'Motion is off':PRESETS[preset]+' · '+animationMode;
    if($('animation-status').textContent!==state)$('animation-status').textContent=state;
    host.dataset.motion=paused?'paused':animationMode;
    if(!moving){lastMotionFrame=now;return;}
    motionTime+=delta;if(transition)transition.elapsed+=delta;
    const elapsed=Math.min(100,now-lastMotionFrame);lastMotionFrame=now;
    const progress=transition?(reducedMotion?1:Math.min(1,transition.elapsed/1000)):1,ease=progress*progress*(3-2*progress);
    let unsettled=false;
    for(const n of nodes){
      if(n.manual&&!window.HflIdeas?.maps.current)continue;
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
  }
  function Graph({data,activeId,selectedId}) {
    const ref=useRef();
    const [keepDrawing,setKeepDrawing]=useState(true);
    setGraphRedraw=setKeepDrawing;
    const labelLayout=useRef(null);
    if(!labelLayout.current)labelLayout.current=createLabelLayout();
    const sizeTools=useRef(),actionTools=useRef(),connectorTools=useRef(),connectionTools=useRef(),hoverTimer=useRef(),gesture=useRef();
    const [hoverId,setHoverId]=useState(null),[controlsFocused,setControlsFocused]=useState(false);
    const sizeAnchor=useRef(null);
    const board=window.HflIdeas?.maps.current;
    const sizeNode=board?data.nodes.find(n=>n.id===(hoverId||selectedId)):null;
    const actionNode=board?data.nodes.find(n=>n.id===selectedId):null;
    const edgeKey=link=>JSON.stringify([endpointId(link.source),endpointId(link.target),link.relation||'related-to']);
    const [chosenEdge,setChosenEdge]=useState(null),[connectFrom,setConnectFrom]=useState(null),[preview,setPreview]=useState(null),[connectionBusy,setConnectionBusy]=useState(false),[connectionMessage,setConnectionMessage]=useState('');
    const connection=board?data.links.find(e=>(e.local?'local:':'shared:')+edgeKey(e)===chosenEdge):null;
    const connectorNode=board?data.nodes.find(n=>n.id===(connectFrom||hoverId||selectedId)):null;
    const editable=connection&&(connection.local||connection.manual);
    const lineLevel=connection?(board.edge_widths?.[edgeKey(connection)]||2):2;
    const sizeLevel=sizeNode?(board.node_sizes?.[sizeNode.id]||3):3;
    useEffect(()=>{if(!sizeNode||connectFrom||connection)setControlsFocused(false);},[sizeNode,connectFrom,connection]);
    useEffect(()=>()=>clearTimeout(hoverTimer.current),[]);
    useEffect(()=>setHoverId(null),[board?.id]);
    useEffect(()=>{setChosenEdge(null);setConnectFrom(null);setPreview(null);setConnectionMessage('');},[board?.id]);
    useEffect(()=>{
      if(!['Saved','Connections refreshed.','Connection cancelled.'].includes(connectionMessage))return;
      const timer=setTimeout(()=>setConnectionMessage(''),4000);
      return ()=>clearTimeout(timer);
    },[connectionMessage]);
    useEffect(()=>{if(selectedId)setChosenEdge(null);},[selectedId]);
    useEffect(()=>{
      connectionInteraction=!!board&&!!(hoverId||controlsFocused||connectFrom||connection||connectionBusy);
      graphEscapePending=!!(controlsFocused||connectFrom||connection||connectionBusy);
      const cancel=event=>{if(event.key==='Escape'&&!document.querySelector('dialog[open]')){if(graphEscapePending)event.preventDefault();setControlsFocused(false);setConnectFrom(null);setPreview(null);setChosenEdge(null);setConnectionMessage('');}};
      document.addEventListener('keydown',cancel);
      return()=>{connectionInteraction=false;graphEscapePending=false;document.removeEventListener('keydown',cancel);};
    },[board,hoverId,controlsFocused,connectFrom,connection,connectionBusy]);
    const cleanEdge=edge=>({source:endpointId(edge.source),target:endpointId(edge.target),relation:edge.relation||'related-to',direction:edge.direction||'forward'});
    async function connectionCommand(operation,replacement,extra={}){
      if(connectionBusy)return;
      setConnectionBusy(true);setConnectionMessage('Saving…');
      try{
        const edge=operation==='create'?replacement:cleanEdge(connection);
        await window.HflIdeas.maps.connectionCommand({operation,scope:operation==='create'||connection.local?'local':'shared',edge,replacement:replacement||edge,revision:connection?.revision,...extra});
        if(operation==='remove')setChosenEdge(null);
        else setChosenEdge((operation==='create'||connection.local?'local:':'shared:')+edgeKey(replacement||edge));
        setConnectFrom(null);setPreview(null);setConnectionMessage('Saved');
      }catch(error){setConnectionMessage(error.message+' Refresh connections before retrying if the board changed.');}
      finally{setConnectionBusy(false);}
    }
    function finishConnection(target){
      if(!connectFrom||connectionBusy)return;
      if(target.id===connectFrom){setConnectionMessage('Choose a different orb.');return;}
      connectionCommand('create',{source:connectFrom,target:target.id,relation:'related-to',direction:'forward'});
    }
    function startConnector(event,node){
      event.preventDefault();event.stopPropagation();
      if(connectionBusy)return;
      clearTimeout(hoverTimer.current);setConnectFrom(node.id);setChosenEdge(null);setConnectionMessage('Drag to another orb, or select it. Escape cancels.');
      gesture.current={x:event.clientX,y:event.clientY};event.currentTarget.setPointerCapture(event.pointerId);
    }
    function moveConnector(event){
      if(!gesture.current)return;
      const bounds=host.getBoundingClientRect();setPreview({x:event.clientX-bounds.left,y:event.clientY-bounds.top});
    }
    function endConnector(event){
      event.stopPropagation();
      const start=gesture.current;gesture.current=null;
      if(!start||Math.hypot(event.clientX-start.x,event.clientY-start.y)<6)return;
      const bounds=host.getBoundingClientRect(),x=event.clientX-bounds.left,y=event.clientY-bounds.top;
      const target=data.nodes.find(node=>{const p=ref.current.graph2ScreenCoords(node.x,node.y);return Math.hypot(p.x-x,p.y-y)<=node.radius+12;});
      if(target)finishConnection(target);else{setConnectFrom(null);setPreview(null);setConnectionMessage('Connection cancelled.');}
    }
    const curveOffsets=new Map(),parallelGroups=new Map();
    if(board){
      for(const link of data.links){
        const key=JSON.stringify([endpointId(link.source),endpointId(link.target)].sort());
        if(!parallelGroups.has(key))parallelGroups.set(key,[]);
        parallelGroups.get(key).push(link);
      }
      for(const group of parallelGroups.values())group.sort((a,b)=>edgeKey(a).localeCompare(edgeKey(b))||Number(!!a.local)-Number(!!b.local)).forEach((link,index)=>curveOffsets.set(link,index-(group.length-1)/2));
    }
    function paintArrows(link,ctx){
      if(!board&&link.direction!=='both')return;
      const mode=link.direction||'forward';if(mode==='none')return;
      const a=link.source,b=link.target,zoom=ref.current?.zoom()||1;
      if(!Number.isFinite(a.x)||!Number.isFinite(b.x))return;
      const angle=Math.atan2(b.y-a.y,b.x-a.x),length=Math.hypot(b.x-a.x,b.y-a.y);
      if(length<(a.radius+b.radius+20)/zoom)return;
      ctx.save();ctx.fillStyle=color(board?a.kind:b.kind);ctx.globalAlpha=.85*arrivalAlpha(edgeArrivals.get(arrivalKey(link)));
      for(const reverse of !board?[true]:mode==='both'?[false,true]:[false]){
        const distance=(reverse?a.radius:b.radius)+9,t=reverse?distance/(zoom*length):1-distance/(zoom*length);
        const cp=link.__controlPoints;
        const x=cp?.length===2?(1-t)**2*a.x+2*(1-t)*t*cp[0]+t*t*b.x:a.x+(b.x-a.x)*t;
        const y=cp?.length===2?(1-t)**2*a.y+2*(1-t)*t*cp[1]+t*t*b.y:a.y+(b.y-a.y)*t;
        const tangent=cp?.length===2?Math.atan2((1-t)*(cp[1]-a.y)+t*(b.y-cp[1]),(1-t)*(cp[0]-a.x)+t*(b.x-cp[0])):angle;
        ctx.save();ctx.translate(x,y);ctx.rotate(tangent+(reverse?Math.PI:0));ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(-6/zoom,-3/zoom);ctx.lineTo(-6/zoom,3/zoom);ctx.closePath();ctx.fill();ctx.restore();
      }
      ctx.restore();
    }
    function menuKeys(event){
      if(event.key==='Escape'){
        event.preventDefault();event.stopPropagation();select(null);host.focus();
      }else if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
        event.preventDefault();event.stopPropagation();
        const items=[...actionTools.current.querySelectorAll('[role=menuitem]')],index=items.indexOf(document.activeElement);
        const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowUp'?-1:1)+items.length)%items.length;
        items[next]?.focus();
      }
    }
    function resizeOrb(delta){
      if(!sizeNode)return;
      const level=Math.max(1,Math.min(20,sizeLevel+delta));
      sizeNode.radius=8+level*3;
      window.HflIdeas.maps.persist({node_sizes:{...board.node_sizes,[sizeNode.id]:level}});
      draw();
    }
    const [size,setSize]=useState({width:host.clientWidth,height:host.clientHeight});
    useEffect(()=>{
      if(!fullscreenFitPending||!graphApi)return;
      // Fit the current node positions after the resized canvas has committed.
      const frame=requestAnimationFrame(()=>{fullscreenFitPending=false;fitTargets(true,true);});
      return()=>cancelAnimationFrame(frame);
    },[size]);
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
    const labelNodes=useMemo(()=>new Map(data.nodes.map(node=>[node.id,node])),[data]);
    const near=connected(activeId);
    const isLinked=link=>activeId&&(endpointId(link.source)===activeId||endpointId(link.target)===activeId);
    function paintNode(node,ctx,globalScale){
      if(!Number.isFinite(node.x)||!Number.isFinite(node.y)||!Number.isFinite(globalScale)||globalScale<=0)return;
      const visible=!activeId||node.id===activeId||near.has(node.id);
      const radius=node.radius/globalScale;
      const ink=color(node.kind),emphasis=node.id===activeId||node.id===selectedId||window.HflIdeas?.maps.selection.has(node.id);
      ctx.save();ctx.globalAlpha=(visible?(node.status==='dismissed'?.35:node.outside_workspace?.55:1):.075)*arrivalAlpha(nodeArrivals.get(node.id));
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
    return <><ForceGraph2D ref={ref} width={size.width} height={size.height} autoPauseRedraw={!keepDrawing}
      graphData={data} enableNodeDrag={!readOnly&&!connectFrom&&!connectionBusy&&(!!board||!touchViewport)} enablePanInteraction={!connectFrom&&!connectionBusy} enableZoomInteraction={!connectFrom&&!connectionBusy} backgroundColor="rgba(0,0,0,0)" nodeLabel={()=>''}
      onRenderFramePost={(ctx,scale)=>{
        if(!ref.current||!Number.isFinite(scale)||scale<=0)return;
        const origin=ref.current.screen2GraphCoords(0,0);
        if(sizeNode&&sizeTools.current){
          const point=ref.current.graph2ScreenCoords(sizeNode.x,sizeNode.y);
          if(sizeAnchor.current?.id!==sizeNode.id)sizeAnchor.current={id:sizeNode.id,radius:sizeNode.radius};
          const anchorRadius=sizeAnchor.current.radius;
          const toolsWidth=sizeTools.current.offsetWidth,toolsHeight=sizeTools.current.offsetHeight;
          sizeTools.current.style.left=Math.max(4,Math.min(size.width-toolsWidth-4,point.x-anchorRadius-toolsWidth-24))+'px';
          const toolsTop=point.x-anchorRadius-toolsWidth-24<4?point.y-anchorRadius-toolsHeight-24:point.y-toolsHeight/2;
          sizeTools.current.style.top=Math.max(4,Math.min(size.height-toolsHeight-4,toolsTop))+'px';
        }else sizeAnchor.current=null;
        if(actionNode&&actionTools.current){
          const point=ref.current.graph2ScreenCoords(actionNode.x,actionNode.y),panel=actionTools.current;
          const right=point.x+actionNode.radius+28,left=point.x-actionNode.radius-58-panel.offsetWidth;
          panel.style.left=Math.max(4,Math.min(size.width-panel.offsetWidth-4,right+panel.offsetWidth<=size.width-4?right:left>=4?left:right))+'px';
          panel.style.top=Math.max(4,Math.min(size.height-panel.offsetHeight-4,point.y-30))+'px';
        }
        if(connectorNode&&connectorTools.current){
          const p=ref.current.graph2ScreenCoords(connectorNode.x,connectorNode.y);
          connectorTools.current.style.left=p.x+'px';connectorTools.current.style.top=p.y+'px';
        }
        if(connection&&connectionTools.current){
          const a=ref.current.graph2ScreenCoords(connection.source.x,connection.source.y),b=ref.current.graph2ScreenCoords(connection.target.x,connection.target.y),panel=connectionTools.current;
          panel.style.left=Math.max(4,Math.min(size.width-panel.offsetWidth-4,(a.x+b.x)/2+12))+'px';
          panel.style.top=Math.max(4,Math.min(size.height-panel.offsetHeight-4,(a.y+b.y)/2))+'px';
        }
        if(connectFrom&&preview&&connectorNode){
          const target=ref.current.screen2GraphCoords(preview.x,preview.y);
          ctx.save();ctx.strokeStyle=color(connectorNode.kind);ctx.lineWidth=1.5/scale;ctx.setLineDash([4/scale,4/scale]);ctx.beginPath();ctx.moveTo(connectorNode.x,connectorNode.y);ctx.lineTo(target.x,target.y);ctx.stroke();ctx.restore();
        }
        const projectLabel=n=>({
          id:n.id,label:n.label,kind:n.kind,x:(n.x-origin.x)*scale,y:(n.y-origin.y)*scale,
          radius:n.radius,degree:n.visibleDegree,preferred:n.kind===(preset==='timeline'?'daily':preset)||defaultLabelKinds.has(n.kind),
          pinned:!!n.manual,emphasis:n.id===activeId||n.id===selectedId
        });
        const candidates=()=>data.nodes.filter(n=>board||!activeId||n.id===activeId||n.id===selectedId||near.has(n.id)).map(projectLabel);
        ctx.save();
        const obstacles=[sizeTools,actionTools,connectionTools].map(tool=>tool.current).filter(Boolean).map(el=>({x:el.offsetLeft,y:el.offsetTop,w:el.offsetWidth,h:el.offsetHeight}));
        const labelKey=JSON.stringify([labelRevision,size.width,size.height,activeId,selectedId,board?.id,!!sizeNode,!!actionNode,!!connection]);
        const labels=labelLayout.current(candidates,{width:size.width,height:size.height,zoom:scale,fullTitles:!!board,obstacles,cameraKey:`${scale}:${origin.x}:${origin.y}`},(text,font)=>{
          ctx.font=`500 ${font}px ${uiFont}`;return ctx.measureText(text).width;
        },performance.now(),labelKey,reducedMotion,id=>{
          const node=labelNodes.get(id);return node?projectLabel(node):null;
        });
        labelRefreshAt=labels.nextUpdate;labelFadeUntil=labels.fadeUntil;
        for(const box of labels){
          ctx.globalAlpha=box.alpha;
          const x=origin.x+box.x/scale,y=origin.y+box.y/scale,ink=color(box.node.kind);
          ctx.fillStyle=box.node.emphasis?'#142a42f5':'#0a1728ee';ctx.beginPath();
          ctx.roundRect(x,y,box.w/scale,box.h/scale,5/scale);ctx.fill();
          ctx.strokeStyle=ink+(box.node.emphasis?'90':'30');ctx.lineWidth=.6/scale;ctx.stroke();
          ctx.font=`500 ${box.font/scale}px ${uiFont}`;ctx.textAlign='left';ctx.textBaseline='middle';
          ctx.fillStyle=box.node.emphasis?'#ffffff':'#d9e9fa';box.lines.forEach((line,index)=>ctx.fillText(line,x+6/scale,y+(12+index*16)/scale));
        }
        ctx.restore();
      }}
      nodeCanvasObject={paintNode}
      nodePointerAreaPaint={(node,paint,ctx)=>{ctx.fillStyle=paint;ctx.beginPath();ctx.arc(node.x,node.y,(node.radius+4)/(ref.current?.zoom()||1),0,2*Math.PI);ctx.fill();}}
      linkColor={link=>color(board?link.source.kind:link.target.kind)+Math.round(parseInt(connection===link?'ff':activeId?(isLinked(link)?'df':'07'):(data.nodes.length<=35?'70':'32'),16)*arrivalAlpha(edgeArrivals.get(arrivalKey(link)))).toString(16).padStart(2,'0')}
      linkDirectionalArrowLength={link=>board||link.direction==='none'?0:link.manual?4:['ideas','actions','goals','drafts','boards','lists','thoughts'].includes(link.source.kind)||['ideas','actions','goals','drafts','boards','lists','thoughts'].includes(link.target.kind)?4:0}
      linkDirectionalArrowRelPos={0.8}
      linkWidth={link=>board?([.7,1,1.4,1.9,2.5][(board.edge_widths?.[edgeKey(link)]||2)-1]+(connection===link?.4:0)):isLinked(link)?2:data.nodes.length<=35?1.1:.65} linkCurvature={link=>board?boardCurvature(link,ref.current?.zoom()||1,curveOffsets.get(link)||0):.16}
      linkCanvasObjectMode={()=>'after'} linkCanvasObject={paintArrows} linkHoverPrecision={8}
      onLinkClick={link=>{if(readOnly)return;if(!board||connectFrom||connectionBusy)return;select(null);setChosenEdge((link.local?'local:':'shared:')+edgeKey(link));setConnectionMessage('');}}
      linkLineDash={link=>link.local?[4,3]:null}
      linkDirectionalParticles={0}
      linkDirectionalParticleWidth={2} linkDirectionalParticleSpeed={.004}
      onZoom={()=>{if(activePointers.size)lastInteraction=Date.now();scheduleStateSave();}}
      onNodeHover={node=>{host.style.cursor=node?'pointer':'grab';clearTimeout(hoverTimer.current);if(node)setHoverId(node.id);else hoverTimer.current=setTimeout(()=>setHoverId(null),250);if(!touchViewport)highlight(node?.id||selected);}}
      onNodeClick={(node,event)=>{if(readOnly)return;if(board)window.HflIdeas.maps.selectNode(node.id,event.shiftKey||event.ctrlKey||event.metaKey);if(connectFrom)finishConnection(node);else{setChosenEdge(null);setConnectionMessage('');select(node.id);}}} onBackgroundClick={()=>{if(!connectionBusy){window.HflIdeas?.maps.selectNode(null);select(null);setChosenEdge(null);setConnectFrom(null);setPreview(null);setConnectionMessage('');}}}
      onNodeDrag={followDrag}
      onNodeDragEnd={node=>{draggedNode=null;node.manual=true;layoutTargets.set(node.id,{x:node.x,y:node.y,anchor:false});node.fx=node.x;node.fy=node.y;draw();if(window.HflIdeas?.maps.current)window.HflIdeas.maps.saveLayout();else graphApi.d3ReheatSimulation();}}
      warmupTicks={0} cooldownTicks={reducedMotion||(!draggedNode&&!dragNodes.size)?0:Infinity}
      d3VelocityDecay={dragNodes.size?.2:.4}
      d3AlphaMin={.001}
      onEngineStop={finishDrag}

    />{sizeNode&&!connectFrom&&!connection&&<div ref={sizeTools} className="kg-orb-size" role="group" aria-label={'Orb controls for '+sizeNode.label}
      onFocus={()=>setControlsFocused(true)} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))setControlsFocused(false);}}
      onPointerEnter={()=>clearTimeout(hoverTimer.current)} onPointerLeave={()=>{hoverTimer.current=setTimeout(()=>setHoverId(null),250);}}
      onPointerDown={event=>event.stopPropagation()} onClick={event=>event.stopPropagation()}>
      <button type="button" aria-label="Increase orb size" title="Increase orb size" disabled={sizeLevel===20} onClick={()=>resizeOrb(1)}><svg aria-hidden="true" viewBox="0 0 20 20"><path d="M10 4v12M4 10h12"/></svg></button>
      <button type="button" aria-label="Decrease orb size" title="Decrease orb size" disabled={sizeLevel===1} onClick={()=>resizeOrb(-1)}><svg aria-hidden="true" viewBox="0 0 20 20"><path d="M4 10h12"/></svg></button>
    </div>}
      {connectorNode&&!connection&&<div ref={connectorTools} className="kg-connectors" role="group" aria-label={'Connect from '+connectorNode.label} onPointerEnter={()=>clearTimeout(hoverTimer.current)} onPointerLeave={()=>{if(!connectFrom)hoverTimer.current=setTimeout(()=>setHoverId(null),250);}}>
        {['North','East','South','West'].map((side,index)=><button key={side} type="button" className="kg-connector" aria-label={side+' connector for '+connectorNode.label} title="Connect to another orb" disabled={connectionBusy} style={{left:Math.sin(index*Math.PI/2)*(connectorNode.radius+9),top:-Math.cos(index*Math.PI/2)*(connectorNode.radius+9),'--connector-color':color(connectorNode.kind)}}
          onPointerDown={event=>startConnector(event,connectorNode)} onPointerMove={moveConnector} onPointerUp={endConnector} onPointerCancel={()=>{gesture.current=null;setConnectFrom(null);setPreview(null);}} onClick={event=>{event.stopPropagation();if(event.detail===0){setConnectFrom(connectorNode.id);setConnectionMessage('Select another orb to connect. Escape cancels.');}}}/>)}
      </div>}
      {connection&&<div ref={connectionTools} className="kg-orb-actions-menu kg-connection-menu" role="region" aria-label="Connection actions" style={{maxHeight:size.height-12}} onPointerDown={event=>event.stopPropagation()} onClick={event=>event.stopPropagation()}>
        <strong>{connection.local?'Board-only connection':connection.manual?'Shared connection':'Derived connection'}</strong>
        <p>{connection.source.label} {connection.direction==='both'?'↔':connection.direction==='none'?'—':'→'} {connection.target.label}</p>
        {!editable?<p>Automatically derived · read-only</p>:<>
          {connection.manual&&<p>Relationship changes apply everywhere this connection appears.</p>}
          <label>Relationship<select aria-label="Connection relationship" disabled={connectionBusy} value={connection.relation||'related-to'} onChange={event=>connectionCommand('update',{...cleanEdge(connection),relation:event.target.value})}>
            {[...new Set(['related-to','supports','alternative','depends-on',connection.relation].filter(Boolean))].map(value=><option key={value} value={value}>{value.replaceAll('-',' ')}</option>)}
          </select></label>
          <label>Arrows<select aria-label="Connection arrows" disabled={connectionBusy} value={connection.direction||'forward'} onChange={event=>connectionCommand('update',{...cleanEdge(connection),direction:event.target.value})}>
            <option value="forward">one-way</option><option value="both">bidirectional</option><option value="none">no arrow</option>
          </select></label>
          <button type="button" disabled={connectionBusy} onClick={()=>connectionCommand('update',{...cleanEdge(connection),source:connection.target.id,target:connection.source.id})}>Reverse direction</button>
          <div className="kg-line-size" role="group" aria-label="Line thickness on this board"><span>Line thickness</span><button type="button" aria-label="Decrease line thickness" disabled={connectionBusy||lineLevel===1} onClick={()=>connectionCommand('width',null,{width:lineLevel-1})}><svg aria-hidden="true" viewBox="0 0 20 20"><path d="M4 10h12"/></svg></button><button type="button" aria-label="Increase line thickness" disabled={connectionBusy||lineLevel===5} onClick={()=>connectionCommand('width',null,{width:lineLevel+1})}><svg aria-hidden="true" viewBox="0 0 20 20"><path d="M10 4v12M4 10h12"/></svg></button></div>
          <button type="button" className="kg-orb-remove" disabled={connectionBusy} onClick={()=>connectionCommand('remove')}>Remove connection</button>
          {connection.local&&![connection.source.id,connection.target.id].some(id=>id.startsWith('draft:'))&&<button type="button" disabled={connectionBusy} onClick={async()=>{setConnectionBusy(true);try{await window.HflIdeas.maps.promoteConnection(cleanEdge(connection));setChosenEdge(null);setConnectionMessage('Shared connection saved');}catch(error){setConnectionMessage(error.message);}finally{setConnectionBusy(false);}}}>Share with Activity Graph</button>}
        </>}
        <button type="button" disabled={connectionBusy} onClick={()=>{setChosenEdge(null);setConnectionMessage('');}}>Close</button>
      </div>}
      {board&&connectionMessage&&<div className="kg-connection-feedback" role="status">{connectionMessage}{!connectionBusy&&connectionMessage!=='Saved'&&!connectFrom&&<button type="button" onClick={async()=>{try{await window.HflIdeas.maps.refreshConnections();setChosenEdge(null);setConnectionMessage('Connections refreshed.');}catch(error){setConnectionMessage(error.message);}}}>Refresh connections</button>}</div>}
      {actionNode&&!connectFrom&&!connection&&nodeActions.length>0&&<div ref={actionTools} id="kg-orb-actions-menu" className="kg-orb-actions-menu" role="menu" aria-label="Orb actions" style={{maxHeight:Math.max(100,Math.min(440,size.height-8))}}
        onPointerDown={event=>event.stopPropagation()} onClick={event=>event.stopPropagation()} onKeyDown={menuKeys}>
        {['Edit & develop','Add & connect','Board','View'].map(group=>{
          const actions=nodeActions.filter(action=>action.group===group);
          return actions.length>0&&<div role="group" aria-label={group} key={group}><span className="kg-orb-menu-heading" aria-hidden="true">{group}</span>{actions.map(action=><button type="button" role="menuitem" key={action.label} className={action.label==='Remove from board'?'kg-orb-remove':''} onClick={()=>action.button.click()}>{action.label}</button>)}</div>;
        })}
      </div>}
    </>;
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
      dot.className='kg-dot';dot.style.background=color(n.kind);name.textContent=n.label;meta.textContent=n.outside_workspace?'Outside Space filters':n.visibleDegree+' links';button.title=n.label+' · '+kindLabel(n.kind);
      if(selected){const link=edges.find(e=>(e.source===selected&&e.target===n.id)||(e.target===selected&&e.source===n.id));if(link){const evidence=document.createElement('small');evidence.textContent=(link.relation||'linked')+' · '+(link.evidence||'');evidence.style.cssText='grid-column:2 / 4;white-space:normal;font-size:11px';button.append(evidence);button.title=link.evidence||n.label;}}
      button.prepend(dot,name,meta);button.onclick=event=>{window.HflIdeas?.maps.selectNode(n.id,event.shiftKey||event.ctrlKey||event.metaKey);select(n.id);};$('list').append(button);
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
        action.className='corpus-followup-action';action.href=item.action_url;action.textContent='Create action ↗';
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
    if(readOnly){selected=null;draw();return;}
    nodeActions=[];
    selected=id;updateFullscreen();const n=nodes.find(n=>n.id===id),near=connected(id);
    highlight(id);
    $('detail').replaceChildren();$('detail').classList.toggle('kg-detail-empty',!n);
    const heading=document.createElement('h2'),description=document.createElement('p');
    const eyebrow=document.createElement('span');eyebrow.className='kg-eyebrow';eyebrow.textContent=n?kindLabel(n.kind):window.HflIdeas?.maps.current?'Your next big idea starts here':'Your knowledge, connected';$('detail').append(eyebrow);
    heading.textContent=n?n.label:'';
    description.textContent=n?[kindLabel(n.kind),n.date,n.source,near.size+' visible connections'].filter(Boolean).join(' · '):window.HflIdeas?.maps.current?'Select an orb to build on a thought, connect ideas, or take the next step.':'Select an orb to explore its linked entries and entities.';
    if(n)$('detail').append(heading);$('detail').append(description);
    if(n?.outside_workspace){const note=document.createElement('p');note.className='kg-outside-workspace';note.textContent='Outside Space filters · Included as a member of this board.';$('detail').append(note);}
    if(n?.href&&n.kind==='entries') {const button=document.createElement('button');button.textContent='Open entry';button.className='kg-open-entry';button.onclick=()=>openEntry(n.id.replace(/^entry:/,''),n.locator);$('detail').append(button);}
    if(!exampleMode)window.HflIdeas?.inspect(n,$('detail'),data.edges);
    if(n){const focus=document.createElement('button');focus.textContent='Focus on this connection';focus.className='kg-focus-button';focus.onclick=()=>{focusId=n.id;render();};$('detail').append(focus);}
    if(focusId){const back=document.createElement('button');back.textContent='Back to overview';back.onclick=()=>{focusId=null;render();};$('detail').append(back);}
    if(n){const clear=document.createElement('button');clear.textContent='Clear selection';clear.onclick=()=>select(null);$('detail').append(clear);}
    if(n&&window.HflIdeas?.maps.current){
      // Reuse the inspector's commands so board permissions and workflows stay identical.
      nodeActions=[...$('detail').querySelectorAll(':scope > button')].map(button=>{
        const label=button.textContent;
        const group=/^(Edit|Promote|Dismiss|Restore)/.test(label)?'Edit & develop':/^(Create|Add|Connect)/.test(label)?'Add & connect':/^(Clone|Remove|Use as|Board connections)/.test(label)?'Board':'View';
        button.remove();return {label,group,button};
      });
      nodeActions.sort((a,b)=>Number(a.label==='Remove from board')-Number(b.label==='Remove from board'));
      draw();
    }
    const items=n?nodes.filter(node=>near.has(node.id)):preset==='mindmap'?nodes:nodes.filter(node=>node.kind===(preset==='timeline'?'daily':preset));
    $('list-title').textContent=(n?'Linked nodes':preset==='mindmap'?'Board members':PRESETS[preset])+' · '+items.length;
    nodeList(items);
  }
  function render(preserveLayout=false) {
    draggedNode=null;dragNodes.clear();
    const board=window.HflIdeas?.maps.current;
    const sameBoard=!!board&&renderedBoardId===board.id;
    if(!sameBoard)boardLayoutPositions={};
    renderedBoardId=board?.id||null;
    // Search and filters change visibility, never the board's geometry or camera.
    if(sameBoard)preserveLayout=true;
    if(!preserveLayout)labelRevision++;
    const boardPositions=board?{...boardLayoutPositions,...board.positions,...window.HflIdeas.maps.pendingPositions}:null;
    const previousNodes=new Map(graphData.nodes.map(node=>[node.id,node]));
    const previousTargets=layoutTargets;
    $('legend').querySelectorAll('button[data-kind]').forEach(button=>button.setAttribute('aria-pressed',String(enabled.has(button.dataset.kind))));
    $('types').querySelectorAll('input[data-kind]').forEach(input=>{input.checked=enabled.has(input.dataset.kind);});
    const degrees=new Map();data.edges.forEach(e=>{degrees.set(e.source,(degrees.get(e.source)||0)+1);degrees.set(e.target,(degrees.get(e.target)||0)+1);});
    let filtered=data.nodes.filter(n=>enabled.has(n.kind)&&(!exampleMode||!$('shared').checked||n.kind==='entries'||degrees.get(n.id)>1));
    const query=exampleMode||window.HflIdeas?.maps.current?$('search').value.trim().toLocaleLowerCase():'';
    if(query){const matches=new Set(filtered.filter(n=>n.label.toLocaleLowerCase().includes(query)).map(n=>n.id)),near=new Set(matches);data.edges.forEach(e=>{if(matches.has(e.source))near.add(e.target);if(matches.has(e.target))near.add(e.source);});filtered=filtered.filter(n=>near.has(n.id));}
    if(focusId){const keep=new Set([focusId]);data.edges.forEach(e=>{if(e.source===focusId)keep.add(e.target);if(e.target===focusId)keep.add(e.source);});filtered=filtered.filter(n=>keep.has(n.id));}
    const chosen=filtered.slice().sort((a,b)=>(degrees.get(b.id)||0)-(degrees.get(a.id)||0));
    nodes=chosen.map((n,index)=>({...n,index,degree:degrees.get(n.id)||0}));
    const byId=new Map(nodes.map(n=>[n.id,n]));
    edges=data.edges.filter(e=>byId.has(e.source)&&byId.has(e.target)).map(e=>({...e,a:byId.get(e.source),b:byId.get(e.target)}));
    nodes.forEach(n=>n.visibleDegree=0);edges.forEach(e=>{e.a.visibleDegree++;e.b.visibleDegree++;});
    nodes.forEach(n=>{const board=window.HflIdeas?.maps.current,smallGraph=nodes.length<=35;n.radius=board?8+3*(board.node_sizes?.[n.id]||3):n.kind==='entries'?(smallGraph?7:4.5):(smallGraph?10:4)+4*Math.log2(1+n.visibleDegree);});
    const anchors=nodes.filter(n=>n.kind!=='entries').sort((a,b)=>b.visibleDegree-a.visibleDegree).slice(0,4);
    const adjacency=new Map(nodes.map(n=>[n.id,new Set()]));
    for(const e of edges){adjacency.get(e.source).add(e.target);adjacency.get(e.target).add(e.source);}
    for(const n of nodes){
      const index=anchors.findIndex(a=>a.id===n.id||adjacency.get(n.id).has(a.id));
      n.clusterX=index<0?0:Math.cos(index*Math.PI/2)*220;
      n.clusterY=index<0?0:Math.sin(index*Math.PI/2)*160;
    }
    if(!preserveLayout){if(!pendingState)layoutSeed=Math.random();randomizePresetNodes(nodes,layoutSeed);}
    const layout=presetLayout(nodes,edges,window.HflIdeas?.maps.current?'mindmap':preset,layoutSeed,window.HflIdeas?.maps.current?.root);preset=layout.preset;layoutTargets=layout.positions;
    if(window.HflIdeas?.maps.current&&boardPositions&&Object.keys(boardPositions).length){
      const occupied=new Map(),cell=p=>[Math.floor(p.x/85),Math.floor(p.y/85)];
      const occupy=p=>{const key=cell(p).join(',');if(!occupied.has(key))occupied.set(key,[]);occupied.get(key).push({...p});};
      const overlaps=p=>{const [x,y]=cell(p);for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)if((occupied.get([x+dx,y+dy].join(','))||[]).some(q=>Math.hypot(p.x-q.x,p.y-q.y)<85))return true;return false;};
      Object.values(boardPositions).forEach(occupy);
      for(const node of nodes){
        if(boardPositions[node.id])continue;
        const target=layoutTargets.get(node.id);
        // Growing a board must not move its camera or place the new object
        // beyond the visible canvas. Find a free slot near the selected node.
        if(graphApi){
          const a=graphApi.screen2GraphCoords(45,45),b=graphApi.screen2GraphCoords(host.clientWidth-45,host.clientHeight-45);
          if(target.x<a.x||target.x>b.x||target.y<a.y||target.y>b.y||overlaps(target)){
            const origin=boardPositions[selected]||target,candidates=[],step=Math.max(100,(b.x-a.x)/30,(b.y-a.y)/30);
            for(let x=a.x;x<=b.x;x+=step)for(let y=a.y;y<=b.y;y+=step)candidates.push({x,y});
            candidates.sort((p,q)=>Math.hypot(p.x-origin.x,p.y-origin.y)-Math.hypot(q.x-origin.x,q.y-origin.y));
            const free=candidates.find(p=>!overlaps(p));if(free)Object.assign(target,free);
          }
        }
        while(overlaps(target))target.y+=110;
        occupy(target);
      }
    }
    nodes.forEach(node=>{
      const previous=previousNodes.get(node.id),target=layoutTargets.get(node.id);
      if(preserveLayout&&previous){Object.assign(node,{x:previous.x,y:previous.y,manual:previous.manual});layoutTargets.set(node.id,previousTargets.get(node.id)||{x:node.x,y:node.y});}
      else {node.x=target.x;node.y=target.y;}
      const saved=boardPositions?.[node.id]||(!board&&pendingState?.positions?.[node.id]);
      if(saved){node.x=saved.x;node.y=saved.y;node.manual=!!saved.manual;layoutTargets.set(node.id,{...target,x:saved.x,y:saved.y});}
      node.fx=node.x;node.fy=node.y;node.phase=phaseFor(node.id);
      if(board)boardLayoutPositions[node.id]={x:node.x,y:node.y};
    });
    transition=null;if(!preserveLayout)motionTime=0;
    // Timeline opens on the latest week, even if an earlier session was panned
    // away from the date row. Keep saved filters and node positions intact.
    const restoredViewport=preset!=='timeline'&&nodes.some(n=>pendingState?.positions?.[n.id])?pendingState?.viewport:null;
    pendingState=null;
    if(window.HflIdeas)window.HflIdeas.maps.pendingPositions=null;
    // Supply endpoints from this render directly. Static board updates use zero
    // simulation ticks, so links must not wait for d3 to resolve string IDs.
    const oldEdges=new Set(graphData.links.map(arrivalKey)),now=performance.now();
    if(!preserveLayout){nodeArrivals.clear();edgeArrivals.clear();}
    for(const node of nodes)if(preserveLayout&&!previousNodes.has(node.id))nodeArrivals.set(node.id,now);
    for(const edge of edges)if(preserveLayout&&!oldEdges.has(arrivalKey(edge)))edgeArrivals.set(arrivalKey(edge),now);
    if(!reducedMotion&&(nodeArrivals.size||edgeArrivals.size))arrivalFadeUntil=now+400;
    for(const [id,time] of nodeArrivals)if(!byId.has(id)||now-time>=400)nodeArrivals.delete(id);
    const edgeIds=new Set(edges.map(arrivalKey));
    for(const [id,time] of edgeArrivals)if(!edgeIds.has(id)||now-time>=400)edgeArrivals.delete(id);
    graphData={nodes,viewport:restoredViewport,fitOnce:!preserveLayout,links:edges.map(e=>({...e,source:byId.get(e.source),target:byId.get(e.target),local:!!e.local}))};
    updatePresetMenu(layout.notice);
    $('map-count').textContent=nodes.length+' nodes · '+edges.length+' links';
    showInfo('status',nodes.length+' / '+(data.total_nodes ?? data.nodes.length)+' matching nodes · '+(data.nodes.length-nodes.length)+' hidden by view filters · '+edges.length+' connections'+(!nodes.length?' · No matching nodes. Clear your search or change the filters.':''),!nodes.length);
    select(byId.has(selected)?selected:null);
  }
  function configureData(next,preserveLayout=false) {
    for(const node of next.nodes)if(node.kind!=='drafts')window.HflIdeas?.maps.cacheNode(node);
    for(const edge of next.edges)if(!edge.local)window.HflIdeas?.maps.sharedEdges.set(JSON.stringify([edge.source,edge.target,edge.relation]),edge);
    const map=window.HflIdeas?.maps.current;
    if(map){const members=new Set(map.members);next.nodes.filter(n=>members.has(n.list_id)).forEach(n=>members.add(n.id));const drafts=(map.drafts||[]).map(d=>({id:d.id,label:d.title,body:d.body,kind:'drafts',status:'board draft'}));next={...next,nodes:[...next.nodes.filter(n=>members.has(n.id)),...drafts],edges:[...next.edges.filter(e=>members.has(e.source)&&members.has(e.target)),...(map.edges||[]).map(e=>({...e,local:true,method:'board',evidence:'Board-only connection'}))]};next.total_nodes=next.nodes.length;next.truncated=false;}
    data=next;
    const requestedSelection=new URL(location.href).searchParams.get('select');
    if(!readOnly&&requestedSelection&&next.nodes.some(n=>n.id===requestedSelection)){
      selected=requestedSelection;focusId=null;$('search').value='';enabled.add(next.nodes.find(n=>n.id===selected).kind);
      const url=new URL(location.href);url.searchParams.delete('select');history.replaceState(null,'',url);
    }
    if(window.HflIdeas)window.HflIdeas.maps.nodeLabels=Object.fromEntries(next.nodes.map(n=>[n.id,n.label]));
    if(focusId&&!data.nodes.some(node=>node.id===focusId))focusId=null;
    if(selected&&!data.nodes.some(node=>node.id===selected))selected=null;
    const availableKinds=new Set(data.nodes.map(node=>node.kind));$('types').replaceChildren();
    $('legend').replaceChildren();
    const legendLabels={sources:'sources',entries:'entries',daily:'dates',people:'people',companies:'organizations',tools:'tools',topics:'topics'};
    const legendKinds=[...Object.keys(legendLabels).filter(kind=>availableKinds.has(kind)),...[...availableKinds].filter(kind=>!legendLabels[kind]).sort()];
    legendKinds.forEach(kind=>{
      const item=document.createElement('li'),button=document.createElement('button'),dot=document.createElement('span');
      dot.className='kg-dot';dot.style.background=color(kind);dot.setAttribute('aria-hidden','true');
      button.type='button';button.dataset.kind=kind;button.title='Show or hide '+(legendLabels[kind]||kindLabel(kind).toLowerCase());
      button.onclick=()=>{enabled.has(kind)?enabled.delete(kind):enabled.add(kind);render();};
      button.append(dot,document.createTextNode(legendLabels[kind]||kindLabel(kind).toLowerCase()));item.append(button);$('legend').append(item);
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
  function clearCapacity(){
    capacityBlocked=false;
    $('capacity-overlay').hidden=true;$('capacity-preview-note').hidden=true;
    host.inert=false;document.querySelector('.kg-zoom').inert=false;
  }
  function acceptGraph(next,preserveLayout=false,background=false){
    const capacity=capacityEnabled&&!window.HflIdeas?.maps.current?next.capacity:null;
    sourceOptions(next.sources||[]);
    if(capacity?.exceeded&&!capacity.preview){
      capacityBlocked=true;
      // Remove the old graph from the renderer; an overlay alone would keep drawing it.
      configureData({nodes:[],edges:[],sources:next.sources||[],total_nodes:0});
      host.inert=true;document.querySelector('.kg-zoom').inert=true;
      $('capacity-preview-note').hidden=true;
      $('capacity-message').textContent=`${capacity.total_nodes.toLocaleString()} matching nodes and ${capacity.total_edges.toLocaleString()} connections exceed your limits of ${capacity.node_limit.toLocaleString()} nodes and ${capacity.edge_limit.toLocaleString()} connections.`;
      $('capacity-overlay').hidden=false;
      showInfo('status','Graph paused · Refine your search or show a limited preview.',true);
      if(!background)requestAnimationFrame(()=>{if(capacityBlocked)$('capacity-overlay').focus();});
      return;
    }
    clearCapacity();configureData(next,preserveLayout);
    if(capacity?.preview){
      $('capacity-preview-note').textContent=`Limited preview · ${next.nodes.length.toLocaleString()} of ${capacity.total_nodes.toLocaleString()} nodes · ${next.edges.length.toLocaleString()} of ${capacity.total_edges.toLocaleString()} connections. Some matches and connections are omitted.`;
      $('capacity-preview-note').hidden=false;
    }
  }
  $('capacity-search').onclick=()=>{if(fullscreen)setFullscreen(false);$('search').focus();};
  $('capacity-filters').onclick=()=>{if(fullscreen)setFullscreen(false);$('open-filters').click();};
  $('capacity-preview').onclick=()=>{capacityPreview=true;load(false,true);};
  $('capacity-reset').onclick=()=>{$('node-limit').value=recommendedCapacity.nodes;$('edge-limit').value=recommendedCapacity.edges;};
  function sourceOptions(values) {
    const params=new URLSearchParams(window.activityModals?.context()||'');
    const scope=JSON.parse(params.get('scope')||'{"any":[],"all":{}}');
    const split=value=>String(value||'').split(',').map(s=>s.trim()).filter(Boolean);
    const clauses=(scope.any||[]).map(state=>split(state.source));
    // Selected workspaces are OR-ed; additional shared filters narrow that union.
    let inherited=clauses.length&&clauses.every(sources=>sources.length)?[...new Set(clauses.flat())]:null;
    const additional=split(params.has('source')?params.get('source'):scope.all?.source);
    if(additional.length)inherited=inherited?inherited.filter(source=>additional.includes(source)):additional;
    const scoped=!!(params.get('workspace')||params.get('views')||inherited);
    const baseline=scoped?'Space sources':'All sources';
    $('source-inherited').textContent=scoped
      ? 'Inherited: '+(inherited===null?'all sources':inherited.length?inherited.join(', '):'no overlapping sources')+'. Selections below narrow this graph only.'
      : 'Selections narrow this graph only.';
    $('source-options').replaceChildren();
    const reset=document.createElement('button');reset.type='button';reset.dataset.sourceReset='';
    reset.textContent=scoped?'Reset to Space sources':'Reset to all sources';
    reset.onclick=()=>{selectedSources.clear();sourceOptions(values);};
    $('source-options').append(reset);
    for(const value of [...new Set([...(inherited||[]),...values,...selectedSources])].sort()) {
      const label=document.createElement('label'),input=document.createElement('input');
      input.type='checkbox';input.value=value;input.checked=selectedSources.has(value);
      input.onchange=()=>{input.checked?selectedSources.add(value):selectedSources.delete(value);sourceOptions(values);};
      label.append(input,document.createTextNode(value));$('source-options').append(label);
    }
    $('source-caption').textContent=selectedSources.size?selectedSources.size+' sources selected':baseline;
  }
  async function load(force=false,preview=false) {
    delete $('info').dataset.error;
    capacityPreview=preview;
    clearCapacity();syncCapacitySettings();
    backgroundController?.abort();

    requestController?.abort(); const version=++requestVersion;
    if(exampleMode){setLoading(false);configureData(exampleGraph());window.HflIdeas?.maps.finishDeletionTransition();return;}
    const board=window.HflIdeas?.maps.current;
    if(board){
      loading=true;$('reload').disabled=true;
      const progress=window.HflIdeas.maps.status;
      progress.textContent='Updating board and loading connected items…';progress.setAttribute('aria-busy','true');
      showInfo('status','Updating board and loading connected items…',true);
      appliedParams=null;
      try{
        let shared={nodes:board.members.map(id=>window.HflIdeas.maps.nodes.get(id)).filter(Boolean),edges:[...window.HflIdeas.maps.sharedEdges.values()],sources:[]};
        if(force===true||board.members.some(id=>id.startsWith('list:'))||shared.nodes.length!==board.members.length||(window.activityModals?.context()&&shared.nodes.some(n=>n.outside_workspace===undefined))){
          shared=await window.HflIdeas.api('/maps/'+board.id+'/graph?'+new URLSearchParams({context:window.activityModals?.context()||''}));
          if(version!==requestVersion||window.HflIdeas.maps.current?.id!==board.id)return;
          board.members.forEach(id=>window.HflIdeas.maps.nodes.delete(id));
          for(const [key,edge] of window.HflIdeas.maps.sharedEdges)if(board.members.includes(edge.source)&&board.members.includes(edge.target))window.HflIdeas.maps.sharedEdges.delete(key);
        }
        setLoading(false);configureData(shared,force===true);progress.textContent='Board ready · '+data.nodes.length+' nodes';
      }catch(error){setLoading(false);showInfo('status',error.message,true);progress.textContent=error.message;}
      finally{progress.removeAttribute('aria-busy');}
      return;
    }
    requestController=new AbortController(); setLoading(true);showInfo('status','Loading your graph…',true);
    try {
      const params=requestParams();
      const response=await fetch('/api/hfl/entities/graph?'+params,{cache:'no-store',signal:requestController.signal});
      if(!response.ok)throw Error(response.status===401?'Sign in to view your knowledge graph.':'Graph could not load. Use Refresh to try again.');
      const next=await response.json();
      if(!exampleMode&&version===requestVersion){appliedParams=params.toString();graphSignature=signature(next);acceptGraph(next);}
    } catch(error){if(!exampleMode&&version===requestVersion&&error.name!=='AbortError'){$('info').dataset.error='true';showInfo('status',error.message,true);}} finally{if(version===requestVersion){setLoading(false);window.HflIdeas?.maps.finishDeletionTransition(!!$('info').dataset.error);}}
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
  let liveBoardSignature='';
  async function refreshInBackground(){
    const liveBoard=window.HflIdeas?.maps.current;
    if(liveBoard){
      if(!liveBoard.members.some(id=>id.startsWith('list:'))||busy()||backgroundController||Date.now()<nextRefresh)return;
      const controller=new AbortController();backgroundController=controller;
      try{
        const next=await window.HflIdeas.api('/maps/'+liveBoard.id+'/graph');
        const key=liveBoard.id+JSON.stringify(next);
        if(window.HflIdeas.maps.current?.id===liveBoard.id&&!busy()&&key!==liveBoardSignature){configureData(next,true);liveBoardSignature=key;}
      }catch(error){$('live').textContent='List updates unavailable · '+error.message;}
      finally{backgroundController=null;nextRefresh=Date.now()+5000;}
      return;
    }
    if(capacityBlocked||busy()||backgroundController||!appliedParams||Date.now()<nextRefresh)return;
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
        acceptGraph(next,true,true);graphSignature=nextSignature;
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
  $('filter').onclick=()=>{
    if(capacityEnabled&&!window.HflIdeas?.maps.current){
      if(!$('node-limit').reportValidity()||!$('edge-limit').reportValidity())return;
      capacityLimits={nodes:Number($('node-limit').value),edges:Number($('edge-limit').value)};
      try{localStorage.setItem(capacityKey,JSON.stringify(capacityLimits));}catch{}
    }
    $('filter-drawer').close();if(!exampleMode)load();
  };
  window.HflHotkeys?.register(key=>{
    if(readOnly)return false;
    const hotkeys=window.HflHotkeys, maps=window.HflIdeas?.maps;
    const named=(root,pattern)=>[...(root?.querySelectorAll('button')||[])].find(button=>pattern.test(button.textContent.trim()));
    const orbKeys={t:/^Add thought$/,c:/^Connect on this board$/,n:/^Clone /,d:/^Dismiss /,r:/^Promote /,e:/^Edit /,u:/^Use as starting point$/,o:/^Board connections/};
    if(selected&&(orbKeys[key]||['x','f','arrowup','arrowdown'].includes(key))){
      if(['n','r','e'].includes(key)&&maps?.selection?.size>1)return true;
      if(key==='x'){maps?.selectNode(null);select(null);return true;}
      if(key==='f'){focusId=focusId?null:selected;render();return true;}
      if(key==='arrowup'||key==='arrowdown'){
        if(maps?.current){const node=nodes.find(n=>n.id===selected),board=maps.current,level=Math.max(1,Math.min(20,(board.node_sizes?.[selected]||3)+(key==='arrowup'?1:-1)));if(node){node.radius=8+level*3;maps.persist({node_sizes:{...board.node_sizes,[selected]:level}});draw();}}
        return true;
      }
      const pattern=orbKeys[key],button=nodeActions.find(action=>pattern.test(action.label))?.button||named($('detail'),pattern);
      if(key==='d')hotkeys.confirm(button,'Dismiss this object');else hotkeys.click(button);
      return true;
    }
    const selectors={a:'.board-explore',e:'#kg-entities',f:'#kg-open-filters',b:'.board-guide-trigger',r:'#kg-reload',p:'#kg-fit','[':'#kg-in',']':'#kg-out'};
    if(selectors[key]){hotkeys.click(document.querySelector(selectors[key]));return true;}
    if(key==='\\'){setFullscreen(!fullscreen);return true;}
    if(key===' '){if(maps?.current)hotkeys.click(named(document.querySelector('.board-controls'),/^Attach existing$/));else{choosePreset(lastChosenPreset);hotkeys.click($('reload'));}return true;}
    return false;
  });
  $('shared').onchange=()=>exampleMode?render():load();$('in').onclick=()=>zoom(1.3);$('out').onclick=()=>zoom(1/1.3);$('fit').onclick=()=>fitTargets(true,true);$('reload').onclick=async()=>{try{await window.HflIdeas?.maps.reload();await load(true);}catch(error){showInfo('status',error.message,true);}};
  $('reset').onclick=()=>{
    pendingState=null;try {localStorage.removeItem(stateKey);} catch {}
    window.activityModals?.reset();preset='timeline';setAnimation('off');
    $('search').value='';$('rolling').value='0';$('since').value='';$('until').value='';
    selectedSources.clear();sourceOptions(data.sources||[]);syncDates();$('shared').checked=false;
    enabled=new Set(['entries','sources','daily','people','companies','tools','topics','objects','ideas','actions','goals','drafts','boards','lists','thoughts']);selected=null;focusId=null;exampleMode?render():load();
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
  $('open-filters').onclick=()=>{syncCapacitySettings();setViewsOpen(false);$('filter-drawer').showModal();$('open-filters').setAttribute('aria-expanded','true');};
  $('close-filters').onclick=()=>$('filter-drawer').close();
  $('filter-drawer').addEventListener('close',()=>{$('open-filters').setAttribute('aria-expanded','false');$('source-menu').open=false;$('open-filters').focus();});
  $('filter-drawer').addEventListener('click',event=>{const box=$('filter-drawer').getBoundingClientRect();if(event.target===$('filter-drawer')&&(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom))$('filter-drawer').close();});
  document.addEventListener('click',e=>{if(!$('source-menu').contains(e.target))$('source-menu').open=false;});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')$('source-menu').open=false;});
  sourceOptions([]);
  window.addEventListener('hfl:activity-scope',()=>{focusId=null;selected=null;load();});
  $('entities').onclick=()=>window.activityModals.open('entities','');

  if(pendingState){
    for(const id of ['search','rolling','since','until']){
      const value=pendingState.filters[id];
      if(typeof value==='string'&&($(id).tagName!=='SELECT'||[...$(id).options].some(o=>o.value===value)))$(id).value=value;
    }
    $('shared').checked=pendingState.filters.shared===true;
    enabled=new Set([...pendingState.enabled,'ideas','actions','goals','drafts','boards','lists','thoughts']);pendingState.sources.forEach(s=>selectedSources.add(s));
    if(PRESETS[pendingState.preset])preset=pendingState.preset;
    if(Number.isFinite(pendingState.layoutSeed))layoutSeed=pendingState.layoutSeed;
    selected=typeof pendingState.selected==='string'?pendingState.selected:null;
    focusId=typeof pendingState.focusId==='string'?pendingState.focusId:null;
    window.activityModals?.setAll(pendingState.all);syncDates();sourceOptions([]);
  }
  showMode();
  const previewAnimation=!reducedMotion&&new URLSearchParams(location.search).get('animation')==='drift'?'drift':'off';
  setAnimation(readOnly?previewAnimation:!reducedMotion&&['off','breathing','ripple','drift'].includes(pendingState?.animationMode)?pendingState.animationMode:savedAnimation(),false);
  requestAnimationFrame(animate);
  if(window.HflIdeas){
    window.HflIdeas.maps.getPositions=()=>Object.fromEntries(nodes.map(n=>{
      const point=window.HflIdeas.maps.current?(layoutTargets.get(n.id)||n):n;
      return [n.id,{x:point.x,y:point.y}];
    }));
    window.addEventListener('hfl:ideas-updated',event=>{if(event.detail?.boardSwitch){pendingState=null;selected=null;enabled=new Set(['entries','sources','daily','people','companies','tools','topics','objects','ideas','actions','goals','drafts','boards','lists','thoughts']);}if(event.detail?.selectId)selected=event.detail.selectId;
      if(event.detail?.refreshShared||window.HflIdeas.maps.current?.members.some(id=>id.startsWith('list:'))){load(true);return;}
      if(event.detail?.boardLocal&&!event.detail?.boardSwitch){
        const board=window.HflIdeas.maps.current;
        configureData({nodes:board.members.map(id=>window.HflIdeas.maps.nodes.get(id)).filter(Boolean),edges:[...window.HflIdeas.maps.sharedEdges.values()],sources:[]},true);
        return;
      }
      focusId=null;if(!window.HflIdeas.maps.current&&preset==='mindmap')preset='timeline';load();});
    window.HflIdeas.maps.init(document.getElementById('idea-map-tools')).then(load);
  }else load();
})();
