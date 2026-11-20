import test from 'node:test';
import assert from 'node:assert/strict';
import {fleetMotionOffset} from './fleet-motion.mjs';
import {motionOffset} from './graph-presets.mjs';

test('Fleet drift remains noticeable and bounded at every zoom',()=>{
 for(const zoom of [.05,.25,1,3]){
  const start=fleetMotionOffset('drift',{x:100,y:50},0,0,zoom);
  const next=fleetMotionOffset('drift',{x:100,y:50},1000,0,zoom);
  assert.ok(Math.hypot(next.x-start.x,next.y-start.y)*zoom>12);
  for(let t=0;t<32000;t+=100){
   const p=fleetMotionOffset('drift',{x:100,y:50},t,1,zoom);
   assert.ok(Math.abs(p.x*zoom)<=18&&Math.abs(p.y*zoom)<=14);
  }
 }
});
test('Off restores base positions and other modes retain existing motion',()=>{
 for(const mode of ['off','breathing','ripple'])assert.deepEqual(fleetMotionOffset(mode,{x:100,y:50},1500,1,.1),motionOffset(mode,{x:100,y:50},1500,1));
});
