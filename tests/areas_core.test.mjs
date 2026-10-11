import test from 'node:test';
import assert from 'node:assert/strict';
import {scope,reviewRequest,summary} from '../library_claim/web/areas_core.mjs';
test('scope rejects traversal and empty IDs',()=>{for(const id of ['','../a','a/b','x?y'])assert.throws(()=>scope(id));assert.equal(scope('sweep_1'),'sweep_1');});
test('review binds sweep revision and explicit interpretation',()=>{const body={run_id:'r1',sweep_id:'s1',expected_contents_revision:4,interpretation:{wall_area_basis:'net',dimensions:'unknown',height:'unknown'}};assert.deepEqual(reviewRequest(JSON.stringify(body),'s1',4),body);assert.throws(()=>reviewRequest(JSON.stringify(body),'s2',4));assert.throws(()=>reviewRequest(JSON.stringify(body),'s1',5));body.interpretation.height=null;assert.throws(()=>reviewRequest(JSON.stringify(body),'s1',4));});
test('unknown area cannot render as zero and stale results stay visible',()=>{const text=summary({run_id:'r',status:'partial',stale:true,geometry:{area_units:{floor_area_m2:{m2:12,ft2:129}}}}).join('\n');assert.match(text,/stale/);assert.match(text,/wall_area_m2: unknown/);assert.match(text,/12 m²/);});
