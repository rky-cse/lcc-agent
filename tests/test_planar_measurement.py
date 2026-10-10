import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.measurement import export_measurement, measure
from library_claim.models import PacketPolicy
from library_claim.planar import MeasurementRequest, dimensions, fit_homography, no_horizon, transform


def project(point):
    # Independently specified forward camera, not the implementation's inverse.
    x, y = point
    d = .004*x + .006*y + 1
    return ((30*x+4*y+200)/d, (3*x+25*y+120)/d)


def fixture(record):
    def spine(name, corners):
        return dict(id=name, frame_ref=record.id, plane_id="fixture-plane",
                    corners_px=[project(p) for p in corners], corner_tolerance_px=.5,
                    coplanarity_confirmed=True, coplanarity_provenance="synthetic plane",
                    annotation_source="developer_annotated")
    return dict(sweep_id=record.sweep_id, reference=dict(
        id="fixture-reference", frame_ref=record.id, frame_sha256=record.sha256,
        plane_id="fixture-plane", width_cm=10, height_cm=20,
        width_uncertainty_cm=.1, height_uncertainty_cm=.2,
        dimensions_verified=True, dimension_provenance="synthetic dimensions, not a real object",
        corners_px=[project(p) for p in [(0,0),(10,0),(10,20),(0,20)]],
        corner_tolerance_px=.5, coordinate_space="encoded_pixels",
        lens_status="verified_negligible", lens_provenance="synthetic pinhole projection",
        valid_region_px=[(100,50),(1500,50),(1500,1000),(100,1000)],
        validity_provenance="synthetic plane region",
        check_points=[dict(pixel=project((5,10)),plane_cm=(5,10),provenance="independent synthetic centre")]),
        policy=dict(min_reference_area_px2=10000, max_check_error_cm=.1,
                    max_opposite_edge_relative_difference=.1, max_corner_cosine=.1,
                    max_sensitivity_relative_change=.15),
        spines=[spine("upright", [(15,2),(17.5,2),(17.5,25),(15,25)]),
                spine("horizontal",[(20,2),(20,5),(42,5),(42,2)])])


class PlanarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = FrameStore(self.root/"store")
        sink = io.BytesIO()
        Image.new("RGB",(1920,1080),(55,70,90)).save(sink,"PNG")
        self.data = sink.getvalue()
        self.capture = CaptureInput(sweep_id="synthetic-planar",upload_id="first",media_sequence=0,
                                   captured_at=datetime(2026,10,10,tzinfo=timezone.utc),
                                   source="file_import",synthetic=True)
        self.record = self.store.save(self.capture,self.data)
        self.input = fixture(self.record)

    def run_measure(self):
        return measure(self.store,MeasurementRequest.model_validate(self.input))

    def test_perspective_and_horizontal_axes(self):
        result = self.run_measure()
        self.assertEqual(result["stage_result"]["status"],"success")
        self.assertEqual([(r["spine_height_cm"],r["spine_thickness_cm"]) for r in result["results"]],
                         [(Decimal("23.000"),Decimal("2.500")),(Decimal("22.000"),Decimal("3.000"))])
        self.assertLess(result["check_points"][0]["error_cm"],1e-9)
        self.assertEqual(len(result["measurements"]),4)
        self.assertTrue(result["synthetic"])

    def test_affine_known_scale(self):
        h = fit_homography([(100,100),(300,100),(300,500),(100,500)],10,20)
        height,thickness = dimensions(h,[(400,120),(450,120),(450,580),(400,580)])
        self.assertAlmostEqual(height,23)
        self.assertAlmostEqual(thickness,2.5)
        self.assertAlmostEqual(transform(h,(200,300))[0],5)

    def test_missing_reference_preserves_unknowns(self):
        self.input["reference"] = None
        result = self.run_measure()
        self.assertEqual(result["stage_result"]["status"],"unavailable")
        self.assertEqual(result["measurements"],[])
        self.assertEqual(len(result["review_queue"]),2)
        self.assertTrue(all(r["spine_height_cm"] is None for r in result["results"]))

    def test_declared_physical_validity_required(self):
        for field,value in [("dimensions_verified",False),("dimension_provenance"," "),
                            ("lens_status","unknown"),("lens_provenance",""),("validity_provenance","")]:
            with self.subTest(field=field):
                self.input = fixture(self.record)
                self.input["reference"][field] = value
                self.assertEqual(self.run_measure()["calibration_status"],"unavailable")

    def test_independent_check_required(self):
        for checks in [[],[dict(pixel=self.input["reference"]["corners_px"][0],plane_cm=(0,0),provenance="fitted corner")],
                       [dict(pixel=project((5,10)),plane_cm=(6,10),provenance="wrong metric")]]:
            with self.subTest(checks=checks):
                self.input["reference"]["check_points"] = checks
                self.assertEqual(self.run_measure()["calibration_status"],"unavailable")

    def test_partial_off_plane_retained(self):
        self.input["spines"][1]["plane_id"] = "another-plane"
        result = self.run_measure()
        self.assertEqual(result["stage_result"]["status"],"partial")
        self.assertEqual(len(result["results"]),2)
        self.assertIsNone(result["results"][1]["spine_thickness_cm"])
        self.assertEqual(len(result["measurements"]),2)
        self.assertIn("coplanarity",result["review_queue"][0]["reason"])

    def test_no_coplanarity_assertion(self):
        self.input["spines"][0]["coplanarity_confirmed"] = False
        self.assertEqual(self.run_measure()["results"][0]["status"],"unavailable")

    def test_hash_sweep_and_missing_frame_fail_closed(self):
        self.input["reference"]["frame_sha256"] = "0"*64
        with self.assertRaisesRegex(ValueError,"hash"):
            self.run_measure()
        self.input = fixture(self.record)
        self.input["sweep_id"] = "different"
        with self.assertRaisesRegex(ValueError,"sweep"):
            self.run_measure()
        self.input = fixture(self.record)
        self.input["spines"][0]["frame_ref"] = "absent"
        with self.assertRaises((ValueError,KeyError,FileNotFoundError)):
            self.run_measure()

    def test_saved_original_tampering_detected(self):
        (self.store.root/self.record.path).write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.run_measure()

    def test_calibration_not_transferred(self):
        another = self.store.save(self.capture.model_copy(update={"upload_id":"second","media_sequence":1}),self.data)
        self.input["spines"][0]["frame_ref"] = another.id
        self.assertIn("another view",self.run_measure()["results"][0]["reason"])

    def test_bounds_and_valid_region(self):
        for point in [(-1,100),(1920,100),(1600,100)]:
            with self.subTest(point=point):
                self.input = fixture(self.record)
                self.input["spines"][0]["corners_px"][0] = point
                self.assertEqual(self.run_measure()["results"][0]["status"],"unavailable")

    def test_degenerate_reference_and_small_area(self):
        for corners in [[(100,100),(200,100),(300,100),(400,100)],
                        [(100,100),(200,200),(200,100),(100,200)],
                        [(100,100),(101,100),(101,101),(100,101)]]:
            with self.subTest(corners=corners):
                self.input = fixture(self.record)
                self.input["reference"]["corners_px"] = corners
                self.assertEqual(self.run_measure()["calibration_status"],"unavailable")

    def test_horizon_rejected(self):
        with self.assertRaisesRegex(ValueError,"horizon"):
            no_horizon([[1,0,0],[0,1,0],[1,0,-5]],[(0,0),(10,0),(10,10),(0,10)])

    def test_self_intersecting_valid_region_rejected(self):
        import math
        pentagon = [(700+500*math.cos(i*2*math.pi/5),500+400*math.sin(i*2*math.pi/5)) for i in range(5)]
        self.input["reference"]["valid_region_px"] = [pentagon[i] for i in [0,2,4,1,3]]
        self.assertEqual(self.run_measure()["calibration_status"],"unavailable")

    def test_rotated_exif_requires_adapter(self):
        sink = io.BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB",(1920,1080)).save(sink,"JPEG",exif=exif)
        record = self.store.save(self.capture.model_copy(update={"upload_id":"rotated","media_sequence":1}),sink.getvalue())
        self.input = fixture(record)
        result = self.run_measure()
        self.assertIn("EXIF",result["calibration_reason"])
        self.assertEqual(len(result["stage_result"]["errors"]),2)

    def test_nonrectangular_spine_rejected(self):
        self.input["spines"][0]["corners_px"] = [project(p) for p in [(15,2),(20,2),(17.5,25),(15,25)]]
        self.assertEqual(self.run_measure()["results"][0]["status"],"unavailable")

    def test_sensitivity_gate(self):
        self.input["spines"][0]["corner_tolerance_px"] = 100
        self.assertEqual(self.run_measure()["results"][0]["status"],"unavailable")

    def test_dimension_uncertainty_analytic_envelope(self):
        self.input["reference"]["corner_tolerance_px"] = 0
        for spine in self.input["spines"]:
            spine["corner_tolerance_px"] = 0
        result = self.run_measure()["results"][0]
        self.assertEqual(result["sensitivity_cm"]["height"],[Decimal("22.770"),Decimal("23.230")])
        self.assertEqual(result["sensitivity_cm"]["thickness"],[Decimal("2.475"),Decimal("2.525")])
        self.assertFalse(result["sensitivity_cm"]["confidence_bound"])

    def test_schema_rejects_uncertainty_duplicates_and_nonfinite(self):
        for change in [lambda r:r["reference"].update(width_uncertainty_cm=10),
                       lambda r:r["spines"][1].update(id="upright"),
                       lambda r:r["reference"].update(width_cm=float("nan")),
                       lambda r:r.update(spines=[])]:
            with self.subTest(change=change):
                self.input = fixture(self.record)
                change(self.input)
                with self.assertRaises(ValidationError):
                    MeasurementRequest.model_validate(self.input)

    def test_replay_stable_evidence(self):
        first,second = self.run_measure(),self.run_measure()
        self.assertEqual(first["input_sha256"],second["input_sha256"])
        self.assertEqual(first["measurements"],second["measurements"])

    def test_portable_export_and_no_overwrite(self):
        self.input["spines"][1]["id"] = "horizontal<&"
        request = MeasurementRequest.model_validate(self.input)
        policy = dict(country="IN",currency="INR",aggregation=PacketPolicy(currency_decimal_places=2,
                      shelf_run_basis="sum_spine_thickness",exclusion_basis="missing_any_component"))
        output = self.root/"packet"
        export_measurement(self.store,request,policy,output)
        packet = json.loads((output/"claim_packet.json").read_text())
        self.assertEqual(packet["books"][0]["spine_height_cm"],23)
        self.assertEqual(packet["books"][0]["title"],"")
        self.assertIsNone(packet["books"][0]["replacement_cost"]["amount"])
        self.assertEqual(packet["totals"]["shelf_run_m"],.055)
        ET.parse(next(output.glob("overlay-*.svg")))
        self.assertEqual((output/self.record.path).read_bytes(),self.data)
        self.assertTrue((output/"report.html").exists())
        with self.assertRaises(FileExistsError):
            export_measurement(self.store,request,policy,output)


if __name__ == "__main__":
    unittest.main()
