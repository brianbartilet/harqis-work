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
