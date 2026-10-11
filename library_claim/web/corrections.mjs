// Reviewed intent -> audited command; no inference or automatic rebase.
export function executionRequest(state,intent,decision,requestId) {
  if(intent.status==='dispatching')return intent.execution_result.request;
  return {request_id:requestId,session_id:state.id,intent_id:intent.intent_id,
    expected_guidance_revision:state.revision,expected_inventory_revision:state.inventory_revision,
    decision,reviewer:'Local browser reviewer',reason:intent.claimant_statement};
}
export function renderCorrections(container,state,onExecute) {
  container.replaceChildren();if(!state?.corrections?.length){container.textContent='No book corrections requested.';return;}
  const targets=new Map((state.correction_targets||[]).map(t=>[t.id,t]));
  for(const intent of state.corrections) {
    const section=document.createElement('section'),heading=document.createElement('h3'),details=document.createElement('p');
    heading.textContent=`${intent.operation} · ${intent.status}`;
    const shelfTarget=intent.target_kind==='shelf'?(state.shelf_correction_targets||[]).find(t=>t.id===intent.track_id):null;
    const target=shelfTarget?{id:`Shelf ${intent.track_id}: ${shelfTarget.track_ids.join(', ')||'physical associations pending'}`,shelf:intent.track_id,position:'all observations and future resolved copies',owned:shelfTarget.owned,frame_ref:shelfTarget.frame_refs[0]}:targets.get(intent.track_id);
    details.textContent=`${intent.claimant_statement} — ${target?`${target.id}; shelf ${target.shelf}; position ${target.position}; currently ${target.owned?'owned':'excluded'}`:'Physical target not selected'}`;
    section.append(heading,details);
    if(target?.frame_ref){const link=document.createElement('a');link.href=`/api/frames/${encodeURIComponent(target.frame_ref)}`;link.textContent='Open original target evidence';section.append(link);}
    if(intent.execution_result){const result=document.createElement('p');const receipt=intent.execution_result;
      result.textContent=receipt.applied?`Applied at inventory revision ${receipt.ledger_event_revision}. Current inventory may include later corrections.`:
        receipt.status==='prepared'?'Execution was prepared; resume the same request to verify its outcome.':`Execution outcome: ${receipt.status}.`;
      section.append(result);}
    if(intent.status==='dispatching'){const resume=document.createElement('button');resume.textContent='Resume prepared execution';resume.onclick=()=>onExecute(intent,'apply',resume);section.append(resume);}
    else if(['pending_review','review_required','awaiting_target'].includes(intent.status)) {
      if(intent.proposed_command){const apply=document.createElement('button');apply.textContent='Apply reviewed correction';
        apply.disabled=intent.proposed_command.expected_revision!==state.inventory_revision||!target;
        apply.onclick=()=>onExecute(intent,'apply',apply);section.append(apply);
        if(apply.disabled){const warning=document.createElement('p');warning.textContent='Inventory changed. Submit a new explicit intent against the current physical target; this proposal will not be rebased.';section.append(warning);}
      }else{const warning=document.createElement('p');warning.textContent=intent.track_id?'This assertion needs separate identity/appraisal review.':'Choose the physical target before applying.';section.append(warning);}
      const dismiss=document.createElement('button');dismiss.textContent='Dismiss book correction';dismiss.onclick=()=>onExecute(intent,'dismiss',dismiss);section.append(dismiss);
    }
    container.append(section);
  }
}
