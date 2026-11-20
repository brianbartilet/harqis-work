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
test('discovered schedules survive date filters and retain both linked agents',()=>{
  const schedule={id:'schedule',kind:'schedule',entity:true,agent_ids:['a','b'],label:'Morning briefing',workspace_ids:[]};
  const result=filterFleet({...data,nodes:[...data.nodes,schedule],edges:[...data.edges,{source:'agent:a',target:'schedule'},{source:'agent:b',target:'schedule'}]}, {types:['schedule'],since:'2030-01-01'});
  assert.deepEqual(result.nodes.map(n=>n.id),['agent:a','agent:b','schedule']);
  assert.equal(result.links.length,2);
});
test('configured skills remain visible when filtering recent work',()=>{
  const skill={id:'skills:shared',kind:'skill',definition:true,agent_ids:['a'],label:'Review',workspace_ids:[]};
  const result=filterFleet({...data,nodes:[...data.nodes,skill]}, {types:['skill'],since:'2030-01-01'});
  assert.ok(result.nodes.some(n=>n.id===skill.id));
  assert.ok(!filterFleet({...data,nodes:[...data.nodes,skill]}, {types:['file'],since:'2030-01-01'}).nodes.some(n=>n.id===skill.id));
});
test('output search retains its parent and removes dangling edges',()=>{
  const result=filterFleet(data,{query:'release',types:['file','task']});
  assert.deepEqual(result.nodes.map(n=>n.id),['agent:a','report']);
  assert.deepEqual(result.links,[data.edges[0]]);
});
test('date range applies to work and preserves agents without matching activity',()=>{
  const result=filterFleet(data,{since:'2026-10-01',until:'2026-10-27',types:['file','task','configuration']});
  assert.deepEqual(result.nodes.map(n=>n.id),['agent:a','agent:b','report']);
});
test('Space and service filters compose without leaking other outputs',()=>{
  assert.deepEqual(filterFleet(data,{spaces:['work'],service:'codex',types:['file','task']}).nodes.map(n=>n.id),['agent:b']);
  assert.deepEqual(filterFleet(data,{spaces:['work'],types:['file']}).nodes.map(n=>n.id),['agent:a','agent:b','report']);
});

test('orb radii mirror Activity Graph and shrink when connections are filtered',()=>{
  const all=filterFleet(data,{types:['file','task','configuration']});
  const agent=all.nodes.find(n=>n.id==='agent:a');
  assert.equal(agent.visibleDegree,2);
  assert.equal(agent.radius,16+4*Math.log2(3));
  const narrowed=filterFleet(data,{types:['file']});
  assert.equal(narrowed.nodes.find(n=>n.id==='agent:a').radius,20);
  assert.ok(agent.radius>narrowed.nodes.find(n=>n.id==='agent:a').radius);
  assert.equal(narrowed.nodes.find(n=>n.id==='agent:b').radius,16);
  assert.equal(data.nodes[0].radius,undefined,'source records stay unchanged');
});


test('fleet outputs use compact activity radii at both density thresholds',()=>{
  assert.equal(filterFleet(data,{types:['file']}).nodes.find(n=>n.id==='report').radius,7);
  const dense={agents:data.agents,nodes:[data.nodes[0],...Array.from({length:35},(_,i)=>({id:'hud:'+i,kind:'hud',agent_ids:['a'],label:'HUD '+i}))],edges:Array.from({length:35},(_,i)=>({source:'agent:a',target:'hud:'+i,relation:'monitors'}))};
  const result=filterFleet(dense,{types:['hud']});
  assert.equal(result.nodes.find(n=>n.kind==='hud').radius,4.5);
  assert.equal(result.nodes.find(n=>n.kind==='agent').radius,16+4*Math.log2(36));
  assert.equal(filterFleet(dense,{types:[]}).nodes[0].radius,16);
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
test('Last 24 hours uses exact rolling bounds and preserves intents',()=>{
 const now=Date.parse('2026-11-15T10:00:00Z');
 const data={agents:[],nodes:[['boundary','2026-11-14T10:00:00Z'],['old','2026-11-14T09:59:59Z'],['now','2026-11-15T10:00:00Z'],['future','2026-11-15T10:00:01Z']].map(([id,created])=>({id,created,kind:'entry'})).concat([{id:'action',kind:'action',created:'2020-01-01'}]),edges:[]};
 assert.deepEqual(filterFleet(data,{types:['entry','action'],range:'24h',now}).nodes.map(n=>n.id),['boundary','now','action']);
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

test('Today starts at local midnight rather than 24 hours ago',()=>{
 const now=new Date(2026,10,15,10,0,0).getTime(),midnight=new Date(2026,10,15).getTime();
 const data={agents:[],edges:[],nodes:[['yesterday',midnight-1],['midnight',midnight],['now',now],['future',now+1]].map(([id,time])=>({id,created:new Date(time).toISOString(),kind:'entry'}))};
 assert.deepEqual(filterFleet(data,{types:['entry'],range:'today',now}).nodes.map(n=>n.id),['midnight','now']);
 assert.deepEqual(filterFleet(data,{types:['entry'],range:'24h',now}).nodes.map(n=>n.id),['yesterday','midnight','now']);
});


test('connected n8n agent with no outputs remains in the main fleet',()=>{
 const input={agents:[...data.agents,{id:'n8n',active:true,runtime:'n8n'},{id:'disabled',active:false,runtime:'n8n'}],nodes:[...data.nodes,{id:'agent:n8n',agent_id:'n8n',kind:'agent',label:'Butler n8n',workspace_ids:[]},{id:'agent:disabled',agent_id:'disabled',kind:'agent',label:'Disabled'}],edges:data.edges};
 const options={spaces:['other'],since:'2099-01-01',types:[]};
 assert.deepEqual(filterFleet(input,options).nodes.map(n=>n.id),['agent:a','agent:b','agent:n8n']);
 assert.deepEqual(filterFleet(input,{...options,query:'n8n'}).nodes.map(n=>n.id),['agent:n8n']);
 assert.deepEqual(filterFleet(input,{...options,service:'n8n'}).nodes.map(n=>n.id),['agent:n8n']);
});


test('n8n definitions survive dates and hide archived or inactive workflows on demand',()=>{
 const input={agents:[{id:'a',active:true}],nodes:[{id:'agent:a',agent_id:'a',kind:'agent'},...['active','inactive','archived'].map(state=>({id:state,kind:'workflow',source:'n8n',state,agent_ids:['a'],workspace_ids:[],created:'2020-01-01'}))],edges:[]};
 const filters={types:['workflow'],since:'2099-01-01',spaces:['other']};
 assert.equal(filterFleet(input,filters).nodes.length,4);
 assert.deepEqual(filterFleet(input,{...filters,hideInactiveWorkflows:true,hideArchivedWorkflows:true}).nodes.map(n=>n.id),['agent:a','active']);
});
test('childless agent and owner are larger than entities in dense graphs',()=>{
 const input={agents:[{id:'a',active:true}],nodes:[{id:'agent:a',agent_id:'a',kind:'agent'},{id:'owner',kind:'owner'},...Array.from({length:40},(_,i)=>({id:'entry'+i,kind:'entry'}))],edges:[]};
 const result=filterFleet(input,{types:['entry']});
 assert.equal(result.nodes.find(n=>n.kind==='agent').radius,16);
 assert.equal(result.nodes.find(n=>n.kind==='owner').radius,16);
 assert.equal(result.nodes.find(n=>n.kind==='entry').radius,4.5);
});


test('connector hubs have their own type filter without hiding their workflows or real agents',()=>{
 const input={agents:[{id:'library',active:true,n8n_library:true,runtime:'n8n'},{id:'butler',active:true,runtime:'n8n'}],nodes:[{id:'agent:library',agent_id:'library',agent_ids:['library'],kind:'connector',source:'n8n',label:'n8n',workspace_ids:[]},{id:'agent:butler',agent_id:'butler',kind:'agent',label:'Butler'},{id:'workflow',kind:'workflow',source:'n8n',agent_ids:['library'],workspace_ids:[]}],edges:[{source:'agent:library',target:'workflow'},{source:'agent:library',target:'agent:butler'}]};
 const options={types:['connector','workflow'],since:'2099-01-01',spaces:['work'],service:'n8n'};
 const visible=filterFleet(input,options);
 assert.equal(visible.nodes.filter(n=>n.kind==='agent').length,1);
 assert.equal(visible.nodes.filter(n=>n.kind==='connector').length,1);
 assert.equal(visible.links.length,2);
 const hidden=filterFleet(input,{...options,types:['workflow']});
 assert.deepEqual(hidden.nodes.map(n=>n.id),['agent:butler','workflow']);
 assert.equal(hidden.links.length,0);
});
