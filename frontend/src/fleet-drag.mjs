import {releaseDragNeighbors} from './graph-drag.mjs';
import {fleetParents,isFleetParent} from './fleet-parent.mjs';
export const isFleetAnchor=node=>['owner','agent','connector','status'].includes(node.kind);
export function pinFleetAnchors(nodes,except){
 for(const node of nodes){
  if(!isFleetAnchor(node)||node===except)continue;
  node.fx=node.x;node.fy=node.y;node.vx=node.vy=0;
 }
}
export function releaseFleetNeighbors(node,nodes,links,released,origin){
 pinFleetAnchors(nodes,node);
 if(!isFleetParent(node))return;
 const parents=fleetParents(nodes,links);
 const movable=nodes.filter(n=>n===node||(!n.manual&&!n.pinned&&parents.get(n.id)===node.id));
 const owned=movable.filter(n=>n!==node).map(n=>({source:node.id,target:n.id}));
 releaseDragNeighbors(node,movable,owned,released,origin);
}

// Fleet dragging translates a cluster, rather than reheating the global graph.
// Keeping offsets exact makes reversal and tiny camera scales equally responsive.
export function translateFleetChildren(parent,nodes,parents,delta){
 if(!isFleetParent(parent))return [];
 const moved=[];
 for(const n of nodes){
  if(n.manual||n.pinned||parents.get(n.id)!==parent.id)continue;
  n.x+=delta.x;n.y+=delta.y;n.fx=n.x;n.fy=n.y;n.vx=n.vy=0;moved.push(n);
 }
 return moved;
}
