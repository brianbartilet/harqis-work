import test from 'node:test';
import assert from 'node:assert/strict';
import {releaseFleetNeighbors} from './fleet-drag.mjs';
const fixture=()=>{
 const nodes=[['owner','owner'],['agent','agent'],['child','action'],['sibling','entry'],['status','status']].map(([id,kind],i)=>({id,kind,x:i*100,y:50,fx:i*100,fy:50,manual:true}));
 const links=[['child','owner'],['child','agent'],['agent','sibling'],['child','status']].map(([source,target])=>({source,target}));
 return {nodes,links};
};
test('child drag leaves owner and agent anchors pinned and unrelated children untouched',()=>{
 const {nodes,links}=fixture(),released=new Set();
 releaseFleetNeighbors(nodes[2],nodes,links,released,{x:200,y:50});
 for(const n of [nodes[0],nodes[1],nodes[3],nodes[4]]){assert.equal(n.fx,n.x);assert.equal(n.fy,n.y);assert.equal(n.manual,true);assert.ok(!released.has(n));}
 assert.equal(released.size,0);
});
test('direct anchor drag can release its children without releasing other anchors',()=>{
 const {nodes,links}=fixture(),released=new Set();
 nodes[2].manual=false;nodes[3].manual=false;
 releaseFleetNeighbors(nodes[1],nodes,links,released,{x:100,y:50});
 assert.ok(released.has(nodes[2]));assert.ok(released.has(nodes[3]));
 assert.equal(nodes[0].fx,0);assert.ok(!released.has(nodes[0]));assert.ok(!released.has(nodes[1]));
});

test('status drag releases its children but keeps agent anchors pinned',()=>{
 const {nodes,links}=fixture(),released=new Set();
 nodes[2].manual=false;
 releaseFleetNeighbors(nodes[4],nodes,links,released);
 assert.ok(released.has(nodes[2]));
 for(const n of [nodes[0],nodes[1],nodes[4]])assert.ok(!released.has(n));
 assert.equal(nodes[1].fx,100);
});

test('faster Fleet response follows a dragged agent sooner and settles finitely',async()=>{
 const {forceSimulation,forceManyBody,forceLink}=await import('d3-force-3d');
 const {configureDragForces}=await import('./graph-drag.mjs');
 const run=response=>{
  const parent={id:'agent',kind:'agent',x:0,y:0,fx:0,fy:0,radius:12};
  const child={id:'child',kind:'action',x:105,y:0,fx:105,fy:0,radius:7};
  const nodes=[parent,child],links=[{source:'agent',target:'child'}];
  const sim=forceSimulation(nodes).stop().velocityDecay(.2).force('charge',forceManyBody()).force('link',forceLink(links).id(n=>n.id));
  releaseFleetNeighbors(parent,nodes,links,new Set());
  configureDragForces({d3Force:(...args)=>sim.force(...args)},true,response);
  parent.x=parent.fx=-300;
  sim.tick(5);const progress=105-child.x;
  sim.tick(180);
  assert.ok(Number.isFinite(child.x)&&Number.isFinite(child.y));
  assert.equal(parent.x,-300);sim.stop();return progress;
 };
 assert.ok(run(2.2)>run(1.3),'Fleet catches up sooner');
});

test('Fleet follow speed remains strong when zoomed out and reverses smoothly',async()=>{
 const {forceSimulation,forceManyBody,forceLink}=await import('d3-force-3d');
 const {configureDragForces}=await import('./graph-drag.mjs');
 for(const zoom of [1,.2,.02,.005]){
  const parent={id:'a',kind:'agent',x:0,y:0,fx:0,fy:0,radius:12};
  const child={id:'c',kind:'skill',x:105/zoom,y:0,fx:105/zoom,fy:0,radius:7};
  const nodes=[parent,child],links=[{source:'a',target:'c'}];
  const sim=forceSimulation(nodes).stop().velocityDecay(.2).force('charge',forceManyBody()).force('link',forceLink(links).id(n=>n.id));
  releaseFleetNeighbors(parent,nodes,links,new Set());
  configureDragForces({d3Force:(...args)=>sim.force(...args),zoom:()=>zoom},true,2.2,{screenSpace:true});
  parent.x=parent.fx=-300/zoom;
  sim.tick(5);
  assert.ok(105-child.x*zoom>100,'child follows more than 100 screen pixels at zoom '+zoom);
  parent.x=parent.fx=300/zoom;
  for(let i=0;i<200;i++){
   const x=child.x,y=child.y;sim.tick();
   assert.ok(Math.hypot(child.x-x,child.y-y)*zoom<=52.81,'reversal stays within screen speed limit');
  }
  assert.ok(Number.isFinite(child.x)&&Math.abs(child.vx*zoom)<.1);
  sim.stop();
 }
});

test('drag never clears manual or explicit pins on connected entities',()=>{
 const {nodes,links}=fixture(),released=new Set();
 nodes[3].manual=false;nodes[3].pinned=true;
 const before=structuredClone(nodes.slice(2));
 releaseFleetNeighbors(nodes[1],nodes,links,released);
 assert.equal(released.size,0);
 assert.deepEqual(nodes.slice(2).map(n=>[n.x,n.y,n.manual,n.pinned]),before.map(n=>[n.x,n.y,n.manual,n.pinned]));
});

test('dense Fleet rings retain their spacing after dragging at extreme zoom',async()=>{
 const {forceSimulation,forceManyBody,forceLink}=await import('d3-force-3d');
 const {configureDragForces}=await import('./graph-drag.mjs');
 for(const zoom of [.005,.0001]){
  const parent={id:'a',kind:'agent',x:0,y:0,fx:0,fy:0,radius:44};
  const children=Array.from({length:24},(_,i)=>{const angle=i*Math.PI/12,reach=i%2?160:100;return {id:'c'+i,kind:'skill',x:reach*Math.cos(angle)/zoom,y:reach*Math.sin(angle)/zoom,radius:5};});
  const nodes=[parent,...children],links=children.map(n=>({source:'a',target:n.id}));
  const before=children.map(n=>({x:n.x,y:n.y}));
  const sim=forceSimulation(nodes).stop().velocityDecay(.2).force('charge',forceManyBody()).force('link',forceLink(links).id(n=>n.id));
  releaseFleetNeighbors(parent,nodes,links,new Set());
  configureDragForces({d3Force:(...args)=>sim.force(...args),zoom:()=>zoom},true,2.2,{screenSpace:true});
  parent.x=parent.fx=300/zoom;parent.y=parent.fy=100/zoom;
  sim.tick(300);
  children.forEach((n,i)=>assert.ok(Math.hypot(n.x-parent.x-before[i].x,n.y-parent.y-before[i].y)*zoom<2));
  for(const n of children)assert.ok(Math.hypot(n.x-parent.x,n.y-parent.y)*zoom>90);
  sim.stop();
 }
});
