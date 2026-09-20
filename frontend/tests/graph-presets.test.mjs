import test from 'node:test';
import assert from 'node:assert/strict';
import {randomizePresetNodes,presetLayout,presetFitPoints,timelineFitPoints,motionOffset,phaseFor} from '../src/graph-presets.mjs';
const nodes=[
  {id:'daily:2026-09-01',kind:'daily',label:'September 1'},
  {id:'daily:2026-09-20',kind:'daily',label:'September 20'},
  ...['sources','people','tools','companies'].flatMap(kind=>[0,1].map(i=>({id:kind+i,kind,label:kind+i,visibleDegree:10-i*9}))),
  ...Array.from({length:100},(_,i)=>({id:'entry'+i,kind:'entries',label:'Activity '+i}))];
const edges=nodes.filter(n=>n.kind==='entries').flatMap((n,i)=>[
  {source:n.id,target:'sources'+i%2},{source:n.id,target:'people'+i%2},
  {source:n.id,target:'tools'+i%2},{source:n.id,target:'companies'+i%2},
  {source:n.id,target:'daily:2026-09-'+(i%2?'01':'20')}]);
test('timeline preserves ascending dates on a straight horizontal axis',()=>{
  const p=presetLayout(nodes,edges,'timeline').positions;
  assert.equal(p.size,nodes.length);assert.equal(p.get('daily:2026-09-01').y,0);
  assert.ok(p.get('daily:2026-09-20').x>p.get('daily:2026-09-01').x);
});

test('dense selected orb clusters have randomized final positions and clear spacing',()=>{
  const sample=Array.from({length:80},(_,i)=>({id:'person'+i,kind:'people',label:'Person '+i,radius:12+i%15,visibleDegree:80-i}));
  for(const seed of [1,2,3,4,5]){
    const points=presetLayout(sample,[],'people',seed).positions;
    for(let i=0;i<sample.length;i++)for(let j=i+1;j<sample.length;j++){
      const a=points.get(sample[i].id),b=points.get(sample[j].id);
      assert.ok(Math.hypot(a.x-b.x,a.y-b.y)>=sample[i].radius+sample[j].radius+12);
    }
  }
});

test('preset preparation randomizes every orb and clears previous drag state before sorting',()=>{
  const dirty=nodes.map(n=>({...n,x:1e8,y:-1e8,fx:1e8,fy:-1e8,vx:999,vy:-999,manual:true,dragOrigin:{x:1,y:2},dragWeight:.1}));
  randomizePresetNodes(dirty,42);
  for(const n of dirty){
    assert.ok(Number.isFinite(n.x)&&Math.abs(n.x)<10000);
    assert.equal(n.fx,n.x);assert.equal(n.fy,n.y);
    assert.equal(n.vx,0);assert.equal(n.vy,0);assert.equal(n.manual,false);
    assert.equal(n.dragOrigin,undefined);assert.equal(n.dragWeight,undefined);
  }
  const next=structuredClone(dirty);randomizePresetNodes(next,43);
  for(let i=0;i<dirty.length;i++)assert.notEqual(dirty[i].x,next[i].x);
  for(const preset of ['sources','timeline','people','tools','companies']){
    const prepared=presetLayout(dirty,edges,preset,42),fresh=presetLayout(nodes,edges,preset,42);
    assert.deepEqual(prepared.positions,fresh.positions);
  }
});

for(const preset of ['people','tools','companies'])test(preset+' frames its orb cluster without outer sources or unrelated notes',()=>{
  const positions=presetLayout(nodes,edges,preset).positions;
  const points=presetFitPoints(nodes,positions,preset);
  assert.deepEqual(points,nodes.filter(n=>n.kind===preset).map(n=>positions.get(n.id)));
  const before=structuredClone(points);
  for(const n of nodes)if(n.kind!==preset)positions.set(n.id,{x:100000,y:-100000});
  assert.deepEqual(presetFitPoints(nodes,positions,preset),before);
  positions.set(preset+'0',{x:120,y:240});
  assert.ok(presetFitPoints(nodes,positions,preset).some(p=>p.x===120&&p.y===240));
});

test('preset framing handles absent clusters and keeps source and timeline framing',()=>{
  const positions=presetLayout(nodes,edges,'sources').positions;
  assert.deepEqual(presetFitPoints(nodes,positions,'sources'),nodes.filter(n=>n.kind==='sources').map(n=>positions.get(n.id)));
  assert.deepEqual(presetFitPoints(nodes.filter(n=>n.kind!=='people'),positions,'people'),[...positions.values()]);
  assert.deepEqual(presetFitPoints([],new Map(),'people'),[]);
  const timeline=presetLayout(nodes,edges,'timeline').positions;
  assert.deepEqual(presetFitPoints(nodes,timeline,'timeline'),timelineFitPoints(nodes,timeline));
});
test('sources cluster centrally with the largest source at the center',()=>{
  const sample=nodes.map(n=>({...n,radius:n.id==='sources1'?40:12}));
  const a=presetLayout(sample,edges,'sources'),b=presetLayout([...sample].reverse(),edges,'sources');
  for(const n of sample)assert.deepEqual(a.positions.get(n.id),b.positions.get(n.id));
  assert.equal(Math.hypot(a.positions.get('sources1').x,a.positions.get('sources1').y),0);
});
for(const kind of ['people','tools','companies'])test(kind+' centers the most connected target',()=>{
  const p=presetLayout(nodes,edges,kind).positions;
  assert.equal(Math.hypot(p.get(kind+'0').x,p.get(kind+'0').y),0);
  assert.ok(Math.hypot(p.get(kind+'1').x,p.get(kind+'1').y)>0);
});
test('missing targets fall back without dropping nodes; empty graphs are finite',()=>{
  const result=presetLayout(nodes.filter(n=>n.kind!=='people'),edges,'people');
  assert.equal(result.preset,'sources');assert.match(result.notice,/No people/);
  assert.equal(presetLayout([],[],'timeline').positions.size,0);
  for(const p of result.positions.values())assert.ok(Number.isFinite(p.x)&&Number.isFinite(p.y));
});

test('new layout seeds scatter final orb positions but preserve the central hub and source arrangements',()=>{
  for(const preset of ['sources','timeline','people','tools','companies']){
    const a=presetLayout(nodes,edges,preset,1).positions;
    const b=presetLayout(nodes,edges,preset,2).positions;
    const repeat=presetLayout([...nodes].reverse(),edges,preset,1).positions;
    for(const n of nodes){
      assert.deepEqual(a.get(n.id),repeat.get(n.id));
      if((preset==='timeline'&&['daily','sources'].includes(n.kind))||Math.hypot(a.get(n.id).x,a.get(n.id).y)===0)assert.deepEqual(a.get(n.id),b.get(n.id));
      else assert.notDeepEqual(a.get(n.id),b.get(n.id));
      if(n.kind==='entries')assert.notDeepEqual(a.get(n.id),b.get(n.id));
    }
  }
});

test('timeline note clouds stay near their dates without repeated columns or rows',()=>{
  const p=presetLayout(nodes,edges,'timeline',12).positions;
  const entries=nodes.filter(n=>n.kind==='entries');
  const xs=new Set(),ys=new Set();
  for(const n of entries){
    const date=edges.find(e=>e.source===n.id&&e.target.startsWith('daily:')).target;
    const point=p.get(n.id),anchor=p.get(date);
    assert.ok(Math.abs(point.x-anchor.x)<=65);
    xs.add(Math.round(point.x*100));ys.add(Math.round(point.y*100));
  }
  assert.ok(xs.size>entries.length*.9);assert.ok(ys.size>entries.length*.9);
});

test('timeline spreads sources chronologically along the axis, above and below it',()=>{
  const p=presetLayout(nodes,edges,'timeline').positions;
  // sources1 is linked to September 1; sources0 is linked to September 20.
  assert.equal(p.get('sources1').x,p.get('daily:2026-09-01').x);
  assert.equal(p.get('sources0').x,p.get('daily:2026-09-20').x);
  assert.equal(p.get('sources1').y,-125);assert.equal(p.get('sources0').y,125);
  const reversed=presetLayout([...nodes].reverse(),[...edges].reverse(),'timeline').positions;
  for(const n of nodes.filter(n=>n.kind==='sources'))assert.deepEqual(p.get(n.id),reversed.get(n.id));
});

test('timeline separates sources even with one date and handles a single source',()=>{
  const day=nodes[0],sources=Array.from({length:6},(_,i)=>({id:'source'+i,kind:'sources',label:'Source '+i}));
  const p=presetLayout([day,...sources],[],'timeline').positions;
  const xs=sources.map(n=>p.get(n.id).x);
  for(let i=1;i<xs.length;i++)assert.ok(xs[i]-xs[i-1]>=90);
  const single=presetLayout([day,sources[0]],[],'timeline').positions.get('source0');
  assert.equal(single.x,0);assert.equal(single.y,-125);
});

for(const kind of ['people','tools','companies'])test(kind+' randomizes sources in a nearer peripheral band',()=>{
  const sample=[...nodes,...Array.from({length:4},(_,i)=>({id:'outer'+i,kind:'sources',label:'Outer '+i}))];
  const p=presetLayout(sample,edges,kind,1).positions;
  const reversed=presetLayout([...sample].reverse(),edges,kind,1).positions;
  const next=presetLayout(sample,edges,kind,2).positions;
  const radii=sample.filter(n=>n.kind==='sources').map(n=>{
    assert.deepEqual(p.get(n.id),reversed.get(n.id));
    assert.notDeepEqual(p.get(n.id),next.get(n.id));
    return Math.hypot(p.get(n.id).x,p.get(n.id).y);
  });
  assert.ok(new Set(radii).size>1);
  assert.ok(Math.min(...radii)>Math.hypot(p.get(kind+'1').x,p.get(kind+'1').y));
  assert.ok(Math.max(...radii)<Math.sqrt(sample.length)*25);
});

test('motion is bounded, deterministic and never moves fixed timeline anchors',()=>{
  for(const mode of ['off','breathing','ripple','drift'])for(let t=0;t<48000;t+=100){
    const offset=motionOffset(mode,{x:100,y:50},t,phaseFor('one'));
    assert.ok(Math.hypot(offset.x,offset.y)<=11);
    assert.deepEqual(motionOffset(mode,{x:100,y:50},t,0,true),{x:0,y:0});
  }
});
test('6000-node layout stays within a bounded computation budget',()=>{
  const large=[...nodes,...Array.from({length:5890},(_,i)=>({id:'extra'+i,kind:'entries',label:'Extra'}))];
  const links=[...edges,...large.filter(n=>n.id.startsWith('extra')).map(n=>({source:n.id,target:'sources0'}))];
  const start=performance.now();
  for(const preset of ['timeline','sources','people','tools','companies'])assert.equal(presetLayout(large,links,preset).positions.size,large.length);
  const elapsed=performance.now()-start;console.log(`Five 6000-node layouts: ${elapsed.toFixed(1)}ms`);
  assert.ok(elapsed<2000);
});

test('timeline fits the latest available 14 days without removing older dates',()=>{
  const dates=['2020-01-01','2026-09-06','2026-09-07','2026-09-20'].map(date=>({id:'daily:'+date,kind:'daily',label:date}));
  const positions=presetLayout(dates,[],'timeline').positions;
  const points=timelineFitPoints(dates,positions);
  assert.equal(positions.size,4);
  assert.equal(points.length,4);
  assert.equal(Math.min(...points.map(p=>p.x)),positions.get('daily:2026-09-07').x-60);
  assert.equal(Math.max(...points.map(p=>p.x)),positions.get('daily:2026-09-20').x+60);
});


test('Sources reserves its center for all source orbs regardless of activity count',()=>{
  const sources=Array.from({length:24},(_,i)=>({id:'s'+i,kind:'sources',label:'Source '+i,radius:12+i*2}));
  const others=Array.from({length:2900},(_,i)=>({id:'e'+i,kind:i%2?'entries':'tools',label:'Other '+i,radius:8}));
  for(const seed of [1,2,3]){
    const sparse=presetLayout(sources,[],'sources',seed).positions;
    const dense=presetLayout([...sources,...others],[],'sources',seed).positions;
    for(const n of sources)assert.deepEqual(dense.get(n.id),sparse.get(n.id),'activity count must not expand the source cluster');
    const edge=Math.max(...sources.map(n=>Math.hypot(dense.get(n.id).x,dense.get(n.id).y)+n.radius));
    for(const n of others)assert.ok(Math.hypot(dense.get(n.id).x,dense.get(n.id).y)-n.radius>=edge+99,'other types stay outside');
    for(let i=0;i<sources.length;i++)for(let j=i+1;j<sources.length;j++){
      const a=dense.get(sources[i].id),b=dense.get(sources[j].id);
      assert.ok(Math.hypot(a.x-b.x,a.y-b.y)>=sources[i].radius+sources[j].radius+12);
    }
    assert.equal(presetFitPoints([...sources,...others],dense,'sources').length,sources.length);
  }
});
