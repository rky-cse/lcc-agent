import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from library_claim.recognition_jobs import RecognitionQueue,DetectionJob,parse_job
from library_claim.spine_detection import DetectionRequest,DetectionResponse
from library_claim.spine_reading import ReadingResponse
from library_claim.server import create_app
from library_claim.tracking import TrackingCommand
from tests import test_guidance as fixture
from tests.test_spine_detection import proposal

class DetectionQueueTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.GuidanceTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.bind();self.before,self.frame=self.fx.tracks();self.queue=RecognitionQueue(self.fx.frames)
        self.job=DetectionJob(kind='detection',job_id='detector-1',session_id=fixture.SESSION,expected_reference_revision=self.fx.guide.snapshot(fixture.SESSION)['reference_revision'],
            expected_inventory_revision=1,request=DetectionRequest(sweep_id=fixture.SESSION,frame_ref=self.frame.id,frame_sha256=self.frame.sha256,
                shelf_id='explicit-shelf',shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5)))
        self.response=DetectionResponse(coverage='clear',objects=[proposal()],unresolved_regions=[])
    def work(self,**kwargs):return self.queue.run_next(kind='detection',response=self.response,**kwargs)
    def correction(self):
        self.fx.guide.ledger.apply(TrackingCommand(command_id='borrowed',sweep_id=fixture.SESSION,expected_revision=1,operation='ownership',
            track_id=self.before['books'][0]['id'],owned=False,detection_result_sha256=None,decisions=[],provenance='Fixture explicit correction'))
    def test_completed_detection_is_not_registered_and_has_pinned_stage(self):
        self.queue.enqueue(self.job);result=self.work();self.assertEqual(result['status'],'completed')
        self.assertTrue(result['eligible_for_review']);self.assertEqual(self.before,self.fx.guide.ledger.snapshot(fixture.SESSION))
        directory=self.queue._directory(self.job.job_id);stage=json.loads((directory/'queue_stage.json').read_text())
        self.assertEqual(stage['stage_result']['input_revision'],1);self.assertEqual(stage['stage_result']['job_id'],self.job.job_id)
        self.assertEqual(json.loads((directory/'detection_result.json').read_text())['stage_result']['input_revision'],0)
        self.assertEqual(result,RecognitionQueue(self.fx.frames).get(self.job.job_id))
    def test_retry_conflict_and_cross_kind_namespace(self):
        queued=self.queue.enqueue(self.job);self.assertEqual(self.queue.enqueue(self.job),queued)
        with self.assertRaises(ValueError):self.queue.enqueue(self.job.model_copy(update={'expected_inventory_revision':2}))
        payload=self.job.model_dump();payload['kind']='unknown'
        with self.assertRaises(ValueError):parse_job(payload)
    def test_default_reader_does_not_claim_detector(self):
        self.queue.enqueue(self.job)
        self.assertIsNone(self.queue.run_next(response=ReadingResponse(legibility='unreadable',spans=[],uncertainty='Fixture')))
        self.assertEqual(self.queue.get(self.job.job_id)['status'],'queued')
    def test_explicit_policy_region_hash_and_shelf_required(self):
        for update in [dict(shelf_region_px=(0,0,1700,900)),dict(frame_sha256='0'*64),dict(sweep_id='other')]:
            with self.assertRaises(ValueError):self.queue.enqueue(self.job.model_copy(update={'request':self.job.request.model_copy(update=update)}))
        for field in ('shelf_region_px','policy','shelf_id'):
            payload=self.job.model_dump();del payload['request'][field]
            with self.assertRaises(ValueError):parse_job(payload)
        payload=self.job.model_dump();payload['request']['shelf_id']=' '
        with self.assertRaises(ValueError):parse_job(payload)
    def test_stale_before_call_and_after_publication(self):
        self.queue.enqueue(self.job);self.correction()
        with patch('library_claim.recognition_jobs.request_detection') as call:
            self.assertEqual(self.queue.run_next(kind='detection',key='fixture')['status'],'stale');call.assert_not_called()
    def test_live_late_inventory_correction_no_export(self):
        self.queue.enqueue(self.job)
        def provider(*args):self.correction();return self.response,None,None,None
        with patch('library_claim.recognition_jobs.request_detection',side_effect=provider):
            result=self.queue.run_next(kind='detection',key='fixture')
        self.assertEqual(result['status'],'stale');self.assertEqual(result['artifacts'],{})
        self.assertFalse(self.queue._directory(self.job.job_id).exists())
    def test_reference_change_and_completed_invalidation(self):
        self.queue.enqueue(self.job);self.work();self.fx.apply(self.fx.reference())
        self.assertEqual(self.queue.get(self.job.job_id)['status'],'stale')
    def test_unavailable_is_unknown_count_not_zero(self):
        self.queue.enqueue(self.job)
        failure=dict(code='quota',reason='Fixture quota unavailable',retryable=True)
        with patch('library_claim.recognition_jobs.request_detection',return_value=(None,failure,None,None)):
            result=self.queue.run_next(kind='detection',key='fixture')
        self.assertEqual(result['result_status'],'unavailable')
        directory=self.queue._directory(self.job.job_id)
        self.assertIsNone(json.loads((directory/'detection_result.json').read_text())['provisional_shelf_count'])
        self.assertEqual(json.loads((directory/'queue_stage.json').read_text())['stage_result']['errors'][0]['code'],'quota')
        self.assertIsNone(self.work())
    def test_invalid_live_geometry_stays_in_partial_review(self):
        self.queue.enqueue(self.job)
        invalid=DetectionResponse(coverage='clear',objects=[dict(proposal(),polygon_1000=[(0,0),(100,100),(0,100),(100,0)])],unresolved_regions=[])
        with patch('library_claim.recognition_jobs.request_detection',return_value=(invalid,None,None,None)):
            result=self.queue.run_next(kind='detection',key='fixture')
        self.assertEqual(result['result_status'],'partial')
        detection=json.loads((self.queue._directory(self.job.job_id)/'detection_result.json').read_text())
        self.assertTrue(detection['review_queue']);self.assertIsNone(detection['provisional_shelf_count'])
    def test_interruption_and_cancel_no_provider_retry(self):
        self.queue.enqueue(self.job)
        with patch('library_claim.recognition_jobs.request_detection',side_effect=SystemExit):
            with self.assertRaises(SystemExit):self.queue.run_next(kind='detection',key='fixture')
        with self.assertRaises(ValueError):self.work()
        self.queue.interrupt(self.job.job_id);self.assertIsNone(self.work())
        second=self.job.model_copy(update={'job_id':'second'});self.queue.enqueue(second);self.queue.cancel('second');self.assertIsNone(self.work())
    def test_artifact_corruption_and_existing_output_zero_calls(self):
        self.queue.enqueue(self.job);self.queue._directory(self.job.job_id).mkdir(parents=True)
        with patch('library_claim.recognition_jobs.request_detection') as call:
            self.assertEqual(self.queue.run_next(kind='detection',key='fixture')['status'],'failed');call.assert_not_called()
    def test_http_enrollment_artifact_scope_cancel_and_bounds(self):
        app=create_app(self.fx.frames.root,{'http://testserver'});url=f'/api/guidance/{fixture.SESSION}/recognition'
        with TestClient(app) as client:
            headers={'Origin':'http://testserver'};body=self.job.model_dump(mode='json')
            self.assertEqual(client.post(url+'/detection',json=body).status_code,403)
            self.assertEqual(client.post(url+'/detection',json=body,headers=headers).status_code,200)
            self.work();self.assertEqual(client.get(url+'/detector-1/detection_result.json').status_code,200)
            self.assertEqual(client.get(url+'/detector-1/queue_stage.json').status_code,200)
            self.assertEqual(client.get('/api/guidance/'+'a'*32+'/recognition/detector-1/queue_stage.json').status_code,404)
            self.assertEqual(client.get(url+'/detector-1/provider_response.json').status_code,404)
            (self.queue._directory(self.job.job_id)/'queue_stage.json').write_text('{}')
            self.assertEqual(client.get(url+'/detector-1/detection_result.json').status_code,409)

if __name__=='__main__':unittest.main()
