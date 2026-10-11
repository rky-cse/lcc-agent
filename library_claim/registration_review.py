"""Explicit queued-detection registration through the existing atomic tracking ledger."""
from contextlib import closing
from typing import Annotated
from pydantic import Field,model_validator
from .guidance import Token
from .models import Contract
from .packet import json_text
from .recognition_jobs import DetectionJob,parse_job
from .tracking import TrackStore,TrackingCommand,Decision,digest,load_bundle

class RegistrationReview(Contract):
    review_id: Token
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    job_id: Token
    expected_inventory_revision: int = Field(ge=0)
    expected_reference_revision: int = Field(ge=0)
    reviewer: str = Field(min_length=1,max_length=200)
    reason: str = Field(min_length=1,max_length=1000)
    decisions: Annotated[list[Decision],Field(max_length=256)]

    @model_validator(mode='after')
    def literal_review(self):
        if not self.reviewer.strip() or not self.reason.strip() or any(not d.provenance.strip() for d in self.decisions):
            raise ValueError('Explicit nonblank review provenance required')
        return self

class RegistrationReviewer:
    def __init__(self,queue):
        self.queue=queue;self.ledger=TrackStore(queue.store)

    def _job(self,session_id,job_id):
        job=self.queue.get(job_id)
        if job['input']['session_id']!=session_id:raise KeyError('unknown job in this session')
        if not isinstance(parse_job(job['input']),DetectionJob):raise ValueError('registration requires a detection job')
        return job

    def snapshot(self,session_id,job_id):
        job=self._job(session_id,job_id)
        if 'detection_result.json' not in job['artifacts']:raise ValueError('no published detection evidence')
        bundle=load_bundle(self.queue.store,self.queue._directory(job_id),job['artifacts']['detection_result.json'])
        inventory=self.ledger.snapshot(session_id)
        targets=[dict(id=t['id'],shelf_id=t['shelf_id'],owned=t['owned'],observations=[o for o in inventory['observations'] if o['track_id']==t['id']]) for t in inventory['tracks'] if t['shelf_id']==bundle['request']['shelf_id']]
        with closing(self.queue.store._connect()) as db:
            state=self.ledger._read(db,session_id)
        events=[e for e in state['events'] if e['command']['operation']=='import' and e['command']['detection_result_sha256']==job['artifacts']['detection_result.json']]
        if any(e['command_sha256']!=digest(json_text(e['command']).encode()) for e in events):raise ValueError('registration event integrity failure')
        return dict(session_id=session_id,job_id=job_id,job=job,inventory_revision=inventory['revision'],
            candidates=[p for p in bundle['result']['proposals'] if p['status']=='candidate'],
            proposals=bundle['result']['proposals'],unresolved_regions=bundle['result']['unresolved_regions'],review_queue=bundle['result']['review_queue'],
            frame_ref=bundle['request']['frame_ref'],frame=self.queue.store.get(bundle['request']['frame_ref']).model_dump(mode='json',include={'id','sha256','width','height','exif_orientation','synthetic'}),shelf_id=bundle['request']['shelf_id'],targets=targets,
            registration_events=events,can_register=job['eligible_for_review'] and job['result_status'] in ('success','partial') and not events)

    def apply(self,review):
        review=RegistrationReview.model_validate(review.model_dump())
        job=self._job(review.session_id,review.job_id)
        sha=job['artifacts'].get('detection_result.json')
        if not sha:raise ValueError('no published detection evidence')
        provenance=json_text(review.model_dump(exclude={'decisions'}))
        command=TrackingCommand(command_id='registration-'+digest((review.session_id+'\0'+review.review_id).encode())[:24],
            sweep_id=review.session_id,expected_revision=review.expected_inventory_revision,operation='import',
            detection_result_sha256=sha,decisions=review.decisions,track_id=None,owned=None,provenance=provenance)
        def guard(db,state):
            current=self._job(review.session_id,review.job_id)
            inputs=current['input']
            if not current['eligible_for_review'] or current['result_status'] not in ('success','partial'):
                raise ValueError('detection is stale or unavailable; no registration applied')
            if inputs['expected_inventory_revision']!=review.expected_inventory_revision or inputs['expected_reference_revision']!=review.expected_reference_revision:
                raise ValueError('review pins differ from detection inputs')
        self.ledger.apply(command,self.queue._directory(review.job_id),guard=guard)
        with closing(self.queue.store._connect()) as db:
            state=self.ledger._read(db,review.session_id)
        self.ledger._verify(state)
        event=next(e for e in state['events'] if e['command']['command_id']==command.command_id)
        if event['command_sha256']!=digest(json_text(command.model_dump()).encode()):raise ValueError('registration ledger proof differs')
        return dict(applied=True,review=review.model_dump(mode='json'),ledger_event_revision=event['revision'],
            command_sha256=event['command_sha256'],inventory=self.ledger._snapshot(state),job=self.queue.get(review.job_id),
            warning='Receipt is historical; current inventory may include later reviewed changes.')
