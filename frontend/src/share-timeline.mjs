const endpoint = value => typeof value === 'object' ? value.id : value;

// Equal-width date columns keep sparse history readable without calendar gaps.
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
  const columns = new Map(dates.map((n, i) => [n.id, i * 280]));
  const groups = new Map();
  const positions = new Map(dates.map(n => [n.id, {x: columns.get(n.id), y: 0}]));
  for (const node of nodes) {
    if (node.kind === 'daily') continue;
    const owner = owners.get(node.id);
    const key = `${owner || 'undated'}:${node.kind === 'entries' ? 'entries' : 'entities'}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(node);
  }
  for (const group of groups.values()) {
    group.sort((a, b) => a.kind.localeCompare(b.kind) || (a.label || a.id).localeCompare(b.label || b.id) || a.id.localeCompare(b.id));
    group.forEach((node, i) => {
      const x = columns.get(owners.get(node.id)) ?? dates.length * 280;
      const direction = node.kind === 'entries' ? -1 : 1;
      positions.set(node.id, {x: x + (i % 2 ? 65 : -65), y: direction * (90 + Math.floor(i / 2) * 65)});
    });
  }
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
