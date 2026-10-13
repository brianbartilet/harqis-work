import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ForceGraph2D from 'react-force-graph-2d';
import {GraphIcon} from './graph-icons.jsx';
import {placeLabels} from './graph-labels.mjs';

const colors = {actions:'#fb8ca6', ideas:'#f9ca74', drafts:'#c4b5fd', boards:'#93c5fd',
  goals:'#a7f3d0', entries:'#77dcf5', daily:'#95a7c3', people:'#ffbd91', tools:'#70edbd'};
const kindName = kind => ({actions:'Action', ideas:'Idea', drafts:'Thought', boards:'Board',
  goals:'Goal', entries:'Entry', daily:'Date', companies:'Organization'}[kind] || kind);
const identity = node => typeof node === 'object' ? node.id : node;
const statusLabel = status => ({open:'In Review',active:'Ready',suggested:'Available'}[status] || status.replace(/[_-]+/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase()));
const tooltip = text => {const span = document.createElement('span'); span.textContent = text; return span;};
let activeDialog;

const relationChoices = [
  ['depends-on','depends on',false], ['depends-on','dependency for',true],
  ['related-to','relates to',false], ['blocked-by','blocked by',false], ['blocked-by','blocks',true],
  ['cloned-from','cloned from',false], ['cloned-from','cloned to',true],
  ['promoted-from','promoted from',false], ['promoted-from','promoted to',true],
  ['created-from','created from',false], ['created-from','created to',true],
];
const editableRelations = new Set(relationChoices.map(([relation]) => relation));
const connectionLabel = (edge, from) => relationChoices.find(([relation,,reverse]) => relation === edge.relation && (relation === 'related-to' || reverse === (edge.target === from)))?.[1] || edge.relation;
const changed = () => {
  window.dispatchEvent(new CustomEvent('hfl:ideas-updated', {detail:{refreshShared:true}}));
  window.dispatchEvent(new Event('hfl:actions-updated'));
};
async function connectionRequest(path, body, signal) {
  const response = await fetch('/hfl-corpus/timeline/ideas/' + path, {
    method:body ? 'POST' : 'GET', signal:signal ? AbortSignal.any([signal,AbortSignal.timeout(45000)]) : AbortSignal.timeout(45000), cache:'no-store',
    headers:body ? {'Content-Type':'application/json', 'X-CSRF-Token':document.querySelector('[data-input-editor]')?.dataset.csrf || ''} : {},
    ...(body ? {body:JSON.stringify(body)} : {}),
  });
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Connection could not be saved. Please try again.');
  return data;
}

function ConnectionPicker({item, edge, initialLabel, close}) {
  const root = (item.kind === 'idea' ? 'idea:' : 'action:') + item.id;
  const [query,setQuery] = useState(''), [offset,setOffset] = useState(0), [data,setData] = useState(null);
  const [target,setTarget] = useState(edge ? (edge.source === root ? edge.target : edge.source) : '');
  const [targetLabel,setTargetLabel] = useState(initialLabel || '');
  const [choice,setChoice] = useState(Math.max(0, relationChoices.findIndex(([r,,reverse]) => edge && r === edge.relation && (r === 'related-to' || reverse === (edge.target === root)))));
  const [error,setError] = useState(''), [busy,setBusy] = useState(false), [attempt,setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let live = true;
    setData(null); setError('');
    const timer = setTimeout(() => connectionRequest('item-connection-options?' + new URLSearchParams({query,offset}), null, controller.signal)
      .then(result => {if(live)setData(result);}).catch(e => {if(live && e.name !== 'AbortError')setError(e.message);}), 250);
    return () => {live=false;clearTimeout(timer);controller.abort();};
  }, [query,offset,attempt]);
  async function save(operation) {
    setBusy(true); setError('');
    const [relation,,reverse] = relationChoices[choice];
    const replacement = {source:reverse ? target : root, target:reverse ? root : target, relation};
    try {
      await connectionRequest('item-connections', {operation, edge:edge || replacement, ...(edge ? {revision:edge.revision,replacement} : {})});
      changed(); close();
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  return <div className="connection-picker">
    <div className="connection-picker-fields">
    <label>Search ideas and actions<input type="search" autoFocus value={query} maxLength={200} placeholder="Title or item ID" onChange={e=>{setQuery(e.target.value);setOffset(0);}}/></label>
    <label>Connection type<select value={choice} onChange={e=>setChoice(Number(e.target.value))}>{relationChoices.map(([,label],i)=><option key={i} value={i}>{label}</option>)}</select></label>
    </div>
    <p className="connection-selected" role="status">{target ? 'Selected: ' + targetLabel : 'Select an idea or action.'}</p>
    <div className="idea-choices" aria-label="Connection search results">
      {!data && !error && <p role="status">Loading…</p>}
      {data?.nodes.filter(n=>n.id !== root).map(node=><button type="button" className="idea-attach-choice" key={node.id} aria-pressed={target===node.id} disabled={busy} onClick={()=>{setTarget(node.id);setTargetLabel(node.label);}}>
        <span className="connection-card-pills"><span className="connection-type-pill" data-kind={node.kind}>{node.kind==='ideas'?'Idea':'Action'}</span><span className="connection-status-pill" data-status={node.status}>{statusLabel(node.status)}</span></span>
        <span className="idea-attach-title">{node.label}</span>
        <span className="connection-card-description">{node.description || 'No description yet.'}</span><small title={node.object_id}>{node.object_id}</small>
      </button>)}
      {data && !data.nodes.some(n=>n.id!==root) && <p>No matching ideas or actions.</p>}
    </div>
    <nav className="connection-pagination" aria-label="Connection results pages">{offset>0 && <button type="button" disabled={busy} onClick={()=>setOffset(offset-50)}>Previous</button>}{data?.has_more && <button type="button" disabled={busy} onClick={()=>setOffset(offset+50)}>Next</button>}</nav>
    {error && <p role="alert">{error} <button type="button" onClick={()=>setAttempt(a=>a+1)}>Retry search</button></p>}
    <footer><button type="button" disabled={busy} onClick={close}>Cancel</button>{edge && <button type="button" disabled={busy} onClick={()=>save('remove')}>Remove connection</button>}<button type="button" disabled={busy || !target} onClick={()=>save(edge?'update':'create')}>{busy?'Saving…':'Save connection'}</button></footer>
  </div>;
}

function openConnectionPicker(item, edge, trigger, initialLabel='') {
  const dialog=document.createElement('dialog'); dialog.className='idea-dialog agenda-dialog connection-picker-dialog';
  const title=document.createElement('h2');title.id='connection-title-'+crypto.randomUUID();title.textContent=edge?'Edit connection':'Add connection';dialog.setAttribute('aria-labelledby',title.id);
  const host=document.createElement('div');dialog.append(title,host);document.body.append(dialog);
  const root=createRoot(host);dialog.addEventListener('close',()=>{root.unmount();dialog.remove();trigger?.focus();},{once:true});
  dialog.showModal();root.render(<ConnectionPicker item={item} edge={edge} initialLabel={initialLabel} close={()=>dialog.close()}/>);
}

function Preview({item, editable=false}) {
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
        const collection = item.kind === 'daily' ? 'dates' : item.kind === 'idea' ? 'ideas' : 'actions';
        const response = await fetch('/hfl-corpus/timeline/ideas/' + collection + '/' + encodeURIComponent(item.id) + '/connections',
          {cache:'no-store', signal:controller.signal});
        if (!response.ok) throw Error(response.status === 404 ? 'This object is unavailable or protected.' : 'Connections could not load. Please try again.');
        const result = await response.json();
        for (const node of result.nodes) {
          const degree = result.edges.filter(edge => edge.source === node.id || edge.target === node.id).length;
          node.radius = node.kind === 'entries' ? 7 : 10 + 4 * Math.log2(1 + degree);
        }
        const links = result.edges.flatMap(edge => [{...edge}, ...(edge.direction === 'both'
          ? [{...edge, source:edge.target, target:edge.source, reverse:true}] : [])]);
        if (live) {setData({...result, links}); setSelected(result.nodes.find(n => n.id === result.root));}
      } catch (failure) {
        if (live) setError(failure.name === 'AbortError' ? 'Loading connections timed out. Please try again.' : failure.message);
      } finally {clearTimeout(timeout);}
    })();
    return () => {live = false; clearTimeout(timeout); controller.abort();};
  }, [item.id, item.kind, attempt]);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setSize({width:entry.contentRect.width, height:entry.contentRect.height}));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, [data]);
  useEffect(() => {
    const refresh = () => setAttempt(a => a + 1);
    window.addEventListener('hfl:ideas-updated', refresh);
    return () => window.removeEventListener('hfl:ideas-updated', refresh);
  }, []);
  const fit = () => graph.current?.zoomToFit(250, 65, () => true);
  if (error) return <div className="connections-state" role="alert"><p>{error}</p><button type="button" onClick={() => setAttempt(a => a + 1)}>Retry</button></div>;
  if (!data) return <div className="connections-loading" role="status" aria-live="polite" aria-busy="true"><span className="connections-loading-spinner" aria-hidden="true"/><strong>Finding related items</strong><span>Your connections graph will appear here.</span></div>;
  if (!data.links.length && !editable) return <div className="connections-state connections-empty" role="status">
    <h3>No connections yet</h3>
    <p>{item.kind === 'daily' ? 'Related activity will appear here when it is connected to this date.' : `Add this ${item.kind === 'idea' ? 'idea' : 'action'} to a board to organize it alongside related ideas, thoughts, and actions.`}</p>
  </div>;
  const relations = data.edges.filter(e => [e.source, e.target].includes(selected?.id));
  const label = id => data.nodes.find(n => n.id === identity(id))?.label || identity(id);
  return <>
    <div className="connections-layout">
      <div className="connections-canvas" ref={host} aria-label={item.kind === 'daily' ? 'Date connections graph' : item.kind === 'idea' ? 'Idea connections graph' : 'Action connections graph'} tabIndex={0}
        onKeyDown={event => {
          if (!['ArrowRight', 'ArrowLeft'].includes(event.key)) return;
          event.preventDefault();
          const index = data.nodes.findIndex(node => node.id === selected?.id);
          setSelected(data.nodes[(index + (event.key === 'ArrowRight' ? 1 : data.nodes.length - 1)) % data.nodes.length]);
        }}>
        <div className="connections-tools" role="group" aria-label="Graph controls">
          <button type="button" onClick={() => graph.current?.zoom(graph.current.zoom() * 1.3, 150)} aria-label="Zoom in" title="Zoom in"><GraphIcon name="plus"/></button>
          <button type="button" onClick={() => graph.current?.zoom(graph.current.zoom() / 1.3, 150)} aria-label="Zoom out" title="Zoom out"><GraphIcon name="minus"/></button>
          <button type="button" onClick={fit} aria-label="Fit" title="Fit graph"><GraphIcon name="fit"/></button>
        </div>
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
              radius: node.radius, degree:0, preferred:true,
              emphasis:node.id === data.root || node.id === selected?.id}));
            const obstacles = [{x:size.width-130,y:0,w:130,h:48}, ...candidates.map(n => ({x:n.x-n.radius,y:n.y-n.radius,w:n.radius*2,h:n.radius*2}))];
            const labels = placeLabels(candidates, {...size, zoom:scale, obstacles}, (text, font) => {
              ctx.font = `${font}px system-ui`; return ctx.measureText(text).width;
            });
            for (const box of labels) {
              const x = origin.x + box.x / scale, y = origin.y + box.y / scale;
              const ink = colors[box.node.kind] || '#9bafff';
              ctx.fillStyle = box.node.emphasis ? '#142a42f5' : '#0a1728ee'; ctx.beginPath();
              ctx.roundRect(x, y, box.w / scale, box.h / scale, 5 / scale); ctx.fill();
              ctx.strokeStyle = ink + (box.node.emphasis ? '90' : '30'); ctx.lineWidth = .6 / scale; ctx.stroke();
              ctx.font = `500 ${box.font / scale}px system-ui`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
              ctx.fillStyle = box.node.emphasis ? '#ffffff' : '#d9e9fa'; ctx.fillText(box.text, x + 6 / scale, y + 12 / scale);
            }
          }}
          nodePointerAreaPaint={(node, ink, ctx) => {
            ctx.fillStyle = ink; ctx.beginPath(); ctx.arc(node.x, node.y, (node.radius + 4) / (graph.current?.zoom() || 1), 0, 2 * Math.PI); ctx.fill();
          }}
          nodeCanvasObject={(node, ctx, globalScale) => {
            if (!Number.isFinite(node.x) || !Number.isFinite(node.y) || globalScale <= 0) return;
            const radius = node.radius / globalScale, ink = colors[node.kind] || '#9bafff';
            const emphasis = node.id === data.root || node.id === selected?.id;
            ctx.save();
            const glow=ctx.createRadialGradient(node.x,node.y,0,node.x,node.y,(emphasis?30:18)/globalScale);
            glow.addColorStop(0,ink+(emphasis?'75':'35'));glow.addColorStop(1,ink+'00');
            ctx.fillStyle=glow;ctx.beginPath();ctx.arc(node.x,node.y,(emphasis?30:18)/globalScale,0,2*Math.PI);ctx.fill();
            const fill=ctx.createRadialGradient(node.x-radius*.3,node.y-radius*.4,0,node.x,node.y,radius*1.6);
            fill.addColorStop(0,'#effbff');fill.addColorStop(.3,ink);fill.addColorStop(1,ink+'70');
            ctx.beginPath();ctx.arc(node.x,node.y,radius,0,2*Math.PI);ctx.fillStyle=fill;ctx.fill();
            ctx.strokeStyle=ink;ctx.lineWidth=.8/globalScale;ctx.stroke();
            if(data.nodes.length<=35&&node.kind!=='entries'){
              const mark=node.kind==='people'?node.label.slice(0,1):node.kind==='tools'?'⌘':'◇';
              ctx.font=`600 ${14/globalScale}px system-ui`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle='#10263c';ctx.fillText(mark,node.x,node.y);ctx.textAlign='left';
            }
            if(emphasis){ctx.beginPath();ctx.arc(node.x,node.y,radius+5/globalScale,0,2*Math.PI);ctx.strokeStyle=ink+'aa';ctx.lineWidth=1/globalScale;ctx.stroke();}
            ctx.restore();
          }}/>

      </div>
      <aside className="connections-details" aria-label="Read-only orb details">
        {selected ? <><p className="connections-kind">{kindName(selected.kind)}</p><h3>{selected.label}</h3>
          {selected.status && <div className="agenda-card-meta"><span className="action-status connections-status" data-status={selected.status} aria-label={'Status: ' + statusLabel(selected.status)}>{statusLabel(selected.status)}</span></div>}{selected.date && <p>{selected.date}</p>}
          {selected.boards.length > 0 && <div><h4>{selected.kind === 'drafts' ? 'Originating board' : 'Appears on boards'}</h4><ul>{selected.boards.map(b => <li key={b.id}><a href={'/hfl-corpus/graph?' + new URLSearchParams({board:b.id})}>{b.name}</a></li>)}</ul></div>}
          {(selected.body || selected.description) && <div className="connections-body markdown-body" dangerouslySetInnerHTML={{__html:selected.body_html}}/>}
          {selected.checklists?.map((list, index) => <div key={list.id || index}><h4>{list.title || 'Checklist'}</h4><ul>{list.items.map((entry, i) => <li key={entry.id || i}>{entry.done ? '☑' : '☐'} {entry.text}</li>)}</ul></div>)}
          <h4>Connections</h4><ul className="connections-relations">{relations.map((edge, index) => <li key={index}>
            <span>{editableRelations.has(edge.relation) ? `${label(selected.id)} ${connectionLabel(edge,selected.id)} ${label(edge.source === selected.id ? edge.target : edge.source)}` : <>{label(edge.source)} {edge.direction === 'none' ? '—' : edge.direction === 'both' ? '↔' : '→'} {label(edge.target)}</>}</span>
            <small>{connectionLabel(edge,selected.id)} · {edge.board ? 'Board: ' + edge.board.name : 'Activity Graph'}</small>
            {editable && edge.manual && edge.scope==='shared' && editableRelations.has(edge.relation) && [edge.source,edge.target].includes(data.root) && <button type="button" onClick={event=>openConnectionPicker(item,edge,event.currentTarget,label(edge.source===data.root?edge.target:edge.source))}>Edit connection</button>}
          </li>)}</ul></> : <p>Select an orb to read its details.</p>}
      </aside>
    </div>
    <p className="connections-footnote">Dashed links belong to boards. This temporary view resets when closed.</p>
  </>;
}

function Sidebar({getItem}) {
  const [expanded,setExpanded]=useState(false), [,refresh]=useState(0);
  useEffect(()=>{const update=()=>refresh(n=>n+1);window.addEventListener('hfl:ideas-updated',update);window.addEventListener('hfl:actions-updated',update);return()=>{window.removeEventListener('hfl:ideas-updated',update);window.removeEventListener('hfl:actions-updated',update);};},[]);
  const item=getItem();
  return <details className="action-triage" open={expanded} onToggle={event=>setExpanded(event.currentTarget.open)}><summary><span>Connections</span><button type="button" disabled={!item?.id} title={item?.id?'Add a connection':'Save this item to add connections'} onClick={event=>{event.preventDefault();event.stopPropagation();openConnectionPicker(item,null,event.currentTarget);}}>Add</button></summary>
    {expanded && (item?.id ? <Preview item={item} editable/> : <p>Save this item to add connections.</p>)}
  </details>;
}
window.HflActionConnections = {attach(dialog,getItem) {
  dialog._connectionsCleanup?.();
  const form=dialog.querySelector('form'), body=form.querySelector('.agenda-form-body');
  if(!body)return;
  dialog.classList.add('has-connections-sidebar');
  const aside=document.createElement('aside');aside.className='item-connections-sidebar';aside.setAttribute('aria-label','Item integrations');body.after(aside);
  const root=createRoot(aside);root.render(<Sidebar getItem={getItem}/>);
  const cleanup=()=>{root.unmount();aside.remove();dialog.removeEventListener('close',cleanup);delete dialog._connectionsCleanup;};
  dialog._connectionsCleanup=cleanup;dialog.addEventListener('close',cleanup,{once:true});
}, open(item, trigger) {
  activeDialog?.close();
  const dialog = document.createElement('dialog');
  dialog.className = 'agenda-dialog action-connections-dialog';
  dialog.setAttribute('aria-labelledby', 'action-connections-title');
  const header = document.createElement('header'); header.className = 'agenda-dialog-header';
  const heading = document.createElement('h2'); heading.id = 'action-connections-title'; heading.textContent = 'Connections · ' + item.title;
  const close = document.createElement('button'); close.type = 'button'; close.textContent = 'Close'; close.setAttribute('aria-label', 'Close connections');
  close.onclick = () => dialog.close(); header.append(heading, close);
  if (item.kind !== 'daily') {
    const toolbar = document.createElement('div'); toolbar.className = 'connections-actions';
    const hint = document.createElement('p'); hint.textContent = `Explore related activity and the boards this ${item.kind === 'idea' ? 'idea' : 'action'} belongs to.`;
    const add = document.createElement('button'); add.type = 'button'; add.textContent = 'Add to a board';
    add.onclick = () => window.HflIdeas.addToBoard(item.kind === 'idea' ? 'idea' : 'actionable', item);
    toolbar.append(hint, add); dialog.append(header, toolbar);
  } else dialog.append(header);
  const content = document.createElement('div'); content.className = 'connections-content'; dialog.append(content); document.body.append(dialog);
  const root = createRoot(content); activeDialog = dialog;
  dialog.addEventListener('close', () => {root.unmount(); dialog.remove(); if (activeDialog === dialog) activeDialog = null; if (trigger?.isConnected) trigger.focus();}, {once:true});
  dialog.showModal(); root.render(<Preview item={item}/>);
}};

document.addEventListener('click', event => {
  const trigger = event.target.closest('[data-date-connections]');
  if (!trigger) return;
  window.HflActionConnections.open({id:trigger.dataset.dateConnections, kind:'daily', title:trigger.dataset.dateConnections}, trigger);
});
