export async function mount(document=globalThis.document,environment={}){
const location=environment.location||globalThis.location,$=id=>document.getElementById(id),session=new URL(location.href).searchParams.get('session');let inventory=null,busy=false,version=0;
const id=()=>crypto.randomUUID().replaceAll('-',''),message=text=>{$('status').textContent=text;};
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(60000)}),value=await r.json();if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:'Identification request failed');return value;}
function text(parent,value){const p=document.createElement('p');p.textContent=value;parent.append(p);return p;}
function button(parent,label,work){const b=document.createElement('button');b.textContent=label;b.onclick=()=>action(work);parent.append(b);return b;}
function review(){const reviewer=$('reviewer').value.trim(),reason=$('reason').value.trim();if(!reviewer||!reason)throw new Error('Enter your reviewer name and reason before saving a decision.');return {reviewer,reason};}
async function action(work){if(busy)return;busy=true;try{await work();}catch(e){message(e.message);}finally{busy=false;}}
async function refresh(){const current=++version;const [data,ledger]=await Promise.all([api(`/api/guidance/${session}/recognition`),api(`/api/sweeps/${session}/inventory/export`)]);if(current!==version)return;inventory=ledger;$('readings').replaceChildren();
 for(const job of data.jobs.filter(j=>j.artifacts['reading_result.json'])){
  const base=`/api/guidance/${session}/recognition/${job.input.job_id}`,reading=await api(base+'/reading_result.json');if(current!==version)return;
  const observation=inventory.observations.find(o=>o.id===reading.request.observation_id),row=document.createElement('section');$('readings').append(row);
  text(row,`Observation ${reading.request.observation_id}; ${observation?.track_id||'physical copy unresolved'}; ${reading.response?.legibility||'unavailable'}`);
  const img=document.createElement('img');img.src=base+'/crop.png';img.alt='Saved spine crop for literal text review';img.className='spine-crop';row.append(img);
  const checks=[];for(const span of reading.text_evidence){const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';label.append(check,document.createTextNode(`${span.tentative_role}: ${span.text}`));row.append(label);checks.push({span,check});}
  const lookup=button(row,'Find catalogue work',async()=>{if(!observation?.track_id)throw new Error('Resolve the physical observation in Books and review first.');
    const chosen=checks.filter(x=>x.check.checked).map(x=>x.span);if(!chosen.some(s=>s.tentative_role==='title'))throw new Error('Confirm the visible title text before searching.');
    const result=await api(`/api/sweeps/${session}/stages/catalogue`,{run_id:id(),job_id:job.input.job_id,request:{reading_result_sha256:job.artifacts['reading_result.json'],title_span_ids:chosen.filter(s=>s.tentative_role==='title').map(s=>s.id),author_span_ids:chosen.filter(s=>s.tentative_role==='author').map(s=>s.id),limit:10}});
    showCandidates(result,reading,observation,chosen);message('Catalogue search saved. Review matches before accepting.');});lookup.disabled=!job.eligible_for_review||!observation?.track_id;
 }
 message('Readings loaded. Unreadable or unresolved books remain in the review queue.');
}
function showCandidates(bundle,reading,observation,spans){const panel=$('candidates');panel.replaceChildren();text(panel,`${bundle.result.outcome}: ${bundle.result.selected_title} / ${bundle.result.selected_author}`);
 for(const candidate of bundle.result.candidates){text(panel,`${candidate.title}; ${candidate.authors.join(', ')}; ${candidate.disposition}; ${candidate.reasons.join('; ')}`);
  const appraisal=document.createElement('input');appraisal.type='checkbox';const label=document.createElement('label');label.append(appraisal,document.createTextNode('Signed, rare, first edition or otherwise needs appraisal'));panel.append(label);
  const accept=button(panel,'Accept evidenced work',async()=>{
    const metadata=spans.filter(s=>['publisher','edition','isbn'].includes(s.tentative_role)).map(s=>({field:s.tentative_role,value:s.text,source:'visible_text',span_id:s.id,claimant_statement:null}));
    const confirmed=[...bundle.result.request.title_span_ids,...bundle.result.request.author_span_ids,...metadata.map(m=>m.span_id)];
    const command={command_id:id(),sweep_id:session,expected_revision:reading.request.expected_revision,track_id:observation.track_id,action:'accept_work',catalogue_result_sha256:bundle.result_sha256,work_id:candidate.work_id,confirmed_span_ids:confirmed,metadata,needs_appraisal:appraisal.checked,...review()};
    inventory=await api(`/api/sweeps/${session}/identity`,{bundle_id:bundle.run_id,command});panel.replaceChildren();showEdition(observation.track_id);message('Work saved. Prices and edition remain separate evidence checks. Refresh after further inventory changes.');
  });accept.disabled=candidate.disposition!=='supported_candidate';
 }
}
function showEdition(track){const panel=$('editions');panel.replaceChildren();const format=document.createElement('select');for(const value of ['unknown','hardcover','paperback','other_print']){const o=document.createElement('option');o.value=value;o.textContent=value;format.append(o);}const statement=document.createElement('input');statement.placeholder='Literal claimant statement about physical format';panel.append(format,statement);
 button(panel,'Look up evidenced edition',async()=>{const request={sweep_id:session,expected_revision:inventory.revision,track_id:track,edition_id:null,limit:10,owned_physical_format:format.value,format_statement:statement.value};const result=await api(`/api/sweeps/${session}/stages/edition`,{run_id:id(),request});text(panel,result.result.outcome);
   for(const c of result.result.candidates){text(panel,`${c.edition_id}: ${c.disposition}; ${c.reasons.join('; ')}`);const b=button(panel,'Accept evidenced edition',async()=>{inventory=await api(`/api/sweeps/${session}/edition`,{bundle_id:result.run_id,command:{command_id:id(),sweep_id:session,expected_revision:request.expected_revision,track_id:track,action:'accept_edition',edition_result_sha256:result.result_sha256,edition_id:c.edition_id,...review()}});message('Edition saved from reviewed evidence.');});b.disabled=c.disposition!=='supported_candidate';}
 });
}
$('refresh').onclick=()=>action(refresh);await action(refresh);return {refresh:()=>action(refresh)};
}
