"""M03b1: bounded CPU sparse reconstruction, without metric room claims."""

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .capture_store import FrameStore
from .models import Contract, Room, StageError, StageResult
from .packet import json_text


class ReconstructionPolicy(Contract):
    max_runtime_seconds: Annotated[int, Field(ge=1, le=180)]
    min_points3d: Annotated[int, Field(ge=1)]
    max_median_reprojection_error_px: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    min_median_triangulation_angle_deg: Annotated[float, Field(gt=0, lt=180)]


class PinholeCalibration(Contract):
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    fx: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    fy: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    cx: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    cy: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    coordinate_space: Literal["colmap_encoded_pixels"]
    independently_verified: bool
    provenance: str
    lens_status: Literal["corrected", "verified_negligible"]
    lens_provenance: str

    @model_validator(mode="after")
    def valid_principal_point(self):
        if self.cx >= self.width or self.cy >= self.height:
            raise ValueError("principal point outside encoded image")
        return self


class ReconstructionRequest(Contract):
    sweep_id: str = Field(min_length=1)
    frame_refs: Annotated[list[str], Field(min_length=3, max_length=12)]
    same_camera_and_zoom_confirmed: bool
    camera_provenance: str
    policy: ReconstructionPolicy
    camera_calibration: PinholeCalibration | None = None

    @model_validator(mode="after")
    def unique_frames(self):
        if len(set(self.frame_refs)) != len(self.frame_refs):
            raise ValueError("select distinct capture IDs")
        return self


def connectivity_gate(summary, expected_names, policy):
    """All selected images must register in one component; never cherry-pick."""
    models = summary["models"]
    if len(models) != 1:
        return "no single connected reconstruction of the selected frames"
    model = models[0]
    names = model["registered_names"]
    if len(names) != len(set(names)) or set(names) != set(expected_names):
        return "selected evidence includes unregistered images"
    if type(model["num_points3d"]) is not int or model["num_points3d"] < policy.min_points3d:
        return "insufficient reconstructed support points"
    for field in ("median_reprojection_error_px", "median_triangulation_angle_deg"):
        if model[field] is None or not math.isfinite(model[field]) or model[field] < 0:
            return "missing or nonfinite reconstruction diagnostics"
    if model["median_reprojection_error_px"] > policy.max_median_reprojection_error_px:
        return "median reprojection error exceeds selected policy"
    if model["median_triangulation_angle_deg"] < policy.min_median_triangulation_angle_deg:
        return "insufficient triangulation angle; rotation/low parallax cannot establish depth"
    if model["median_triangulation_angle_deg"] > 180:
        return "invalid triangulation angle"
    return None


def run_reconstruction(store, request, output):
    request = ReconstructionRequest.model_validate(request.model_dump())
    output = Path(output)
    if output.exists():
        raise FileExistsError("choose a fresh reconstruction output directory")
    started = datetime.now(timezone.utc)
    records = [store.get(ref) for ref in request.frame_refs]
    if any(r.sweep_id != request.sweep_id for r in records):
        raise ValueError("all reconstruction frames must belong to this sweep")
    output.mkdir(parents=True)
    images = output / "images"
    images.mkdir()
    manifest = []
    for record in records:
        data = store.read(record.id)
        name = Path(record.path).name
        (images / name).write_bytes(data)
        manifest.append(dict(frame_ref=record.id, name=name, sha256=record.sha256,
                             media_sequence=record.media_sequence, captured_at=record.captured_at,
                             synthetic=record.synthetic))
    fingerprint = hashlib.sha256(json_text(request.model_dump()).encode()).hexdigest()
    (output / "request.json").write_text(json_text(request.model_dump()) + "\n", encoding="utf-8")
    (output / "frames.json").write_text(json_text(manifest) + "\n", encoding="utf-8")
    reason, code, status, summary, elapsed = None, None, "unavailable", None, None
    if not request.same_camera_and_zoom_confirmed or not request.camera_provenance.strip():
        reason, code = "same-camera/fixed-zoom input is not confirmed", "camera_validity_unknown"
    elif len({(r.width, r.height) for r in records}) != 1:
        reason, code = "shared-camera images have different encoded resolutions", "camera_validity_unknown"
    elif any(r.exif_orientation not in (None, 1) for r in records):
        reason, code = "EXIF orientation requires an explicit coordinate adapter", "coordinate_adapter_missing"
    elif len({r.sha256 for r in records}) < 3:
        reason, code = "fewer than three byte-distinct views", "insufficient_views"
    elif request.camera_calibration and (not request.camera_calibration.independently_verified
            or not request.camera_calibration.provenance.strip() or not request.camera_calibration.lens_provenance.strip()
            or (request.camera_calibration.width,request.camera_calibration.height) != (records[0].width,records[0].height)):
        reason, code = "camera calibration provenance or resolution is invalid", "camera_validity_unknown"
    elif importlib.util.find_spec("pycolmap") is None:
        reason, code = "optional pinned reconstruction environment is not installed", "backend_unavailable"
    else:
        worker_path = output / "worker-result.json"
        command = [sys.executable, "-B", "-m", "library_claim.reconstruction_worker",
                   "--work", str(output.resolve()), "--timeout", str(request.policy.max_runtime_seconds)]
        before = time.monotonic()
        try:
            with (output / "backend.log").open("wb") as log:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, shell=False,
                                         cwd=Path(__file__).resolve().parents[1],
                                         timeout=request.policy.max_runtime_seconds, check=False)
            if process.returncode != 0:
                reason, code, status = "native reconstruction worker exited unsuccessfully; inspect backend.log", "backend_failed", "failed"
            elif not worker_path.exists() or worker_path.stat().st_size > 2 * 1024 * 1024:
                reason, code, status = "worker summary missing or exceeds size limit", "backend_failed", "failed"
            else:
                summary = json.loads(worker_path.read_text(encoding="utf-8"))
                reason = connectivity_gate(summary, [m["name"] for m in manifest], request.policy)
                code = "geometry_unavailable" if reason else None
                status = "unavailable" if reason else "connected_provisional"
        except subprocess.TimeoutExpired:
            reason, code, status = "reconstruction exceeded the selected runtime limit; worker terminated", "backend_timeout", "failed"
        except (ValueError, KeyError, TypeError) as error:
            reason, code, status = f"invalid worker diagnostics: {error}", "backend_failed", "failed"
        elapsed = time.monotonic() - before
    errors = [] if not reason else [StageError(code=code, reason=reason, retryable=False, ref_id="room", field="connected_geometry")]
    stage = StageResult(sweep_id=request.sweep_id, job_id=fingerprint, input_revision=0,
        stage="sparse_reconstruction", status="success" if status=="connected_provisional" else status,
        started_at=started, finished_at=datetime.now(timezone.utc), evidence_refs=request.frame_refs,
        errors=errors, warnings=["Sparse geometry is in arbitrary units. " + ("Intrinsics use a caller-verified fixed calibration." if request.camera_calibration else "Intrinsics are estimated, not independently calibrated."),
                                "Connectivity of selected images does not establish room coverage, scale or boundary accuracy."])
    artifacts = []
    for path in sorted((output / "sparse").rglob("*")) if (output / "sparse").exists() else []:
        if path.is_file():
            artifacts.append(dict(path=path.relative_to(output).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    result = dict(schema_version="1.0", algorithm="pycolmap-cpu-sparse-v1", synthetic=any(r.synthetic for r in records),
                  status=status, reason=reason, stage_result=stage.model_dump(), input_sha256=fingerprint,
                  backend_summary=summary, backend_elapsed_seconds=elapsed,
                  artifacts=artifacts, room=Room().model_dump(), measurement_status="unavailable",
                  measurement_reason="Metric scale, observed room boundaries and height have not been recovered in M03b1.")
    (output / "reconstruction_result.json").write_text(json_text(result) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description="M03b1 optional CPU sparse reconstruction feasibility")
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = ReconstructionRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
    result = run_reconstruction(FrameStore(args.store), request, args.output)
    print(f'Reconstruction: {result["status"]}; room metrics: unavailable; output: {args.output.resolve()}')


if __name__ == "__main__":
    main()
