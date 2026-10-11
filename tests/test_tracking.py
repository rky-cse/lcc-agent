import copy
import hashlib
import json
import unittest

from library_claim.tracking import TrackStore, TrackingCommand
from library_claim.spine_detection import DetectionResponse, export_detection
from tests import test_spine_detection as detection_fixture


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = detection_fixture.DetectionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.ledger = TrackStore(self.store)
        self.request = self.fixture.request
        self.bundle = self.fixture.root / "first"
        self.result = export_detection(self.store, self.request, self.bundle,
            DetectionResponse.model_validate(self.fixture.response))
        self.ids = [b["id"] for b in self.result["books"]]

    def command(self, revision=0, actions=None, bundle=None, cid="first"):
        bundle = bundle or self.bundle
        return TrackingCommand(command_id=cid, sweep_id="fixture", expected_revision=revision,
            operation="import", detection_result_sha256=hashlib.sha256((bundle/"detection_result.json").read_bytes()).hexdigest(),
            decisions=actions if actions is not None else [self.decision(oid) for oid in self.ids],
            track_id=None, owned=None, provenance="synthetic labeled distinct physical objects")

    @staticmethod
    def decision(oid, action="new", tid=None):
        return dict(observation_id=oid, action=action, track_id=tid, provenance="fixture physical identity annotation")

    def revisit(self):
        capture = self.store.get(self.request.frame_ref)
        from library_claim.capture_store import CaptureInput
        data = self.store.read(capture.id)
        second = self.store.save(CaptureInput(sweep_id="fixture", upload_id="revisit", media_sequence=1,
            captured_at=capture.captured_at, source="file_import", synthetic=True), data)
        request = self.request.model_copy(update=dict(frame_ref=second.id, frame_sha256=second.sha256))
        directory = self.fixture.root/"second"
        result = export_detection(self.store, request, directory, DetectionResponse.model_validate(self.fixture.response))
        return directory, result

    def test_distinct_copies_horizontal_and_unknown_fields(self):
        snap = self.ledger.apply(self.command(), self.bundle)
        self.assertEqual(snap["assigned_track_count"], 3)
        self.assertEqual(len({b["id"] for b in snap["books"]}), 3)
        self.assertEqual({o["orientation"] for o in snap["observations"]}, {"upright", "horizontal"})
        self.assertTrue(all(b["title"] == "" and b["spine_height_cm"] is None for b in snap["books"]))
        self.assertIsNone(snap["total_book_count"])

    def test_revisit_same_tracks_survive_restart(self):
        first = self.ledger.apply(self.command(), self.bundle)
        mapping = {o["id"]: o["track_id"] for o in first["observations"]}
        directory, result = self.revisit()
        actions = [self.decision(new["id"], "same", mapping[old]) for old, new in zip(self.ids, result["books"])]
        second = self.ledger.apply(self.command(1, actions, directory, "revisit"), directory)
        self.assertEqual(second["assigned_track_count"], 3)
        self.assertTrue(all(len(t["observations"]) == 2 for t in second["tracks"]))
        self.assertEqual(TrackStore(self.store).snapshot("fixture"), second)

    def test_unresolved_does_not_inflate_and_later_resolves(self):
        first = self.ledger.apply(self.command(actions=[self.decision(o, "unresolved") for o in self.ids]), self.bundle)
        self.assertEqual(first["assigned_track_count"], 0)
        self.assertEqual(len(first["review_queue"]), 3)
        command = TrackingCommand(command_id="resolve", sweep_id="fixture", expected_revision=1, operation="resolve",
            detection_result_sha256=None, decisions=[self.decision(o) for o in self.ids], track_id=None, owned=None,
            provenance="independent fixture inspection")
        snap = self.ledger.apply(command)
        self.assertEqual(snap["assigned_track_count"], 3)
        self.assertEqual(snap["review_queue"], [])

    def test_ownership_excludes_without_deleting_evidence(self):
        first = self.ledger.apply(self.command(), self.bundle)
        command = TrackingCommand(command_id="exclude", sweep_id="fixture", expected_revision=1, operation="ownership",
            detection_result_sha256=None, decisions=[], track_id=first["books"][0]["id"], owned=False,
            provenance="user says borrowed")
        snap = self.ledger.apply(command)
        self.assertEqual(snap["assigned_track_count"], 3)
        self.assertEqual(snap["owned_assigned_track_count"], 2)
        self.assertEqual(len(snap["observations"]), 3)
        self.assertEqual(len(snap["events"]), 2)

    def test_retry_exact_payload_and_conflicting_replay(self):
        command = self.command()
        first = self.ledger.apply(command, self.bundle)
        self.assertEqual(self.ledger.apply(command, self.bundle), first)
        with self.assertRaisesRegex(ValueError, "reused"):
            self.ledger.apply(command.model_copy(update=dict(provenance="changed")), self.bundle)

    def test_stale_revision_rolls_back(self):
        before = self.ledger.apply(self.command(), self.bundle)
        directory, result = self.revisit()
        with self.assertRaisesRegex(ValueError, "stale"):
            self.ledger.apply(self.command(0, [self.decision(b["id"]) for b in result["books"]], directory, "stale"), directory)
        self.assertEqual(self.ledger.snapshot("fixture"), before)

    def test_same_frame_many_to_one_rejected_atomically(self):
        first = self.ledger.apply(self.command(actions=[self.decision(self.ids[0]), *[self.decision(o,"unresolved") for o in self.ids[1:]]]), self.bundle)
        command = TrackingCommand(command_id="badmerge", sweep_id="fixture", expected_revision=1, operation="resolve",
            detection_result_sha256=None, decisions=[self.decision(self.ids[1], "same", first["books"][0]["id"])],
            track_id=None, owned=None, provenance="bad fixture association")
        with self.assertRaisesRegex(ValueError, "one frame"):
            self.ledger.apply(command)
        self.assertEqual(self.ledger.snapshot("fixture"), first)

    def test_missing_decision_and_unknown_track_rollback(self):
        for actions in [[self.decision(self.ids[0])], [self.decision(o,"same","missing") for o in self.ids]]:
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                self.ledger.apply(self.command(actions=actions), self.bundle)
        self.assertEqual(self.ledger.snapshot("fixture")["revision"], 0)

    def test_cross_sweep_and_reimport_rejected(self):
        with self.assertRaisesRegex(ValueError, "cross-sweep"):
            self.ledger.apply(self.command().model_copy(update=dict(sweep_id="different")), self.bundle)
        self.ledger.apply(self.command(), self.bundle)
        with self.assertRaisesRegex(ValueError, "already imported"):
            self.ledger.apply(self.command(1,cid="again"), self.bundle)

    def test_pinned_result_and_response_tampering_rejected(self):
        command = self.command()
        path = self.bundle/"detection_result.json"
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw+" ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.ledger.apply(command,self.bundle)
        path.write_text(raw,encoding="utf-8")
        response = copy.deepcopy(self.fixture.response)
        response["objects"] = []
        (self.bundle/"detector_response.json").write_text(json.dumps(response),encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.ledger.apply(command,self.bundle)

    def test_uncertain_coverage_keeps_review(self):
        directory=self.fixture.root/"uncertain"
        response=copy.deepcopy(self.fixture.response)
        response["coverage"]="uncertain"
        export_detection(self.store,self.request,directory,DetectionResponse.model_validate(response))
        snap=self.ledger.apply(self.command(bundle=directory),directory)
        self.assertTrue(any("coverage" in r["reason"] for r in snap["review_queue"]))

    def test_unavailable_detection_is_not_zero_total(self):
        directory=self.fixture.root/"unavailable"
        export_detection(self.store,self.request,directory,failure=dict(code="timeout",reason="provider timed out"))
        snap=self.ledger.apply(self.command(actions=[],bundle=directory),directory)
        self.assertIsNone(snap["total_book_count"])
        self.assertTrue(snap["review_queue"])
        self.assertEqual(snap["assigned_track_count"],0)

    def test_original_tampering_blocks_snapshot(self):
        self.ledger.apply(self.command(), self.bundle)
        frame=self.store.get(self.request.frame_ref)
        (self.store.root/frame.path).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.ledger.snapshot("fixture")

    def test_cross_shelf_link_rejected(self):
        first=self.ledger.apply(self.command(),self.bundle)
        directory,result=self.revisit()
        request=self.request.model_copy(update=dict(frame_ref=result["frame_ref"],frame_sha256=result["frame_sha256"],shelf_id="other"))
        other=self.fixture.root/"other"
        detected=export_detection(self.store,request,other,DetectionResponse.model_validate(self.fixture.response))
        actions=[self.decision(b["id"],"same",first["books"][0]["id"]) for b in detected["books"]]
        with self.assertRaisesRegex(ValueError,"cross-shelf"):
            self.ledger.apply(self.command(1,actions,other,"cross-shelf"),other)
        self.assertEqual(self.ledger.snapshot("fixture"),first)

    def test_split_merge_review_from_detector_is_retained(self):
        response=copy.deepcopy(self.fixture.response)
        response["objects"]=[response["objects"][0],response["objects"][0]]
        directory=self.fixture.root/"overlap"
        export_detection(self.store,self.request,directory,DetectionResponse.model_validate(response))
        snap=self.ledger.apply(self.command(actions=[],bundle=directory),directory)
        self.assertEqual(snap["assigned_track_count"],0)
        self.assertEqual(len(snap["review_queue"]),2)
        self.assertIsNone(snap["total_book_count"])

    def test_command_shape_rejects_implicit_targets(self):
        from pydantic import ValidationError
        base=self.command().model_dump()
        for update in [dict(owned=False),dict(detection_result_sha256="z"*64),
                       dict(decisions=[self.decision(self.ids[0],"same")]),
                       dict(decisions=[self.decision(self.ids[0]),self.decision(self.ids[0])])]:
            with self.subTest(update=update),self.assertRaises(ValidationError):
                TrackingCommand.model_validate({**base,**update})


if __name__ == "__main__":
    unittest.main()
