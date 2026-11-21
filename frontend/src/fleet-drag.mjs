import {releaseDragNeighbors} from './graph-drag.mjs';
export const isFleetAnchor=node=>['owner','agent','connector','status'].includes(node.kind);
export const isFleetFixed=node=>isFleetAnchor(node)||!!node.manual||!!node.pinned;
export function pinFleetAnchors(nodes,except){
 for(const node of nodes){
  if(!isFleetFixed(node)||node===except)continue;
  node.fx=node.x;node.fy=node.y;node.vx=node.vy=0;
 }
}
export function releaseFleetNeighbors(node,nodes,links,released,origin){
 pinFleetAnchors(nodes,node);
 // Fixed hubs are traversal boundaries, so a child cannot drag another cluster.
 const movable=nodes.filter(n=>!isFleetFixed(n)||n===node);
 releaseDragNeighbors(node,movable,links,released,origin);
}
