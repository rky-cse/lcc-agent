"""M03a synthetic saved-frame -> independent CLI -> portable packet smoke."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

# Script execution puts scripts/ on sys.path; use the repository explicitly.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.packet import json_text
from library_claim.planar import MeasurementRequest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise FileExistsError("choose a fresh smoke directory")
    root.mkdir(parents=True)
    def project(point):
        x,y = point
        d = .004*x+.006*y+1
        return ((30*x+4*y+200)/d,(3*x+25*y+120)/d)
    objects = [dict(id="upright",physical=[(15,2),(17.5,2),(17.5,25),(15,25)],expected=[23,2.5]),
               dict(id="horizontal",physical=[(20,2),(20,5),(42,5),(42,2)],expected=[22,3]),
               dict(id="off-plane",physical=[(30,8),(34,8),(34,27),(30,27)],expected=None)]
    ref = [project(p) for p in [(0,0),(10,0),(10,20),(0,20)]]
    image = Image.new("RGB",(1920,1080),"#263445")
    draw = ImageDraw.Draw(image)
    draw.text((70,20),"SYNTHETIC M03a: reference 10 x 20 cm; NOT REAL MEASUREMENT",fill="white")
    draw.polygon(ref,fill="#336655",outline="white",width=3)
    draw.ellipse((project((5,10))[0]-4,project((5,10))[1]-4,
                  project((5,10))[0]+4,project((5,10))[1]+4),fill="white")
    for item in objects:
        item["pixels"] = [project(p) for p in item["physical"]]
        draw.polygon(item["pixels"],fill="#995d29",outline="white",width=3)
    original = root/"synthetic-scene.png"
    image.save(original)
    store = FrameStore(root/"store")
    record = store.ingest_file(CaptureInput(sweep_id="synthetic-m03a",upload_id="scene-1",media_sequence=0,
          captured_at=datetime.now(timezone.utc),source="file_import",synthetic=True),original)
    request = MeasurementRequest.model_validate(dict(sweep_id=record.sweep_id,
        reference=dict(id="synthetic-reference",frame_ref=record.id,frame_sha256=record.sha256,
            plane_id="synthetic-plane",width_cm=10,height_cm=20,width_uncertainty_cm=.1,height_uncertainty_cm=.2,
            dimensions_verified=True,dimension_provenance="independently specified synthetic scene",
            corners_px=ref,corner_tolerance_px=.5,coordinate_space="encoded_pixels",
            lens_status="verified_negligible",lens_provenance="synthetic pinhole projection",
            valid_region_px=[(100,50),(1500,50),(1500,1000),(100,1000)],validity_provenance="synthetic scene plane",
            check_points=[dict(pixel=project((5,10)),plane_cm=(5,10),provenance="synthetic known centre")]),
        policy=dict(min_reference_area_px2=10000,max_check_error_cm=.1,max_opposite_edge_relative_difference=.1,
                    max_corner_cosine=.1,max_sensitivity_relative_change=.15),
        spines=[dict(id=item["id"],frame_ref=record.id,plane_id="synthetic-plane",corners_px=item["pixels"],
                    corner_tolerance_px=.5,coplanarity_confirmed=item["expected"] is not None,
                    coplanarity_provenance="synthetic scene declaration",annotation_source="developer_annotated") for item in objects]))
    input_path = root/"input.json"
    input_path.write_text(json_text(request.model_dump())+"\n",encoding="utf-8")
    result = subprocess.run([sys.executable,"-B","-m","library_claim.measurement","--store",str(store.root),
           "--input",str(input_path),"--output",str(root/"packet"),"--country","IN","--currency","INR",
           "--currency-decimal-places","2","--exclusion-basis","missing_any_component"],
           cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True,text=True)
    measured = json.loads((root/"packet"/"measurement_result.json").read_text())
    packet = json.loads((root/"packet"/"claim_packet.json").read_text())
    assert measured["synthetic"] and measured["stage_result"]["status"] == "partial"
    for item,actual in zip(objects,measured["results"]):
        assert [actual["spine_height_cm"],actual["spine_thickness_cm"]] == (item["expected"] or [None,None])
    assert len(packet["books"]) == 3
    assert packet["totals"]["shelf_run_m"] is None
    assert packet["coverage"]["shelf_run_measured_m"] == .055
    assert packet["totals"]["books_replacement_cost"] == 0
    assert (root/"packet"/record.path).read_bytes() == original.read_bytes()
    (root/"ground-truth.json").write_text(json.dumps(dict(synthetic=True,objects=objects),indent=2)+"\n",encoding="utf-8")
    print(result.stdout.strip())
    print("Synthetic CLI smoke passed: 2 measured spines; 1 unknown retained; partial shelf run 0.055 m")


if __name__ == "__main__":
    main()
