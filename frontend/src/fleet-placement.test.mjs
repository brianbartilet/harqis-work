import test from 'node:test';
import assert from 'node:assert/strict';
import {placeFleetNodes} from './fleet-placement.mjs';
const node=(id,kind='action',parent='agent:a')=>({id,kind,groupParent:parent,radius:5,clusterX:9000,clusterY:9000});
test('arrivals stay near saved same-type siblings without moving saved nodes',()=>{
 const input=[node('agent:a','agent'),node('a'),node('b'),node('other','idea'),node('new')];
 const saved={'agent:a':{x:100,y:100},a:{x:200,y:220,manual:true},b:{x:225,y:220},other:{x:-4000,y:-4000}};
 const before=structuredClone(saved),result=placeFleetNodes(input,saved,.5),fresh=result.find(n=>n.id==='new');
 assert.ok(Math.hypot(fresh.x-200,fresh.y-220)<150);
 assert.equal(fresh.fx,fresh.x);assert.equal(fresh.fy,fresh.y);
 for(const n of result.filter(n=>saved[n.id])){assert.equal(n.x,saved[n.id].x);assert.equal(n.y,saved[n.id].y);}
 assert.deepEqual(saved,before);assert.equal(input[0].x,undefined);
});
test('same-agent cluster wins over same-type nodes belonging to another agent',()=>{
 const input=[node('local'),node('remote','action','agent:b'),node('new')];
 const result=placeFleetNodes(input,{local:{x:100,y:100},remote:{x:-5000,y:-5000}});
 assert.ok(Math.hypot(result[2].x-100,result[2].y-100)<100);
});
test('a batch of arrivals gets distinct free positions and survives reload',()=>{
 const input=[node('a'),...Array.from({length:30},(_,i)=>node('new:'+i))];
 const result=placeFleetNodes(input,{a:{x:300,y:400}},.5);
 for(let i=0;i<result.length;i++)for(let j=i+1;j<result.length;j++)assert.ok(Math.hypot(result[i].x-result[j].x,result[i].y-result[j].y)>=36);
 const saved=Object.fromEntries(result.map(n=>[n.id,{x:n.x,y:n.y}]));
 assert.deepEqual(placeFleetNodes(input,saved,.5).map(n=>[n.x,n.y]),result.map(n=>[n.x,n.y]));
});
test('first-of-type arrivals use the actual saved agent and cold layouts stay movable',()=>{
 const input=[node('agent:a','agent'),node('new','file')];
 const result=placeFleetNodes(input,{'agent:a':{x:-500,y:-800}});
 assert.ok(Math.hypot(result[1].x+500,result[1].y+800)<200);
 const cold=placeFleetNodes(input);assert.equal(cold[1].fx,undefined);assert.equal(cold[0].fx,cold[0].x);
});

test('status nodes are pinned on initial layout and retain saved positions',()=>{
 const input=[node('status:failed','status')];
 const [cold]=placeFleetNodes(input);
 assert.equal(cold.fx,cold.x);assert.equal(cold.fy,cold.y);
 const [saved]=placeFleetNodes(input,{'status:failed':{x:120,y:240,manual:true}});
 assert.equal(saved.fx,120);assert.equal(saved.fy,240);
});

test('an assignment change places the child near its new parent but respects an explicit pin',()=>{
 const input=[node('agent:a','agent'),node('agent:b','agent'),node('moved','action','agent:b')];
 const saved={'agent:a':{x:0,y:0},'agent:b':{x:5000,y:0},moved:{x:100,y:0,layoutParent:'agent:a'}};
 const result=placeFleetNodes(input,saved);
 assert.ok(Math.hypot(result[2].x-5000,result[2].y)<200);
 saved.moved.manual=true;
 assert.equal(placeFleetNodes(input,saved)[2].x,100);
});
