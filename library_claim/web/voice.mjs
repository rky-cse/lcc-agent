import {pcm16,encode,Playback,ConnectionGeneration} from './voice_core.mjs';
import {executionRequest,renderCorrections} from './corrections.mjs';
const $=id=>document.getElementById(id), generation=new ConnectionGeneration();
let state=null,socket=null,ready=false,context=null,playback=null,stream=null,node=null,source=null,pending=null,micStarting=false,micGeneration=0;
const executionRequests=new Map();let executing=false;
const status=text=>{$('status').textContent=text;};
async function api(path,body) {const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});if(!response.ok)throw new Error(`Request failed (${response.status}). Refresh the session before retrying.`);return response.json();}
function render() {
  $('prompt').textContent=state?.next_prompt||'';
  const progress=state?.recognition_progress;
  $('recognition-progress').textContent=progress?`Saved recognition: ${JSON.stringify(progress.counts)}. Identity, coverage and packet readiness still require their own stages.`:'';
  $('combined-sweep').href=state?`/sweep?session=${state.id}`:'/sweep';$('reading-review').href=state?`/recognition?session=${state.id}`:'/recognition';
  $('connect').disabled=!state||!!socket;$('disconnect').disabled=!socket;
  $('mic').disabled=!ready||!!stream||micStarting;$('mute').disabled=!stream&&!micStarting;$('silence').disabled=!ready;
  $('send').disabled=!ready;$('preview').disabled=!ready||state?.capture_status!=='capturing';
  $('confirm').disabled=!pending||pending.cancelled;$('reject').disabled=!pending;
  $('proposal').textContent=pending?JSON.stringify(pending.command.payload,null,2):'No proposed answer yet.';
  $('bind').disabled=!state||state.phase!=='ready_to_capture';
  $('capture').hidden=!state?.capture_start_proposal;
  if(state?.capture_start_proposal) $('capture').href=`/?guidance=${state.id}`;
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
function disconnect() {generation.next();ready=false;void stopMic();playback?.clear();if(socket){try{socket.send(JSON.stringify({type:'close'}));}catch{}socket.close();}socket=null;render();}
async function open(id,create=false) {
  disconnect();pending=null;state=await api(create?'/api/guidance':`/api/guidance/${id}`,create?{session_id:id}:null);
  $('session').value=state.id;history.replaceState(null,'',`/voice?session=${state.id}`);
  const journal=await api(`/api/guidance/${state.id}/voice`);
  $('transcript').replaceChildren();for(const event of journal.events.filter(e=>e.kind==='transcript'||e.kind==='text').slice(-40)) transcript(event.payload);
  const applied=new Set(state.events.map(e=>e.command.command_id));
  pending=Object.values(journal.proposals).find(p=>!p.cancelled&&!p.dismissed&&!applied.has(p.command.command_id))||null;
  status('Session opened. Review pending answers; connect voice when ready.');render();
  if(window.parent!==window)window.parent.postMessage({type:'guided_session',session_id:state.id},location.origin);
}
function transcript(event) {const row=document.createElement('li');row.textContent=`${event.speaker}: ${event.text}`;$('transcript').append(row);while($('transcript').children.length>200)$('transcript').firstChild.remove();}
async function nextProposal() {
  const id=state.id,journal=await api(`/api/guidance/${id}/voice`);
  if(state.id!==id)return;
  const applied=new Set(state.events.map(e=>e.command.command_id));
  pending=Object.values(journal.proposals).find(p=>!p.cancelled&&!p.dismissed&&!applied.has(p.command.command_id))||null;render();
}
$('new').onclick=()=>open(crypto.randomUUID().replaceAll('-',''),true).catch(e=>status(e.message));
$('open').onclick=()=>{if(/^[a-f0-9]{32}$/.test($('session').value))void open($('session').value).catch(e=>status(e.message));else status('Enter a valid guided session ID.');};
$('connect').onclick=async()=>{
  try {
    const health=await api('/api/health');if(!health.voice_enabled)throw new Error('Voice is disabled on this local server. Start it with the documented free-tier voice options.');
    context ||= new AudioContext();await context.resume();playback ||=new Playback(context);
    const current=generation.next();socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/voice/${state.id}`);render();status('Connecting voice…');
    socket.onmessage=event=>{
      if(current!==generation.value)return;
      try {
        const message=JSON.parse(event.data);
        if(message.type==='error'){status(message.message);disconnect();return;}
        if(!generation.accepts(current,message))return;
        if(message.type==='ready'){ready=true;state=message.state;send({type:'watch',enabled:$('watch-sweep').checked});status(message.resumed?'Voice resumed. Microphone is off until started.':'Voice connected. Microphone is off until started.');}
        else if(message.type==='audio')playback.play(message.data);
        else if(message.type==='interrupted')playback.clear();
        else if(message.type==='transcript')transcript(message);
        else if(message.type==='proposal') {if(!pending)pending=message.proposal;status('Review the proposed answer before confirming.');}
        else if(message.type==='cancelled'&&pending&&message.ids.includes(pending.call_id))pending.cancelled=true;
        else if(message.type==='state')state=message.state;
        else if(message.type==='reconnect_required'){status('Provider requested reconnect. Saved state is retained.');disconnect();}
        else if(message.type==='input_error')status(message.message);
        render();
      } catch(error){status(error.message);disconnect();}
    };
    socket.onclose=()=>{if(current===generation.value){disconnect();status('Voice disconnected. Reconnect explicitly; capture and saved guidance remain available.');}};
    socket.onerror=()=>{if(current===generation.value)status('Voice unavailable. Check that the local server has voice enabled, then reconnect.');};
  }catch(error){status(error.message);disconnect();}
};
$('disconnect').onclick=()=>{disconnect();status('Voice disconnected. Capture has not ended.');};
$('watch-sweep').onchange=()=>{send({type:'watch',enabled:$('watch-sweep').checked});};
$('silence').onclick=()=>{playback?.clear();status('Playback cleared. Speak to interrupt the provider, or disconnect voice.');};
$('mic').onclick=async()=>{
  const epoch=generation.value,request=++micGeneration;micStarting=true;render();let acquired;
  try {
    acquired=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
    if(epoch!==generation.value||!ready||request!==micGeneration){acquired.getTracks().forEach(t=>t.stop());return;}
    await context.audioWorklet.addModule('/assets/pcm-worklet.mjs');
    if(epoch!==generation.value||request!==micGeneration){acquired.getTracks().forEach(t=>t.stop());return;}
    stream=acquired;source=context.createMediaStreamSource(stream);node=new AudioWorkletNode(context,'capture-pcm');
    node.port.onmessage=event=>{if(epoch===generation.value&&stream&&ready){if(!send({type:'audio',data:encode(pcm16(event.data,context.sampleRate))})){void stopMic();status('Microphone stopped because transport fell behind. Reconnect explicitly.');}}};
    source.connect(node);node.connect(context.destination);status('Microphone on. Speak briefly; review proposed answers.');
    stream.getTracks().forEach(t=>t.addEventListener('ended',()=>{void stopMic();status('Microphone ended. Start it again when ready.');},{once:true}));
  }catch(error){acquired?.getTracks().forEach(t=>t.stop());status(`Microphone unavailable: ${error.message}`);}
  finally{if(request===micGeneration)micStarting=false;render();}
};
$('mute').onclick=()=>{void stopMic();status('Microphone off. Voice connection remains open.');};
$('text-form').onsubmit=event=>{event.preventDefault();const text=$('text').value.trim();if(text&&send({type:'text',text})){$('text').value='';transcript({speaker:'claimant',text});}else status('Answer not sent. Connect voice first.');};
$('frame-form').onsubmit=event=>{event.preventDefault();if(!send({type:'frame',frame_ref:$('frame').value.trim()}))status('Preview not sent. Connect voice first.');};
$('confirm').onclick=async()=>{
  const proposal=pending,id=state.id;if(!proposal||proposal.cancelled||proposal.dismissed)return;$('confirm').disabled=true;
  try {const result=await api(`/api/guidance/${id}/turns`,proposal.command);if(state.id!==id)return;state=result;pending=null;$('saved').textContent='Answer saved to guidance. Any book correction remains pending review.';send({type:'refresh'});await nextProposal();}
  catch(error){if(state.id===id){status(error.message);state=await api(`/api/guidance/${id}`);}}
  finally{render();}
};
$('reject').onclick=async()=>{const id=state.id,proposal=pending;if(!proposal)return;try{await api(`/api/guidance/${id}/voice/dismiss`,{call_id:proposal.call_id});if(state.id===id){pending=null;await nextProposal();status('Proposal dismissed. Nothing was saved to guidance.');}}catch(error){status(error.message);}};
$('bind').onclick=async()=>{
  try {state=await api(`/api/guidance/${state.id}/turns`,{command_id:crypto.randomUUID(),session_id:state.id,expected_revision:state.revision,speaker:'agent',payload:{action:'bind_capture'}});send({type:'refresh'});render();}
  catch(error){status(error.message);}
};
window.addEventListener('pagehide',disconnect);
document.addEventListener('visibilitychange',()=>{if(document.hidden){void stopMic();playback?.clear();}});
if(new URL(location.href).searchParams.get('embedded')==='1')$('watch-sweep').checked=true;
render();const id=new URL(location.href).searchParams.get('session');if(id&&/^[a-f0-9]{32}$/.test(id))await open(id).catch(e=>status(e.message));
