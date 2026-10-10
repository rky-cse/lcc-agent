"""M04a single-shelf proposal validation. Physical tracking is M04b."""

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from .capture_store import FrameStore
from .models import Book, Contract, StageError, StageResult
from .packet import json_text
from .planar import area, convex

Normalized = Annotated[float, Field(ge=0,le=1000,allow_inf_nan=False)]
Polygon = Annotated[list[tuple[Normalized,Normalized]],Field(min_length=4,max_length=4)]


class Proposal(Contract):
    kind: Literal["book_spine","non_book","ambiguous"]
    orientation: Literal["upright","horizontal","diagonal","unknown"]
    polygon_1000: Polygon  # [x,y], original image edges, not a preview/crop
    reason: str = Field(max_length=1000)


class UnresolvedRegion(Contract):
    polygon_1000: Polygon
    reason: str = Field(min_length=1,max_length=1000)


class DetectionResponse(Contract):
    coverage: Literal["clear","uncertain","no_visible_books"]
    objects: Annotated[list[Proposal],Field(max_length=256)]
    unresolved_regions: Annotated[list[UnresolvedRegion],Field(max_length=40)]


class DetectionPolicy(Contract):
    min_polygon_area_px2: Annotated[float,Field(gt=0,allow_inf_nan=False)]
    max_pair_overlap_fraction: Annotated[float,Field(gt=0,lt=1)]


class DetectionRequest(Contract):
    sweep_id: str = Field(min_length=1)
    frame_ref: str
    frame_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    shelf_id: str = Field(min_length=1,max_length=128)
    shelf_region_px: tuple[int,int,int,int]  # x_min,y_min,x_max,y_max
    policy: DetectionPolicy


def intersection_polygon(subject,clip):
    """Convex polygon clipping; does not merge or suppress physical copies."""
    orientation = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(clip,clip[1:]+clip[:1]))
    sign = 1 if orientation>0 else -1
    result = list(subject)
    for a,b in zip(clip,clip[1:]+clip[:1]):
        def distance(p):
            return sign*((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))
        previous = result
        result = []
        if not previous:
            break
        start = previous[-1]
        ds = distance(start)
        for end in previous:
            de = distance(end)
            if (ds>=0)!=(de>=0):
                fraction = ds/(ds-de)
                result.append(tuple(x+fraction*(y-x) for x,y in zip(start,end)))
            if de>=0:
                result.append(end)
            start,ds = end,de
    return result


def validate_frame(store,request):
    record = store.get(request.frame_ref)
    if record.sweep_id!=request.sweep_id or record.sha256.lower()!=request.frame_sha256.lower():
        raise ValueError("detection frame sweep/hash mismatch")
    x0,y0,x1,y1 = request.shelf_region_px
    if not (0<=x0<x1<=record.width and 0<=y0<y1<=record.height):
        raise ValueError("shelf region is outside original encoded image")
    if record.exif_orientation not in (None,1):
        raise ValueError("EXIF orientation requires an explicit coordinate adapter")
    return record


def process_response(store,request,response,provider):
    request = DetectionRequest.model_validate(request.model_dump())
    response = DetectionResponse.model_validate(response.model_dump())
    record = validate_frame(store,request)
    x0,y0,x1,y1 = request.shelf_region_px
    proposals,reviews = [],[]
    for index,item in enumerate(response.objects):
        polygon = [(x*record.width/1000,y*record.height/1000) for x,y in item.polygon_1000]
        row = dict(provider_index=index,kind=item.kind,orientation=item.orientation,polygon_px=polygon,
                   status="candidate",reason=item.reason,observation_id=None)
        if item.kind!="book_spine":
            row["status"] = "excluded" if item.kind=="non_book" else "review"
        elif not convex(polygon) or area(polygon)<request.policy.min_polygon_area_px2:
            row.update(status="review",reason="degenerate or too-small spine polygon")
        elif any(not (x0<=x<=x1 and y0<=y<=y1) for x,y in polygon):
            row.update(status="review",reason="proposal is outside selected shelf region")
        elif item.orientation=="unknown":
            row.update(status="review",reason="spine orientation unresolved")
        if row["status"]=="candidate":
            stable = dict(frame_ref=record.id,shelf_id=request.shelf_id,polygon_px=polygon,orientation=item.orientation)
            row["observation_id"] = "spine-"+hashlib.sha256(json_text(stable).encode()).hexdigest()[:24]
        proposals.append(row)
    # Evaluate all candidates before excluding overlaps, so A/B/C conflicts are
    # visible rather than dependent on provider ordering or suppression score.
    candidates = [p for p in proposals if p["status"]=="candidate"]
    conflicts = set()
    for i,a in enumerate(candidates):
        for b in candidates[i+1:]:
            overlap = intersection_polygon(a["polygon_px"],b["polygon_px"])
            ratio = area(overlap)/min(area(a["polygon_px"]),area(b["polygon_px"])) if len(overlap)>=3 else 0
            if ratio>request.policy.max_pair_overlap_fraction:
                conflicts.update((a["provider_index"],b["provider_index"]))
    for row in proposals:
        if row["provider_index"] in conflicts:
            row.update(status="review",reason="overlapping proposals; duplicate or split/merge ambiguity",observation_id=None)
        if row["status"]=="review":
            reviews.append(dict(provider_index=row["provider_index"],reason=row["reason"]))
    regions = []
    for region in response.unresolved_regions:
        polygon = [(x*record.width/1000,y*record.height/1000) for x,y in region.polygon_1000]
        if not convex(polygon):
            raise ValueError("unresolved region polygon is not convex/ordered")
        regions.append(dict(polygon_px=polygon,reason=region.reason))
    accepted = sorted((p for p in proposals if p["status"]=="candidate"),key=lambda p:(min(x for x,y in p["polygon_px"]),min(y for x,y in p["polygon_px"])))
    contradictory = response.coverage=="no_visible_books" and any(p["kind"]=="book_spine" for p in proposals)
    if contradictory:
        reviews.append(dict(provider_index=None,reason="coverage contradicts book proposals"))
    complete = response.coverage in {"clear","no_visible_books"} and not reviews and not regions and not contradictory
    return dict(algorithm="single-shelf-proposals-v1",synthetic=record.synthetic,provider=provider,
                coverage_assertion=response.coverage,coverage_verified=False,provisional=True,
                coordinate_space="original_encoded_pixel_edges",proposals=proposals,unresolved_regions=regions,
                review_queue=reviews,provisional_observed_count=len(accepted),
                provisional_shelf_count=len(accepted) if complete else None,
                books=[Book(id=p["observation_id"],shelf=request.shelf_id,position=i,frame_ref=record.id).model_dump() for i,p in enumerate(accepted)],
                frame_ref=record.id,frame_sha256=record.sha256)


def export_detection(store,request,output,response=None,provider="offline_replay",failure=None,usage=None,started_at=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError("choose a fresh detection output directory")
    started = started_at or datetime.now(timezone.utc)
    record = validate_frame(store,request)
    if failure is None:
        result = process_response(store,request,response,provider)
        status = "partial" if result["review_queue"] or result["unresolved_regions"] or result["provisional_shelf_count"] is None else "success"
    else:
        result = dict(synthetic=record.synthetic,provider=provider,provisional=True,coverage_verified=False,
                      frame_ref=record.id,frame_sha256=record.sha256,proposals=[],unresolved_regions=[],books=[],
                      provisional_observed_count=None,provisional_shelf_count=None,review_queue=[dict(reason=failure["reason"])])
        status = "unavailable"
    fingerprint = hashlib.sha256(json_text(dict(request=request.model_dump(),response=response.model_dump() if response else None,provider=provider)).encode()).hexdigest()
    errors = [StageError(code=failure["code"],reason=failure["reason"],retryable=failure.get("retryable",False),
                         ref_id=request.shelf_id,field="spine_detection")] if failure else []
    stage = StageResult(sweep_id=request.sweep_id,job_id=fingerprint,input_revision=0,stage="single_shelf_detection",
        status=status,started_at=started,finished_at=datetime.now(timezone.utc),evidence_refs=[record.id],errors=errors,
        warnings=["Model polygons/counts are provisional. Real detection precision/recall is unmeasured; no physical tracking or OCR."])
    result.update(schema_version="1.0",input_sha256=fingerprint,stage_result=stage.model_dump(),usage=usage)
    output.mkdir(parents=True)
    (output/"detection_input.json").write_text(json_text(request.model_dump())+"\n",encoding="utf-8")
    if response:
        (output/"detector_response.json").write_text(json_text(response.model_dump())+"\n",encoding="utf-8")
    (output/"detection_result.json").write_text(json_text(result)+"\n",encoding="utf-8")
    original = store.read(record.id)
    (output/("original"+Path(record.path).suffix)).write_bytes(original)
    image = base64.b64encode(original).decode("ascii")
    shapes = []
    for row in result["proposals"]:
        colour = "#40c980" if row["status"]=="candidate" else "#ffb346" if row["status"]=="review" else "#adb5bd"
        points = " ".join(f"{x},{y}" for x,y in row["polygon_px"])
        x,y = row["polygon_px"][0]
        shapes.append(f'<polygon points="{points}" fill="none" stroke="{colour}" stroke-width="4"/><text x="{x}" y="{max(24,y-8)}" fill="white" stroke="black" stroke-width=".5" font-size="22">{row["provider_index"]}: {row["status"]}</text>')
    for row in result["unresolved_regions"]:
        points = " ".join(f"{x},{y}" for x,y in row["polygon_px"])
        shapes.append(f'<polygon points="{points}" fill="#ffb346" fill-opacity=".2" stroke="#ffb346" stroke-dasharray="8 6" stroke-width="4"/>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {record.width} {record.height}"><image width="{record.width}" height="{record.height}" href="data:{record.mime_type};base64,{image}"/>'+"".join(shapes)+"</svg>"
    (output/"overlay.svg").write_text(svg,encoding="utf-8")
    rows = "".join(f'<tr><td>{p["provider_index"]}</td><td>{escape(p["kind"])}</td><td>{escape(p["orientation"])}</td><td>{escape(p["status"])}</td><td>{escape(p["reason"])}</td></tr>' for p in result["proposals"])
    reviews = "".join(f'<li>{escape(r["reason"])}</li>' for r in result["review_queue"]+result["unresolved_regions"])
    html = '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><title>M04a shelf review</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto;background:#15202b;color:white}svg{width:100%}td,th{padding:8px;border:1px solid #506070}table{border-collapse:collapse}</style>'
    html += f'<h1>M04a single-shelf review</h1><p>Stage: {status}. Synthetic: {record.synthetic}. Count proposals are provisional; coverage is unverified.</p><p>Observed proposals: {result["provisional_observed_count"]}; provisional shelf count: {result["provisional_shelf_count"]}. Green: candidate; orange: review; gray: non-book.</p>'+svg+f'<table><tr><th>#</th><th>Kind</th><th>Orientation</th><th>Status</th><th>Reason</th></tr>{rows}</table><ul>{reviews}</ul>'
    (output/"report.html").write_text(html,encoding="utf-8")
    return result


def main():
    from .vision_provider import ALLOWED_MODELS, request_detection, read_key
    parser = argparse.ArgumentParser(description="M04a one-shelf provisional spine proposals")
    for name in ("store","input","output"):
        parser.add_argument(f"--{name}",type=Path,required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--response",type=Path)
    group.add_argument("--gemini",action="store_true")
    parser.add_argument("--key-file",type=Path)
    parser.add_argument("--free-tier-confirmed",action="store_true")
    parser.add_argument("--model",choices=ALLOWED_MODELS,default="gemini-3.1-flash-lite")
    args = parser.parse_args()
    store = FrameStore(args.store)
    request = DetectionRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
    if args.output.exists():
        raise FileExistsError("choose a fresh detection output directory before a provider call")
    record = validate_frame(store,request)
    raw = None
    if args.gemini:
        if not args.free_tier_confirmed:
            raise ValueError("confirm the free-tier account; no paid fallback is supported")
        started = datetime.now(timezone.utc)
        response,failure,usage,raw = request_detection(read_key(args.key_file),store.read(record.id),record,request,args.model)
        try:
            result = export_detection(store,request,args.output,response,args.model,failure,usage,started)
        except ValueError:
            if args.output.exists():
                raise
            failure = dict(code="provider_invalid_geometry",reason="provider geometry failed local validation",retryable=False)
            result = export_detection(store,request,args.output,None,args.model,failure,usage,started)
    else:
        response = DetectionResponse.model_validate_json(args.response.read_text(encoding="utf-8"))
        result = export_detection(store,request,args.output,response)
    if raw is not None:
        (args.output/"provider_response.json").write_text(json_text(raw)+"\n",encoding="utf-8")
    print(f'Shelf detection: {result["stage_result"]["status"]}; provisional count: {result["provisional_shelf_count"]}; output: {args.output.resolve()}')


if __name__=="__main__":
    main()
