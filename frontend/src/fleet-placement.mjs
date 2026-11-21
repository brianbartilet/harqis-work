import {isFleetAnchor} from './fleet-drag.mjs';
import {phaseFor} from './graph-presets.mjs';

// Existing coordinates win. Only arrivals get a new, collision-free position.
export function placeFleetNodes(input,positions={},zoom=1){
 const scale=Number.isFinite(zoom)&&zoom>0?zoom:1;
 const valid=p=>Number.isFinite(p?.x)&&Number.isFinite(p?.y);
 const nodes=input.map((n,i)=>{
  const prior=valid(positions[n.id])?positions[n.id]:null,phase=phaseFor(n.id);
  const point=prior||{x:(n.clusterX??0)+(isFleetAnchor(n)?0:100*Math.cos(phase+i)),y:(n.clusterY??0)+(isFleetAnchor(n)?0:100*Math.sin(phase+i))};
  const node={...n,...point};
  if(prior||isFleetAnchor(n)){node.fx=node.x;node.fy=node.y;}
  return node;
 });
 const settled=nodes.filter(n=>valid(positions[n.id]));
 if(!settled.length)return nodes; // The first layout still uses the normal simulation.
 const occupied=nodes.filter(n=>valid(positions[n.id])||isFleetAnchor(n));
 const median=values=>{values.sort((a,b)=>a-b);return values[Math.floor(values.length/2)];};
 for(const n of nodes.filter(n=>!valid(positions[n.id])&&!isFleetAnchor(n)).sort((a,b)=>a.id.localeCompare(b.id))){
  const siblings=settled.filter(p=>p.kind===n.kind&&p.groupParent===n.groupParent);
  const peers=siblings.length?siblings:settled.filter(p=>p.kind===n.kind);
  const parent=nodes.find(p=>p.id===n.groupParent);
  let center;
  if(peers.length){
   const middle={x:median(peers.map(p=>p.x)),y:median(peers.map(p=>p.y))};
   // Use an actual cluster member, not empty space between separated clusters.
   center=peers.reduce((best,p)=>Math.hypot(p.x-middle.x,p.y-middle.y)<Math.hypot(best.x-middle.x,best.y-middle.y)?p:best);
  }else if(parent){
   const angle=Math.atan2((n.clusterY??0)-(parent.clusterY??0),(n.clusterX??0)-(parent.clusterX??0));
   center={x:parent.x+120/scale*Math.cos(angle),y:parent.y+120/scale*Math.sin(angle)};
  }else center=settled[0];
  const step=Math.max(24,(n.radius||5)*2+10)/scale,phase=phaseFor(n.id);
  let point;
  for(let i=0;i<2048;i++){
   const angle=phase+i*2.399963229728653,reach=step*Math.sqrt(i);
   point={x:center.x+reach*Math.cos(angle),y:center.y+reach*Math.sin(angle)};
   if(occupied.every(p=>Math.hypot(point.x-p.x,point.y-p.y)>=((n.radius||5)+(p.radius||5)+8)/scale))break;
  }
  Object.assign(n,point,{fx:point.x,fy:point.y});
  occupied.push(n);
 }
 return nodes;
}
