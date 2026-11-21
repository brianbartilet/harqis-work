// Fleet orbs and avatars have a constant screen size, unlike graph coordinates.
export function fleetFitView(nodes,width,height,padding=32){
 const points=nodes.filter(n=>Number.isFinite(n.x)&&Number.isFinite(n.y));
 if(!points.length||width<=0||height<=0)return null;
 const x=(Math.min(...points.map(n=>n.x))+Math.max(...points.map(n=>n.x)))/2;
 const y=(Math.min(...points.map(n=>n.y))+Math.max(...points.map(n=>n.y)))/2;
 let zoom=1;
 for(const n of points){
  const margin=(n.radius||7)+padding;
  if(n.x!==x)zoom=Math.min(zoom,Math.max(1,width/2-margin)/Math.abs(n.x-x));
  if(n.y!==y)zoom=Math.min(zoom,Math.max(1,height/2-margin)/Math.abs(n.y-y));
 }
 return {x,y,zoom:Math.max(.000001,zoom)};
}
