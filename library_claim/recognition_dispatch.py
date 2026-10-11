"""Opt-in exact-job subprocess dispatch. No automatic queue consumption."""
import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from .vision_provider import ALLOWED_MODELS
from .spine_detection import DetectionResponse
from .spine_reading import ReadingResponse
from .packet import json_text
from .tracking import TrackStore


@dataclass(repr=False)
class DispatchConfig:
    key: str | None = field(default=None,repr=False)
    free_tier_confirmed: bool = False
    model: str = 'gemini-3.1-flash-lite'
    replay: dict = field(default_factory=dict)

    def validate(self, synthetic):
        if self.model not in ALLOWED_MODELS:raise ValueError('unsupported recognition model')
        if bool(self.key)==bool(self.replay):raise ValueError('configure exactly one recognition key or replay')
        if self.key is not None and (not self.key.strip() or not self.free_tier_confirmed):
            raise ValueError('live recognition requires a local key and explicit free-tier confirmation')
        if self.replay:
            if not synthetic:raise ValueError('recognition replay requires synthetic server mode')
            if set(self.replay)-{'reading','detection'}:raise ValueError('unsupported replay kind')
            self.replay={kind:(DetectionResponse if kind=='detection' else ReadingResponse).model_validate(payload)
                         for kind,payload in self.replay.items()}
        return self


class RecognitionDispatcher:
    def __init__(self,queue,config=None,*,synthetic=False):
        self.queue=queue;self.config=config.validate(synthetic) if config else None
        self.lock=asyncio.Lock();self.task=None;self.process=None;self.selected=None
        self.owner=None;self.last_outcome=None;self.closing=False;self.session_id=None;self.spawn_task=None

    def snapshot(self,session_id=None):
        visible=session_id is None or self.session_id==session_id
        return dict(enabled=self.config is not None,mode=('replay' if self.config.replay else 'gemini') if self.config else 'disabled',
            session_id=session_id,supported_kinds=sorted(self.config.replay) if self.config and self.config.replay else ['reading','detection'] if self.config else [],
            model=self.config.model if self.config and not self.config.replay else None,
            active=self.task is not None and not self.task.done(),job_id=self.selected if visible else None,
            closing=self.closing,last_outcome=self.last_outcome if visible else None)

    async def dispatch(self,session_id,job_id):
        job=await run_in_threadpool(self.queue.get,job_id)
        if job['input']['session_id']!=session_id:raise KeyError('unknown job in this session')
        async with self.lock:
            if self.closing:raise ValueError('recognition dispatcher shutting down')
            if self.config is None:raise ValueError('recognition server dispatch is disabled')
            if job['status'] not in ('queued','running'):
                return dict(accepted=False,job=job,dispatcher=self.snapshot(session_id))
            if self.task is not None and not self.task.done():
                if self.selected!=job_id:raise ValueError('recognition dispatcher busy')
                return dict(accepted=True,job=job,dispatcher=self.snapshot(session_id))
            states=await run_in_threadpool(self.queue.list)
            if any(s['status']=='running' or s.get('worker_active',False) for s in states):
                raise ValueError('worker active or uncertain; stop and resolve its attempt before dispatch')
            kind=job['input'].get('kind','reading')
            if self.config.replay and kind not in self.config.replay:
                raise ValueError('selected recognition kind has no configured replay')
            if self.config.replay:
                await run_in_threadpool(self._synthetic_evidence,job,kind)
            self.selected=job_id;self.session_id=session_id;self.owner=uuid.uuid4().hex;self.last_outcome=None
            # Task ownership belongs to the app, not the HTTP request/client.
            self.task=asyncio.create_task(self._execute(job_id,kind,self.owner))
            return dict(accepted=True,job=job,dispatcher=self.snapshot(session_id))

    def _synthetic_evidence(self,job,kind):
        request=job['input']['request']
        if kind=='detection':frame_ref=request['frame_ref']
        else:
            state=TrackStore(self.queue.store).snapshot(job['input']['session_id'])
            frame_ref=next(o['frame_ref'] for o in state['observations'] if o['id']==request['observation_id'])
        if not self.queue.store.get(frame_ref).synthetic:
            raise ValueError('synthetic replay cannot analyze real capture evidence')

    def _replay_file(self,kind,owner):
        directory=self.queue.store.root/'dispatch_replays';directory.mkdir(parents=True,exist_ok=True)
        path=directory/(owner+'.json')
        path.write_text(json_text(self.config.replay[kind].model_dump()),encoding='utf-8')
        return path.resolve()

    async def _stop_child(self):
        child=self.process
        if child is None or child.returncode is not None:return
        try:child.terminate()
        except ProcessLookupError:pass
        try:await asyncio.wait_for(child.wait(),5)
        except TimeoutError:
            child.kill();await child.wait()

    async def _close_owned_attempt(self,job_id,owner):
        job=await run_in_threadpool(self.queue.get,job_id)
        if job.get('worker_owner')==owner and (job['status']=='running' or job.get('worker_active',False)):
            await run_in_threadpool(self.queue.interrupt,job_id,expected_worker_id=owner)

    async def _execute(self,job_id,kind,owner):
        child_exited=False;replay_path=None
        try:
            config=self.config
            args=[sys.executable,'-B','-m','library_claim.recognition_jobs','--store',str(self.queue.store.root.resolve()),
                  '--run-one','--job-id',job_id,'--worker-id',owner,'--model',config.model]
            env=os.environ.copy()
            if config.replay:
                # Validated startup fixtures only. No HTTP-provided response/path.
                replay_path=await run_in_threadpool(self._replay_file,kind,owner)
                args+=['--response',str(replay_path)]
            else:
                env['GEMINI_API_KEY']=config.key
                args+=['--gemini','--free-tier-confirmed']
            # Child output is neither buffered nor surfaced; verified SQLite state is authoritative.
            self.spawn_task=asyncio.create_task(asyncio.create_subprocess_exec(*args,env=env,cwd=str(Path(__file__).resolve().parent.parent),
                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,
                **({'creationflags':0x08000000} if os.name=='nt' else {})))
            self.process=await asyncio.shield(self.spawn_task)
            if self.closing:await self._stop_child()
            code=await self.process.wait();child_exited=True
            await self._close_owned_attempt(job_id,owner)
            self.last_outcome='worker_exited' if code==0 else 'worker_failed_or_stopped'
        except asyncio.CancelledError:
            if self.process is None and self.spawn_task is not None:
                self.process=await asyncio.shield(self.spawn_task)
            await self._stop_child();child_exited=self.process is not None and self.process.returncode is not None
            if child_exited:await self._close_owned_attempt(job_id,owner)
            self.last_outcome='worker_stopped';raise
        except Exception:
            self.last_outcome='dispatch_failed'  # Do not expose exception strings/credentials.
            if self.process is not None:
                await self._stop_child();child_exited=self.process.returncode is not None
                if child_exited:
                    try:await self._close_owned_attempt(job_id,owner)
                    except Exception:self.last_outcome='recovery_required'
        finally:
            self.process=None;self.spawn_task=None
            if replay_path is not None:
                try:await run_in_threadpool(replay_path.unlink,missing_ok=True)
                except OSError:self.last_outcome='replay_cleanup_failed'

    async def shutdown(self):
        async with self.lock:
            self.closing=True;task=self.task
        if task is not None and not task.done():
            # Let a concurrent spawn finish; _execute notices closing immediately after spawn.
            await self._stop_child()
            await asyncio.shield(task)
