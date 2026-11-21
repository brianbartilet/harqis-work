import test from 'node:test';
import assert from 'node:assert/strict';
import {fleetFitView} from './fleet-viewport.mjs';
import {resetFleetChildren} from './fleet-reset.mjs';

test('fit includes screen sized avatars at desktop and mobile widths',()=>{
 for(const width of [390,1440])for(const distance of [100,1e7]){
  const nodes=[{x:-distance,y:-distance,radius:44},{x:distance,y:distance,radius:6}];
  const view=fleetFitView(nodes,width,700);
  for(const n of nodes){
   assert.ok(Math.abs(n.x-view.x)*view.zoom+n.radius<=width/2-31);
   assert.ok(Math.abs(n.y-view.y)*view.zoom+n.radius<=350-31);
  }
  assert.deepEqual(fleetFitView(nodes,width,700),view);
 }
 assert.equal(fleetFitView([],390,700),null);
});

test('reset rings do not depend on where the viewport edge falls',()=>{
 const make=x=>[{id:'a',kind:'agent',x,y:0,radius:40},...Array.from({length:80},(_,i)=>({id:'c'+i,kind:'skill',radius:5,x:0,y:0}))];
 const a=make(0),b=make(100000),links=a.slice(1).map(n=>({source:'a',target:n.id}));
 resetFleetChildren(a,links,{scale:.001});resetFleetChildren(b,links,{scale:.001});
 for(let i=1;i<a.length;i++){
  assert.ok(Math.abs(a[i].x-(b[i].x-100000))<1e-7);
  assert.equal(a[i].y,b[i].y);
 }
 assert.ok(a.some(n=>n.x<0)&&a.some(n=>n.x>0));
});
