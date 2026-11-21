import React from 'react';

export function SecondBrainNavigation(){
 const views=[
  ['Kanban','/hfl-corpus/actions','M3 4h18v16H3z M9 4v16M15 4v16 M5 8h2m4 0h2m4 0h2'],
  ['Dashboard','/second-brain','M3 3h7v10H3z M14 3h7v6h-7z M3 17h7v4H3z M14 13h7v8h-7z'],
 ];
 return <nav className="second-brain-navigation" aria-label="Second Brain views">{views.map(([label,href,path])=><a key={href} href={href} aria-label={label} title={label==='Kanban'?'Kanban — manage actions':'Dashboard — view HUD widgets'}><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={path}/></svg></a>)}<button type="button" className="qn-launch" data-quick-notes-open aria-label="Quick Notes" title="Quick Notes" aria-haspopup="dialog"><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M14 3H5v18h14V8z M14 3v5h5 M8 12h1m3 0h4 M8 16h1m3 0h4"/></svg></button></nav>;
}
