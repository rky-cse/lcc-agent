"""Explicitly activated, budgeted same-pass recognition coordinator."""
import asyncio
import json
import math
import uuid
from contextlib import closing
from typing import Literal
from pydantic import Field,model_validator
from starlette.concurrency import run_in_threadpool
from .models import Contract
from .guidance import Token
from .packet import json_text
from .recognition_jobs import DetectionJob,ReadingJob
from .spine_detection import DetectionRequest,DetectionPolicy
from .spine_reading import ReadingRequest
from .registration_review import RegistrationReviewer,RegistrationReview
from .tracking import TrackStore,Decision,digest
from .automatic_registration import acquire_links


class SweepPlan(Contract):
    plan_id: Token
    shelf_id: str=Field(min_length=1,max_length=128)
    region: tuple[float,float,float,float]
    policy: DetectionPolicy
    max_attempts: int=Field(ge=1,le=20)
    interval_seconds: int=Field(ge=5,le=60)
    expected_shelves: int=Field(ge=1,le=100)
    reference_revision: int=Field(ge=0)
    allow_unresolved_import: Literal[True]

    @model_validator(mode='after')
    def bounds(self):
        x0,y0,x1,y1=self.region
        if not self.shelf_id.strip() or not all(math.isfinite(v) for v in self.region) or not 0<=x0<x1<=1 or not 0<=y0<y1<=1:
            raise ValueError('explicit shelf and normalized region required')
        return self


class SweepRuntime:
    def __init__(self,queue,dispatcher):
        self.queue=queue;self.dispatcher=dispatcher;self.frames=queue.store
        self.registration=RegistrationReviewer(queue);self.ledger=TrackStore(self.frames)
        self.lock=asyncio.Lock();self.task=None;self.session=None;self.closing=False;self.wake=asyncio.Event()
        with closing(self.frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS sweep_runtime (id TEXT PRIMARY KEY,state TEXT NOT NULL)');db.commit()

    def read(self,session):
        self.queue.guidance.snapshot(session)
        with closing(self.frames._connect()) as db:row=db.execute('SELECT state FROM sweep_runtime WHERE id=?',(session,)).fetchone()
        return json.loads(row[0]) if row else dict(session_id=session,status='idle',plan=None,jobs=[],pending=[],last_frame=None,
            imported=[],association_proposals=[],attempts=0,last_error=None)

    def save(self,state):
        with closing(self.frames._connect()) as db:
            db.execute('INSERT OR REPLACE INTO sweep_runtime VALUES (?,?)',(state['session_id'],json_text(state)));db.commit()

    def snapshot(self,session):
        state=self.read(session);jobs=self.queue.list(session)
        active=self.session==session and self.task is not None and not self.task.done() and state['status']=='running'
        if state['status']=='running' and not active:state['status']='restart_requires_explicit_resume'
        guide=self.queue.guidance.snapshot(session);capture=self.queue.guidance.capture.snapshot(session) if guide['phase']=='capture_bound' else None
        inventory=self.ledger.snapshot(session)
        read_ids={j['input']['request']['observation_id'] for j in jobs if j['input'].get('kind','reading')=='reading' and j['status']=='completed'}
        state.update(active=active,dispatcher=self.dispatcher.snapshot(session),
            capture_closed=bool(capture and capture['status']=='closed'),
            remaining_attempts=max(0,(state['plan'] or {}).get('max_attempts',0)-state['attempts']),
            pending_job_count=sum(j['status'] in ('queued','running') or j.get('worker_active',False) for j in jobs),
            recognition_drained=not any(j['status'] in ('queued','running') or j.get('worker_active',False) for j in jobs),
            packet_ready=False,coverage_verified=False,
            unread_observation_count=sum(o['id'] not in read_ids for o in inventory['observations']),
            unresolved_physical_count=sum(o['track_id'] is None for o in inventory['observations']),
            observed_shelves=sorted({j['input']['request']['shelf_id'] for j in jobs if j['input'].get('kind')=='detection'}))
        state['coverage_missing_shelves']=max(0,(state['plan'] or {}).get('expected_shelves',0)-len(state['observed_shelves']))
        return state

    async def start(self,session,plan):
        async with self.lock:
            if self.closing:raise ValueError('server shutting down')
            guide=await run_in_threadpool(self.queue.guidance.snapshot,session)
            if guide['phase']!='capture_bound' or guide['capture_status']!='capturing':raise ValueError('active bound capture required')
            if guide['reference_revision']!=plan.reference_revision:raise ValueError('reference changed; review and start a new plan')
            if not self.dispatcher.config or not {'detection','reading'}<=set(self.dispatcher.snapshot()['supported_kinds']):
                raise ValueError('configure detection and reading dispatch before starting the sweep')
            if self.task and not self.task.done():
                saved=await run_in_threadpool(self.read,session) if self.session==session else None
                if saved and saved['plan']==plan.model_dump(mode='json'):
                    if saved['attempts']>=plan.max_attempts:raise ValueError('attempt budget exhausted')
                    if saved['status']=='paused':saved['status']='running';await run_in_threadpool(self.save,saved)
                    return await run_in_threadpool(self.snapshot,session)
                raise ValueError('one continuous sweep coordinator is already active')
            state=await run_in_threadpool(self.read,session);payload=plan.model_dump(mode='json')
            if state['plan'] and state['plan']['plan_id']==plan.plan_id:
                if state['plan']!=payload:raise ValueError('plan ID reused with different controls')
            else:
                if state['pending']:raise ValueError('resume or finish the previous plan before selecting another shelf')
                if len(state['jobs'])>=200:raise ValueError('retained sweep job limit reached')
                state.update(plan=payload,attempts=0,last_frame=None,last_error=None)
            if state['attempts']>=plan.max_attempts:raise ValueError('attempt budget exhausted; explicitly choose a new plan')
            state['status']='running';await run_in_threadpool(self.save,state)
            self.session=session;self.task=asyncio.create_task(self.run(session))
            return await run_in_threadpool(self.snapshot,session)

    async def pause(self,session):
        async with self.lock:
            state=await run_in_threadpool(self.read,session);state['status']='paused';await run_in_threadpool(self.save,state)
        return await run_in_threadpool(self.snapshot,session)

    async def cancel_pending(self,session):
        async with self.lock:
            state=await run_in_threadpool(self.read,session)
            for payload in state['pending']:
                try:job=await run_in_threadpool(self.queue.get,payload['job_id'])
                except KeyError:continue # frozen input not enrolled yet
                if job['input']['session_id']!=session:raise ValueError('pending job scope differs')
                await run_in_threadpool(self.queue.cancel,payload['job_id'])
            state.update(status='paused',pending=[],last_error='pending_work_cancelled_by_user')
            await run_in_threadpool(self.save,state)
        return await run_in_threadpool(self.snapshot,session)

    def import_detection(self,state,job):
        sid=state['session_id'];jid=job['input']['job_id']
        review=self.registration.snapshot(sid,jid)
        if review['registration_events']:return [] # recovery after committed import
        if not review['can_register']:raise ValueError('detection is stale; review evidence instead of rebasing')
        old=self.ledger.snapshot(sid)['observations']
        result=self.registration.apply(RegistrationReview(review_id='auto-'+digest(jid.encode())[:24],session_id=sid,job_id=jid,
            expected_inventory_revision=job['input']['expected_inventory_revision'],expected_reference_revision=job['input']['expected_reference_revision'],
            reviewer='Budgeted sweep coordinator',reason='Opt-in unresolved observation enrollment; no new/same physical acceptance',
            decisions=[Decision(observation_id=p['observation_id'],action='unresolved',track_id=None,
                provenance='Provisional detection; physical identity and duplicate relationships require review') for p in review['candidates']]))
        observations=result['inventory']['observations'];new=[o for o in observations if o['frame_ref']==review['frame_ref'] and o['shelf_id']==review['shelf_id']]
        anchors=[]
        for ref in list(dict.fromkeys(o['frame_ref'] for o in old if o['shelf_id']==review['shelf_id']))[-3:]:
            if ref!=review['frame_ref']:anchors.append(dict(frame_ref=ref,observations=[o for o in old if o['frame_ref']==ref and o['shelf_id']==review['shelf_id']]))
        try:proposal=acquire_links(self.frames,dict(frame_ref=review['frame_ref'],observations=new),anchors)
        except (ValueError,ImportError):proposal=dict(status='registration_unavailable',links=[],accepted=False)
        state['association_proposals']=(state['association_proposals']+[dict(job_id=jid,**proposal)])[-20:]
        return new

    def prepare_readings(self,state,job):
        jid=job['input']['job_id'];review=self.registration.snapshot(state['session_id'],jid)
        inv=self.ledger.snapshot(state['session_id']);limit=state['plan']['max_attempts']-state['attempts']
        for proposal in review['candidates'][:limit]:
            oid=proposal['observation_id'];rid='sweep-read-'+digest((jid+oid).encode())[:24]
            if rid in state['jobs']:continue
            observation=next(o for o in inv['observations'] if o['id']==oid)
            reading=ReadingJob(job_id=rid,session_id=state['session_id'],expected_reference_revision=state['plan']['reference_revision'],
                request=ReadingRequest(sweep_id=state['session_id'],expected_revision=inv['revision'],observation_id=oid,frame_sha256=observation['frame_sha256']))
            # Persist exact frozen inputs before enrollment; recovery never re-pins them.
            state['pending'].append(reading.model_dump(mode='json'));state['jobs'].append(rid);state['attempts']+=1
        self.save(state)

    async def tick(self,session):
        async with self.lock:
            state=await run_in_threadpool(self.read,session)
            if state['status']!='running':return False
            guide=await run_in_threadpool(self.queue.guidance.snapshot,session)
            if guide['reference_revision']!=state['plan']['reference_revision']:
                state.update(status='paused',last_error='reference_changed');await run_in_threadpool(self.save,state);return False
            # Process only the frozen jobs prepared by this explicitly started plan.
            if state['pending']:
                payload=state['pending'][0];model=DetectionJob if payload.get('kind')=='detection' else ReadingJob
                job=await run_in_threadpool(self.queue.enqueue,model.model_validate(payload))
                if job['status']=='queued':await self.dispatcher.dispatch(session,payload['job_id']);return True
                if job['status']=='running' or job.get('worker_active',False):return True
                if payload.get('kind')=='detection' and job['status'] in ('completed','stale') and job['result_status'] in ('success','partial'):
                    await run_in_threadpool(self.import_detection,state,job)
                    state['pending'].pop(0)
                    await run_in_threadpool(self.prepare_readings,state,job)
                else:
                    state['pending'].pop(0)
                    if job['status']!='completed' or job.get('result_status') not in ('success','partial'):
                        state.update(status='paused',last_error=job.get('error_code') or 'recognition_unavailable_review_required')
                await run_in_threadpool(self.save,state);return True
            if guide['capture_status']=='closed' or state['attempts']>=state['plan']['max_attempts'] or len(state['jobs'])>=200:
                state['status']='drained' if guide['capture_status']=='closed' else 'budget_exhausted'
                await run_in_threadpool(self.save,state);return False
            frames=(await run_in_threadpool(self.frames.manifest,session))['frames']
            if not frames:return True
            frame=max(frames,key=lambda f:f['media_sequence'])
            if frame['id']==state['last_frame']:return True
            inv=await run_in_threadpool(self.ledger.snapshot,session);region=state['plan']['region']
            if inv['shelf_ownership'].get(state['plan']['shelf_id']) is False:
                state.update(status='paused',last_error='selected_shelf_excluded');await run_in_threadpool(self.save,state);return False
            bounds=(math.floor(region[0]*frame['width']),math.floor(region[1]*frame['height']),math.ceil(region[2]*frame['width']),math.ceil(region[3]*frame['height']))
            job=DetectionJob(kind='detection',job_id='sweep-detect-'+uuid.uuid4().hex,session_id=session,
                expected_reference_revision=state['plan']['reference_revision'],expected_inventory_revision=inv['revision'],
                request=DetectionRequest(sweep_id=session,frame_ref=frame['id'],frame_sha256=frame['sha256'],shelf_id=state['plan']['shelf_id'],
                    shelf_region_px=bounds,policy=state['plan']['policy']))
            state['last_frame']=frame['id'];state['pending']=[job.model_dump(mode='json')];state['jobs'].append(job.job_id);state['attempts']+=1
            await run_in_threadpool(self.save,state);return True

    async def run(self,session):
        try:
            while not self.closing and await self.tick(session):
                state=await run_in_threadpool(self.read,session)
                try:await asyncio.wait_for(self.wake.wait(),2 if state['pending'] else state['plan']['interval_seconds'])
                except TimeoutError:pass
        except asyncio.CancelledError:raise
        except Exception:
            state=await run_in_threadpool(self.read,session);state.update(status='paused',last_error='stale_busy_or_failed_review_required')
            await run_in_threadpool(self.save,state) # bounded redacted failure, no provider retry

    async def shutdown(self):
        self.closing=True
        self.wake.set()
        if self.task and not self.task.done():
            # Drain any SQLite thread before stopping the dispatcher-owned child.
            await self.task
