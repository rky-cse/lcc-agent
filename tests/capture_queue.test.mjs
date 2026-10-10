import test from 'node:test';
import assert from 'node:assert/strict';
import {EvidenceQueue, LatestPreview, acquireCamera} from '../library_claim/web/queue.mjs';

const entry = (id, size=3) => ({upload_id:id, blob:new Blob(['x'.repeat(size)])});

test('slow upload remains counted; FIFO and count/byte limits bound memory', async()=>{
  let release; const sent=[];
  const queue=new EvidenceQueue(async item=>{sent.push(item.upload_id); if(item.upload_id==='a') await new Promise(resolve=>{release=resolve;});}, {maxCount:2,maxBytes:6});
  assert.equal(queue.push(entry('a')),true);
  assert.equal(queue.push(entry('b')),true);
  assert.equal(queue.push(entry('c')),false);
  assert.equal(queue.bytes,6);
  const drained=queue.drain(); release(); await drained;
  assert.deepEqual(sent,['a','b']); assert.equal(queue.bytes,0);
});

test('byte limit rejects a single large frame without sending', ()=>{
  const queue=new EvidenceQueue(()=>assert.fail('must not send'),{maxBytes:2});
  assert.equal(queue.push(entry('large')),false); assert.equal(queue.items.length,0);
});

test('lost acknowledgement pauses and retries exact object and upload ID', async()=>{
  const calls=[]; let fail=true;
  const queue=new EvidenceQueue(async item=>{calls.push(item); if(fail) throw new Error('disconnect');});
  const frame=entry('stable'); queue.push(frame);
  await assert.rejects(queue.drain(),/disconnect/);
  assert.equal(queue.items[0],frame); assert.equal(queue.bytes,3);
  fail=false; queue.resume(); await queue.drain();
  assert.deepEqual(calls,[frame,frame]); assert.equal(queue.items.length,0);
});

test('preview replaces old preview independently of a blocked evidence queue', async()=>{
  let release; const queue=new EvidenceQueue(()=>new Promise(resolve=>{release=resolve;}));
  queue.push(entry('evidence'));
  const preview=new LatestPreview(), epoch=preview.begin();
  preview.put('old',epoch); preview.put('latest',epoch);
  assert.equal(preview.value,'latest'); assert.equal(queue.items[0].upload_id,'evidence');
  const drained=queue.drain(); release(); await drained;
});

test('reset rejects a late preview from the previous camera generation', ()=>{
  const preview=new LatestPreview(), old=preview.begin(); preview.clear(); const current=preview.begin();
  assert.equal(preview.put('stale',old),false); assert.equal(preview.put('current',current),true);
});

test('discard requires upload stopped and returns each unresolved frame', async()=>{
  const queue=new EvidenceQueue(async()=>{throw new Error('offline');});
  queue.push(entry('pending')); await assert.rejects(queue.drain());
  const removed=queue.discard(); assert.equal(removed[0].upload_id,'pending'); assert.equal(queue.bytes,0);
});

test('late camera permission result after timeout releases all tracks', async()=>{
  let release, stopped=0;
  const stream={getTracks:()=>[{stop:()=>++stopped}]};
  const request=acquireCamera(()=>new Promise(resolve=>{release=resolve;}),{}, {isCurrent:()=>true,timeoutMs:5});
  await assert.rejects(request,/still pending/);
  release(stream); await Promise.resolve(); await Promise.resolve();
  assert.equal(stopped,1);
});

test('camera arriving after pause/reset releases tracks and never becomes active', async()=>{
  let release, current=true, stopped=0;
  const request=acquireCamera(()=>new Promise(resolve=>{release=resolve;}),{}, {isCurrent:()=>current});
  current=false; release({getTracks:()=>[{stop:()=>++stopped}]});
  await assert.rejects(request,/cancelled/); assert.equal(stopped,1);
});

test('successful current camera is returned without stopping it', async()=>{
  let stopped=0; const stream={getTracks:()=>[{stop:()=>++stopped}]};
  assert.equal(await acquireCamera(()=>Promise.resolve(stream),{}, {isCurrent:()=>true}),stream);
  assert.equal(stopped,0);
});
