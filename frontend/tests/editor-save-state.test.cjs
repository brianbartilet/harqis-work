const {test}=require('node:test');
const assert=require('node:assert/strict');
const State=require('../static/js/hfl-editor-state.js');

test('simultaneous flushes share the in-flight write and acknowledge its result',async()=>{
  let value='before',release,calls=0,locked=false;
  const state=new State({snapshot:()=>value,exists:()=>true,valid:()=>true,status:()=>{},lock:x=>locked=x,
    save:async()=>{calls++;await new Promise(r=>release=r);}});
  value='after';const first=state.flush(),second=state.flush();
  assert.equal(locked,true);release();await Promise.all([first,second]);
  assert.equal(calls,1);assert.equal(state.dirty,false);assert.equal(locked,false);
});
test('failed save retains dirty state, requires retry, and never acknowledges a conflict',async()=>{
  let value='saved',fail=true;
  const state=new State({snapshot:()=>value,exists:()=>true,valid:()=>true,status:()=>{},lock:()=>{},
    save:async()=>{if(fail)throw Error('version conflict');}});
  value='edit';await assert.rejects(state.flush(),/version conflict/);
  assert.equal(state.saved,'saved');assert.equal(state.dirty,true);
  state.changed();assert.equal(state.timer,null);
  fail=false;await state.flush();assert.equal(state.dirty,false);
});
test('new drafts and invalid forms are never autosaved',async()=>{
  let value='',calls=0;
  const state=new State({snapshot:()=>value,exists:()=>false,valid:()=>false,status:()=>{},lock:()=>{},save:async()=>calls++});
  value='draft';state.changed();assert.equal(state.timer,null);
  await assert.rejects(state.flush(),/required fields/);assert.equal(calls,0);
});
test('typing during a slow write is saved separately against the next version',async()=>{
  let value='before',release,version=1;const writes=[];
  const state=new State({snapshot:()=>value,exists:()=>true,valid:()=>true,status:()=>{},lock:()=>{},
    save:async()=>{writes.push({value,version});if(writes.length===1)await new Promise(r=>release=r);version++;}});
  value='first';const saving=state.flush();value='second';state.changed();release();await saving;
  assert.deepEqual(writes,[{value:'first',version:1},{value:'second',version:2}]);assert.equal(state.dirty,false);
});
