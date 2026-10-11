import {planRequest,progressSummary} from './sweep_core.mjs';
export async function mount(document=globalThis.document,environment={}) {
const window=environment.window||globalThis.window,location=environment.location||globalThis.location,history=environment.history||globalThis.history;
const $=id=>document.getElementById(id);let session=null,epoch=0,pollVersion=0,timer=null,controller=null,guide=null,state=null,request=null,working=false,cameraPhase=null;
async function api(path,body,signal){const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal});const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${response.status})`);return data;}
function renderOutcomes(outcomes){
  const summary=$('outcomes'),details=$('outcome-details');if(!summary||!details)return;
  details.replaceChildren();if(!outcomes){summary.textContent='Start a recognition plan to see queued work, results, and failures here.';return;}
  const jobs=outcomes.jobs||{},detection=outcomes.detection||{},reading=outcomes.reading||{};
  summary.textContent=`Jobs: ${jobs.total||0} total · ${jobs.queued||0} queued · ${jobs.running||0} running · ${jobs.completed||0} completed · ${jobs.failed||0} failed · ${jobs.stale||0} stale · ${jobs.cancelled||0} cancelled.`;
  const add=text=>{const p=document.createElement('p');p.textContent=text;details.append(p);};
  if(detection.completed)add(`Book detection: ${detection.book_spine_candidates||0} provisional book-spine candidates; ${detection.non_book_proposals||0} non-book proposals; ${detection.ambiguous_or_review||0} ambiguous/review proposals; ${detection.unresolved_regions||0} unresolved regions across ${detection.completed} completed detection jobs.`);
  if(detection.uncertain_coverage||detection.no_visible_books||detection.clear_coverage)add(`Coverage assertions: ${detection.clear_coverage||0} clear · ${detection.uncertain_coverage||0} uncertain · ${detection.no_visible_books||0} no visible books. Coverage is not independently verified.`);
  if(reading.completed)add(`Spine reading: ${reading.readable||0} readable proposals; ${reading.partial_or_unreadable||0} partial or unreadable proposals. Readable text is not an accepted title or edition.`);
  for(const failure of outcomes.failures||[])add(`Attention: ${failure.kind||'recognition'} job ${failure.job_id||'unknown'} is ${failure.status||'unavailable'} (${failure.reason||'no result available'}).`);
}
function render(){
  $('start-plan').disabled=!guide||guide.capture_status!=='capturing'||working||state?.active;
  $('pause').disabled=!state?.active||working;$('resume').disabled=!state?.plan||state?.active||working||state.remaining_attempts===0||guide?.capture_status!=='capturing';
  $('cancel-pending').disabled=!state?.pending?.length||working;
  if($('recognition')) $('recognition').href=session?`/recognition?session=${session}`:'/recognition';
  $('next-prompt').textContent=guide?.next_prompt||'';
  $('progress').textContent=state?progressSummary(state):'';
  renderOutcomes(state?.outcomes);
  $('associations').replaceChildren();for(const proposal of state?.association_proposals||[]){const p=document.createElement('p');p.textContent=`Alignment for ${proposal.job_id}: ${proposal.status} · ${proposal.links.length} possible links requiring physical review.`;$('associations').append(p);for(const link of proposal.links){const a=document.createElement('a');a.href=`/resolution?session=${session}&observation=${encodeURIComponent(link.observation_id)}`;a.target='_blank';a.rel='noopener';a.textContent=`Review ${link.observation_id} against ${link.anchor_observation_id}${link.proposed_track_id?` (${link.proposed_track_id})`:''}`;$('associations').append(a,document.createElement('br'));}}
}
async function poll(current){
  const version=++pollVersion;controller?.abort();const own=new AbortController();controller=own;const timeout=setTimeout(()=>own.abort(),10000);
  try{const [g,s]=await Promise.all([api(`/api/guidance/${session}`,null,own.signal),api(`/api/guidance/${session}/sweep`,null,own.signal)]);if(current!==epoch||version!==pollVersion)return;
    if(g.id!==session||s.session_id!==session)throw new Error('Session response differs');guide=g;state=s;
    const phase=g.phase==='ready_to_capture'||g.phase==='capture_bound'?'capture_available':null;
    if(phase&&cameraPhase!==phase){cameraPhase=phase;environment.onCaptureReady?.(g);updateCameraPanel();}
    $('status').textContent=`Session ${session}. Recognition mode: ${s.dispatcher.mode}. Automatic work starts only when you start a plan.`;render();
  }catch(error){if(current===epoch&&version===pollVersion){guide=null;state=null;$('status').textContent=`Progress unavailable: ${error.message}. Start/resume is disabled.`;render();}}
  finally{clearTimeout(timeout);if(current===epoch&&version===pollVersion)timer=setTimeout(()=>void poll(current),2000);}
}
function updateCameraPanel(){
  const panel=$('camera-panel');if(!panel)return;
  if(!session){panel.src='about:blank';return;}
  const target=`/?guidance=${encodeURIComponent(session)}`;
  if(panel.getAttribute('src')!==target) panel.src=target;
}
function open(id){if(!/^[a-f0-9]{32}$/.test(id))return;session=id;++epoch;clearTimeout(timer);controller?.abort();guide=null;state=null;request=null;cameraPhase=null;$('session').value=id;updateCameraPanel();render();void poll(epoch);}
window.addEventListener('message',event=>{
  if(event.origin===location.origin&&event.data?.type==='guided_session'&&/^[a-f0-9]{32}$/.test(event.data.session_id)){
    if(session!==event.data.session_id) open(event.data.session_id);
  }
});
$('open-form').onsubmit=e=>{e.preventDefault();open($('session').value);};
async function mutate(path,body){if(working||!session)return;working=true;render();const selected=session,current=epoch;
  try{await api(`/api/guidance/${selected}/sweep/${path}`,body,AbortSignal.timeout(10000));if(current===epoch){clearTimeout(timer);await poll(current);}}
  catch(error){if(current===epoch)$('status').textContent=`Request not confirmed: ${error.message}. Saved plan state will refresh; nothing is automatically retried.`;}
  finally{working=false;if(current===epoch)render();}}
$('plan-form').onsubmit=e=>{e.preventDefault();if(!guide||working)return;
  let payload;try{const values=Object.fromEntries(['shelf','x0','y0','x1','y1','min-area','max-overlap','budget','interval','expected-shelves'].map(id=>[id,$(id).value]));values.consent=$('consent').checked;payload=planRequest(guide,values,'pending');delete payload.plan_id;}catch(error){$('status').textContent=error.message;return;}
  const key=JSON.stringify(payload);if(!request||request.key!==key)request={key,body:{plan_id:crypto.randomUUID(),...payload}};void mutate('start',request.body);};
$('pause').onclick=()=>void mutate('pause',{session_id:session});$('resume').onclick=()=>{if(state?.plan)void mutate('start',state.plan);};
$('cancel-pending').onclick=()=>void mutate('cancel',{session_id:session});
window.addEventListener('pagehide',()=>{++epoch;clearTimeout(timer);controller?.abort();});
const id=new URL(location.href).searchParams.get('session');if(id)open(id);else render();
return {open};
}
