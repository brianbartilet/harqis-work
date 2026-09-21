import test from 'node:test';
import assert from 'node:assert/strict';
import {boardCurvature} from '../src/graph-curves.mjs';
const source={id:'a',x:0,y:0,radius:17};
const target={id:'b',x:200,y:0,radius:17};

test('curves adapt to orb positions and soften as orbs touch',()=>{
  const curve=boardCurvature({source,target});
  assert.ok(curve>0);
  assert.ok(boardCurvature({source,target:{...target,x:40}})<curve);
  assert.equal(boardCurvature({source,target:{...target,x:30}}),0);
  assert.equal(boardCurvature({source,target:{...target,x:0,y:200}}),curve);
  assert.ok(boardCurvature({source,target:{...target,x:2000}})*2000<=64);
});
test('reversing a link preserves its route and parallel lanes stay distinct',()=>{
  assert.equal(boardCurvature({source:target,target:source}),-boardCurvature({source,target}));
  assert.notEqual(boardCurvature({source,target},1,-.5),boardCurvature({source,target},1,.5));
});
test('unresolved and coincident endpoints do not produce invalid curves',()=>{
  assert.equal(boardCurvature({source:'a',target:'b'}),0);
  assert.equal(boardCurvature({source,target:{...target,x:0}}),0);
});
