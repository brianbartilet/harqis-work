import {forceCollide, forceX, forceY} from 'd3-force-3d';

// Preserve preset spacing while letting connected nodes follow elastically.
const originalLinkStrength=new WeakMap();
export function configureDragForces(graph,localDrag=false) {
  const linkForce=graph.d3Force('link');
  if(!originalLinkStrength.has(linkForce))originalLinkStrength.set(linkForce,linkForce.strength());
  linkForce.strength(localDrag?.06:originalLinkStrength.get(linkForce));
  graph.d3Force('charge').strength(localDrag?0:-230);
  graph.d3Force('link').distance(localDrag?link=>Math.max(30,Math.hypot(link.source.x-link.target.x,link.source.y-link.target.y)):105);
  graph.d3Force('collide',forceCollide(n=>n.radius+(localDrag?4:30)).iterations(2));
  graph.d3Force('x',localDrag?null:forceX(n=>n.clusterX||0).strength(.065));
  graph.d3Force('y',localDrag?null:forceY(n=>n.clusterY||0).strength(.065));
  if(localDrag){
    // Presets are not a force-equilibrium layout: reheating must not contract
    // every link to 105 or pull the entire graph back to the old cluster centers.
    graph.d3Force('center',null);
    graph.d3Force('drag-damping',dragDamping());
  }else{
    graph.d3Force('drag-damping',null);
  }
}

export function dragDamping(){
  let nodes=[];
  const force=()=>{for(const n of nodes){
    if(!n.dragOrigin)continue;
    const weight=n.dragWeight??1;
    const parent=n.dragParent,origin=n.dragParentOrigin;
    const px=parent&&origin?(parent.fx??parent.x)-origin.x:0;
    const py=parent&&origin?(parent.fy??parent.y)-origin.y:0;
    // The resting position travels with the parent: no fixed 120-unit leash.
    // Springs and collision response allow lag, overshoot and independent motion.
    const targetX=n.dragOrigin.x+px*.9*weight,targetY=n.dragOrigin.y+py*.9*weight;
    n.vx=n.vx*.94+(targetX-n.x)*.22;
    n.vy=n.vy*.94+(targetY-n.y)*.22;
    const dx=n.x+n.vx-n.dragOrigin.x,dy=n.y+n.vy-n.dragOrigin.y;
    const distance=Math.hypot(dx,dy),reach=(Math.hypot(px,py)+120)*weight;
    if(distance>reach){
      n.vx=n.dragOrigin.x+dx/distance*reach-n.x;
      n.vy=n.dragOrigin.y+dy/distance*reach-n.y;
    }
    // Clamp after correcting the envelope so reversing a drag cannot teleport nodes.
    const speed=Math.hypot(n.vx,n.vy),maxSpeed=24*weight;
    if(speed>maxSpeed){n.vx*=maxSpeed/speed;n.vy*=maxSpeed/speed;}
  }};
  force.initialize=value=>{nodes=value;};
  return force;
}

export function releaseDragNeighbors(node,nodes,edges,released,parentOrigin={x:node.x,y:node.y}) {
  const endpoint=value=>typeof value==='object'?value.id:value;
  const adjacency=new Map(nodes.map(n=>[n.id,[]]));
  for(const edge of edges){
    const a=endpoint(edge.source),b=endpoint(edge.target);
    if(adjacency.has(a)&&adjacency.has(b)){
      adjacency.get(a).push(b);adjacency.get(b).push(a);
    }
  }
  // A child can connect several hubs. Releasing only immediate neighbors leaves
  // its other springs attached to rigid nodes, so the connected group cannot relax.
  const connected=new Map([[node.id,0]]),queue=[node.id];
  for(let i=0;i<queue.length;i++)for(const id of adjacency.get(queue[i])||[]){
    if(!connected.has(id)){connected.set(id,connected.get(queue[i])+1);queue.push(id);}
  }
  released.delete(node);
  for(const other of nodes)if(other.id!==node.id&&connected.has(other.id)){
    other.dragOrigin={x:other.x,y:other.y};
    other.dragParent=node;other.dragParentOrigin={...parentOrigin};
    other.dragWeight=Math.pow(.5,connected.get(other.id)-1);
    other.vx=other.vy=0;
    delete other.fx;delete other.fy;other.manual=false;released.add(other);
  }
}

export function settleDragNodes(nodes,targets,offsetFor=()=>({x:0,y:0})) {
  for(const node of nodes){
    node.fx=node.x;node.fy=node.y;node.vx=node.vy=0;
    const target={...targets.get(node.id),x:node.x,y:node.y};
    // Recover the resting position underneath the current animation offset.
    // Otherwise resuming motion adds the offset a second time and causes a jump.
    for(let i=0;i<8;i++){
      const offset=offsetFor(node,target);
      target.x=node.x-offset.x;target.y=node.y-offset.y;
    }
    targets.set(node.id,target);
    delete node.dragOrigin;delete node.dragWeight;delete node.dragParent;delete node.dragParentOrigin;
  }
}
