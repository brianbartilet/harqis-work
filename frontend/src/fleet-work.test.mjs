import test from 'node:test';
import assert from 'node:assert/strict';
import {agentWork} from './fleet-work.mjs';

test('execution and canonical status stay independent; current agent scopes the drawer',()=>{
 const nodes=[
  {id:'a',kind:'action',state:'in_progress',agent_ids:['a'],execution:{state:'failed',agent_id:'a'}},
  {id:'b',kind:'action',state:'active',agent_ids:['a']},
  {id:'c',kind:'action',state:'open',agent_ids:['b'],execution:{state:'running',agent_id:'b'}},
  {id:'d',kind:'action',state:'done',agent_ids:['a'],execution:{state:'succeeded',agent_id:'a'}},
  {id:'e',kind:'entry',agent_ids:['a']},
  {id:'f',kind:'action',state:'active',agent_ids:[]},
 ];
 const groups=agentWork(nodes,'a');
 assert.deepEqual(groups.attention.map(n=>n.id),['a']);
 assert.deepEqual(groups.assigned.map(n=>n.id),['b']);
 assert.deepEqual(groups.recent.map(n=>n.id),['d']);
 assert.equal(groups.running.length,0);
 assert.equal(agentWork(nodes).running.length,1);
 assert.deepEqual(agentWork(nodes).assigned.map(n=>n.id),['b']);
 assert.equal(Object.values(agentWork(nodes,'empty-agent')).flat().length,0);
 assert.equal(nodes[0].state,'in_progress');
});
