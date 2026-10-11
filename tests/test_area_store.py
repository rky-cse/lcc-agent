import copy
import json
import shutil
import unittest
from contextlib import closing
from unittest.mock import patch

from fastapi.testclient import TestClient
from library_claim.area_store import AreaStore
from library_claim.areas import AreaRequest
from library_claim.contents import ContentsCommand
from library_claim.server import create_app
from tests import test_room_measurement as upstream
from tests import test_areas as geometry_fixture


class AreaStoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture=upstream.RoomBoundaryTests('test_model_tampering_fails');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store=AreaStore(self.fixture.store)
        inside=self.fixture.store.root/'models'/'fixture';inside.parent.mkdir(parents=True)
        shutil.copytree(self.fixture.reconstruction,inside)
        _,_,request=geometry_fixture.scene()
        data=request.model_dump();data['points']=self.fixture.request.model_dump()['points']
        data['reconstruction_result_sha256']=self.fixture.request.reconstruction_result_sha256
        self.request=AreaRequest.model_validate(data);self.views=self.fixture.views;self.model=inside

    def run_area(self):
        with patch('library_claim.area_store.calibrated_views',return_value=self.views):return self.store.run(self.request)

    def observe(self,category='chair',key='chair'):
        f=self.fixture.records[0]
        cmd=ContentsCommand.model_validate(dict(command_id='observe-'+key,sweep_id='fixture',expected_revision=self.store.contents.snapshot('fixture')['revision'],operation='observe',item_id=key,
            reviewer='Synthetic reviewer',reason='Synthetic physical object review',frame_ref=f.id,frame_sha256=f.sha256,bounds_px=[100,20,1800,1050],new_owned=True,
            labels=[dict(field='category',value=category,basis='visible_appearance',statement='Synthetic visible category')]))
        return self.store.contents.apply(cmd)

    def test_durable_result_replay_and_measurement_evidence(self):
        first=self.run_area();restored=AreaStore(self.fixture.store).get(self.request.run_id,'fixture')
        self.assertEqual(first,restored);self.assertEqual(restored['status'],'success');self.assertFalse(first['packet_ready'])
        self.assertEqual(len(first['measurements']),6);self.assertEqual(first['room']['floor_area_m2'],12)
        with patch('library_claim.area_store.calibrated_views',side_effect=AssertionError('retry recomputed')):
            self.assertEqual(self.store.run(self.request),first)

    def test_changed_payload_and_wrong_sweep_fail(self):
        self.run_area()
        self.request.openings_complete=False
        with self.assertRaisesRegex(ValueError,'different payload'):self.store.run(self.request)
        with self.assertRaises(KeyError):self.store.get('area-one','another')

    def test_contents_changes_mark_stale(self):
        self.run_area();self.observe();result=self.store.get('area-one')
        self.assertTrue(result['stale']);self.assertFalse(result['usable_for_current_inventory'])
        self.request.run_id='second'
        with self.assertRaisesRegex(ValueError,'stale contents'):self.store.run(self.request)

    def test_results_and_model_tampering_fail(self):
        self.run_area()
        with closing(self.fixture.store._connect()) as db:
            db.execute('UPDATE area_runs SET result=? WHERE id=?',(b'{}','area-one'));db.commit()
        with self.assertRaisesRegex(ValueError,'result hash'):self.store.get('area-one')

    def test_native_artifact_tampering_detected_on_reopen(self):
        self.run_area();(self.model/'sparse'/'0'/'images.bin').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'model hash'):self.store.get('area-one')

    def test_invalid_geometry_saved_as_unknown(self):
        self.request.anchor.independently_verified=False
        result=self.run_area();self.assertEqual(result['status'],'unavailable');self.assertIsNone(result['room']['floor_area_m2']);self.assertEqual(result['measurements'],[])

    def test_partial_wall_output_is_not_full_total(self):
        self.request.walls.pop();result=self.run_area()
        self.assertEqual(result['status'],'partial');self.assertIsNone(result['room']['wall_area_m2']);self.assertIsNotNone(result['room']['floor_area_m2'])

    def test_store_path_traversal_and_absolute_rejected(self):
        for name in ['../model',str(self.fixture.reconstruction)]:
            self.request.reconstruction_path=name
            with self.assertRaisesRegex(ValueError,'relative inside'):self.store.run(self.request)

    def test_omitted_physical_shelving_rejected(self):
        self.observe('shelving_unit','shelf');self.request.expected_contents_revision=1
        with self.assertRaisesRegex(ValueError,'omits reviewed'):self.store.run(self.request)
        self.request.shelving_coverage_complete=False
        self.assertIsNone(self.run_area()['room']['shelved_wall_area_m2'])

    def test_surface_missing_physical_item_rejected(self):
        # Bind a geometrically valid surface to an absent physical identity.
        data=self.request.model_dump();data['shelves']=[dict(id='face',wall_index=0,corners=['f0','f1','t1','t0'],item_id='absent',provenance='Synthetic visible face')]
        with self.assertRaisesRegex(ValueError,'current reviewed'):self.store.run(AreaRequest.model_validate(data))

    def test_shelf_corner_identity_bounds_are_required(self):
        self.observe('shelving_unit','shelf');self.request.expected_contents_revision=1
        data=self.request.model_dump();data['shelves']=[dict(id='face',wall_index=0,corners=['f0','f1','t1','t0'],item_id='shelf',provenance='Synthetic visible face')]
        # One frame ties all corners to the reviewed item's visible bounds.
        request=AreaRequest.model_validate(data)
        inventory=self.store.contents.snapshot('fixture');self.store.validate_shelves(request,inventory)
        inventory['rows'][0]['observations'][0]['bounds_px']=[1,1,2,2]
        with self.assertRaisesRegex(ValueError,'observation bounds'):self.store.validate_shelves(request,inventory)

    def test_http_page_assets_scope_and_origin(self):
        # Saved result reads do not invoke native geometry or a provider.
        self.run_area();app=create_app(self.fixture.store.root,{'http://testserver'})
        with TestClient(app) as client:
            for url in ['/areas','/api/areas/schema','/assets/areas.mjs','/assets/areas_core.mjs']:self.assertEqual(client.get(url).status_code,200)
            self.assertIn('interpretation',client.get('/api/areas/schema').json()['required'])
            # Capture-session lookup must exist for sweep-scoped operations.
            with patch.object(app.state.sessions,'snapshot',return_value={'sweep_id':'fixture'}):
                value=client.get('/api/sweeps/fixture/areas/area-one');self.assertEqual(value.status_code,200)
                self.assertEqual(client.get('/api/sweeps/other/areas/area-one').status_code,404)
                self.assertEqual(client.post('/api/sweeps/fixture/areas',json=self.request.model_dump(mode='json')).status_code,403)
                self.assertEqual(client.post('/api/sweeps/other/areas',json=self.request.model_dump(mode='json'),headers={'Origin':'http://testserver'}).status_code,422)
                replay=client.post('/api/sweeps/fixture/areas',json=self.request.model_dump(mode='json'),headers={'Origin':'http://testserver'})
                self.assertEqual(replay.status_code,200);self.assertEqual(replay.json()['result_sha256'],value.json()['result_sha256'])


if __name__=='__main__':unittest.main()
