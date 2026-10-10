"""Offline CLI/restart smoke with labeled synthetic shelf views, no inference."""
import argparse
import hashlib
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.packet import json_text
from library_claim.spine_detection import DetectionRequest, DetectionResponse, export_detection


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists():
        raise FileExistsError("choose a fresh smoke directory")
    root.mkdir(parents=True)
    store=FrameStore(root/"store")

    def source(name,shelf,sequence,count,shift=0):
        image=Image.new("RGB",(1600,900),(25,30,40))
        draw=ImageDraw.Draw(image)
        objects=[]
        for i in range(count):
            x=150+i*220+shift
            polygon=[(x,150),(x+150,150),(x+150,780),(x,780)]
            draw.polygon(polygon,fill=(120+20*i,70,160),outline="white")
            draw.text((x+10,250),"SAME TITLE",fill="white")
            objects.append(dict(kind="book_spine",orientation="upright",reason="labeled synthetic physical outline",
                polygon_1000=[(px/1.6,py/.9) for px,py in polygon]))
        sink=io.BytesIO()
        image.save(sink,"PNG")
        frame=store.save(CaptureInput(sweep_id="tracking-smoke",upload_id=name,media_sequence=sequence,
            captured_at=datetime.now(timezone.utc),source="file_import",synthetic=True),sink.getvalue())
        request=DetectionRequest(sweep_id="tracking-smoke",frame_ref=frame.id,frame_sha256=frame.sha256,
            shelf_id=shelf,shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
        result=export_detection(store,request,root/name,DetectionResponse(coverage="clear",objects=objects,unresolved_regions=[]))
        return result

    def decision(oid,action="new",tid=None):
        return dict(observation_id=oid,action=action,track_id=tid,provenance="labeled synthetic fixture; manually associated")

    def run(name,revision,operation="import",decisions=None,bundle=None,track=None,owned=None):
        command=dict(command_id=name,sweep_id="tracking-smoke",expected_revision=revision,operation=operation,
            detection_result_sha256=hashlib.sha256((root/bundle/"detection_result.json").read_bytes()).hexdigest() if bundle else None,
            decisions=decisions or [],track_id=track,owned=owned,provenance="synthetic smoke annotation")
        path=root/(name+"-command.json")
        path.write_text(json_text(command),encoding="utf-8")
        output=root/(name+"-snapshot.json")
        args=[sys.executable,"-m","library_claim.tracking","--store",str(root/"store"),"--command",str(path),"--output",str(output)]
        if bundle:
            args += ["--bundle",str(root/bundle)]
        subprocess.run(args,check=True)
        return json.loads(output.read_text(encoding="utf-8"))

    first=source("shelf-a","a",0,2)
    a=run("import-a",0,decisions=[decision(b["id"]) for b in first["books"]],bundle="shelf-a")
    second=source("shelf-b","b",1,2)
    b=run("import-b",1,decisions=[decision(book["id"]) for book in second["books"]],bundle="shelf-b")
    revisit=source("revisit-a","a",2,3,shift=35)
    targets={o["id"]:o["track_id"] for o in a["observations"]}
    decisions=[decision(new["id"],"same",targets[old["id"]]) for old,new in zip(first["books"],revisit["books"])]
    decisions.append(decision(revisit["books"][2]["id"],"unresolved"))
    c=run("import-revisit",2,decisions=decisions,bundle="revisit-a")
    assert c["assigned_track_count"]==4 and len(c["review_queue"])==1
    d=run("resolve-new",3,operation="resolve",decisions=[decision(revisit["books"][2]["id"])])
    e=run("exclude-borrowed",4,operation="ownership",track=d["books"][0]["id"],owned=False)
    subprocess.run([sys.executable,"-m","library_claim.tracking","--store",str(root/"store"),
                    "--sweep-id","tracking-smoke","--output",str(root/"restart-snapshot.json")],check=True)
    restored=json.loads((root/"restart-snapshot.json").read_text(encoding="utf-8"))
    assert restored==e and e["assigned_track_count"]==5 and e["owned_assigned_track_count"]==4
    assert len(e["observations"])==7 and e["total_book_count"] is None
    summary=dict(synthetic=True,provider_calls=0,association_method="explicit_review",physical_accuracy_measured=False,
        assigned_before_revisit=b["assigned_track_count"],assigned_after_ambiguous_revisit=c["assigned_track_count"],
        assigned_after_review=e["assigned_track_count"],owned_after_exclusion=e["owned_assigned_track_count"],
        revision=e["revision"],observations=len(e["observations"]),restart_equal=True,total_book_count=None)
    (root/"smoke-summary.json").write_text(json_text(summary)+"\n",encoding="utf-8")
    print(json_text(summary))


if __name__=="__main__":
    main()
