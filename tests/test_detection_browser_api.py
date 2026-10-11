import unittest
from fastapi.testclient import TestClient
from library_claim.server import create_app
from library_claim.capture_store import CaptureInput
from tests import test_guidance as fixture

class DetectionEvidencePageTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.GuidanceTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.fx.bind();self.before,self.frame=self.fx.tracks()
        self.client=TestClient(create_app(self.fx.frames.root,{'http://testserver'}));self.addCleanup(self.client.close)
        self.url=f'/api/guidance/{fixture.SESSION}/recognition'
    def test_frame_metadata_pins_original_without_registered_observation_dependency(self):
        data=self.client.get(self.url).json();self.assertEqual(data['total_frames'],1)
        self.assertEqual(data['frames'][0],dict(id=self.frame.id,sha256=self.frame.sha256,width=1600,height=900,exif_orientation=None,synthetic=True))
        self.assertEqual(data['inventory_revision'],1);self.assertEqual(data['jobs'],[])
        other=fixture.GuidanceTests();other.setUp();self.addCleanup(other.doCleanups);other.bind()
        saved=other.frames.save(CaptureInput(sweep_id=fixture.SESSION,upload_id='standalone',captured_at=self.frame.captured_at,
            media_sequence=0,source='file_import',synthetic=True),self.fx.frames.read(self.frame.id))
        with TestClient(create_app(other.frames.root,{'http://testserver'})) as client:
            empty=client.get(self.url).json();self.assertEqual(empty['observations'],[]);self.assertEqual(empty['inventory_revision'],0)
            self.assertEqual(empty['frames'][0]['id'],saved.id)
    def test_frame_paging_and_bounds(self):
        data=self.client.get(self.url+'?frame_offset=1&frame_limit=1').json();self.assertEqual(data['frames'],[]);self.assertEqual(data['total_frames'],1)
        for query in ('frame_offset=-1','frame_limit=0','frame_limit=101'):self.assertEqual(self.client.get(self.url+'?'+query).status_code,422)
    def test_selector_page_assets_no_worker(self):
        page=self.client.get('/recognition');self.assertIn('Queue shelf detection',page.text)
        self.assertEqual(self.client.get('/assets/shelf_selector.mjs').status_code,200)
        self.assertEqual(self.client.get('/api/health').json()['recognition_worker'],'explicit_cli')
        self.assertEqual(self.fx.guide.ledger.snapshot(fixture.SESSION),self.before)

if __name__=='__main__':unittest.main()
