import test from 'node:test';
import assert from 'node:assert/strict';
import {shareTimeline, timelineBounds} from '../src/share-timeline.mjs';

const nodes = [
  {id:'daily:2026-01-01', kind:'daily', label:'2026-01-01'},
  {id:'daily:2026-10-07', kind:'daily', label:'2026-10-07'},
  {id:'old', kind:'entries', label:'Old entry', date:'2026-01-01 12:00'},
  {id:'morning', kind:'entries', label:'Morning', date:'2026-10-07 08:00'},
  {id:'latest', kind:'entries', label:'Latest', date:'2026-10-07 18:00'},
  {id:'person', kind:'people', label:'Person'},
  {id:'isolated', kind:'ideas', label:'Unlinked idea'},
];
const edges = [
  ['old','daily:2026-01-01'], ['morning','daily:2026-10-07'],
  ['latest','daily:2026-10-07'], ['latest','person'], ['old','person'],
].map(([source,target]) => ({source,target}));

test('latest entry, date and direct entities define the fit, not a calendar window', () => {
  const layout = shareTimeline(nodes, edges);
  assert.equal(layout.focusId, 'latest');
  assert.deepEqual([...layout.fitIds].sort(), ['daily:2026-10-07','latest','person']);
  const positioned = nodes.map(n => ({...n, ...layout.positions.get(n.id)}));
  const bounds = timelineBounds(positioned, layout.fitIds);
  for (const n of positioned.filter(n => layout.fitIds.has(n.id))) {
    assert.ok(n.x > bounds.left && n.x < bounds.right);
    assert.ok(n.y > bounds.top && n.y < bounds.bottom);
  }
});

test('date columns are ordered and equally spaced despite calendar gaps', () => {
  const {positions} = shareTimeline(nodes, edges);
  assert.equal(positions.get('daily:2026-01-01').y, 0);
  assert.equal(positions.get('daily:2026-10-07').y, 0);
  assert.equal(positions.get('daily:2026-10-07').x - positions.get('daily:2026-01-01').x, 280);
  assert.ok(positions.get('latest').y < 0);
  assert.ok(positions.get('person').y > 0);
  assert.equal(positions.size, nodes.length);
  assert.equal(new Set([...positions.values()].map(p => `${p.x},${p.y}`)).size, nodes.length);
});

test('older snapshots, date-only graphs and missing dates have safe fallbacks', () => {
  const legacy = shareTimeline(nodes.map(({date, ...n}) => n), edges);
  assert.ok(['morning','latest'].includes(legacy.focusId));
  assert.equal(shareTimeline(nodes.filter(n => n.kind === 'daily'), []).focusId, 'daily:2026-10-07');
  assert.equal(shareTimeline(nodes.filter(n => n.kind !== 'daily'), []), null);
  assert.equal(shareTimeline([], []), null);
});
