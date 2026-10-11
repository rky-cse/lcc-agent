import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.models import PacketPolicy
from library_claim.packet import json_text
from library_claim.reconstruction import PinholeCalibration, ReconstructionRequest
from library_claim.room_measurement import export_room
from test_room_geometry import scene


class RoomBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = FrameStore(self.root/"store")
        self.reconstruction = self.root/"reconstruction"
        (self.reconstruction/"images").mkdir(parents=True)
        records = []
        for i in range(3):
            sink = io.BytesIO()
            Image.new("RGB",(1920,1080),(40+i*20,50,60)).save(sink,"PNG")
            records.append(self.store.save(CaptureInput(sweep_id="fixture",upload_id=f"view-{i}",media_sequence=i,
                captured_at=datetime(2026,10,10,tzinfo=timezone.utc),source="file_import",synthetic=True),sink.getvalue()))
        self.records = records
        views,_,self.request = scene()
        self.views = {r.id:views[f"v{i}"] for i,r in enumerate(records)}
        for point in self.request.points:
            for observation in point.observations:
                observation.frame_ref = records[int(observation.frame_ref[1:])].id
        calibration = PinholeCalibration(width=1920,height=1080,fx=1200,fy=1200,cx=960,cy=540,
            coordinate_space="colmap_encoded_pixels",independently_verified=True,provenance="synthetic calibration",
            lens_status="verified_negligible",lens_provenance="synthetic pinhole")
        self.source = ReconstructionRequest(sweep_id="fixture",frame_refs=[r.id for r in records],
            same_camera_and_zoom_confirmed=True,camera_provenance="fixture",camera_calibration=calibration,
            policy=dict(max_runtime_seconds=10,min_points3d=10,max_median_reprojection_error_px=2,min_median_triangulation_angle_deg=2))
        manifest = []
        for record in records:
            name = Path(record.path).name
            (self.reconstruction/"images"/name).write_bytes(self.store.read(record.id))
            manifest.append(dict(frame_ref=record.id,sha256=record.sha256,name=name))
        (self.reconstruction/"frames.json").write_text(json.dumps(manifest))
        self.result = dict(input_sha256="",status="connected_provisional",synthetic=True,
            backend_summary=dict(settings=dict(intrinsics="verified_fixed"),models=[dict(model_id=0,
                registered_names=[m["name"] for m in manifest],num_points3d=100,median_reprojection_error_px=.2,median_triangulation_angle_deg=10)]),artifacts=[])
        # These bytes exercise the integrity/export boundary. Native parsing is
        # replaced only in these tests; the native smoke uses real model files.
        (self.reconstruction/"sparse"/"0").mkdir(parents=True)
        for name in ("cameras","images","points3D","frames","rigs"):
            path = self.reconstruction/"sparse"/"0"/f"{name}.bin"
            path.write_bytes(b"synthetic mock native file")
            self.result["artifacts"].append(dict(path=f"sparse/0/{name}.bin",sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.save_metadata()
        self.output = self.root/"packet"
        self.policy = PacketPolicy(currency_decimal_places=2,shelf_run_basis="sum_spine_thickness",exclusion_basis="missing_any_component")

    def save_metadata(self):
        data = json_text(self.source.model_dump())
        (self.reconstruction/"request.json").write_text(data)
        self.result["input_sha256"] = hashlib.sha256(data.encode()).hexdigest()
        path = self.reconstruction/"reconstruction_result.json"
        path.write_text(json_text(self.result))
        self.request.reconstruction_result_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def export(self,mock_views=True):
        if mock_views:
            with patch("library_claim.room_measurement.calibrated_views",return_value=self.views):
                return export_room(self.store,self.reconstruction,self.request,self.output,"IN","INR",self.policy)
        return export_room(self.store,self.reconstruction,self.request,self.output,"IN","INR",self.policy)

    def test_evidence_and_portable_packet_agree(self):
        result = self.export()
        packet = json.loads((self.output/"claim_packet.json").read_text())
        self.assertEqual(result["stage_result"]["status"],"success")
        self.assertEqual([packet["room"][f] for f in ("length_m","width_m","height_m")],[3,4,2.6])
        self.assertEqual(len(result["measurements"]),3)
        self.assertEqual(result["reconstruction_request"]["camera_calibration"]["fx"],1200)
        self.assertEqual(set(result["camera_views"]),{r.id for r in self.records})
        self.assertIsNone(packet["room"]["floor_area_m2"])
        for record in self.records:
            self.assertEqual((self.output/record.path).read_bytes(),self.store.read(record.id))

    def test_missing_anchor_exports_unknowns(self):
        self.request.anchor = None
        result = self.export()
        self.assertEqual(result["stage_result"]["status"],"unavailable")
        self.assertEqual(result["measurements"],[])
        packet = json.loads((self.output/"claim_packet.json").read_text())
        self.assertIsNone(packet["room"]["length_m"])
        self.assertTrue(any("reference" in r["reason"] for r in packet["review_queue"]))

    def test_estimated_intrinsics_export_unknowns(self):
        self.source.camera_calibration = None
        self.result["backend_summary"]["settings"]["intrinsics"] = "estimated"
        self.save_metadata()
        result = self.export(mock_views=False)
        self.assertEqual(result["stage_result"]["status"],"unavailable")
        self.assertIn("fixed camera calibration",result["reason"])

    def test_result_hash_mismatch_fails(self):
        self.request.reconstruction_result_sha256 = "0"*64
        with self.assertRaisesRegex(ValueError,"result hash"):
            self.export()

    def test_model_tampering_fails(self):
        (self.reconstruction/"sparse"/"0"/"images.bin").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError,"model hash"):
            self.export()

    def test_original_or_request_tampering_fails(self):
        path = self.reconstruction/"images"/Path(self.records[0].path).name
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError,"image hash"):
            self.export()
        path.write_bytes(self.store.read(self.records[0].id))
        changed = self.source.model_dump()|dict(camera_provenance="modified")
        (self.reconstruction/"request.json").write_text(json_text(changed))
        with self.assertRaisesRegex(ValueError,"fingerprint"):
            self.export()

    def test_unqualified_or_incomplete_model_ledger_fails(self):
        self.result["status"] = "unavailable"
        self.save_metadata()
        with self.assertRaisesRegex(ValueError,"qualified"):
            self.export()
        self.result["status"] = "connected_provisional"
        self.result["artifacts"].pop()
        self.save_metadata()
        with self.assertRaisesRegex(ValueError,"incomplete"):
            self.export()

    def test_bad_boundary_exports_unknowns_and_no_overwrite(self):
        self.request.ceiling_corners = None
        result = self.export()
        self.assertIsNone(result["room"]["height_m"])
        with self.assertRaises(FileExistsError):
            self.export()


if __name__=="__main__":
    unittest.main()
