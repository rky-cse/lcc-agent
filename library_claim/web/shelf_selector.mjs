// Coordinates refer to original encoded image pixel edges, never preview pixels.
export function pixelRegion(start,end,rect,width,height) {
  if(![...start,...end,rect.left,rect.top,rect.width,rect.height,width,height].every(Number.isFinite)||rect.width<=0||rect.height<=0||width<=0||height<=0)throw new Error('Invalid image coordinates');
  const point=p=>[Math.max(0,Math.min(width,(p[0]-rect.left)*width/rect.width)),Math.max(0,Math.min(height,(p[1]-rect.top)*height/rect.height))];
  const a=point(start),b=point(end);
  if(a[0]===b[0]||a[1]===b[1])throw new Error('Draw a nonzero shelf rectangle');
  const box=[Math.floor(Math.min(a[0],b[0])),Math.floor(Math.min(a[1],b[1])),Math.ceil(Math.max(a[0],b[0])),Math.ceil(Math.max(a[1],b[1]))];
  if(box[0]===box[2]||box[1]===box[3])throw new Error('Draw a nonzero shelf rectangle');
  return box;
}

export function detectionEnrollment(data,frame,box,shelf,policy,jobId) {
  const saved=data.frames.find(f=>f.id===frame.id);
  if(!saved||saved.sha256!==frame.sha256)throw new Error('Select a frame from the current saved evidence page');
  if(frame.exif_orientation!==null&&frame.exif_orientation!==1)throw new Error('This frame needs an EXIF coordinate adapter');
  if(box.length!==4||!box.every(Number.isSafeInteger)||!(0<=box[0]&&box[0]<box[2]&&box[2]<=frame.width&&0<=box[1]&&box[1]<box[3]&&box[3]<=frame.height))throw new Error('Shelf rectangle must fit the original image');
  if(!shelf.trim()||shelf.length>128)throw new Error('Enter a shelf ID');
  if(!Number.isFinite(policy.min_polygon_area_px2)||policy.min_polygon_area_px2<=0||!Number.isFinite(policy.max_pair_overlap_fraction)||policy.max_pair_overlap_fraction<=0||policy.max_pair_overlap_fraction>=1)throw new Error('Enter valid detection review limits');
  return {kind:'detection',job_id:jobId,session_id:data.session_id,expected_reference_revision:data.reference_revision,expected_inventory_revision:data.inventory_revision,
    request:{sweep_id:data.session_id,frame_ref:frame.id,frame_sha256:frame.sha256,shelf_id:shelf,shelf_region_px:[...box],policy:{...policy}}};
}

export class ShelfSelector {
  constructor(document,onSubmit) {
    this.document=document;this.onSubmit=onSubmit;this.$=id=>document.getElementById(id);this.generation=0;
    this.$('region-form').onsubmit=event=>{event.preventDefault();
      try {if(!this.ready||!this.frame)throw new Error('Select and load a saved original first');
        const box=['x0','y0','x1','y1'].map(id=>this.$(id).value.trim()===''?NaN:Number(this.$(id).value));
        const policy={min_polygon_area_px2:Number(this.$('min-area').value),max_pair_overlap_fraction:Number(this.$('max-overlap').value)};
        const body=detectionEnrollment(this.data,this.frame,box,this.$('shelf-id').value,policy,'placeholder');
        this.paint(box);
        this.onSubmit(body,this.$('queue-detection'));
      }catch(error){this.$('region-status').textContent=error.message;}
    };
    for(const id of ['x0','y0','x1','y1'])this.$(id).oninput=()=>{
      const box=['x0','y0','x1','y1'].map(key=>this.$(key).value.trim()===''?NaN:Number(this.$(key).value));
      if(this.ready&&box.every(Number.isSafeInteger)&&0<=box[0]&&box[0]<box[2]&&box[2]<=this.frame.width&&0<=box[1]&&box[1]<box[3]&&box[3]<=this.frame.height)this.paint(box);
      else this.$('region-box').hidden=true;
    };
  }
  clear() {
    ++this.generation;this.ready=false;this.frame=null;this.drag=null;this.image=null;
    this.$('region-editor').hidden=true;this.$('region-image').replaceChildren();this.$('saved-frames').replaceChildren();
    this.$('queue-detection').disabled=true;this.$('region-status').textContent='Select a saved frame to mark its shelf.';
    this.$('frame-prev').disabled=true;this.$('frame-next').disabled=true;
  }
  render(data) {
    this.clear();this.data=data;
    this.$('frame-page').textContent=`${data.total_frames} saved frames · page starts at ${data.total_frames ? data.frame_offset+1 : 0}`;
    this.$('frame-prev').disabled=data.frame_offset===0;this.$('frame-next').disabled=data.frame_offset+data.frame_limit>=data.total_frames;
    for(const frame of data.frames) {
      const button=this.document.createElement('button');button.textContent=`Select frame ${frame.id} · ${frame.width} × ${frame.height}${frame.synthetic?' · synthetic':''}`;
      button.disabled=frame.exif_orientation!==null&&frame.exif_orientation!==1;button.onclick=()=>this.select(frame);this.$('saved-frames').append(button);
    }
  }
  select(frame) {
    const generation=++this.generation;this.ready=false;this.frame=frame;this.drag=null;
    this.$('region-editor').hidden=false;this.$('queue-detection').disabled=true;this.$('region-box').hidden=true;
    for(const id of ['x0','y0','x1','y1','shelf-id','min-area','max-overlap'])this.$(id).value='';
    this.$('region-status').textContent='Loading saved original…';
    const image=this.document.createElement('img');this.image=image;image.alt='Saved original for shelf selection';image.draggable=false;
    this.$('region-image').replaceChildren(image);
    image.onload=()=>{if(generation!==this.generation)return;
      if(image.naturalWidth!==frame.width||image.naturalHeight!==frame.height){this.$('region-status').textContent='Original dimensions differ; selection disabled.';return;}
      this.ready=true;this.$('queue-detection').disabled=false;this.$('region-status').textContent=`Original ${frame.width} × ${frame.height}. Draw the shelf rectangle or enter its pixel edges below.`;
    };
    image.onerror=()=>{if(generation===this.generation){this.ready=false;this.$('region-status').textContent='Original unavailable; reselect the frame.';}};
    image.onpointerdown=event=>{if(generation!==this.generation||!this.ready||event.button!==0)return;event.preventDefault();this.drag={id:event.pointerId,start:[event.clientX,event.clientY]};image.setPointerCapture(event.pointerId);};
    image.onpointerup=event=>{if(generation!==this.generation||!this.drag||event.pointerId!==this.drag.id)return;
      const start=this.drag.start;this.drag=null;
      try {const box=pixelRegion(start,[event.clientX,event.clientY],image.getBoundingClientRect(),frame.width,frame.height);
        ['x0','y0','x1','y1'].forEach((id,i)=>this.$(id).value=String(box[i]));this.paint(box);
      }catch(error){this.$('region-status').textContent=error.message;}
    };
    image.onpointercancel=image.onlostpointercapture=()=>{if(generation===this.generation)this.drag=null;};
    image.src=`/api/frames/${encodeURIComponent(frame.id)}`;
  }
  paint(box) {
    const overlay=this.$('region-box');overlay.hidden=false;
    Object.assign(overlay.style,{left:`${box[0]/this.frame.width*100}%`,top:`${box[1]/this.frame.height*100}%`,width:`${(box[2]-box[0])/this.frame.width*100}%`,height:`${(box[3]-box[1])/this.frame.height*100}%`});
    this.$('region-status').textContent=`Selected original pixel edges: ${box.join(', ')}. Enter shelf ID and review limits before queuing.`;
  }
}
