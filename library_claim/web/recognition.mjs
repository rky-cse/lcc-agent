export function enrollment(data, observation, jobId) {
  if(!data.observations.some(o=>o.id===observation.id)) throw new Error('Observation is not in the displayed page');
  return {job_id:jobId,session_id:data.session_id,expected_reference_revision:data.reference_revision,
    request:{sweep_id:data.session_id,expected_revision:data.inventory_revision,observation_id:observation.id,frame_sha256:observation.frame_sha256}};
}

export function dispatchable(data,job) {
  const worker=data.dispatcher;
  return Boolean(worker?.enabled&&worker.session_id===data.session_id&&!worker.closing&&!worker.active&&!worker.worker_busy
    &&['gemini','replay'].includes(worker.mode)&&job.input.session_id===data.session_id
    &&worker.supported_kinds?.includes(job.input.kind||'reading')&&job.status==='queued'
    &&!data.jobs.some(j=>j.status==='running'||j.worker_active));
}

export function dispatchRequest(data,job) {
  const saved=data.jobs.find(j=>j.input.job_id===job.input.job_id);
  if(!saved||saved.input.session_id!==data.session_id||!dispatchable(data,saved))throw new Error('Refresh status; this saved job cannot be dispatched now');
  return {job_id:saved.input.job_id};
}

export function dispatchSummary(data) {
  const worker=data.dispatcher;
  if(!worker||worker.session_id!==data.session_id)return 'Dispatch status unavailable. Refresh status before running a job.';
  if(!worker.enabled)return 'Server dispatch disabled. An operator must enable recognition on the server; queued jobs can still use the CLI worker.';
  if(worker.closing)return 'Server is shutting down. Dispatch is unavailable.';
  const mode=worker.mode==='replay'?'Synthetic replay':`Gemini recognition (${worker.model})`;
  if(worker.active)return `${mode}: server worker active${worker.job_id?` for ${worker.job_id}`:''}. Refresh status to see its result. Cancellation revokes publication; it cannot undo a provider request.`;
  if(worker.worker_busy||data.jobs.some(j=>j.status==='running'||j.worker_active))return `${mode}: active or uncertain worker holds the slot. Refresh status; after an abrupt stop, an operator must stop the old worker before CLI interruption recovery.`;
  return `${mode}: available for one explicitly selected queued job. Supported kinds: ${worker.supported_kinds.join(', ')}. Refresh status after running; acceptance does not mean completion.${worker.last_outcome?` Last server outcome: ${worker.last_outcome}.`:''}`;
}

export function renderReadings(document,data,{enqueue,cancel,dispatch}) {
  const $=id=>document.getElementById(id);
  $('observations').replaceChildren();$('jobs').replaceChildren();
  const link=(label,url)=>{const a=document.createElement('a');a.textContent=label;a.href=url;a.target='_blank';a.rel='noopener';return a;};
  const line=(parent,text)=>{const p=document.createElement('p');p.textContent=text;parent.append(p);return p;};
  const workflow=data.workflow;
  if($('workflow-status'))$('workflow-status').textContent=workflow?`Saved images: ${workflow.saved_frame_count} → provisional observations: ${workflow.provisional_observation_count} → readable spines: ${workflow.readable_spine_count}; partial/unreadable: ${workflow.partial_or_unreadable_spine_count}; physical decisions still needed: ${workflow.unresolved_physical_count}. Next: ${workflow.next_action}`:'Workflow summary unavailable for this saved session.';
  function renderInventoryProjection(){
    const projection=data.inventory_projection,host=$('inventory-evidence'),summary=$('inventory-projection'),download=$('inventory-json');if(!host||!summary||!download)return;
    host.replaceChildren();download.hidden=true;if(!projection){summary.textContent='Inventory projection unavailable for this saved session.';return;}
    summary.textContent=`Inventory revision ${projection.revision}: ${projection.observation_count} provisional detected spine regions from ${projection.detection_import_count} detection result(s); ${projection.assigned_track_count} physically accepted tracks; ${projection.unresolved_physical_count} physical decisions and ${projection.review_count} review entries pending. Final book count is unknown; coverage verified: ${projection.coverage_verified?'yes':'no'}.`;
    download.href=`/api/sweeps/${encodeURIComponent(data.session_id)}/inventory/export`;download.hidden=false;
    const readings=new Map(data.jobs.filter(job=>job.result_summary?.kind==='reading').map(job=>[job.result_summary.observation_id,{summary:job.result_summary,job}]));
    const byFrame=new Map();for(const observation of data.observations){const rows=byFrame.get(observation.frame_ref)||[];rows.push(observation);byFrame.set(observation.frame_ref,rows);}
    for(const [frameRef,observations] of byFrame){
      const card=document.createElement('article');card.className='inventory-evidence-card';const title=document.createElement('h3');title.textContent=`Saved original with ${observations.length} detected spine region${observations.length===1?'':'s'}`;card.append(title);
      const frame=data.frames?.find(value=>value.id===frameRef);const holder=document.createElement('div');holder.className='inventory-evidence-image';
      const image=document.createElement('img');image.src=`/api/frames/${encodeURIComponent(frameRef)}`;image.alt='Original capture with detected book-spine regions';holder.append(image);
      if(frame&&document.createElementNS){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${frame.width} ${frame.height}`);for(const [index,observation] of observations.entries()){const polygon=document.createElementNS(svg.namespaceURI,'polygon');polygon.setAttribute('points',observation.polygon_px.map(point=>point.join(',')).join(' '));polygon.setAttribute('class','inventory-polygon');svg.append(polygon);const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',observation.polygon_px[0][0]);label.setAttribute('y',Math.max(24,observation.polygon_px[0][1]-8));label.setAttribute('class','inventory-polygon-label');label.textContent=String(index+1);svg.append(label);}holder.append(svg);}
      card.append(holder);const list=document.createElement('ol');for(const [index,observation] of observations.entries()){const item=document.createElement('li'),reading=readings.get(observation.id);let text=`#${index+1} · ${observation.orientation} · ${observation.track_id ? `physical track ${observation.track_id}`:'physical identity unresolved'}`;if(reading?.summary.text?.length)text+=` · visible text: ${reading.summary.text.map(span=>`${span.role} — ${span.text}`).join('; ')}`;else if(reading?.summary)text+=` · text legibility: ${reading.summary.legibility||'not reported'}`;item.textContent=text;if(reading?.summary.crop_available){const base=`/api/guidance/${encodeURIComponent(data.session_id)}/recognition/${encodeURIComponent(reading.job.input.job_id)}`;item.append(document.createTextNode(' · '),link('Open reading crop',`${base}/crop.png`));}list.append(item);}card.append(list);host.append(card);
    }
  }
  renderInventoryProjection();
  function actionLink(label,url){const a=link(label,url);a.className='action-button';return a;}
  function renderNextActions(){
    const host=$('next-actions');if(!host)return;host.replaceChildren();const readingByObservation=new Map(data.jobs.filter(job=>(job.input.kind||'reading')==='reading'&&job.input.request?.observation_id).map(job=>[job.input.request.observation_id,job]));
    for(const [index,observation] of data.observations.entries()){
      const card=document.createElement('section');card.className='recognition-action-card';const reading=readingByObservation.get(observation.id);
      if(observation.track_id===null){line(card,`Spine #${index+1}: physical copy unresolved. Check the saved crop and original, then decide whether it is a new physical book, the same book as an existing track, or should remain unresolved.`);card.append(actionLink(`Resolve spine #${index+1}`,`/resolution?session=${encodeURIComponent(data.session_id)}&observation=${encodeURIComponent(observation.id)}`));}
      else {line(card,`Spine #${index+1}: physical copy ${observation.track_id} is accepted. Next, review its literal title/author evidence and catalogue match before requesting a price.`);card.append(actionLink(`Open book identification`, `/?session=${encodeURIComponent(data.session_id)}`));}
      if(reading?.result_summary?.crop_available){const base=`/api/guidance/${encodeURIComponent(data.session_id)}/recognition/${encodeURIComponent(reading.input.job_id)}`;card.append(actionLink('View reading crop',`${base}/crop.png`));}
      card.append(actionLink('View original image',`/api/frames/${encodeURIComponent(observation.frame_ref)}`));host.append(card);
    }
  }
  renderNextActions();
  $('pins').textContent=`Inventory revision ${data.inventory_revision} · reference revision ${data.reference_revision} · observations ${data.observations.length ? data.offset+1 : 0}–${data.offset+data.observations.length} of ${data.total_observations}`;
  $('prev').disabled=data.offset===0;$('next').disabled=data.offset+data.limit>=data.total_observations;
  $('dispatch-status').textContent=dispatchSummary(data);
  function resultCard(job,base){
    const summary=job.result_summary;if(!summary)return null;
    const card=document.createElement('article');card.className='recognition-result-card';
    const heading=document.createElement('h3');heading.textContent=summary.kind==='detection'?'Detection result':'Spine reading result';card.append(heading);
    if(summary.kind==='detection'){
      line(card,`Shelf ${summary.shelf_id||'unknown'} · coverage: ${summary.coverage||'not reported'} · ${summary.book_spine_candidates||0} provisional book-spine candidates · ${summary.non_book_proposals||0} non-book proposals · ${summary.ambiguous_or_review||0} ambiguous/review proposals · ${summary.unresolved_regions||0} unresolved regions.`);
      if(summary.review_findings)line(card,`${summary.review_findings} detector findings require review.`);
      if(summary.frame_ref)card.append(link('Open original image',`/api/frames/${encodeURIComponent(summary.frame_ref)}`));
    }else{
      line(card,`Observation ${summary.observation_id||'unknown'} · text legibility: ${summary.legibility||'not reported'}.`);
      if(summary.text?.length)line(card,`Extracted visible text: ${summary.text.map(span=>`${span.role||'text'} — ${span.text||'empty'}`).join(' · ')}`);
      else line(card,'No readable text was extracted from this spine crop.');
      if(summary.crop_available){const image=document.createElement('img');image.className='recognition-crop';image.alt='Saved crop used for this spine reading';image.src=`${base}/crop.png`;card.append(image);}
      if(summary.frame_ref){card.append(link('Open original image',`/api/frames/${encodeURIComponent(summary.frame_ref)}`));}
    }
    return card;
  }
  for(const obs of data.observations) {
    const row=document.createElement('p');row.textContent=`Physical track ${obs.track_id} · observation ${obs.id} · shelf ${obs.shelf_id || 'unknown'} `;
    if(obs.track_id===null)row.append(link('Resolve physical observation',`/resolution?session=${encodeURIComponent(data.session_id)}&observation=${encodeURIComponent(obs.id)}`));
    row.append(link('Saved original',`/api/frames/${encodeURIComponent(obs.frame_ref)}`));
    const previous=data.jobs.find(job=>(job.input.kind||'reading')==='reading'&&job.input.request?.observation_id===obs.id);const button=document.createElement('button');
    if(previous){button.textContent=previous.status==='completed'?'Reading complete':previous.status==='queued'?'Reading queued':'Reading in progress';button.disabled=true;}else{button.textContent='Queue reading';button.onclick=()=>enqueue(obs,button);}row.append(button);$('observations').append(row);
  }
  for(const job of data.jobs) {
    const row=document.createElement('p');const review=job.review_state==='already_imported_as_provisional_observations'?'Already imported as provisional observations; continue with physical review':job.review_state==='stale_inputs_or_inventory_changed'?'Outdated after inventory/reference changed; evidence remains visible but cannot be applied':job.eligible_for_review?'Unverified proposal available for review':'Not eligible for current review';row.textContent=`${job.input.job_id} · ${job.input.kind || 'reading'} · ${job.status} · ${job.result_status || 'no stage result'} · ${review} `;
    if(job.status==='queued'||job.status==='running') {
      const button=document.createElement('button');button.textContent=job.input.kind==='detection'?'Cancel detection':'Cancel reading';button.onclick=()=>cancel(job,button);row.append(button);
    }
    if(job.status==='queued'&&dispatch) {
      const button=document.createElement('button');button.textContent=`Run selected ${job.input.kind||'reading'}`;
      button.disabled=!dispatchable(data,job);button.dataset.jobId=job.input.job_id;
      button.onclick=()=>dispatch(job,button);row.append(button);
    }
    if(job.status==='running'||job.worker_active) row.append(document.createTextNode('Worker slot retained until execution exits. After an abrupt stop, stop the old worker before explicit CLI interruption recovery. '));
    if(job.artifacts['reading_result.json']) {
      const base=`/api/guidance/${encodeURIComponent(data.session_id)}/recognition/${encodeURIComponent(job.input.job_id)}`;
      row.append(link('Reading evidence JSON',`${base}/reading_result.json`));row.append(document.createTextNode(' · '));row.append(link('Saved crop',`${base}/crop.png`));
    }
    if(job.artifacts['detection_result.json']) {
      const base=`/api/guidance/${encodeURIComponent(data.session_id)}/recognition/${encodeURIComponent(job.input.job_id)}`;
      row.append(link('Detection proposal JSON',`${base}/detection_result.json`));row.append(document.createTextNode(' · '));row.append(link('Pinned queue stage',`${base}/queue_stage.json`));
      row.append(document.createTextNode(' · '));row.append(link('Review physical registration',`/registration?session=${encodeURIComponent(data.session_id)}&job=${encodeURIComponent(job.input.job_id)}`));
    }
    $('jobs').append(row);
    const base=`/api/guidance/${encodeURIComponent(data.session_id)}/recognition/${encodeURIComponent(job.input.job_id)}`;
    const card=resultCard(job,base);if(card)$('jobs').append(card);
  }
}

// Switching session/page revokes every late response and aborts outstanding requests.
export class ReadingView {
  constructor({load,changed,failed}) {Object.assign(this,{load,changed,failed});this.epoch=0;}
  async open(session,offset=0,frameOffset=0) {
    this.controller?.abort();const epoch=++this.epoch;this.session=session;this.offset=offset;this.frameOffset=frameOffset;
    const controller=new AbortController();this.controller=controller;
    const timer=setTimeout(()=>controller.abort(),10000);
    try {const data=await this.load(session,offset,controller.signal,frameOffset);if(epoch!==this.epoch)return;
      if(data.session_id!==session||data.offset!==offset||(data.frame_offset!==undefined&&data.frame_offset!==frameOffset))throw new Error('Reading response target differs');
      this.changed(data);
    } catch(error) {if(epoch===this.epoch)this.failed(error);}finally{clearTimeout(timer);}
  }
  stop(){++this.epoch;this.controller?.abort();}
}
