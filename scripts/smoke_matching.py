"""Projective synthetic revisit with labeled detections; no provider calls."""
import argparse
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.matching import MatchingRequest, propose
from library_claim.packet import json_text
from library_claim.planar import fit_quad_transform, transform
from library_claim.spine_detection import DetectionRequest, DetectionResponse, export_detection
from library_claim.tracking import TrackStore, TrackingCommand, digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists():
        raise FileExistsError("choose a fresh smoke directory")
    root.mkdir(parents=True)
    frames=FrameStore(root/"store")
    ledger=TrackStore(frames)
    boxes=[[(200,160),(350,160),(350,800),(200,800)],
           [(390,160),(540,160),(540,800),(390,800)],
           [(650,680),(1000,680),(1000,780),(650,780)],
           [(1100,250),(1250,250),(1250,700),(1100,700)]]
    anchor_support=[(100,100),(1500,100),(1500,850),(100,850)]
    current_support=[(150,80),(1480,140),(1510,830),(80,860)]
    forward=fit_quad_transform(anchor_support,current_support)
    inverse=fit_quad_transform(current_support,anchor_support)

    def render(count):
        image=Image.new("RGB",(1600,900),(30,35,45))
        draw=ImageDraw.Draw(image)
        for i,box in enumerate(boxes[:count]):
            draw.polygon(box,fill=(120,55,150) if i<2 else (40,120,90),outline="white",width=3)
            x0,y0=box[0]
            x1,y1=box[2]
            for y in range(y0+20,y1-10,25):
                draw.line((x0+12,y,x1-12,y),fill=(205,180,220),width=4)
            draw.text((x0+12,y0+40),"SAME COPY LABEL" if i<2 else "BOOK",fill="white")
        return image

    def save(name,sequence,image,polygons):
        sink=io.BytesIO()
        image.save(sink,"PNG")
        frame=frames.save(CaptureInput(sweep_id="matching-smoke",upload_id=name,media_sequence=sequence,
            captured_at=datetime.now(timezone.utc),source="file_import",synthetic=True),sink.getvalue())
        request=DetectionRequest(sweep_id="matching-smoke",frame_ref=frame.id,frame_sha256=frame.sha256,shelf_id="a",
            shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
        response=DetectionResponse(coverage="clear",unresolved_regions=[],objects=[dict(kind="book_spine",
            orientation="horizontal" if i==2 else "upright",reason="labeled fixture outline; no model inference",
            polygon_1000=[(x/1.6,y/.9) for x,y in polygon]) for i,polygon in enumerate(polygons)])
        result=export_detection(frames,request,root/name,response)
        return frame,result,digest((root/name/"detection_result.json").read_bytes())

    anchor,anchor_result,anchor_hash=save("anchor",0,render(3),boxes[:3])
    initial=TrackingCommand(command_id="anchor",sweep_id="matching-smoke",expected_revision=0,operation="import",
        detection_result_sha256=anchor_hash,track_id=None,owned=None,provenance="synthetic initial copy labels",
        decisions=[dict(observation_id=b["id"],action="new",track_id=None,provenance="labeled distinct fixture copy") for b in anchor_result["books"]])
    first=ledger.apply(initial,root/"anchor")
    coefficients=[inverse[i][j]/inverse[2][2] for i,j in [(0,0),(0,1),(0,2),(1,0),(1,1),(1,2),(2,0),(2,1)]]
    warped=render(4).transform((1600,900),Image.Transform.PERSPECTIVE,coefficients,Image.Resampling.BICUBIC)
    current,current_result,current_hash=save("revisit",1,warped,[[transform(forward,p) for p in polygon] for polygon in boxes])
    checks=[]
    for p in [(750,300),(850,500),(1300,750)]:
        checks.append(dict(current_px=transform(forward,p),anchor_px=p,provenance="renderer holdout landmark, not used for fitting"))
    request=MatchingRequest(sweep_id="matching-smoke",expected_revision=1,command_id="reviewed-revisit",
        detection_result_sha256=current_hash,registration=dict(anchor_frame_ref=anchor.id,anchor_frame_sha256=anchor.sha256,
        current_corners_px=current_support,anchor_corners_px=anchor_support,checks=checks,
        same_physical_shelf_confirmed=True,coplanar_spines_confirmed=True,book_positions_unchanged_confirmed=True,
        lens_status="verified_negligible",provenance="known synthetic renderer plane and fixed physical positions"),
        policy=dict(max_check_error_px=2,min_registration_area_px2=10000,plausible_iou=.1,accepted_iou=.7,max_appearance_mae=.1))
    (root/"matching_input.json").write_text(json_text(request.model_dump())+"\n",encoding="utf-8")
    subprocess.run([sys.executable,"-m","library_claim.matching","--store",str(root/"store"),"--input",str(root/"matching_input.json"),
                    "--bundle",str(root/"revisit"),"--output",str(root/"proposal")],check=True)
    result=json.loads((root/"proposal/matching_result.json").read_text(encoding="utf-8"))
    command=TrackingCommand.model_validate_json((root/"proposal/proposed_command.json").read_text(encoding="utf-8"))
    # Evaluation labels are retained separately from matcher inputs.
    tracks_by_obs={o["id"]:o["track_id"] for o in first["observations"]}
    truth={new["id"]:tracks_by_obs[old["id"]] for old,new in zip(anchor_result["books"],current_result["books"])}
    truth[current_result["books"][-1]["id"]]=None
    correct=sum(d.track_id==truth[d.observation_id] for d in command.decisions)
    assert correct==4 and sum(d.action=="same" for d in command.decisions)==3
    assert ledger.snapshot("matching-smoke")==first  # proposing never mutates
    subprocess.run([sys.executable,"-m","library_claim.tracking","--store",str(root/"store"),
        "--command",str(root/"proposal/proposed_command.json"),"--bundle",str(root/"revisit"),
        "--output",str(root/"reviewed-snapshot.json")],check=True)
    subprocess.run([sys.executable,"-m","library_claim.tracking","--store",str(root/"store"),"--sweep-id","matching-smoke",
        "--output",str(root/"restart-snapshot.json")],check=True)
    after=json.loads((root/"restart-snapshot.json").read_text(encoding="utf-8"))
    assert after==json.loads((root/"reviewed-snapshot.json").read_text(encoding="utf-8"))
    assert after["assigned_track_count"]==3 and len(after["observations"])==7 and len(after["review_queue"])==1
    summary=dict(synthetic=True,provider_calls=0,registration_source="renderer annotated correspondences",
        physical_identity_accuracy_measured=False,proposed_links=3,unresolved_observations=1,
        correct_fixture_decisions=correct,fixture_decisions=4,assigned_tracks_after_review=3,restart_equal=True,
        policy=request.policy.model_dump(),total_book_count=None)
    (root/"fixture-truth.json").write_text(json_text(truth)+"\n",encoding="utf-8")
    (root/"smoke-summary.json").write_text(json_text(summary)+"\n",encoding="utf-8")
    print(json_text(summary))


if __name__=="__main__":
    main()
