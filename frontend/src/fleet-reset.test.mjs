import test from 'node:test';
import assert from 'node:assert/strict';
import {resetFleetChildren} from './fleet-reset.mjs';
const hub=(id,x=0,y=0,kind='agent')=>({id,kind,x,y,fx:x,fy:y,radius:35});
const child=(id,kind='skill')=>({id,kind,x:1,y:1,radius:6});
const link=(source,target)=>({source,target});
function assertSeparated(nodes,zoom=1,padding=23){
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
  assert.ok(performance.now()-start<2000);assertSeparated(nodes,1,23);
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
