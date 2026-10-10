"""M04b2: assisted planar registration and conservative association proposals."""
import argparse
import io
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image
from pydantic import Field

from .capture_store import FrameStore
from .models import Contract, StageError, StageResult
from .packet import json_text
from .planar import Point, Quad, area, convex, fit_quad_transform, inside, no_horizon, transform
from .spine_detection import intersection_polygon
from .tracking import TrackStore, TrackingCommand, digest, load_bundle


class LandmarkCheck(Contract):
    current_px: Point
    anchor_px: Point
    provenance: str = Field(min_length=1,max_length=1000)


class Registration(Contract):
    anchor_frame_ref: str
    anchor_frame_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    current_corners_px: Quad
    anchor_corners_px: Quad
    checks: Annotated[list[LandmarkCheck],Field(min_length=2,max_length=32)]
    same_physical_shelf_confirmed: bool
    coplanar_spines_confirmed: bool
    book_positions_unchanged_confirmed: bool
    lens_status: Literal["corrected","verified_negligible","unknown"]
    provenance: str = Field(min_length=1,max_length=2000)


class MatchPolicy(Contract):
    max_check_error_px: Annotated[float,Field(gt=0,allow_inf_nan=False)]
    min_registration_area_px2: Annotated[float,Field(gt=0,allow_inf_nan=False)]
    plausible_iou: Annotated[float,Field(gt=0,lt=1)]
    accepted_iou: Annotated[float,Field(gt=0,lt=1)]
    max_appearance_mae: Annotated[float,Field(gt=0,lt=1)]


class MatchingRequest(Contract):
    sweep_id: str
    expected_revision: int = Field(ge=0)
    command_id: str = Field(min_length=1,max_length=128)
    detection_result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    registration: Registration | None
    policy: MatchPolicy


def iou(a,b):
    clipped=intersection_polygon(a,b)
    intersection=area(clipped) if len(clipped)>=3 else 0
    union=area(a)+area(b)-intersection
    return intersection/union if union>0 else 0


def appearance(image, polygon):
    # Sample inset positions in a rectified 16x32 grid. Avoid polygon edges,
    # where background/neighbor contamination dominates narrow spine crops.
    h=fit_quad_transform([(0,0),(1,0),(1,1),(0,1)],polygon)
    pixels=image.load()
    samples=[]
    for y in range(32):
        for x in range(16):
            px,py=transform(h,(.1+.8*(x+.5)/16,.1+.8*(y+.5)/32))
            ix,iy=math.floor(px),math.floor(py)
            if not (0<=ix<image.width and 0<=iy<image.height):
                raise ValueError("appearance sample outside original frame")
            samples.extend(pixels[ix,iy])
    return samples


def validate_registration(store, request, source, snapshot):
    r=request.registration
    if r is None:
        raise ValueError("registration missing")
    if not (r.same_physical_shelf_confirmed and r.coplanar_spines_confirmed and r.book_positions_unchanged_confirmed):
        raise ValueError("same-shelf, coplanarity and unchanged-position assertions required")
    if r.lens_status=="unknown":
        raise ValueError("lens validity unresolved")
    anchor=store.get(r.anchor_frame_ref)
    current=store.get(source["request"]["frame_ref"])
    if anchor.sweep_id!=request.sweep_id or anchor.sha256!=r.anchor_frame_sha256:
        raise ValueError("anchor sweep/hash mismatch")
    if anchor.id==current.id or anchor.exif_orientation not in (None,1):
        raise ValueError("anchor must be a different, coordinate-compatible frame")
    shelf=source["request"]["shelf_id"]
    anchors=[s for s in snapshot["detection_sources"] if s["request"]["frame_ref"]==anchor.id and s["request"]["shelf_id"]==shelf]
    if len(anchors)!=1:
        raise ValueError("anchor frame/shelf is not in the inventory")
    for corners,frame in [(r.current_corners_px,current),(r.anchor_corners_px,anchor)]:
        if area(corners)<request.policy.min_registration_area_px2:
            raise ValueError("registration support too small")
        if any(not(0<=x<=frame.width and 0<=y<=frame.height) for x,y in corners):
            raise ValueError("registration corners outside original frame")
    h=fit_quad_transform(r.current_corners_px,r.anchor_corners_px)
    no_horizon(h,r.current_corners_px)
    errors=[]
    current_seen,anchor_seen=[],[]
    for check in r.checks:
        for point,corners,seen in [(check.current_px,r.current_corners_px,current_seen),(check.anchor_px,r.anchor_corners_px,anchor_seen)]:
            if not inside(point,corners) or any(math.dist(point,p)<=request.policy.max_check_error_px for p in list(corners)+seen):
                raise ValueError("checks must be distinct holdouts inside registration support")
            seen.append(point)
        error=math.dist(transform(h,check.current_px),check.anchor_px)
        if error>request.policy.max_check_error_px:
            raise ValueError("independent registration check failed")
        errors.append(error)
    # Reject reflection: corner correspondence must preserve image winding.
    def winding(poly):
        return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1]))
    if winding(r.current_corners_px)*winding(r.anchor_corners_px)<=0:
        raise ValueError("registration reflects the shelf")
    return h,anchors[0],dict(matrix=h,check_errors_px=errors,anchor_frame_ref=anchor.id,
                             current_frame_ref=current.id,provenance=r.provenance)


def propose(store, request, bundle):
    started=datetime.now(timezone.utc)
    request=MatchingRequest.model_validate(request.model_dump())
    if request.policy.accepted_iou<=request.policy.plausible_iou:
        raise ValueError("accepted IoU must exceed plausible IoU")
    source=load_bundle(store,bundle,request.detection_result_sha256)
    if source["request"]["sweep_id"]!=request.sweep_id:
        raise ValueError("current sweep mismatch")
    snapshot=TrackStore(store).snapshot(request.sweep_id)
    if snapshot["revision"]!=request.expected_revision:
        raise ValueError("stale inventory revision")
    current_frame=source["request"]["frame_ref"]
    shelf=source["request"]["shelf_id"]
    if any(s["request"]["frame_ref"]==current_frame and s["request"]["shelf_id"]==shelf for s in snapshot["detection_sources"]):
        raise ValueError("current frame/shelf already imported")
    candidates=[p for p in source["result"]["proposals"] if p["status"]=="candidate"]
    rows={p["observation_id"]:dict(observation_id=p["observation_id"],action="unresolved",track_id=None,
        reason="no validated registration",comparisons=[]) for p in candidates}
    registration=None
    try:
        h,anchor_source,registration=validate_registration(store,request,source,snapshot)
    except ValueError as error:
        failure=str(error)
    else:
        failure=None
        r=request.registration
        observations={o["id"]:o for o in snapshot["observations"]}
        anchors=[p for p in anchor_source["result"]["proposals"] if p["status"]=="candidate"]
        with Image.open(io.BytesIO(store.read(current_frame))) as raw_current, Image.open(io.BytesIO(store.read(r.anchor_frame_ref))) as raw_anchor:
            current_image,anchor_image=raw_current.convert("RGB"),raw_anchor.convert("RGB")
            features={p["observation_id"]:appearance(anchor_image,p["polygon_px"]) for p in anchors}
            for p in candidates:
                row=rows[p["observation_id"]]
                if not all(inside(q,r.current_corners_px) for q in p["polygon_px"]):
                    row["reason"]="outside registration support; extrapolation forbidden"
                    continue
                mapped=[transform(h,q) for q in p["polygon_px"]]
                row["mapped_polygon_px"]=mapped
                feature=appearance(current_image,p["polygon_px"])
                for a in anchors:
                    anchor_supported=all(inside(q,r.anchor_corners_px) for q in a["polygon_px"])
                    overlap=iou(mapped,a["polygon_px"])
                    if overlap>=request.policy.plausible_iou:
                        other=features[a["observation_id"]]
                        mae=sum(abs(x-y) for x,y in zip(feature,other))/(len(feature)*255)
                        obs=observations[a["observation_id"]]
                        row["comparisons"].append(dict(anchor_observation_id=obs["id"],track_id=obs["track_id"],
                            iou=overlap,appearance_mae=mae,anchor_supported=anchor_supported,
                            orientation_equal=p["orientation"]==a["orientation"]))
                # Model-reviewed ambiguous regions can conceal another book.
                obstacles=[a["polygon_px"] for a in anchor_source["result"]["proposals"] if a["status"]=="review"]
                obstacles += [a["polygon_px"] for a in anchor_source["result"]["unresolved_regions"]]
                current_obstacles=[a["polygon_px"] for a in source["result"]["proposals"] if a["status"]=="review"]
                current_obstacles += [a["polygon_px"] for a in source["result"]["unresolved_regions"]]
                row["blocked_by_anchor_review"]=(anchor_source["result"].get("coverage_assertion")=="uncertain"
                    or source["result"].get("coverage_assertion")=="uncertain"
                    or any(not convex(q) or area(intersection_polygon(mapped,q))>0 for q in obstacles)
                    or any(not convex(q) or area(intersection_polygon(p["polygon_px"],q))>0 for q in current_obstacles))
            # A plausible edge is retained even if appearance is poor. This
            # prevents selecting a convenient winner from a split/merge graph.
            degree={a["observation_id"]:sum(any(c["anchor_observation_id"]==a["observation_id"] for c in row["comparisons"]) for row in rows.values()) for a in anchors}
            for row in rows.values():
                if "mapped_polygon_px" not in row:
                    continue
                edges=row["comparisons"]
                row["reason"]="no unique one-to-one match; review identity"
                if len(edges)!=1 or row["blocked_by_anchor_review"]:
                    continue
                edge=edges[0]
                if (degree[edge["anchor_observation_id"]]==1 and edge["track_id"] is not None
                        and edge["iou"]>=request.policy.accepted_iou
                        and edge["appearance_mae"]<=request.policy.max_appearance_mae
                        and edge["anchor_supported"] and edge["orientation_equal"]):
                    row.update(action="same",track_id=edge["track_id"],reason="unique spatial/appearance proposal; physical identity unverified")
    result=dict(schema_version="1.0",association_method="assisted_planar_proposal",provisional=True,
        physical_identity_verified=False,synthetic=source["synthetic"],sweep_id=request.sweep_id,
        expected_revision=snapshot["revision"],registration=registration,registration_failure=failure,
        matches=list(rows.values()),new_tracks_created=0,requires_review=True,provider_calls=0,
        request=request.model_dump(mode="json"),current_detection_result_sha256=request.detection_result_sha256)
    result["baseline_inventory_sha256"]=digest(json_text(snapshot).encode())
    result["anchor_detection_result_sha256"]=anchor_source["result_sha256"] if registration else None
    fingerprint=digest(json_text(dict(request=request.model_dump(),baseline=result["baseline_inventory_sha256"])).encode())
    status="unavailable" if failure else "partial" if any(r["action"]=="unresolved" for r in rows.values()) else "success"
    result["stage_result"]=StageResult(sweep_id=request.sweep_id,job_id=fingerprint,input_revision=snapshot["revision"],
        stage="shelf_association_proposal",status=status,started_at=started,finished_at=datetime.now(timezone.utc),
        evidence_refs=list(dict.fromkeys([current_frame]+([request.registration.anchor_frame_ref] if request.registration else []))),
        errors=[StageError(code="registration_unavailable",reason=failure,retryable=False,ref_id=shelf,field="registration")] if failure else [],
        warnings=["Assisted registration and heuristic appearance proposals require review; physical identity is unverified."]).model_dump(mode="json")
    # Timing diagnostics must not change a retry's proposed command payload.
    proof=digest(json_text({k:v for k,v in result.items() if k!="stage_result"}).encode())
    result["proposal_sha256"]=proof
    command=TrackingCommand(command_id=request.command_id,sweep_id=request.sweep_id,expected_revision=snapshot["revision"],
        operation="import",detection_result_sha256=request.detection_result_sha256,
        decisions=[dict(observation_id=row["observation_id"],action=row["action"],track_id=row["track_id"],
                        provenance=f'assisted proposal {proof}: {row["reason"]}') for row in rows.values()],
        track_id=None,owned=None,provenance=f"review required; matching proposal SHA256 {proof}")
    return result,command


def main():
    parser=argparse.ArgumentParser(description="M04b2 association proposal; does not mutate inventory")
    for name in ("store","input","bundle","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError("choose a fresh proposal directory")
    request=MatchingRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
    result,command=propose(FrameStore(args.store),request,args.bundle)
    args.output.mkdir(parents=True)
    (args.output/"matching_result.json").write_text(json_text(result)+"\n",encoding="utf-8")
    (args.output/"proposed_command.json").write_text(json_text(command.model_dump())+"\n",encoding="utf-8")
    print(f'Proposed same-book links: {sum(r["action"]=="same" for r in result["matches"])}; review required')


if __name__=="__main__":
    main()
