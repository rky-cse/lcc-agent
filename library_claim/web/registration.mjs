export function registrationRequest(data,decisions,reviewer,reason,reviewId) {
  if(!data.can_register)throw new Error('Detection is stale, unavailable or already registered');
  if(!reviewer.trim()||!reason.trim())throw new Error('Enter reviewer and review reason');
  if(decisions.length!==data.candidates.length||new Set(decisions.map(d=>d.observation_id)).size!==decisions.length)throw new Error('Decide every candidate exactly once');
  for(const candidate of data.candidates) {
    const d=decisions.find(d=>d.observation_id===candidate.observation_id);
    if(!d||!['new','same','unresolved'].includes(d.action)||!d.provenance.trim())throw new Error('Every candidate needs a decision and reason');
    if(d.action==='same'&&!data.targets.some(t=>t.id===d.track_id&&t.shelf_id===data.shelf_id))throw new Error('Choose a physical track on this shelf');
    if(d.action!=='same'&&d.track_id!==null)throw new Error('Only same-copy decisions have a target');
  }
  return {review_id:reviewId,session_id:data.session_id,job_id:data.job_id,expected_inventory_revision:data.job.input.expected_inventory_revision,
    expected_reference_revision:data.job.input.expected_reference_revision,reviewer,reason,decisions:structuredClone(decisions)};
}

export function receiptText(event) {
  return `${event.command.operation==='resolve'?'Resolution':'Registration'} applied at inventory revision ${event.revision}. This is historical; current inventory may include later changes. Recorded decisions: `+event.command.decisions.map(d=>`${d.observation_id}: ${d.action}${d.track_id ? ` → ${d.track_id}` : ''}; reason: ${d.provenance}`).join(' | ');
}

export function renderRegistration(document,data,{resolution=false}={}) {
  const $=id=>document.getElementById(id);$('registration-decisions').replaceChildren();$('registration-original').replaceChildren();$('registration-warnings').replaceChildren();$('registration-receipts').replaceChildren();
  $('registration-pins').textContent=`Shelf ${data.shelf_id} · current inventory ${data.inventory_revision} · ${resolution?'review':'detection'} inventory ${data.job.input.expected_inventory_revision} · reference ${data.job.input.expected_reference_revision} · ${data.candidates.length} candidates`;
  const holder=document.createElement('div');holder.className='registration-image';
  const image=document.createElement('img');image.alt='Unchanged original with numbered candidate polygons';image.src=`/api/frames/${encodeURIComponent(data.frame_ref)}`;holder.append(image);
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${data.frame.width} ${data.frame.height}`);
  data.proposals.forEach((p,index)=>{const polygon=document.createElementNS(svg.namespaceURI,'polygon');polygon.setAttribute('points',p.polygon_px.map(point=>point.join(',')).join(' '));polygon.setAttribute('fill','none');polygon.setAttribute('stroke',p.status==='candidate'?'#079542':'#c56d00');polygon.setAttribute('stroke-width','4');svg.append(polygon);
    const text=document.createElementNS(svg.namespaceURI,'text');text.setAttribute('x',p.polygon_px[0][0]);text.setAttribute('y',Math.max(24,p.polygon_px[0][1]-8));text.setAttribute('font-size','24');text.setAttribute('fill','#074d31');text.textContent=String(index+1);svg.append(text);});holder.append(svg);$('registration-original').append(holder);
  for(const warning of [...data.review_queue,...data.unresolved_regions]){const p=document.createElement('p');p.textContent=`Unresolved detector evidence: ${warning.reason}`;$('registration-warnings').append(p);}
  for(const c of data.candidates) {
    const field=document.createElement('fieldset');const legend=document.createElement('legend');legend.textContent=`Candidate ${data.proposals.findIndex(p=>p.observation_id===c.observation_id)+1} · ${c.observation_id}`;field.append(legend);
    const action=document.createElement('select');action.required=true;action.dataset.observation=c.observation_id;action.setAttribute('aria-label',`Decision for ${c.observation_id}`);
    for(const [value,label] of [['','Choose a decision'],['new','New physical copy'],['same','Previously registered physical copy'],...(!resolution?[['unresolved','Keep unresolved']]:[])]){const option=document.createElement('option');option.value=value;option.textContent=label;action.append(option);}field.append(action);
    const target=document.createElement('select');target.dataset.target=c.observation_id;target.setAttribute('aria-label',`Existing physical track for ${c.observation_id}`);
    const blank=document.createElement('option');blank.value='';blank.textContent='Choose physical track if same copy';target.append(blank);
    for(const t of data.targets){const option=document.createElement('option');option.value=t.id;option.textContent=`${t.id} · ${t.owned?'included':'excluded'} · ${t.observations.length} observations`;target.append(option);}target.disabled=true;field.append(target);
    action.onchange=()=>{target.disabled=action.value!=='same';target.required=action.value==='same';if(target.disabled)target.value='';};
    const reason=document.createElement('input');reason.required=true;reason.maxLength=2000;reason.dataset.reason=c.observation_id;reason.setAttribute('aria-label',`Decision reason for ${c.observation_id}`);reason.placeholder='Physical evidence for this decision';field.append(reason);
    $('registration-decisions').append(field);
  }
  for(const t of data.targets) {const p=document.createElement('p');p.textContent=`Existing track ${t.id} · shelf ${t.shelf_id} `;for(const obs of t.observations){const link=document.createElement('a');link.href=`/api/frames/${encodeURIComponent(obs.frame_ref)}`;link.target='_blank';link.rel='noopener';link.textContent=`Original ${obs.id} · polygon ${JSON.stringify(obs.polygon_px)} `;p.append(link);}$('registration-decisions').append(p);}
  $('registration-apply').disabled=!data.can_register;
  for(const event of data.registration_events){const p=document.createElement('p');p.textContent=receiptText(event);$('registration-receipts').append(p);}
}
