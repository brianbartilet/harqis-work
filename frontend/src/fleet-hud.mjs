export function linkedHudNodes(agent,nodes){
 const workflows=new Set([...(agent.workflows||[]),...(agent.triggers||[])]);
 return nodes.filter(n=>['hud','feed'].includes(n.kind)&&((n.agent_ids||[]).includes(agent.id)||(n.kind==='hud'&&n.id.startsWith('hud:')&&n.summary&&workflows.has('celery:'+n.summary))));
}
export function orderHudCards(cards,order){
 const rank=new Map();order.forEach((id,i)=>{if(!rank.has(id))rank.set(id,i);});
 return cards.slice().sort((a,b)=>(rank.get(a.id)??Infinity)-(rank.get(b.id)??Infinity));
}
export function moveHudCard(ids,id,offset){
 const from=ids.indexOf(id),to=from+offset;if(from<0||to<0||to>=ids.length)return ids;
 const result=[...ids];result.splice(to,0,result.splice(from,1)[0]);return result;
}
