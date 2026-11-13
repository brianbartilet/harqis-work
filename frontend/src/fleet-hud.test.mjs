import test from 'node:test';
import assert from 'node:assert/strict';
import {linkedHudNodes,orderHudCards,moveHudCard} from './fleet-hud.mjs';
const nodes=[{id:'hud:radar',kind:'hud',summary:'workflows.radar',agent_ids:['butler']},{id:'feed:a',kind:'feed',agent_ids:['a']},{id:'other',kind:'file',agent_ids:['a']},{id:'feed:b',kind:'feed',agent_ids:['b']}];
test('HUD linkage uses agent relationships and exact configured workflow identities',()=>{
 assert.deepEqual(linkedHudNodes({id:'a',workflows:['celery:workflows.radar']},nodes).map(n=>n.id),['hud:radar','feed:a']);
 assert.deepEqual(linkedHudNodes({id:'b'},nodes).map(n=>n.id),['feed:b']);
 assert.deepEqual(linkedHudNodes({id:'butler'},nodes).map(n=>n.id),['hud:radar']);
});
test('saved ordering keeps all cards, appends new HUDs, and supports bounded moves',()=>{
 assert.deepEqual(orderHudCards(nodes,['feed:a','missing','hud:radar']).map(n=>n.id),['feed:a','hud:radar','other','feed:b']);
 assert.deepEqual(orderHudCards(nodes,['feed:a','hud:radar','feed:a']).map(n=>n.id),['feed:a','hud:radar','other','feed:b']);
 assert.deepEqual(moveHudCard(['a','b','c'],'a',1),['b','a','c']);
 assert.deepEqual(moveHudCard(['a','b'],'a',-1),['a','b']);
});
