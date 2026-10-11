export function scope(value) {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(value)) throw new Error('Enter a valid sweep or run ID');
  return value;
}
export function reviewRequest(text, sweep, revision) {
  const request=JSON.parse(text);
  if(request.sweep_id!==scope(sweep)) throw new Error('Request belongs to another sweep');
  if(request.expected_contents_revision!==revision) throw new Error('Reload the current contents revision');
  if(!request.interpretation?.wall_area_basis || !request.interpretation?.dimensions || !request.interpretation?.height) throw new Error('Review all area interpretation choices');
  scope(request.run_id);
  return request;
}
export function summary(result) {
  const lines=[`Run ${result.run_id}: ${result.status}${result.stale?' — stale contents revision':''}`];
  for(const name of ['floor_area_m2','wall_area_m2','shelved_wall_area_m2']) {
    const units=result.geometry?.area_units?.[name];
    lines.push(`${name}: ${units?.m2??'unknown'} m²; ${units?.ft2??'unknown'} ft²`);
  }
  if(result.reason)lines.push(result.reason);
  lines.push('Physical coverage and accuracy are unverified. Final packet integration is pending.');
  return lines;
}
