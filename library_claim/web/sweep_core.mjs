export function planRequest(guide,values,planId){
  if(guide?.phase!=='capture_bound'||guide.capture_status!=='capturing')throw new Error('Bind an active capture before starting recognition');
  const number=id=>{if(String(values[id]??'').trim()==='')throw new Error(`${id} is required`);const value=Number(values[id]);if(!Number.isFinite(value))throw new Error(`${id} must be finite`);return value;};
  const region=['x0','y0','x1','y1'].map(number),[x0,y0,x1,y1]=region;
  if(!(0<=x0&&x0<x1&&x1<=1&&0<=y0&&y0<y1&&y1<=1))throw new Error('Select a valid shelf region');
  if(!String(values.shelf||'').trim()||values.consent!==true)throw new Error('Explicit shelf and enrollment consent required');
  const budget=number('budget'),interval=number('interval'),expected=number('expected-shelves'),minimum=number('min-area'),overlap=number('max-overlap');
  if(!Number.isInteger(budget)||budget<1||budget>20||!Number.isInteger(interval)||interval<5||interval>60||!Number.isInteger(expected)||expected<1||expected>100||minimum<=0||overlap<=0||overlap>=1)throw new Error('Review budget, expected shelves and detection limits');
  return {plan_id:planId,shelf_id:values.shelf,region,policy:{min_polygon_area_px2:minimum,max_pair_overlap_fraction:overlap},max_attempts:budget,interval_seconds:interval,expected_shelves:expected,reference_revision:guide.reference_revision,allow_unresolved_import:true};
}
export function progressSummary(state){
  return `${state.status} · ${state.attempts} attempts prepared · ${state.remaining_attempts} remaining · ${state.pending_job_count} saved pending jobs · ${state.coverage_missing_shelves} expected shelves not observed · ${state.unread_observation_count??'unknown'} observations without a current reading · ${state.unresolved_physical_count??'unknown'} physical associations unresolved. ${state.capture_closed?'Capture ended. ':''}${state.recognition_drained?'Recognition queue drained; identity, measurement, pricing and packet stages still need completion.':'Recognition or review work remains.'}${state.last_error?` Review required: ${state.last_error}.`:''}`;
}
