import asyncio
import json
import subprocess
import sys
import time
import unittest
from contextlib import closing
from unittest.mock import patch
from fastapi.testclient import TestClient
from library_claim.recognition_dispatch import DispatchConfig,RecognitionDispatcher
from library_claim.server import create_app
from tests import test_recognition_jobs as fixture
from tests import test_detection_jobs as detection_fixture


class Child:
    def __init__(self):self.returncode=None;self.exited=asyncio.Event();self.terminated=False
    async def wait(self):await self.exited.wait();return self.returncode
    def terminate(self):self.terminated=True;self.returncode=-15;self.exited.set()
    def kill(self):self.terminate()


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx=fixture.RecognitionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.queue=self.fx.queue;self.queue.enqueue(self.fx.job)
        self.other=self.fx.job.model_copy(update={'job_id':'other-job'});self.queue.enqueue(self.other)
        self.manager=RecognitionDispatcher(self.queue,DispatchConfig(replay={'reading':self.fx.response}),synthetic=True)
        self.addAsyncCleanup(self.manager.shutdown)
        self.child=Child();self.spawned=asyncio.Event();self.calls=[]

    async def spawn(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        job_id=args[args.index('--job-id')+1];owner=args[args.index('--worker-id')+1]
        with closing(self.queue.store._connect()) as db:
            state=self.queue._load(db,job_id);state.update(status='running',worker_active=True,worker_owner=owner)
            self.queue._save(db,state);db.commit()
        self.spawned.set();return self.child

    async def start(self):
        result=await self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id)
        await asyncio.wait_for(self.spawned.wait(),5);return result

    async def test_repeated_dispatch_single_owned_child_and_other_job_busy(self):
        with patch('library_claim.recognition_dispatch.asyncio.create_subprocess_exec',side_effect=self.spawn):
            first=await self.start();self.assertTrue(first['accepted'])
            again=await self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id);self.assertTrue(again['accepted'])
            with self.assertRaisesRegex(ValueError,'busy'):await self.manager.dispatch(self.other.session_id,self.other.job_id)
            self.assertEqual(len(self.calls),1)
            await self.manager.shutdown()
        self.assertEqual(self.queue.get(self.fx.job.job_id)['status'],'interrupted')
        self.assertFalse(self.queue.get(self.fx.job.job_id)['worker_active'])
        self.assertEqual(self.queue.get(self.other.job_id)['status'],'queued')

    async def test_http_cancellation_does_not_cancel_owned_worker_and_cancel_holds_slot(self):
        with patch('library_claim.recognition_dispatch.asyncio.create_subprocess_exec',side_effect=self.spawn):
            request=asyncio.create_task(self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id))
            await request;request.cancel();await asyncio.wait_for(self.spawned.wait(),5)
            self.assertTrue(self.manager.snapshot()['active']);self.assertIsNone(self.child.returncode)
            self.queue.cancel(self.fx.job.job_id)
            with self.assertRaisesRegex(ValueError,'busy'):await self.manager.dispatch(self.other.session_id,self.other.job_id)
            await self.manager.shutdown()
        self.assertTrue(self.child.terminated);self.assertEqual(self.queue.get(self.fx.job.job_id)['status'],'interrupted')

    async def test_shutdown_waits_for_spawn_before_recovering_owned_attempt(self):
        release=asyncio.Event();entered=asyncio.Event()
        async def delayed(*args,**kwargs):entered.set();await release.wait();return await self.spawn(*args,**kwargs)
        with patch('library_claim.recognition_dispatch.asyncio.create_subprocess_exec',side_effect=delayed):
            await self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id);await entered.wait()
            closing_task=asyncio.create_task(self.manager.shutdown());await asyncio.sleep(0)
            self.assertFalse(closing_task.done());release.set();await asyncio.wait_for(closing_task,5)
        self.assertTrue(self.child.terminated);self.assertEqual(self.queue.get(self.fx.job.job_id)['status'],'interrupted')

    async def test_process_failure_fixed_outcome_no_retry_or_other_job(self):
        with patch('library_claim.recognition_dispatch.asyncio.create_subprocess_exec',side_effect=RuntimeError('SECRET_KEY')) as spawn:
            await self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id);await self.manager.task
            self.assertEqual(spawn.call_count,1)
        self.assertEqual(self.manager.snapshot()['last_outcome'],'dispatch_failed')
        self.assertNotIn('SECRET_KEY',json.dumps(self.manager.snapshot()))
        self.assertEqual(self.queue.get(self.other.job_id)['status'],'queued')

    async def test_external_worker_ownership_is_never_closed_by_dispatcher(self):
        with patch('library_claim.recognition_dispatch.asyncio.create_subprocess_exec',side_effect=self.spawn):
            await self.start()
            with closing(self.queue.store._connect()) as db:
                state=self.queue._load(db,self.fx.job.job_id);state['worker_owner']='external-worker';self.queue._save(db,state);db.commit()
            await self.manager.shutdown()
        self.assertEqual(self.queue.get(self.fx.job.job_id)['status'],'running')
        with self.assertRaises(ValueError):self.queue.interrupt(self.fx.job.job_id,expected_worker_id=self.manager.owner)
        self.queue.interrupt(self.fx.job.job_id)

    async def test_disabled_terminal_scope_and_secrets(self):
        disabled=RecognitionDispatcher(self.queue)
        with self.assertRaisesRegex(ValueError,'disabled'):await disabled.dispatch(self.fx.job.session_id,self.fx.job.job_id)
        with self.assertRaises(KeyError):await self.manager.dispatch('a'*32,self.fx.job.job_id)
        cancelled=self.queue.cancel(self.fx.job.job_id)
        result=await self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id)
        self.assertFalse(result['accepted']);self.assertEqual(result['job'],cancelled)
        live=RecognitionDispatcher(self.queue,DispatchConfig(key='SENSITIVE_FIXTURE',free_tier_confirmed=True))
        self.assertNotIn('SENSITIVE_FIXTURE',repr(live.config)+json.dumps(live.snapshot()))
        self.manager.selected='private-job';self.manager.session_id=self.fx.job.session_id
        self.assertIsNone(self.manager.snapshot('a'*32)['job_id'])

    async def test_uncertain_existing_worker_blocks_new_server_without_automatic_reset(self):
        with closing(self.queue.store._connect()) as db:
            state=self.queue._load(db,self.other.job_id);state.update(status='cancelled',worker_active=True)
            self.queue._save(db,state);db.commit()
        with self.assertRaisesRegex(ValueError,'uncertain'):await self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id)
        await self.manager.shutdown();self.assertTrue(self.queue.get(self.other.job_id)['worker_active'])

    async def test_real_child_is_stopped_and_verified_before_owned_recovery(self):
        real_spawn=asyncio.create_subprocess_exec
        code='''import sys,time,json,sqlite3
db=sqlite3.connect(sys.argv[1]);state=json.loads(db.execute('SELECT state FROM recognition_jobs WHERE id=?',(sys.argv[2],)).fetchone()[0])
state.update(status='running',worker_active=True,worker_owner=sys.argv[3])
db.execute('UPDATE recognition_jobs SET state=? WHERE id=?',(json.dumps(state),sys.argv[2]));db.commit();db.close()
time.sleep(300)
'''
        async def helper(*args,**kwargs):
            owner=args[args.index('--worker-id')+1]
            # A controlled blocked worker claims the same durable ownership contract, with no network.
            database=self.queue.store.database
            return await real_spawn(sys.executable,'-c',code,str(database),self.fx.job.job_id,owner,**kwargs)
        with patch('library_claim.recognition_dispatch.asyncio.create_subprocess_exec',side_effect=helper):
            await self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id)
            deadline=asyncio.get_running_loop().time()+5
            while not self.queue.get(self.fx.job.job_id).get('worker_active',False) and asyncio.get_running_loop().time()<deadline:
                await asyncio.sleep(.02)
            self.assertTrue(self.queue.get(self.fx.job.job_id).get('worker_active',False))
            child=self.manager.process;self.assertIsNone(child.returncode)
            await self.manager.shutdown();self.assertIsNotNone(child.returncode)
        self.assertEqual(self.queue.get(self.fx.job.job_id)['status'],'interrupted')
        self.assertFalse(self.queue.get(self.fx.job.job_id)['worker_active'])

    async def test_live_credentials_stay_in_child_environment_and_never_public_status(self):
        self.manager=RecognitionDispatcher(self.queue,DispatchConfig(key='PRIVATE_TEST_KEY',free_tier_confirmed=True))
        self.addAsyncCleanup(self.manager.shutdown)
        with patch('library_claim.recognition_dispatch.asyncio.create_subprocess_exec',side_effect=self.spawn):
            await self.start();args,options=self.calls[0]
            self.assertNotIn('PRIVATE_TEST_KEY',' '.join(args));self.assertEqual(options['env']['GEMINI_API_KEY'],'PRIVATE_TEST_KEY')
            self.assertNotIn('PRIVATE_TEST_KEY',json.dumps(self.manager.snapshot())+json.dumps(self.queue.get(self.fx.job.job_id)))
            await self.manager.shutdown()

    async def test_replay_rejects_real_evidence_and_missing_configured_kind(self):
        with patch.object(self.queue.store,'get',return_value=self.fx.frame.model_copy(update={'synthetic':False})):
            with self.assertRaisesRegex(ValueError,'real capture'):await self.manager.dispatch(self.fx.job.session_id,self.fx.job.job_id)
        missing=RecognitionDispatcher(self.queue,DispatchConfig(replay={'detection':dict(coverage='no_visible_books',objects=[],unresolved_regions=[])}),synthetic=True)
        with self.assertRaisesRegex(ValueError,'no configured replay'):await missing.dispatch(self.fx.job.session_id,self.fx.job.job_id)
        self.assertEqual(self.queue.get(self.fx.job.job_id)['status'],'queued')


class DispatchHttpTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.RecognitionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.queue=self.fx.queue;self.queue.enqueue(self.fx.job)
        self.url=f'/api/guidance/{self.fx.job.session_id}/recognition/dispatch'

    def test_actual_child_http_completion_repeat_restart_and_scope_boundaries(self):
        config=DispatchConfig(replay={'reading':self.fx.response})
        app=create_app(self.fx.fx.frames.root,{'http://testserver'},synthetic=True,recognition_config=config)
        with TestClient(app) as client:
            body={'job_id':self.fx.job.job_id};headers={'Origin':'http://testserver'}
            self.assertEqual(client.post(self.url,json=body).status_code,403)
            self.assertEqual(client.post(self.url,json=body|{'key':'never'},headers=headers).status_code,422)
            self.assertEqual(client.post(self.url,content='x'*4097,headers=headers).status_code,413)
            self.assertEqual(client.post(self.url.replace(self.fx.job.session_id,'a'*32),json=body,headers=headers).status_code,404)
            response=client.post(self.url,json=body,headers=headers);self.assertEqual(response.status_code,202)
            deadline=time.monotonic()+10
            while client.get(self.url).json()['active'] and time.monotonic()<deadline:time.sleep(.02)
            self.assertFalse(client.get(self.url).json()['active'])
            result=client.post(self.url,json=body,headers=headers);self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['job']['status'],'completed');self.assertFalse(result.json()['accepted'])
            self.assertEqual(client.get('/api/health').json()['recognition_worker'],'explicit_server')
            self.assertFalse(client.get('/api/health').json()['provider_calls'])
        with TestClient(create_app(self.fx.fx.frames.root,{'http://testserver'},synthetic=True,recognition_config=config)) as restarted:
            self.assertEqual(restarted.post(self.url,json=body,headers=headers).json()['job'],result.json()['job'])
        self.assertEqual(self.fx.inventory,self.fx.fx.guide.ledger.snapshot(self.fx.job.session_id))

    def test_default_disabled_and_configuration_gates(self):
        with TestClient(create_app(self.fx.fx.frames.root,{'http://testserver'})) as client:
            self.assertFalse(client.get(self.url).json()['enabled'])
            self.assertEqual(client.post(self.url,json={'job_id':self.fx.job.job_id},headers={'Origin':'http://testserver'}).status_code,409)
        for config,synthetic in [(DispatchConfig(key='fixture'),False),(DispatchConfig(replay={'reading':self.fx.response}),False),
                                  (DispatchConfig(key='fixture',free_tier_confirmed=True,replay={'reading':self.fx.response}),True),
                                  (DispatchConfig(key='fixture',free_tier_confirmed=True,model='paid-model'),False)]:
            with self.assertRaises(ValueError):create_app(self.fx.fx.frames.root,{'http://testserver'},synthetic=synthetic,recognition_config=config)
        prefix=[sys.executable,'-B','-m','library_claim.server','--store',str(self.fx.fx.frames.root)]
        for args in [['--recognition'],['--recognition-replay','missing.json']]:
            self.assertEqual(subprocess.run(prefix+args,capture_output=True,text=True).returncode,2)

    def test_actual_detection_child_uses_stored_kind_and_does_not_register(self):
        fx=detection_fixture.DetectionQueueTests();fx.setUp();self.addCleanup(fx.doCleanups);fx.queue.enqueue(fx.job)
        app=create_app(fx.fx.frames.root,{'http://testserver'},synthetic=True,recognition_config=DispatchConfig(replay={'detection':fx.response}))
        url=f'/api/guidance/{fx.job.session_id}/recognition/dispatch'
        with TestClient(app) as client:
            self.assertEqual(client.post(url,json={'job_id':fx.job.job_id},headers={'Origin':'http://testserver'}).status_code,202)
            deadline=time.monotonic()+10
            while client.get(url).json()['active'] and time.monotonic()<deadline:time.sleep(.02)
            self.assertFalse(client.get(url).json()['active']);self.assertEqual(fx.queue.get(fx.job.job_id)['status'],'completed')
        self.assertEqual(fx.before,fx.fx.guide.ledger.snapshot(fx.job.session_id))

    def test_status_reports_global_uncertainty_and_supported_kinds_without_cross_session_ids(self):
        app=create_app(self.fx.fx.frames.root,{'http://testserver'},synthetic=True,
            recognition_config=DispatchConfig(replay={'reading':self.fx.response}))
        with closing(self.queue.store._connect()) as db:
            state=self.queue._load(db,self.fx.job.job_id);state.update(status='cancelled',worker_active=True)
            self.queue._save(db,state);db.commit()
        app.state.dispatcher.session_id='a'*32;app.state.dispatcher.selected='private-other-job';app.state.dispatcher.last_outcome='private-outcome'
        with TestClient(app) as client:
            response=client.get(self.url);self.assertEqual(response.status_code,200)
            data=response.json();self.assertEqual(data['session_id'],self.fx.job.session_id)
            self.assertEqual(data['supported_kinds'],['reading']);self.assertTrue(data['worker_busy'])
            self.assertIsNone(data['job_id']);self.assertIsNone(data['last_outcome'])
            self.assertEqual(client.get(self.url).json(),data)
        self.assertTrue(self.queue.get(self.fx.job.job_id)['worker_active'])

if __name__=='__main__':unittest.main()
