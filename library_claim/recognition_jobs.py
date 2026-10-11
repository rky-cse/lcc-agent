"""Durable single-worker reading/detection queue, with no inventory acceptance."""
import argparse
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field,model_validator,TypeAdapter

from .capture_store import FrameStore
from .guidance import GuidanceStore, Token
from .models import Contract,StageResult
from .packet import json_text
from .spine_reading import ReadingRequest, ReadingResponse, export_reading, prepare_crop
from .tracking import digest,TrackStore
from .spine_detection import DetectionRequest,DetectionResponse,validate_frame,export_detection
from .vision_provider import ALLOWED_MODELS, read_key,request_detection


def now():
    return datetime.now(timezone.utc).isoformat()


class ReadingJob(Contract):
    job_id: Token
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_reference_revision: int = Field(ge=0)
    request: ReadingRequest


class DetectionJob(Contract):
    kind: Literal['detection']
    job_id: Token
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_reference_revision: int = Field(ge=0)
    expected_inventory_revision: int = Field(ge=0)
    request: DetectionRequest

    @model_validator(mode='after')
    def explicit_shelf(self):
        if not self.request.shelf_id.strip():raise ValueError('explicit nonblank shelf ID required')
        return self


def parse_job(payload):
    # Existing stored reading inputs deliberately retain their original schema.
    return DetectionJob.model_validate(payload) if payload.get('kind')=='detection' else ReadingJob.model_validate(payload)


class RecognitionQueue:
    MAX_JOBS = 200
    MAX_PENDING = 20

    def __init__(self, store):
        self.store = store
        self.guidance = GuidanceStore(store)
        with closing(store._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS recognition_jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.commit()

    def _load(self, db, job_id):
        row = db.execute('SELECT state FROM recognition_jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError('unknown recognition job')
        return json.loads(row[0])

    def _save(self, db, state):
        db.execute('UPDATE recognition_jobs SET state=? WHERE id=?', (json_text(state), state['input']['job_id']))

    def _validate_pins(self, job):
        state = self.guidance.snapshot(job.session_id)
        if state['phase'] != 'capture_bound' or job.request.sweep_id != job.session_id:
            raise ValueError('recognition requires the bound capture sweep')
        if state['reference_revision'] != job.expected_reference_revision:
            raise ValueError('stale reference revision')
        if isinstance(job,DetectionJob):
            if TrackStore(self.store).snapshot(job.session_id)['revision']!=job.expected_inventory_revision:
                raise ValueError('stale inventory revision')
            validate_frame(self.store,job.request)
            self.store.read(job.request.frame_ref)
        else:
            prepare_crop(self.store, job.request)  # Original hash, observation, inventory and geometry gates.

    def enqueue(self, job):
        job = parse_job(job.model_dump())
        payload = job.model_dump(mode='json')
        with closing(self.store._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT state FROM recognition_jobs WHERE id=?', (job.job_id,)).fetchone()
            if existing:
                state = json.loads(existing[0])
                if state['input'] != payload:
                    raise ValueError('job ID already has different inputs')
                return self._project(state)
            states = [json.loads(r[0]) for r in db.execute('SELECT state FROM recognition_jobs')]
            if len(states) >= self.MAX_JOBS or sum(s['status'] in ('queued', 'running') or s.get('worker_active',False) for s in states) >= self.MAX_PENDING:
                raise ValueError('recognition queue limit reached')
            self._validate_pins(job)
            state = dict(input=payload, status='queued', created_at=now(), started_at=None, finished_at=None,
                         result_status=None, artifacts={}, error_code=None, inventory_mutated=False)
            db.execute('INSERT INTO recognition_jobs VALUES (?,?)', (job.job_id, json_text(state)))
            db.commit()
        return self._project(state)

    def _directory(self, job_id):
        return self.store.root / 'recognition' / job_id

    def _project(self, state):
        result = dict(state, eligible_for_review=False)
        if state['status'] == 'completed':
            directory = self._directory(state['input']['job_id'])
            for name, sha in state['artifacts'].items():
                path = directory / name
                if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != sha:
                    raise ValueError('recognition artifact integrity failure')
            try:
                self._validate_pins(parse_job(state['input']))
            except ValueError:
                result['status'] = 'stale'
            else:
                result['eligible_for_review'] = True
        return result

    def get(self, job_id):
        with closing(self.store._connect()) as db:
            return self._project(self._load(db, job_id))

    def list(self, session_id=None):
        with closing(self.store._connect()) as db:
            states=[json.loads(row[0]) for row in db.execute('SELECT state FROM recognition_jobs ORDER BY rowid')]
            return [self._project(state) for state in states if session_id is None or state['input']['session_id']==session_id]

    def cancel(self, job_id):
        """Revoke publication; an already submitted provider call may still finish."""
        with closing(self.store._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._load(db, job_id)
            if state['status'] in ('queued', 'running'):
                if state['status']=='running':
                    state['worker_active']=True  # Preserve the slot for legacy running records, too.
                state.update(status='cancelled', finished_at=now())
                self._save(db, state)
            db.commit()
        return self._project(state)

    def interrupt(self, job_id, *, expected_worker_id=None):
        """Explicitly close an uncertain running attempt; never requeue it."""
        with closing(self.store._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._load(db, job_id)
            if expected_worker_id is not None and state.get('worker_owner') != expected_worker_id:
                raise ValueError('attempt belongs to a different worker')
            if state['status'] != 'running' and not (state['status']=='cancelled' and state.get('worker_active',False)):
                raise ValueError('only a running attempt can be marked interrupted')
            state.update(status='interrupted', worker_active=False, finished_at=now(), error_code='provider_outcome_unknown')
            self._save(db, state)
            db.commit()
        return self._project(state)

    def _detect(self,job,output,response,key,model):
        if output.exists():raise FileExistsError('choose a fresh detection output directory before a provider call')
        started=datetime.now(timezone.utc)
        failure=usage=raw=None
        provider='offline_replay'
        if key is not None:
            record=validate_frame(self.store,job.request)
            response,failure,usage,raw=request_detection(key,self.store.read(record.id),record,job.request,model)
            provider=model
            self._validate_pins(job)
        try:
            result=export_detection(self.store,job.request,output,response,provider,failure,usage,started)
        except ValueError:
            if key is None or output.exists():raise
            failure=dict(code='provider_invalid_geometry',reason='provider geometry failed local validation',retryable=False)
            result=export_detection(self.store,job.request,output,None,provider,failure,usage,started)
        if raw is not None:
            (output/'provider_response.json').write_text(json_text(raw)+'\n',encoding='utf-8')
        stage=StageResult(sweep_id=job.session_id,job_id=job.job_id,input_revision=job.expected_inventory_revision,
            stage='queued_shelf_detection',status=result['stage_result']['status'],started_at=started,finished_at=datetime.now(timezone.utc),
            evidence_refs=[job.request.frame_ref],errors=result['stage_result']['errors'],
            warnings=['Provisional polygons only; registration and physical count acceptance require separate review.'])
        (output/'queue_stage.json').write_text(json_text(dict(input=job.model_dump(),stage_result=stage.model_dump(),inventory_mutated=False))+'\n',encoding='utf-8')
        return result

    def run_job(self, job_id, *, response=None, key=None, model='gemini-3.1-flash-lite',worker_id=None):
        """Dispatch only this exact job; terminal attempts are never rerun."""
        selected = self.get(job_id)
        kind = selected['input'].get('kind', 'reading')
        return self.run_next(response=response, key=key, model=model, kind=kind, job_id=job_id,worker_id=worker_id)

    def run_next(self, *, response=None, key=None, model='gemini-3.1-flash-lite',kind='reading',job_id=None,worker_id=None):
        if worker_id is not None:TypeAdapter(Token).validate_python(worker_id)
        if kind not in ('reading','detection'):raise ValueError('unsupported recognition kind')
        if (response is None) == (key is None):
            raise ValueError('choose exactly one replay response or live key')
        if response is not None:
            response = (DetectionResponse if kind=='detection' else ReadingResponse).model_validate(response.model_dump())
        if model not in ALLOWED_MODELS:
            raise ValueError('unsupported model')
        with closing(self.store._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            states = [json.loads(r[0]) for r in db.execute('SELECT state FROM recognition_jobs ORDER BY rowid')]
            if job_id is not None:
                state = self._load(db, job_id)
                if state['input'].get('kind', 'reading') != kind:
                    raise ValueError('selected job differs from recognition kind')
                if state['status'] not in ('queued', 'running'):
                    return self._project(state)  # A repeated selection returns evidence, never another attempt.
            if any(s['status'] == 'running' or s.get('worker_active',False) for s in states):
                raise ValueError('worker busy or interrupted; resolve running attempt explicitly')
            if job_id is None:
                state = next((s for s in states if s['status'] == 'queued' and s['input'].get('kind','reading')==kind), None)
            if state is None:
                return None
            job = parse_job(state['input'])
            try:
                self._validate_pins(job)
            except ValueError:
                state.update(status='stale', finished_at=now(), error_code='inputs_invalidated')
                self._save(db, state); db.commit()
                return self._project(state)
            state.update(status='running', worker_active=True, started_at=now(), attempt_provider=model if key is not None else 'offline_replay')
            if worker_id is not None:state['worker_owner']=worker_id
            self._save(db, state); db.commit()
        # No SQLite lock and no audio/camera task is held across a provider request.
        artifacts = {}
        try:
            if isinstance(job,DetectionJob):
                result=self._detect(job,self._directory(job.job_id),response,key,model)
            else:
                result = export_reading(self.store, job.request, self._directory(job.job_id), response=response, key=key, model=model)
            self._validate_pins(job)
            artifacts = {p.name: digest(p.read_bytes()) for p in self._directory(job.job_id).iterdir() if p.is_file()}
            status, error, result_status = 'completed', None, result['stage_result']['status']
        except ValueError:
            try:
                self._validate_pins(job)
            except ValueError:
                status, error = 'stale', 'inputs_invalidated'
            else:
                status, error = 'failed', 'recognition_validation_failed'
            result_status = None
        except Exception:
            # Exception messages can contain provider URLs/credentials. Never journal them.
            status, error, result_status = 'failed', 'recognition_worker_failed', None
        with closing(self.store._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._load(db, job.job_id)
            if current['status'] == 'running':
                # Check again while holding the writer lock, before publishing a result.
                if status == 'completed':
                    try:
                        self._validate_pins(job)
                    except ValueError:
                        status, error = 'stale', 'inputs_invalidated'
                current.update(status=status, error_code=error, result_status=result_status,
                               artifacts=artifacts, finished_at=now())
            current['worker_active']=False  # Cancellation revokes publication, but holds the slot until execution exits.
            self._save(db, current)
            db.commit()
        return self._project(current)


def main():
    parser = argparse.ArgumentParser(description='Explicit bounded recognition queue; one job per worker invocation')
    parser.add_argument('--store', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--enqueue', type=Path)
    action.add_argument('--list', action='store_true')
    action.add_argument('--run-one', action='store_true')
    action.add_argument('--cancel')
    action.add_argument('--interrupt')
    parser.add_argument('--response', type=Path)
    parser.add_argument('--gemini', action='store_true')
    parser.add_argument('--free-tier-confirmed', action='store_true')
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--model', choices=ALLOWED_MODELS, default='gemini-3.1-flash-lite')
    parser.add_argument('--kind',choices=('reading','detection'))
    parser.add_argument('--job-id', help='With --run-one, dispatch only this stored job (kind inferred)')
    parser.add_argument('--worker-id', help='Optional local dispatch ownership token')
    args = parser.parse_args()
    if args.job_id is not None and not args.run_one:
        parser.error('--job-id requires --run-one')
    if args.job_id is not None:
        try:
            TypeAdapter(Token).validate_python(args.job_id)
        except ValueError:
            parser.error('--job-id must be a nonblank stored job token')
    if args.worker_id is not None:
        if not args.run_one:parser.error('--worker-id requires --run-one')
        try:TypeAdapter(Token).validate_python(args.worker_id)
        except ValueError:parser.error('invalid worker ownership token')
    queue = RecognitionQueue(FrameStore(args.store))
    if args.enqueue:
        result = queue.enqueue(parse_job(json.loads(args.enqueue.read_text(encoding='utf-8'))))
    elif args.list:
        result = queue.list()
    elif args.run_one:
        if bool(args.response) == args.gemini:
            parser.error('run-one needs exactly one --response or --gemini')
        if args.gemini and not args.free_tier_confirmed:
            parser.error('confirm free-tier account; no paid fallback')
        kind = queue.get(args.job_id)['input'].get('kind','reading') if args.job_id else (args.kind or 'reading')
        if args.job_id and args.kind and args.kind != kind:
            parser.error('--kind differs from selected job; nothing dispatched')
        response_type=DetectionResponse if kind=='detection' else ReadingResponse
        response = response_type.model_validate_json(args.response.read_text(encoding='utf-8')) if args.response else None
        options=dict(response=response, key=read_key(args.key_file) if args.gemini else None, model=args.model,worker_id=args.worker_id)
        result = queue.run_job(args.job_id, **options) if args.job_id else queue.run_next(kind=kind, **options)
    else:
        result = queue.cancel(args.cancel) if args.cancel else queue.interrupt(args.interrupt)
    print(json_text(result))


if __name__ == '__main__':
    main()
