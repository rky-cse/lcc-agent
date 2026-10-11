import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pydantic import ValidationError

from library_claim.capture_store import CaptureInput, FrameStore, StorageLimits
from library_claim.models import PacketInput, Sweep
from library_claim.packet import build_packet
from library_claim.models import PacketPolicy


def image_bytes(format="JPEG", size=(1600, 900), orientation=None):
    sink = io.BytesIO()
    image = Image.new("RGB", size, (31, 77, 115))
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        kwargs["exif"] = exif
    image.save(sink, format=format, **kwargs)
    return sink.getvalue()


class CaptureStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = FrameStore(self.root / "store")
        self.capture = CaptureInput(sweep_id="synthetic-sweep", upload_id="upload-1", media_sequence=0,
                                    captured_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
                                    source="file_import", synthetic=True)
        self.data = image_bytes()

    def test_original_bytes_and_metadata_preserved(self):
        record = self.store.save(self.capture, self.data)
        self.assertEqual(self.store.read(record.id), self.data)
        self.assertEqual((record.width, record.height), (1600, 900))
        self.assertEqual(record.byte_size, len(self.data))
        self.assertEqual(record.sha256, hashlib.sha256(self.data).hexdigest())
        self.assertEqual(record.captured_at, self.capture.captured_at)
        self.assertIsNotNone(record.received_at.utcoffset())
        self.assertEqual(record.timestamp_source, "caller_supplied")
        self.assertTrue(record.synthetic)

    def test_exif_rotation_does_not_reencode_original(self):
        data = image_bytes(orientation=6)
        record = self.store.save(self.capture, data)
        self.assertEqual(record.exif_orientation, 6)
        self.assertEqual((record.display_width, record.display_height), (900, 1600))
        self.assertEqual(self.store.read(record.id), data)

    def test_png_and_extension_from_decoded_content(self):
        source = self.root / "wrong-extension.txt"
        source.write_bytes(image_bytes(format="PNG"))
        record = self.store.ingest_file(self.capture, source)
        self.assertEqual(record.mime_type, "image/png")
        self.assertTrue(record.path.endswith(".png"))

    def test_invalid_truncated_small_and_wrong_formats_rejected(self):
        for data in [b"", b"not an image", self.data[:300], image_bytes(size=(640, 480)),
                     image_bytes(format="GIF"), image_bytes(format="TIFF")]:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                self.store.save(self.capture, data)
        self.assertEqual(self.store.manifest(self.capture.sweep_id)["frames"], [])

    def test_invalid_orientation_rejected(self):
        with self.assertRaisesRegex(ValueError, "EXIF orientation"):
            self.store.save(self.capture, image_bytes(orientation=9))

    def test_byte_pixel_and_bomb_limits(self):
        with self.assertRaisesRegex(ValueError, "byte limit"):
            FrameStore(self.root / "byte", StorageLimits(max_bytes=100)).save(self.capture, self.data)
        with self.assertRaisesRegex(ValueError, "pixel limit"):
            FrameStore(self.root / "pixel", StorageLimits(max_pixels=10_000)).save(self.capture, self.data)
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1_000_000), self.assertRaises(ValueError):
            self.store.save(self.capture, self.data)

    def test_animated_png_rejected(self):
        sink = io.BytesIO()
        Image.new("RGB", (1600, 900), "red").save(sink, format="PNG", save_all=True,
              append_images=[Image.new("RGB", (1600, 900), "blue")], duration=100)
        with self.assertRaisesRegex(ValueError, "multi-frame"):
            self.store.save(self.capture, sink.getvalue())

    def test_idempotent_retry_after_reopen(self):
        first = self.store.save(self.capture, self.data)
        second = FrameStore(self.store.root).save(self.capture, self.data)
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.manifest(self.capture.sweep_id)["frames"]), 1)

    def test_retry_conflicts_do_not_replace_original(self):
        first = self.store.save(self.capture, self.data)
        with self.assertRaisesRegex(ValueError, "different image"):
            self.store.save(self.capture, image_bytes(size=(1600, 901)))
        changed = self.capture.model_copy(update={"media_sequence": 1})
        with self.assertRaisesRegex(ValueError, "different image"):
            self.store.save(changed, self.data)
        self.assertEqual(self.store.read(first.id), self.data)

    def test_distinct_capture_ids_preserve_duplicate_views(self):
        first = self.store.save(self.capture, self.data)
        second = self.store.save(self.capture.model_copy(update={"upload_id": "upload-2", "media_sequence": 1}), self.data)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(self.store.manifest(self.capture.sweep_id)["frames"]), 2)

    def test_sweeps_are_isolated_and_manifest_ordered(self):
        self.store.save(self.capture.model_copy(update={"media_sequence": 9}), self.data)
        first = self.store.save(self.capture.model_copy(update={"upload_id": "upload-2", "media_sequence": 1}), self.data)
        other = self.store.save(self.capture.model_copy(update={"sweep_id": "other"}), self.data)
        manifest = self.store.manifest(self.capture.sweep_id)
        self.assertEqual(manifest["frames"][0]["id"], first.id)
        self.assertNotIn(other.id, [x["id"] for x in manifest["frames"]])
        path = self.store.write_manifest(self.capture.sweep_id)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), manifest)

    def test_tampered_or_missing_original_not_acknowledged(self):
        record = self.store.save(self.capture, self.data)
        path = self.store.root / record.path
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.store.get(record.id)
        with self.assertRaises(ValueError):
            self.store.save(self.capture, self.data)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.store.get(record.id)

    def test_metadata_corruption_detected(self):
        record = self.store.save(self.capture, self.data)
        fields = record.model_dump(mode="json")
        fields["width"] = 1601
        with closing(sqlite3.connect(self.store.database)) as connection, connection:
            connection.execute("UPDATE frames SET record=? WHERE id=?", (json.dumps(fields), record.id))
        with self.assertRaisesRegex(ValueError, "metadata mismatch"):
            self.store.get(record.id)

    def test_write_failure_has_no_acknowledged_record(self):
        with patch("library_claim.capture_store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.save(self.capture, self.data)
        self.assertEqual(self.store.manifest(self.capture.sweep_id)["frames"], [])
        self.assertEqual(list((self.store.root / "frames").iterdir()), [])

    def test_database_failure_orphan_can_be_recovered_by_retry(self):
        with closing(sqlite3.connect(self.store.database)) as connection, connection:
            connection.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON frames BEGIN SELECT RAISE(FAIL, 'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save(self.capture, self.data)
        self.assertEqual(self.store.manifest(self.capture.sweep_id)["frames"], [])
        self.assertEqual(len(list((self.store.root / "frames").glob("*.jpg"))), 1)
        with closing(sqlite3.connect(self.store.database)) as connection, connection:
            connection.execute("DROP TRIGGER fail_insert")
        record = FrameStore(self.store.root).save(self.capture, self.data)
        self.assertEqual(self.store.read(record.id), self.data)

    def test_concurrent_retries_commit_once(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            records = list(workers.map(lambda _: FrameStore(self.store.root).save(self.capture, self.data), range(4)))
        self.assertTrue(all(r == records[0] for r in records))
        self.assertEqual(len(self.store.manifest(self.capture.sweep_id)["frames"]), 1)

    def test_flush_failure_has_no_acknowledged_record(self):
        with patch("library_claim.capture_store.os.fsync", side_effect=OSError("flush failed")):
            with self.assertRaises(OSError):
                self.store.save(self.capture, self.data)
        self.assertEqual(self.store.manifest(self.capture.sweep_id)["frames"], [])
        self.assertEqual(list((self.store.root / "frames").iterdir()), [])

    def test_path_identifiers_and_timezone_validated(self):
        for changes in [{"sweep_id": "../escape"}, {"upload_id": "C:\\bad"},
                        {"captured_at": "2026-10-10T12:00:00"}, {"media_sequence": -1}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                CaptureInput.model_validate(dict(self.capture.model_dump(), **changes))
        with self.assertRaises(KeyError):
            self.store.get("missing")

    def test_new_process_reopen_cli(self):
        source = self.root / "original.jpg"
        source.write_bytes(self.data)
        command = [sys.executable, "-B", "-m", "library_claim.capture", "--store", str(self.store.root)]
        saved = subprocess.run(command + ["ingest", "--file", str(source), "--sweep-id", "synthetic-sweep",
                               "--upload-id", "upload-1", "--captured-at", "2026-10-10T00:00:00Z",
                               "--media-sequence", "0", "--synthetic"], check=True, text=True, capture_output=True)
        record = json.loads(saved.stdout)
        source.unlink()
        reopened = subprocess.run(command + ["reopen", "--frame-id", record["id"]], check=True, text=True, capture_output=True)
        self.assertEqual(json.loads(reopened.stdout), record)

    def test_m01_packet_consumes_stored_evidence(self):
        record = self.store.save(self.capture, self.data)
        packet = PacketInput(sweep=Sweep(id=self.capture.sweep_id, captured_at=self.capture.captured_at,
                                        country="IN", currency="INR"), frames=[record.packet_evidence()], synthetic=True)
        policy = PacketPolicy(currency_decimal_places=2, shelf_run_basis="sum_spine_thickness",
                              exclusion_basis="missing_any_component")
        result = build_packet(packet, self.store.root, policy)
        self.assertEqual(result["evidence_manifest"][0]["sha256"], record.sha256)


if __name__ == "__main__":
    unittest.main()
