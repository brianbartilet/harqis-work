/* Treat an intentional backdrop click like Escape, preserving cancel guards. */
(() => {
  const events=new AbortController();
  let pressed=null;
  const outside=(dialog,event)=>{
    const box=dialog.getBoundingClientRect();
    return event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom;
  };
  const eligible=target=>target instanceof HTMLDialogElement&&target.open&&target.id!=='activity-standalone';
  document.addEventListener('pointerdown',event=>{
    pressed=event.button===0&&eligible(event.target)&&outside(event.target,event)?event.target:null;
  },{capture:true,signal:events.signal});
  document.addEventListener('pointercancel',()=>{pressed=null;},{signal:events.signal});
  document.addEventListener('click',event=>{
    const dialog=pressed;pressed=null;
    if(!dialog||event.target!==dialog||!eligible(dialog)||!outside(dialog,event))return;
    // Own this backdrop gesture so older per-dialog handlers cannot bypass guards.
    event.preventDefault();event.stopImmediatePropagation();
    if(dialog.matches('[inert],[aria-busy="true"]')||dialog.querySelector('[inert]'))return;
    if(dialog.dispatchEvent(new Event('cancel',{cancelable:true}))&&dialog.open)dialog.close();
  },{capture:true,signal:events.signal});
  window.addEventListener('hfl:view-replacing',()=>events.abort(),{once:true});
})();
