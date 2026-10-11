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
  $('pins').textContent=`Inventory revision ${data.inventory_revision} · reference revision ${data.reference_revision} · observations ${data.observations.length ? data.offset+1 : 0}–${data.offset+data.observations.length} of ${data.total_observations}`;
  $('prev').disabled=data.offset===0;$('next').disabled=data.offset+data.limit>=data.total_observations;
  $('dispatch-status').textContent=dispatchSummary(data);
  const link=(label,url)=>{const a=document.createElement('a');a.textContent=label;a.href=url;a.target='_blank';a.rel='noopener';return a;};
  for(const obs of data.observations) {
    const row=document.createElement('p');row.textContent=`Physical track ${obs.track_id} · observation ${obs.id} · shelf ${obs.shelf_id || 'unknown'} `;
    if(obs.track_id===null)row.append(link('Resolve physical observation',`/resolution?session=${encodeURIComponent(data.session_id)}&observation=${encodeURIComponent(obs.id)}`));
    row.append(link('Saved original',`/api/frames/${encodeURIComponent(obs.frame_ref)}`));
    const button=document.createElement('button');button.textContent='Queue reading';button.onclick=()=>enqueue(obs,button);row.append(button);$('observations').append(row);
  }
  for(const job of data.jobs) {
    const row=document.createElement('p');row.textContent=`${job.input.job_id} · ${job.input.kind || 'reading'} · ${job.status} · ${job.result_status || 'no stage result'} · ${job.eligible_for_review ? 'Unverified proposal available for review' : 'Not eligible for current review'} `;
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
