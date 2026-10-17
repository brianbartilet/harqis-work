import test from 'node:test';
import assert from 'node:assert/strict';
import {graphDateRange} from '../src/graph-dates.mjs';

test('this week includes Monday through today, across month and year boundaries', () => {
  for (const [year, month, day, since, until] of [
    [2026,10,19,'2026-10-19','2026-10-19'],
    [2026,10,25,'2026-10-19','2026-10-25'],
    [2026,10,21,'2026-10-19','2026-10-21'],
    [2026,1,1,'2025-12-29','2026-01-01'],
    [2024,3,1,'2024-02-26','2024-03-01'],
  ]) assert.deepEqual(graphDateRange('week', new Date(year,month-1,day,12)), {since,until});
});

test('local calendar dates survive DST changes and UTC date boundaries', () => {
  const previous=process.env.TZ;
  try {
    process.env.TZ='America/New_York';
    assert.deepEqual(graphDateRange('week',new Date('2026-03-09T03:30:00Z')), {since:'2026-03-02',until:'2026-03-08'});
    assert.deepEqual(graphDateRange('week',new Date('2026-11-02T04:30:00Z')), {since:'2026-10-26',until:'2026-11-01'});
    process.env.TZ='Asia/Singapore';
    assert.deepEqual(graphDateRange('week',new Date('2026-10-18T16:30:00Z')), {since:'2026-10-19',until:'2026-10-19'});
  } finally {if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous;}
});

test('rolling windows remain inclusive and fixed dates remain untouched', () => {
  const now=new Date(2026,0,2,12);
  assert.deepEqual(graphDateRange('7',now), {since:'2025-12-27',until:'2026-01-02'});
  for(const mode of ['0','invalid','-1',null])assert.equal(graphDateRange(mode,now),null);
  assert.equal(now.getDate(),2);
});
