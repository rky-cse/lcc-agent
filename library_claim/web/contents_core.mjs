export function originalPoint(frame,image,rect,event,expectedUrl){
  if(!frame||!image.complete||image.currentSrc!==expectedUrl||image.naturalWidth!==frame.width||image.naturalHeight!==frame.height)throw new Error('Wait for the selected original to finish loading');
  if(![rect.left,rect.top,rect.width,rect.height,event.clientX,event.clientY].every(Number.isFinite)||rect.width<=0||rect.height<=0)throw new Error('Invalid original-image coordinates');
  return [Math.max(0,Math.min(frame.width-1,(event.clientX-rect.left)/rect.width*frame.width)),Math.max(0,Math.min(frame.height-1,(event.clientY-rect.top)/rect.height*frame.height))];
}
export function rectangle(points){
  if(points.length!==2||points.some(p=>p.length!==2||!p.every(Number.isFinite)))throw new Error('Select two valid opposite corners');
  const result=[Math.min(points[0][0],points[1][0]),Math.min(points[0][1],points[1][1]),Math.max(points[0][0],points[1][0]),Math.max(points[0][1],points[1][1])];
  if(result[0]===result[2]||result[1]===result[3])throw new Error('Object rectangle must have visible area');
  return result;
}
