const {test}=require('node:test');
const assert=require('node:assert/strict');
const Queue=require('../static/js/hfl-board-state.js');
const board={id:'map-test',version:1,name:'Test',drafts:[],edges:[]};
test('edits during an in-flight save are serialized against the acknowledged version',async()=>{
  let release;const calls=[];
  const q=new Queue(board,async fields=>{calls.push(fields);if(calls.length===1)await new Promise(r=>release=r);return {...board,...fields,version:fields.version+1};},null,()=>{},10000);
  q.edit({drafts:[{id:'a'}]});const save=q.flush();
  q.edit({drafts:[{id:'a'},{id:'b'}]});release();await save;
  assert.deepEqual(calls.map(c=>c.version),[1,2]);assert.equal(q.value.drafts.length,2);assert.equal(q.dirty,false);
});
test('failed saves retain newer edits and can retry without losing content',async()=>{
  let fail=true;
  const q=new Queue(board,async fields=>{if(fail)throw Error('offline');return {...board,...fields,version:2};},async()=>board,()=>{},10000);
  q.edit({name:'First'});await assert.rejects(q.flush(),/offline/);
  q.edit({name:'Latest'});assert.equal(q.dirty,true);fail=false;await q.flush();
  assert.equal(q.value.name,'Latest');assert.equal(q.dirty,false);
});
test('conflicts never overwrite a newer remote revision',async()=>{
  let calls=0;
  const q=new Queue(board,async()=>{calls++;throw Error('conflict');},async()=>({...board,version:2,name:'Someone else'}),()=>{},10000);
  q.edit({name:'Mine'});await assert.rejects(q.flush());await assert.rejects(q.flush(),/changed elsewhere/);
  assert.equal(calls,1);assert.equal(q.value.name,'Mine');assert.equal(q.dirty,true);
});
test('lost responses reconcile only the exact committed fields before retrying',async()=>{
  let remote=board,fail=true;
  const q=new Queue(board,async fields=>{remote={...remote,...fields,version:remote.version+1};if(fail){fail=false;throw Error('lost response');}return remote;},async()=>remote,()=>{},10000);
  q.edit({name:'Committed'});await assert.rejects(q.flush());q.edit({name:'Newer'});await q.flush();
  assert.equal(remote.name,'Newer');assert.equal(remote.version,3);assert.equal(q.dirty,false);
});
