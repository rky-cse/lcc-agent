"""Single-shelf replay smoke; optional one live Gemini synthetic-image call."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image,ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_claim.capture_store import CaptureInput,FrameStore
from library_claim.packet import json_text
from library_claim.spine_detection import DetectionRequest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--gemini",action="store_true")
    parser.add_argument("--key-file",type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise FileExistsError("choose a fresh smoke directory")
    root.mkdir(parents=True)
    image = Image.new("RGB",(1920,1080),"#ded9ce")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80,120,1840,1020),fill="#665344")
    draw.rectangle((120,160,1800,970),fill="#35302c")
    draw.rectangle((120,900,1800,940),fill="#aa8359")
    truths = []
    colours = ["#a73937","#3a779a","#40895b","#af943e"]
    for i,(left,right) in enumerate([(260,365),(375,505),(515,620),(630,750)]):
        box = (left,310,right,895)
        draw.rectangle(box,fill=colours[i],outline="#d2c6a2",width=3)
        draw.line((left+8,330,right-8,330),fill="white",width=3)
        draw.text((left+15,360),"BOOK",fill="white")
        draw.text((left+15,390),str(i+1),fill="white")
        draw.line((left+8,855,right-8,855),fill="white",width=3)
        truths.append(dict(id=f"upright-{i}",kind="book_spine",orientation="upright",box_px=box))
    for i,(top,bottom) in enumerate([(755,820),(830,895)]):
        box = (1020,top,1520,bottom)
        draw.rectangle(box,fill=["#805b8a","#385c8a"][i],outline="#d2c6a2",width=3)
        draw.text((1070,top+24),f"BOOK {i+5} - AUTHOR",fill="white")
        truths.append(dict(id=f"horizontal-{i}",kind="book_spine",orientation="horizontal",box_px=box))
    draw.rectangle((210,730,250,895),fill="#202427")
    draw.rectangle((190,870,275,895),fill="#202427")
    truths.append(dict(id="bookend",kind="non_book",orientation="unknown",box_px=(190,730,275,895)))
    original = root/"synthetic-shelf.png"
    image.save(original)
    store = FrameStore(root/"store")
    record = store.ingest_file(CaptureInput(sweep_id="synthetic-m04a",upload_id="shelf-1",media_sequence=0,
        captured_at=datetime.now(timezone.utc),source="file_import",synthetic=True),original)
    request = DetectionRequest(sweep_id=record.sweep_id,frame_ref=record.id,frame_sha256=record.sha256,
        shelf_id="fixture-shelf",shelf_region_px=(120,160,1800,940),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
    input_path = root/"input.json"
    input_path.write_text(json_text(request.model_dump())+"\n",encoding="utf-8")
    (root/"ground-truth.json").write_text(json.dumps(dict(synthetic=True,book_count=6,objects=truths,
        frame_sha256=record.sha256),indent=2)+"\n",encoding="utf-8")
    objects = []
    for truth in truths:
        x0,y0,x1,y1 = truth["box_px"]
        objects.append(dict(kind=truth["kind"],orientation=truth["orientation"],
            polygon_1000=[(x*1000/1920,y*1000/1080) for x,y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]],reason="synthetic replay, not detector inference"))
    response_path = root/"replay-response.json"
    response_path.write_text(json.dumps(dict(coverage="clear",objects=objects,unresolved_regions=[])),encoding="utf-8")
    command = [sys.executable,"-B","-m","library_claim.spine_detection","--store",str(store.root),"--input",str(input_path),"--output",str(root/"review")]
    if args.gemini:
        command += ["--gemini","--free-tier-confirmed"]
        if args.key_file:
            command += ["--key-file",str(args.key_file)]
    else:
        command += ["--response",str(response_path)]
    subprocess.run(command,check=True,cwd=Path(__file__).resolve().parents[1])
    result = json.loads((root/"review"/"detection_result.json").read_text())
    assert result["synthetic"] and result["provisional"] and not result["coverage_verified"]
    assert hashlib.sha256((root/"review"/"original.png").read_bytes()).hexdigest()==record.sha256
    if not args.gemini:
        assert result["provisional_shelf_count"]==6 and len(result["books"])==6
        assert sum(p["status"]=="excluded" for p in result["proposals"])==1
        assert all(not b["title"] and b["spine_height_cm"] is None for b in result["books"])
        print("Replay boundary smoke passed: six candidates, one excluded bookend; not an inference accuracy test")
    else:
        print(f'Live provider smoke outcome: {result["stage_result"]["status"]}; observed proposals={result["provisional_observed_count"]}; synthetic truth=6')


if __name__=="__main__":
    main()
