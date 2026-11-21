import test from 'node:test';
import assert from 'node:assert/strict';
import {fleetParents} from './fleet-parent.mjs';
import {fleetOverview,arrangeFleetClusters,fleetCamera} from './fleet-overview.mjs';
import {translateFleetChildren} from './fleet-drag.mjs';
const hub=id=>({id:'agent:'+id,kind:'agent',label:id,x:0,y:0,radius:35});
function fixture(count=200){
 const nodes=[hub('a'),hub('b')],links=[];
 for(let i=0;i<count;i++){
  const parent=i%2?'b':'a',id='child:'+i;
  nodes.push({id,kind:'skill',label:'Skill '+i,assigned_agent_id:parent,groupParent:'agent:'+parent,radius:6,x:0,y:0});
  links.push({source:'agent:'+parent,target:id});
 }
 return {nodes,links};
}
test('assignment wins over higher degree, corpus ownership, and relationship order',()=>{
 const data=fixture();data.links.push({source:'agent:b',target:'child:0'});
 data.nodes[2].groupParent='agent:b';
 assert.equal(fleetParents(data.nodes,data.links).get('child:0'),'agent:a');
 assert.equal(fleetParents([...data.nodes].reverse(),[...data.links].reverse()).get('child:0'),'agent:a');
});
test('dense fleets retain every entity and relationship without count substitutes',()=>{
 const data=fixture(700),initial=structuredClone(data);
 for(const options of [{},{compact:true},{group:'fleet-group:["agent:a","skill"]',page:99,limit:12}]){
  const overview=fleetOverview(data,options);
  assert.deepEqual(overview.nodes.map(n=>n.id),data.nodes.map(n=>n.id));
  assert.deepEqual(overview.links,data.links);
  assert.ok(!overview.nodes.some(n=>n.kind==='group'));
  assert.equal(overview.nodes[0].childCount,350);
 }
 assert.deepEqual(data,initial);
});
test('arrangement separates parents and keeps each displayed child closer to its own parent',()=>{
 const data=fleetOverview(fixture(200),{group:'fleet-group:["agent:a","skill"]'});
 arrangeFleetClusters(data.nodes,data.links);
 const parents=fleetParents(data.nodes,data.links),hubs=data.nodes.filter(n=>n.kind==='agent');
 for(const n of data.nodes.filter(n=>parents.has(n.id))){
  const parent=hubs.find(h=>h.id===parents.get(n.id)),other=hubs.find(h=>h!==parent);
  assert.ok(Math.hypot(n.x-parent.x,n.y-parent.y)<Math.hypot(n.x-other.x,n.y-other.y));
 }
 const first=data.nodes.map(n=>[n.x,n.y]);arrangeFleetClusters(data.nodes,data.links);
 assert.deepEqual(data.nodes.map(n=>[n.x,n.y]),first);
});
test('drag translates exactly at every zoom, preserves pins and never follows cross-links',()=>{
 for(const zoom of [1,.2,.005,.0001,.000001]){
  const data=fixture(8);data.links.push({source:'child:0',target:'child:1'});
  data.nodes[4].manual=true;
  const parents=fleetParents(data.nodes,data.links),delta={x:120/zoom,y:-40/zoom};
  translateFleetChildren(data.nodes[0],data.nodes,parents,delta);
  assert.equal(data.nodes[2].x*zoom,120);assert.equal(data.nodes[2].y*zoom,-40);
  assert.equal(data.nodes[3].x,0);assert.equal(data.nodes[4].x,0);
  translateFleetChildren(data.nodes[0],data.nodes,parents,{x:-delta.x,y:-delta.y});
  for(const n of data.nodes)assert.equal(Math.abs(n.x)+Math.abs(n.y),0);
 }
});
test('fit handles legacy coordinates without rearranging nodes or changing pins',()=>{
 const data=fixture(2);data.nodes[0].x=-1000000;data.nodes[1].x=1000000;data.nodes[2].manual=true;
 const before=structuredClone(data.nodes),view=fleetCamera(data.nodes,390,640);
 assert.ok(view.zoom>0&&view.zoom<.001);
 for(const n of data.nodes)assert.ok(Math.abs(n.x-view.x)*view.zoom<195);
 assert.deepEqual(data.nodes,before);
});
test('arranging repairs coincident parents while preserving explicit child pins',()=>{
 const data=fixture(20);data.nodes[3].manual=true;data.nodes[3].x=75;
 arrangeFleetClusters(data.nodes,data.links);
 assert.ok(Math.hypot(data.nodes[0].x-data.nodes[1].x,data.nodes[0].y-data.nodes[1].y)>300);
 assert.equal(data.nodes[3].x,75);assert.equal(data.nodes[3].y,0);
});
test('narrow canvases retain all parents and their individual entities',()=>{
 const data=fixture();const overview=fleetOverview(data,{compact:true,selected:'child:199'});
 assert.equal(overview.nodes.filter(n=>n.kind==='agent').length,2);
 assert.equal(overview.nodes.length,202);
 assert.ok(overview.nodes.some(n=>n.id==='child:199'));
});
