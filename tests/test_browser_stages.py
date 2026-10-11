import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from library_claim.browser_stages import BrowserStages,CatalogueLookup,IdentityReview,MeasurementRun
from library_claim.server import create_app
from library_claim.catalogue import CatalogueClient
from library_claim.tracking import digest
from library_claim.identity import IdentityCommand
from tests.test_catalogue import CatalogueTests,raw
from tests.test_planar_measurement import PlanarTests

class BrowserStageTests(unittest.TestCase):
    def setUp(self):
        self.f=CatalogueTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.frames=self.f.store;self.stages=BrowserStages(self.frames)

    def lookup(self):
        body=CatalogueLookup(run_id='a'*32,job_id='reading',request=self.f.request)
        job=dict(input=dict(session_id='fixture',kind='reading'),eligible_for_review=True)
        with patch.object(self.stages.jobs,'get',return_value=job),patch.object(self.stages.jobs,'_directory',return_value=self.f.reading),patch.object(CatalogueClient,'fetch',return_value=(raw(),None,{'requests':1,'cache_hit':False})):
            return body,self.stages.execute('fixture','catalogue',body)

    def test_browser_catalogue_can_accept_work_without_cli_or_client_paths(self):
        body,result=self.lookup();self.assertEqual(result['result']['outcome'],'supported_candidate')
        self.assertEqual(result['result_sha256'],digest((self.stages.path(body.run_id)/'catalogue_result.json').read_bytes()))
        observation=self.f.f.fixture.ledger.snapshot('fixture')['observations'][0]
        command=IdentityCommand(command_id='browser-accept',sweep_id='fixture',expected_revision=1,track_id=observation['track_id'],action='accept_work',catalogue_result_sha256=result['result_sha256'],work_id='/works/OL1W',confirmed_span_ids=self.f.request.title_span_ids+self.f.request.author_span_ids,metadata=[],needs_appraisal=False,reviewer='Fixture reviewer',reason='Checked synthetic lettering')
        accepted=self.stages.identity('fixture',IdentityReview(bundle_id=body.run_id,command=command))
        self.assertEqual(next(b for b in accepted['books'] if b['id']==observation['track_id'])['title'],'RIVER ATLAS')
        with patch.object(CatalogueClient,'fetch',side_effect=AssertionError('retry must not fetch')):
            self.assertEqual(self.stages.execute('fixture','catalogue',body),result)

    def test_cross_sweep_tampering_and_id_conflict_rejected(self):
        body,result=self.lookup()
        with self.assertRaises(KeyError):self.stages.get('other',body.run_id)
        with self.assertRaises(ValueError):self.stages.execute('fixture','edition',body)
        (self.stages.path(body.run_id)/'crop.png').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'integrity'):self.stages.get('fixture',body.run_id)

    def test_workspace_routes_assets_and_run_discovery(self):
        app=create_app(self.frames.root,{'http://testserver'})
        with TestClient(app) as client:
            for path in ['/','/sweep','/assets/workspace.mjs','/assets/workspace_core.mjs','/assets/sweep.mjs','/assets/sweep_core.mjs','/assets/identity.mjs','/assets/geometry.mjs','/api/ui/voice','/api/ui/geometry']:
                self.assertEqual(client.get(path).status_code,200,path)
            self.assertNotIn('<iframe',client.get('/').text)
            self.assertEqual(client.get('/api/ui/private').status_code,404)
            self.assertEqual(client.get('/api/sweeps/fixture/runs').json(),{'books':[],'items':[],'areas':[],'packets':[]})

    def test_failed_stage_does_not_publish_and_retries_do_not_repeat_network(self):
        body=CatalogueLookup(run_id='b'*32,job_id='missing',request=self.f.request)
        with self.assertRaises(KeyError):self.stages.execute('fixture','catalogue',body)
        self.assertEqual(self.stages.get('fixture',body.run_id)['status'],'failed')
        self.assertEqual(self.stages.execute('fixture','catalogue',body)['status'],'failed')

class BrowserMeasurementTests(unittest.TestCase):
    def test_saved_measurement_retains_exact_input_for_final_packet(self):
        f=PlanarTests();f.setUp();self.addCleanup(f.doCleanups)
        body=MeasurementRun(run_id='c'*32,request=f.request)
        stages=BrowserStages(f.store);result=stages.execute(f.record.sweep_id,'measurement',body)
        self.assertEqual(result['input']['request'],json.loads(body.request.model_dump_json()))
        self.assertTrue(result['result']['results'])
