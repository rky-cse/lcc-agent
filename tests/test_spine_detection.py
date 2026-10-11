import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from library_claim.capture_store import CaptureInput,FrameStore
from library_claim.spine_detection import DetectionRequest,DetectionResponse,area,export_detection,intersection_polygon,process_response
from scripts.evaluate_detection import evaluate


def proposal(box=(100,100,200,800),kind="book_spine",orientation="upright",reason="observed outline"):
    x0,y0,x1,y1=box
    return dict(kind=kind,orientation=orientation,polygon_1000=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)],reason=reason)


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=FrameStore(self.root/"store")
        sink=io.BytesIO()
        Image.new("RGB",(1600,900)).save(sink,"PNG")
        self.data=sink.getvalue()
        self.record=self.store.save(CaptureInput(sweep_id="fixture",upload_id="shelf",media_sequence=0,
            captured_at=datetime(2026,10,10,tzinfo=timezone.utc),source="file_import",synthetic=True),self.data)
        self.request=DetectionRequest(sweep_id="fixture",frame_ref=self.record.id,frame_sha256=self.record.sha256,
            shelf_id="shelf",shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
        self.response=dict(coverage="clear",objects=[proposal(),proposal((300,100,400,800)),proposal((500,700,900,800),orientation="horizontal")],unresolved_regions=[])

    def run_response(self):
        return process_response(self.store,self.request,DetectionResponse.model_validate(self.response),"test_replay")

    def test_upright_and_horizontal_polygons_count(self):
        result=self.run_response()
        self.assertEqual(result["provisional_shelf_count"],3)
        self.assertEqual(result["proposals"][0]["polygon_px"][0],(160,90))
        self.assertTrue(result["provisional"])
        self.assertFalse(result["coverage_verified"])
        self.assertTrue(all(b["title"]=="" and b["spine_height_cm"] is None for b in result["books"]))

    def test_bookend_excluded_without_claiming_geometry_classification(self):
        self.response["objects"].append(proposal((10,10,80,800),kind="non_book",orientation="unknown",reason="bookend"))
        result=self.run_response()
        self.assertEqual(result["provisional_observed_count"],3)
        self.assertEqual(result["proposals"][-1]["status"],"excluded")

    def test_adjacent_identical_looking_copies_remain_distinct(self):
        self.response["objects"]=[proposal((100,100,200,800)),proposal((200,100,300,800))]
        result=self.run_response()
        self.assertEqual(result["provisional_shelf_count"],2)
        self.assertNotEqual(result["books"][0]["id"],result["books"][1]["id"])

    def test_overlaps_become_review_without_arbitrary_suppression(self):
        self.response["objects"]=[proposal(),proposal(),proposal((300,100,400,800))]
        result=self.run_response()
        self.assertEqual(result["provisional_observed_count"],1)
        self.assertIsNone(result["provisional_shelf_count"])
        self.assertEqual(len(result["review_queue"]),2)

    def test_degenerate_tiny_and_unknown_orientation_review(self):
        for value in [proposal((100,100,100,800)),proposal((100,100,101,101)),proposal(orientation="unknown")]:
            with self.subTest(value=value):
                self.response["objects"]=[value]
                self.assertIsNone(self.run_response()["provisional_shelf_count"])

    def test_outside_roi_review(self):
        self.request.shelf_region_px=(250,0,1600,900)
        self.assertEqual(self.run_response()["proposals"][0]["status"],"review")

    def test_unresolved_coverage_and_ambiguous_objects(self):
        self.response["coverage"]="uncertain"
        self.response["unresolved_regions"]=[dict(polygon_1000=[(500,100),(700,100),(700,500),(500,500)],reason="glare")]
        self.response["objects"].append(proposal((600,100,800,800),kind="ambiguous"))
        result=self.run_response()
        self.assertIsNone(result["provisional_shelf_count"])
        self.assertEqual(len(result["unresolved_regions"]),1)
        self.assertTrue(result["review_queue"])

    def test_contradictory_empty_coverage_not_trusted(self):
        self.response["coverage"]="no_visible_books"
        self.assertIsNone(self.run_response()["provisional_shelf_count"])

    def test_provisional_empty_shelf(self):
        self.response.update(coverage="no_visible_books",objects=[])
        self.assertEqual(self.run_response()["provisional_shelf_count"],0)
        self.assertFalse(self.run_response()["coverage_verified"])

    def test_replay_and_order_stable_observation_ids(self):
        first=self.run_response()
        self.response["objects"].reverse()
        second=self.run_response()
        self.assertEqual(first["books"],second["books"])

    def test_frame_integrity_sweep_and_roi(self):
        for update in [dict(frame_sha256="0"*64),dict(sweep_id="wrong"),dict(shelf_region_px=(0,0,1601,900))]:
            with self.subTest(update=update),self.assertRaises(ValueError):
                request=DetectionRequest.model_validate(self.request.model_dump()|update)
                process_response(self.store,request,DetectionResponse.model_validate(self.response),"test")

    def test_changed_original_rejected(self):
        (self.store.root/self.record.path).write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.run_response()

    def test_schema_limits_nonfinite_extra_and_invalid_labels(self):
        for change in [dict(objects=[proposal(kind="made-up")]),dict(extra=1),dict(objects=[proposal()]*257)]:
            with self.subTest(change=change),self.assertRaises(ValidationError):
                DetectionResponse.model_validate(self.response|change)
        value=proposal()
        value["polygon_1000"][0]=(float("nan"),100)
        with self.assertRaises(ValidationError):
            DetectionResponse.model_validate(self.response|dict(objects=[value]))

    def test_convex_overlap_arithmetic(self):
        a=[(0,0),(10,0),(10,10),(0,10)]
        b=[(5,0),(15,0),(15,10),(5,10)]
        self.assertAlmostEqual(area(intersection_polygon(a,b)),50)
        self.assertAlmostEqual(area(intersection_polygon(a,list(reversed(b)))),50)

    def test_portable_escaped_review_and_no_overwrite(self):
        self.response["objects"][0]["reason"]="<script>alert('x')</script>"
        output=self.root/"review"
        result=export_detection(self.store,self.request,output,DetectionResponse.model_validate(self.response))
        self.assertEqual((output/"original.png").read_bytes(),self.data)
        self.assertNotIn("<script>",(output/"report.html").read_text())
        ET.parse(output/"overlay.svg")
        saved=json.loads((output/"detection_result.json").read_text())
        self.assertEqual(saved["provisional_observed_count"],result["provisional_observed_count"])
        with self.assertRaises(FileExistsError):
            export_detection(self.store,self.request,output,DetectionResponse.model_validate(self.response))

    def test_provider_failure_is_unknown_not_zero(self):
        result=export_detection(self.store,self.request,self.root/"failed",failure=dict(code="rate_limited",reason="HTTP 429",retryable=True))
        self.assertIsNone(result["provisional_observed_count"])
        self.assertIsNone(result["provisional_shelf_count"])
        self.assertEqual(result["stage_result"]["status"],"unavailable")
        self.assertTrue(result["stage_result"]["errors"][0]["retryable"])

    def test_evaluation_exposes_count_cancellation(self):
        result=dict(frame_sha256=self.record.sha256,synthetic=True,proposals=[
            dict(status="candidate",polygon_px=[(0,0),(10,0),(10,10),(0,10)],observation_id="first",orientation="upright"),
            dict(status="candidate",polygon_px=[(100,0),(110,0),(110,10),(100,10)],observation_id="false",orientation="upright")])
        truth=dict(frame_sha256=self.record.sha256,objects=[dict(id="a",kind="book_spine",orientation="upright",box_px=(0,0,10,10)),
            dict(id="b",kind="book_spine",orientation="upright",box_px=(30,0,40,10))])
        score=evaluate(result,truth,.5)
        self.assertEqual(score["candidate_books"],score["truth_books"])
        self.assertEqual((score["true_positives"],score["false_positives"],score["false_negatives"]),(1,1,1))
        truth["frame_sha256"]="wrong"
        with self.assertRaises(ValueError):
            evaluate(result,truth,.5)


if __name__=="__main__":
    unittest.main()
