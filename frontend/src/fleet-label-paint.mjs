// Labels are laid out and painted in CSS pixels, independent of camera zoom.
export function fleetLabelTransform(ctx,scale){
 const m=ctx.getTransform();ctx.setTransform(m.a/scale,0,0,m.d/scale,0,0);
}
export function paintFleetLabel(ctx,box,ink='#60a5fa',fontFamily='sans-serif'){
 if(!box.lines.some(line=>String(line).trim()))return;
 const {x,y,w,h,node}=box;
 ctx.globalAlpha=box.alpha;
 ctx.fillStyle=node.emphasis?'#142a42f5':'#0a1728ee';
 ctx.beginPath();ctx.roundRect(x,y,w,h,5);ctx.fill();
 ctx.strokeStyle=ink+(node.emphasis?'90':'30');ctx.lineWidth=.6;ctx.stroke();
 ctx.font=`500 ${box.font}px ${fontFamily}`;ctx.textAlign='left';ctx.textBaseline='middle';
 ctx.fillStyle=node.emphasis?'#ffffff':'#d9e9fa';
 box.lines.forEach((line,index)=>ctx.fillText(line,x+6,y+12+index*16));
}
