import test from 'node:test';
import assert from 'node:assert/strict';
import '../static/js/agent-avatar.js';

test('initials use the name before the role, handle multiword and Unicode names',()=>{
  const {initials}=globalThis.AgentAvatars;
  assert.equal(initials('Sage · Research partner'),'S');
  assert.equal(initials('Ada Lovelace · Developer'),'AL');
  assert.equal(initials('  HARQIS   Butler  '),'HB');
  assert.equal(initials('Élodie · Research'),'É');
  assert.equal(initials(''),'?');
});

test('accessible avatar label includes service and classification names',()=>{
  assert.equal(globalThis.AgentAvatars.label({name:'Sage · Research partner',runtime:'hermes',classification:'general'}),
    'Sage · Research partner · Hermes · General purpose');
});
