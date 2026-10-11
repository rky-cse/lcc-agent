import test from 'node:test';import assert from 'node:assert/strict';
import {planRequest,progressSummary} from '../library_claim/web/sweep_core.mjs';
const guide={phase:'capture_bound',capture_status:'capturing',reference_revision:7};
const values={shelf:'A',x0:'0',y0:'0',x1:'1',y1:'1','min-area':'100','max-overlap':'.5',budget:'4',interval:'10','expected-shelves':'2',consent:true};
test('explicit plan freezes reference and bounded budget without credentials or evidence replacement',()=>{const plan=planRequest(guide,values,'fixed');assert.equal(plan.plan_id,'fixed');assert.equal(plan.reference_revision,7);assert.equal(plan.max_attempts,4);assert.deepEqual(plan.region,[0,0,1,1]);assert.equal(plan.allow_unresolved_import,true);assert.equal('key' in plan,false);});
test('missing declarations, unsafe region and absent consent cannot start automatic work',()=>{for(const update of [{'expected-shelves':''},{'min-area':''},{x0:''},{x1:'2'},{budget:'21'},{interval:'1'},{shelf:' '},{consent:false}])assert.throws(()=>planRequest(guide,{...values,...update},'fixed'));assert.throws(()=>planRequest({...guide,capture_status:'closed'},values,'fixed'));});
test('closed and drained recognition never claims a finished packet',()=>{const text=progressSummary({status:'drained',attempts:2,remaining_attempts:0,pending_job_count:0,coverage_missing_shelves:1,capture_closed:true,recognition_drained:true});assert.match(text,/Capture ended/);assert.match(text,/stages still need completion/);assert.match(text,/1 expected shelves not observed/);});
test('sweep page contains a persistent result and failure visibility panel',async()=>{const html=await (await import('node:fs/promises')).readFile(new URL('../library_claim/web/sweep.html',import.meta.url),'utf8');assert.match(html,/Recognition activity and provisional results/);assert.match(html,/id="outcomes"/);});
test('sweep mount does not throw when recognition element is missing',async()=>{
  const {mount}=await import('../library_claim/web/sweep.mjs');
  const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,{disabled:false,textContent:'',replaceChildren(){},value:'',addEventListener(){},setAttribute(){}});return elements.get(id);};
  const mockDoc={getElementById:id=>(id==='recognition'?null:get(id)),querySelectorAll:()=>[],addEventListener(){}};
  const mockWin={addEventListener(){}};
  const ctrl=await mount(mockDoc,{window:mockWin,location:new URL('http://localhost/sweep')});
  assert.equal(typeof ctrl.open,'function');
});
