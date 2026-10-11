"""Saved-evidence planar measurement boundary and review CLI."""

import argparse
import base64
import hashlib
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .capture_store import FrameStore
from .models import Book, MeasurementEvidence, PacketInput, PacketPolicy, ReviewFinding, StageError, StageResult, Sweep
from .packet import export_packet, json_text
from .planar import (MeasurementRequest, area, convex, dimensions, fit_homography,
                     inside, metric, no_horizon, sensitivity, transform)


def measure(store: FrameStore, request: MeasurementRequest) -> dict:
    request = MeasurementRequest.model_validate(request.model_dump())
    started = datetime.now(timezone.utc)
    frame_ids = {s.frame_ref for s in request.spines}
    if request.reference:
        frame_ids.add(request.reference.frame_ref)
    frames = {ref:store.get(ref) for ref in frame_ids}
    if any(record.sweep_id != request.sweep_id for record in frames.values()):
        raise ValueError("measurement frames do not belong to the requested sweep")
    if request.reference and frames[request.reference.frame_ref].sha256.lower() != request.reference.frame_sha256.lower():
        raise ValueError("reference frame hash does not match saved original")
    reference, h, global_reason = request.reference, None, None
    checks = []

    def frame_bounds(points, record):
        if any(not (0 <= x < record.width and 0 <= y < record.height) for x,y in points):
            raise ValueError("annotation is outside encoded image bounds")

    if reference is None:
        global_reason = "no verified metric reference supplied"
    else:
        try:
            record = frames[reference.frame_ref]
            if record.exif_orientation not in (None, 1):
                raise ValueError("EXIF rotation requires an explicit coordinate adapter; this module accepts unrotated encoded pixels")
            if not reference.dimensions_verified or not reference.dimension_provenance.strip():
                raise ValueError("reference dimensions have no verified provenance assertion")
            if reference.lens_status == "unknown" or not reference.lens_provenance.strip():
                raise ValueError("lens distortion validity is unknown")
            if not reference.validity_provenance.strip():
                raise ValueError("plane validity region has no provenance assertion")
            frame_bounds(reference.corners_px + reference.valid_region_px + [p.pixel for p in reference.check_points],record)
            if not convex(reference.valid_region_px):
                raise ValueError("valid region must be a convex ordered polygon")
            if not all(inside(p,reference.valid_region_px) for p in reference.corners_px):
                raise ValueError("reference is outside its declared valid region")
            if area(reference.corners_px) < request.policy.min_reference_area_px2:
                raise ValueError("reference occupies too few pixels for the selected policy")
            h = fit_homography(reference.corners_px,reference.width_cm,reference.height_cm)
            no_horizon(h,reference.valid_region_px)
            if not reference.check_points:
                raise ValueError("no independent reference check point; four-corner exact fit is not validation")
            for point in reference.check_points:
                if not point.provenance.strip():
                    raise ValueError("independent check point has no provenance")
                if not inside(point.pixel,reference.valid_region_px):
                    raise ValueError("check point is outside plane validity region")
                if any(sum((a-b)**2 for a,b in zip(point.pixel,corner))<1e-12 for corner in reference.corners_px):
                    raise ValueError("check point duplicates a fitted corner")
                actual = transform(h,point.pixel)
                error = sum((a-b)**2 for a,b in zip(actual,point.plane_cm))**.5
                checks.append({"pixel":point.pixel,"expected_cm":point.plane_cm,"mapped_cm":actual,"error_cm":error,"provenance":point.provenance})
                if error > request.policy.max_check_error_cm:
                    raise ValueError("independent reference check error exceeds policy")
        except ValueError as error:
            global_reason = str(error)
            h = None

    results, evidence, reviews = [], [], []
    fingerprint = hashlib.sha256(json_text(request.model_dump()).encode()).hexdigest()
    for spine in request.spines:
        result = {"id":spine.id,"frame_ref":spine.frame_ref,"spine_height_cm":None,
                  "spine_thickness_cm":None,"status":"unavailable","reason":"",
                  "annotation_source":spine.annotation_source,"sensitivity_cm":None}
        try:
            if global_reason:
                raise ValueError(global_reason)
            if spine.frame_ref != reference.frame_ref:
                raise ValueError("single-frame calibration cannot be transferred to another view")
            if spine.plane_id != reference.plane_id or not spine.coplanarity_confirmed or not spine.coplanarity_provenance.strip():
                raise ValueError("spine coplanarity is not confirmed for this reference plane")
            frame_bounds(spine.corners_px,frames[spine.frame_ref])
            if not all(inside(point,reference.valid_region_px) for point in spine.corners_px):
                raise ValueError("spine is outside declared plane validity region")
            nominal = dimensions(h,spine.corners_px,request.policy)
            envelope = sensitivity(reference,spine,h,nominal)
            if any(max(abs(low-value),abs(high-value))/value > request.policy.max_sensitivity_relative_change
                   for (low,high),value in zip(envelope,nominal)):
                raise ValueError("declared input sensitivity exceeds measurement policy")
            height,thickness = map(metric,nominal)
            if min(height,thickness) <= 0:
                raise ValueError("dimension vanishes at output precision")
            result.update(status="measured",spine_height_cm=height,spine_thickness_cm=thickness,
                          sensitivity_cm={"height":[metric(x) for x in envelope[0]],"thickness":[metric(x) for x in envelope[1]],
                                          "method":"one_at_a_time_explored_envelope","confidence_bound":False})
            for field,value in [("spine_height_cm",height),("spine_thickness_cm",thickness)]:
                evidence.append(MeasurementEvidence(id=f"measure-{fingerprint[:16]}-{hashlib.sha256(spine.id.encode()).hexdigest()[:16]}-{field}",
                    ref_id=spine.id,field=field,value=value,unit="cm",frame_refs=[spine.frame_ref],
                    scale_method=f"planar_reference:{reference.id}",
                    derivation=f"Encoded-pixel developer polygon mapped by saved homography; opposite-edge mean; reference={reference.id}; input_sha256={fingerprint}"))
        except ValueError as error:
            result["reason"] = str(error)
            reviews.append({"ref_id":spine.id,"reason":f"spine dimensions unavailable: {error}"})
        results.append(result)
    measured = sum(r["status"] == "measured" for r in results)
    status = "success" if measured and measured == len(results) else "partial" if measured else "unavailable"
    stage = StageResult(sweep_id=request.sweep_id,job_id=fingerprint,input_revision=0,stage="planar_spine_feasibility",
                        status=status,started_at=started,finished_at=datetime.now(timezone.utc),evidence_refs=sorted(frame_ids),
                        errors=[StageError(code="measurement_unavailable",reason=r["reason"],retryable=False,ref_id=r["id"],field="spine_dimensions")
                                for r in results if r["status"]=="unavailable"],
                        warnings=["Developer annotations; coplanarity/dimension/lens validity are caller assertions, not automatically verified."])
    return {"schema_version":"1.0","algorithm":"planar-annotated-v1","synthetic":any(x.synthetic for x in frames.values()),
            "input_sha256":fingerprint,"stage_result":stage.model_dump(),"calibration_status":"unavailable" if global_reason else "accepted",
            "calibration_reason":global_reason,"homography_encoded_px_to_cm":h,"check_points":checks,
            "results":results,"measurements":[x.model_dump() for x in evidence],"review_queue":reviews}


def export_measurement(store, request, policy, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("choose a fresh measurement output directory")
    result = measure(store,request)
    frames = {ref:store.get(ref) for ref in result["stage_result"]["evidence_refs"]}
    # Locale is supplied explicitly to this exporter, never inferred from geometry.
    now = min(record.captured_at for record in frames.values())
    packet = PacketInput(sweep=Sweep(id=request.sweep_id,captured_at=now,country=policy["country"],currency=policy["currency"]),
        books=[Book(id=r["id"],frame_ref=r["frame_ref"],spine_height_cm=r["spine_height_cm"],spine_thickness_cm=r["spine_thickness_cm"]) for r in result["results"]],
        frames=[record.packet_evidence() for record in frames.values()],
        measurements=[MeasurementEvidence.model_validate(x) for x in result["measurements"]],
        review_queue=[ReviewFinding.model_validate(x) for x in result["review_queue"]],synthetic=result["synthetic"])
    export_packet(packet,store.root,output,policy["aggregation"])
    (output/"measurement_input.json").write_text(json_text(request.model_dump())+"\n",encoding="utf-8")
    (output/"measurement_result.json").write_text(json_text(result)+"\n",encoding="utf-8")
    for frame_ref,record in frames.items():
        original=base64.b64encode(store.read(frame_ref)).decode("ascii")
        shapes=[]
        if request.reference and request.reference.frame_ref==frame_ref:
            points=" ".join(f"{x},{y}" for x,y in request.reference.corners_px)
            shapes.append(f'<polygon points="{points}" fill="none" stroke="#00cc66" stroke-width="5"/>')
        for spine,r in zip(request.spines,result["results"]):
            if spine.frame_ref!=frame_ref:
                continue
            points=" ".join(f"{x},{y}" for x,y in spine.corners_px)
            label=f'{spine.id}: {r["spine_height_cm"]} x {r["spine_thickness_cm"]} cm' if r["status"]=="measured" else f'{spine.id}: UNAVAILABLE'
            x,y=spine.corners_px[0]
            shapes.append(f'<polygon points="{points}" fill="none" stroke="#ffae00" stroke-width="4"/><text x="{x}" y="{max(24,y-10)}" font-size="22" fill="white" stroke="black" stroke-width=".5">{escape(label)}</text>')
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {record.width} {record.height}"><image width="{record.width}" height="{record.height}" href="data:{record.mime_type};base64,{original}"/>'+"".join(shapes)+"</svg>"
        (output/f"overlay-{record.id}.svg").write_text(svg,encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(description="M03a annotated planar measurement feasibility")
    parser.add_argument("--store",type=Path,required=True); parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True); parser.add_argument("--country",required=True)
    parser.add_argument("--currency",required=True); parser.add_argument("--currency-decimal-places",type=int,required=True)
    parser.add_argument("--exclusion-basis",choices=["missing_any_component","missing_all_components"],required=True)
    args=parser.parse_args()
    request=MeasurementRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
    aggregation=PacketPolicy(currency_decimal_places=args.currency_decimal_places,shelf_run_basis="sum_spine_thickness",exclusion_basis=args.exclusion_basis)
    result=export_measurement(FrameStore(args.store),request,{"country":args.country,"currency":args.currency,"aggregation":aggregation},args.output)
    print(f'Measurement stage: {result["stage_result"]["status"]}; output: {args.output.resolve()}')


if __name__=="__main__":
    main()
