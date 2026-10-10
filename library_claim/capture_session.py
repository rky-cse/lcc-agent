"""Durable capture lifecycle. One server process; frame storage remains M02a."""

import io
import json
import threading
from contextlib import closing
from datetime import datetime, timezone

from PIL import Image

from .capture_store import CaptureInput, FrameStore
from .models import Sweep


def quality_signals(data: bytes) -> dict:
    """Cheap heuristics, not calibrated readability or measurement confidence."""
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((160, 160))
        grey = image.convert("L")
        width, height = grey.size
        pixels = list(grey.get_flattened_data())
    edges = [4 * pixels[y * width + x] - pixels[y * width + x - 1] - pixels[y * width + x + 1]
             - pixels[(y - 1) * width + x] - pixels[(y + 1) * width + x]
             for y in range(1, height - 1) for x in range(1, width - 1)]
    mean = sum(edges) / max(len(edges), 1)
    variance = sum((x - mean) ** 2 for x in edges) / max(len(edges), 1)
    bright_fraction = sum(x >= 250 for x in pixels) / len(pixels)
    return dict(laplacian_variance=round(variance, 3), bright_fraction=round(bright_fraction, 4),
                possible_blur=variance < 30, possible_glare=bright_fraction > .15,
                heuristic=True, analysis_size=[width, height])


class CaptureSessions:
    def __init__(self, store: FrameStore):
        self.store = store
        self.lock = threading.RLock()
        with closing(store._connect()) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS capture_sweeps
                (id TEXT PRIMARY KEY, state TEXT NOT NULL)""")
            connection.execute("CREATE TABLE IF NOT EXISTS capture_quality (frame_id TEXT PRIMARY KEY, signals TEXT NOT NULL)")

    def _read(self, sweep_id):
        with closing(self.store._connect()) as connection:
            row = connection.execute("SELECT state FROM capture_sweeps WHERE id=?", (sweep_id,)).fetchone()
        if row is None:
            raise KeyError("unknown capture sweep")
        return json.loads(row[0])

    def _write(self, state):
        with closing(self.store._connect()) as connection, connection:
            connection.execute("INSERT INTO capture_sweeps VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                               (state["id"], json.dumps(state)))

    def start(self, country, currency, start_id):
        now = datetime.now(timezone.utc)
        sweep = Sweep(id=start_id, captured_at=now, country=country, currency=currency)
        state = dict(id=sweep.id, country=country, currency=currency, started_at=now.isoformat(),
                     ended_at=None, status="capturing", revision=0, capture_gaps=0, end_id=None,
                     transport_complete=False)
        with self.lock:
            try:
                previous = self._read(sweep.id)
            except KeyError:
                previous = None
            if previous:
                if previous["country"] != country or previous["currency"] != currency:
                    raise ValueError("start ID already belongs to a different locale")
                return previous
            self._write(state)
        return state

    def snapshot(self, sweep_id):
        with self.lock:
            state = self._read(sweep_id)
            state["frames"] = self.store.manifest(sweep_id)["frames"]
            with closing(self.store._connect()) as connection:
                rows = connection.execute("SELECT frame_id,signals FROM capture_quality WHERE frame_id IN (SELECT id FROM frames WHERE sweep_id=?)", (sweep_id,)).fetchall()
            state["quality"] = {ref: json.loads(signals) for ref, signals in rows}
            return state

    def upload(self, capture, data):
        with self.lock:
            state = self._read(capture.sweep_id)
            with closing(self.store._connect()) as connection:
                entries = [json.loads(row[0]) for row in connection.execute("SELECT record FROM frames WHERE sweep_id=?", (capture.sweep_id,)).fetchall()]
            if state["status"] != "capturing":
                # An acknowledgement lost before close can still be recovered.
                record = next((x for x in entries if x["upload_id"] == capture.upload_id), None)
                if record is None:
                    raise ValueError("capture is closed; new frames are rejected")
            if any(x["media_sequence"] == capture.media_sequence and x["upload_id"] != capture.upload_id for x in entries):
                raise ValueError("media sequence already belongs to a different capture")
            record = self.store.save(capture, data)
            # Optional signal computation cannot roll back a durably saved frame.
            try:
                signals = quality_signals(data)
            except Exception:
                signals = {"heuristic": True, "unavailable": True}
            try:
                with closing(self.store._connect()) as connection, connection:
                    connection.execute("INSERT INTO capture_quality VALUES (?,?) ON CONFLICT(frame_id) DO UPDATE SET signals=excluded.signals", (record.id, json.dumps(signals)))
            except Exception:
                signals["persistence_unavailable"] = True
            return {"frame": record.model_dump(mode="json"), "quality": signals, "durable": True}

    def end(self, sweep_id, end_id, capture_gaps):
        with self.lock:
            state = self._read(sweep_id)
            if state["status"] == "closed":
                if state["end_id"] != end_id or state["capture_gaps"] != capture_gaps:
                    raise ValueError("end request conflicts with already closed capture")
                return self.snapshot(sweep_id)
            frames = self.store.manifest(sweep_id)["frames"]
            state.update(status="closed", ended_at=datetime.now(timezone.utc).isoformat(),
                         revision=state["revision"] + 1, end_id=end_id, capture_gaps=capture_gaps,
                         transport_complete=bool(frames) and capture_gaps == 0)
            self._write(state)
            self.store.write_manifest(sweep_id)
            return self.snapshot(sweep_id)
