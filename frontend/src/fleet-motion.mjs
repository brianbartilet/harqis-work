import {motionOffset} from './graph-presets.mjs';

// Keep Fleet drift visible in screen pixels even when the map is zoomed out.
export function fleetMotionOffset(mode,point,time,phase,zoom=1){
 if(mode!=='drift')return motionOffset(mode,point,time,phase);
 const wave=time*2*Math.PI/8000,scale=Math.max(.02,zoom);
 return {x:18*Math.sin(wave+phase)/scale,y:14*Math.cos(wave*.8+phase)/scale};
}
