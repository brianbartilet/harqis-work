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
