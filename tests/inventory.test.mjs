import test from 'node:test';
import assert from 'node:assert/strict';
import {InventoryPoller,renderInventory} from '../library_claim/web/inventory.mjs';
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const data=(id='a',revision=1,offset=0)=>({sweep_id:id,revision,page_offset:offset,page_limit:50,rows:[],total_rows:0,
  assigned_track_count:0,owned_assigned_track_count:0,review_count:0,detection_import_count:0});
function harness(fetchSnapshot){
  const timers=new Map(),changes=[],errors=[]; let next=0;
  const poller=new InventoryPoller({fetchSnapshot,changed:x=>changes.push(x),failed:x=>errors.push(x),
    setTimer:(fn,delay)=>{timers.set(++next,{fn,delay});return next;},clearTimer:id=>timers.delete(id)});
  return {poller,timers,changes,errors};
}
test('late previous sweep response is ignored even without abort support',async()=>{
  const pending=[]; const h=harness((id,offset)=>new Promise(resolve=>pending.push({id,resolve})));
  h.poller.watch('a'); h.poller.watch('b');
  pending[1].resolve(data('b')); await settle();
  pending[0].resolve(data('a',99)); await settle();
  assert.equal(h.changes.at(-1).sweep_id,'b'); assert.equal(h.errors.length,0); h.poller.stop();
});
test('page switch ignores late old page and retries after connection errors',async()=>{
  const pending=[]; const h=harness((id,offset)=>new Promise((resolve,reject)=>pending.push({offset,resolve,reject})));
  h.poller.watch('a'); h.poller.select('a',50); pending[0].resolve(data()); await settle();
  pending[1].reject(new Error('offline')); await settle(); assert.equal(h.errors.length,1);
  const retry=[...h.timers.values()].find(t=>t.delay===2000); retry.fn();
  pending[2].resolve(data('a',2,50)); await settle(); assert.equal(h.changes.at(-1).page_offset,50); h.poller.stop();
});
test('older revisions never replace displayed inventory',async()=>{
  let revision=3; const h=harness(async()=>data('a',revision)); h.poller.watch('a'); await settle();
  revision=2; [...h.timers.values()].find(t=>t.delay===2000).fn(); await settle();
  assert.equal(h.changes.at(-1).revision,3); assert.equal(h.errors.length,1); h.poller.stop();
});
test('stop aborts in-flight poll and removes scheduled work',async()=>{
  let signal; const h=harness((id,offset,s)=>{signal=s; return new Promise(()=>{});});
  h.poller.watch('a'); h.poller.stop(); assert.equal(signal.aborted,true); assert.equal(h.timers.size,0);
});
test('unchanged polls preserve row focus but successful reconnect clears error',async()=>{
  let offline=false; const h=harness(async()=>{if(offline)throw new Error('offline');return data();});
  h.poller.watch('a'); await settle(); const count=h.changes.length;
  [...h.timers.values()].find(t=>t.delay===2000).fn(); await settle(); assert.equal(h.changes.length,count);
  offline=true; [...h.timers.values()].find(t=>t.delay===2000).fn(); await settle();
  offline=false; [...h.timers.values()].find(t=>t.delay===2000).fn(); await settle();
  assert.equal(h.changes.length,count+1); h.poller.stop();
});
test('timeout aborts request and retry has one active request',async()=>{
  let active=0; const h=harness((id,offset,signal)=>new Promise((resolve,reject)=>{
    active++; signal.addEventListener('abort',()=>{active--;reject(new Error('timeout'));});
  })); h.poller.watch('a'); h.poller.watch('a'); assert.equal(active,1);
  [...h.timers.values()].find(t=>t.delay===10000).fn(); await settle();
  assert.equal(active,0); assert.equal(h.errors.length,1); h.poller.stop();
});
class Element {
  constructor(){this.children=[];this.textContent='';}
  append(x){this.children.push(x);} replaceChildren(){this.children=[];}
}
test('render uses literal model text, encoded evidence links and explicit exclusions',()=>{
  const ids=new Map(); const doc={getElementById:id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);},createElement:()=>new Element()};
  const snap={...data(),assigned_track_count:1,review_count:1,detection_import_count:1,total_rows:51,
    rows:[{kind:'book',title:'<script>bad()</script>',shelf:'A',owned:false,reason:'Unknown',frame_ref:'a/b',observation_count:2},
          {kind:'review',shelf:'',reason:'<img onerror=bad()>',frame_ref:'x',owned:null}]};
  renderInventory(doc,snap); const rows=ids.get('inventory-rows').children;
  assert.equal(rows[0].children[0].textContent,'<script>bad()</script>');
  assert.equal(rows[0].children[2].textContent,'Excluded');
  assert.equal(rows[0].children[4].children[0].href,'/api/frames/a%2Fb');
  assert.equal(rows[1].children[3].textContent,'<img onerror=bad()>');
  assert.match(ids.get('inventory-summary').textContent,/total books unknown/);
  assert.equal(ids.get('inventory-next').disabled,false);
  renderInventory(doc,null); assert.equal(ids.get('inventory-rows').children.length,0);
});
