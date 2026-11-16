import {releaseDragNeighbors} from './graph-drag.mjs';
export const isFleetAnchor=node=>['owner','agent','connector'].includes(node.kind);
export function pinFleetAnchors(nodes,except){
 for(const node of nodes){
  if(!isFleetAnchor(node)||node===except)continue;
  node.fx=node.x;node.fy=node.y;node.vx=node.vy=0;
 }
}
export function releaseFleetNeighbors(node,nodes,links,released,origin){
 pinFleetAnchors(nodes,node);
 // Fixed hubs are traversal boundaries, so a child cannot drag another cluster.
 const movable=nodes.filter(n=>!isFleetAnchor(n)||n===node);
 releaseDragNeighbors(node,movable,links,released,origin);
}
