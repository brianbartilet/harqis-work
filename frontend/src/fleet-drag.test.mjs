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
 for(const n of [nodes[0],nodes[1],nodes[3]]){assert.equal(n.fx,n.x);assert.equal(n.fy,n.y);assert.equal(n.manual,true);assert.ok(!released.has(n));}
 assert.ok(released.has(nodes[4]));assert.equal(nodes[4].fx,undefined);
});
test('direct anchor drag can release its children without releasing other anchors',()=>{
 const {nodes,links}=fixture(),released=new Set();
 releaseFleetNeighbors(nodes[1],nodes,links,released,{x:100,y:50});
 assert.ok(released.has(nodes[2]));assert.ok(released.has(nodes[3]));
 assert.equal(nodes[0].fx,0);assert.ok(!released.has(nodes[0]));assert.ok(!released.has(nodes[1]));
});
