import {pcm16,encode,Playback,ConnectionGeneration,ReconnectBudget} from './voice_core.mjs';
import {executionRequest,renderCorrections} from './corrections.mjs';
export async function mount(document=globalThis.document, environment={}) {
const window=environment.window||globalThis.window, location=environment.location||globalThis.location, history=environment.history||globalThis.history;
const $=id=>document.getElementById(id), generation=new ConnectionGeneration();
let state=null,socket=null,ready=false,context=null,playback=null,stream=null,node=null,source=null,pending=null,micStarting=false,micGeneration=0,connecting=false;
const executionRequests=new Map();let executing=false;const reconnect=new ReconnectBudget();let resumeMicrophone=false,skipAudioTurn=false;
const status=text=>{$('status').textContent=text;};
async function api(path,body) {const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});if(!response.ok)throw new Error(`Request failed (${response.status}). Refresh the session before retrying.`);return response.json();}
function render() {
  environment.onState?.(state);
  $('prompt').textContent=state?.next_prompt||'';
  const progress=state?.recognition_progress;
  $('recognition-progress').textContent=progress?`Saved recognition: ${JSON.stringify(progress.counts)}. Identity, coverage and packet readiness still require their own stages.`:'';
  if($('combined-sweep')) $('combined-sweep').href=state?`/sweep?session=${state.id}`:'/sweep';
  if($('reading-review')) $('reading-review').href=state?`/recognition?session=${state.id}`:'/recognition';
  $('connect').disabled=!state||!!socket||connecting;$('disconnect').disabled=!socket&&!connecting;
  $('mic').disabled=!ready||!!stream||micStarting;$('mute').disabled=!stream&&!micStarting;$('silence').disabled=!ready;
  $('send').disabled=!ready;$('preview').disabled=!ready||state?.capture_status!=='capturing';
  $('confirm').disabled=!pending||pending.cancelled;$('reject').disabled=!pending;
  if(pending?.command?.payload?.action==='reference'&&pending.command.payload.width_cm!=null&&pending.command.payload.height_cm!=null){
    pending.command.payload.dimensions_verified=true;
  }
  $('proposal').textContent=pending?JSON.stringify(pending.command.payload,null,2):'No proposed answer yet.';
  $('bind').disabled=!state||state.phase!=='ready_to_capture';
  if($('capture')) $('capture').hidden=!state?.capture_start_proposal;
  if(state?.capture_start_proposal && $('capture')) $('capture').href=`/?guidance=${state.id}`;
  if($('ready-card')) {
    $('ready-card').hidden = state?.phase !== 'ready_to_capture';
    if(state && $('capture-link')) $('capture-link').href = `/?guidance=${state.id}`;
  }
  if($('direct-setup')) $('direct-setup').hidden = !state;
  if($('direct-skip-ref')) $('direct-skip-ref').disabled = !state || state.phase !== 'awaiting_reference';
  if($('direct-ref-save')) $('direct-ref-save').disabled = !state || state.phase !== 'awaiting_reference';
  if($('direct-locale-save')) $('direct-locale-save').disabled = !state || state.phase !== 'awaiting_locale';
  $('refresh-guidance').disabled=!state||executing;
  if(!executing)renderCorrections($('corrections'),state,executeCorrection);
}
async function executeCorrection(intent,decision,button) {
  if(executing)return;executing=true;button.disabled=true;
  const id=state.id,key=`${id}/${intent.intent_id}/${decision}`;
  if(!executionRequests.has(key))executionRequests.set(key,executionRequest(state,intent,decision,crypto.randomUUID()));
  try {const result=await api(`/api/guidance/${id}/corrections`,executionRequests.get(key));if(state?.id!==id)return;
    state=result.guidance;status(result.execution.applied?'Book correction applied and acknowledged.':`Correction outcome: ${result.execution.status}.`);send({type:'refresh'});
  }catch(error){if(state?.id===id){status(error.message+' Refresh guided state to inspect or resume the saved request.');state=await api(`/api/guidance/${id}`);}}
  finally{executing=false;render();}
}
$('refresh-guidance').onclick=async()=>{const id=state.id;try{const latest=await api(`/api/guidance/${id}`);if(state?.id===id){state=latest;await nextProposal();render();}}catch(error){status(error.message);}};
function send(value) {if(ready&&socket?.readyState===WebSocket.OPEN&&socket.bufferedAmount<64000) {socket.send(JSON.stringify(value));return true;}return false;}
async function stopMic() {
  ++micGeneration;micStarting=false;stream?.getTracks().forEach(t=>t.stop());stream=null;
  node?.disconnect();source?.disconnect();node=null;source=null;
  send({type:'audio_end'});render();
}
function disconnect(manual=true) {if(manual){reconnect.stop();resumeMicrophone=false;}generation.next();connecting=false;ready=false;void stopMic();playback?.clear();if(socket){try{socket.send(JSON.stringify({type:'close'}));}catch{}socket.close();}socket=null;render();}
async function open(id,create=false) {
  if(environment.canSwitch && !environment.canSwitch(id))throw new Error('End the current sweep before changing sessions.');
  disconnect();pending=null;state=await api(create?'/api/guidance':`/api/guidance/${id}`,create?{session_id:id}:null);
  $('session').value=state.id;history.replaceState(null,'',`/voice?session=${state.id}`);
  const journal=await api(`/api/guidance/${state.id}/voice`);
  $('transcript').replaceChildren();for(const event of journal.events.filter(e=>e.kind==='transcript'||e.kind==='text').slice(-40)) transcript(event.payload);
  const applied=new Set(state.events.map(e=>e.command.command_id));
  pending=Object.values(journal.proposals).find(p=>!p.cancelled&&!p.dismissed&&!applied.has(p.command.command_id))||null;
  status('Session opened. Review pending answers; connect voice when ready.');render();
  if(window.parent!==window)window.parent.postMessage({type:'guided_session',session_id:state.id},location.origin);
}
function recoverVoice(reason){resumeMicrophone=resumeMicrophone||!!stream||micStarting;disconnect(false);const scheduled=reconnect.schedule(()=>connectVoice(true));status(scheduled?reason+' Reconnecting automatically…':reason+' Automatic recovery stopped after three attempts. Use Connect voice to retry.');}
function transcript(event) {const row=document.createElement('li');row.textContent=`${event.speaker}: ${event.text}`;$('transcript').append(row);while($('transcript').children.length>200)$('transcript').firstChild.remove();}
async function nextProposal() {
  const id=state.id,journal=await api(`/api/guidance/${id}/voice`);
  if(state.id!==id)return;
  const applied=new Set(state.events.map(e=>e.command.command_id));
  pending=Object.values(journal.proposals).find(p=>!p.cancelled&&!p.dismissed&&!applied.has(p.command.command_id))||null;render();
}
$('new').onclick=()=>open(crypto.randomUUID().replaceAll('-',''),true).catch(e=>status(e.message));
$('open').onclick=()=>{if(/^[a-f0-9]{32}$/.test($('session').value))void open($('session').value).catch(e=>status(e.message));else status('Enter a valid guided session ID.');};
async function connectVoice(recovering=false){
  if(!state||socket||connecting)return;
  if(!recovering)reconnect.start();
  const current=generation.next(),id=state.id;connecting=true;render();
  try {
    const health=await api('/api/health');if(!health.voice_enabled)throw new Error('Voice is disabled on this local server. Start it with the documented free-tier voice options.');
    if(current!==generation.value||state?.id!==id)return;
    context ||= new AudioContext();await context.resume();playback ||=new Playback(context);
    if(current!==generation.value||state?.id!==id)return;
    socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/voice/${id}`);connecting=false;render();status('Connecting voice…');
    socket.onmessage=event=>{
      if(current!==generation.value)return;
      try {
        const message=JSON.parse(event.data);
        if(message.type==='error'){recoverVoice(message.message);return;}
        if(!generation.accepts(current,message))return;
        if(message.type==='ready'){ready=true;skipAudioTurn=false;state=message.state;send({type:'watch',enabled:$('watch-sweep').checked});status(resumeMicrophone?'Voice restored. Restarting microphone…':'Voice connected. Start microphone to speak.');if(resumeMicrophone)void startMicrophone();}
        else if(message.type==='audio'&&!skipAudioTurn){try{if(!playback.play(message.data)){skipAudioTurn=true;status('Playback paused because the answer was too long. Voice remains connected; ask for a shorter answer.');}}catch{playback.clear();skipAudioTurn=true;status('Audio could not be played. Voice remains connected; ask the agent to repeat.');}}
        else if(message.type==='interrupted'){playback.clear();skipAudioTurn=false;}else if(message.type==='turn_complete')skipAudioTurn=false;
        else if(message.type==='transcript')transcript(message);
        else if(message.type==='proposal') {if(!pending)pending=message.proposal;status('Review the proposed answer before confirming.');}
        else if(message.type==='cancelled'&&pending&&message.ids.includes(pending.call_id))pending.cancelled=true;
        else if(message.type==='state')state=message.state;
        else if(message.type==='reconnect_required'){recoverVoice('Provider is refreshing the voice connection. Saved state is retained.');}
        else if(message.type==='input_error')status(message.message);
        render();
      } catch{recoverVoice('Voice received an invalid response; restoring saved conversation.');}
    };
    socket.onclose=()=>{if(current===generation.value){recoverVoice('Voice transport closed; restoring the conversation.');}};
    socket.onerror=()=>{if(current===generation.value)status('Voice unavailable. Check that the local server has voice enabled, then reconnect.');};
  }catch(error){if(current===generation.value)recoverVoice(error.message);}
}
$('connect').onclick=()=>void connectVoice();
$('disconnect').onclick=()=>{disconnect();status('Voice disconnected. Capture has not ended.');};
$('watch-sweep').onchange=()=>{send({type:'watch',enabled:$('watch-sweep').checked});};
$('silence').onclick=()=>{playback?.clear();status('Playback cleared. Speak to interrupt the provider, or disconnect voice.');};
async function startMicrophone(){
  if(!ready||stream||micStarting)return;
  const epoch=generation.value,request=++micGeneration;micStarting=true;render();let acquired;
  try {
    acquired=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
    if(epoch!==generation.value||!ready||request!==micGeneration){acquired.getTracks().forEach(t=>t.stop());return;}
    await context.audioWorklet.addModule('/assets/pcm-worklet.mjs');
    if(epoch!==generation.value||request!==micGeneration){acquired.getTracks().forEach(t=>t.stop());return;}
    stream=acquired;source=context.createMediaStreamSource(stream);node=new AudioWorkletNode(context,'capture-pcm');
    node.port.onmessage=event=>{if(epoch===generation.value&&stream&&ready){if(!send({type:'audio',data:encode(pcm16(event.data,context.sampleRate))})){recoverVoice('Voice upload fell behind; restoring the connection.');}}};
    source.connect(node);node.connect(context.destination);status('Microphone on. Speak briefly; review proposed answers.');
    const ownStream=stream;stream.getTracks().forEach(t=>t.addEventListener('ended',()=>{if(stream===ownStream){resumeMicrophone=false;void stopMic();status('Microphone ended. Start it again when ready.');}},{once:true}));
  }catch(error){acquired?.getTracks().forEach(t=>t.stop());status(`Microphone unavailable: ${error.message}`);}
  finally{if(request===micGeneration)micStarting=false;render();}
}
$('mic').onclick=()=>void startMicrophone();
$('mute').onclick=()=>{resumeMicrophone=false;void stopMic();status('Microphone off. Voice connection remains open.');};
$('text-form').onsubmit=event=>{event.preventDefault();const text=$('text').value.trim();if(text&&send({type:'text',text})){$('text').value='';transcript({speaker:'claimant',text});}else status('Answer not sent. Connect voice first.');};
$('frame-form').onsubmit=event=>{event.preventDefault();if(!send({type:'frame',frame_ref:$('frame').value.trim()}))status('Preview not sent. Connect voice first.');};
$('confirm').onclick=async()=>{
  const proposal=pending,id=state.id;if(!proposal||proposal.cancelled||proposal.dismissed)return;$('confirm').disabled=true;
  try {
    const cmd={...proposal.command,expected_revision:state.revision};
    if(cmd.payload?.action==='reference'&&cmd.payload.width_cm!=null&&cmd.payload.height_cm!=null){
      cmd.payload={...cmd.payload,dimensions_verified:true};
    }
    const result=await api(`/api/guidance/${id}/turns`,cmd);if(state.id!==id)return;state=result;pending=null;$('saved').textContent='Answer saved to guidance. Any book correction remains pending review.';send({type:'refresh'});await nextProposal();}
  catch(error){if(state.id===id){status(error.message);state=await api(`/api/guidance/${id}`);}}
  finally{render();}
};
if($('direct-skip-ref')) {
  $('direct-skip-ref').onclick=async()=>{
    if(!state||state.phase!=='awaiting_reference')return;
    try {
      const result=await api(`/api/guidance/${state.id}/turns`,{
        command_id:crypto.randomUUID().replaceAll('-',''),
        session_id:state.id,
        expected_revision:state.revision,
        speaker:'claimant',
        payload:{action:'skip_reference',claimant_statement:'Skip reference object'}
      });
      state=result;pending=null;
      $('saved').textContent='Reference skipped. You are ready to start camera capture.';
      status('Reference skipped. Ready for camera capture.');
      send({type:'refresh'});render();
    }catch(e){status(e.message);}
  };
}
if($('direct-ref-save')) {
  $('direct-ref-save').onclick=async()=>{
    if(!state||state.phase!=='awaiting_reference')return;
    const desc=$('ref-desc')?.value.trim()||'Card';
    const width=parseFloat($('ref-width')?.value);
    const height=parseFloat($('ref-height')?.value);
    const tol=parseFloat($('ref-tol')?.value)||0.05;
    const prov=$('ref-prov')?.value.trim()||'Measured with ruler';
    if(isNaN(width)||isNaN(height)||width<=0||height<=0){status('Enter valid positive width and height in cm.');return;}
    if(tol>=width||tol>=height){status('Tolerance must be smaller than dimensions.');return;}
    try {
      const result=await api(`/api/guidance/${state.id}/turns`,{
        command_id:crypto.randomUUID().replaceAll('-',''),
        session_id:state.id,
        expected_revision:state.revision,
        speaker:'claimant',
        payload:{
          action:'reference',
          description:desc,
          width_cm:String(width),
          height_cm:String(height),
          width_uncertainty_cm:String(tol),
          height_uncertainty_cm:String(tol),
          dimensions_verified:true,
          dimension_provenance:prov,
          claimant_statement:`${desc}: ${width} cm x ${height} cm, tol ±${tol} cm, ${prov}`
        }
      });
      state=result;pending=null;
      $('saved').textContent='Reference dimensions verified and saved. Ready for camera capture.';
      status('Reference dimensions saved. Ready for camera capture.');
      send({type:'refresh'});render();
    }catch(e){status(e.message);}
  };
}
if($('direct-locale-save')) {
  $('direct-locale-save').onclick=async()=>{
    if(!state||state.phase!=='awaiting_locale')return;
    const country=$('direct-country')?.value.trim().toUpperCase();
    const currency=$('direct-currency')?.value.trim().toUpperCase();
    if(!country||country.length!==2||!currency||currency.length!==3){status('Enter 2-letter country (e.g. IN) and 3-letter currency (e.g. INR).');return;}
    try {
      const result=await api(`/api/guidance/${state.id}/turns`,{
        command_id:crypto.randomUUID().replaceAll('-',''),
        session_id:state.id,
        expected_revision:state.revision,
        speaker:'claimant',
        payload:{action:'locale',country,currency,claimant_statement:`Country ${country}, Currency ${currency}`}
      });
      state=result;pending=null;
      $('saved').textContent='Country and currency saved. Provide reference object details next.';
      status('Locale saved. Provide reference object details next.');
      send({type:'refresh'});render();
    }catch(e){status(e.message);}
  };
}
$('reject').onclick=async()=>{const id=state.id,proposal=pending;if(!proposal)return;try{await api(`/api/guidance/${id}/voice/dismiss`,{call_id:proposal.call_id});if(state.id===id){pending=null;await nextProposal();status('Proposal dismissed. Nothing was saved to guidance.');}}catch(error){status(error.message);}};
$('bind').onclick=async()=>{
  try {state=await api(`/api/guidance/${state.id}/turns`,{command_id:crypto.randomUUID(),session_id:state.id,expected_revision:state.revision,speaker:'agent',payload:{action:'bind_capture'}});send({type:'refresh'});render();}
  catch(error){status(error.message);}
};
window.addEventListener('pagehide',disconnect);
document.addEventListener('visibilitychange',()=>{if(document.hidden){void stopMic();playback?.clear();}});
if(new URL(location.href).searchParams.get('embedded')==='1')$('watch-sweep').checked=true;
render();const id=new URL(location.href).searchParams.get('session');if(id&&/^[a-f0-9]{32}$/.test(id))await open(id).catch(e=>status(e.message));

return {open,connect:connectVoice,startMicrophone,disconnect,refresh:async()=>{if(state){state=await api(`/api/guidance/${state.id}`);render();}},getState:()=>state};
}
if(globalThis.document?.querySelector('script[src="/assets/voice.mjs"]')) await mount();
