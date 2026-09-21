import test from 'node:test';
import assert from 'node:assert/strict';
import {placeLabels} from '../src/graph-labels.mjs';
const node=(id,degree=1)=>({id,label:id,degree,x:200,y:200,radius:8,kind:'tools',preferred:true});
const viewport={width:800,height:600,zoom:0.1};
const measure=text=>text.length*7;
test('board titles wrap without truncation even at low zoom',()=>{
  const title='Create a thought to brainstorm and refine, promote as idea';
  const labels=placeLabels([{...node('draft'),label:title,kind:'drafts',preferred:false}],{...viewport,fullTitles:true,width:300},measure);
  assert.equal(labels.length,1);
  assert.equal(labels[0].text,title);
  assert.equal(labels[0].lines.join(' '),title);
  assert.ok(labels[0].lines.length>1);
  assert.ok(labels[0].w<=276);
});
test('crowded labels prioritize hubs, avoid overlap, and ignore input order',()=>{
  const nodes=Array.from({length:50},(_,i)=>node('orb'+i,i));
  const labels=placeLabels(nodes,viewport,measure);
  assert.equal(labels[0].node.id,'orb49');
  assert.ok(labels.length<10);
  assert.deepEqual(labels,placeLabels(nodes.reverse(),viewport,measure));
  for(let i=0;i<labels.length;i++)for(const b of labels.slice(i+1)){
    const a=labels[i];assert.ok(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y);
  }
});
test('zoom reveals more labels while selected orbs outrank hubs',()=>{
  const nodes=Array.from({length:40},(_,i)=>({...node('orb'+i,i),x:60+i%8*95,y:50+Math.floor(i/8)*100}));
  assert.ok(placeLabels(nodes,{...viewport,zoom:2},measure).length>placeLabels(nodes,viewport,measure).length);
  nodes[0].emphasis=true;
  assert.equal(placeLabels(nodes,viewport,measure)[0].node.id,'orb0');
});
test('offscreen labels are culled and edge selections remain visible',()=>{
  const labels=placeLabels([{...node('outside',100),x:-10},{...node('selected'),x:799,y:599,emphasis:true}],viewport,measure);
  assert.equal(labels.length,1);assert.equal(labels[0].node.id,'selected');
  assert.ok(labels[0].x+labels[0].w<=800&&labels[0].y+labels[0].h<=600);
});
