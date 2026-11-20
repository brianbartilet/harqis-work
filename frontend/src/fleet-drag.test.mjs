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
 releaseFleetNeighbors(nodes[1],nodes,links,released,{x:100,y:50});
 assert.ok(released.has(nodes[2]));assert.ok(released.has(nodes[3]));
 assert.equal(nodes[0].fx,0);assert.ok(!released.has(nodes[0]));assert.ok(!released.has(nodes[1]));
});

test('status drag releases its children but keeps agent anchors pinned',()=>{
 const {nodes,links}=fixture(),released=new Set();
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
