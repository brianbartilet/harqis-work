import React,{useState,useEffect} from 'react';
export function OwnerCard({node,onSelect}){return node&&<section className="fleet-owner"><h3>Corpus owner</h3><button className="fleet-relationship-card" onClick={()=>onSelect(node.id)}>{node.avatar_url?<img src={node.avatar_url} alt=""/>:<span className="fleet-owner-avatar">{node.label.slice(0,1)}</span>}<span><strong>{node.label}</strong><small>Activity, actions and ideas</small></span></button></section>;}
export function Description({node}){
 const [loaded,setLoaded]=useState(null),[error,setError]=useState('');
 useEffect(()=>{setLoaded(null);setError('');if(!node.corpus_entry)return;const controller=new AbortController();fetch('/agents/api/entries/'+encodeURIComponent(node.id.slice(6))+'/description',{signal:controller.signal}).then(async response=>{if(!response.ok)throw Error('Formatted description unavailable. Open the entry for details.');const data=await response.json();if(!controller.signal.aborted)setLoaded({id:node.id,html:data.html});}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[node.id,node.summary]);
 const html=node.summary_html||(loaded?.id===node.id?loaded.html:'');
 return <details className="fleet-description-details"><summary>Description</summary>{html?<div className="fleet-description markdown-body" dangerouslySetInnerHTML={{__html:html}}/>:<div className="fleet-description fleet-plain-description">{node.summary}</div>}{error&&<p role="status">{error}</p>}</details>;
}
export function Relationships({node,data,onSelect}){
 const [limit,setLimit]=useState(30),groups=new Map(),nodes=new Map(data.nodes.map(n=>[n.id,n]));
 for(const edge of data.edges){if(edge.source!==node.id&&edge.target!==node.id)continue;const id=edge.source===node.id?edge.target:edge.source,related=nodes.get(id);if(!related)continue;if(!groups.has(id))groups.set(id,{related,relations:new Set()});groups.get(id).relations.add(edge.relation);}
 return <div className="fleet-relationships">{[...groups.values()].slice(0,limit).map(({related,relations})=><button className="fleet-relationship-card" key={related.id} onClick={()=>onSelect(related.id)}><span><span className="fleet-relationship-type" style={{'--entity-color':data.types?.find(t=>t.id===related.kind)?.color||related.color||'#94a3b8'}}>{related.kind}</span><strong>{related.label}</strong><small>{[...relations].map(value=>value.replaceAll('-', ' ')).join(' · ')}</small></span></button>)}{groups.size>limit&&<button onClick={()=>setLimit(v=>v+30)}>Show more ({groups.size-limit})</button>}</div>;
}

export function RelatedMemory({node,data,onSelect}){
 const relations=new Map();
 for(const edge of data.edges){
  if(edge.source!==node.id&&edge.target!==node.id)continue;
  const id=edge.source===node.id?edge.target:edge.source;
  if(!relations.has(id))relations.set(id,new Set());relations.get(id).add(edge.relation);
 }
 const memories=data.nodes.filter(n=>['entry','file','link'].includes(n.kind)&&relations.has(n.id))
  .sort((a,b)=>(b.created||'').localeCompare(a.created||''));
 return <section className="fleet-related-memory"><h3>Related memory</h3>
  {memories.slice(0,5).map(item=><button type="button" className="fleet-relationship-card" key={item.id} onClick={()=>onSelect(item.id)}><span><strong>{item.label}</strong><small>{[...relations.get(item.id)].join(' · ')}{item.source?' · '+item.source:''}{item.created?' · '+new Date(item.created).toLocaleDateString():''}</small></span></button>)}
  {!memories.length&&<p>No linked evidence in the current view.</p>}
  {memories.length>5&&<p>{memories.length-5} more linked records in Provenance &amp; relationships.</p>}
  <a href={'/hfl-corpus/graph?context=second-brain-memory&select='+encodeURIComponent(node.id)} target="_blank" rel="noopener noreferrer">Explore Activity Graph ↗</a>
 </section>;
}
