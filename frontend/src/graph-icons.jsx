import React from 'react';
export function GraphIcon({name}) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{name==='fit'?<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>:<><path d="M5 12h14"/>{name==='plus'&&<path d="M12 5v14"/>}</>}</svg>;
}
