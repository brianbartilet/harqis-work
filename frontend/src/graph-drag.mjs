import {forceCollide, forceX, forceY} from 'd3-force-3d';

// Preserve preset spacing while letting connected nodes follow elastically.
const originalLinkStrength=new WeakMap();
export function configureDragForces(graph,localDrag=false,response=1,{screenSpace=false}={}) {
  const linkForce=graph.d3Force('link');
  if(!originalLinkStrength.has(linkForce))originalLinkStrength.set(linkForce,linkForce.strength());
  linkForce.strength(localDrag?.06:originalLinkStrength.get(linkForce));
  graph.d3Force('charge').strength(localDrag?0:-230);
  graph.d3Force('link').distance(localDrag?link=>Math.max(30,Math.hypot(link.source.x-link.target.x,link.source.y-link.target.y)):105);
  // Apply attraction before collisions, and the speed limiter after collisions.
  graph.d3Force('collide',null);graph.d3Force('drag-damping',null);
  graph.d3Force('drag-follow',localDrag?dragFollow(Math.max(.02,graph.zoom?.()||1),response):null);
  const scale=localDrag?Math.max(.02,graph.zoom?.()||1):1;
  graph.d3Force('collide',forceCollide(n=>(n.radius+(localDrag?12:30))/scale).iterations(localDrag?3:2));
  graph.d3Force('x',localDrag?null:forceX(n=>n.clusterX||0).strength(.065));
  graph.d3Force('y',localDrag?null:forceY(n=>n.clusterY||0).strength(.065));
  if(localDrag){
    // Presets are not a force-equilibrium layout: reheating must not contract
    // every link to 105 or pull the entire graph back to the old cluster centers.
    graph.d3Force('center',null);
    graph.d3Force('drag-damping',dragDamping(response,screenSpace?Math.max(.000001,graph.zoom?.()||1):1));
  }else{
    graph.d3Force('drag-damping',null);
  }
}


// Nearby children orbit a spring's rest distance from the actual parent.
// Their bearing is free to change, so collisions can deflect their path.
export function dragFollow(scale=1,response=1){
  let nodes=[];
  const force=()=>{for(const n of nodes){
    if(!n.dragOrigin||!n.dragParent)continue;
    const parent=n.dragParent,origin=n.dragParentOrigin,weight=n.dragWeight??1;
    const parentX=parent.fx??parent.x,parentY=parent.fy??parent.y;
    const px=parentX-origin.x,py=parentY-origin.y;
    if(weight===1){
      const initial=Math.hypot(n.dragOrigin.x-origin.x,n.dragOrigin.y-origin.y);
      const progress=1-Math.exp(-Math.hypot(px,py)/100);
      const rest=initial+(Math.min(initial,Math.max(105,((parent.radius||12)+(n.radius||7)+30)/scale))-initial)*progress;
      const dx=parentX-n.x,dy=parentY-n.y,distance=Math.hypot(dx,dy)||1;
      const pull=(distance-rest)/distance*.10*response;
      n.vx+=dx*pull;n.vy+=dy*pull;
    }else{
      // Weak support for the rest of the connected graph avoids rigid shared hubs.
      n.vx+=(n.dragOrigin.x+px*.9*weight-n.x)*.06*response;
      n.vy+=(n.dragOrigin.y+py*.9*weight-n.y)*.06*response;
    }
  }};
  force.initialize=value=>{nodes=value;};return force;
}

export function dragDamping(response=1,scale=1){
  let nodes=[];
  const force=()=>{for(const n of nodes){
    if(!n.dragOrigin)continue;
    const weight=n.dragWeight??1;
    const parent=n.dragParent,origin=n.dragParentOrigin;
    const px=parent&&origin?(parent.fx??parent.x)-origin.x:0;
    const py=parent&&origin?(parent.fy??parent.y)-origin.y:0;
    const dx=n.x+n.vx-n.dragOrigin.x,dy=n.y+n.vy-n.dragOrigin.y;
    const distance=Math.hypot(dx,dy),reach=(Math.hypot(px,py)+120/scale+(weight===1?Math.hypot(n.dragOrigin.x-origin.x,n.dragOrigin.y-origin.y)*(1-Math.exp(-Math.hypot(px,py)/100)):0))*weight;
    if(distance>reach){
      n.vx=n.dragOrigin.x+dx/distance*reach-n.x;
      n.vy=n.dragOrigin.y+dy/distance*reach-n.y;
    }
    // Clamp after correcting the envelope so reversing a drag cannot teleport nodes.
    const speed=Math.hypot(n.vx,n.vy),maxSpeed=24*weight*response/scale;
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
