import test from 'node:test';
import assert from 'node:assert/strict';
import {connectionRadius} from './graph-sizing.mjs';
test('matches existing small and large Activity Graph scaling',()=>{
 for(const count of [1,35,36,1000])for(const degree of [0,1,5,100]){
  assert.equal(connectionRadius('agent',degree,count),(count<=35?10:4)+4*Math.log2(1+degree));
 }
 assert.ok(connectionRadius('agent',100,50)>connectionRadius('agent',5,50));
});
test('activity entries retain the reference graph leaf sizing',()=>{
 for(const kind of ['entries','entry']){
  assert.equal(connectionRadius(kind,100,35),7);
  assert.equal(connectionRadius(kind,100,36),4.5);
 }
});
