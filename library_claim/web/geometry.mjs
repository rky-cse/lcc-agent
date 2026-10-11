import {originalPoint} from './contents_core.mjs';
export async function mount(document=globalThis.document,environment={}){
const location=environment.location||globalThis.location,$=id=>document.getElementById(id),session=new URL(location.href).searchParams.get('session');let capture=null,inventory=null,frame=null,busy=false;
const points={reference:[],check:[],region:[]},id=()=>crypto.randomUUID().replaceAll('-','');const message=text=>{$('status').textContent=text;};
async function api(url,body){const r=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(200000)}),value=await r.json();if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:'Measurement request failed');return value;}
async function action(work){if(busy)return;busy=true;try{await work();}catch(e){message(e.message);}finally{busy=false;}}
function numeric(name){if($(name).value.trim()==='')throw new Error(`${name} is required`);const value=Number($(name).value);if(!Number.isFinite(value))throw new Error(`${name} must be finite`);return value;}
function markerText(){$('markers').textContent=JSON.stringify(points,null,2);}
function select(){frame=capture.frames.find(f=>f.id===$('frame-select').value);for(const key in points)points[key]=[];markerText();$('frame').hidden=!frame;if(!frame)return;$('frame').src=`/api/frames/${frame.id}`;$('spines').replaceChildren();
 for(const obs of inventory.observations.filter(o=>o.frame_ref===frame.id&&o.track_id)){const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.dataset.observation=obs.id;label.append(check,document.createTextNode(`Measure physical book ${obs.track_id} (${obs.shelf_id})`));$('spines').append(label);}
}
async function load(){[capture,inventory]=await Promise.all([api(`/api/sweeps/${session}`),api(`/api/sweeps/${session}/inventory/export`)]);const guide=await api(`/api/guidance/${session}`);$('frame-select').replaceChildren();$('room-frames').replaceChildren();
 for(const f of capture.frames){const option=document.createElement('option');option.value=f.id;option.textContent=`View ${f.media_sequence} · ${f.width}×${f.height}`;$('frame-select').append(option);const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.value=f.id;label.append(check,document.createTextNode(option.textContent));$('room-frames').append(label);}
 const ref=guide.reference?.payload||guide.reference;if(ref){for(const [name,field] of [['description','description'],['width','width_cm'],['height','height_cm'],['width-error','width_uncertainty_cm'],['height-error','height_uncertainty_cm'],['provenance','dimension_provenance']])if(ref[field]!=null)$(name).value=ref[field];}
 select();message('Select the reference corners and independently measured check point in an original image.');
}
$('load').onclick=()=>action(load);$('frame-select').onchange=select;
$('frame').onclick=event=>{try{const mode=$('mark-mode').value,point=originalPoint(frame,$('frame'),$('frame').getBoundingClientRect(),event,new URL(`/api/frames/${frame.id}`,location.origin).href);if(points[mode].length>=(mode==='check'?1:4))points[mode]=[];points[mode].push(point);markerText();}catch(e){message(e.message);}};
$('reset-points').onclick=()=>{points[$('mark-mode').value]=[];markerText();};
$('measure').onclick=()=>action(async()=>{
 if(!frame||points.reference.length!==4||points.region.length!==4||points.check.length!==1)throw new Error('Mark four reference corners, four validity-region corners and one independent check point.');
 const selected=[...$('spines').querySelectorAll('input:checked')].map(input=>inventory.observations.find(o=>o.id===input.dataset.observation));if(!selected.length)throw new Error('Select at least one physical book.');
 const plane='reviewed-plane-'+id(),tolerance=numeric('tolerance'),reference={id:'reference-'+id(),frame_ref:frame.id,frame_sha256:frame.sha256,plane_id:plane,width_cm:numeric('width'),height_cm:numeric('height'),width_uncertainty_cm:numeric('width-error'),height_uncertainty_cm:numeric('height-error'),dimensions_verified:$('dimensions-confirmed').checked,dimension_provenance:$('provenance').value,corners_px:points.reference,corner_tolerance_px:tolerance,coordinate_space:'encoded_pixels',lens_status:$('lens').value,lens_provenance:$('lens-provenance').value,valid_region_px:points.region,validity_provenance:$('plane-provenance').value,check_points:[{pixel:points.check[0],plane_cm:[numeric('check-x'),numeric('check-y')],provenance:$('check-provenance').value}]};
 const request={sweep_id:session,reference,policy:{min_reference_area_px2:400,max_check_error_cm:0.5,max_opposite_edge_relative_difference:0.15,max_corner_cosine:0.15,max_sensitivity_relative_change:0.15},spines:selected.map(obs=>({id:obs.track_id,frame_ref:frame.id,plane_id:plane,corners_px:obs.polygon_px,corner_tolerance_px:tolerance,coplanarity_confirmed:$('coplanar').checked,coplanarity_provenance:$('plane-provenance').value,annotation_source:'developer_annotated'}))};
 const result=await api(`/api/sweeps/${session}/stages/measurement`,{run_id:id(),request});show(result);message('Measured output saved. Valid measurements can be selected in the claim packet.');
});
$('reconstruct').onclick=()=>action(async()=>{const frame_refs=[...$('room-frames').querySelectorAll('input:checked')].map(c=>c.value);if(frame_refs.length<3||frame_refs.length>12)throw new Error('Select 3–12 overlapping views.');
 const camera_calibration=$('calibration').value.trim()?JSON.parse($('calibration').value):null;const request={sweep_id:session,frame_refs,same_camera_and_zoom_confirmed:$('fixed-camera').checked,camera_provenance:$('camera-provenance').value,policy:{max_runtime_seconds:180,min_points3d:30,max_median_reprojection_error_px:2,min_median_triangulation_angle_deg:2},camera_calibration};
 const result=await api(`/api/sweeps/${session}/stages/reconstruction`,{run_id:id(),request});show(result);message('Room reconstruction saved. Qualified calibration and observed surfaces are required for area calculations.');
});
function show(result){const p=document.createElement('pre');p.textContent=JSON.stringify(result,null,2);$('results').prepend(p);}
await action(load);return {refresh:()=>action(load)};
}
