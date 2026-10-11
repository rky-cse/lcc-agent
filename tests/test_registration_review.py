import unittest
import json
from contextlib import closing
from unittest.mock import patch
from fastapi.testclient import TestClient
from library_claim.registration_review import RegistrationReviewer,RegistrationReview
from library_claim.recognition_jobs import RecognitionQueue,DetectionJob
from library_claim.spine_detection import DetectionRequest,DetectionResponse
from library_claim.capture_store import CaptureInput
from library_claim.tracking import TrackingCommand
from library_claim.server import create_app
from tests import test_guidance as fixture
from tests.test_spine_detection import proposal

class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.GuidanceTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.fx.bind();self.before,self.frame=self.fx.tracks()
        self.queue=RecognitionQueue(self.fx.frames);self.reviewer=RegistrationReviewer(self.queue)
        self.job=DetectionJob(kind='detection',job_id='registration-job',session_id=fixture.SESSION,expected_inventory_revision=1,
            expected_reference_revision=self.fx.guide.snapshot(fixture.SESSION)['reference_revision'],
            request=DetectionRequest(sweep_id=fixture.SESSION,frame_ref=self.frame.id,frame_sha256=self.frame.sha256,shelf_id='new-shelf',shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5)))
    def complete(self,job=None,objects=None):
        self.job=job or self.job;self.queue.enqueue(self.job)
        self.queue.run_next(kind='detection',response=DetectionResponse(coverage='clear',objects=objects or [proposal(),proposal((300,100,400,800))],unresolved_regions=[]))
        return self.reviewer.snapshot(fixture.SESSION,self.job.job_id)
    def review(self,actions=None):
        data=self.reviewer.snapshot(fixture.SESSION,self.job.job_id);actions=actions or [('new',None)]*len(data['candidates'])
        return RegistrationReview(review_id='explicit-review',session_id=fixture.SESSION,job_id=self.job.job_id,expected_inventory_revision=1,expected_reference_revision=self.job.expected_reference_revision,
            reviewer='Synthetic reviewer',reason='Reviewed saved physical rectangles',decisions=[dict(observation_id=c['observation_id'],action=a,track_id=t,provenance='Explicit physical fixture comparison') for c,(a,t) in zip(data['candidates'],actions)])
    def test_no_mutation_on_get_then_explicit_new_and_unresolved(self):
        self.complete();self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION),self.before)
        result=self.reviewer.apply(self.review([('new',None),('unresolved',None)]))
        self.assertTrue(result['applied']);self.assertEqual(result['ledger_event_revision'],2)
        self.assertEqual(result['inventory']['assigned_track_count'],3);self.assertEqual(len(result['inventory']['review_queue']),1)
        self.assertEqual(result['job']['status'],'stale');self.assertFalse(self.reviewer.snapshot(fixture.SESSION,self.job.job_id)['can_register'])
    def test_exact_retry_and_restart_no_extra_revision(self):
        self.complete();review=self.review();first=self.reviewer.apply(review)
        restarted=RegistrationReviewer(RecognitionQueue(self.fx.frames));self.assertEqual(restarted.apply(review),first)
        with self.assertRaises(ValueError):restarted.apply(review.model_copy(update={'reason':'Changed review'}))
    def test_ack_failure_after_commit_recovers_from_event(self):
        self.complete();review=self.review()
        with patch.object(self.reviewer.ledger,'_snapshot',side_effect=OSError('Lost acknowledgment')):
            with self.assertRaises(OSError):self.reviewer.apply(review)
        self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION)['revision'],2)
        self.assertEqual(self.reviewer.apply(review)['ledger_event_revision'],2)
    def test_each_candidate_required_and_invalid_target_rolls_back(self):
        self.complete();review=self.review()
        for decisions in [review.decisions[:1],[review.decisions[0],review.decisions[0]],
            [review.decisions[0].model_copy(update={'action':'same','track_id':'missing'}),review.decisions[1]]]:
            with self.assertRaises(ValueError):self.reviewer.apply(review.model_copy(update={'decisions':decisions}))
        self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION),self.before)
    def test_same_revisit_preserves_counts_and_ownership(self):
        newframe=self.fx.frames.save(CaptureInput(sweep_id=fixture.SESSION,upload_id='revisit',captured_at=self.frame.captured_at,media_sequence=1,source='file_import',synthetic=True),self.fx.frames.read(self.frame.id))
        job=self.job.model_copy(update={'request':self.job.request.model_copy(update={'frame_ref':newframe.id,'frame_sha256':newframe.sha256,'shelf_id':'shelf'})})
        self.complete(job);targets=[b['id'] for b in self.before['books']];result=self.reviewer.apply(self.review([('same',targets[0]),('same',targets[1])]))
        self.assertEqual(result['inventory']['assigned_track_count'],2);self.assertTrue(all(b['owned'] for b in result['inventory']['books']))
        self.assertEqual(len(result['inventory']['observations']),4)
    def test_two_detections_cannot_merge_one_existing_copy(self):
        newframe=self.fx.frames.save(CaptureInput(sweep_id=fixture.SESSION,upload_id='revisit',captured_at=self.frame.captured_at,media_sequence=1,source='file_import',synthetic=True),self.fx.frames.read(self.frame.id))
        self.complete(self.job.model_copy(update={'request':self.job.request.model_copy(update={'frame_ref':newframe.id,'frame_sha256':newframe.sha256,'shelf_id':'shelf'})}))
        target=self.before['books'][0]['id']
        with self.assertRaises(ValueError):self.reviewer.apply(self.review([('same',target),('same',target)]))
        self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION),self.before)
    def test_reference_change_between_precheck_and_atomic_guard(self):
        self.complete();review=self.review();apply=self.reviewer.ledger.apply
        def racing(*args,**kwargs):self.fx.apply(self.fx.reference());return apply(*args,**kwargs)
        with patch.object(self.reviewer.ledger,'apply',side_effect=racing):
            with self.assertRaises(ValueError):self.reviewer.apply(review)
        self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION),self.before)
    def test_inventory_change_stale_job_rejected(self):
        self.complete();review=self.review()
        self.fx.guide.ledger.apply(TrackingCommand(command_id='borrowed',sweep_id=fixture.SESSION,expected_revision=1,operation='ownership',track_id=self.before['books'][0]['id'],owned=False,detection_result_sha256=None,decisions=[],provenance='Explicit fixture ownership'))
        with self.assertRaises(ValueError):self.reviewer.apply(review)
        self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION)['revision'],2)
    def test_wrong_pins_and_blank_review_rejected(self):
        self.complete();review=self.review()
        with self.assertRaises(ValueError):self.reviewer.apply(review.model_copy(update={'expected_reference_revision':99}))
        with self.assertRaises(ValueError):RegistrationReview.model_validate(review.model_dump()|{'reviewer':' '})
    def test_corrupt_bundle_rejected_without_mutation(self):
        self.complete();review=self.review();(self.queue._directory(self.job.job_id)/'detector_response.json').write_text('{}')
        with self.assertRaises(ValueError):self.reviewer.apply(review)
        self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION),self.before)
    def test_tampered_event_cannot_display_verified_receipt(self):
        self.complete();self.reviewer.apply(self.review())
        with closing(self.fx.frames._connect()) as db:
            state=self.reviewer.ledger._read(db,fixture.SESSION);state['events'][-1]['command']['provenance']='Tampered review'
            db.execute('UPDATE physical_inventory SET state=? WHERE sweep_id=?',(json.dumps(state),fixture.SESSION));db.commit()
        with self.assertRaisesRegex(ValueError,'event integrity'):self.reviewer.snapshot(fixture.SESSION,self.job.job_id)
    def test_http_scope_bounds_and_verified_receipt(self):
        self.complete();review=self.review();app=create_app(self.fx.frames.root,{'http://testserver'});url=f'/api/guidance/{fixture.SESSION}/registration/{self.job.job_id}'
        with TestClient(app) as client:
            self.assertEqual(client.get(url).status_code,200);body=review.model_dump(mode='json');headers={'Origin':'http://testserver'}
            self.assertEqual(client.post(url,json=body).status_code,403)
            self.assertEqual(client.post(url,json=body|{'job_id':'other'},headers=headers).status_code,422)
            self.assertEqual(client.post(url,content='x'*(600*1024+1),headers=headers).status_code,413)
            self.assertEqual(client.get('/api/guidance/'+'a'*32+'/registration/'+self.job.job_id).status_code,404)
            first=client.post(url,json=body,headers=headers);self.assertEqual(first.status_code,200);self.assertTrue(first.json()['applied'])
            self.assertEqual(client.post(url,json=body,headers=headers).json(),first.json())
            self.assertEqual(client.get('/registration').status_code,200)
    def test_unavailable_job_cannot_import_even_empty_decisions(self):
        self.queue.enqueue(self.job)
        with patch('library_claim.recognition_jobs.request_detection',return_value=(None,dict(code='quota',reason='Fixture unavailable',retryable=True),None,None)):
            self.queue.run_next(kind='detection',key='fixture')
        review=self.review();self.assertEqual(review.decisions,[])
        with self.assertRaises(ValueError):self.reviewer.apply(review)

if __name__=='__main__':unittest.main()
