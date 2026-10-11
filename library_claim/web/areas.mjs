import {scope,reviewRequest,summary} from './areas_core.mjs';
export async function mount(document=globalThis.document, environment={}) {
const window=environment.window||globalThis.window, location=environment.location||globalThis.location, history=environment.history||globalThis.history;
const $=id=>document.getElementById(id);let inventory=null,result=null,generation=0,busy=false;
const sweep=()=>scope($('sweep-id').value.trim());
async function json(url,options){const r=await fetch(url,options);const v=await r.json();if(!r.ok)throw new Error(v.detail||'Request failed');return v;}
function message(text){$('status').textContent=text;}
function line(parent,text){const p=document.createElement('p');p.textContent=text;parent.append(p);}
async function action(work){if(busy)return;busy=true;const g=++generation;try{await work(()=>g===generation);}catch(e){if(g===generation)message(e.message);}finally{busy=false;}}
function render(value){result=value;$('result').replaceChildren();for(const text of summary(value))line($('result'),text);$('run-id').value=value.run_id;$('download').disabled=false;message('Saved area run loaded. Review unknowns and sensitivity in the downloaded evidence.');}
$('sweep-id').oninput=()=>{generation++;inventory=null;result=null;$('calculate').disabled=true;$('download').disabled=true;$('inventory').replaceChildren();$('result').replaceChildren();};
$('load').onclick=()=>action(async current=>{const id=sweep();const value=await json(`/api/sweeps/${id}/contents`);if(!current())return;inventory=value;$('inventory').replaceChildren();line($('inventory'),`Contents revision ${value.revision}`);for(const row of value.rows.filter(r=>r.item.category==='shelving_unit'))line($('inventory'),`Shelving ${row.item.id}: ${row.item.description}`);$('calculate').disabled=false;message('Review the current shelving IDs and observed geometry.');});
$('template').onclick=()=>{try{if(!inventory)throw new Error('Load contents first');$('request').value=JSON.stringify({run_id:crypto.randomUUID().replaceAll('-',''),sweep_id:sweep(),expected_contents_revision:inventory.revision,reconstruction_path:'',reconstruction_result_sha256:'',coordinate_space:'colmap_encoded_pixels',annotation_source:'developer_annotated',points:[],anchor:null,scale_check:null,floor_corners:null,floor_boundary_complete:false,walls:[],openings:[],shelves:[],openings_complete:false,shelving_coverage_complete:false,boundary_provenance:'',policy:{min_triangulation_angle_deg:null,max_reprojection_error_px:null,max_scale_check_relative_error:null,max_sensitivity_relative_change:null},interpretation:{dimensions:null,wall_area_basis:null,shelving_basis:'all_reviewed_physical_shelving',height:null,max_wall_projection_distance_m:null,max_surface_plane_error_m:null}},null,2);message('Fill the observed geometry and make each policy choice before calculating.');}catch(e){message(e.message);}};
$('calculate').onclick=()=>action(async current=>{if(!inventory)throw new Error('Load contents first');const id=sweep(),request=reviewRequest($('request').value,id,inventory.revision);const value=await json(`/api/sweeps/${id}/areas`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});if(current())render(value);});
$('restore').onclick=()=>action(async current=>{const value=await json(`/api/sweeps/${sweep()}/areas/${scope($('run-id').value.trim())}`);if(current())render(value);});
$('download').onclick=()=>{if(!result)return;const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='room-areas.json';a.click();URL.revokeObjectURL(url);};
$('sweep-id').value=new URLSearchParams(location.search).get('sweep_id')||'';


}
if(globalThis.document?.querySelector('script[src="/assets/areas.mjs"]')) await mount();
