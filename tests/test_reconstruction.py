import io
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pydantic import ValidationError

from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.reconstruction import ReconstructionPolicy, ReconstructionRequest, connectivity_gate, run_reconstruction


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = FrameStore(self.root/"store")
        self.records = []
        for i in range(3):
            sink = io.BytesIO()
            Image.new("RGB",(1600,900),(30+i*10,40,50)).save(sink,"PNG")
            self.records.append(self.store.save(CaptureInput(sweep_id="synthetic",upload_id=f"view-{i}",media_sequence=i,
                captured_at=datetime(2026,10,10,tzinfo=timezone.utc),source="file_import",synthetic=True),sink.getvalue()))
        self.policy = ReconstructionPolicy(max_runtime_seconds=10,min_points3d=100,
            max_median_reprojection_error_px=2,min_median_triangulation_angle_deg=2)
        self.request = ReconstructionRequest(sweep_id="synthetic",frame_refs=[r.id for r in self.records],
            same_camera_and_zoom_confirmed=True,camera_provenance="synthetic fixed camera",policy=self.policy)
        self.names = [Path(r.path).name for r in self.records]
        self.model = dict(model_id=0,registered_names=self.names,num_points3d=120,
                          median_reprojection_error_px=.5,median_triangulation_angle_deg=15)
        self.output = self.root/"job"

    def worker(self, command, **kwargs):
        (self.output/"worker-result.json").write_text(json.dumps(dict(models=[self.model])),encoding="utf-8")
        return subprocess.CompletedProcess(command,0)

    def run_mock(self, side_effect=None):
        with patch("library_claim.reconstruction.importlib.util.find_spec",return_value=object()), \
             patch("library_claim.reconstruction.subprocess.run",side_effect=side_effect or self.worker) as runner:
            result = run_reconstruction(self.store,self.request,self.output)
        return result,runner

    def test_connected_is_provisional_and_metric_null(self):
        result,runner = self.run_mock()
        self.assertEqual(result["status"],"connected_provisional")
        self.assertEqual(result["measurement_status"],"unavailable")
        for field in ["length_m","width_m","height_m","floor_area_m2","wall_area_m2"]:
            self.assertIsNone(result["room"][field])
        self.assertTrue(result["synthetic"])
        self.assertFalse(runner.call_args.kwargs["shell"])
        self.assertEqual(runner.call_args.kwargs["timeout"],10)

    def test_evidence_handoff_exact_and_reopenable(self):
        self.run_mock()
        manifest = json.loads((self.output/"frames.json").read_text())
        self.assertEqual([x["frame_ref"] for x in manifest],self.request.frame_refs)
        for r in self.records:
            self.assertEqual((self.output/"images"/Path(r.path).name).read_bytes(),self.store.read(r.id))

    def test_no_model_unavailable(self):
        self.assertIsNotNone(connectivity_gate(dict(models=[]),self.names,self.policy))

    def test_multiple_components_rejected(self):
        self.assertIsNotNone(connectivity_gate(dict(models=[self.model,self.model]),self.names,self.policy))

    def test_missing_or_duplicate_registration_rejected(self):
        for names in [self.names[:2],self.names+[self.names[0]],["foreign"]+self.names[1:]]:
            with self.subTest(names=names):
                model = dict(self.model,registered_names=names)
                self.assertIsNotNone(connectivity_gate(dict(models=[model]),self.names,self.policy))

    def test_insufficient_support_rejected(self):
        self.model["num_points3d"] = 20
        self.assertIn("support",connectivity_gate(dict(models=[self.model]),self.names,self.policy))

    def test_reprojection_gate(self):
        self.model["median_reprojection_error_px"] = 2.1
        self.assertIn("reprojection",connectivity_gate(dict(models=[self.model]),self.names,self.policy))

    def test_rotation_or_low_parallax_gate(self):
        self.model["median_triangulation_angle_deg"] = .01
        self.assertIn("parallax",connectivity_gate(dict(models=[self.model]),self.names,self.policy))

    def test_missing_nonfinite_negative_diagnostics(self):
        for field in ["median_reprojection_error_px","median_triangulation_angle_deg"]:
            for value in [None,float("nan"),float("inf"),-1]:
                with self.subTest(field=field,value=value):
                    model = dict(self.model,**{field:value})
                    self.assertIsNotNone(connectivity_gate(dict(models=[model]),self.names,self.policy))

    def test_camera_declaration_required(self):
        self.request.same_camera_and_zoom_confirmed = False
        result,runner = self.run_mock()
        self.assertEqual(result["status"],"unavailable")
        runner.assert_not_called()

    def test_resolution_change_rejected(self):
        sink = io.BytesIO()
        Image.new("RGB",(1920,1080)).save(sink,"PNG")
        record = self.store.save(CaptureInput(sweep_id="synthetic",upload_id="different-resolution",media_sequence=4,
            captured_at=self.records[0].captured_at,source="file_import",synthetic=True),sink.getvalue())
        self.request.frame_refs[0] = record.id
        result,runner = self.run_mock()
        self.assertIn("resolutions",result["reason"])
        runner.assert_not_called()

    def test_exif_orientation_rejected(self):
        sink = io.BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB",(1600,900)).save(sink,"JPEG",exif=exif)
        record = self.store.save(CaptureInput(sweep_id="synthetic",upload_id="rotated",media_sequence=4,
            captured_at=self.records[0].captured_at,source="file_import",synthetic=True),sink.getvalue())
        self.request.frame_refs[0] = record.id
        result,runner = self.run_mock()
        self.assertIn("orientation",result["reason"])
        runner.assert_not_called()

    def test_missing_backend_reported(self):
        with patch("library_claim.reconstruction.importlib.util.find_spec",return_value=None):
            result = run_reconstruction(self.store,self.request,self.output)
        self.assertEqual(result["stage_result"]["errors"][0]["code"],"backend_unavailable")

    def test_duplicate_bytes_cannot_establish_views(self):
        for i,r in enumerate(self.records[1:]):
            copy = self.store.save(CaptureInput(sweep_id="synthetic",upload_id=f"copy-{i}",media_sequence=5+i,
                captured_at=r.captured_at,source="file_import",synthetic=True),self.store.read(self.records[0].id))
            self.request.frame_refs[i+1] = copy.id
        result,runner = self.run_mock()
        self.assertEqual(result["stage_result"]["errors"][0]["code"],"insufficient_views")
        runner.assert_not_called()

    def test_timeout_and_crash_retained_as_failed(self):
        for effect in [subprocess.TimeoutExpired("worker",10),lambda command,**kwargs:subprocess.CompletedProcess(command,9)]:
            with self.subTest(effect=effect):
                self.output = self.root/str(len(list(self.root.iterdir())))
                result,_ = self.run_mock(effect)
                self.assertEqual(result["status"],"failed")
                self.assertTrue((self.output/"reconstruction_result.json").exists())
                self.assertIsNone(result["room"]["height_m"])

    def test_missing_or_malformed_worker_summary_failed(self):
        def malformed(command,**kwargs):
            (self.output/"worker-result.json").write_text("{}")
            return subprocess.CompletedProcess(command,0)
        result,_ = self.run_mock(malformed)
        self.assertEqual(result["status"],"failed")

    def test_wrong_sweep_fails_before_output(self):
        self.request.sweep_id = "different"
        with self.assertRaisesRegex(ValueError,"sweep"):
            run_reconstruction(self.store,self.request,self.output)
        self.assertFalse(self.output.exists())

    def test_original_tampering_fails_closed(self):
        (self.store.root/self.records[0].path).write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            run_reconstruction(self.store,self.request,self.output)

    def test_no_overwrite(self):
        self.run_mock()
        with self.assertRaises(FileExistsError):
            run_reconstruction(self.store,self.request,self.output)

    def test_bounded_request_schema(self):
        for refs in [self.request.frame_refs[:2],self.request.frame_refs+[self.request.frame_refs[0]],list(map(str,range(13)))]:
            with self.subTest(refs=refs),self.assertRaises(ValidationError):
                ReconstructionRequest.model_validate(self.request.model_dump()|dict(frame_refs=refs))
        with self.assertRaises(ValidationError):
            ReconstructionPolicy.model_validate(self.policy.model_dump()|dict(max_runtime_seconds=181))


if __name__ == "__main__":
    unittest.main()
