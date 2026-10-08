import React, {useEffect, useId, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {createPortal} from 'react-dom';
import ForceGraph2D from 'react-force-graph-2d';
import {placeLabels} from './graph-labels.mjs';
import {GraphIcon} from './graph-icons.jsx';
import {PRESETS, presetLayout, motionOffset, phaseFor} from './graph-presets.mjs';
import {shareTimeline, timelineBounds} from './share-timeline.mjs';

// Same type palette and sizing conventions as the Activity Graph.
const palette = {entries:'#77dcf5', people:'#ffbd91', companies:'#deafff', tools:'#70edbd', topics:'#9bafff', daily:'#95a7c3', ideas:'#f9ca74', actions:'#fb8ca6', goals:'#a7f3d0', drafts:'#c4b5fd', lists:'#5eead4', thoughts:'#c4b5fd', boards:'#93c5fd', sources:'#e9c96c'};
const kindName = kind => ({daily:'Date', entries:'Entry', people:'Person', companies:'Company', ideas:'Idea', actions:'Action', thoughts:'Thought', boards:'Board', goals:'Goal', lists:'List', sources:'Source', tools:'Tool', topics:'Topic'}[kind] || kind);
const legendLabel = kind => ({daily:'dates', companies:'organizations', drafts:'thoughts', thoughts:'list thoughts'}[kind] || kind.replaceAll('_', ' ')).toLowerCase();
const identity = value => typeof value === 'object' ? value.id : value;
const SelectCaret = () => <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 7.5 5 5 5-5"/></svg>;

function SharedGraph({data, layout = 'timeline', rootId, initialView = {}, onViewChange, fillHeight = false, controlsHost, collapseEntitiesOnMobile = false, description = ''}) {
  const host = useRef(null), graph = useRef(null), cameraReady = useRef(false), dragging = useRef(false);
  const connectionFitted = useRef(false);
  const descriptionOverlay = useRef(null);
  const [width, setWidth] = useState(600), [selected, setSelected] = useState(data.nodes.find(n=>n.id===rootId)||null);
  const [height, setHeight] = useState(440);
  const [entityOrbsExpanded, setEntityOrbsExpanded] = useState(false);
  const entityOrbsId = useId();
  const [view, setView] = useState(() => ({preset:'timeline', animation:'drift', hidden_kinds:[], ...initialView}));
  const viewRef = useRef(view);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const motion = useRef({time:initialView.animation_time || 0, last:0});
  const kinds = useMemo(() => [...new Set(data.nodes.map(n=>n.kind))], [data]);
  const changeView = patch => {
    const next = {...captureView(), ...patch};
    if (patch.hidden_kinds) cameraReady.current=false;
    if (patch.preset && patch.preset !== view.preset) {
      next.positions={}; next.viewport=null; next.animation_time=0;
      motion.current.time=0; cameraReady.current=false;
    }
    viewRef.current=next; setView(next); onViewChange?.(next);
  };
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReducedMotion(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  const model = useMemo(() => {
    const degree = new Map(data.nodes.map(n => [n.id, 0]));
    data.edges.forEach(e => [e.source,e.target].forEach(id => degree.set(id,(degree.get(id)||0)+1)));
    const nodes = data.nodes.map(n => ({...n, visibleDegree:degree.get(n.id)||0,
      radius:layout === 'board' ? 7+1.5*(data.node_sizes?.[n.id]||3) : layout==='connections' ? Math.min(22,10+4*Math.log2(1+(degree.get(n.id)||0))) : n.kind==='entries' ? 5 : Math.min(16,6+2*Math.log2(1+(degree.get(n.id)||0)))}));
    const timeline = layout === 'timeline' && view.preset === 'timeline' ? shareTimeline(nodes, data.edges) : null;
    const positions = timeline?.positions || presetLayout(nodes, data.edges, layout === 'timeline' ? view.preset : 'mindmap', 0, rootId).positions;
    nodes.forEach(n => {
      const saved = layout === 'timeline' && viewRef.current.positions?.[n.id];
      const target = positions.get(n.id) || {x:0,y:0};
      const p = saved || layout === 'board' && data.positions?.[n.id] || target;
      n.x=n.fx=Number.isFinite(p.x)?p.x:0; n.y=n.fy=Number.isFinite(p.y)?p.y:0;
      n.origin={x:n.x,y:n.y,anchor:target.anchor}; n.manual=!!saved?.manual;
      if(layout==='connections'){delete n.fx;delete n.fy;}
    });
    const visible = nodes.filter(n=>!view.hidden_kinds.includes(n.kind)), ids = new Set(visible.map(n=>n.id));
    return {nodes:visible, allNodes:nodes, links:data.edges.filter(e=>ids.has(identity(e.source))&&ids.has(identity(e.target))).map(e=>({...e})), timeline};
  }, [data, layout, rootId, view.preset, view.hidden_kinds]);
  useEffect(() => {setSelected(current=>current ? model.nodes.find(n=>n.id===current.id)||null : null);}, [model]);
  useEffect(() => {
    const container=host.current?.closest('[data-shared-graph]');
    if(!container)return;
    const reveal=()=>{
      const node=model.nodes.find(n=>n.id===container.dataset.selectNode);
      if(node){setSelected(node);delete container.dataset.selectNode;}
    };
    reveal();container.addEventListener('share-select-node',reveal);
    return ()=>container.removeEventListener('share-select-node',reveal);
  }, [model]);
  useEffect(() => {
    if (layout === 'timeline') model.nodes.forEach(n=>{n.x=n.fx=n.origin.x;n.y=n.fy=n.origin.y;});
  }, [view.animation, reducedMotion, model, layout]);
  const captureView = () => ({...viewRef.current,
    positions:Object.fromEntries(model.allNodes.map(n=>[n.id,{x:n.origin.x,y:n.origin.y,manual:n.manual}])),
    animation_time:motion.current.time,
  });
  const persist = () => {const next=captureView();viewRef.current=next;onViewChange?.(next);return next;};
  const recordCamera = () => {
    if(!cameraReady.current||!graph.current||!host.current?.getClientRects().length)return;
    const center=graph.current.centerAt();
    viewRef.current={...viewRef.current,viewport:{x:center.x,y:center.y,zoom:graph.current.zoom()}};
  };
  // FormData is also used for preview refreshes. Capture immediately so save and
  // generate cannot miss a recent pan, zoom, drag, or animation frame.
  useEffect(() => {
    const form=host.current?.closest('form');
    if(!form||!onViewChange)return;
    const save=event=>{event.formData.set('graph_view',JSON.stringify(persist()));};
    form.addEventListener('formdata',save);
    return ()=>form.removeEventListener('formdata',save);
  }, [model, onViewChange]);
  const fit = () => {
    if (!graph.current || !model.nodes.length) return;
    cameraReady.current=false;
    const bounds = (model.timeline && timelineBounds(model.nodes, model.timeline.fitIds)) || timelineBounds(model.nodes,new Set(model.nodes.map(n=>n.id)));
    if (bounds) {
      graph.current.centerAt((bounds.left+bounds.right)/2,(bounds.top+bounds.bottom)/2,0);
      graph.current.zoom(Math.max(.01, Math.min(1, (width-48)/(bounds.right-bounds.left),(height-100)/(bounds.bottom-bounds.top))),0);
    }
    cameraReady.current=true;recordCamera();persist();
  };
  useEffect(() => {
    // D3 centers against integer clientWidth; use the same width for rendering
    // so fractional CSS pixels do not shift the saved camera on every reload.
    const observer = new ResizeObserver(([entry])=> {
      if(entry.contentRect.width>0)setWidth(Math.floor(entry.contentRect.width));
      if(fillHeight && entry.contentRect.height>0)setHeight(Math.max(120,Math.floor(entry.contentRect.height)));
    });
    observer.observe(host.current); return ()=>observer.disconnect();
  }, [fillHeight]);
  useEffect(() => {
    cameraReady.current=false;
    const timer=setTimeout(()=>{
      if(!graph.current)return;
      const viewport=viewRef.current.viewport;
      if(viewport){
        graph.current.zoom(viewport.zoom,0);graph.current.centerAt(viewport.x,viewport.y,0);
        cameraReady.current=true;recordCamera();persist();
      } else fit();
    },100);
    return ()=>clearTimeout(timer);
  }, [width,height,model]);
  const peers = selected ? model.links.filter(e=>[identity(e.source),identity(e.target)].includes(selected.id)) : [];
  const controls = layout==='timeline' ? <div className="share-graph-options">
      {onViewChange && <label>Preset <span className="share-graph-select"><select aria-label="Graph preset" value={view.preset} onChange={e=>changeView({preset:e.target.value})}>{Object.entries(PRESETS).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select><SelectCaret/></span></label>}
      {!controlsHost && <label>Animation <span className="share-graph-select"><select aria-label="Graph animation" value={view.animation} onChange={e=>changeView({animation:e.target.value})}>{['off','breathing','ripple','drift'].map(mode=><option key={mode} value={mode}>{mode[0].toUpperCase()+mode.slice(1)}</option>)}</select><SelectCaret/></span></label>}
      {reducedMotion && view.animation!=='off' && <span>Animation paused by your reduced-motion preference.</span>}
    </div> : null;
  return <>
    {controlsHost ? createPortal(controls, controlsHost) : controls}
    <div className={'share-graph-workspace'+(selected?' has-selection':'')}><div className="share-graph-viewport">
    {description && <p ref={descriptionOverlay} className="share-board-purpose" title={description}>{description}</p>}
    <div className="share-graph-toolbar" role="group" aria-label="Graph controls">
      <span>{layout==='timeline'?'Timeline':layout==='board'?'Board map':'Connections'} · Read-only</span>
      <div><button type="button" title="Zoom in" aria-label="Zoom in" onClick={()=>graph.current?.zoom(graph.current.zoom()*1.3,150)}><GraphIcon name="plus"/></button>
      <button type="button" title="Zoom out" aria-label="Zoom out" onClick={()=>graph.current?.zoom(graph.current.zoom()/1.3,150)}><GraphIcon name="minus"/></button>
      <button type="button" title="Reset view" aria-label="Reset view" onClick={fit}><GraphIcon name="fit"/></button></div>
    </div>
    <div ref={host} className="share-graph-stage" tabIndex={0} aria-label="Read-only shared activity graph" onKeyDown={event=>{
      if(!['ArrowRight','ArrowLeft'].includes(event.key)||!model.nodes.length)return;
      event.preventDefault();const i=model.nodes.findIndex(n=>n.id===selected?.id);
      setSelected(model.nodes[(i+(event.key==='ArrowRight'?1:model.nodes.length-1)+model.nodes.length)%model.nodes.length]);
    }}>
    {model.nodes.length ? <ForceGraph2D ref={graph} width={width} height={height} graphData={model}
      autoPauseRedraw={layout!=='timeline'||view.animation==='off'||reducedMotion||!!selected}
      onRenderFramePre={()=>{
        const now=performance.now(), clock=motion.current, delta=Math.min(100,now-(clock.last||now));clock.last=now;
        if(layout!=='timeline'||view.animation==='off'||reducedMotion||selected||dragging.current||document.hidden||!host.current?.getClientRects().length)return;
        clock.time+=delta;
        model.nodes.forEach(n=>{
          const offset=motionOffset(view.animation,n.origin,clock.time,phaseFor(n.id),n.manual||view.preset==='timeline'&&n.origin.anchor);
          n.x=n.fx=n.origin.x+offset.x;n.y=n.fy=n.origin.y+offset.y;
        });
      }}
      backgroundColor="#0b1728" enableNodeDrag={true} cooldownTicks={layout==='connections'?100:0} minZoom={.01} maxZoom={4}
      onEngineStop={()=>{if(layout==='connections'&&!connectionFitted.current){connectionFitted.current=true;fit();}}}
      onZoom={recordCamera} onZoomEnd={()=>{recordCamera();if(cameraReady.current)persist();}}
      nodeLabel={node=>{const tip=document.createElement('span');tip.textContent=node.label;return tip;}}
      onNodeDrag={()=>{dragging.current=true;}}
      onNodeDragEnd={node=>{dragging.current=false;node.fx=node.x;node.fy=node.y;node.origin={...node.origin,x:node.x,y:node.y};node.manual=true;persist();}}
      onBackgroundClick={()=>setSelected(null)}
      linkLineDash={edge=>edge.relation?.includes('board')?[4,3]:null}
      linkCurvature={.12} linkDirectionalArrowLength={3}
      onNodeClick={setSelected} linkColor={()=>'#94a3b855'} linkWidth={.7}
          onRenderFramePost={(ctx, scale) => {
            if (!graph.current) return;
            const origin = graph.current.screen2GraphCoords(0, 0);
            const candidates = model.nodes.map(node => ({...node, ...graph.current.graph2ScreenCoords(node.x, node.y),
              radius: node.radius, degree:node.kind==='daily'?Number.MAX_SAFE_INTEGER:node.visibleDegree, preferred:model.nodes.length<40||node.kind!=='entries',
              emphasis:node.id === rootId || node.id === selected?.id || node.id === model.timeline?.focusId}));
            const obstacles = [{x:width-130,y:0,w:130,h:48}, ...candidates.map(n => ({x:n.x-n.radius,y:n.y-n.radius,w:n.radius*2,h:n.radius*2}))];
            if(descriptionOverlay.current)obstacles.push({x:10,y:10,w:descriptionOverlay.current.offsetWidth,h:descriptionOverlay.current.offsetHeight});
            const labels = placeLabels(candidates, {width, height, zoom:scale, obstacles}, (text, font) => {
              ctx.font = `${font}px system-ui`; return ctx.measureText(text).width;
            });
            for (const box of labels) {
              const x = origin.x + box.x / scale, y = origin.y + box.y / scale;
              const ink = palette[box.node.kind] || '#9bafff';
              ctx.fillStyle = box.node.emphasis ? '#142a42f5' : '#0a1728ee'; ctx.beginPath();
              ctx.roundRect(x, y, box.w / scale, box.h / scale, 5 / scale); ctx.fill();
              ctx.strokeStyle = ink + (box.node.emphasis ? '90' : '30'); ctx.lineWidth = .6 / scale; ctx.stroke();
              ctx.font = `500 ${box.font / scale}px system-ui`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
              ctx.fillStyle = box.node.emphasis ? '#ffffff' : '#d9e9fa'; ctx.fillText(box.text, x + 6 / scale, y + 12 / scale);
            }
          }}
          nodeCanvasObject={(node, ctx, globalScale) => {
            if (!Number.isFinite(node.x) || !Number.isFinite(node.y) || globalScale <= 0) return;
            const radius = node.radius / globalScale, ink = palette[node.kind] || '#9bafff';
            const emphasis = node.id === rootId || node.id === selected?.id;
            ctx.save();
            const glow=ctx.createRadialGradient(node.x,node.y,0,node.x,node.y,(emphasis?30:18)/globalScale);
            glow.addColorStop(0,ink+(emphasis?'75':'35'));glow.addColorStop(1,ink+'00');
            ctx.fillStyle=glow;ctx.beginPath();ctx.arc(node.x,node.y,(emphasis?30:18)/globalScale,0,2*Math.PI);ctx.fill();
            const fill=ctx.createRadialGradient(node.x-radius*.3,node.y-radius*.4,0,node.x,node.y,radius*1.6);
            fill.addColorStop(0,'#effbff');fill.addColorStop(.3,ink);fill.addColorStop(1,ink+'70');
            ctx.beginPath();ctx.arc(node.x,node.y,radius,0,2*Math.PI);ctx.fillStyle=fill;ctx.fill();
            ctx.strokeStyle=ink;ctx.lineWidth=.8/globalScale;ctx.stroke();
            if(model.nodes.length<=35&&node.kind!=='entries'){
              const mark=node.kind==='people'?node.label.slice(0,1):node.kind==='tools'?'⌘':'◇';
              ctx.font=`600 ${14/globalScale}px system-ui`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle='#10263c';ctx.fillText(mark,node.x,node.y);ctx.textAlign='left';
            }
            if(emphasis){ctx.beginPath();ctx.arc(node.x,node.y,radius+5/globalScale,0,2*Math.PI);ctx.strokeStyle=ink+'aa';ctx.lineWidth=1/globalScale;ctx.stroke();}
            ctx.restore();
          }} nodePointerAreaPaint={(node,color,ctx,scale)=>{ctx.fillStyle=color;ctx.beginPath();ctx.arc(node.x,node.y,(node.radius+5)/(graph.current?.zoom()||1),0,2*Math.PI);ctx.fill();}} /> : <p className="share-scope-note">{data.nodes.length ? 'No visible objects. Enable an entity type below to show it.' : 'No approved connections in this scope.'}</p>}
    </div>
    </div>
    {selected && <aside className="share-graph-inspector share-graph-selection"><button type="button" className="share-inspector-close" aria-label="Close object details" onClick={()=>setSelected(null)}>×</button><span className="share-kind-pill" data-kind={selected.kind}>{kindName(selected.kind)}</span><h3>{selected.label}</h3><div className="markdown-body" dangerouslySetInnerHTML={{__html:selected.body_html||''}}/><h4>Connections</h4><ul>{peers.slice(0,100).map((e,i)=>{const other=model.nodes.find(n=>n.id===(identity(e.source)===selected.id?identity(e.target):identity(e.source)));return <li key={i}><button type="button" onClick={()=>setSelected(other)}>{other?.label}</button><small>{e.relation}</small></li>;})}</ul></aside>}
    </div>
    <p className="share-graph-hint">{model.timeline && `${model.timeline.hasEntry ? 'Latest entry and its connections' : 'Latest available date'} · Oldest to newest, left to right. `}Drag to explore · Scroll to zoom · Select an orb for details. Toggle types below to filter the view.</p>
    {collapseEntitiesOnMobile && <button type="button" className="share-entity-orbs-toggle" aria-expanded={entityOrbsExpanded} aria-controls={entityOrbsId} onClick={()=>setEntityOrbsExpanded(expanded=>!expanded)}>Entity orbs <SelectCaret/></button>}
    <div id={entityOrbsId} className={'share-graph-legend'+(collapseEntitiesOnMobile&&!entityOrbsExpanded?' share-entity-orbs-collapsed':'')} role="group" aria-label="Graph entity types">{kinds.map(kind=><button type="button" className="share-kind-pill" data-kind={kind} key={kind} aria-pressed={!view.hidden_kinds.includes(kind)} onClick={()=>changeView({hidden_kinds:view.hidden_kinds.includes(kind)?view.hidden_kinds.filter(k=>k!==kind):[...view.hidden_kinds,kind]})}><i style={{background:palette[kind]||'#e9c96c'}}/>{legendLabel(kind)}</button>)}</div>
  </>;
}
const roots = new Map();
// Recipient navigation resets exploration to the owner's published view and
// releases canvases/animation loops while they are hidden.
window.resetShareGraphs = container => {
  for (const [host, root] of roots) if (container.contains(host)) {
    delete host.closest("[data-shared-graph]").dataset.selectNode;
    root.unmount(); roots.delete(host);
  }
};
window.renderShareGraphs = () => {
  for(const [host,root] of roots)if(!host.isConnected){root.unmount();roots.delete(host);}
  document.querySelectorAll('[data-shared-graph]').forEach(container=>{
    const host=container.querySelector('[data-graph-canvas]');
    if(!host||roots.has(host)||!container.getClientRects().length)return;
    const data=JSON.parse(container.querySelector('[data-graph-data]').textContent);
    const settings=container.dataset.graphLayout==='timeline' ? container.closest('form')?.querySelector('[name="graph_view"]') : null;
    const initialView=settings ? JSON.parse(settings.value) : data.view || {};
    const onViewChange=settings ? view=>{settings.value=JSON.stringify(view);} : undefined;
    const root=createRoot(host);roots.set(host,root);root.render(<SharedGraph data={data} layout={container.dataset.graphLayout} initialView={initialView} onViewChange={onViewChange} fillHeight={!!container.closest("[data-share-main]")} collapseEntitiesOnMobile={!!container.closest("[data-share-main]")} controlsHost={container.closest("[data-share-main]")?.querySelector("[data-share-graph-controls]")} description={container.closest("[data-share-board]")?.querySelector("[data-share-board-description]")?.content.textContent.trim() || ""}/>);
  });
};
window.selectShareGraphNode = (panel, nodeId) => {
  const container=panel?.querySelector('[data-shared-graph]');
  if(!container)return;
  container.dataset.selectNode=nodeId;
  container.dispatchEvent(new Event('share-select-node'));
};
document.addEventListener('toggle',()=>window.renderShareGraphs(),true);
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-share-connections]');if(!button)return;
  const raw=JSON.parse(document.querySelector('[data-share-connections-data]').textContent), id=button.dataset.shareConnections;
  const ids=new Set([id]);raw.edges.filter(e=>e.source===id||e.target===id).forEach(e=>{ids.add(e.source);ids.add(e.target);});
  const data={nodes:raw.nodes.filter(n=>ids.has(n.id)),edges:raw.edges.filter(e=>ids.has(e.source)&&ids.has(e.target))};
  const dialog=document.createElement('dialog');dialog.className='share-connections-dialog';dialog.setAttribute('aria-label','Approved object connections');
  const close=document.createElement('button');close.type='button';close.className='btn btn-soft';close.textContent='Close connections';close.onclick=()=>dialog.close();
  const title=document.createElement('h3');title.textContent='Connections · '+(data.nodes.find(n=>n.id===id)?.label||'Shared object');
  const host=document.createElement('div');const header=document.createElement('header');header.className='share-dialog-header';header.append(title,close);dialog.append(header,host);document.body.append(dialog);dialog.showModal();
  const root=createRoot(host);root.render(<SharedGraph data={data} layout="connections" rootId={id}/>);
  dialog.addEventListener('close',()=>{root.unmount();dialog.remove();button.focus();},{once:true});
});
