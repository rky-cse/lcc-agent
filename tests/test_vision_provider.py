import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError,URLError

from library_claim.vision_provider import NoRedirect,read_key,request_detection
import test_spine_detection as detection_fixtures


class ProviderTests(unittest.TestCase):
    setUp = detection_fixtures.DetectionTests.setUp
    def call(self,raw):
        opener=unittest.mock.MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value=json.dumps(raw).encode()
        with patch("library_claim.vision_provider.build_opener",return_value=opener):
            result=request_detection("test-secret",self.data,self.record,self.request)
        return result,opener

    def test_valid_bounded_payload_header_and_usage(self):
        raw=dict(candidates=[dict(finishReason="STOP",content=dict(parts=[dict(text=json.dumps(self.response))]))],
                 usageMetadata=dict(totalTokenCount=100),modelVersion="fixture")
        (response,error,usage,_),opener=self.call(raw)
        self.assertIsNone(error)
        self.assertEqual(len(response.objects),3)
        self.assertEqual(usage["metadata"]["totalTokenCount"],100)
        request=opener.open.call_args.args[0]
        self.assertNotIn("test-secret",request.full_url)
        self.assertIn("gemini-3.1-flash-lite",request.full_url)
        payload=json.loads(request.data)
        self.assertEqual(payload["contents"][0]["parts"][1]["inlineData"]["mimeType"],"image/png")
        self.assertNotIn("test-secret",str(payload))

    def test_blocked_truncated_bad_json_and_extra_schema(self):
        for raw in [dict(candidates=[]),dict(candidates=[dict(finishReason="MAX_TOKENS")]),
                    dict(candidates=[dict(finishReason="STOP",content=dict(parts=[dict(text="not json")]))])]:
            with self.subTest(raw=raw):
                (_,error,_,_),_=self.call(raw)
                self.assertEqual(error["code"],"provider_invalid_response")

    def test_rate_limit_no_retry_and_redaction(self):
        opener=unittest.mock.Mock()
        opener.open.side_effect=HTTPError("https://example",429,"limit",{},io.BytesIO(b'{"error":{"message":"test-secret quota"}}'))
        with patch("library_claim.vision_provider.build_opener",return_value=opener):
            response,error,usage,raw=request_detection("test-secret",self.data,self.record,self.request)
        self.assertIsNone(response)
        self.assertTrue(error["retryable"])
        self.assertNotIn("test-secret",json.dumps(raw)+error["reason"])
        opener.open.assert_called_once()

    def test_network_failure_and_disallowed_model(self):
        opener=unittest.mock.Mock()
        opener.open.side_effect=URLError("failed")
        with patch("library_claim.vision_provider.build_opener",return_value=opener):
            self.assertEqual(request_detection("test-secret",self.data,self.record,self.request)[1]["code"],"provider_unavailable")
        with self.assertRaises(ValueError):
            request_detection("test-secret",self.data,self.record,self.request,"unapproved-paid-model")
        self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_input_limit_and_local_key_loading(self):
        self.assertEqual(request_detection("test-secret",b"x"*(10*1024*1024+1),self.record,self.request)[1]["code"],"provider_input_limit")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/".env"
            path.write_text('# comment\nGOOGLE_API_KEY="test-secret"\n')
            self.assertEqual(read_key(path),"test-secret")


if __name__=="__main__":
    unittest.main()
