import unittest
from fastapi.testclient import TestClient
from library_claim.server import create_app
from library_claim.recognition_jobs import ReadingJob
from library_claim.spine_reading import ReadingRequest,ReadingResponse
from tests import test_guidance as fixture

class ReadingHttpTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.GuidanceTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.bind();self.inventory,self.frame=self.fx.tracks()
        self.app=create_app(self.fx.frames.root,{'http://testserver'},synthetic=True)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url=f'/api/guidance/{fixture.SESSION}/recognition'
        self.job=ReadingJob(job_id='browser-job',session_id=fixture.SESSION,expected_reference_revision=self.fx.guide.snapshot(fixture.SESSION)['reference_revision'],
            request=ReadingRequest(sweep_id=fixture.SESSION,expected_revision=1,observation_id=self.inventory['observations'][0]['id'],frame_sha256=self.frame.sha256))
    def post(self,path=None,body=None):
        return self.client.post(path or self.url,json=body or self.job.model_dump(mode='json'),headers={'Origin':'http://testserver'})
    def test_read_enroll_retry_restart_no_worker(self):
        data=self.client.get(self.url).json();self.assertEqual(len(data['observations']),2);self.assertEqual(data['jobs'],[])
        first=self.post();self.assertEqual(first.status_code,200);self.assertEqual(first.json()['status'],'queued')
        self.assertEqual(self.post().json(),first.json());self.assertEqual(self.client.get(self.url).json()['jobs'],[first.json()])
        with TestClient(create_app(self.fx.frames.root,{'http://testserver'})) as restarted:
            self.assertEqual(restarted.get(self.url).json()['jobs'],[first.json()])
        self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION),self.inventory)
    def test_boundaries(self):
        self.assertEqual(self.client.post(self.url,json=self.job.model_dump(mode='json')).status_code,403)
        self.assertEqual(self.client.get(self.url,headers={'Host':'evil'}).status_code,403)
        self.assertEqual(self.client.post(self.url,content='x'*4097,headers={'Origin':'http://testserver'}).status_code,413)
        self.assertEqual(self.post(body={'extra':True}).status_code,422)
        self.assertEqual(self.post(path='/api/guidance/'+'a'*32+'/recognition').status_code,422)
        self.assertEqual(self.client.get(self.url+'?limit=101').status_code,422)
        self.assertEqual(self.client.get(self.url+'?offset=-1').status_code,422)
        self.assertEqual(self.client.get('/api/guidance/'+'a'*32+'/recognition').status_code,404)
    def test_stale_and_wrong_hash_enrollment(self):
        for update in [{'expected_revision':0},{'frame_sha256':'0'*64}]:
            body=self.job.model_dump(mode='json');body['request'].update(update)
            self.assertEqual(self.post(body=body).status_code,409)
        self.assertEqual(self.client.get(self.url).json()['jobs'],[])
    def test_cancel_and_session_guard(self):
        self.post();other='/api/guidance/'+'a'*32+'/recognition'
        self.assertEqual(self.post(other+'/cancel',{'job_id':self.job.job_id}).status_code,404)
        self.assertEqual(self.post(self.url+'/cancel',{'job_id':self.job.job_id}).json()['status'],'cancelled')
        self.assertIsNone(self.app.state.recognition.run_next(response=ReadingResponse(legibility='unreadable',spans=[],uncertainty='Fixture')))
    def test_results_only_published_and_integrity_checked(self):
        self.post();path=self.url+'/'+self.job.job_id
        self.assertEqual(self.client.get(path+'/reading_result.json').status_code,409)
        self.app.state.recognition.run_next(response=ReadingResponse(legibility='unreadable',spans=[],uncertainty='Fixture'))
        response=self.client.get(path+'/reading_result.json');self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['transcription_verified']);self.assertEqual(self.client.get(path+'/crop.png').headers['content-type'],'image/png')
        self.assertEqual(self.client.get(path+'/report.html').status_code,404)
        self.assertEqual(self.client.get('/api/guidance/'+'a'*32+'/recognition/'+self.job.job_id+'/crop.png').status_code,404)
        (self.app.state.recognition._directory(self.job.job_id)/'crop.png').write_bytes(b'tampered')
        self.assertEqual(self.client.get(path+'/reading_result.json').status_code,409)
    def test_page_assets_and_health(self):
        self.assertEqual(self.client.get('/recognition').status_code,200)
        self.assertEqual(self.client.get('/assets/recognition.mjs').status_code,200)
        self.assertEqual(self.client.get('/api/health').json()['recognition_worker'],'explicit_cli')

if __name__=='__main__':unittest.main()
