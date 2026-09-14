// Fictional, local-only data for demonstrating React Force Graph interactions.
export function exampleGraph() {
  const nodes = [
    ['atlas','Project Atlas','topics'], ['garden','Community garden','topics'],
    ['studio','Design studio','topics'], ['maya','Maya','people'],
    ['leo','Leo','people'], ['sam','Sam','people'], ['react','React','tools'],
    ['figma','Figma','tools'], ['obsidian','Obsidian','tools'],
    ['research','Research','topics'], ['planning','Planning','topics'],
    ['accessibility','Accessibility','topics']
  ].map(([id,label,kind]) => ({id:'example:'+id,label,kind}));
  const entries = [
    ['Atlas kickoff',['atlas','maya','planning','obsidian']],
    ['Prototype review',['atlas','leo','react','figma']],
    ['Accessibility walkthrough',['atlas','sam','accessibility','react']],
    ['User interview findings',['atlas','maya','research','obsidian']],
    ['Garden planning session',['garden','sam','planning','obsidian']],
    ['Community interviews',['garden','maya','research']],
    ['Volunteer sign-up prototype',['garden','leo','react','accessibility']],
    ['Garden opening checklist',['garden','sam','planning']],
    ['Studio moodboard',['studio','leo','figma','research']],
    ['Design system workshop',['studio','maya','figma','accessibility']],
    ['Portfolio build',['studio','leo','react']],
    ['Monthly studio retrospective',['studio','sam','planning','obsidian']]
  ];
  const edges = [];
  entries.forEach(([label,links],index) => {
    const id='example:entry:'+index;
    nodes.push({id,label,kind:'entries',source:'Fictional example'});
    links.forEach(target => edges.push({source:id,target:'example:'+target}));
  });
  return {nodes,edges};
}
