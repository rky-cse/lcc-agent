import {EvidenceQueue, LatestPreview, acquireCamera} from './queue.mjs';
import {InventoryPoller, renderInventory} from './inventory.mjs';

const $ = id => document.getElementById(id);
const video = $('video'), nativeCanvas = document.createElement('canvas'), previewCanvas = document.createElement('canvas');
const preview = new LatestPreview();
let stream = null, timer = null, generation = 0, starting = false, encoding = null, finishing = false;
let sweep = null, nextSequence = 0, gaps = 0, saved = new Map(), recovery = [], endId = null;
let recovering=true, recoveryFailed=false, encodingRef=null, startIntent=null;
const storageKey = 'library-capture-v1';
const inventory = new InventoryPoller({
  fetchSnapshot: async (id,offset,signal) => {
    const response=await fetch(`/api/sweeps/${encodeURIComponent(id)}/inventory?offset=${offset}`,{signal});
    if(!response.ok) throw new Error(`Inventory request failed (${response.status})`);
    return response.json();
  },
  changed: data => {renderInventory(document,data); $('inventory-error').hidden=true;},
  failed: error => { $('inventory-error').textContent=`Inventory updates unavailable: ${error.message}. Displayed rows may be stale; retrying automatically.`; $('inventory-error').hidden=false; }
});
function watchInventory() { if(!document.hidden) inventory.watch(sweep?.id || null); }
let preferencesError = false;
try {
  const prior = JSON.parse(localStorage.getItem(storageKey) || 'null');
  if (prior) { sweep = {id: prior.id}; nextSequence = prior.nextSequence; gaps = prior.gaps; recovery = prior.pending || []; endId = prior.endId; }
  startIntent=JSON.parse(localStorage.getItem('library-capture-start-intent') || 'null');
  if(startIntent&&!sweep) { $('country').value=startIntent.country; $('currency').value=startIntent.currency; }
} catch { preferencesError = true; }

function status(message) { $('status').textContent = message; }
function persist() {
  try {
    if (!sweep) { localStorage.removeItem(storageKey); return; }
    localStorage.setItem(storageKey, JSON.stringify({id:sweep.id, nextSequence, gaps, endId, pending:[...new Set([...queue.items.map(x=>x.upload_id),...(encodingRef?[encodingRef]:[])])]}));
  } catch { preferencesError = true; }
}
function refresh() {
  $('counts').textContent = `${saved.size} saved · ${queue.items.length} queued (${(queue.bytes/1048576).toFixed(1)} MiB) · ${gaps} capture gaps`;
  $('start').disabled = starting || !!stream || finishing || recovering || recoveryFailed;
  $('stop').disabled = !stream && !starting;
  $('end').disabled = !sweep || sweep.status === 'closed' || finishing;
  $('retry').disabled = !queue.paused;
  $('discard').hidden = !queue.paused || !queue.items.length;
  $('country').disabled = !!sweep && sweep.status !== 'closed';
  $('currency').disabled = !!sweep && sweep.status !== 'closed';
  $('camera').disabled = !!stream || starting;
  $('open-sweep').disabled = !!stream || starting || finishing || recovering || !!encoding || !!queue.items.length;
  $('inventory-retry').disabled = !sweep;
  persist();
}
async function api(path, options = {}) {
  const controller = new AbortController(), timeout = setTimeout(()=>controller.abort(), 30000);
  try {
    const response = await fetch(path, {...options, signal:controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  } finally { clearTimeout(timeout); }
}
function recordFrame(frame, signals = null) {
  if (!saved.has(frame.id)) {
    const li = document.createElement('li'), link = document.createElement('a');
    link.href = `/api/frames/${encodeURIComponent(frame.id)}`; link.target = '_blank'; link.rel = 'noopener';
    link.textContent = `Frame ${frame.media_sequence + 1}: ${frame.width} × ${frame.height} · ${frame.captured_at}`;
    li.append(link); $('frames').append(li); saved.set(frame.id, frame);
  }
  if (signals) {
    const hints = [signals.possible_blur && 'Possible blur: slow down or hold steady', signals.possible_glare && 'Possible glare: change the angle slightly'].filter(Boolean);
    $('quality').textContent = hints.join(' · ') || 'No blur/glare hint on the last saved frame (not a readability guarantee).';
  }
}
const queue = new EvidenceQueue(async item => {
  const query = new URLSearchParams({upload_id:item.upload_id, captured_at:item.captured_at, media_sequence:String(item.media_sequence)});
  const result = await api(`/api/sweeps/${item.sweep_id}/frames?${query}`, {method:'POST', headers:{'Content-Type':item.blob.type}, body:item.blob});
  if (!result.durable || result.frame.upload_id !== item.upload_id) throw new Error('Frame acknowledgement did not match');
  recordFrame(result.frame, result.quality);
}, {changed: q => { refresh(); if(q.paused) status(`Uploads paused: ${q.error?.message}. Frames remain queued; use Retry uploads.`); }});

async function restore() {
  if (!sweep) return;
  try {
    sweep = await api(`/api/sweeps/${sweep.id}`);
    watchInventory();
    $('country').value = sweep.country; $('currency').value = sweep.currency;
    for (const frame of sweep.frames) recordFrame(frame, sweep.quality?.[frame.id]);
    const acknowledged = new Set(sweep.frames.map(x=>x.upload_id));
    const lost = recovery.filter(id=>!acknowledged.has(id)).length;
    gaps += lost; recovery = [];
    $('manifest').href = `/api/sweeps/${sweep.id}/manifest`; $('manifest').hidden = false;
    status(lost ? `${lost} unsaved frames were lost when the page closed. These are recorded as capture gaps.` :
      sweep.status === 'closed' ? 'Previous sweep closed. You can start a new sweep.' : 'Previous sweep recovered. Resume the camera or end the sweep.');
    refresh();
  } catch(error) { recoveryFailed=true; status(`Cannot recover sweep: ${error.message}. Reload after restoring the connection.`); }
}
function stopCamera() {
  ++generation; clearInterval(timer); timer = null; preview.clear();
  if(stream) stream.getTracks().forEach(track=>track.stop());
  stream = null; video.srcObject = null; $('resolution').textContent = 'Camera paused'; refresh();
}
function blob(canvas, quality) { return new Promise((resolve,reject)=>canvas.toBlob(value=>value ? resolve(value) : reject(new Error('Camera encoding failed')), 'image/jpeg', quality)); }
async function sample(epoch) {
  if (!stream || epoch !== generation || !video.videoWidth) return;
  if (encoding) { ++gaps; refresh(); return; }
  const capture = async () => {
    const captured_at = new Date().toISOString(), sequence = nextSequence++, previewEpoch=preview.generation;
    const upload_id = crypto.randomUUID();
    encodingRef=upload_id; persist();
    nativeCanvas.width = video.videoWidth; nativeCanvas.height = video.videoHeight;
    nativeCanvas.getContext('2d').drawImage(video,0,0);
    previewCanvas.width = 320; previewCanvas.height = Math.round(video.videoHeight*320/video.videoWidth);
    previewCanvas.getContext('2d').drawImage(video,0,0,previewCanvas.width,previewCanvas.height);
    // The slot and FIFO are independent: preview cannot overwrite evidence.
    const previewBlob = await blob(previewCanvas,.6);
    preview.put(previewBlob, previewEpoch);
    const evidence = await blob(nativeCanvas,.92);
    if (!queue.push({sweep_id:sweep.id, upload_id, captured_at, media_sequence:sequence, blob:evidence})) {
      ++gaps; status('Upload queue is full. Slow down; omitted keyframes are counted as capture gaps.');
    }
    encodingRef=null;
    refresh();
  };
  encoding = capture();
  try { await encoding; } catch(error) { ++gaps; status(error.message); refresh(); }
  finally { encoding = null; encodingRef=null; refresh(); }
}
async function startCamera() {
  if (starting || stream || finishing) return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) { status('Camera access needs localhost or trusted HTTPS in a supported browser.'); return; }
  if (!$('settings').reportValidity()) return;
  starting = true; const epoch = ++generation; refresh();
  status('Requesting camera access. Allow camera permission for this local page.');
  let acquired = null;
  try {
    const device = $('camera').value;
    acquired = await acquireCamera(constraints=>navigator.mediaDevices.getUserMedia(constraints),
      {audio:false, video:{width:{ideal:1920},height:{ideal:1080}, ...(device ? {deviceId:{exact:device}} : {facingMode:{ideal:'environment'}})}},
      {isCurrent:()=>epoch===generation});
    if(epoch !== generation) { acquired.getTracks().forEach(t=>t.stop()); return; }
    video.srcObject = acquired; await video.play();
    if(epoch !== generation) { acquired.getTracks().forEach(t=>t.stop()); return; }
    if (Math.min(video.videoWidth,video.videoHeight)<720 || Math.max(video.videoWidth,video.videoHeight)<1280) throw new Error(`Camera provides ${video.videoWidth} × ${video.videoHeight}; select a camera supporting at least 1280 × 720.`);
    if (!sweep || sweep.status === 'closed') {
      const country=$('country').value, currency=$('currency').value;
      if(!startIntent||startIntent.country!==country||startIntent.currency!==currency) startIntent={start_id:crypto.randomUUID().replaceAll('-',''),country,currency};
      try { localStorage.setItem('library-capture-start-intent',JSON.stringify(startIntent)); } catch { preferencesError=true; }
      sweep = await api('/api/sweeps', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(startIntent)});
      startIntent=null;
      try { localStorage.removeItem('library-capture-start-intent'); } catch { preferencesError=true; }
      saved = new Map(); $('frames').replaceChildren(); nextSequence=0; gaps=0; endId=null;
      watchInventory();
    }
    persist();
    if(epoch !== generation) { acquired.getTracks().forEach(t=>t.stop()); return; }
    stream = acquired;
    stream.getVideoTracks().forEach(track=>track.addEventListener('ended',()=>{ ++gaps; stopCamera(); status('Camera ended unexpectedly. Resume it to continue the same sweep.'); },{once:true}));
    const devices = await navigator.mediaDevices.enumerateDevices();
    if(epoch !== generation) { acquired.getTracks().forEach(t=>t.stop()); return; }
    $('camera').replaceChildren(new Option('Default camera',''));
    devices.filter(d=>d.kind==='videoinput').forEach(d=>$('camera').append(new Option(d.label||'Camera',d.deviceId)));
    $('resolution').textContent = `Evidence ${video.videoWidth} × ${video.videoHeight} · preview 320 px · keyframe every 1.5 s`;
    $('manifest').href = `/api/sweeps/${sweep.id}/manifest`; $('manifest').hidden = false;
    preview.begin(); status('Camera running. Move slowly and keep each shelf in view.');
    timer = setInterval(()=>void sample(epoch),1500); void sample(epoch);
  } catch(error) {
    if(acquired) acquired.getTracks().forEach(t=>t.stop());
    stream=null; video.srcObject=null;
    if(epoch===generation) status(error.name==='NotAllowedError' ? 'Camera permission was denied. Allow camera access for this site, then retry.' : `Camera unavailable: ${error.message}`);
  } finally { starting=false; refresh(); }
}
async function endSweep(discard=false) {
  if (!sweep || finishing) return;
  finishing=true; stopCamera(); refresh();
  try {
    if(encoding) await encoding.catch(()=>{});
    if(discard) {
      if(queue.running) throw new Error('An upload is still running. Wait for it to finish.');
      const snapshot=await api(`/api/sweeps/${sweep.id}`);
      const acked=new Set(snapshot.frames.map(x=>x.upload_id));
      snapshot.frames.forEach(x=>recordFrame(x));
      gaps += queue.discard().filter(x=>!acked.has(x.upload_id)).length;
    } else await queue.drain();
    endId ||= crypto.randomUUID(); persist();
    sweep=await api(`/api/sweeps/${sweep.id}/end`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({end_id:endId,capture_gaps:gaps})});
    status(sweep.transport_complete ? 'Sweep closed; all selected frames were saved. Review the evidence below.' : 'Sweep closed with capture gaps or no saved frames. Review coverage before continuing.');
  } catch(error) { status(`Sweep is not closed: ${error.message}. Retry uploads, then End sweep.`); }
  finally { finishing=false; refresh(); }
}
$('start').onclick=()=>void startCamera(); $('stop').onclick=()=>{stopCamera();status('Camera paused; saved and queued frames are retained.');};
$('retry').onclick=()=>queue.resume(); $('end').onclick=()=>void endSweep(); $('discard').onclick=()=>void endSweep(true);
$('inventory-prev').onclick=()=>inventory.select(sweep?.id,Math.max(0,inventory.offset-50));
$('inventory-next').onclick=()=>inventory.select(sweep?.id,inventory.offset+50);
$('inventory-retry').onclick=()=>inventory.select(sweep?.id,inventory.offset);
$('saved-sweep-form').onsubmit=async event=>{
  event.preventDefault();
  if($('open-sweep').disabled || !$('saved-sweep-form').reportValidity()) return;
  recovering=true; refresh();
  try {
    const restored=await api(`/api/sweeps/${encodeURIComponent($('saved-sweep-id').value)}`);
    sweep=restored; recoveryFailed=false; recovery=[]; endId=restored.end_id;
    nextSequence=Math.max(-1,...restored.frames.map(f=>f.media_sequence))+1;
    gaps=restored.capture_gaps; saved=new Map(); $('frames').replaceChildren();
    restored.frames.forEach(frame=>recordFrame(frame,restored.quality?.[frame.id]));
    $('country').value=restored.country; $('currency').value=restored.currency;
    $('manifest').href=`/api/sweeps/${encodeURIComponent(restored.id)}/manifest`; $('manifest').hidden=false;
    watchInventory(); status(restored.status==='closed' ? 'Saved sweep opened for review.' : 'Saved sweep opened. Resume capture or review its evidence.');
  } catch(error) { status(`Cannot open saved sweep: ${error.message}`); }
  finally { recovering=false; refresh(); }
};
document.addEventListener('visibilitychange',()=>{if(document.hidden) inventory.stop(); else watchInventory();});
window.addEventListener('pagehide',()=>inventory.stop());
for(const name of ['country','currency']) $(name).oninput=()=>{$(name).value=$(name).value.toUpperCase();};
window.addEventListener('beforeunload',event=>{if(stream||starting||encoding||queue.items.length){event.preventDefault();event.returnValue='';}});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&stream){++gaps;stopCamera();status('Camera paused while the page was hidden. Resume to continue.');}});
if(preferencesError) status('Browser recovery storage is unavailable. Keep this page open until uploads finish.');
refresh();
try { const health=await api('/api/health'); $('mode').hidden=!health.synthetic_capture_mode; }
catch(error) { recoveryFailed=true; status(`Capture server unavailable: ${error.message}`); }
await restore(); recovering=false; refresh();
