import {registrationRequest,renderRegistration} from './registration.mjs';
export async function mount(document=globalThis.document, environment={}) {
const window=environment.window||globalThis.window, location=environment.location||globalThis.location, history=environment.history||globalThis.history;
const $=id=>document.getElementById(id),params=new URL(location.href).searchParams,session=params.get('session'),job=params.get('job');
let data=null,epoch=0,pending=null;const controllers=new Set();
const url=`/api/guidance/${encodeURIComponent(session)}/registration/${encodeURIComponent(job)}`;
async function api(body){const controller=new AbortController();controllers.add(controller);const timer=setTimeout(()=>controller.abort(),10000);
 try {const response=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal:controller.signal});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Registration request failed');return result;}
 finally{clearTimeout(timer);controllers.delete(controller);}}
async function load(){const generation=++epoch;data=null;pending=null;$('registration-apply').disabled=true;
 try {const result=await api();if(generation!==epoch)return;data=result;renderRegistration(document,data);$('registration-status').textContent=data.can_register?'Review each candidate before applying.':'Registration unavailable for new decisions; inspect evidence and historical receipts.';}
 catch(error){if(generation===epoch)$('registration-status').textContent=error.message;}}
$('registration-refresh').onclick=()=>void load();
$('registration-form').onsubmit=async event=>{event.preventDefault();if(!data)return;const generation=epoch;
 try {const decisions=data.candidates.map(c=>({observation_id:c.observation_id,action:document.querySelector(`[data-observation="${c.observation_id}"]`).value,track_id:document.querySelector(`[data-target="${c.observation_id}"]`).value||null,provenance:document.querySelector(`[data-reason="${c.observation_id}"]`).value}));
   const proposed=registrationRequest(data,decisions,$('registration-reviewer').value,$('registration-reason').value,'placeholder');
   if(pending&&JSON.stringify({...pending,review_id:'placeholder'})!==JSON.stringify(proposed))throw new Error('Unconfirmed request has changed; refresh and inspect inventory before making new decisions');
   pending ||= {...proposed,review_id:crypto.randomUUID()};$('registration-apply').disabled=true;const result=await api(pending);
   if(generation!==epoch)return;$('registration-status').textContent=`Verified registration at inventory revision ${result.ledger_event_revision}.`;await load();
 }catch(error){if(generation===epoch){$('registration-status').textContent=`Request not confirmed: ${error.message}. Retry unchanged inputs or refresh to inspect the saved ledger.`;$('registration-apply').disabled=false;}}};
window.addEventListener('pagehide',()=>{++epoch;data=null;for(const c of controllers)c.abort();});
if(/^[a-f0-9]{32}$/.test(session||'')&&/^[A-Za-z0-9_-]{1,128}$/.test(job||''))void load();else $('registration-status').textContent='Open a detection review from the recognition queue.';


}
if(globalThis.document?.querySelector('script[src="/assets/registration_page.mjs"]')) await mount();
