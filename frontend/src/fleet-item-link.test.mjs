import test from 'node:test';
import assert from 'node:assert/strict';
import {fleetItemLink} from './fleet-item-link.mjs';
test('action links open only the recorded action editor, not the execution dialog',()=>{
 const result=fleetItemLink({kind:'action',url:'/hfl-corpus/actions?integration_agent=item-123'});
 assert.equal(result.label,'Open action');
 const url=new URL(result.href,'https://fleet.test');
 assert.equal(url.searchParams.get('edit'),'item-123');assert.equal(url.searchParams.get('edit_kind'),'actionable');assert.equal(url.searchParams.get('integration_agent'),null);
});
test('idea and entry links retain their recorded identities',()=>{
 assert.deepEqual(fleetItemLink({kind:'idea',url:'/hfl-corpus/graph?edit=idea-123'}),{label:'Open idea',href:'/hfl-corpus/graph?edit=idea-123&edit_kind=idea',external:false});
 assert.deepEqual(fleetItemLink({kind:'entry',url:'/hfl-corpus/read?path=notes.md#entry-1'}),{label:'Open entry',href:'/hfl-corpus/read?path=notes.md#entry-1',external:false});
});
test('missing, simulated and unsafe URLs never become item links',()=>{
 for(const node of [null,{kind:'action'},{kind:'action',url:'/hfl-corpus/actions',mock:true},{url:'javascript:alert(1)'},{url:'//example.com'},{url:'https://'}])assert.equal(fleetItemLink(node),null);
 assert.equal(fleetItemLink({kind:'idea',url:'/hfl-corpus/graph'}).label,'Open source');
 assert.equal(fleetItemLink({kind:'file',url:'https://example.com/report'}).external,true);
});
