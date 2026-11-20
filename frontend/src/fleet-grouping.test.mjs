import test from 'node:test';
import assert from 'node:assert/strict';
import {groupFleet,configureFleetLinks} from './fleet-grouping.mjs';
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
 const after=groupFleet(changed),oldId=before.nodes.find(n=>n.label==='In Review').id;
 assert.ok(!after.nodes.some(n=>n.id===oldId));assert.ok(!after.links.some(e=>e.target===oldId));
 assert.ok(after.nodes.some(n=>n.label==='Done'));
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

test('matching statuses merge across owner and agents with unique hub connections',()=>{
 const input=structuredClone(data);
 input.nodes.push({id:'action:owner',kind:'action',state:'open',agent_ids:[]},{id:'action:other',kind:'action',state:'open',agent_ids:['a']},{id:'idea:agent',kind:'idea',state:'suggested',agent_ids:['a']});
 const result=groupFleet(input),statuses=result.nodes.filter(n=>n.kind==='status');
 assert.equal(statuses.length,2);
 const action=statuses.find(n=>n.groupKind==='action');assert.equal(action.count,3);
 assert.deepEqual(action.groupParents,['agent:a','owner']);
 assert.equal(result.links.filter(e=>e.target===action.id&&e.relation==='has status').length,3);
 assert.equal(result.links.filter(e=>e.target===action.id&&e.relation==='status group').length,2);
 const members=result.nodes.filter(n=>n.statusGroup===action.id);
 assert.ok(members.some(n=>n.clusterX!==action.clusterX||n.clusterY!==action.clusterY));
 const ownerMember=members.find(n=>n.id==='action:owner'),agentMember=members.find(n=>n.id==='action:a');
 assert.notEqual(ownerMember.clusterX,agentMember.clusterX);
 input.nodes.find(n=>n.id==='action:owner').state='done';
 const changed=groupFleet(input);
 assert.equal(changed.nodes.find(n=>n.id===action.id).count,2);
 assert.equal(changed.links.find(e=>e.source==='action:owner'&&e.relation==='has status').target,changed.nodes.find(n=>n.label==='Done').id);
});

test('status changes do not reposition individual ideas and actions',()=>{
 const changed=structuredClone(data);changed.nodes[2].state='done';changed.nodes[3].state='dismissed';
 const placement=result=>result.nodes.filter(n=>n.kind!=='status').map(({id,clusterX,clusterY})=>({id,clusterX,clusterY}));
 assert.deepEqual(placement(groupFleet(changed)),placement(groupFleet(data)));
});
test('status links are visible without exerting clustering force',()=>{
 let strength,distance;
 const force={strength(value){strength=value;return this;},distance(value){distance=value;return this;}};
 configureFleetLinks({d3Force:()=>force});
 assert.equal(strength({grouping:true}),0);
 assert.equal(strength({relation:'produced'}),.035);
 assert.equal(distance,220);
 assert.ok(groupFleet(data).links.some(link=>link.grouping));
});

test('status nodes use a uniform blue-gray and concise labels',()=>{
 const statuses=groupFleet(data).nodes.filter(n=>n.kind==='status');
 assert.deepEqual(statuses.map(n=>n.label),['In Review','Suggested']);
 assert.ok(statuses.every(n=>n.color==='#94a3b8'));
});
test('status groups honor the entity catalog color',()=>{
 assert.ok(groupFleet(data,{statusColor:'#abcdef'}).nodes.filter(n=>n.kind==='status').every(n=>n.color==='#abcdef'));
});
