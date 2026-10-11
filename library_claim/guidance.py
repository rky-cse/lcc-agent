"""M06a: durable guided setup, evidence requests and correction proposals.

Typed turns only: no speech recognition, model inference or inventory mutation.
"""
import argparse
import json
import re
from contextlib import closing
from datetime import datetime,timezone
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Annotated,Literal

from pydantic import Field,model_validator

from .capture_store import FrameStore
from .capture_session import CaptureSessions
from .identity import IdentityCommand
from .models import Contract,Sweep,StageResult
from .packet import json_text
from .tracking import TrackStore,TrackingCommand,digest

Text=Annotated[str,Field(min_length=1,max_length=2000)]
Token=Annotated[str,Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')]
Positive=Annotated[Decimal,Field(gt=0,le=1000000,allow_inf_nan=False)]
Uncertainty=Annotated[Decimal,Field(ge=0,le=1000000,allow_inf_nan=False)]


class LocaleAnswer(Contract):
    action: Literal['locale']
    country: str
    currency: str
    claimant_statement: Text


class ReferenceAnswer(Contract):
    action: Literal['reference']
    description: Text
    width_cm: Positive | None
    height_cm: Positive | None
    width_uncertainty_cm: Uncertainty | None
    height_uncertainty_cm: Uncertainty | None
    dimensions_verified: bool
    dimension_provenance: Text
    claimant_statement: Text

    @model_validator(mode='after')
    def dimensions(self):
        values=[self.width_cm,self.height_cm,self.width_uncertainty_cm,self.height_uncertainty_cm]
        if any(v is None for v in values) and any(v is not None for v in values): raise ValueError('supply all reference dimensions/uncertainties or leave all unknown')
        if self.dimensions_verified and self.width_cm is None: raise ValueError('verified dimensions require actual values')
        if self.width_cm is not None and (self.width_uncertainty_cm>=self.width_cm or self.height_uncertainty_cm>=self.height_cm):
            raise ValueError('uncertainty must be smaller than the dimension')
        return self


class SkipReference(Contract):
    action: Literal['skip_reference']
    claimant_statement: Text


class ArtAnswer(Contract):
    action: Literal['art']
    frame_ref: str=Field(min_length=1,max_length=128)
    description: Text
    classification: Literal['print','original','unknown']
    claimant_statement: Text


class BindCapture(Contract):
    action: Literal['bind_capture']


class RecaptureRequest(Contract):
    action: Literal['request_evidence']
    request_id: Token
    reason_code: Literal['unreadable_spine','isbn_not_visible','binding_unknown','glare','reference_not_visible']
    track_id: str | None = Field(max_length=128)
    shelf_id: str | None = Field(max_length=128)
    expected_inventory_revision: int = Field(ge=0)


class BindingAnswer(Contract):
    action: Literal['binding']
    request_id: Token
    physical_format: Literal['hardcover','paperback','other_print','unknown']
    claimant_statement: Text


class EvidenceAnswer(Contract):
    action: Literal['evidence_received']
    request_id: Token
    frame_ref: str = Field(min_length=1,max_length=128)


class DeclineEvidence(Contract):
    action: Literal['decline_evidence']
    request_id: Token
    claimant_statement: Text


class CorrectionIntent(Contract):
    action: Literal['correction']
    intent_id: Token
    operation: Literal['exclude','include','clear_identity','signed','first_edition']
    track_id: str | None = Field(max_length=128)
    expected_inventory_revision: int = Field(ge=0)
    claimant_statement: Text


class ShelfCorrectionIntent(Contract):
    action: Literal['shelf_correction']
    intent_id: Token
    operation: Literal['exclude_shelf','include_shelf']
    shelf_id: str=Field(min_length=1,max_length=128)
    expected_inventory_revision: int=Field(ge=0)
    claimant_statement: Text


class ChooseTarget(Contract):
    action: Literal['choose_target']
    intent_id: Token
    track_id: str = Field(min_length=1,max_length=128)
    expected_inventory_revision: int = Field(ge=0)
    claimant_statement: Text


Payload=Annotated[LocaleAnswer|ReferenceAnswer|SkipReference|ArtAnswer|BindCapture|RecaptureRequest|BindingAnswer|EvidenceAnswer|DeclineEvidence|CorrectionIntent|ShelfCorrectionIntent|ChooseTarget,Field(discriminator='action')]


class GuidanceCommand(Contract):
    command_id: Token
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_revision: int = Field(ge=0)
    speaker: Literal['claimant','agent']
    payload: Payload

    @model_validator(mode='after')
    def speaker_and_text(self):
        agent_actions={'request_evidence','evidence_received','bind_capture'}
        if (self.payload.action in agent_actions)!=(self.speaker=='agent'): raise ValueError('turn speaker does not match action')
        for name in ['claimant_statement','description','dimension_provenance']:
            value=getattr(self.payload,name,None)
            if value is not None and not value.strip(): raise ValueError('nonblank declaration/provenance required')
        return self


PROMPTS=dict(unreadable_spine='Slow down on this shelf and show the spines clearly with overlap, without moving books. Unreadable titles will stay unknown.',
    isbn_not_visible='If an ISBN is visible in the shelf view without moving a book, hold that view steady. Otherwise say it is not visible; the edition will stay unknown.',
    binding_unknown='What binding does this physical copy have: hardcover, paperback, another print binding, or unknown?',
    glare='Tilt the camera slightly to reduce glare and pause on this shelf, keeping the books in place.',
    reference_not_visible='Show the reference beside the spines on the same plane. Its dimensions do not calibrate another plane or the whole room.')


class GuidanceStore:
    def __init__(self,frames):
        self.frames=frames;self.capture=CaptureSessions(frames);self.ledger=TrackStore(frames)
        with closing(frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS guidance_sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)');db.commit()

    @staticmethod
    def read(db,session_id):
        row=db.execute('SELECT state FROM guidance_sessions WHERE id=?',(session_id,)).fetchone()
        if row is None: raise KeyError('unknown guidance session')
        return json.loads(row[0])

    def start(self,session_id):
        if not re.fullmatch(r'[a-f0-9]{32}',session_id): raise ValueError('invalid session ID')
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM guidance_sessions WHERE id=?',(session_id,)).fetchone()
            if row: state=json.loads(row[0])
            else:
                # A fresh conversation must ask its locale, not infer it from
                # an existing capture under the same identifier.
                if db.execute('SELECT 1 FROM capture_sweeps WHERE id=?',(session_id,)).fetchone(): raise ValueError('use a new guidance ID before capture')
                state=dict(schema_version='1.0',id=session_id,revision=0,phase='awaiting_locale',locale=None,reference=None,
                    reference_revision=0,reference_skipped=False,requests=[],corrections=[],events=[])
                db.execute('INSERT INTO guidance_sessions VALUES (?,?)',(session_id,json_text(state)))
            db.commit()
        return self.project(state)

    def inventory(self,session_id,revision,target=None):
        snapshot=self.ledger.snapshot(session_id)
        if snapshot['revision']!=revision: raise ValueError('stale inventory revision; reload targets')
        if target is not None and target not in {t['id'] for t in snapshot['tracks']}: raise ValueError('unknown physical correction/evidence target')
        return snapshot

    @staticmethod
    def proposal(session_id,intent):
        tid=intent['track_id']
        if tid is None: return None
        command_id='guidance-'+digest((session_id+'\0'+intent['intent_id']).encode())[:24]
        common=dict(command_id=command_id,sweep_id=session_id,expected_revision=intent['inventory_revision'],track_id=tid)
        if intent['operation'] in ['exclude','include']:
            return TrackingCommand(**common,operation='ownership',owned=intent['operation']=='include',detection_result_sha256=None,
                decisions=[],provenance=intent['claimant_statement']).model_dump(mode='json')
        if intent['operation'] in ['exclude_shelf','include_shelf','signed','first_edition']:
            return TrackingCommand(**common,operation='shelf_ownership' if intent.get('target_kind')=='shelf' else 'appraisal',
                owned=intent['operation']=='include_shelf' if intent.get('target_kind')=='shelf' else None,
                detection_result_sha256=None,decisions=[],provenance=intent['claimant_statement']).model_dump(mode='json')
        if intent['operation']=='clear_identity':
            return IdentityCommand(**common,action='clear_identity',catalogue_result_sha256=None,work_id=None,confirmed_span_ids=[],
                metadata=[],needs_appraisal=False,reviewer='Claimant via guided session',reason=intent['claimant_statement']).model_dump(mode='json')
        return None # signed/first-edition claims require an explicit identity/appraisal review

    def apply(self,command):
        command=GuidanceCommand.model_validate(command.model_dump());fingerprint=digest(json_text(command.model_dump()).encode())
        payload=command.payload;started=datetime.now(timezone.utc)
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE');state=self.read(db,command.session_id)
            for event in state['events']:
                if event['command']['command_id']==command.command_id:
                    if event['command_sha256']!=fingerprint: raise ValueError('command ID reused with different payload')
                    return self.project(state)
            if state['revision']!=command.expected_revision: raise ValueError('stale guidance revision')
            if len(state['events'])>=1000: raise ValueError('guided turn limit exceeded')
            action=payload.action;invalidated=[]
            if action=='locale':
                if state['phase'] not in ['awaiting_locale','awaiting_reference','ready_to_capture']: raise ValueError('captured locale cannot be relabeled; start a new session')
                if db.execute('SELECT 1 FROM capture_sweeps WHERE id=?',(state['id'],)).fetchone(): raise ValueError('capture already fixes country/currency')
                checked=Sweep(id=state['id'],captured_at=started,country=payload.country,currency=payload.currency)
                state['locale']=dict(country=checked.country,currency=checked.currency,claimant_statement=payload.claimant_statement)
                state['phase']='ready_to_capture' if state['reference_skipped'] or (state['reference'] and state['reference']['dimensions_verified']) else 'awaiting_reference'
                invalidated=['locale_dependent_jobs']
            elif action in ['reference','skip_reference']:
                if state['locale'] is None: raise ValueError('answer country/currency first')
                state['reference_revision']+=1;invalidated=['metric_jobs','scale_dependent_results']
                if action=='reference':
                    state['reference']=payload.model_dump(mode='json');state['reference_skipped']=False
                    if state['phase']!='capture_bound': state['phase']='ready_to_capture' if payload.dimensions_verified else 'awaiting_reference'
                else:
                    state['reference']=None;state['reference_skipped']=True;state['reference_skip_statement']=payload.claimant_statement
                    if state['phase']!='capture_bound': state['phase']='ready_to_capture'
            elif action=='bind_capture':
                if state['phase']!='ready_to_capture': raise ValueError('complete or explicitly skip reference intake before capture')
                capture=self.capture.snapshot(state['id'])
                if capture['status']!='capturing' or any(capture[k]!=state['locale'][k] for k in ['country','currency']): raise ValueError('capture locale/status differs from guidance')
                state['phase']='capture_bound'
            else:
                if state['phase']!='capture_bound': raise ValueError('bind the configured capture before evidence/corrections')
                capture=self.capture.snapshot(state['id'])
                if action=='art':
                    frame=self.frames.get(payload.frame_ref)
                    if frame.sweep_id!=state['id']:raise ValueError('cross-sweep art declaration')
                    if len(state.get('art_declarations',[]))>=100:raise ValueError('art declaration limit exceeded')
                    state.setdefault('art_declarations',[]).append(dict(**payload.model_dump(mode='json'),needs_appraisal=payload.classification!='print'))
                elif action=='request_evidence':
                    if capture['status']!='capturing': raise ValueError('recapture cannot be requested after capture ends')
                    self.inventory(state['id'],payload.expected_inventory_revision,payload.track_id)
                    if len(state['requests'])>=100: raise ValueError('evidence request limit exceeded')
                    if any(r['request_id']==payload.request_id for r in state['requests']): raise ValueError('request ID already used')
                    state['requests'].append(dict(**payload.model_dump(mode='json'),status='awaiting_answer' if payload.reason_code=='binding_unknown' else 'awaiting_evidence',
                        prompt=PROMPTS[payload.reason_code],frame_ref=None,answer=None))
                elif action in ['binding','evidence_received','decline_evidence']:
                    matches=[r for r in state['requests'] if r['request_id']==payload.request_id]
                    if len(matches)!=1 or matches[0]['status'] not in ['awaiting_answer','awaiting_evidence']: raise ValueError('request is missing or already answered')
                    request=matches[0]
                    if action=='binding':
                        if request['reason_code']!='binding_unknown': raise ValueError('binding answer needs a binding request')
                        request['answer']=payload.model_dump(mode='json');request['status']='answered'
                    elif action=='evidence_received':
                        if request['reason_code']=='binding_unknown': raise ValueError('binding declaration still required')
                        frame=self.frames.get(payload.frame_ref)
                        if frame.sweep_id!=state['id']: raise ValueError('cross-sweep evidence')
                        request['frame_ref']=frame.id;request['status']='received_analysis_pending'
                    else: request['status']='declined_unknown';request['answer']=payload.model_dump(mode='json')
                elif action in ('correction','shelf_correction'):
                    target=payload.shelf_id if action=='shelf_correction' else payload.track_id
                    inventory=self.inventory(state['id'],payload.expected_inventory_revision,None if action=='shelf_correction' else target)
                    if action=='shelf_correction' and not any(o['shelf_id']==target for o in inventory['observations']):raise ValueError('unknown physical shelf; show its saved detections first')
                    if len(state['corrections'])>=100: raise ValueError('correction limit exceeded')
                    if any(c['intent_id']==payload.intent_id for c in state['corrections']): raise ValueError('intent ID already used')
                    intent=dict(**payload.model_dump(mode='json'),inventory_revision=payload.expected_inventory_revision,
                        status='awaiting_target' if target is None else 'pending_review',applied=False)
                    intent['track_id']=target
                    if action=='shelf_correction':intent['target_kind']='shelf'
                    intent['proposed_command']=self.proposal(state['id'],intent);state['corrections'].append(intent)
                elif action=='choose_target':
                    self.inventory(state['id'],payload.expected_inventory_revision,payload.track_id)
                    matches=[c for c in state['corrections'] if c['intent_id']==payload.intent_id]
                    if len(matches)!=1 or matches[0]['status']!='awaiting_target': raise ValueError('intent is not awaiting a target')
                    intent=matches[0];intent.update(track_id=payload.track_id,inventory_revision=payload.expected_inventory_revision,
                        target_statement=payload.claimant_statement,status='pending_review')
                    intent['proposed_command']=self.proposal(state['id'],intent)
            state['revision']+=1
            stage=StageResult(sweep_id=state['id'],job_id=fingerprint,input_revision=command.expected_revision,stage='guided_session_turn',status='partial',
                started_at=started,finished_at=datetime.now(timezone.utc),evidence_refs=[payload.frame_ref] if action=='evidence_received' else [],
                warnings=['Structured guidance only; metric calibration, evidence analysis and correction execution remain separate.'],errors=[])
            state['events'].append(dict(revision=state['revision'],command=command.model_dump(mode='json'),command_sha256=fingerprint,
                stage_result=stage.model_dump(mode='json'),invalidated_dependencies=invalidated))
            db.execute('UPDATE guidance_sessions SET state=? WHERE id=?',(json_text(state),state['id']));db.commit()
        return self.project(state)

    def snapshot(self,session_id):
        with closing(self.frames._connect()) as db: state=self.read(db,session_id)
        return self.project(state)

    def project(self,state):
        state=json.loads(json_text(state));capture=None
        if state['phase']=='capture_bound': capture=self.capture.snapshot(state['id'])
        if capture and any(capture[k]!=state['locale'][k] for k in ['country','currency']): raise ValueError('bound capture locale differs from guidance')
        for request in state['requests']:
            if request['frame_ref']:
                frame=self.frames.get(request['frame_ref'])
                if frame.sweep_id!=state['id']: raise ValueError('guidance evidence integrity mismatch')
        if state['phase']=='awaiting_locale': prompt='Which country should this claim use, and in which currency?'
        elif state['phase']=='awaiting_reference': prompt='Which reference object can you use? Give its independently measured width and height in centimetres, measurement tolerances and how you measured them. Do not assume a standard object size.'
        elif state['phase']=='ready_to_capture': prompt='Setup declarations are saved. Start the shelf capture when ready. Keep books in place; show the reference beside the spines on the same plane if available. Metric calibration is still pending.'
        else:
            ambiguous=next((c for c in state['corrections'] if c['status']=='awaiting_target'),None)
            pending=next((r for r in state['requests'] if r['status'] in ['awaiting_answer','awaiting_evidence']),None)
            prompt=('Which physical book do you mean? Select its track ID using the shelf position and saved original; I will not choose by title.' if ambiguous else
                pending['prompt'] if pending and capture['status']=='capturing' else
                'Capture has ended. Evidence analysis and correction reviews may still be pending.' if capture['status']=='closed' else
                'Move slowly across each shelf with overlap, keeping the books in place. Unknown titles, editions and measurements will remain visible.')
        inventory=self.ledger.snapshot(state['id']);candidates=[]
        from .sweep_progress import recognition_progress
        progress=recognition_progress(self.frames,state['id'],inventory['revision'],state['reference_revision'])
        quality={};latest=None
        if capture and capture['frames']:
            latest=max(capture['frames'],key=lambda f:f['media_sequence'])
            quality=capture.get('quality',{}).get(latest['id'],{})
        if capture and capture['status']=='capturing' and not pending and not ambiguous:
            if quality.get('possible_blur'):prompt='The latest saved view may be blurred. Slow down and hold this shelf steady, keeping books in place.'
            elif quality.get('possible_glare'):prompt='The latest saved view may have glare. Tilt the camera slightly and pause on this shelf.'
            elif progress['capture_hints']:prompt=progress['capture_hints'][0]
        executing=any(c['status']=='dispatching' for c in state['corrections'])
        if executing:prompt='A book correction has an unfinished execution acknowledgment. Review or resume its saved request before treating its outcome as confirmed.'
        if any(c['status']=='awaiting_target' for c in state['corrections']):
            candidates=[{k:b[k] for k in ['id','shelf','position','title','frame_ref']} for b in inventory['books'][:20]]
        targets={c['track_id'] for c in state['corrections'] if c['track_id']}
        target_shelves={c['track_id'] for c in state['corrections'] if c.get('target_kind')=='shelf'}
        shelf_targets=[dict(id=shelf,shelf=shelf,frame_refs=sorted({o['frame_ref'] for o in inventory['observations'] if o['shelf_id']==shelf}),
            track_ids=[t['id'] for t in inventory['tracks'] if t['shelf_id']==shelf],owned=inventory['shelf_ownership'].get(shelf,True)) for shelf in sorted(target_shelves)]
        state.update(next_prompt=prompt,capture_status=capture['status'] if capture else None,metric_ready=False,
            shelf_correction_targets=shelf_targets,
            recognition_progress=progress,latest_frame_ref=latest['id'] if latest else None,latest_quality=quality,
            calibration_status='not_geometrically_verified',inventory_mutated=True if any(c.get('applied',False) for c in state['corrections']) else None if executing else False,
            correction_execution_pending=executing,inventory_revision=inventory['revision'],
            correction_targets=[{k:b[k] for k in ['id','shelf','position','owned','title','frame_ref']} for b in inventory['books'] if b['id'] in targets or b['shelf'] in target_shelves],
            target_choices=candidates,target_choice_total=inventory['assigned_track_count'],target_choices_complete=len(candidates)==inventory['assigned_track_count'] if candidates else False,
            capture_start_proposal=dict(start_id=state['id'],country=state['locale']['country'],currency=state['locale']['currency']) if state['phase']=='ready_to_capture' else None)
        return state

    def export(self,session_id,directory):
        root=Path(directory)
        if root.exists(): raise FileExistsError('choose a fresh guidance export directory')
        state=self.snapshot(session_id);root.mkdir(parents=True);(root/'guidance.json').write_text(json_text(state)+'\n',encoding='utf-8')
        html='<!doctype html><meta charset="utf-8"><title>Guided session review</title><h1>Guided session review</h1>'
        html+=f'<p>Revision {state["revision"]}; phase {state["phase"]}. Voice transport is separate. Calibration is unverified. Corrections require explicit execution review; see their recorded outcomes.</p><h2>Next agent prompt</h2><p>{escape(state["next_prompt"])}</p><h2>Structured turns</h2>'
        for event in state['events']: html+=f'<pre>{escape(json.dumps(event["command"],ensure_ascii=False,indent=2))}</pre>'
        html+='<h2>Corrections and execution outcomes</h2><pre>'+escape(json.dumps(state['corrections'],ensure_ascii=False,indent=2))+'</pre>'
        html+='<p><a href="guidance.json">Full state, questions and audit evidence</a></p>'
        (root/'report.html').write_text(html,encoding='utf-8');return state


def main():
    parser=argparse.ArgumentParser(description='M06a durable typed guidance');parser.add_argument('--store',type=Path,required=True)
    parser.add_argument('--session-id',required=True);parser.add_argument('--command',type=Path);parser.add_argument('--start',action='store_true');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.start and args.command: parser.error('start or command, not both')
    if args.output.exists(): raise FileExistsError('choose a fresh output')
    guide=GuidanceStore(FrameStore(args.store))
    if args.start: guide.start(args.session_id)
    elif args.command:
        command=GuidanceCommand.model_validate_json(args.command.read_bytes())
        if command.session_id!=args.session_id: parser.error('command session differs')
        guide.apply(command)
    state=guide.export(args.session_id,args.output);print(f'Guidance revision {state["revision"]}: {state["next_prompt"]}')


if __name__=='__main__': main()
