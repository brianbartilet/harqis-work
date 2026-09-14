import {exampleGraph} from './knowledge-graph-example.js';
import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ForceGraph2D from 'react-force-graph-2d';
import {forceCollide, forceX, forceY} from 'd3-force-3d';
// Bundled locally. Graph data is fetched only from the authenticated HARQIS API.
(() => {
  'use strict';
  const $ = id => document.getElementById('kg-' + id);
  const palette = {entries:'#77dcf5', people:'#ffbd91', companies:'#deafff', tools:'#70edbd', topics:'#9bafff', daily:'#95a7c3'};
  const color = kind => palette[kind] || '#e9c96c';
  let data = {nodes:[],edges:[]}, nodes = [], edges = [], selected = null, enabled = new Set();
  let exampleMode=new URLSearchParams(location.search).get('example')==='1';
  let loading=false, graphData={nodes:[],links:[]}, graphApi=null, active=null, focusId=null;
  const host=$('canvas'), root=createRoot(host);
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const endpointId=value=>typeof value==='object'?value.id:value;
  const duration=reducedMotion?0:500;
  function fit(){
    if(!graphApi||!graphData.nodes.length||graphData.nodes.some(n=>!Number.isFinite(n.x)||!Number.isFinite(n.y)))return;
    const bounds=graphApi.getGraphBbox();
    if(bounds&&[...bounds.x,...bounds.y].every(Number.isFinite))graphApi.zoomToFit(duration,70);
  }
  function zoom(factor){if(graphApi)graphApi.zoom(graphApi.zoom()*factor,duration);}
  function Graph({data,activeId,selectedId}) {
    const ref=useRef(),needsFit=useRef(true),labelBoxes=useRef([]);
    const [size,setSize]=useState({width:host.clientWidth,height:host.clientHeight});
    useEffect(()=>{
      const observer=new ResizeObserver(()=>{setSize({width:host.clientWidth,height:host.clientHeight});needsFit.current=true;});
      observer.observe(host);return()=>observer.disconnect();
    },[]);
    useEffect(()=>{
      graphApi=ref.current;needsFit.current=true;
      ref.current.d3Force('charge').strength(-230);
      ref.current.d3Force('link').distance(105);
      ref.current.d3Force('collide',forceCollide(n=>n.radius+30).iterations(2));
      ref.current.d3Force('x',forceX(n=>n.clusterX||0).strength(.065));
      ref.current.d3Force('y',forceY(n=>n.clusterY||0).strength(.065));
      ref.current.d3ReheatSimulation();
    },[data]);
    useEffect(()=>{const timer=setTimeout(fit,100);return()=>clearTimeout(timer);},[size,data]);
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
        ctx.font=`600 ${14/globalScale}px system-ui,sans-serif`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle='#10263c';ctx.fillText(mark,node.x,node.y);ctx.textAlign='left';
      }
      if(emphasis){ctx.beginPath();ctx.arc(node.x,node.y,radius+5/globalScale,0,2*Math.PI);ctx.strokeStyle=ink+'aa';ctx.lineWidth=1/globalScale;ctx.stroke();}
      if(emphasis||(!activeId&&node.labelRank<(data.nodes.length<=35?35:9))||activeId&&near.has(node.id)&&near.size<16||globalScale>2.5&&visible){
        const fontSize=(emphasis?13:data.nodes.length<=35?12:11)/globalScale;ctx.font=`500 ${fontSize}px Inter,system-ui,sans-serif`;
        const label=node.label.length>34?node.label.slice(0,32)+'…':node.label;
        const x=node.x+radius+9/globalScale,y=node.y,w=ctx.measureText(label).width;
        const box={x:x-6/globalScale,y:y-12/globalScale,w:w+12/globalScale,h:24/globalScale};
        const overlaps=labelBoxes.current.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y);
        if(!overlaps||emphasis){
        labelBoxes.current.push(box);
        ctx.fillStyle=emphasis?'#142a42f5':'#0a1728dd';ctx.beginPath();ctx.roundRect(x-5/globalScale,y-11/globalScale,w+10/globalScale,22/globalScale,5/globalScale);ctx.fill();
        ctx.strokeStyle=ink+(emphasis?'90':'30');ctx.lineWidth=.6/globalScale;ctx.stroke();
        ctx.textBaseline='middle';ctx.fillStyle=emphasis?'#ffffff':'#d9e9fa';ctx.fillText(label,x,y);
        }
      }
      ctx.restore();
    }
    return <ForceGraph2D ref={ref} width={size.width} height={size.height}
      graphData={data} backgroundColor="rgba(0,0,0,0)" nodeLabel={()=>''}
      onRenderFramePre={()=>{labelBoxes.current=[];}}
      nodeCanvasObject={paintNode}
      nodePointerAreaPaint={(node,paint,ctx)=>{ctx.fillStyle=paint;ctx.beginPath();ctx.arc(node.x,node.y,(node.radius+4)/(ref.current?.zoom()||1),0,2*Math.PI);ctx.fill();}}
      linkColor={link=>color(link.target.kind)+(activeId?(isLinked(link)?'df':'07'):(data.nodes.length<=35?'70':'32'))}
      linkWidth={link=>isLinked(link)?2:data.nodes.length<=35?1.1:.65} linkCurvature={.16}
      linkDirectionalParticles={link=>!reducedMotion&&isLinked(link)?2:0}
      linkDirectionalParticleWidth={2} linkDirectionalParticleSpeed={.004}
      onNodeHover={node=>{host.style.cursor=node?'pointer':'grab';highlight(node?.id||selected);}}
      onNodeClick={node=>select(node.id)} onBackgroundClick={()=>select(null)}
      onNodeDragEnd={node=>{node.fx=node.x;node.fy=node.y;}}
      warmupTicks={reducedMotion?150:80} cooldownTicks={reducedMotion?0:100}
      onEngineStop={()=>{if(needsFit.current){needsFit.current=false;fit();}}}
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
    items.sort((a,b)=>b.visibleDegree-a.visibleDegree || a.label.localeCompare(b.label)).forEach(n => {
      const button=document.createElement('button'),dot=document.createElement('span'),name=document.createElement('span'),meta=document.createElement('small');
      dot.className='kg-dot';dot.style.background=color(n.kind);name.textContent=n.label;meta.textContent=n.visibleDegree+' links';button.title=n.label+' · '+n.kind;
      if(selected){const link=edges.find(e=>(e.source===selected&&e.target===n.id)||(e.target===selected&&e.source===n.id));if(link){const evidence=document.createElement('small');evidence.textContent=(link.relation||'linked')+' · '+(link.evidence||'');evidence.style.cssText='grid-column:2 / 4;white-space:normal;font-size:11px';button.append(evidence);button.title=link.evidence||n.label;}}
      button.prepend(dot,name,meta);button.onclick=()=>select(n.id);$('list').append(button);
    });
  }
  function select(id) {
    selected=id;const n=nodes.find(n=>n.id===id),near=connected(id);
    highlight(id);
    $('detail').replaceChildren();
    const heading=document.createElement('h2'),description=document.createElement('p');
    const eyebrow=document.createElement('span');eyebrow.className='kg-eyebrow';eyebrow.textContent=n?n.kind.replaceAll('_',' '):'Your knowledge, connected';$('detail').append(eyebrow);
    heading.textContent=n?n.label:'Follow a thread';
    description.textContent=n?[n.kind,n.date,n.source,near.size+' visible connections'].filter(Boolean).join(' · '):'Select a node to see its linked entries and entities.';
    $('detail').append(heading,description);
    if(n?.href) {const link=document.createElement('a');link.href=n.href;link.textContent='Open entry →';$('detail').append(link);}
    if(n){const focus=document.createElement('button');focus.textContent='Focus on this connection';focus.className='kg-focus-button';focus.onclick=()=>{focusId=n.id;render();};$('detail').append(focus);}
    if(focusId){const back=document.createElement('button');back.textContent='Back to overview';back.onclick=()=>{focusId=null;render();};$('detail').append(back);}
    if(n){const clear=document.createElement('button');clear.textContent='Show all nodes';clear.onclick=()=>select(null);$('detail').append(document.createElement('br'),clear);}
    const items=n?nodes.filter(node=>near.has(node.id)):nodes.slice();
    $('list-title').textContent=(n?'Linked nodes':'Nodes')+' · '+items.length;
    nodeList(items);
  }
  function render() {
    const degrees=new Map();data.edges.forEach(e=>{degrees.set(e.source,(degrees.get(e.source)||0)+1);degrees.set(e.target,(degrees.get(e.target)||0)+1);});
    let filtered=data.nodes.filter(n=>enabled.has(n.kind)&&(!$('shared').checked||n.kind==='entries'||degrees.get(n.id)>1));
    const query=$('search').value.trim().toLocaleLowerCase();
    if(query){const matches=new Set(filtered.filter(n=>n.label.toLocaleLowerCase().includes(query)).map(n=>n.id)),near=new Set(matches);data.edges.forEach(e=>{if(matches.has(e.source))near.add(e.target);if(matches.has(e.target))near.add(e.source);});filtered=filtered.filter(n=>near.has(n.id));}
    if(focusId){const keep=new Set([focusId]);data.edges.forEach(e=>{if(e.source===focusId)keep.add(e.target);if(e.target===focusId)keep.add(e.source);});filtered=filtered.filter(n=>keep.has(n.id));}
    const budget=Number($('density').value),limited=filtered.length>budget;
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
    nodes.forEach(n=>{const adjacent=edges.filter(e=>e.source===n.id||e.target===n.id).map(e=>e.source===n.id?e.target:e.source);const anchor=anchors.find(a=>a.id===n.id||adjacent.includes(a.id));const index=anchors.indexOf(anchor);n.clusterX=index<0?0:Math.cos(index*Math.PI/2)*220;n.clusterY=index<0?0:Math.sin(index*Math.PI/2)*160;});
    const grouping=$('group').value;
    if(grouping!=='relationships'){
      const groupOf=n=>grouping==='source'?n.source:(n.date||'').slice(0,7);
      const groups=[...new Set(nodes.filter(n=>n.kind==='entries').map(groupOf).filter(Boolean))].sort();
      nodes.forEach(n=>{let value=groupOf(n);if(!value){const neighbor=edges.find(e=>e.target===n.id);value=neighbor?groupOf(neighbor.a):'';}const i=groups.indexOf(value);n.clusterX=i<0?0:Math.cos(i*2*Math.PI/Math.max(1,groups.length))*350;n.clusterY=i<0?0:Math.sin(i*2*Math.PI/Math.max(1,groups.length))*250;});
    }
    graphData={nodes,links:edges.map(e=>({source:e.source,target:e.target}))};
    $('map-title').textContent=focusId?'Connection in focus':exampleMode?'Example constellation':'Knowledge constellation';
    $('map-count').textContent=nodes.length+' nodes · '+edges.length+' links';
    $('status').textContent=nodes.length+' / '+data.nodes.length+' nodes · '+edges.length+' connections'+(limited?' · '+$('density').selectedOptions[0].text.split(' · ')[0]+'; search or increase detail to explore more.':'')+(!nodes.length?' · No matching nodes. Clear your search or change the filters.':'');
    select(byId.has(selected)?selected:null);
  }
  function configureData(next) {
    data=next;selected=null;focusId=null;$('search').value='';
    enabled=new Set(data.nodes.map(n=>n.kind));$('types').replaceChildren();
    [...enabled].sort().forEach(kind=>{const label=document.createElement('label'),input=document.createElement('input'),dot=document.createElement('span');input.type='checkbox';input.checked=true;input.onchange=()=>{input.checked?enabled.add(kind):enabled.delete(kind);render();};dot.className='kg-dot';dot.style.background=color(kind);label.append(input,dot,document.createTextNode(kind.replaceAll('_',' ')));$('types').append(label);});
    render();
  }
  function showMode() {
    $('example').textContent=exampleMode?'Return to vault':'Try example graph';
    $('example').setAttribute('aria-pressed',String(exampleMode));
    $('example-note').hidden=!exampleMode;
    const url=new URL(location.href);exampleMode?url.searchParams.set('example','1'):url.searchParams.delete('example');history.replaceState(null,'',url);
  }
  async function load() {
    if(exampleMode){configureData(exampleGraph());return;}
    if(loading)return;loading=true;$('reload').disabled=true;$('status').textContent='Loading your graph…';
    try {
      const response=await fetch('/api/hfl/entities/graph?'+new URLSearchParams({source:$('source').value,since:$('since').value,until:$('until').value}),{cache:'no-store'});
      if(!response.ok)throw Error(response.status===401?'Sign in to view your knowledge graph.':'Graph could not load. Use Reload graph to try again.');
      const next=await response.json();
      if(!exampleMode)configureData(next);
    } catch(error){if(!exampleMode)$('status').textContent=error.message;} finally{loading=false;$('reload').disabled=false;}
  }
  $('example').onclick=()=>{exampleMode=!exampleMode;showMode();load();};
  let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(render,180);};
  $('filter').onclick=()=>{if(!exampleMode)load();};$('group').onchange=render;
  $('density').onchange=render;$('shared').onchange=render;$('in').onclick=()=>zoom(1.3);$('out').onclick=()=>zoom(1/1.3);$('fit').onclick=fit;$('reload').onclick=load;
  $('reset').onclick=()=>{$('search').value='';$('density').value='120';$('shared').checked=true;enabled=new Set(data.nodes.map(n=>n.kind));$('types').querySelectorAll('input').forEach(el=>el.checked=true);selected=null;focusId=null;render();};

  showMode();
  load();
})();
