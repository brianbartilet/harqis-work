import test from 'node:test';
import assert from 'node:assert/strict';
import {groupFleet} from './fleet-grouping.mjs';
const data={nodes:[{id:'owner',kind:'owner'},{id:'agent:a',kind:'agent',agent_id:'a'},{id:'action:a',kind:'action',state:'open',assigned_agent_id:'a',agent_ids:['a']},{id:'idea:a',kind:'idea',state:'suggested',agent_ids:[]},{id:'entry:a',kind:'entry',agent_ids:['a']}],links:[{source:'action:a',target:'owner',relation:'belongs to corpus'}]};
test('groups by assignment and entity kind without changing provenance',()=>{
 const result=groupFleet(data),action=result.nodes.find(n=>n.id==='action:a');
 assert.equal(action.groupParent,'agent:a');
 assert.equal(result.nodes.find(n=>n.id==='idea:a').groupParent,'owner');
 assert.equal(result.nodes.filter(n=>n.kind==='status').length,2);
 assert.deepEqual(result.links[0],data.links[0]);
 assert.equal(data.nodes.length,5);assert.equal(data.nodes[2].statusGroup,undefined);
 assert.notEqual(action.clusterY,result.nodes.find(n=>n.id==='entry:a').clusterY);
 assert.ok(result.nodes.every(n=>Number.isFinite(n.clusterX)&&Number.isFinite(n.clusterY)));
});
test('status changes replace the group and edge; filtering removes empty groups',()=>{
 const before=groupFleet(data),changed=structuredClone(data);changed.nodes[2].state='done';
 const after=groupFleet(changed),oldId=before.nodes.find(n=>n.label==='Actions · In Review').id;
 assert.ok(!after.nodes.some(n=>n.id===oldId));assert.ok(!after.links.some(e=>e.target===oldId));
 assert.ok(after.nodes.some(n=>n.label==='Actions · Done'));
 const filtered=groupFleet({nodes:data.nodes.filter(n=>n.kind!=='action'),links:[]});
 assert.equal(filtered.nodes.filter(n=>n.kind==='status').length,1);
 const ids=new Set(after.nodes.map(n=>n.id));assert.ok(after.links.every(e=>ids.has(e.source)&&ids.has(e.target)));
});


test('status filter hides only visual status nodes and their edges',()=>{
 const result=groupFleet(data,{showStatus:false});
 assert.deepEqual(result.nodes.map(n=>n.id),data.nodes.map(n=>n.id));
 assert.deepEqual(result.links,data.links);
 assert.equal(groupFleet(data).nodes.filter(n=>n.kind==='status').length,2);
});
