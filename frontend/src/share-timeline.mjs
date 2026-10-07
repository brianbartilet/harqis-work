import {presetLayout} from './graph-presets.mjs';

const endpoint = value => typeof value === 'object' ? value.id : value;

// Reuse the Activity Graph's chronological anchors and scattered date clouds.
export function shareTimeline(nodes, edges) {
  const dates = nodes.filter(n => n.kind === 'daily').sort((a, b) =>
    (a.label || a.id).localeCompare(b.label || b.id));
  if (!dates.length) return null;
  const adjacent = new Map(nodes.map(n => [n.id, []]));
  for (const edge of edges) {
    const a = endpoint(edge.source), b = endpoint(edge.target);
    if (adjacent.has(a) && adjacent.has(b)) {
      adjacent.get(a).push(b); adjacent.get(b).push(a);
    }
  }
  // Nearest date wins; shared entities belong to the latest date on a tie.
  const queue = dates.slice().reverse().map(n => n.id);
  const owners = new Map(queue.map(id => [id, id]));
  for (let i = 0; i < queue.length; i++) {
    for (const id of adjacent.get(queue[i])) if (!owners.has(id)) {
      owners.set(id, owners.get(queue[i])); queue.push(id);
    }
  }
  const positions = presetLayout(nodes, edges, 'timeline').positions;
  // Older snapshots lack entry timestamps; use their linked date as a fallback.
  const dateLabels = new Map(dates.map(n => [n.id, n.label || n.id.replace(/^daily:/, '')]));
  const entryDate = node => node.date || dateLabels.get(owners.get(node.id)) || '';
  const latestEntry = nodes.filter(n => n.kind === 'entries').sort((a, b) => entryDate(b).localeCompare(entryDate(a)))[0];
  const focusId = latestEntry?.id || dates.at(-1).id;
  const fitIds = new Set([focusId, ...adjacent.get(focusId)]);
  return {positions, fitIds, focusId, hasEntry: !!latestEntry};
}

export function timelineBounds(nodes, fitIds) {
  const visible = nodes.filter(n => fitIds.has(n.id) && Number.isFinite(n.x) && Number.isFinite(n.y));
  if (!visible.length) return null;
  return visible.reduce((box, n) => ({
    left: Math.min(box.left, n.x - 90), right: Math.max(box.right, n.x + 90),
    top: Math.min(box.top, n.y - 50), bottom: Math.max(box.bottom, n.y + 50),
  }), {left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity});
}
