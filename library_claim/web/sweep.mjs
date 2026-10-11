import {planRequest,progressSummary} from './sweep_core.mjs';
const $=id=>document.getElementById(id);let session=null,epoch=0,pollVersion=0,timer=null,controller=null,guide=null,state=null,request=null,working=false,cameraPhase=null;
async function api(path,body,signal){const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal});const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${response.status})`);return data;}
function render(){
  $('start-plan').disabled=!guide||guide.capture_status!=='capturing'||working||state?.active;
  $('pause').disabled=!state?.active||working;$('resume').disabled=!state?.plan||state?.active||working||state.remaining_attempts===0||guide?.capture_status!=='capturing';
  $('cancel-pending').disabled=!state?.pending?.length||working;
  $('recognition').href=session?`/recognition?session=${session}`:'/recognition';
  $('next-prompt').textContent=guide?.next_prompt||'';
  $('progress').textContent=state?progressSummary(state):'';
  $('associations').replaceChildren();for(const proposal of state?.association_proposals||[]){const p=document.createElement('p');p.textContent=`Alignment for ${proposal.job_id}: ${proposal.status} · ${proposal.links.length} possible links requiring physical review.`;$('associations').append(p);for(const link of proposal.links){const a=document.createElement('a');a.href=`/resolution?session=${session}&observation=${encodeURIComponent(link.observation_id)}`;a.target='_blank';a.rel='noopener';a.textContent=`Review ${link.observation_id} against ${link.anchor_observation_id}${link.proposed_track_id?` (${link.proposed_track_id})`:''}`;$('associations').append(a,document.createElement('br'));}}
}
async function poll(current){
  const version=++pollVersion;controller?.abort();const own=new AbortController();controller=own;const timeout=setTimeout(()=>own.abort(),10000);
  try{const [g,s]=await Promise.all([api(`/api/guidance/${session}`,null,own.signal),api(`/api/guidance/${session}/sweep`,null,own.signal)]);if(current!==epoch||version!==pollVersion)return;
    if(g.id!==session||s.session_id!==session)throw new Error('Session response differs');guide=g;state=s;
    const phase=g.phase==='ready_to_capture'||g.phase==='capture_bound'?'capture_available':null;
    if(phase&&cameraPhase!==phase){cameraPhase=phase;$('camera-panel').src=`/?guidance=${session}`;}
    $('status').textContent=`Session ${session}. Recognition mode: ${s.dispatcher.mode}. Automatic work starts only when you start a plan.`;render();
  }catch(error){if(current===epoch&&version===pollVersion){guide=null;state=null;$('status').textContent=`Progress unavailable: ${error.message}. Start/resume is disabled.`;render();}}
  finally{clearTimeout(timeout);if(current===epoch&&version===pollVersion)timer=setTimeout(()=>void poll(current),2000);}
}
function open(id,fromVoice=false){if(!/^[a-f0-9]{32}$/.test(id))return;const changed=session!==id;if(changed&&guide?.capture_status==='capturing'){$('status').textContent='End the current camera sweep before opening another session.';return;}if(changed)$('camera-panel').src='about:blank';session=id;++epoch;clearTimeout(timer);controller?.abort();guide=null;state=null;request=null;cameraPhase=null;$('session').value=id;history.replaceState(null,'',`/sweep?session=${id}`);if(!fromVoice||changed&&new URL($('voice-panel').src).searchParams.get('session')!==id)$('voice-panel').src=`/voice?session=${id}&embedded=1`;render();void poll(epoch);}
$('open-form').onsubmit=e=>{e.preventDefault();open($('session').value);};
window.addEventListener('message',e=>{if(e.origin===location.origin&&e.source===$('voice-panel').contentWindow&&e.data?.type==='guided_session'&&e.data.session_id!==session)open(e.data.session_id,true);});
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
