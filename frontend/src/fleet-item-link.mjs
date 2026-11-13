// Reuse the existing HARQIS editor deep links; never invent records for mock nodes.
export function fleetItemLink(node) {
 if(!node||node.mock||typeof node.url!=='string'||!node.url)return null;
 if(!/^(https?:\/\/|\/(?!\/))/.test(node.url)||/[\\\r\n]/.test(node.url))return null;
 let url;try{url=new URL(node.url,'https://fleet.local');}catch{return null;}
 const local=url.origin==='https://fleet.local'&&url.pathname.startsWith('/hfl-corpus/');
 let label='Open source';
 if(local&&node.kind==='action'){
  const id=url.searchParams.get('edit')||url.searchParams.get('integration_agent');
  if(id){url.pathname='/hfl-corpus/actions';url.searchParams.set('edit',id);url.searchParams.set('edit_kind','actionable');url.searchParams.delete('integration_agent');label='Open action';}
 }else if(local&&node.kind==='idea'&&url.searchParams.get('edit')){
  url.searchParams.set('edit_kind','idea');label='Open idea';
 }else if(local&&node.kind==='entry'){label='Open entry';}
 return {label,href:url.origin==='https://fleet.local'?url.pathname+url.search+url.hash:url.href,external:url.origin!=='https://fleet.local'};
}
