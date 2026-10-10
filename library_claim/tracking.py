"""M04b1: durable, explicitly reviewed physical identity associations.

No title deduplication or automatic cross-view matching. Detection artifacts
are recomputed against immutable originals before entering the ledger.
"""

import argparse
import hashlib
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .capture_store import FrameStore
from .models import Book, Contract, StageResult
from .packet import json_text
from .spine_detection import DetectionRequest, DetectionResponse, process_response, validate_frame


class Decision(Contract):
    observation_id: str = Field(min_length=1)
    action: Literal["new", "same", "unresolved"]
    track_id: str | None
    provenance: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def target(self):
        if (self.action == "same") != bool(self.track_id):
            raise ValueError("only same-book decisions require a target track")
        return self


class TrackingCommand(Contract):
    command_id: str = Field(min_length=1, max_length=128)
    sweep_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    operation: Literal["import", "resolve", "ownership"]
    detection_result_sha256: str | None
    decisions: Annotated[list[Decision], Field(max_length=256)]
    track_id: str | None
    owned: bool | None
    provenance: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def shape(self):
        if self.operation == "import":
            if not self.detection_result_sha256 or len(self.detection_result_sha256) != 64:
                raise ValueError("import requires the exact detection result SHA256")
            if any(c not in "0123456789abcdef" for c in self.detection_result_sha256):
                raise ValueError("invalid result SHA256")
        elif self.detection_result_sha256 is not None:
            raise ValueError("only import has detection evidence")
        if self.operation == "ownership":
            if not self.track_id or self.owned is None or self.decisions:
                raise ValueError("ownership requires target, boolean and no decisions")
        elif self.track_id is not None or self.owned is not None:
            raise ValueError("identity commands cannot change ownership")
        if self.operation == "resolve" and (not self.decisions or any(d.action == "unresolved" for d in self.decisions)):
            raise ValueError("resolve requires conclusive association decisions")
        ids = [d.observation_id for d in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate observation decision")
        return self


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_bundle(store, directory, expected_hash):
    def read(name):
        data = (Path(directory) / name).read_bytes()
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("detection artifact exceeds import limit")
        return data
    raw = read("detection_result.json")
    if digest(raw) != expected_hash:
        raise ValueError("detection result hash mismatch")
    result = json.loads(raw)
    request = DetectionRequest.model_validate_json(read("detection_input.json"))
    frame = validate_frame(store, request)
    stage = result["stage_result"]
    StageResult.model_validate(stage)
    if stage["stage"] != "single_shelf_detection" or stage["evidence_refs"] != [frame.id]:
        raise ValueError("incorrect detection stage/evidence")
    if stage["sweep_id"] != request.sweep_id or result["frame_ref"] != frame.id or result["frame_sha256"] != frame.sha256:
        raise ValueError("detection artifact identity mismatch")
    response = None
    if stage["status"] in {"success", "partial"}:
        response = DetectionResponse.model_validate_json(read("detector_response.json"))
        recomputed = process_response(store, request, response, result["provider"])
        for key, value in recomputed.items():
            if json.loads(json_text(value)) != result.get(key):
                raise ValueError("detection result differs from validated response")
    elif stage["status"] == "unavailable":
        if (result["proposals"] or result["books"] or result["provisional_shelf_count"] is not None
                or result["provisional_observed_count"] is not None or not stage["errors"] or not result["review_queue"]):
            raise ValueError("invalid unavailable detection")
    else:
        raise ValueError("unsupported detection stage status")
    fingerprint = digest(json_text(dict(request=request.model_dump(), response=response.model_dump() if response else None,
                                       provider=result["provider"])).encode())
    if result["input_sha256"] != fingerprint or stage["job_id"] != fingerprint:
        raise ValueError("detection input fingerprint mismatch")
    return dict(request=request.model_dump(mode="json"), response=response.model_dump(mode="json") if response else None,
                result=result, result_sha256=expected_hash, synthetic=frame.synthetic)


class TrackStore:
    def __init__(self, frames):
        self.frames = frames
        with closing(frames._connect()) as db:
            db.execute("CREATE TABLE IF NOT EXISTS physical_inventory (sweep_id TEXT PRIMARY KEY, state TEXT NOT NULL)")
            db.commit()

    @staticmethod
    def _read(db, sweep_id):
        row = db.execute("SELECT state FROM physical_inventory WHERE sweep_id=?", (sweep_id,)).fetchone()
        return json.loads(row[0]) if row else dict(schema_version="1.0", sweep_id=sweep_id, revision=0,
                                                 tracks={}, observations={}, imports={}, events=[])

    def apply(self, command, bundle=None):
        command = TrackingCommand.model_validate(command.model_dump())
        evidence = None
        if command.operation == "import":
            if bundle is None:
                raise ValueError("import requires a detection bundle directory")
            evidence = load_bundle(self.frames, bundle, command.detection_result_sha256)
            if evidence["request"]["sweep_id"] != command.sweep_id:
                raise ValueError("cross-sweep detection import")
        elif bundle is not None:
            raise ValueError("unexpected detection bundle")
        fingerprint = digest(json_text(command.model_dump()).encode())
        with closing(self.frames._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._read(db, command.sweep_id)
            self._verify(state)
            for event in state["events"]:
                if event["command"]["command_id"] == command.command_id:
                    if event["command_sha256"] != fingerprint:
                        raise ValueError("command ID reused with different payload")
                    return self._snapshot(state)  # exact retries do not add revisions
            if command.expected_revision != state["revision"]:
                raise ValueError("stale inventory revision; reload before deciding identity")
            if len(state["events"]) >= 10000 or len(state["observations"]) + len(command.decisions) > 10000:
                raise ValueError("inventory ledger limit exceeded")
            if evidence is not None:
                request, result = evidence["request"], evidence["result"]
                key = request["frame_ref"] + ":" + request["shelf_id"]
                if key in state["imports"]:
                    raise ValueError("frame/shelf already imported; reanalysis requires a future explicit replacement operation")
                candidates = [p for p in result["proposals"] if p["status"] == "candidate"]
                if {p["observation_id"] for p in candidates} != {d.observation_id for d in command.decisions}:
                    raise ValueError("every validated candidate requires exactly one decision")
                for p in candidates:
                    oid = p["observation_id"]
                    if oid in state["observations"]:
                        raise ValueError("observation already exists")
                    state["observations"][oid] = dict(id=oid, frame_ref=request["frame_ref"],
                        frame_sha256=request["frame_sha256"], shelf_id=request["shelf_id"],
                        polygon_px=p["polygon_px"], orientation=p["orientation"], track_id=None,
                        synthetic=evidence["synthetic"], detection_result_sha256=command.detection_result_sha256)
                state["imports"][key] = evidence
            if command.operation == "ownership":
                if command.track_id not in state["tracks"]:
                    raise ValueError("unknown ownership target")
                state["tracks"][command.track_id]["owned"] = command.owned
            else:
                for decision in command.decisions:
                    obs = state["observations"].get(decision.observation_id)
                    if obs is None or obs["track_id"] is not None:
                        raise ValueError("decision must target an unresolved observation")
                    if decision.action == "unresolved":
                        continue
                    if decision.action == "new":
                        tid = "book-" + digest((command.sweep_id + "\0" + obs["id"]).encode())[:24]
                        state["tracks"][tid] = dict(id=tid, shelf_id=obs["shelf_id"], owned=True, observations=[])
                    else:
                        tid = decision.track_id
                        if tid not in state["tracks"]:
                            raise ValueError("unknown same-book target")
                    track = state["tracks"][tid]
                    if track["shelf_id"] != obs["shelf_id"]:
                        raise ValueError("cross-shelf identity requires an explicit relocation operation")
                    if any(state["observations"][oid]["frame_ref"] == obs["frame_ref"] for oid in track["observations"]):
                        raise ValueError("two detections in one frame cannot be merged into one physical book")
                    obs["track_id"] = tid
                    track["observations"].append(obs["id"])
            state["revision"] += 1
            state["events"].append(dict(revision=state["revision"], recorded_at=datetime.now(timezone.utc).isoformat(),
                                        command_sha256=fingerprint, command=command.model_dump(mode="json")))
            db.execute("INSERT INTO physical_inventory VALUES (?,?) ON CONFLICT(sweep_id) DO UPDATE SET state=excluded.state",
                       (command.sweep_id, json_text(state)))
            db.commit()
            return self._snapshot(state)

    def snapshot(self, sweep_id):
        with closing(self.frames._connect()) as db:
            state = self._read(db, sweep_id)
        self._verify(state)
        return self._snapshot(state)

    def _verify(self, state):
        # Preserve the immutable evidence boundary on restart and mutation, too.
        for obs in state["observations"].values():
            frame = self.frames.get(obs["frame_ref"])
            if frame.sweep_id != state["sweep_id"] or frame.sha256 != obs["frame_sha256"]:
                raise ValueError("inventory frame integrity mismatch")
        for source in state["imports"].values():
            validate_frame(self.frames, DetectionRequest.model_validate(source["request"]))
        if state.get("identity_evidence"):
            with closing(self.frames._connect()) as db:
                for sha in state["identity_evidence"]:
                    row=db.execute("SELECT content FROM identity_artifacts WHERE sha256=?",(sha,)).fetchone()
                    if row is None or digest(row[0])!=sha:
                        raise ValueError("identity evidence missing or corrupted")

    @staticmethod
    def _snapshot(state):
        reviews = [dict(observation_id=o["id"], frame_ref=o["frame_ref"], reason="physical identity unresolved")
                   for o in state["observations"].values() if o["track_id"] is None]
        for source in state["imports"].values():
            result = source["result"]
            for row in result["review_queue"] + result["unresolved_regions"]:
                reviews.append(dict(frame_ref=result["frame_ref"], reason=row["reason"]))
            if result.get("coverage_assertion") == "uncertain":
                reviews.append(dict(frame_ref=result["frame_ref"], reason="detection coverage uncertain"))
        books = []
        tracks = sorted(state["tracks"].values(), key=lambda t: t["id"])
        for index, track in enumerate(tracks):
            first = state["observations"][track["observations"][0]]
            identity=track.get("bibliography")
            fields=dict(**identity["values"],status=identity["status"],id_confidence=None,
                        field_evidence=identity["field_evidence"]) if identity else {}
            books.append(Book(id=track["id"], shelf=track["shelf_id"], position=index, frame_ref=first["frame_ref"],
                              owned=track["owned"],**fields).model_dump(mode="json"))
            if identity:
                reason=("Edition record reviewed; physical binding is claimant-declared" if identity.get("accepted_edition_id")
                        else "Work reviewed; owned-copy edition identity unresolved")
                if identity["edition_status"]=="claimant_asserted_metadata": reason+="; claimant metadata requires verification"
                if identity["status"]=="needs_appraisal": reason+="; appraisal required"
                reviews.append(dict(ref_id=track["id"],frame_ref=first["frame_ref"],reason=reason))
        return dict(schema_version="1.0", sweep_id=state["sweep_id"], revision=state["revision"],
                    association_method="explicit_review", provisional=True, coverage_verified=False,
                    assigned_track_count=len(tracks), owned_assigned_track_count=sum(t["owned"] for t in tracks),
                    total_book_count=None, books=books, tracks=tracks, observations=list(state["observations"].values()),
                    review_queue=reviews, detection_sources=list(state["imports"].values()), events=state["events"],
                    **({"identity_evidence":state["identity_evidence"]} if "identity_evidence" in state else {}))


def main():
    parser = argparse.ArgumentParser(description="M04b1 reviewed physical inventory ledger")
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--command", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--sweep-id")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("choose a fresh inventory snapshot path")
    ledger = TrackStore(FrameStore(args.store))
    if args.command:
        if args.sweep_id:
            parser.error("use command or sweep-id, not both")
        command = TrackingCommand.model_validate_json(args.command.read_text(encoding="utf-8"))
        result = ledger.apply(command, args.bundle)
    else:
        if not args.sweep_id or args.bundle:
            parser.error("snapshot requires sweep-id and no bundle")
        result = ledger.snapshot(args.sweep_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json_text(result) + "\n", encoding="utf-8")
    print(f'Inventory revision {result["revision"]}: {result["assigned_track_count"]} assigned tracks; total unknown')


if __name__ == "__main__":
    main()
