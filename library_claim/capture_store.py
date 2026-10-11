"""M02a: durable, immutable original frames and a transactional manifest.

The file is flushed before its metadata transaction commits. A crash between
those operations can leave an unacknowledged orphan; an identical retry reuses
it. No acknowledged frame depends on a live process or a provider session.
"""

import hashlib
import io
import json
import os
import sqlite3
import tempfile
import warnings
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from PIL import Image, UnidentifiedImageError
from pydantic import Field, field_validator

from .models import Contract, FrameEvidence, Sweep


class CaptureInput(Contract):
    sweep_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    upload_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    captured_at: datetime
    media_sequence: int = Field(ge=0)
    source: Literal["file_import", "browser_camera"]
    synthetic: bool

    _timezone = field_validator("captured_at")(classmethod(Sweep.timezone_required.__func__))


class StorageLimits(Contract):
    max_bytes: int = Field(default=32 * 1024 * 1024, gt=0)
    max_pixels: int = Field(default=40_000_000, gt=0)
    min_short_edge: int = Field(default=720, ge=0)
    min_long_edge: int = Field(default=1280, ge=0)


class StoredFrame(FrameEvidence):
    sweep_id: str
    upload_id: str
    media_sequence: int = Field(ge=0)
    source: Literal["file_import", "browser_camera"]
    synthetic: bool
    received_at: datetime
    byte_size: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    display_width: int = Field(gt=0)
    display_height: int = Field(gt=0)
    mime_type: Literal["image/jpeg", "image/png"]
    exif_orientation: int | None = Field(default=None, ge=1, le=8)
    timestamp_source: Literal["caller_supplied"] = "caller_supplied"

    _received_timezone = field_validator("received_at")(classmethod(Sweep.timezone_required.__func__))

    def packet_evidence(self) -> FrameEvidence:
        """M01-compatible evidence boundary; richer capture metadata stays here."""
        return FrameEvidence.model_validate(self.model_dump(include={"id", "path", "sha256", "captured_at"}))


def inspect_image(data: bytes, limits: StorageLimits) -> dict:
    if not data or len(data) > limits.max_bytes:
        raise ValueError("empty image or encoded byte limit exceeded")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG"]) as image:
                width, height = image.size
                if width * height > limits.max_pixels:
                    raise ValueError("decoded pixel limit exceeded")
                if min(width, height) < limits.min_short_edge or max(width, height) < limits.min_long_edge:
                    raise ValueError("image resolution below configured evidence minimum")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("animated or multi-frame image is not a single evidence frame")
                image_format = image.format
                image.verify()
            # verify() is not a full pixel decode; reopen and load before accepting.
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG"]) as image:
                image.load()
                orientation = image.getexif().get(274)
                if orientation is not None and (type(orientation) is not int or orientation not in range(1, 9)):
                    raise ValueError("invalid EXIF orientation")
        rotated = orientation in {5, 6, 7, 8}
        return dict(width=width, height=height,
                    display_width=height if rotated else width,
                    display_height=width if rotated else height,
                    exif_orientation=orientation,
                    mime_type="image/jpeg" if image_format == "JPEG" else "image/png")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("invalid or unsafe JPEG/PNG image") from exc


class FrameStore:
    def __init__(self, root: Path, limits: StorageLimits | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits or StorageLimits()
        self.database = self._safe_path("manifest.sqlite3")
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS frames (
                id TEXT PRIMARY KEY, sweep_id TEXT NOT NULL, upload_id TEXT NOT NULL,
                record TEXT NOT NULL, UNIQUE(sweep_id, upload_id))""")

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _safe_path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("evidence path escapes store root")
        return candidate

    def _verify_record(self, record: StoredFrame) -> bytes:
        expected_id = "frame-" + hashlib.sha256(f"{record.sweep_id}\0{record.upload_id}".encode()).hexdigest()
        extension = "jpg" if record.mime_type == "image/jpeg" else "png"
        if record.id != expected_id or record.path != f"frames/{expected_id}.{extension}":
            raise ValueError("saved frame identity/path metadata mismatch")
        path = self._safe_path(record.path)
        try:
            with path.open("rb") as source:
                data = source.read(record.byte_size + 1)
        except OSError as exc:
            raise ValueError(f"saved frame missing or unreadable: {record.id}") from exc
        if len(data) != record.byte_size or hashlib.sha256(data).hexdigest() != record.sha256:
            raise ValueError(f"saved frame integrity failure: {record.id}")
        # Recheck decoding and dimensions without treating a changed minimum as corruption.
        inspection = inspect_image(data, StorageLimits(max_bytes=max(record.byte_size, 1),
                                   max_pixels=record.width * record.height, min_short_edge=0, min_long_edge=0))
        if any(getattr(record, key) != value for key, value in inspection.items()):
            raise ValueError(f"saved frame metadata mismatch: {record.id}")
        return data

    def save(self, capture: CaptureInput, data: bytes) -> StoredFrame:
        capture = CaptureInput.model_validate(capture.model_dump())
        digest = hashlib.sha256(data).hexdigest()
        frame_id = "frame-" + hashlib.sha256(f"{capture.sweep_id}\0{capture.upload_id}".encode()).hexdigest()
        # Serialize writers across store instances/processes before examining retries.
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT record FROM frames WHERE id=?", (frame_id,)).fetchone()
            if row:
                record = StoredFrame.model_validate_json(row[0])
                same_capture = all(getattr(record, key) == value for key, value in capture.model_dump().items())
                if record.sha256 != digest or not same_capture:
                    raise ValueError("upload_id already committed with different image or capture metadata")
                self._verify_record(record)
                connection.commit()
                return record
            inspection = inspect_image(data, self.limits)
            extension = "jpg" if inspection["mime_type"] == "image/jpeg" else "png"
            relative = f"frames/{frame_id}.{extension}"
            target = self._safe_path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                with target.open("rb") as existing:
                    old_data = existing.read(self.limits.max_bytes + 1)
                if old_data != data:
                    raise ValueError("uncommitted frame conflicts with retry; original left intact")
            else:
                descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
                try:
                    with os.fdopen(descriptor, "wb") as sink:
                        sink.write(data)
                        sink.flush()
                        os.fsync(sink.fileno())
                    os.replace(temporary, target)
                finally:
                    if Path(temporary).exists():
                        Path(temporary).unlink()
            record = StoredFrame(id=frame_id, path=relative, sha256=digest,
                                 received_at=datetime.now(timezone.utc), byte_size=len(data),
                                 **capture.model_dump(), **inspection)
            connection.execute("INSERT INTO frames VALUES (?,?,?,?)",
                               (record.id, record.sweep_id, record.upload_id, record.model_dump_json()))
            connection.commit()
            return record
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ingest_file(self, capture: CaptureInput, source_path: Path) -> StoredFrame:
        with Path(source_path).open("rb") as source:
            data = source.read(self.limits.max_bytes + 1)
        return self.save(capture, data)

    def get(self, frame_id: str) -> StoredFrame:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT record FROM frames WHERE id=?", (frame_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown frame: {frame_id}")
        record = StoredFrame.model_validate_json(row[0])
        if record.id != frame_id:
            raise ValueError("manifest lookup identity mismatch")
        self._verify_record(record)
        return record

    def read(self, frame_id: str) -> bytes:
        return self._verify_record(self.get(frame_id))

    def manifest(self, sweep_id: str) -> dict:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT record FROM frames WHERE sweep_id=? ORDER BY id", (sweep_id,)).fetchall()
        records = [StoredFrame.model_validate_json(row[0]) for row in rows]
        for record in records:
            if record.sweep_id != sweep_id:
                raise ValueError("manifest sweep identity mismatch")
            self._verify_record(record)
        records.sort(key=lambda r: (r.media_sequence, r.id))
        return {"schema_version": "1.0", "sweep_id": sweep_id,
                "frames": [r.model_dump(mode="json") for r in records]}

    def write_manifest(self, sweep_id: str) -> Path:
        """Portable per-sweep snapshot; SQLite is authoritative, not this cache."""
        snapshot = self.manifest(sweep_id)
        name = "manifest-" + hashlib.sha256(sweep_id.encode()).hexdigest() + ".json"
        target = self._safe_path(name)
        descriptor, temporary = tempfile.mkstemp(prefix=".manifest-", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as sink:
                json.dump(snapshot, sink, ensure_ascii=False, indent=2)
                sink.write("\n")
                sink.flush()
                os.fsync(sink.fileno())
            os.replace(temporary, target)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
        return target
