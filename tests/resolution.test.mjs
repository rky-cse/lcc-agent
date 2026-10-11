import test from 'node:test';import assert from 'node:assert/strict';
import {resolutionRequest,resolutionView} from '../library_claim/web/resolution.mjs';
import {receiptText} from '../library_claim/web/registration.mjs';
const result={session_id:'s',inventory_revision:5,reference_revision:3,can_resolve:true,
  observation:{id:'obs',track_id:null,frame_ref:'original',shelf_id:'A',polygon_px:[[0,0],[1,0],[1,1],[0,1]]},
  targets:[{id:'physical',shelf_id:'A'}],resolution_events:[],frame:{width:1600,height:900}};
const decision={observation_id:'obs',action:'new',track_id:null,provenance:'Distinct physical evidence'};
test('resolution pins current inventory rather than old detector revision',()=>{
  const data=resolutionView(result),request=resolutionRequest(data,[decision],'Reviewer','Comparison','review');
  assert.equal(request.expected_inventory_revision,5);assert.equal(request.expected_reference_revision,3);
  assert.equal(request.job_id,undefined);assert.equal(data.candidates[0].observation_id,'obs');
  request.decisions[0].provenance='changed';assert.equal(decision.provenance,'Distinct physical evidence');
});
test('ambiguity remains unresolved without a mutation request',()=>{
  const data=resolutionView(result);
  for(const decisions of [[],[decision,decision],[{...decision,action:'unresolved'}]])assert.throws(()=>resolutionRequest(data,decisions,'R','Reason','id'));
  assert.throws(()=>resolutionRequest(resolutionView({...result,can_resolve:false}),[decision],'R','Reason','id'));
});
test('same copy requires explicit same-shelf physical target and literal reason',()=>{
  const data=resolutionView(result);assert.throws(()=>resolutionRequest(data,[{...decision,action:'same',track_id:'missing'}],'R','Reason','id'));
  const request=resolutionRequest(data,[{...decision,action:'same',track_id:'physical'}],'R','Reason','id');assert.equal(request.decisions[0].track_id,'physical');
  assert.throws(()=>resolutionRequest(data,[{...decision,provenance:' '}],'R','Reason','id'));
});
test('historical resolution receipt shows recorded action and revision',()=>{
  const text=receiptText({revision:7,command:{operation:'resolve',decisions:[{...decision,provenance:'Literal <script> reason'}]}});
  assert.match(text,/Resolution applied at inventory revision 7/);assert.match(text,/historical/);assert.match(text,/Literal <script> reason/);
});
