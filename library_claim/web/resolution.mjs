import {registrationRequest} from './registration.mjs';

// Reuse the explicit physical-decision renderer without tying resolution to a stale queue job.
export function resolutionView(result) {
  const obs=result.observation,candidate={...obs,observation_id:obs.id,status:'candidate'};
  return {...result,can_register:result.can_resolve,shelf_id:obs.shelf_id,frame_ref:obs.frame_ref,
    candidates:[candidate],proposals:[candidate],review_queue:[],unresolved_regions:[],
    registration_events:result.resolution_events,
    job:{input:{expected_inventory_revision:result.inventory_revision,expected_reference_revision:result.reference_revision}}};
}

export function resolutionRequest(data,decisions,reviewer,reason,reviewId) {
  if(decisions.length!==1||!['new','same'].includes(decisions[0].action))throw new Error('Choose new or same; leave without applying if still ambiguous');
  const request=registrationRequest(data,decisions,reviewer,reason,reviewId);
  delete request.job_id;
  return request;
}
