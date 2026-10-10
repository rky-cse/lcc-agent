import unittest
from fastapi.testclient import TestClient
from library_claim.server import create_app
from library_claim.spine_detection import DetectionRequest,DetectionResponse,export_detection
from library_claim.tracking import TrackStore,TrackingCommand,digest
from tests import test_capture_server as server_fixture
from tests import test_spine_detection as detection_fixture


class InventoryServerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=server_fixture.ServerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.client
        self.path=f'/api/sweeps/{self.fixture.sweep["id"]}/inventory'

    def import_rows(self):
        frame=self.fixture.upload().json()["frame"]
        request=DetectionRequest(sweep_id=self.fixture.sweep["id"],frame_ref=frame["id"],frame_sha256=frame["sha256"],
            shelf_id="shelf",shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
        bundle=self.fixture.root/"detection"
        result=export_detection(self.fixture.app.state.sessions.store,request,bundle,DetectionResponse(coverage="clear",
            objects=[detection_fixture.proposal(),detection_fixture.proposal((300,100,400,800))],unresolved_regions=[]))
        command=TrackingCommand(command_id="import",sweep_id=request.sweep_id,expected_revision=0,operation="import",
            detection_result_sha256=digest((bundle/"detection_result.json").read_bytes()),track_id=None,owned=None,provenance="fixture review",
            decisions=[dict(observation_id=b["id"],action="new" if i==0 else "unresolved",track_id=None,provenance="fixture labels") for i,b in enumerate(result["books"])])
        ledger=TrackStore(self.fixture.app.state.sessions.store)
        return ledger,ledger.apply(command,bundle)

    def test_empty_inventory_is_unknown_and_capture_is_independent(self):
        data=self.client.get(self.path).json()
        self.assertEqual(data["revision"],0)
        self.assertEqual(data["detection_import_count"],0)
        self.assertIsNone(data["total_book_count"])
        self.assertEqual(data["rows"],[])
        self.assertEqual(self.fixture.upload().status_code,200)

    def test_unknown_sweep_bounds_host_and_assets(self):
        self.assertEqual(self.client.get('/api/sweeps/missing/inventory').status_code,404)
        for query in ['?offset=-1','?limit=0','?limit=101']:
            self.assertEqual(self.client.get(self.path+query).status_code,422)
        self.assertEqual(self.client.get(self.path,headers={"Host":"evil.invalid"}).status_code,403)
        self.assertEqual(self.client.get('/assets/inventory.mjs').status_code,200)

    def test_import_pagination_evidence_and_restart(self):
        self.import_rows()
        first=self.client.get(self.path+'?limit=1').json()
        self.assertEqual(first["assigned_track_count"],1)
        self.assertEqual(first["review_count"],1)
        self.assertEqual(first["total_rows"],2)
        self.assertEqual(first["rows"][0]["title"],"")
        second=self.client.get(self.path+'?offset=1&limit=1').json()
        self.assertEqual(second["rows"][0]["kind"],"review")
        self.assertEqual(self.client.get('/api/frames/'+second["rows"][0]["frame_ref"]).content,self.fixture.data)
        with TestClient(create_app(self.fixture.root,{"http://testserver"})) as restarted:
            self.assertEqual(restarted.get(self.path+'?limit=1').json(),first)

    def test_ownership_and_closed_capture_still_update(self):
        ledger,initial=self.import_rows()
        self.fixture.end()
        command=TrackingCommand(command_id="ownership",sweep_id=self.fixture.sweep["id"],expected_revision=1,
            operation="ownership",detection_result_sha256=None,decisions=[],track_id=initial["books"][0]["id"],owned=False,provenance="borrowed fixture")
        ledger.apply(command)
        data=self.client.get(self.path).json()
        self.assertEqual(data["revision"],2)
        self.assertEqual(data["capture_status"],"closed")
        self.assertEqual(data["owned_assigned_track_count"],0)
        self.assertFalse(data["rows"][0]["owned"])
        exported=self.client.get(self.path+'/export')
        self.assertIn('attachment',exported.headers['content-disposition'])
        self.assertEqual(exported.json()["events"][-1]["command"]["provenance"],"borrowed fixture")

    def test_tampered_original_is_not_served_as_inventory(self):
        _,snap=self.import_rows()
        record=self.fixture.app.state.sessions.store.get(snap["books"][0]["frame_ref"])
        (self.fixture.root/record.path).write_bytes(b"changed")
        self.assertEqual(self.client.get(self.path).status_code,409)


if __name__=="__main__":
    unittest.main()
