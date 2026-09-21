import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ForceGraph2D from 'react-force-graph-2d';
import {placeLabels} from './graph-labels.mjs';

const colors = {actions:'#fb8ca6', ideas:'#f9ca74', drafts:'#c4b5fd', boards:'#93c5fd',
  goals:'#a7f3d0', entries:'#77dcf5', daily:'#95a7c3', people:'#ffbd91', tools:'#70edbd'};
const kindName = kind => ({actions:'Action', ideas:'Idea', drafts:'Thought', boards:'Board',
  goals:'Goal', entries:'Entry', daily:'Date', companies:'Organization'}[kind] || kind);
const identity = node => typeof node === 'object' ? node.id : node;
const tooltip = text => {const span = document.createElement('span'); span.textContent = text; return span;};
let activeDialog;

function Preview({item}) {
  const [data, setData] = useState(null), [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0), [selected, setSelected] = useState(null);
  const [size, setSize] = useState({width:480, height:360});
  const host = useRef(null), graph = useRef(null), fitted = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    const timeout = setTimeout(() => controller.abort(), 50000);
    setData(null); setError(''); setSelected(null); fitted.current = false;
    (async () => {
      try {
        const response = await fetch('/hfl-corpus/timeline/ideas/actions/' + encodeURIComponent(item.id) + '/connections',
          {cache:'no-store', signal:controller.signal});
        if (!response.ok) throw Error(response.status === 404 ? 'This action is unavailable or protected.' : 'Connections could not load. Please try again.');
        const result = await response.json();
        const links = result.edges.flatMap(edge => [{...edge}, ...(edge.direction === 'both'
          ? [{...edge, source:edge.target, target:edge.source, reverse:true}] : [])]);
        if (live) {setData({...result, links}); setSelected(result.nodes.find(n => n.id === result.root));}
      } catch (failure) {
        if (live) setError(failure.name === 'AbortError' ? 'Loading connections timed out. Please try again.' : failure.message);
      } finally {clearTimeout(timeout);}
    })();
    return () => {live = false; clearTimeout(timeout); controller.abort();};
  }, [item.id, attempt]);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setSize({width:entry.contentRect.width, height:entry.contentRect.height}));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, [data]);
  const fit = () => graph.current?.zoomToFit(250, 65, () => true);
  if (error) return <div className="connections-state" role="alert"><p>{error}</p><button onClick={() => setAttempt(a => a + 1)}>Retry</button></div>;
  if (!data) return <p className="connections-state" role="status">Loading connections…</p>;
  if (!data.links.length) return <p className="connections-state" role="status">No connections available.</p>;
  const relations = data.edges.filter(e => [e.source, e.target].includes(selected?.id));
  const label = id => data.nodes.find(n => n.id === identity(id))?.label || identity(id);
  return <>
    <div className="connections-tools"><span>Drag orbs to arrange · select to inspect</span>
      <button onClick={() => graph.current?.zoom(graph.current.zoom() * 1.3, 150)} aria-label="Zoom in">+</button>
      <button onClick={() => graph.current?.zoom(graph.current.zoom() / 1.3, 150)} aria-label="Zoom out">−</button>
      <button onClick={fit}>Fit</button></div>
    <div className="connections-layout">
      <div className="connections-canvas" ref={host} aria-label="Action connections graph">
        <ForceGraph2D ref={graph} width={size.width} height={size.height} graphData={data} maxZoom={2.5}
          backgroundColor="#0b1728" nodeId="id" nodeLabel={node => tooltip(`${node.label} · ${kindName(node.kind)}${node.boards.length ? ' · ' + node.boards.map(b => b.name).join(', ') : ''}`)}
          nodeVal={node => node.id === data.root ? 3 : 1.5} nodeColor={node => colors[node.kind] || '#9bafff'}
          linkColor={edge => edge.scope === 'board' ? '#c4b5fd' : '#7792ac'}
          linkLineDash={edge => edge.scope === 'board' ? [4, 3] : null}
          linkLabel={edge => tooltip(`${edge.relation}${edge.board ? ' · Board: ' + edge.board.name : ' · Activity Graph'}`)}
          linkCurvature={edge => edge.reverse ? -.15 : .15} linkDirectionalArrowLength={edge => edge.direction === 'none' ? 0 : 4}
          linkDirectionalArrowRelPos={1} onNodeClick={setSelected} onBackgroundClick={() => setSelected(null)}
          onNodeDragEnd={node => {node.fx = node.x; node.fy = node.y;}}
          cooldownTicks={100} onEngineStop={() => {if (!fitted.current) {fitted.current = true; fit();}}}
          onRenderFramePost={(ctx, scale) => {
            if (!graph.current) return;
            const origin = graph.current.screen2GraphCoords(0, 0);
            const candidates = data.nodes.map(node => ({...node, ...graph.current.graph2ScreenCoords(node.x, node.y),
              radius: (node.id === data.root ? 9 : 6) * scale, degree:0, preferred:true,
              emphasis:node.id === data.root || node.id === selected?.id}));
            const obstacles = candidates.map(n => ({x:n.x-n.radius,y:n.y-n.radius,w:n.radius*2,h:n.radius*2}));
            const labels = placeLabels(candidates, {...size, zoom:scale, obstacles}, (text, font) => {
              ctx.font = `${font}px system-ui`; return ctx.measureText(text).width;
            });
            for (const box of labels) {
              const x = origin.x + box.x / scale, y = origin.y + box.y / scale;
              ctx.fillStyle = '#0b1728ee'; ctx.fillRect(x, y, box.w / scale, box.h / scale);
              ctx.font = `${box.font / scale}px system-ui`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
              ctx.fillStyle = '#e2e8f0'; ctx.fillText(box.text, x + 6 / scale, y + 12 / scale);
            }
          }}
          nodeCanvasObjectMode={() => 'after'} nodeCanvasObject={(node, ctx, scale) => {
            const r = node.id === data.root ? 9 : 6;
            if (node.id === data.root || node.id === selected?.id) {
              ctx.beginPath(); ctx.arc(node.x, node.y, r + 3, 0, Math.PI * 2);
              ctx.strokeStyle = node.id === selected?.id ? '#f8fafc' : '#f9ca74'; ctx.lineWidth = 1.5 / scale; ctx.stroke();
            }

          }}/>
      </div>
      <aside className="connections-details" aria-label="Read-only orb details">
        <label>Inspect orb<select value={selected?.id || ''} onChange={e => setSelected(data.nodes.find(n => n.id === e.target.value))}>
          <option value="">Select an orb</option>{data.nodes.map(n => <option key={n.id} value={n.id}>{kindName(n.kind)}: {n.label}{n.kind === 'drafts' ? ' · ' + n.boards[0].name : ''}</option>)}
        </select></label>
        {selected ? <><p className="connections-kind">{kindName(selected.kind)}</p><h3>{selected.label}</h3>
          {selected.status && <p>Status: {selected.status}</p>}{selected.date && <p>{selected.date}</p>}
          {selected.boards.length > 0 && <div><h4>{selected.kind === 'drafts' ? 'Originating board' : 'Appears on boards'}</h4><ul>{selected.boards.map(b => <li key={b.id}>{b.name}</li>)}</ul></div>}
          {(selected.body || selected.description) && <p className="connections-body">{selected.body || selected.description}</p>}
          {selected.checklists?.map((list, index) => <div key={list.id || index}><h4>{list.title || 'Checklist'}</h4><ul>{list.items.map((entry, i) => <li key={entry.id || i}>{entry.done ? '☑' : '☐'} {entry.text}</li>)}</ul></div>)}
          <h4>Connections</h4><ul className="connections-relations">{relations.map((edge, index) => <li key={index}>
            <span>{label(edge.source)} {edge.direction === 'none' ? '—' : edge.direction === 'both' ? '↔' : '→'} {label(edge.target)}</span>
            <small>{edge.relation} · {edge.board ? 'Board: ' + edge.board.name : 'Activity Graph'}</small>
          </li>)}</ul></> : <p>Select an orb to read its details.</p>}
      </aside>
    </div>
    <p className="connections-footnote">Dashed links belong to boards. This temporary view resets when closed.</p>
  </>;
}

window.HflActionConnections = {open(item, trigger) {
  activeDialog?.close();
  const dialog = document.createElement('dialog');
  dialog.className = 'agenda-dialog action-connections-dialog';
  dialog.setAttribute('aria-labelledby', 'action-connections-title');
  const header = document.createElement('header'); header.className = 'agenda-dialog-header';
  const heading = document.createElement('h2'); heading.id = 'action-connections-title'; heading.textContent = 'Connections · ' + item.title;
  const close = document.createElement('button'); close.type = 'button'; close.textContent = 'Close'; close.setAttribute('aria-label', 'Close connections');
  close.onclick = () => dialog.close(); header.append(heading, close);
  const content = document.createElement('div'); dialog.append(header, content); document.body.append(dialog);
  const root = createRoot(content); activeDialog = dialog;
  dialog.addEventListener('close', () => {root.unmount(); dialog.remove(); if (activeDialog === dialog) activeDialog = null; if (trigger?.isConnected) trigger.focus();}, {once:true});
  dialog.showModal(); root.render(<Preview item={item}/>);
}};
