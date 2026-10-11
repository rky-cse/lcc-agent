import json
import subprocess
import sys
import threading
import unittest
from contextlib import closing
from unittest.mock import patch
from library_claim.recognition_jobs import RecognitionQueue
from library_claim.spine_reading import export_reading
from library_claim.spine_detection import DetectionResponse
from tests import test_recognition_jobs as reading_fixture
from tests import test_detection_jobs as detection_fixture


class SelectedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.fx=reading_fixture.RecognitionTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.queue=self.fx.queue;self.first=self.fx.job
        self.second=self.first.model_copy(update={'job_id':'chosen-second'})
        self.queue.enqueue(self.first);self.queue.enqueue(self.second)

    def run_selected(self,job=None):
        return self.queue.run_job((job or self.second).job_id,response=self.fx.response)

    def test_selected_non_fifo_reading_does_not_touch_first_or_inventory(self):
        result=self.run_selected();self.assertEqual(result['input']['job_id'],self.second.job_id)
        self.assertEqual(result['status'],'completed');self.assertFalse(result['worker_active'])
        self.assertEqual(self.queue.get(self.first.job_id)['status'],'queued')
        self.assertEqual(self.fx.inventory,self.fx.fx.guide.ledger.snapshot(self.first.session_id))

    def test_completed_selection_after_restart_never_calls_provider(self):
        result=self.run_selected();restarted=RecognitionQueue(self.fx.fx.frames)
        with patch('library_claim.recognition_jobs.export_reading') as call:
            self.assertEqual(restarted.run_job(self.second.job_id,key='fixture'),result);call.assert_not_called()
        self.assertEqual(self.queue.get(self.first.job_id)['status'],'queued')

    def test_unknown_selection_and_wrong_kind_do_not_fall_back(self):
        with self.assertRaises(KeyError):self.queue.run_job('missing',response=self.fx.response)
        with self.assertRaises(ValueError):self.queue.run_next(kind='detection',response=DetectionResponse(coverage='no_visible_books',objects=[],unresolved_regions=[]),job_id=self.second.job_id)
        self.assertTrue(all(s['status']=='queued' for s in self.queue.list()))

    def test_cancelled_selection_never_dispatches_another_job(self):
        result=self.queue.cancel(self.second.job_id)
        with patch('library_claim.recognition_jobs.export_reading') as call:
            self.assertEqual(self.run_selected(),result);call.assert_not_called()
        self.assertEqual(self.queue.get(self.first.job_id)['status'],'queued')

    def test_stale_selection_only_marks_selected_and_never_calls_provider(self):
        self.fx.change_inventory()
        with patch('library_claim.recognition_jobs.export_reading') as call:
            self.assertEqual(self.run_selected()['status'],'stale');call.assert_not_called()
        self.assertEqual(self.queue.get(self.first.job_id)['status'],'queued')

    def test_failed_selection_is_not_retried_or_replaced(self):
        with patch('library_claim.recognition_jobs.export_reading',side_effect=RuntimeError('SECRET')) as call:
            result=self.run_selected();self.assertEqual(result['status'],'failed');self.assertFalse(result['worker_active'])
            self.assertEqual(self.run_selected(),result);self.assertEqual(call.call_count,1)
        self.assertNotIn('SECRET',json.dumps(result));self.assertEqual(self.queue.get(self.first.job_id)['status'],'queued')

    def test_completed_stale_selection_returns_verified_history_without_execution(self):
        self.run_selected();self.fx.change_inventory()
        with patch('library_claim.recognition_jobs.export_reading') as call:
            self.assertEqual(self.run_selected()['status'],'stale');call.assert_not_called()
        (self.queue._directory(self.second.job_id)/'reading_result.json').write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'integrity'):self.run_selected()

    def test_cancelled_active_worker_blocks_concurrent_selected_and_fifo_dispatch(self):
        entered=threading.Event();release=threading.Event();results=[];failures=[]
        def execute(*args,**kwargs):
            entered.set()
            if not release.wait(10):raise RuntimeError('test worker timeout')
            return export_reading(*args,**kwargs)
        def work():
            try:results.append(self.run_selected())
            except BaseException as error:failures.append(error)
        with patch('library_claim.recognition_jobs.export_reading',side_effect=execute) as call:
            thread=threading.Thread(target=work);thread.start()
            try:
                self.assertTrue(entered.wait(5))
                cancelled=self.queue.cancel(self.second.job_id)
                self.assertTrue(cancelled['worker_active'])
                with self.assertRaisesRegex(ValueError,'worker busy'):self.run_selected(self.first)
                with self.assertRaisesRegex(ValueError,'worker busy'):self.queue.run_next(response=self.fx.response)
                self.assertEqual(call.call_count,1)
            finally:release.set();thread.join(15)
        self.assertFalse(thread.is_alive());self.assertEqual(failures,[])
        self.assertEqual(results[0]['status'],'cancelled');self.assertFalse(results[0]['worker_active'])
        self.assertEqual(self.run_selected(self.first)['status'],'completed')

    def test_uncertain_cancelled_attempt_requires_explicit_stopped_worker_recovery(self):
        def stop(*args,**kwargs):
            # Simulate a pre-M06c2g1 running record without the new activity field.
            with closing(self.queue.store._connect()) as db:
                state=self.queue._load(db,self.second.job_id);state.pop('worker_active')
                self.queue._save(db,state);db.commit()
            self.assertTrue(self.queue.cancel(self.second.job_id)['worker_active'])
            raise SystemExit('fixture worker stopped')
        with patch('library_claim.recognition_jobs.export_reading',side_effect=stop):
            with self.assertRaises(SystemExit):self.run_selected()
        restarted=RecognitionQueue(self.fx.fx.frames)
        with self.assertRaisesRegex(ValueError,'worker busy'):restarted.run_job(self.first.job_id,response=self.fx.response)
        closed=restarted.interrupt(self.second.job_id)
        self.assertEqual(closed['status'],'interrupted');self.assertFalse(closed['worker_active'])
        self.assertEqual(restarted.run_job(self.second.job_id,response=self.fx.response),closed)
        self.assertEqual(restarted.run_job(self.first.job_id,response=self.fx.response)['status'],'completed')

    def test_cli_rejects_conflicting_kind_or_missing_free_tier_confirmation(self):
        response=self.fx.fx.root/'response.json';response.write_text(self.fx.response.model_dump_json(),encoding='utf-8')
        prefix=[sys.executable,'-B','-m','library_claim.recognition_jobs','--store',str(self.fx.fx.frames.root)]
        for flags in [ ['--run-one','--job-id',self.second.job_id,'--kind','detection','--response',str(response)],
                       ['--run-one','--job-id',self.second.job_id,'--gemini'],
                       ['--run-one','--job-id','','--response',str(response)],
                       ['--list','--job-id',self.second.job_id] ]:
            result=subprocess.run(prefix+flags,capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
        self.assertTrue(all(s['status']=='queued' for s in self.queue.list()))


class SelectedDetectionTests(unittest.TestCase):
    def test_detection_kind_inferred_and_one_mock_provider_call_across_retries(self):
        fixture=detection_fixture.DetectionQueueTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.queue.enqueue(fixture.job)
        fixture.queue.enqueue(fixture.job.model_copy(update={'job_id':'chosen-detector'}))
        with patch('library_claim.recognition_jobs.request_detection',return_value=(fixture.response,None,None,None)) as call:
            result=fixture.queue.run_job('chosen-detector',key='not-a-real-key')
            self.assertEqual(result['status'],'completed');self.assertFalse(result['worker_active'])
            self.assertEqual(fixture.queue.run_job('chosen-detector',key='not-a-real-key'),result)
            self.assertEqual(call.call_count,1)
        self.assertEqual(fixture.queue.get(fixture.job.job_id)['status'],'queued')
        self.assertEqual(fixture.before,fixture.fx.guide.ledger.snapshot(fixture.job.session_id))

if __name__=='__main__':unittest.main()
