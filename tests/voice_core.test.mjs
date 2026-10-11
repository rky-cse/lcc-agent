import test from 'node:test';import assert from 'node:assert/strict';
import {pcm16,encode,Playback,ConnectionGeneration} from '../library_claim/web/voice_core.mjs';
test('PCM is signed little endian, resampled and clipped',()=>{
 const buffer=pcm16(new Float32Array([-2,2,0,0]),32000),view=new DataView(buffer);
 assert.equal(view.byteLength,4);assert.equal(view.getInt16(0,true),-32768);assert.equal(view.getInt16(2,true),0);
 assert.equal(encode(buffer),'AIAA AA=='.replaceAll(' ',''));
});
test('invalid audio rate rejected',()=>{assert.throws(()=>pcm16(new Float32Array([0]),0));});
test('old socket and old server epoch cannot deliver audio',()=>{
 const guard=new ConnectionGeneration(),first=guard.next();assert.equal(guard.accepts(first,{type:'audio',epoch:1}),false);
 assert.equal(guard.accepts(first,{type:'ready',epoch:1}),true);assert.equal(guard.accepts(first,{type:'audio',epoch:2}),false);
 const second=guard.next();assert.equal(guard.accepts(first,{type:'ready',epoch:1}),false);assert.equal(guard.accepts(second,{type:'ready',epoch:2}),true);
});
function context(){return {currentTime:0,destination:{},created:[],createBuffer:(_,n,rate)=>({getChannelData:()=>new Float32Array(n),duration:n/rate}),createBufferSource(){const s={connect(){},start(at){this.at=at;},stop(){this.stopped=true;}};this.created.push(s);return s;}};}
test('interruption stops all queued sources and resets playback',()=>{const c=context(),p=new Playback(c);p.play('AAA=');p.play('AAA=');assert.equal(p.sources.size,2);p.clear();assert.equal(p.sources.size,0);assert.equal(p.next,0);assert.ok(c.created.every(s=>s.stopped));});
test('playback refuses growing latency and invalid PCM',()=>{const p=new Playback(context());assert.throws(()=>p.play('AA=='));p.next=6;assert.throws(()=>p.play('AAA='));assert.equal(p.next,0);});
