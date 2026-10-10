import io
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from library_claim.server import create_app


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root, {"http://testserver"})
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"Origin": "http://testserver"}
        self.start_body = {"start_id": "1" * 32, "country": "IN", "currency": "INR"}
        self.sweep = self.client.post("/api/sweeps", json=self.start_body, headers=self.headers).json()
        sink = io.BytesIO()
        Image.new("RGB", (1600, 900), "white").save(sink, format="JPEG")
        self.data = sink.getvalue()

    def upload(self, upload_id="upload-1", sequence=0, data=None):
        return self.client.post(f"/api/sweeps/{self.sweep['id']}/frames", params={
            "upload_id": upload_id, "captured_at": "2026-10-10T00:00:00Z", "media_sequence": sequence},
            content=self.data if data is None else data, headers={**self.headers, "Content-Type": "image/jpeg"})

    def end(self, gaps=0, end_id="end-1"):
        return self.client.post(f"/api/sweeps/{self.sweep['id']}/end", json={"end_id": end_id, "capture_gaps": gaps}, headers=self.headers)

    def test_ui_assets_and_health(self):
        for path in ["/", "/assets/app.mjs", "/assets/queue.mjs", "/assets/style.css", "/api/health"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/assets/private.py").status_code, 404)

    def test_host_origin_and_body_boundaries(self):
        self.assertEqual(self.client.post("/api/sweeps", json=self.start_body).status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/sweeps", json=self.start_body, headers={"Origin": "https://evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/sweeps", content=b"x" * 4097, headers=self.headers).status_code, 413)

    def test_start_replay_and_conflict(self):
        self.assertEqual(self.client.post("/api/sweeps", json=self.start_body, headers=self.headers).json(), self.sweep)
        changed = {**self.start_body, "currency": "USD"}
        self.assertEqual(self.client.post("/api/sweeps", json=changed, headers=self.headers).status_code, 409)

    def test_invalid_locale_and_metadata(self):
        changed = {**self.start_body, "country": "India"}
        self.assertEqual(self.client.post("/api/sweeps", json=changed, headers=self.headers).status_code, 422)
        response = self.client.post(f"/api/sweeps/{self.sweep['id']}/frames", params={"upload_id": "x", "captured_at": "2026-10-10", "media_sequence": -1}, content=self.data, headers={**self.headers, "Content-Type": "image/jpeg"})
        self.assertEqual(response.status_code, 422)

    def test_durable_ack_and_original_reopen_after_new_app(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        ack = response.json()
        self.assertTrue(ack["durable"])
        self.assertEqual(ack["frame"]["source"], "browser_camera")
        self.assertFalse(ack["frame"]["synthetic"])
        self.assertTrue(ack["quality"]["heuristic"])
        restarted = TestClient(create_app(self.root, {"http://testserver"}))
        self.addCleanup(restarted.close)
        snapshot = restarted.get(f"/api/sweeps/{self.sweep['id']}").json()
        self.assertEqual(snapshot["frames"][0], ack["frame"])
        self.assertEqual(snapshot["quality"][ack["frame"]["id"]], ack["quality"])
        self.assertEqual(restarted.get(f"/api/frames/{ack['frame']['id']}").content, self.data)

    def test_idempotent_frame_and_sequence_conflict(self):
        first = self.upload().json()
        self.assertEqual(first, self.upload().json())
        self.assertEqual(self.upload("different-id", 0).status_code, 409)
        self.assertEqual(len(self.client.get(f"/api/sweeps/{self.sweep['id']}").json()["frames"]), 1)

    def test_end_requires_no_new_frames_and_allows_lost_ack_replay(self):
        frame = self.upload().json()
        closed = self.end().json()
        self.assertEqual(closed["status"], "closed")
        self.assertTrue(closed["transport_complete"])
        self.assertEqual(self.end().json(), closed)
        self.assertEqual(self.upload().json(), frame)
        self.assertEqual(self.upload("later", 1).status_code, 409)
        self.assertEqual(self.end(gaps=1).status_code, 409)

    def test_gaps_or_empty_capture_not_complete(self):
        self.assertFalse(self.end(gaps=1).json()["transport_complete"])

    def test_invalid_image_never_acknowledged(self):
        self.assertEqual(self.upload(data=b"invalid").status_code, 409)
        self.assertEqual(self.client.get(f"/api/sweeps/{self.sweep['id']}").json()["frames"], [])

    def test_unknown_sweep_and_frame(self):
        self.assertEqual(self.client.get("/api/sweeps/missing").status_code, 404)
        self.assertEqual(self.client.get("/api/frames/missing").status_code, 404)

    def test_streamed_frame_byte_limit(self):
        self.app.state.sessions.store.limits.max_bytes = 10
        self.assertEqual(self.upload(data=b"x" * 11).status_code, 413)
        self.assertEqual(self.client.get(f"/api/sweeps/{self.sweep['id']}").json()["frames"], [])

    def test_synthetic_mode_cannot_be_claimed_as_real(self):
        client = TestClient(create_app(self.root / "synthetic", {"http://testserver"}, synthetic=True))
        self.addCleanup(client.close)
        self.assertTrue(client.get("/api/health").json()["synthetic_capture_mode"])
        sweep = client.post("/api/sweeps", json=self.start_body, headers=self.headers).json()
        response = client.post(f"/api/sweeps/{sweep['id']}/frames", params={"upload_id": "fixture", "captured_at": "2026-10-10T00:00:00Z", "media_sequence": 0}, content=self.data,
                               headers={**self.headers, "Content-Type": "image/jpeg"})
        self.assertTrue(response.json()["frame"]["synthetic"])


if __name__ == "__main__":
    unittest.main()
