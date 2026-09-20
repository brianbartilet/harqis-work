import test from 'node:test';
import assert from 'node:assert/strict';
import {readGraphState} from '../src/graph-state.mjs';

test('invalid, unavailable, and incompatible storage safely falls back',()=>{
  for(const value of [null,'broken','{}','{"version":2}'])assert.equal(readGraphState({getItem:()=>value},'view'),null);
  assert.equal(readGraphState({getItem:()=>{throw Error('blocked');}},'view'),null);
});

test('restoration rejects invalid coordinates and retains valid positions',()=>{
  const state={version:1,filters:{},enabled:['people',null],sources:['notes'],positions:{good:{x:30,y:40},bad:{x:1e30,y:0}},viewport:{x:0,y:0,zoom:-1}};
  const result=readGraphState({getItem:()=>JSON.stringify(state)},'view');
  assert.deepEqual(result.positions,{good:{x:30,y:40}});
  assert.equal(result.viewport,null);
  assert.deepEqual(result.enabled,['people']);
});


test('old Sources geometry is regenerated without discarding settings or other presets',()=>{
  const state={version:1,preset:'sources',filters:{search:'notes'},enabled:['sources'],sources:['notes'],positions:{s:{x:40,y:20}},viewport:{x:20,y:10,zoom:2}};
  const read=value=>readGraphState({getItem:()=>JSON.stringify(value)},'view');
  const migrated=read(state);
  assert.deepEqual(migrated.positions,{});assert.equal(migrated.viewport,null);
  assert.deepEqual(migrated.filters,state.filters);assert.deepEqual(migrated.sources,state.sources);
  assert.deepEqual(read({...state,preset:'people'}).positions,state.positions);
  assert.deepEqual(read({...state,layoutRevision:2}).positions,state.positions);
});


test('timeline layout upgrade retains filters and migrates only old geometry',()=>{
  const s={version:1,preset:'timeline',filters:{rolling:'90'},enabled:['daily','sources'],sources:[],positions:{d:{x:50,y:0}},viewport:{x:5,y:0,zoom:1},layoutRevision:2};
  const read=v=>readGraphState({getItem:()=>JSON.stringify(v)},'view');
  assert.deepEqual(read(s).positions,{});assert.equal(read(s).viewport,null);
  assert.deepEqual(read(s).filters,s.filters);
  assert.deepEqual(read({...s,layoutRevision:3}).positions,s.positions);
});
