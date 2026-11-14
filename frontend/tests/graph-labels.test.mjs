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

test('crowded board titles stay clear of each other and orb controls',()=>{
  const obstacles=[{x:220,y:160,w:40,h:80}];
  const nodes=Array.from({length:12},(_,i)=>({...node('board orb '+i,i),emphasis:i===0}));
  const labels=placeLabels(nodes,{...viewport,fullTitles:true,obstacles},measure);
  assert.equal(labels[0].node.id,'board orb 0');
  assert.equal(labels[0].font,14);
  assert.ok(labels.length<nodes.length);
  for(let i=0;i<labels.length;i++)for(const b of [...labels.slice(i+1),...obstacles]){
    const a=labels[i];assert.ok(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y);
  }
});

test('passive layout holds visibility for eight seconds and follows its orb',async()=>{
  const {createLabelLayout}=await import('../src/graph-labels.mjs');
  const layout=createLabelLayout(), first=node('first');
  layout([first],viewport,measure,0,'view');
  const initial=layout([first],viewport,measure,400,'view')[0];
  const moved={...first,x:240};
  const second={...node('second'),x:500};
  const held=layout([moved,second],viewport,measure,7999,'view');
  assert.equal(held.length,1);
  assert.equal(held[0].x,initial.x+40);
  assert.equal(held[0].alpha,1);
  const tick=layout([moved,second],viewport,measure,8000,'view');
  assert.equal(tick.find(b=>b.node.id==='first').alpha,1);
  const fading=layout([moved,second],viewport,measure,8300,'view');
  assert.equal(fading.find(b=>b.node.id==='second').alpha,0.5);
  assert.equal(layout([moved,second],viewport,measure,8400,'view').length,2);
});

test('invalid placement fades out and in together; interaction bypasses timer',async()=>{
  const {createLabelLayout}=await import('../src/graph-labels.mjs');
  const layout=createLabelLayout(), first=node('first');
  const old=layout([first],viewport,measure,0,'view',true)[0];
  const blocked={...viewport,obstacles:[{x:old.x,y:old.y,w:old.w,h:old.h}]};
  layout([first],blocked,measure,8000,'view');
  assert.equal(layout([first],blocked,measure,8100,'view')[0].alpha,0.5);
  assert.equal(layout([first],blocked,measure,8200,'view').length,0);
  const next=layout([first],blocked,measure,8300,'view')[0];
  assert.equal(next.alpha,0.5);assert.notEqual(next.x,old.x);
  const selected={...first,emphasis:true};
  assert.equal(layout([selected],viewport,measure,8500,'selected',true)[0].font,14);
  assert.equal(layout([],viewport,measure,8501,'selected').length,0);
});

test('interaction during a fade does not flash an unchanged label to full opacity',async()=>{
  const {createLabelLayout}=await import('../src/graph-labels.mjs');
  const layout=createLabelLayout(), candidate=node('steady');
  layout([candidate],viewport,measure,0,'first');
  assert.equal(layout([candidate],viewport,measure,300,'pan')[0].alpha,0.5);
  assert.equal(layout([candidate],viewport,measure,350,'pan')[0].alpha,0.75);
  assert.equal(layout([candidate],viewport,measure,400,'pan')[0].alpha,1);
});


test('animation resolves only visible labels without rebuilding or remeasuring all nodes',async()=>{
  const {createLabelLayout}=await import('../src/graph-labels.mjs');
  const layout=createLabelLayout();
  const nodes=Array.from({length:5000},(_,i)=>({...node('orb'+i),x:200+i*100}));
  const byId=new Map(nodes.map(n=>[n.id,n]));
  let scans=0,measurements=0,resolved=0;
  const source=()=>{scans++;return nodes;};
  const width=text=>{measurements++;return measure(text);};
  const resolve=id=>{resolved++;return byId.get(id);};
  layout(source,viewport,width,0,'view',true,resolve);
  const count=measurements;
  resolved=0;
  nodes[0].x+=10;
  const frame=layout(source,viewport,width,16,'view',true,resolve);
  assert.equal(scans,1);
  assert.equal(measurements,count);
  assert.equal(resolved,frame.length);
  assert.ok(resolved<10);
  assert.equal(frame[0].node.x,210);
  layout(source,viewport,width,8000,'view',true,resolve);
  assert.equal(scans,2);
  assert.equal(measurements,count);
});

test('camera motion holds labels then lays out once settled; selection stays immediate',async()=>{
  const {createLabelLayout}=await import('../src/graph-labels.mjs');
  const layout=createLabelLayout(),candidate=node('moving');
  let scans=0;
  const source=()=>{scans++;return [candidate];};
  const resolve=()=>candidate;
  layout(source,{...viewport,cameraKey:'0'},measure,0,'view',true,resolve);
  for(let i=1;i<=60;i++){
    candidate.x=200+i;
    const boxes=layout(source,{...viewport,cameraKey:String(i)},measure,i*16,'view',true,resolve);
    assert.equal(boxes[0].node.x,candidate.x);
  }
  assert.equal(scans,1);
  layout(source,{...viewport,cameraKey:'60'},measure,1080,'view',true,resolve);
  assert.equal(scans,2);
  candidate.emphasis=true;
  const selected=layout(source,{...viewport,cameraKey:'61'},measure,1081,'selected',true,resolve);
  assert.equal(scans,3);
  assert.equal(selected[0].font,14);
});


test('status suffix remains visible when long action labels are shortened',()=>{
 const labels=placeLabels([{id:'a',label:'A very long action title that would hide its status · In Progress',labelSuffix:' · In Progress',kind:'actions',x:100,y:100,radius:5,degree:1,emphasis:true}],{width:800,height:400,zoom:1},text=>text.length*6);
 assert.equal(labels.length,1);
 assert.ok(labels[0].text.endsWith(' · In Progress'));
});

test('always-visible status labels survive low zoom, budget and collisions',()=>{
 const statuses=Array.from({length:10},(_,i)=>({id:'status'+i,label:'Actions - In Review',kind:'status',x:150,y:100,radius:13,degree:0,alwaysShow:true}));
 const labels=placeLabels(statuses,{width:300,height:200,zoom:.01,obstacles:[{x:0,y:0,w:300,h:200}]},measure);
 assert.equal(labels.length,statuses.length);
 assert.ok(labels.every(box=>box.x>=0&&box.y>=0&&box.x+box.w<=300&&box.y+box.h<=200));
});
test('always-visible labels render immediately without a fade gap',async()=>{
 const {createLabelLayout}=await import('../src/graph-labels.mjs');
 const layout=createLabelLayout(),status={...node('status'),alwaysShow:true};
 const labels=layout([status],viewport,measure,0,'status');
 assert.equal(labels.length,1);
 assert.equal(labels[0].alpha,1);
});
