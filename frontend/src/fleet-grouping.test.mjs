import test from 'node:test';
import assert from 'node:assert/strict';
import {groupFleet} from './fleet-grouping.mjs';
const data={nodes:[{id:'owner',kind:'owner'},{id:'agent:a',kind:'agent',agent_id:'a'},{id:'action:a',kind:'action',state:'open',assigned_agent_id:'a',agent_ids:['a']},{id:'idea:a',kind:'idea',state:'suggested',agent_ids:[]},{id:'entry:a',kind:'entry',agent_ids:['a']}],links:[{source:'action:a',target:'owner',relation:'belongs to corpus'}]};
test('groups by assignment and entity kind without changing provenance',()=>{
 const result=groupFleet(data),action=result.nodes.find(n=>n.id==='action:a');
 assert.equal(action.groupParent,'agent:a');
 assert.equal(result.nodes.find(n=>n.id==='idea:a').groupParent,'owner');
 assert.equal(result.nodes.filter(n=>n.kind==='status').length,0);
 assert.deepEqual(result.links,data.links);
 assert.deepEqual(result.links[0],data.links[0]);
 assert.equal(data.nodes.length,5);assert.equal(data.nodes[2].statusGroup,undefined);
 assert.notEqual(action.clusterY,result.nodes.find(n=>n.id==='entry:a').clusterY);
 assert.ok(result.nodes.every(n=>Number.isFinite(n.clusterX)&&Number.isFinite(n.clusterY)));
});
test('status changes leave topology and placement unchanged',()=>{
 const changed=structuredClone(data);changed.nodes[2].state='done';changed.nodes[3].state='dismissed';
 const before=groupFleet(data),after=groupFleet(changed);
 const placement=result=>result.nodes.map(({id,clusterX,clusterY})=>({id,clusterX,clusterY}));
 assert.deepEqual(placement(after),placement(before));
 assert.deepEqual(after.links,before.links);
 assert.equal(after.nodes.length,data.nodes.length);
 assert.ok(after.nodes.every(n=>!n.statusGroup));
});
test('matching statuses retain separate assignment anchors',()=>{
 const input=structuredClone(data);
 input.nodes.push({id:'action:owner',kind:'action',state:'open',agent_ids:[]});
 const result=groupFleet(input),assigned=result.nodes.find(n=>n.id==='action:a'),unassigned=result.nodes.find(n=>n.id==='action:owner');
 assert.notEqual(assigned.groupParent,unassigned.groupParent);
 assert.notEqual(assigned.clusterX,unassigned.clusterX);
 assert.deepEqual(result.links,input.links);
});
