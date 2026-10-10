"""Actual fixed-intrinsic SfM -> annotated metric room -> packet smoke."""

import argparse
import hashlib
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.packet import json_text
from library_claim.reconstruction import PinholeCalibration, ReconstructionRequest
from library_claim.room_geometry import RoomRequest
from smoke_reconstruction import render_views


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise FileExistsError("choose a fresh smoke directory")
    root.mkdir(parents=True)
    images,truth = render_views()
    points = dict(a=(-.5,-.8,4),b=(.5,-.8,4),c=(-.5,-.3,4),d=(.5,-.3,4))
    for i,(x,y,z) in enumerate([(-1.5,1.4,4),(1.5,1.4,4),(1.5,1.4,8),(-1.5,1.4,8)]):
        points[f"f{i}"] = (x,y,z)
        points[f"t{i}"] = (x,-1.2,z)
    store = FrameStore(root/"store")
    observations = {name:[] for name in points}
    records = []
    for i,(image,(cx,_,_)) in enumerate(zip(images,truth["camera_centres"])):
        draw = ImageDraw.Draw(image)
        pixels = {}
        for name,(x,y,z) in points.items():
            u,v = round(960+1200*(x-cx)/z),round(540+1200*y/z)
            draw.ellipse((u-4,v-4,u+4,v+4),fill="white",outline="black",width=1)
            draw.text((u+7,v-7),name,fill="white")
            pixels[name] = (u+.5,v+.5)
        # Explicit synthetic wireframe makes fixture boundaries visible. It is
        # a geometry experiment, not imagery of a real room or a detector test.
        for prefix in ("f","t"):
            draw.line([pixels[f"{prefix}{j}"] for j in [0,1,2,3,0]],fill="gray",width=1)
        for j in range(4):
            draw.line([pixels[f"f{j}"],pixels[f"t{j}"]],fill="gray",width=1)
        sink = io.BytesIO()
        image.save(sink,"PNG")
        record = store.save(CaptureInput(sweep_id="synthetic-room",upload_id=f"view-{i}",media_sequence=i,
            captured_at=datetime.now(timezone.utc),source="file_import",synthetic=True),sink.getvalue())
        records.append(record)
        for name,pixel in pixels.items():
            observations[name].append(dict(frame_ref=record.id,pixel=pixel))
    calibration = PinholeCalibration(width=1920,height=1080,fx=1200,fy=1200,cx=960,cy=540,
        coordinate_space="colmap_encoded_pixels",independently_verified=True,provenance="independently specified synthetic pinhole renderer",
        lens_status="verified_negligible",lens_provenance="synthetic pinhole renderer, no distortion")
    reconstruction = ReconstructionRequest(sweep_id="synthetic-room",frame_refs=[r.id for r in records],
        same_camera_and_zoom_confirmed=True,camera_provenance="synthetic renderer",camera_calibration=calibration,
        policy=dict(max_runtime_seconds=120,min_points3d=100,max_median_reprojection_error_px=2,min_median_triangulation_angle_deg=2))
    (root/"reconstruction-input.json").write_text(json_text(reconstruction.model_dump())+"\n",encoding="utf-8")
    command = [sys.executable,"-B","-m","library_claim.reconstruction","--store",str(store.root),"--input",str(root/"reconstruction-input.json"),"--output",str(root/"reconstruction")]
    subprocess.run(command,check=True,cwd=Path(__file__).resolve().parents[1])
    reconstruction_bytes = (root/"reconstruction"/"reconstruction_result.json").read_bytes()
    assert json.loads(reconstruction_bytes)["status"]=="connected_provisional"
    request = RoomRequest(sweep_id="synthetic-room",reconstruction_result_sha256=hashlib.sha256(reconstruction_bytes).hexdigest(),
        coordinate_space="colmap_encoded_pixels",annotation_source="developer_annotated",
        points=[dict(id=name,observations=obs,corner_tolerance_px=.5,provenance="rendered labelled marker centre, synthetic") for name,obs in observations.items()],
        anchor=dict(object_description="synthetic 1 x .5 m reference",endpoints=["a","b"],length_m=1,uncertainty_m=.001,
            independently_verified=True,provenance="synthetic reference width, not runtime room dimensions"),
        scale_check=dict(endpoints=["a","c"],length_m=.5,independently_verified=True,provenance="independently specified reference height"),
        floor_corners=[f"f{i}" for i in range(4)],ceiling_corners=[f"t{i}" for i in range(4)],
        rectangle_and_constant_height_confirmed=True,boundary_provenance="visible synthetic corner wireframe",
        policy=dict(min_triangulation_angle_deg=2,max_reprojection_error_px=2,max_scale_check_relative_error=.03,
            max_shape_relative_error=.03,max_sensitivity_relative_change=.05))
    input_path = root/"room-input.json"
    input_path.write_text(json_text(request.model_dump())+"\n",encoding="utf-8")
    truth.update(room_dimensions_m=[3,4,2.6],room_points=points)
    (root/"ground-truth.json").write_text(json.dumps(truth,indent=2)+"\n",encoding="utf-8")
    command = [sys.executable,"-B","-m","library_claim.room_measurement","--store",str(store.root),"--reconstruction",str(root/"reconstruction"),
        "--input",str(input_path),"--output",str(root/"packet"),"--country","IN","--currency","INR","--currency-decimal-places","2","--exclusion-basis","missing_any_component"]
    subprocess.run(command,check=True,cwd=Path(__file__).resolve().parents[1])
    result = json.loads((root/"packet"/"room_result.json").read_text())
    packet = json.loads((root/"packet"/"claim_packet.json").read_text())
    assert result["stage_result"]["status"]=="success",result["reason"]
    errors = {}
    for field,expected in zip(("length_m","width_m","height_m"),truth["room_dimensions_m"]):
        actual = packet["room"][field]
        assert actual==result["room"][field] and abs(actual-expected)/expected < .02
        errors[field] = dict(expected_m=expected,actual_m=actual,relative_error=abs(actual-expected)/expected)
    assert result["synthetic"] and len(result["measurements"])==3
    assert packet["room"]["floor_area_m2"] is None
    for record in records:
        assert (root/"packet"/record.path).read_bytes()==store.read(record.id)
    (root/"smoke-errors.json").write_text(json.dumps(errors,indent=2)+"\n",encoding="utf-8")
    print("Synthetic native metric room smoke passed; three dimensions within 2%; physical accuracy unverified")


if __name__=="__main__":
    main()
