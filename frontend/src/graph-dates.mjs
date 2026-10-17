// Calendar arithmetic stays in browser-local time, including DST transitions.
export function graphDateRange(mode, now = new Date()) {
  if (mode === '0') return null;
  const days = Number(mode);
  if (mode !== 'week' && (!Number.isInteger(days) || days < 1)) return null;
  const end = new Date(now), start = new Date(now);
  start.setDate(start.getDate() - (mode === 'week' ? (start.getDay() + 6) % 7 : days - 1));
  const date = value => [value.getFullYear(), String(value.getMonth() + 1).padStart(2, '0'), String(value.getDate()).padStart(2, '0')].join('-');
  return {since: date(start), until: date(end)};
}
