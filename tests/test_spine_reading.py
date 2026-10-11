import io
import json
import unittest
from unittest.mock import patch,MagicMock

from PIL import Image
from pydantic import ValidationError

from library_claim.spine_reading import ReadingRequest,ReadingResponse,prepare_crop,export_reading,reading_schema,PROMPT
from library_claim.vision_provider import request_structured
from tests import test_tracking as tracking_fixture


def span(text="RIVER ATLAS",role="title"):
    return dict(text=text,role=role,orientation="horizontal",polygon_1000=[(100,100),(900,100),(900,300),(100,300)])


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=tracking_fixture.TrackingTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.snapshot=self.fixture.ledger.apply(self.fixture.command(),self.fixture.bundle)
        self.request=ReadingRequest(sweep_id="fixture",expected_revision=1,observation_id=self.snapshot["observations"][0]["id"],
            frame_sha256=self.snapshot["observations"][0]["frame_sha256"])
        self.root=self.fixture.fixture.root

    def response(self,**update):
        return ReadingResponse.model_validate(dict(legibility="readable",spans=[span()],uncertainty="",**update))

    def test_crop_original_hash_transform_and_no_upscale(self):
        frame,original,crop,meta=prepare_crop(self.fixture.store,self.request)
        self.assertEqual(original,self.fixture.fixture.data)
        with Image.open(io.BytesIO(crop)) as image:
            self.assertEqual(image.size,(160,630))
        from library_claim.planar import transform
        self.assertAlmostEqual(transform(meta["crop_to_original_matrix"],(0,0))[0],160)
        self.assertEqual(frame.sha256,self.request.frame_sha256)

    def test_unknown_identity_and_source_spans_persist_without_mutation(self):
        result=export_reading(self.fixture.store,self.request,self.root/"reading",self.response())
        self.assertIsNone(result["accepted_identity"])
        self.assertIsNone(result["calibrated_confidence"])
        self.assertEqual(result["text_evidence"][0]["text"],"RIVER ATLAS")
        self.assertFalse(result["text_evidence"][0]["verified"])
        self.assertEqual(self.fixture.ledger.snapshot("fixture"),self.snapshot)
        self.assertEqual((self.root/"reading/original.png").read_bytes(),self.fixture.fixture.data)

    def test_unreadable_partial_and_unicode_fragments(self):
        for index,response in enumerate([ReadingResponse(legibility="unreadable",spans=[],uncertainty="no legible lettering"),
                ReadingResponse(legibility="partial",spans=[span("नदी / RIV","unknown")],uncertainty="remaining letters occluded")]):
            result=export_reading(self.fixture.store,self.request,self.root/f"case-{index}",response)
            self.assertEqual(result["stage_result"]["status"],"partial")
            self.assertIsNone(result["accepted_identity"])

    def test_status_schema_rejects_guesses_extra_confidence_and_invalid_regions(self):
        bad=[dict(legibility="unreadable",spans=[span()],uncertainty="blur"),dict(legibility="readable",spans=[],uncertainty=""),
             dict(legibility="partial",spans=[span()],uncertainty=""),dict(legibility="readable",spans=[{**span(),"confidence":.99}],uncertainty=""),
             dict(legibility="readable",spans=[span(" ")],uncertainty=""),dict(legibility="readable",spans=[{**span(),"polygon_1000":[(0,0)]*4}],uncertainty="")]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValidationError): ReadingResponse.model_validate(value)

    def test_wrong_observation_hash_sweep_and_stale_revision(self):
        for update in [dict(observation_id="missing"),dict(frame_sha256="0"*64),dict(sweep_id="different"),dict(expected_revision=0)]:
            with self.subTest(update=update),self.assertRaises(ValueError):
                prepare_crop(self.fixture.store,self.request.model_copy(update=update))

    def test_fresh_output_required_and_html_escapes_model_text(self):
        response=ReadingResponse(legibility="partial",spans=[span("<script>bad()</script>")],uncertainty="<img onerror=bad()>")
        output=self.root/"escaped"
        export_reading(self.fixture.store,self.request,output,response)
        html=(output/"report.html").read_text()
        self.assertNotIn("<script>bad()",html);self.assertIn("&lt;script&gt;",html)
        with self.assertRaises(FileExistsError): export_reading(self.fixture.store,self.request,output,response)

    def test_provider_failure_preserves_crop_unknown_not_empty_success(self):
        result=export_reading(self.fixture.store,self.request,self.root/"failure",failure=dict(code="rate_limited",reason="quota",retryable=True))
        self.assertEqual(result["stage_result"]["status"],"unavailable")
        self.assertIsNone(result["response"]);self.assertEqual(result["text_evidence"],[])
        self.assertTrue((self.root/"failure/crop.png").exists())

    def test_actual_transport_shape_reads_crop_and_redacts_key(self):
        raw=dict(candidates=[dict(finishReason="STOP",content=dict(parts=[dict(text=self.response().model_dump_json())]))],usageMetadata=dict(totalTokenCount=1))
        opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value=json.dumps(raw).encode()
        with patch("library_claim.vision_provider.build_opener",return_value=opener):
            result=export_reading(self.fixture.store,self.request,self.root/"provider",key="fixture-key")
        payload=json.loads(opener.open.call_args.args[0].data)
        self.assertIn("Transcribe ONLY",payload["contents"][0]["parts"][0]["text"])
        self.assertEqual(result["response"]["spans"][0]["text"],"RIVER ATLAS")
        self.assertEqual(result["usage"]["requests"],1)
        self.assertNotIn("fixture-key",(self.root/"provider/reading_result.json").read_text())

    def test_correction_during_provider_request_rejected(self):
        def corrected(*args,**kwargs):
            cmd=self.fixture.command().model_copy(update=dict(command_id="ownership",expected_revision=1,operation="ownership",
                detection_result_sha256=None,decisions=[],track_id=self.snapshot["books"][0]["id"],owned=False))
            self.fixture.ledger.apply(cmd)
            return self.response(),None,None,None
        with patch("library_claim.spine_reading.request_structured",side_effect=corrected),self.assertRaisesRegex(ValueError,"changed during"):
            export_reading(self.fixture.store,self.request,self.root/"stale",key="fixture-key")
        self.assertFalse((self.root/"stale").exists())


if __name__=='__main__': unittest.main()
