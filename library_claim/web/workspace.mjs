import {componentEnvironment,workflowPath} from './workspace_core.mjs';
const $=id=>document.getElementById(id), components=new Map();
let selected=null,voice=null,camera=null,plan=null,cameraSession=null,loadingCamera=false,reviewVersion=0,activePanel=null;
const controllers={voice:'voice',capture:'app',sweep:'sweep',recognition:'recognition_page',identity:'identity',geometry:'geometry',registration:'registration_page',resolution:'resolution_page',valuation:'valuation',contents:'contents',areas:'areas',packet:'packet'};
const message=text=>{$('workspace-status').textContent=text;};
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000)});const value=await r.json();if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:`Request failed (${r.status})`);return value;}
function simplify(root,name){
  root.querySelector('h1')?.remove();
  for(const a of root.querySelectorAll('a'))if(['/','/voice','/sweep'].includes(new URL(a.href,location.href).pathname))a.hidden=true;
  if(name==='voice'){
    root.getElementById('watch-sweep').checked=true;root.getElementById('bind').hidden=true;root.getElementById('frame-form').hidden=true;
    for(const id of ['limits','recognition-progress'])root.getElementById(id).hidden=true;
    const log=document.createElement('details'),title=document.createElement('summary');title.textContent='Conversation history';log.append(title,root.getElementById('transcript'));root.querySelector('main').append(log);
  }
  if(name==='capture'){
    root.getElementById('saved-sweep-form').hidden=true;
    for(const id of ['country','currency'])root.getElementById(id).closest('label').hidden=true;
    const evidence=document.createElement('details'),title=document.createElement('summary');title.textContent='Saved camera evidence';evidence.append(title,root.getElementById('frames'));root.querySelector('main').append(evidence);
    for(const p of root.querySelectorAll('p'))if(p.textContent.includes('not connected to this capture page yet'))p.remove();
  }
  if(name==='sweep'){
    root.getElementById('open-form').hidden=true;root.querySelector('.sweep-panels').remove();
    for(const p of root.querySelectorAll('main > p'))if(p.querySelector('a')||p.textContent.includes('Both panels remain'))p.hidden=true;
    root.getElementById('min-area').value='100';root.getElementById('max-overlap').value='0.2';
    const advanced=document.createElement('details'),title=document.createElement('summary');title.textContent='Recognition settings';advanced.append(title);
    for(const id of ['x0','y0','x1','y1','min-area','max-overlap','budget','interval'])advanced.append(root.getElementById(id).closest('label'));
    root.getElementById('plan-form').prepend(advanced);
  }
  for(const id of ['sweep-id','session-id']){const input=root.getElementById(id);if(input&&selected){input.value=selected;input.readOnly=true;input.closest('label')?.setAttribute('hidden','');}}
}
async function mount(host,name,url,callbacks={}){
  const response=await fetch(`/api/ui/${name}`,{signal:AbortSignal.timeout(10000)});if(!response.ok)throw new Error('Workspace controls unavailable');
  const parsed=new DOMParser().parseFromString(await response.text(),'text/html'),root=host.shadowRoot||host.attachShadow({mode:'open'});
  root.replaceChildren();const link=document.createElement('link');link.rel='stylesheet';link.href='/assets/style.css';
  const wrapper=document.createElement('div');wrapper.className=parsed.body.className;wrapper.append(document.importNode(parsed.querySelector('main'),true));root.append(link,wrapper);simplify(root,name);
  const scoped=componentEnvironment(root,document,window,url,callbacks),module=await import(`/assets/${controllers[name]}.mjs`);
  const control=await module.mount(scoped.document,scoped.environment);
  const result={root,control,dispose:()=>{scoped.dispose();host.remove();}};components.set(host,result);return result;
}
async function captureReady(state){
  if(loadingCamera||cameraSession===state.id)return;loadingCamera=true;
  try{
    if(camera?.control.getState().active)throw new Error('Finish the current camera sweep before switching sessions.');
    cameraSession=state.id;camera=await mount($('camera-host'),'capture',`/capture?guidance=${state.id}`);
  }catch(error){cameraSession=null;message(error.message);}finally{loadingCamera=false;}
}
function onState(state){
  if(!state)return;
  if(selected!==state.id){selected=state.id;history.replaceState(null,'',`/?session=${selected}`);try{localStorage.setItem('library-workspace-session',selected);}catch{}plan?.control.open(selected);++reviewVersion;for(const host of [...$('review-host').children]){components.get(host)?.dispose();}activePanel=null;}
  if(['ready_to_capture','capture_bound'].includes(state.phase))void captureReady(state);
}
async function review(name,url){
  if(!selected){$('review-status').textContent='Create or open a conversation session first.';return;}
  const version=++reviewVersion;activePanel=name;$('review-status').textContent='Loading review controls…';
  for(const host of $('review-host').children)host.hidden=true;
  const key=`${name}:${url?.search||''}`,existing=[...$('review-host').children].find(h=>h.dataset.key===key);
  try{
    let result;if(existing){existing.hidden=false;result=components.get(existing);}else{
      const host=document.createElement('section');host.dataset.key=key;host.hidden=true;$('review-host').append(host);
      const target=url||new URL(`/${name}?session=${selected}&sweep_id=${selected}`,location.href);target.searchParams.set('session',selected);target.searchParams.set('sweep_id',selected);
      result=await mount(host,name,target.href);if(version!==reviewVersion)return;host.hidden=false;
    }
    if(version!==reviewVersion)return;
    const load=result.root.getElementById('load');if(load)load.click();else result.control?.refresh?.();
    $('review-status').textContent='Changes are saved to this sweep. Voice and camera remain available above.';
    for(const button of $('workspace-nav').querySelectorAll('button'))button.setAttribute('aria-current',String(button.dataset.panel===name));
  }catch(error){if(version===reviewVersion)$('review-status').textContent=error.message;}
}
$('workspace-nav').onclick=e=>{if(e.target.dataset.panel)void review(e.target.dataset.panel);};
document.addEventListener('click',event=>{
  const anchor=event.composedPath().find(node=>node instanceof HTMLAnchorElement);if(!anchor||anchor.hasAttribute('download'))return;
  const url=new URL(anchor.href,location.href);if(url.origin!==location.origin)return;const name=workflowPath(url);
  if(name){event.preventDefault();void review(name,url);return;}
  if(url.pathname.startsWith('/api/')&&!url.pathname.endsWith('/archive')){
    event.preventDefault();void evidence(url);
  }
});
async function evidence(url){
  const dialog=$('evidence-dialog'),body=$('evidence-content');body.textContent='Loading saved evidence…';if(!dialog.open)dialog.showModal();
  try{const r=await fetch(url,{signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error('Evidence unavailable');body.replaceChildren();
    if(r.headers.get('content-type')?.startsWith('image/')){const img=document.createElement('img');img.src=url.href;img.alt='Saved original evidence';body.append(img);}
    else {const pre=document.createElement('pre');pre.textContent=await r.text();body.append(pre);}
  }catch(error){body.textContent=error.message;}
}
$('close-evidence').onclick=()=>$('evidence-dialog').close();
let binding=false;
const timer=setInterval(async()=>{
  const state=voice?.control.getState();if(!state||binding||state.phase!=='ready_to_capture'||camera?.control.getState().sweep?.id!==state.id)return;
  binding=true;try{await api(`/api/guidance/${state.id}/turns`,{command_id:crypto.randomUUID(),session_id:state.id,expected_revision:state.revision,speaker:'agent',payload:{action:'bind_capture'}});await voice.control.refresh();message('Camera and voice are linked. Start recognition for the shelf in view.');}catch(error){message(error.message);}finally{binding=false;}
},2000);
window.addEventListener('pagehide',()=>clearInterval(timer));
try{
  voice=await mount($('voice-host'),'voice','/voice?embedded=1',{onState,canSwitch:id=>!selected||selected===id||!camera?.control.getState().active&&voice?.control.getState()?.capture_status!=='capturing'});
  plan=await mount($('plan-host'),'sweep','/sweep',{onCaptureReady:captureReady});
  let session=new URL(location.href).searchParams.get('session');try{session ||=localStorage.getItem('library-workspace-session');}catch{}
  if(session&&/^[a-f0-9]{32}$/.test(session))await voice.control.open(session);else await voice.control.open(crypto.randomUUID().replaceAll('-',''),true);
  plan.control.open(selected);message('Session ready. Connect voice and start microphone; confirm the agent’s proposed answers below.');
}catch(error){message(`Workspace could not load: ${error.message}. Refresh to retry.`);}
