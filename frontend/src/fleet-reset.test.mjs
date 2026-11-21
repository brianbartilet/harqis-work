import test from 'node:test';
import assert from 'node:assert/strict';
import {resetFleetChildren,resetFleetView} from './fleet-reset.mjs';
const hub=(id,x=0,y=0,kind='agent')=>({id,kind,x,y,fx:x,fy:y,radius:35});
const child=(id,kind='skill')=>({id,kind,x:1,y:1,radius:6});
const link=(source,target)=>({source,target});
function assertSeparated(nodes,zoom=1,padding=0){
 for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
  const a=nodes[i],b=nodes[j];
  const extra=n=>['agent','owner','connector','status'].includes(n.kind)||n.manual?0:padding;
  assert.ok(Math.hypot(a.x-b.x,a.y-b.y)*zoom>=a.radius+b.radius+extra(a)+extra(b)+11.99,`${a.id} overlaps ${b.id}`);
 }
}
test('reset preserves anchors and manual positions and changes only child placement',()=>{
 const fixed=[hub('a'),hub('owner',500,0,'owner'),hub('connector',-500,0,'connector'),hub('status',0,500,'status'),{...child('pinned'),x:0,y:-200,fx:0,fy:-200,manual:true}];
 const nodes=[...fixed,child('child')],before=structuredClone(fixed),links=[link('a','child')],original=structuredClone(links);
 resetFleetChildren(nodes,links);
 assert.deepEqual(fixed,before);assert.deepEqual(links,original);assertSeparated(nodes);
 assert.equal(nodes.at(-1).fx,nodes.at(-1).x);
});
test('shared children choose the parent with the most distinct connections',()=>{
 const a=hub('a',-500),b=hub('b',500),shared=child('shared'),nodes=[a,b,shared,child('b-only')];
 const links=[link('a','shared'),link('b','shared'),link('b','b-only'),link('a','shared')];
 resetFleetChildren(nodes,links);
 assert.ok(Math.hypot(shared.x-b.x,shared.y-b.y)<Math.hypot(shared.x-a.x,shared.y-a.y));
});
test('dense neighboring clusters return to the same rings after animated movement',()=>{
 for(const separation of [150,300,600]){
  const parents=[hub('a',0),hub('b',separation)],nodes=[...parents],links=[];
  for(let i=0;i<300;i++){const n=child('n'+i,i%2?'skill':'workflow');nodes.push(n);links.push(link(i<150?'a':'b',n.id));}
  const start=performance.now();resetFleetChildren(nodes,links);
  assert.ok(performance.now()-start<2000);assertSeparated(nodes,1,0);
  const first=nodes.map(n=>[n.x,n.y]);
  for(const n of nodes.slice(2)){n.x+=18;n.y-=14;}
  resetFleetChildren(nodes,links);
  assert.deepEqual(nodes.map(n=>[n.x,n.y]),first);
 }
});
test('types occupy distinct sectors and sparse parents use the inner ring',()=>{
 const parent=hub('a'),nodes=[parent,...Array.from({length:30},(_,i)=>child('n'+i,i<15?'skill':'workflow'))];
 resetFleetChildren(nodes,nodes.slice(1).map(n=>link(parent,n.id)));
 assert.ok(nodes.filter(n=>n.kind==='skill').every(n=>n.x>0));
 assert.ok(nodes.filter(n=>n.kind==='workflow').every(n=>n.x<0));
 const sparse=[hub('b'),child('only')];resetFleetChildren(sparse,[link('b','only')]);
 assert.ok(Math.hypot(sparse[1].x,sparse[1].y)<100);assertSeparated(nodes);
});

test('a thousand children stay compact without zoom-dependent expansion',()=>{
 const nodes=[hub('a'),...Array.from({length:1000},(_,i)=>child('c'+i))];
 resetFleetChildren(nodes,nodes.slice(1).map(n=>link('a',n.id)));
 assert.ok(Math.max(...nodes.map(n=>Math.hypot(n.x,n.y)))<650);
 assertSeparated(nodes);
});

test('distant saved anchors do not collapse child nodes at fitted zoom',()=>{
 for(const distance of [1000,100000,1000000]){
  const nodes=[hub('a',-distance),hub('b',distance),...Array.from({length:160},(_,i)=>child('child'+i,i%2?'skill':'workflow'))];
  const links=nodes.slice(2).map((n,i)=>link(i<80?'a':'b',n.id));
  const view=resetFleetView(nodes,links,1100,740);
  assert.equal(nodes[0].x,-distance);assert.equal(nodes[1].x,distance);
  for(const n of nodes){assert.ok(Math.abs(n.x-view.x)*view.zoom+n.radius<=550);assert.ok(Math.abs(n.y-view.y)*view.zoom+n.radius<=370);}
  assertSeparated(nodes,view.zoom,0);
  const positions=nodes.map(n=>[n.x,n.y]);assert.deepEqual(resetFleetView(nodes,links,1100,740),view);
  assert.deepEqual(nodes.map(n=>[n.x,n.y]),positions);
 }
});

test('large fitted fleets keep individual child orbs visible',()=>{
 const nodes=Array.from({length:16},(_,i)=>hub('a'+i,100000*Math.cos(i*Math.PI/8),70000*Math.sin(i*Math.PI/8))),links=[];
 for(let i=0;i<700;i++){nodes.push({...child('c'+i,i%2?'skill':'workflow'),radius:5});links.push(link('a'+i%16,'c'+i));}
 const view=resetFleetView(nodes,links,1100,740);
 for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++)assert.ok(Math.hypot(nodes[i].x-nodes[j].x,nodes[i].y-nodes[j].y)*view.zoom>=nodes[i].radius+nodes[j].radius,'orbs remain distinct');
});

test('reset preserves an explicit pinned entity even without the manual flag',()=>{
 const pinned={...child('pinned'),x:120,y:-180,fx:120,fy:-180,pinned:true};
 const nodes=[hub('a'),pinned,child('free')],before=structuredClone(pinned);
 resetFleetChildren(nodes,[link('a','pinned'),link('a','free')],{scale:.2});
 assert.deepEqual(pinned,before);assert.notEqual(nodes[2].x,1);
});
