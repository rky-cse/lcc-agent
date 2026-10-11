"""M03b2 saved-model integrity, calibrated poses, narrow metric room export."""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .capture_store import FrameStore
from .models import MeasurementEvidence, PacketInput, PacketPolicy, ReviewFinding, Room, StageError, StageResult, Sweep
from .packet import export_packet, json_text
from .planar import metric
from .reconstruction import ReconstructionRequest, connectivity_gate
from .room_geometry import RoomRequest, calculate_room


def verified_model(store,reconstruction,request):
    root = Path(reconstruction)
    result_bytes = (root/"reconstruction_result.json").read_bytes()
    if hashlib.sha256(result_bytes).hexdigest().lower() != request.reconstruction_result_sha256.lower():
        raise ValueError("reconstruction result hash mismatch")
    result = json.loads(result_bytes)
    raw_source = json.loads((root/"request.json").read_text(encoding="utf-8"))
    source = ReconstructionRequest.model_validate(raw_source)
    # Hash the saved schema representation; adding optional fields must not
    # invalidate the fingerprints of older uncalibrated M03b1 review bundles.
    fingerprint = hashlib.sha256(json_text(raw_source).encode()).hexdigest()
    if result["input_sha256"] != fingerprint or source.sweep_id != request.sweep_id:
        raise ValueError("reconstruction request fingerprint or sweep mismatch")
    manifest = json.loads((root/"frames.json").read_text(encoding="utf-8"))
    if len(manifest) != len(source.frame_refs) or {m["frame_ref"] for m in manifest} != set(source.frame_refs):
        raise ValueError("frame ledger differs from reconstruction selection")
    records = {}
    for entry in manifest:
        record = store.get(entry["frame_ref"])
        if record.sweep_id != request.sweep_id or entry["sha256"] != record.sha256 or entry["name"] != Path(record.path).name:
            raise ValueError("reconstruction frame identity/hash mismatch")
        image_path = root/"images"/entry["name"]
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != record.sha256:
            raise ValueError("reconstruction original image hash mismatch")
        records[record.id] = record
    if result["status"] != "connected_provisional" or connectivity_gate(result["backend_summary"],[m["name"] for m in manifest],source.policy):
        raise ValueError("reconstruction is not a qualified single connected model")
    if result["synthetic"] != any(r.synthetic for r in records.values()):
        raise ValueError("reconstruction synthetic label mismatch")
    component = str(result["backend_summary"]["models"][0]["model_id"])
    if not component.isdigit():
        raise ValueError("invalid reconstruction component")
    required = {f"sparse/{component}/{name}.bin" for name in ("cameras","images","points3D","frames","rigs")}
    ledger = {a["path"]:a["sha256"] for a in result["artifacts"]}
    if not required.issubset(ledger):
        raise ValueError("reconstruction model hash ledger is incomplete")
    for relative in required:
        path = PurePosixPath(relative)
        target = (root/str(path)).resolve()
        if not target.is_relative_to(root.resolve()) or hashlib.sha256(target.read_bytes()).hexdigest() != ledger[relative]:
            raise ValueError("saved reconstruction model hash mismatch")
    return source,result,records,root/"sparse"/component


def calibrated_views(source,result,model_path,records):
    calibration = source.camera_calibration
    if not source.same_camera_and_zoom_confirmed or not source.camera_provenance.strip() or calibration is None or not calibration.independently_verified or not calibration.provenance.strip() or not calibration.lens_provenance.strip():
        raise ValueError("metric room output requires independently verified fixed camera calibration")
    if result["backend_summary"]["settings"]["intrinsics"] != "verified_fixed":
        raise ValueError("estimated/refined camera intrinsics cannot produce metric room output")
    import pycolmap as pc
    if pc.__version__ != "4.2.1":
        raise ValueError("use the pinned PyCOLMAP 4.2.1 environment")
    model = pc.Reconstruction(model_path)
    names = {Path(r.path).name:r.id for r in records.values()}
    views = {}
    if any((r.width,r.height)!=(calibration.width,calibration.height) or r.exif_orientation not in (None,1) for r in records.values()):
        raise ValueError("saved-frame resolution/orientation differs from calibrated coordinate space")
    for image in model.images.values():
        if image.name not in names or not image.has_pose:
            raise ValueError("native model image differs from verified frame ledger")
        camera = model.cameras[image.camera_id]
        expected = [getattr(calibration,k) for k in ("fx","fy","cx","cy")]
        if camera.model_name != "PINHOLE" or (camera.width,camera.height) != (calibration.width,calibration.height) or len(camera.params)!=4 or any(not math.isclose(float(a),b,rel_tol=1e-10,abs_tol=1e-8) for a,b in zip(camera.params,expected)):
            raise ValueError("native model intrinsics differ from fixed calibration")
        pose = image.cam_from_world()
        views[names[image.name]] = dict(R=pose.rotation.matrix().tolist(),t=pose.translation.tolist(),
            fx=calibration.fx,fy=calibration.fy,cx=calibration.cx,cy=calibration.cy,width=camera.width,height=camera.height)
    if set(views) != set(records):
        raise ValueError("native model has unregistered selected frames")
    return views


def export_room(store,reconstruction,request,output,country,currency,aggregation):
    request = RoomRequest.model_validate(request.model_dump())
    output = Path(output)
    if output.exists():
        raise FileExistsError("choose a fresh room measurement directory")
    started = datetime.now(timezone.utc)
    source,model_result,records,model_path = verified_model(store,reconstruction,request)
    reason,geometry,room,evidence,views = None,None,Room(),[],None
    fingerprint = hashlib.sha256(json_text(request.model_dump()).encode()).hexdigest()
    try:
        views = calibrated_views(source,model_result,model_path,records)
        geometry = calculate_room(request,views)
        values = [metric(x) for x in geometry["dimensions_m"]]
        if min(values) <= 0:
            raise ValueError("dimension vanishes at computational output precision")
        for field,value in zip(("length_m","width_m","height_m"),values):
            setattr(room,field,value)
            evidence.append(MeasurementEvidence(id=f"room-{fingerprint[:20]}-{field}",ref_id="room",field=field,
                value=value,unit="m",frame_refs=source.frame_refs,scale_method="calibrated_multiview_reference",
                derivation=f"Developer observed corner triangulation, fixed intrinsics, anchor scale; input_sha256={fingerprint}; reconstruction_sha256={request.reconstruction_result_sha256}"))
        room.scale_method = "calibrated_multiview_reference"
    except (ValueError,ImportError) as error:
        reason = str(error)
    stage = StageResult(sweep_id=request.sweep_id,job_id=fingerprint,input_revision=0,stage="metric_room_feasibility",
        status="unavailable" if reason else "success",started_at=started,finished_at=datetime.now(timezone.utc),evidence_refs=source.frame_refs,
        warnings=["Developer annotations and independent calibration/reference/boundary assertions, not automated room detection.",
                  "Explored sensitivity excludes camera-pose/intrinsic uncertainty; physical accuracy is unverified."],
        errors=[StageError(code="room_measurement_unavailable",reason=reason,retryable=False,ref_id="room",field="room_dimensions")] if reason else [])
    result = dict(schema_version="1.0",algorithm="calibrated-annotated-room-v1",synthetic=any(r.synthetic for r in records.values()),
        input_sha256=fingerprint,reconstruction_result_sha256=request.reconstruction_result_sha256,
        reconstruction_request=source.model_dump(),reconstruction_artifacts=model_result["artifacts"],
        camera_views=views,
        stage_result=stage.model_dump(),room=room.model_dump(),reason=reason,geometry=geometry,measurements=[m.model_dump() for m in evidence])
    packet = PacketInput(sweep=Sweep(id=request.sweep_id,captured_at=min(r.captured_at for r in records.values()),country=country,currency=currency),
        room=room,frames=[r.packet_evidence() for r in records.values()],measurements=evidence,synthetic=result["synthetic"],
        review_queue=[ReviewFinding(ref_id="room",reason=reason)] if reason else [])
    export_packet(packet,store.root,output,aggregation)
    (output/"room_input.json").write_text(json_text(request.model_dump())+"\n",encoding="utf-8")
    (output/"room_result.json").write_text(json_text(result)+"\n",encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description="M03b2 calibrated annotated room feasibility")
    for name in ("store","reconstruction","input","output"):
        parser.add_argument(f"--{name}",type=Path,required=True)
    parser.add_argument("--country",required=True)
    parser.add_argument("--currency",required=True)
    parser.add_argument("--currency-decimal-places",type=int,required=True)
    parser.add_argument("--exclusion-basis",choices=["missing_any_component","missing_all_components"],required=True)
    args = parser.parse_args()
    request = RoomRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
    policy = PacketPolicy(currency_decimal_places=args.currency_decimal_places,shelf_run_basis="sum_spine_thickness",exclusion_basis=args.exclusion_basis)
    result = export_room(FrameStore(args.store),args.reconstruction,request,args.output,args.country,args.currency,policy)
    print(f'Room geometry: {result["stage_result"]["status"]}; output: {args.output.resolve()}')


if __name__=="__main__":
    main()
