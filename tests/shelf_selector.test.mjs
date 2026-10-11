import test from 'node:test';import assert from 'node:assert/strict';
import {pixelRegion,detectionEnrollment,ShelfSelector} from '../library_claim/web/shelf_selector.mjs';
const frame={id:'frame/a',sha256:'hash',width:1600,height:900,exif_orientation:null,synthetic:true};
const data={session_id:'s',inventory_revision:4,reference_revision:2,frames:[frame],total_frames:1,frame_offset:0,frame_limit:50};
const policy={min_polygon_area_px2:100,max_pair_overlap_fraction:.5};
test('scaled reverse drag converts to outward-rounded original pixel edges',()=>{
 assert.deepEqual(pixelRegion([410.1,250.2],[60.2,75.1],{left:10,top:25,width:800,height:450},1600,900),[100,100,801,451]);
});
test('outside pointer release clamps to original bounds; zero and invalid rectangles fail',()=>{
 assert.deepEqual(pixelRegion([-5,-5],[1000,1000],{left:0,top:0,width:800,height:450},1600,900),[0,0,1600,900]);
 assert.throws(()=>pixelRegion([2,2],[2,2],{left:0,top:0,width:800,height:450},1600,900));
 assert.throws(()=>pixelRegion([2.1,2.2],[2.1,2.2],{left:0,top:0,width:800,height:450},1600,900));
 assert.throws(()=>pixelRegion([2,2],[3,3],{left:0,top:0,width:0,height:450},1600,900));
});
test('explicit enrollment freezes frame hash, revisions, shelf region and policy',()=>{
 const box=[100,50,1000,700];const result=detectionEnrollment(data,frame,box,'shelf',policy,'job');box[0]=0;
 assert.equal(result.expected_inventory_revision,4);assert.equal(result.expected_reference_revision,2);assert.equal(result.request.frame_sha256,'hash');assert.equal(result.request.shelf_region_px[0],100);
});
test('missing policy, wrong frame, invalid bounds and EXIF cannot enroll',()=>{
 for(const [f,b,s,p] of [[{...frame,sha256:'wrong'},[0,0,10,10],'s',policy],[{...frame,exif_orientation:6},[0,0,10,10],'s',policy],[frame,[0,0,1700,10],'s',policy],[frame,[0,0,10.5,10],'s',policy],[frame,[0,0,10,10],' ',policy],[frame,[0,0,10,10],'s',{}]])assert.throws(()=>detectionEnrollment(data,f,b,s,p,'j'));
});
function doc(){const map=new Map();const node=()=>({value:'',style:{},children:[],append(n){this.children.push(n);},replaceChildren(...n){this.children=n;},setPointerCapture(){},getBoundingClientRect(){return {left:0,top:0,width:800,height:450};}});return {getElementById(id){if(!map.has(id))map.set(id,node());return map.get(id);},createElement:node};}
test('late image load and pointer events after reset cannot restore ready state',()=>{
 const document=doc(),selector=new ShelfSelector(document,()=>assert.fail());selector.render(data);selector.select(frame);const image=selector.image;image.naturalWidth=1600;image.naturalHeight=900;selector.clear();image.onload();image.onpointerdown({button:0});assert.equal(selector.ready,false);assert.equal(selector.frame,null);
});
test('wrong decoded dimensions keep enrollment disabled',()=>{
 const document=doc(),selector=new ShelfSelector(document,()=>assert.fail());selector.render(data);selector.select(frame);selector.image.naturalWidth=900;selector.image.naturalHeight=1600;selector.image.onload();assert.equal(selector.ready,false);assert.equal(document.getElementById('queue-detection').disabled,true);
});
test('manual rectangle enrollment is explicit and blank values never become origin zero',()=>{
 const document=doc();let submitted;const selector=new ShelfSelector(document,body=>submitted=body);selector.render(data);selector.select(frame);selector.image.naturalWidth=1600;selector.image.naturalHeight=900;selector.image.onload();
 document.getElementById('shelf-id').value='shelf';document.getElementById('min-area').value='100';document.getElementById('max-overlap').value='.5';
 for(const [key,value] of Object.entries({x0:'',y0:'0',x1:'1500',y1:'800'}))document.getElementById(key).value=value;
 document.getElementById('region-form').onsubmit({preventDefault(){}});assert.equal(submitted,undefined);
 document.getElementById('x0').value='100';document.getElementById('region-form').onsubmit({preventDefault(){}});assert.deepEqual(submitted.request.shelf_region_px,[100,0,1500,800]);
});
