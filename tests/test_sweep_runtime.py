import asyncio
import unittest
from contextlib import closing
from unittest.mock import patch
from fastapi.testclient import TestClient
from library_claim.sweep_runtime import SweepRuntime,SweepPlan
from library_claim.spine_reading import ReadingResponse
from library_claim.recognition_dispatch import DispatchConfig
from library_claim.server import create_app
from library_claim.guidance import GuidanceCommand
from library_claim.live_voice import input_message
from tests import test_detection_jobs as detection_fixture


class LocalDispatcher:
    config=True
    def __init__(self,queue,response):self.queue=queue;self.response=response;self.calls=[]
    def snapshot(self,session=None):return dict(supported_kinds=['detection','reading'],mode='replay',enabled=True,active=False)
    async def dispatch(self,session,job):
        self.calls.append(job);kind=self.queue.get(job)['input'].get('kind','reading')
        self.queue.run_job(job,response=self.response if kind=='detection' else ReadingResponse(legibility='unreadable',spans=[],uncertainty='Unreadable fixture'))


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx=detection_fixture.DetectionQueueTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.sid=self.fx.job.session_id;self.dispatcher=LocalDispatcher(self.fx.queue,self.fx.response)
        self.runtime=SweepRuntime(self.fx.queue,self.dispatcher)
        self.plan=SweepPlan(plan_id='unit-plan',shelf_id='test-live-shelf',region=(0,0,1,1),policy=self.fx.job.request.policy,
            max_attempts=2,interval_seconds=5,expected_shelves=2,reference_revision=self.fx.job.expected_reference_revision,allow_unresolved_import=True)
        self.addAsyncCleanup(self.runtime.shutdown)

    def configured(self):
        state=self.runtime.read(self.sid);state.update(status='running',plan=self.plan.model_dump(mode='json'));self.runtime.save(state);return state

    async def test_budgeted_detection_import_and_reading_without_accepted_copy(self):
        before=self.runtime.ledger.snapshot(self.sid);self.configured()
        for _ in range(7):await self.runtime.tick(self.sid)
        state=self.runtime.snapshot(self.sid);after=self.runtime.ledger.snapshot(self.sid)
        self.assertEqual(state['status'],'budget_exhausted');self.assertEqual(len(self.dispatcher.calls),2)
        self.assertEqual(state['attempts'],2);self.assertEqual(state['remaining_attempts'],0)
        self.assertEqual(after['assigned_track_count'],before['assigned_track_count'])
        self.assertEqual(len(after['observations']),len(before['observations'])+1)
        self.assertIsNone(after['observations'][-1]['track_id']);self.assertFalse(state['packet_ready'])
        self.assertTrue(state['recognition_drained']);self.assertEqual(state['coverage_missing_shelves'],1)
        self.assertEqual(state['outcomes']['detection']['book_spine_candidates'],1)
        self.assertEqual(state['outcomes']['detection']['non_book_proposals'],0)
        self.assertEqual(state['outcomes']['reading']['partial_or_unreadable'],1)
        detection=next(job for job in self.fx.queue.list(self.sid) if job['input'].get('kind')=='detection')
        self.assertEqual(detection['status'],'completed')
        self.assertEqual(detection['review_state'],'already_imported_as_provisional_observations')
        guide=self.fx.fx.guide.snapshot(self.sid);self.assertTrue(guide['recognition_progress']['capture_hints'])
        self.assertFalse(guide['recognition_progress']['accepted_identity'])

    async def test_pause_and_restart_never_dispatch_and_exact_inputs_survive(self):
        self.configured();await self.runtime.tick(self.sid);before=self.runtime.read(self.sid)
        other=SweepRuntime(self.fx.queue,self.dispatcher)
        self.assertEqual(other.snapshot(self.sid)['status'],'restart_requires_explicit_resume')
        self.assertEqual(self.dispatcher.calls,[]);await self.runtime.pause(self.sid)
        self.assertFalse(await self.runtime.tick(self.sid));self.assertEqual(self.runtime.read(self.sid)['pending'],before['pending'])
        state=self.runtime.read(self.sid);state['status']='running';self.runtime.save(state)
        from library_claim.recognition_jobs import DetectionJob
        self.fx.queue.enqueue(DetectionJob.model_validate(state['pending'][0]))
        with closing(self.fx.queue.store._connect()) as db:
            job=self.fx.queue._load(db,state['pending'][0]['job_id']);job.update(status='failed',error_code='fixture_unavailable')
            self.fx.queue._save(db,job);db.commit()
        await self.runtime.tick(self.sid)
        self.assertEqual(self.runtime.read(self.sid)['status'],'paused');self.assertEqual(self.dispatcher.calls,[])

    async def test_reference_change_pauses_before_any_provider_attempt(self):
        state=self.configured();state['plan']['reference_revision']+=1;self.runtime.save(state)
        self.assertFalse(await self.runtime.tick(self.sid));self.assertEqual(self.dispatcher.calls,[])
        self.assertEqual(self.runtime.read(self.sid)['last_error'],'reference_changed')

    async def test_explicit_cancel_removes_frozen_work_without_dispatch_or_retry(self):
        self.configured();await self.runtime.tick(self.sid)
        state=self.runtime.read(self.sid)
        from library_claim.recognition_jobs import DetectionJob
        self.fx.queue.enqueue(DetectionJob.model_validate(state['pending'][0]))
        result=await self.runtime.cancel_pending(self.sid)
        self.assertEqual(result['pending'],[]);self.assertEqual(result['status'],'paused')
        self.assertEqual(self.fx.queue.get(state['jobs'][0])['status'],'cancelled');self.assertEqual(self.dispatcher.calls,[])

    async def test_closed_capture_drains_only_frozen_pending_work(self):
        self.configured();await self.runtime.tick(self.sid)
        self.fx.fx.guide.capture.end(self.sid,'unit-end',0)
        for _ in range(7):await self.runtime.tick(self.sid)
        self.assertEqual(self.runtime.snapshot(self.sid)['status'],'drained')
        self.assertEqual(len(self.dispatcher.calls),2)

    async def test_import_commit_recovery_does_not_add_second_inventory_revision(self):
        state=self.configured();await self.runtime.tick(self.sid);await self.runtime.tick(self.sid)
        state=self.runtime.read(self.sid);job=self.fx.queue.get(state['pending'][0]['job_id'])
        self.runtime.import_detection(state,job);revision=self.runtime.ledger.snapshot(self.sid)['revision']
        await self.runtime.tick(self.sid)
        self.assertEqual(self.runtime.ledger.snapshot(self.sid)['revision'],revision)
        self.assertEqual(self.runtime.read(self.sid)['attempts'],2)

    async def test_explicit_start_activation_scope_and_repeat_controls(self):
        manager=SweepRuntime(self.fx.queue,self.dispatcher)
        async def blocked(session):await manager.wake.wait()
        with patch.object(manager,'run',side_effect=blocked):
            first=await manager.start(self.sid,self.plan);again=await manager.start(self.sid,self.plan)
            self.assertTrue(first['active']);self.assertEqual(first['plan'],again['plan'])
            await manager.pause(self.sid);self.assertFalse(manager.snapshot(self.sid)['active'])
            resumed=await manager.start(self.sid,self.plan);self.assertEqual(resumed['status'],'running')
            with self.assertRaises(ValueError):await manager.start(self.sid,self.plan.model_copy(update={'max_attempts':3}))
            await manager.shutdown()

    async def test_api_read_only_scope_and_same_origin_embedding(self):
        app=create_app(self.fx.fx.frames.root,{'http://testserver'},synthetic=True)
        with TestClient(app) as client:
            self.assertEqual(client.get(f'/api/guidance/{self.sid}/sweep').json()['status'],'idle')
            self.assertEqual(client.post(f'/api/guidance/{self.sid}/sweep/start',json=self.plan.model_dump(mode='json'),headers={'Origin':'http://testserver'}).status_code,409)
            self.assertEqual(client.post(f'/api/guidance/{self.sid}/sweep/pause',json={'session_id':'f'*32},headers={'Origin':'http://testserver'}).status_code,422)
            self.assertIn("frame-ancestors 'self'",client.get('/voice').headers['content-security-policy'])
            self.assertIn("frame-ancestors 'none'",client.get('/sweep').headers['content-security-policy'])

    def test_art_declaration_is_literal_and_defaults_unknown_to_appraisal(self):
        guide=self.fx.fx.guide;before=guide.snapshot(self.sid)
        command=GuidanceCommand(command_id='art-test',session_id=self.sid,expected_revision=before['revision'],speaker='claimant',
            payload=dict(action='art',frame_ref=self.fx.frame.id,description='Portrait',classification='unknown',claimant_statement='I do not know whether this is a print'))
        result=guide.apply(command);self.assertTrue(result['art_declarations'][0]['needs_appraisal'])
        self.assertEqual(result['inventory_revision'],before['inventory_revision'])

    def test_watch_requires_boolean_and_plan_requires_explicit_valid_bounds(self):
        self.assertEqual(input_message('{"type":"watch","enabled":true}')['enabled'],True)
        with self.assertRaises(ValueError):input_message('{"type":"watch","enabled":"true"}')
        for region in [(0,0,0,1),(-1,0,1,1),(0,0,2,1)]:
            payload=self.plan.model_dump();payload['region']=region
            with self.assertRaises(ValueError):SweepPlan.model_validate(payload)


if __name__=='__main__':unittest.main()
