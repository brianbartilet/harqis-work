// The graph transform includes DPR * camera zoom. Remove only the camera;
// requesting font / zoom hits Chromium's 10,000px font clamp on old layouts.
export function paintFleetLabel(ctx, box, color='#60a5fa', fontFamily='sans-serif') {
 const {x,y,w,h,node}=box;
 ctx.globalAlpha=box.alpha;
 ctx.fillStyle=node.emphasis?'#142a42f5':'#0a1728ee';
 ctx.beginPath();ctx.roundRect(x,y,w,h,5);ctx.fill();
 ctx.strokeStyle=color+(node.emphasis?'90':'30');ctx.lineWidth=.6;ctx.stroke();
 ctx.font=`500 ${box.font}px ${fontFamily}`;
 ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillStyle=node.emphasis?'#ffffff':'#d9e9fa';
 box.lines.forEach((line,i)=>ctx.fillText(line,x+6,y+12+i*16));
}

export function fleetScreenTransform(ctx, scale) {
 const transform=ctx.getTransform();
 ctx.setTransform(transform.a/scale,0,0,transform.d/scale,0,0);
}
