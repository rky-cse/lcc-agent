import {ReadingView,enrollment,renderReadings,dispatchRequest} from './recognition.mjs';
import {ShelfSelector} from './shelf_selector.mjs';
export async function mount(document=globalThis.document, environment={}) {
const window=environment.window||globalThis.window, location=environment.location||globalThis.location, history=environment.history||globalThis.history;
const $=id=>document.getElementById(id);let current=null;const attempts=new Map();
const selector=new ShelfSelector(document,enqueueDetection);
const mutations=new Set();
async function api(url,body,signal) {
  const response=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'Request failed');return data;
}
const view=new ReadingView({load:async(session,offset,signal,frameOffset)=>{
    const base=`/api/guidance/${encodeURIComponent(session)}/recognition`;
    const [evidence,worker]=await Promise.allSettled([api(`${base}?offset=${offset}&frame_offset=${frameOffset}`,null,signal),api(`${base}/dispatch`,null,signal)]);
    if(evidence.status==='rejected')throw evidence.reason;
    const data=evidence.value;data.dispatcher=worker.status==='fulfilled'&&worker.value.session_id===session?worker.value:null;return data;
  },
  changed:data=>{current=data;renderReadings(document,data,{enqueue,cancel,dispatch});selector.render(data);$('refresh').disabled=false;$('status').textContent='Saved evidence and job status loaded. Review physical evidence before queuing or running.';},
  failed:error=>{$('status').textContent=`Evidence unavailable: ${error.message}. Refresh before enrolling.`;$('dispatch-status').textContent='Dispatch status unavailable.';current=null;selector.clear();$('observations').replaceChildren();$('jobs').replaceChildren();}});
async function mutate(body,path,button) {
  const session=current.session_id,epoch=view.epoch;button.disabled=true;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);mutations.add(controller);
  try {const result=await api(`/api/guidance/${encodeURIComponent(session)}/recognition${path}`,body,controller.signal);
    if(epoch===view.epoch){const refreshedEpoch=epoch+1;await open(session,view.offset,view.frameOffset);
      if(path==='/dispatch'&&view.epoch===refreshedEpoch&&current?.session_id===session)$('status').textContent=result.accepted?`Dispatch accepted for ${body.job_id}; completion is not confirmed. Refresh evidence and job status to inspect its result.`:`Saved status returned for ${body.job_id}; no new attempt was started.`;}
  }catch(error){if(epoch===view.epoch){$('status').textContent=`Request not confirmed: ${error.message}. Retry uses the same job ID; refresh to inspect saved state.`;button.disabled=false;}}
  finally{clearTimeout(timer);mutations.delete(controller);}
}
function enqueue(obs,button) {
  if(!current)return;
  const proposed=enrollment(current,obs,'placeholder');const key=JSON.stringify(proposed);
  if(!attempts.has(key))attempts.set(key,enrollment(current,obs,crypto.randomUUID()));
  void mutate(attempts.get(key),'',button);
}
function cancel(job,button){if(current)void mutate({job_id:job.input.job_id},'/cancel',button);}
function dispatch(job,button){
  if(!current)return;
  try {const body=dispatchRequest(current,job);for(const b of document.querySelectorAll('[data-job-id]'))b.disabled=true;void mutate(body,'/dispatch',button);}
  catch(error){$('status').textContent=error.message;}
}
function enqueueDetection(body,button){if(!current)return;const key=JSON.stringify(body);if(!attempts.has(key))attempts.set(key,{...body,job_id:crypto.randomUUID()});void mutate(attempts.get(key),'/detection',button);}
function open(session,offset=0,frameOffset=0){current=null;for(const c of mutations)c.abort();selector.clear();$('observations').replaceChildren();$('jobs').replaceChildren();$('dispatch-status').textContent='Loading dispatch status…';$('prev').disabled=true;$('next').disabled=true;return view.open(session,offset,frameOffset);}
$('session-form').onsubmit=event=>{event.preventDefault();open($('session-id').value);};
$('refresh').onclick=()=>open(view.session,view.offset,view.frameOffset);
$('prev').onclick=()=>open(view.session,Math.max(0,view.offset-50),view.frameOffset);
$('next').onclick=()=>open(view.session,view.offset+50,view.frameOffset);
$('frame-prev').onclick=()=>open(view.session,view.offset,Math.max(0,view.frameOffset-50));
$('frame-next').onclick=()=>open(view.session,view.offset,view.frameOffset+50);
window.addEventListener('pagehide',()=>{view.stop();for(const c of mutations)c.abort();selector.clear();current=null;});
const session=new URL(location.href).searchParams.get('session');if(session&&/^[a-f0-9]{32}$/.test(session)){$('session-id').value=session;open(session);}

return {refresh:()=>open(view.session,view.offset,view.frameOffset)};
}
if(globalThis.document?.querySelector('script[src="/assets/recognition_page.mjs"]')) await mount();
