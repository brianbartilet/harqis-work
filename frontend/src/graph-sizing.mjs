// Shared Activity Graph sizing, based on edges remaining after filtering.
export function connectionRadius(kind, visibleDegree, nodeCount) {
  const smallGraph=nodeCount<=35;
  if(kind==='entries'||kind==='entry')return smallGraph?7:4.5;
  return (smallGraph?10:4)+4*Math.log2(1+Math.max(0,visibleDegree));
}
