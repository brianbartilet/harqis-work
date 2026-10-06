import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ForceGraph2D from 'react-force-graph-2d';
import {presetLayout, timelineFitPoints} from './graph-presets.mjs';

// Same type palette and sizing conventions as the Activity Graph.
const palette = {entries:'#77dcf5', people:'#ffbd91', companies:'#deafff', tools:'#70edbd', topics:'#9bafff', daily:'#95a7c3', ideas:'#f9ca74', actions:'#fb8ca6', goals:'#a7f3d0', drafts:'#c4b5fd', lists:'#5eead4', thoughts:'#c4b5fd', boards:'#93c5fd', sources:'#e9c96c'};
const kindName = kind => ({daily:'Date', entries:'Entry', people:'Person', companies:'Company', ideas:'Idea', actions:'Action', thoughts:'Thought', boards:'Board', goals:'Goal', lists:'List', sources:'Source', tools:'Tool', topics:'Topic'}[kind] || kind);
const identity = value => typeof value === 'object' ? value.id : value;

function SharedGraph({data, layout = 'timeline', rootId}) {
  const host = useRef(null), graph = useRef(null);
  const [width, setWidth] = useState(600), [selected, setSelected] = useState(null);
  const [directoryOpen, setDirectoryOpen] = useState(false), [query, setQuery] = useState('');
  const model = useMemo(() => {
    const degree = new Map(data.nodes.map(n => [n.id, 0]));
    data.edges.forEach(e => [e.source,e.target].forEach(id => degree.set(id,(degree.get(id)||0)+1)));
    const nodes = data.nodes.map(n => ({...n, visibleDegree:degree.get(n.id)||0,
      radius:layout === 'board' ? 8+3*(data.node_sizes?.[n.id]||3) : n.kind==='entries' ? 5 : 6+4*Math.log2(1+(degree.get(n.id)||0))}));
    const positions = presetLayout(nodes, data.edges, layout === 'timeline' ? 'timeline' : 'mindmap', 0, rootId).positions;
    nodes.forEach(n => {
      const p = layout === 'board' && data.positions?.[n.id] || positions.get(n.id) || {x:0,y:0};
      n.x=n.fx=Number.isFinite(p.x)?p.x:0; n.y=n.fy=Number.isFinite(p.y)?p.y:0;
    });
    return {nodes, links:data.edges.map(e=>({...e}))};
  }, [data, layout, rootId]);
  const fit = () => {
    if (!graph.current || !model.nodes.length) return;
    if (layout === 'timeline' && model.nodes.some(n=>n.kind==='daily')) {
      const points = timelineFitPoints(model.nodes,new Map(model.nodes.map(n=>[n.id,n])));
      const a=points[0], b=points[1];
      graph.current.centerAt((a.x+b.x)/2,(a.y+b.y)/2,0);
      graph.current.zoom(Math.min((width-80)/(b.x-a.x),380/(b.y-a.y)),0);
    } else graph.current.zoomToFit(0,65);
  };
  useEffect(() => {
    const observer = new ResizeObserver(([entry])=> {if(entry.contentRect.width>0)setWidth(entry.contentRect.width);});
    observer.observe(host.current); return ()=>observer.disconnect();
  }, []);
  useEffect(() => {const timer=setTimeout(fit,100);return ()=>clearTimeout(timer);}, [width,model]);
  const peers = selected ? model.links.filter(e=>[identity(e.source),identity(e.target)].includes(selected.id)) : [];
  const matches = directoryOpen ? model.nodes.filter(n=>(n.label+' '+kindName(n.kind)).toLowerCase().includes(query.toLowerCase())) : [];
  return <>
    <div className="share-graph-toolbar" role="group" aria-label="Graph controls">
      <span>{layout==='timeline'?'Timeline':layout==='board'?'Board map':'Connections'} · Read-only</span>
      <div><button type="button" title="Zoom in" aria-label="Zoom in" onClick={()=>graph.current?.zoom(graph.current.zoom()*1.3,150)}>+</button>
      <button type="button" title="Zoom out" aria-label="Zoom out" onClick={()=>graph.current?.zoom(graph.current.zoom()/1.3,150)}>−</button>
      <button type="button" title="Reset view" aria-label="Reset view" onClick={fit}>⛶</button></div>
    </div>
    <div ref={host} className="share-graph-stage" tabIndex={0} aria-label="Read-only shared activity graph" onKeyDown={event=>{
      if(!['ArrowRight','ArrowLeft'].includes(event.key)||!model.nodes.length)return;
      event.preventDefault();const i=model.nodes.findIndex(n=>n.id===selected?.id);
      setSelected(model.nodes[(i+(event.key==='ArrowRight'?1:model.nodes.length-1)+model.nodes.length)%model.nodes.length]);
    }}>
    {model.nodes.length ? <ForceGraph2D ref={graph} width={width} height={440} graphData={model}
      backgroundColor="#0b1728" enableNodeDrag={false} cooldownTicks={0} nodeLabel={()=>''}
      onNodeClick={setSelected} linkColor={()=>'#94a3b855'} linkWidth={.7}
      nodeCanvasObject={(node,ctx,scale)=>{
        const ink=palette[node.kind]||'#e9c96c', radius=node.radius/scale;
        const fill=ctx.createRadialGradient(node.x-radius*.3,node.y-radius*.4,0,node.x,node.y,radius*1.6);
        fill.addColorStop(0,'#effbff');fill.addColorStop(.3,ink);fill.addColorStop(1,ink+'70');
        ctx.beginPath();ctx.arc(node.x,node.y,radius,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();
        if(selected?.id===node.id){ctx.strokeStyle=ink;ctx.lineWidth=2/scale;ctx.stroke();}
        // Dense graphs reveal labels as the reader zooms; dates and selected nodes stay legible.
        if(model.nodes.length<40||scale>.7||node.kind==='daily'||selected?.id===node.id){
          const text=node.label.length>48?node.label.slice(0,45)+'…':node.label;
          ctx.font=`600 ${12/scale}px system-ui`;ctx.textBaseline='middle';
          const x=node.x+radius+6/scale,w=ctx.measureText(text).width;
          ctx.fillStyle='#0b1728e8';ctx.fillRect(x-3/scale,node.y-9/scale,w+6/scale,18/scale);
          ctx.fillStyle='#e2e8f0';ctx.fillText(text,x,node.y);
        }
      }} nodePointerAreaPaint={(node,color,ctx,scale)=>{ctx.fillStyle=color;ctx.beginPath();ctx.arc(node.x,node.y,(node.radius+5)/scale,0,2*Math.PI);ctx.fill();}} /> : <p className="share-scope-note">No approved connections in this scope.</p>}
    </div>
    <div className="share-graph-legend">{[...new Set(model.nodes.map(n=>n.kind))].map(kind=><span className="share-kind-pill" data-kind={kind} key={kind}><i style={{background:palette[kind]||'#e9c96c'}}/>{kindName(kind)}</span>)}</div>
    {selected && <section className="share-graph-selection" aria-live="polite"><span className="share-kind-pill" data-kind={selected.kind}>{kindName(selected.kind)}</span><h4>{selected.label}</h4>{selected.body&&<p>{selected.body}</p>}
      <ul>{peers.slice(0,100).map((e,i)=><li key={i}>{e.relation} · {model.nodes.find(n=>n.id===(identity(e.source)===selected.id?identity(e.target):identity(e.source)))?.label}</li>)}</ul>{peers.length>100&&<p>Showing 100 of {peers.length} connections. Explore the graph for more.</p>}</section>}
    <details className="share-graph-directory" onToggle={event=>setDirectoryOpen(event.currentTarget.open)}>
      <summary>Objects and connections · {model.nodes.length} objects · {model.links.length} connections</summary>
      {directoryOpen && <><input type="search" className="control" aria-label="Find a shared graph object" placeholder="Find an object or type…" value={query} onChange={e=>setQuery(e.target.value)}/>
      <ul>{matches.slice(0,100).map(n=><li key={n.id}><span className="share-kind-pill" data-kind={n.kind}>{kindName(n.kind)}</span><button type="button" onClick={()=>{setSelected(n);graph.current?.centerAt(n.x,n.y,150);graph.current?.zoom(1,150);}}>{n.label}</button></li>)}</ul>
      {matches.length>100&&<p className="share-scope-note">Showing 100 of {matches.length} objects. Search to narrow the list.</p>}
      {!matches.length&&<p className="share-scope-note">No matching objects.</p>}</>}
    </details>
  </>;
}
const roots = new Map();
window.renderShareGraphs = () => {
  for(const [host,root] of roots)if(!host.isConnected){root.unmount();roots.delete(host);}
  document.querySelectorAll('[data-shared-graph]').forEach(container=>{
    const host=container.querySelector('[data-graph-canvas]');
    if(!host||roots.has(host)||!container.getClientRects().length)return;
    const data=JSON.parse(container.querySelector('[data-graph-data]').textContent);
    const root=createRoot(host);roots.set(host,root);root.render(<SharedGraph data={data} layout={container.dataset.graphLayout}/>);
  });
};
document.addEventListener('toggle',()=>window.renderShareGraphs(),true);
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-share-connections]');if(!button)return;
  const raw=JSON.parse(document.querySelector('[data-share-connections-data]').textContent), id=button.dataset.shareConnections;
  const ids=new Set([id]);raw.edges.filter(e=>e.source===id||e.target===id).forEach(e=>{ids.add(e.source);ids.add(e.target);});
  const data={nodes:raw.nodes.filter(n=>ids.has(n.id)),edges:raw.edges.filter(e=>ids.has(e.source)&&ids.has(e.target))};
  const dialog=document.createElement('dialog');dialog.className='share-connections-dialog';dialog.setAttribute('aria-label','Approved object connections');
  const close=document.createElement('button');close.type='button';close.className='btn btn-soft';close.textContent='Close connections';close.onclick=()=>dialog.close();
  const title=document.createElement('h3');title.textContent=data.nodes.find(n=>n.id===id)?.label||'Connections';
  const host=document.createElement('div');dialog.append(close,title,host);document.body.append(dialog);dialog.showModal();
  const root=createRoot(host);root.render(<SharedGraph data={data} layout="connections" rootId={id}/>);
  dialog.addEventListener('close',()=>{root.unmount();dialog.remove();button.focus();},{once:true});
});
