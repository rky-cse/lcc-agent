import copy
import hashlib
import io
import unittest

from PIL import Image

from library_claim.capture_store import CaptureInput
from library_claim.matching import MatchingRequest, propose
from library_claim.spine_detection import DetectionResponse, export_detection
from tests import test_tracking as tracking_fixture


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=tracking_fixture.TrackingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store
        self.first=self.fixture.ledger.apply(self.fixture.command(),self.fixture.bundle)
        old=self.store.get(self.fixture.request.frame_ref)
        self.current=self.store.save(CaptureInput(sweep_id="fixture",upload_id="shifted",media_sequence=1,
            captured_at=old.captured_at,source="file_import",synthetic=True),self.fixture.fixture.data)
        self.response=copy.deepcopy(self.fixture.fixture.response)
        for obj in self.response["objects"]:
            obj["polygon_1000"]=[(x+12.5,y) for x,y in obj["polygon_1000"]]
        self.input=self.fixture.request.model_copy(update=dict(frame_ref=self.current.id,frame_sha256=self.current.sha256))
        self.bundle=self.fixture.fixture.root/"shifted"
        self.export()
        self.request=MatchingRequest(sweep_id="fixture",expected_revision=1,command_id="match",
            detection_result_sha256=self.hash(),policy=dict(max_check_error_px=2,min_registration_area_px2=10000,
                plausible_iou=.1,accepted_iou=.7,max_appearance_mae=.1),registration=dict(
                anchor_frame_ref=old.id,anchor_frame_sha256=old.sha256,
                current_corners_px=[(50,50),(1550,50),(1550,850),(50,850)],
                anchor_corners_px=[(30,50),(1530,50),(1530,850),(30,850)],
                checks=[dict(current_px=(800,300),anchor_px=(780,300),provenance="holdout A"),
                        dict(current_px=(900,500),anchor_px=(880,500),provenance="holdout B")],
                same_physical_shelf_confirmed=True,coplanar_spines_confirmed=True,
                book_positions_unchanged_confirmed=True,lens_status="verified_negligible",provenance="synthetic shifted view"))

    def export(self):
        export_detection(self.store,self.input,self.bundle,DetectionResponse.model_validate(self.response))

    def hash(self):
        return hashlib.sha256((self.bundle/"detection_result.json").read_bytes()).hexdigest()

    def changed_source(self,name):
        self.bundle=self.fixture.fixture.root/name
        self.export()
        self.request.detection_result_sha256=self.hash()

    def run_match(self):
        return propose(self.store,self.request,self.bundle)

    def test_shifted_revisit_copies_and_horizontal_one_to_one(self):
        result,command=self.run_match()
        self.assertEqual([r["action"] for r in result["matches"]],["same"]*3)
        self.assertEqual(len({d.track_id for d in command.decisions}),3)
        self.assertTrue(all(r["comparisons"][0]["iou"]>.999 for r in result["matches"]))
        self.assertEqual(self.fixture.ledger.snapshot("fixture"),self.first)
        after=self.fixture.ledger.apply(command,self.bundle)
        self.assertEqual(after["assigned_track_count"],3)
        self.assertEqual(len(after["observations"]),6)

    def test_missing_registration_no_new_tracks(self):
        self.request.registration=None
        result,command=self.run_match()
        self.assertEqual(result["registration_failure"],"registration missing")
        self.assertTrue(all(d.action=="unresolved" for d in command.decisions))

    def test_failed_independent_check_no_links(self):
        self.request.registration.checks[0].anchor_px=(700,300)
        result,command=self.run_match()
        self.assertIn("check failed",result["registration_failure"])
        self.assertTrue(all(d.action=="unresolved" for d in command.decisions))

    def test_check_cannot_reuse_fit_corner(self):
        self.request.registration.checks[0].current_px=(50,50)
        self.request.registration.checks[0].anchor_px=(30,50)
        self.assertIn("holdouts",self.run_match()[0]["registration_failure"])

    def test_assertions_lens_and_reflection_rejected(self):
        original=self.request.registration.model_dump()
        for update in [dict(book_positions_unchanged_confirmed=False),dict(coplanar_spines_confirmed=False),
                       dict(same_physical_shelf_confirmed=False),dict(lens_status="unknown"),
                       dict(anchor_corners_px=list(reversed(original["anchor_corners_px"])) )]:
            self.request.registration=self.request.registration.model_validate({**original,**update})
            with self.subTest(update=update):
                self.assertIsNotNone(self.run_match()[0]["registration_failure"])

    def test_outside_support_no_extrapolation(self):
        self.request.registration.current_corners_px=[(400,50),(1550,50),(1550,850),(400,850)]
        self.request.registration.anchor_corners_px=[(380,50),(1530,50),(1530,850),(380,850)]
        result,_=self.run_match()
        self.assertEqual(result["matches"][0]["action"],"unresolved")
        self.assertIn("extrapolation",result["matches"][0]["reason"])

    def test_unmatched_book_not_automatically_new(self):
        obj=copy.deepcopy(self.response["objects"][0])
        obj["polygon_1000"]=[(x+650,y) for x,y in obj["polygon_1000"]]
        obj["polygon_1000"][2]=(obj["polygon_1000"][2][0],600)
        obj["polygon_1000"][3]=(obj["polygon_1000"][3][0],600)
        self.response["objects"].append(obj)
        self.changed_source("unmatched")
        result,_=self.run_match()
        self.assertEqual(sum(r["action"]=="same" for r in result["matches"]),3)
        self.assertEqual(sum(r["action"]=="unresolved" for r in result["matches"]),1)
        self.assertEqual(result["new_tracks_created"],0)

    def test_two_to_one_split_no_convenient_winner(self):
        original=self.response["objects"][0]
        left=copy.deepcopy(original)
        right=copy.deepcopy(original)
        x0,y0=original["polygon_1000"][0]
        x1,y1=original["polygon_1000"][2]
        mid=(x0+x1)/2
        left["polygon_1000"]=[(x0,y0),(mid,y0),(mid,y1),(x0,y1)]
        right["polygon_1000"]=[(mid,y0),(x1,y0),(x1,y1),(mid,y1)]
        self.response["objects"]=[left,right,*self.response["objects"][1:]]
        self.changed_source("split")
        result,_=self.run_match()
        self.assertEqual(sum(r["action"]=="same" for r in result["matches"]),2)
        self.assertEqual(sum(r["action"]=="unresolved" for r in result["matches"]),2)

    def test_many_to_one_merged_detection_unresolved(self):
        merged=copy.deepcopy(self.response["objects"][0])
        merged["polygon_1000"][1]=(412.5,100)
        merged["polygon_1000"][2]=(412.5,800)
        self.response["objects"]=[merged,self.response["objects"][2]]
        self.changed_source("merged")
        result,_=self.run_match()
        self.assertEqual(result["matches"][0]["action"],"unresolved")
        self.assertEqual(len(result["matches"][0]["comparisons"]),2)

    def test_changed_appearance_no_match(self):
        buf=io.BytesIO()
        Image.new("RGB",(1600,900),"white").save(buf,"PNG")
        old=self.store.get(self.current.id)
        white=self.store.save(CaptureInput(sweep_id="fixture",upload_id="white",media_sequence=2,
            captured_at=old.captured_at,source="file_import",synthetic=True),buf.getvalue())
        self.input=self.input.model_copy(update=dict(frame_ref=white.id,frame_sha256=white.sha256))
        self.changed_source("white")
        result,_=self.run_match()
        self.assertTrue(all(r["action"]=="unresolved" for r in result["matches"]))

    def test_orientation_mismatch_no_match(self):
        self.response["objects"][0]["orientation"]="diagonal"
        self.changed_source("orientation")
        result,_=self.run_match()
        self.assertEqual(result["matches"][0]["action"],"unresolved")

    def test_uncertain_coverage_blocks_matches(self):
        self.response["coverage"]="uncertain"
        self.changed_source("uncertain")
        self.assertTrue(all(r["action"]=="unresolved" for r in self.run_match()[0]["matches"]))

    def test_corrupt_hash_and_stale_revision_are_errors(self):
        self.request.expected_revision=0
        with self.assertRaisesRegex(ValueError,"stale"):
            self.run_match()
        self.request.expected_revision=1
        self.request.detection_result_sha256="0"*64
        with self.assertRaisesRegex(ValueError,"hash mismatch"):
            self.run_match()

    def test_unresolved_region_blocks_local_match(self):
        self.response["unresolved_regions"]=[dict(polygon_1000=[(115,150),(190,150),(190,700),(115,700)],reason="glare occlusion")]
        self.changed_source("region")
        result,_=self.run_match()
        self.assertEqual(result["matches"][0]["action"],"unresolved")
        self.assertEqual(sum(r["action"]=="same" for r in result["matches"]),2)

    def test_anchor_corruption_stops_proposal(self):
        self.request.registration.anchor_frame_sha256="0"*64
        result,_=self.run_match()
        self.assertIn("hash mismatch",result["registration_failure"])
        self.assertEqual(result["stage_result"]["status"],"unavailable")

    def test_policy_rejects_inverted_thresholds(self):
        self.request.policy.accepted_iou=.05
        with self.assertRaisesRegex(ValueError,"must exceed"):
            self.run_match()

    def test_repeated_proposal_has_stable_command_payload(self):
        result,command=self.run_match()
        repeated,repeated_command=self.run_match()
        self.assertEqual(command,repeated_command)
        self.assertEqual(result["proposal_sha256"],repeated["proposal_sha256"])

    def test_quad_transform_projective_and_legacy_metric(self):
        from library_claim.planar import fit_quad_transform,fit_homography,transform
        source=[(10,10),(110,20),(120,100),(0,90)]
        target=[(30,40),(250,10),(230,240),(0,200)]
        h=fit_quad_transform(source,target)
        for a,b in zip(source,target):
            self.assertLess(__import__("math").dist(transform(h,a),b),1e-8)
        metric=fit_homography(source,20,30)
        self.assertLess(__import__("math").dist(transform(metric,source[2]),(20,30)),1e-8)


if __name__=="__main__":
    unittest.main()
