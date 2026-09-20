import test from 'node:test';
import assert from 'node:assert/strict';
import {forceSimulation,forceManyBody,forceLink} from 'd3-force-3d';
import {configureDragForces,releaseDragNeighbors,settleDragNodes,dragDamping} from '../src/graph-drag.mjs';
import {motionOffset} from '../src/graph-presets.mjs';

test('drag frees pinned neighbors and physics rearranges colliding notes',()=>{
  const hub={id:'hub',x:0,y:0,fx:0,fy:0,radius:12};
  const a={id:'a',x:100,y:0,fx:100,fy:0,radius:7,manual:true};
  const b={id:'b',x:100,y:1,fx:100,fy:1,radius:7};
  const other={id:'other',x:-200,y:0,fx:-200,fy:0,radius:10};
  const nodes=[hub,a,b,other],edges=[{source:'hub',target:'a'},{source:'hub',target:'b'}];
  const sim=forceSimulation(nodes).stop().force('charge',forceManyBody()).force('link',forceLink(edges).id(n=>n.id));
  configureDragForces({d3Force:(...args)=>sim.force(...args)});
  const released=new Set();releaseDragNeighbors(hub,nodes,edges,released);
  assert.equal(a.fx,undefined);assert.equal(a.manual,false);assert.equal(released.size,2);
  hub.x=hub.fx=160;hub.y=hub.fy=60;
  sim.alpha(1).tick(10);
  assert.ok(Math.hypot(a.x-b.x,a.y-b.y)>30,'collisions separate notes');
  assert.ok(Math.abs((a.x-100)-(b.x-100))>1,'notes rearrange independently');
  assert.equal(other.x,-200);
  sim.tick(90);
  const targets=new Map();settleDragNodes(released,targets);
  assert.equal(a.fx,a.x);assert.equal(targets.get('a').x,a.x);assert.equal(a.vx,0);
  sim.stop();
});

test('settling rejoins each animation at the current position without a jump',()=>{
  for(const mode of ['off','breathing','ripple','drift']){
    const node={id:'note',x:380,y:-120,phase:1.2};
    const targets=new Map([['note',{x:0,y:0,anchor:false}]]);
    const offsetFor=(n,p)=>motionOffset(mode,p,4700,n.phase);
    settleDragNodes([node],targets,offsetFor);
    const target=targets.get('note'),offset=offsetFor(node,target);
    assert.ok(Math.abs(target.x+offset.x-node.x)<1e-6,mode);
    assert.ok(Math.abs(target.y+offset.y-node.y)<1e-6,mode);
  }
});

test('shared children release their other hubs and downstream notes, including cycles',()=>{
  const make=(id,x,y)=>({id,x,y,fx:x,fy:y,radius:7,manual:true});
  const parent=make('parent',0,0),child=make('child',100,0),hub=make('hub',200,0),leaf=make('leaf',280,40),isolated=make('isolated',-300,0);
  const nodes=[parent,child,hub,leaf,isolated];
  const edges=[{source:parent,target:child},{source:'child',target:'hub'},{source:'hub',target:'leaf'},{source:'leaf',target:'child'}];
  const released=new Set();releaseDragNeighbors(parent,nodes,edges,released);
  assert.deepEqual([...released].map(n=>n.id),['child','hub','leaf']);
  for(const n of released){assert.equal(n.fx,undefined);assert.equal(n.fy,undefined);}
  assert.equal(parent.fx,0);assert.equal(isolated.fx,-300);
  const sim=forceSimulation(nodes).stop().force('charge',forceManyBody()).force('link',forceLink(edges).id(n=>n.id));
  configureDragForces({d3Force:(...args)=>sim.force(...args)});
  parent.x=parent.fx=-150;parent.y=parent.fy=120;
  sim.alpha(1).tick(30);
  assert.ok(Math.hypot(hub.x-200,hub.y)>10,'second hub participates in physics');
  assert.ok(Math.hypot(leaf.x-280,leaf.y-40)>10,'downstream note participates too');
  assert.equal(isolated.x,-300);
  const targets=new Map();settleDragNodes(released,targets);
  for(const n of released)assert.equal(targets.get(n.id).x,n.x);
  // Starting a new drag on a previously released hub must keep that hub pinned.
  releaseDragNeighbors(hub,nodes,edges,released);
  assert.ok(!released.has(hub));assert.equal(hub.fx,hub.x);
  sim.stop();
});

test('releasing a 6000-node connected group remains bounded',()=>{
  const nodes=Array.from({length:6000},(_,i)=>({id:String(i),fx:i,fy:0}));
  const edges=nodes.slice(1).map((n,i)=>({source:String(i),target:n.id}));
  const released=new Set(),start=performance.now();
  releaseDragNeighbors(nodes[0],nodes,edges,released);
  assert.equal(released.size,5999);assert.equal(nodes[0].fx,0);
  assert.ok(performance.now()-start<1000);
});

test('successive connections damp movement and local drag preserves existing link lengths',()=>{
  const nodes=Array.from({length:4},(_,i)=>({id:String(i),x:i*400,y:0,fx:i*400,fy:0,radius:7}));
  const edges=nodes.slice(1).map((n,i)=>({source:String(i),target:n.id}));
  const sim=forceSimulation(nodes).stop().force('charge',forceManyBody()).force('link',forceLink(edges).id(n=>n.id));
  releaseDragNeighbors(nodes[0],nodes,edges,new Set());
  configureDragForces({d3Force:(...args)=>sim.force(...args)},true);
  assert.equal(sim.force('link').distance()(edges[0]),400);
  assert.equal(sim.force('center'),undefined);
  for(const n of nodes)n.vx=n.vy=100;
  const damp=dragDamping();damp.initialize(nodes);damp();
  assert.ok(Math.abs(Math.hypot(nodes[1].vx,nodes[1].vy)-24)<1e-8);
  assert.ok(Math.abs(Math.hypot(nodes[2].vx,nodes[2].vy)-12)<1e-8);
  assert.ok(Math.abs(Math.hypot(nodes[3].vx,nodes[3].vy)-6)<1e-8);
  for(const n of nodes)n.vx=n.vy=0;
  sim.alpha(1).tick(30);
  assert.ok(Math.abs(nodes[3].x-1200)<20,'distant node does not collapse toward old layout centers');
  sim.stop();
});


test('dense preset drag keeps every affected orb within its movement budget',()=>{
  const nodes=Array.from({length:1000},(_,i)=>({id:String(i),x:(i%40)*12,y:Math.floor(i/40)*12,radius:i%10?5:16}));
  for(const n of nodes){n.fx=n.x;n.fy=n.y;}
  const edges=nodes.slice(1).map((n,i)=>({source:String(Math.floor(i/3)),target:n.id}));
  const sim=forceSimulation(nodes).stop().force('charge',forceManyBody()).force('link',forceLink(edges).id(n=>n.id));
  const released=new Set();releaseDragNeighbors(nodes[0],nodes,edges,released);
  configureDragForces({d3Force:(...args)=>sim.force(...args)},true);
  nodes[0].x=nodes[0].fx=150;nodes[0].y=nodes[0].fy=80;
  sim.alpha(1);
  let maxStep=0,maxTravel=0;
  for(let tick=0;tick<180;tick++){
    const before=nodes.map(n=>({x:n.x,y:n.y}));sim.tick();
    for(const n of released){
      const step=Math.hypot(n.x-before[n.index].x,n.y-before[n.index].y);
      const travel=Math.hypot(n.x-n.dragOrigin.x,n.y-n.dragOrigin.y);
      maxStep=Math.max(maxStep,step);maxTravel=Math.max(maxTravel,travel);
      assert.ok(step<=24*n.dragWeight+.001,'no instantaneous outward jump');
      assert.ok(travel<=(Math.hypot(150,80)+120)*n.dragWeight+.001,'propagation remains local');
    }
  }
  console.log(`Dense drag: largest step ${maxStep.toFixed(2)}, largest displacement ${maxTravel.toFixed(2)}`);
  sim.stop();
});


test('long parent drags carry children prominently, attenuate by hop, and reverse smoothly',()=>{
  const nodes=Array.from({length:5},(_,i)=>({id:String(i),x:i*100,y:0,fx:i*100,fy:0,radius:7}));
  const edges=nodes.slice(1,4).map((n,i)=>({source:String(i),target:n.id}));
  const sim=forceSimulation(nodes).stop().velocityDecay(.2).force('charge',forceManyBody()).force('link',forceLink(edges).id(n=>n.id));
  const released=new Set();releaseDragNeighbors(nodes[0],nodes,edges,released);
  configureDragForces({d3Force:(...args)=>sim.force(...args)},true);
  nodes[0].x=nodes[0].fx=1000;nodes[0].y=nodes[0].fy=300;
  sim.alpha(1).tick(120);
  const moves=nodes.slice(1,4).map(n=>Math.hypot(n.x-n.dragOrigin.x,n.y-n.dragOrigin.y));
  assert.ok(moves[0]>750,'direct children follow most of a long drag, beyond the old leash');
  assert.ok(moves[1]>300&&moves[1]<moves[0]*.7,'shared hubs follow less');
  assert.ok(moves[2]<moves[1]*.7,'distant propagation fades');
  assert.equal(nodes[4].x,400,'disconnected nodes remain stationary');
  nodes[0].x=nodes[0].fx=-800;nodes[0].y=nodes[0].fy=-300;
  for(let i=0;i<150;i++){
    const before=nodes.map(n=>({x:n.x,y:n.y}));sim.alpha(.5).tick();
    for(const n of released)assert.ok(Math.hypot(n.x-before[n.index].x,n.y-before[n.index].y)<=24*n.dragWeight+.001,'no jump on reversal');
  }
  assert.ok(nodes[1].x<-400,'children follow in the new direction');
  sim.alpha(1).tick(300);
  assert.ok(Math.hypot(nodes[1].vx,nodes[1].vy)<.1,'motion settles without jitter');
  sim.stop();
});
