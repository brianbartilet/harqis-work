import semantics from '../static/entity-semantics.json' with {type:'json'};
export const actionStatusNames=semantics.action.labels;
export const actionStatusColors={open:'#facc15',active:'#facc15',in_progress:'#facc15',incomplete:'#f87171',done:'#4ade80',dismissed:'#94a3b8'};
export function statusLabel(node){const status=actionStatusNames[node.state||node.status];return ['action','actions'].includes(node.kind)&&status?node.label+' · '+status:node.label;}
export function statusColor(node){return ['action','actions'].includes(node.kind)?actionStatusColors[node.state||node.status]:node.status_color;}
export function statusSuffix(node){const status=actionStatusNames[node.state||node.status];return ['action','actions'].includes(node.kind)&&status?' · '+status:'';}
