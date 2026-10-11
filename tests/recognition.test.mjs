import test from 'node:test';
import assert from 'node:assert/strict';
import {ReadingView,enrollment,renderReadings,dispatchRequest,dispatchable,dispatchSummary} from '../library_claim/web/recognition.mjs';
const obs={id:'o',track_id:'track',frame_ref:'frame/a',frame_sha256:'hash',shelf_id:'shelf'};
const data={session_id:'s',inventory_revision:3,reference_revision:2,observations:[obs],total_observations:1,offset:0,limit:50,jobs:[]};
test('enrollment freezes original/observation and separate dependency revisions',()=>{
  assert.deepEqual(enrollment(data,obs,'job'),{job_id:'job',session_id:'s',expected_reference_revision:2,request:{sweep_id:'s',expected_revision:3,observation_id:'o',frame_sha256:'hash'}});
  assert.throws(()=>enrollment(data,{id:'missing'},'job'));
});
test('switching sessions ignores late response and aborts old request',async()=>{
  let resolveOld,signalOld;const changes=[];
  const view=new ReadingView({load:(s,o,signal)=>s==='old'?new Promise(resolve=>{resolveOld=resolve;signalOld=signal;}):Promise.resolve({...data,session_id:s}),changed:d=>changes.push(d.session_id),failed:()=>assert.fail()});
  const old=view.open('old');await view.open('new');resolveOld({...data,session_id:'old'});await old;
  assert.equal(signalOld.aborted,true);assert.deepEqual(changes,['new']);view.stop();
});
test('wrong target response fails without rendering',async()=>{
  let error;const view=new ReadingView({load:async()=>data,changed:()=>assert.fail(),failed:e=>error=e});await view.open('other');assert.match(error.message,/target/);
  const frames=new ReadingView({load:async()=>({...data,frame_offset:0}),changed:()=>assert.fail(),failed:e=>error=e});await frames.open('s',0,50);assert.match(error.message,/target/);
});
function documentFixture(){const elements=new Map();const node=()=>({children:[],textContent:'',dataset:{},append(...items){this.children.push(...items);},replaceChildren(){this.children=[];}});
 return {getElementById(id){if(!elements.has(id))elements.set(id,node());return elements.get(id);},createElement:node,createTextNode:text=>({textContent:text})};}
test('render uses literal physical evidence and explicit actions without executing',()=>{
  const document=documentFixture();let queued=0;
  renderReadings(document,{...data,observations:[{...obs,track_id:'<script>bad</script>'}]},{enqueue:()=>queued++,cancel:()=>assert.fail()});
  const row=document.getElementById('observations').children[0];assert.match(row.textContent,/<script>/);assert.equal(row.children[0].href,'/api/frames/frame%2Fa');assert.equal(queued,0);
  row.children[1].onclick();assert.equal(queued,1);
});
test('render explains the evidence workflow and next action',()=>{
  const document=documentFixture();renderReadings(document,{...data,workflow:{saved_frame_count:3,provisional_observation_count:2,readable_spine_count:1,partial_or_unreadable_spine_count:1,unresolved_physical_count:2,next_action:'Review physical observations.'}},{enqueue:()=>assert.fail(),cancel:()=>assert.fail()});
  assert.match(document.getElementById('workflow-status').textContent,/Saved images: 3/);assert.match(document.getElementById('workflow-status').textContent,/Review physical observations/);
});
test('render exposes the provisional inventory summary and JSON link',()=>{
  const document=documentFixture();renderReadings(document,{...data,inventory_projection:{revision:1,observation_count:2,detection_import_count:1,assigned_track_count:0,unresolved_physical_count:2,review_count:2,coverage_verified:false}},{enqueue:()=>assert.fail(),cancel:()=>assert.fail()});
  assert.match(document.getElementById('inventory-projection').textContent,/2 provisional detected spine regions/);assert.equal(document.getElementById('inventory-json').href,'/api/sweeps/s/inventory/export');
});
test('inventory evidence joins a reading result to its detected spine',()=>{
  const document=documentFixture(),observation={...obs,track_id:null,orientation:'upright',polygon_px:[[0,0],[1,0],[1,2],[0,2]]};
  const reading={input:{job_id:'read-1',kind:'reading'},status:'completed',result_status:'success',eligible_for_review:true,artifacts:{'reading_result.json':'x','crop.png':'x'},result_summary:{kind:'reading',observation_id:'o',legibility:'readable',text:[{role:'title',text:'Visible title'}],crop_available:true}};
  assert.doesNotThrow(()=>renderReadings(document,{...data,observations:[observation],jobs:[reading],inventory_projection:{revision:1,observation_count:1,detection_import_count:1,assigned_track_count:0,unresolved_physical_count:1,review_count:1,coverage_verified:false}},{enqueue:()=>{},cancel:()=>{}}));
  assert.match(document.getElementById('inventory-evidence').children[0].children.at(-1).children[0].textContent,/Visible title/);
});
test('stale evidence stays visibly ineligible and terminal work cannot cancel',()=>{
  const document=documentFixture();renderReadings(document,{...data,jobs:[{input:{job_id:'job/a'},status:'stale',result_status:'partial',eligible_for_review:false,artifacts:{'reading_result.json':'sha'}}]},{enqueue:()=>assert.fail(),cancel:()=>assert.fail()});
  const row=document.getElementById('jobs').children[0];assert.match(row.textContent,/Not eligible/);assert.equal(row.children[0].href,'/api/guidance/s/recognition/job%2Fa/reading_result.json');assert.equal(row.children.some(c=>c.textContent==='Cancel reading'),false);
});
test('detection results expose proposal and pinned-stage links without acceptance',()=>{
  const document=documentFixture();renderReadings(document,{...data,jobs:[{input:{kind:'detection',job_id:'detect'},status:'completed',result_status:'success',eligible_for_review:true,artifacts:{'detection_result.json':'sha','queue_stage.json':'sha'}}]},{enqueue:()=>assert.fail(),cancel:()=>assert.fail()});
  const row=document.getElementById('jobs').children[0];assert.match(row.textContent,/detection/);assert.match(row.textContent,/Unverified proposal/);
  assert.equal(row.children[0].href,'/api/guidance/s/recognition/detect/detection_result.json');assert.equal(row.children[2].href,'/api/guidance/s/recognition/detect/queue_stage.json');
});

const queued={input:{job_id:'exact-job',session_id:'s',kind:'detection'},status:'queued',result_status:null,eligible_for_review:false,artifacts:{}};
const ready={...data,jobs:[queued],dispatcher:{session_id:'s',enabled:true,mode:'replay',supported_kinds:['reading','detection'],active:false,worker_busy:false,closing:false}};
test('dispatch freezes only the saved exact job token, without keys, replay or input rebasing',()=>{
  assert.deepEqual(dispatchRequest(ready,{...queued,input:{...queued.input,kind:'reading'}}),{job_id:'exact-job'});
  assert.throws(()=>dispatchRequest(ready,{input:{job_id:'missing'}}));
  assert.throws(()=>dispatchRequest({...ready,jobs:[{...queued,input:{...queued.input,session_id:'other'}}]},queued));
});
test('missing disabled wrong-session busy shutting-down and unknown-mode status fail closed',()=>{
  for(const dispatcher of [null,{...ready.dispatcher,enabled:false},{...ready.dispatcher,session_id:'other'},
      {...ready.dispatcher,active:true},{...ready.dispatcher,worker_busy:true},{...ready.dispatcher,closing:true},{...ready.dispatcher,mode:'unknown'},
      {...ready.dispatcher,supported_kinds:['reading']}]){
    assert.equal(dispatchable({...ready,dispatcher},queued),false);assert.throws(()=>dispatchRequest({...ready,dispatcher},queued));
  }
});
test('terminal and uncertain activity cannot launch, including cancelled active jobs',()=>{
  for(const status of ['running','completed','failed','stale','cancelled','interrupted']){
    const job={...queued,status};assert.equal(dispatchable({...ready,jobs:[job]},job),false);
  }
  assert.equal(dispatchable({...ready,jobs:[queued,{...queued,input:{...queued.input,job_id:'uncertain'},status:'cancelled',worker_active:true}]},queued),false);
});
test('render creates one explicit run action and never invokes it during load or refresh',()=>{
  const document=documentFixture();let dispatched=0;
  const callbacks={enqueue:()=>assert.fail(),cancel:()=>assert.fail(),dispatch:(job)=>{assert.equal(job.input.job_id,'exact-job');dispatched++;}};
  renderReadings(document,ready,callbacks);renderReadings(document,ready,callbacks);assert.equal(dispatched,0);
  const run=document.getElementById('jobs').children[0].children.find(c=>c.textContent==='Run selected detection');
  assert.equal(run.disabled,false);assert.equal(run.dataset.jobId,'exact-job');run.onclick();assert.equal(dispatched,1);
});
test('disabled dispatch remains visible and cancelled activity displays recovery instructions',()=>{
  const document=documentFixture();renderReadings(document,{...ready,dispatcher:{...ready.dispatcher,enabled:false}}, {enqueue:()=>{},cancel:()=>{},dispatch:()=>assert.fail()});
  const run=document.getElementById('jobs').children[0].children.find(c=>c.textContent==='Run selected detection');assert.equal(run.disabled,true);
  assert.match(document.getElementById('dispatch-status').textContent,/disabled/);
  renderReadings(document,{...ready,jobs:[{...queued,status:'cancelled',worker_active:true}]},{enqueue:()=>{},cancel:()=>{},dispatch:()=>assert.fail()});
  assert.match(document.getElementById('jobs').children[0].children.at(-1).textContent,/stop the old worker/);
});
test('mode summary distinguishes replay, provider readiness and acceptance from completion',()=>{
  assert.match(dispatchSummary(ready),/Synthetic replay/);
  assert.match(dispatchSummary({...ready,dispatcher:{...ready.dispatcher,mode:'gemini',model:'configured-model'}}),/Gemini recognition \(configured-model\)/);
  assert.match(dispatchSummary({...ready,dispatcher:{...ready.dispatcher,active:true,job_id:'<literal>'}}),/worker active for <literal>/);
  assert.match(dispatchSummary({...ready,dispatcher:{...ready.dispatcher,worker_busy:true}}),/uncertain/);
  assert.match(dispatchSummary({...ready,dispatcher:null}),/unavailable/);
  assert.match(dispatchSummary(ready),/acceptance does not mean completion/);
});
