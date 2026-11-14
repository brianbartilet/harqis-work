import test from 'node:test';
import assert from 'node:assert/strict';
import {filterFleet} from './fleet-graph.mjs';
const data={agents:[{id:'a',active:true,runtime:'hermes'},{id:'b',active:true,runtime:'codex'}],
  nodes:[{id:'agent:a',agent_id:'a',kind:'agent',label:'Butler',created:'2020-01-01'},
    {id:'agent:b',agent_id:'b',kind:'agent',label:'Coder'},
    {id:'report',kind:'file',agent_ids:['a'],label:'Release report',created:'2026-10-27',workspace_ids:['work']},
    {id:'old',kind:'task',agent_ids:['b'],label:'Old result',created:'2025-01-01'},
    {id:'config',kind:'configuration',agent_ids:['a'],label:'Model'}],
  edges:[{source:'agent:a',target:'report'},{source:'agent:b',target:'old'},{source:'agent:a',target:'config'}]};
test('output search retains its parent and removes dangling edges',()=>{
  const result=filterFleet(data,{query:'release',types:['file','task']});
  assert.deepEqual(result.nodes.map(n=>n.id),['agent:a','report']);
  assert.deepEqual(result.links,[data.edges[0]]);
});
test('date range applies to work, not the parent agent creation date',()=>{
  const result=filterFleet(data,{since:'2026-10-01',until:'2026-10-27',types:['file','task','configuration']});
  assert.deepEqual(result.nodes.map(n=>n.id),['agent:a','report']);
});
test('Space and service filters compose without leaking other outputs',()=>{
  assert.equal(filterFleet(data,{spaces:['work'],service:'codex',types:['file','task']}).nodes.length,0);
  assert.deepEqual(filterFleet(data,{spaces:['work'],types:['file']}).nodes.map(n=>n.id),['agent:a','report']);
});

test('orb radii mirror Activity Graph and shrink when connections are filtered',()=>{
  const all=filterFleet(data,{types:['file','task','configuration']});
  const agent=all.nodes.find(n=>n.id==='agent:a');
  assert.equal(agent.visibleDegree,2);
  assert.equal(agent.radius,10+4*Math.log2(3));
  const narrowed=filterFleet(data,{types:['file']});
  assert.equal(narrowed.nodes.find(n=>n.id==='agent:a').radius,14);
  assert.ok(agent.radius>narrowed.nodes.find(n=>n.id==='agent:a').radius);
  assert.equal(narrowed.nodes.find(n=>n.id==='agent:b').radius,10);
  assert.equal(data.nodes[0].radius,undefined,'source records stay unchanged');
});


test('fleet outputs use compact activity radii at both density thresholds',()=>{
  assert.equal(filterFleet(data,{types:['file']}).nodes.find(n=>n.id==='report').radius,7);
  const dense={agents:data.agents,nodes:[data.nodes[0],...Array.from({length:35},(_,i)=>({id:'hud:'+i,kind:'hud',agent_ids:['a'],label:'HUD '+i}))],edges:Array.from({length:35},(_,i)=>({source:'agent:a',target:'hud:'+i,relation:'monitors'}))};
  const result=filterFleet(dense,{types:['hud']});
  assert.equal(result.nodes.find(n=>n.kind==='hud').radius,4.5);
  assert.equal(result.nodes.find(n=>n.kind==='agent').radius,4+4*Math.log2(36));
  assert.equal(filterFleet(dense,{types:[]}).nodes[0].radius,10);
});

test('unassigned intent survives without inventing an agent edge',()=>{
 const data={agents:[],nodes:[{id:'action:orphan',kind:'action',label:'Manual task',agent_ids:[],workspace_ids:[]}],edges:[]};
 assert.equal(filterFleet(data,{types:['action']}).nodes.length,1);
 assert.equal(filterFleet(data,{types:['action'],service:'hermes'}).nodes.length,0);
});


test('corpus owner follows visible records without becoming an assigned agent',()=>{
 const data={agents:[],nodes:[{id:'owner:corpus',kind:'owner',label:'Owner'},{id:'action:manual',kind:'action',label:'Manual',agent_ids:[],workspace_ids:['work'],created:'2020-01-01'}],edges:[{source:'action:manual',target:'owner:corpus',relation:'belongs to corpus'}]};
 const visible=filterFleet(data,{types:['action'],spaces:['work']});
 assert.deepEqual(visible.nodes.map(n=>n.id),['owner:corpus','action:manual']);
 assert.equal(visible.links.length,1);
 assert.equal(filterFleet(data,{types:['action'],spaces:['other']}).nodes.length,0);
 assert.equal(filterFleet(data,{types:['action'],since:'2026-01-01'}).nodes.length,2);
});


test('dates preserve active intent while the toggle controls done and dismissed items',()=>{
 const intent=(id,kind,state,created='2020-01-01')=>({id,kind,state,created,label:id,agent_ids:[],workspace_ids:['work']});
 const data={agents:[],nodes:[intent('old-action','action','open'),intent('done','action','done'),intent('future-idea','idea','suggested','2030-01-01'),intent('dismissed-action','action','dismissed'),intent('dismissed-idea','idea','dismissed'),intent('old-entry','entry','recorded'),intent('recent-entry','entry','recorded','2026-11-14')],edges:[]};
 const filters={types:['action','idea','entry'],since:'2026-11-01',until:'2026-11-30'};
 assert.deepEqual(filterFleet(data,filters).nodes.map(n=>n.id),['old-action','future-idea','recent-entry']);
 assert.equal(filterFleet(data,{...filters,spaces:['other']}).nodes.length,0);
 assert.deepEqual(filterFleet(data,{...filters,dismissed:true}).nodes.map(n=>n.id),['old-action','done','future-idea','dismissed-action','dismissed-idea','recent-entry']);
 assert.equal(filterFleet(data,{...filters,dismissed:true,spaces:['other']}).nodes.length,0);
 assert.deepEqual(filterFleet(data,{...filters,query:'old-action'}).nodes.map(n=>n.id),['old-action']);
 assert.deepEqual(filterFleet(data,{types:['action','idea']}).nodes.map(n=>n.id),['old-action','future-idea']);
});

test('owner activity switch preserves agent entries and all intent',()=>{
 const data={agents:[{id:'a',active:true}],nodes:[{id:'owner-entry',kind:'entry',agent_ids:[]},{id:'agent-entry',kind:'entry',agent_ids:['a']},{id:'action',kind:'action',agent_ids:[]},{id:'idea',kind:'idea',agent_ids:[]}],edges:[]};
 assert.deepEqual(filterFleet(data,{types:['entry','action','idea'],includeOwnerActivity:false}).nodes.map(n=>n.id),['agent-entry','action','idea']);
});
test('Today uses exact rolling 24 hour bounds and preserves intents',()=>{
 const now=Date.parse('2026-11-15T10:00:00Z');
 const data={agents:[],nodes:[['boundary','2026-11-14T10:00:00Z'],['old','2026-11-14T09:59:59Z'],['now','2026-11-15T10:00:00Z'],['future','2026-11-15T10:00:01Z']].map(([id,created])=>({id,created,kind:'entry'})).concat([{id:'action',kind:'action',created:'2020-01-01'}]),edges:[]};
 assert.deepEqual(filterFleet(data,{types:['entry','action'],range:'1',now}).nodes.map(n=>n.id),['boundary','now','action']);
});

test('undated HUD catalog nodes survive date filters and global Space selection',()=>{
 const input=structuredClone(data);
 input.nodes.push({id:'hud:calendar',kind:'hud',label:'Calendar',agent_ids:['a'],workspace_ids:[]});
 input.edges.push({source:'agent:a',target:'hud:calendar'});
 const options={types:['hud'],spaces:['work'],since:'2026-10-01',until:'2026-10-02'};
 assert.ok(filterFleet(input,options).nodes.some(n=>n.id==='hud:calendar'));
 input.nodes.at(-1).workspace_ids=['personal'];
 assert.ok(!filterFleet(input,options).nodes.some(n=>n.id==='hud:calendar'));
});
