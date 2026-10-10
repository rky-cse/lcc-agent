"""M03b1 synthetic multiview CPU backend smoke; no supplied poses/tracks."""

import argparse
import hashlib
import io
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.packet import json_text
from library_claim.reconstruction import ReconstructionRequest


def render_views():
    # Physical textured patches at several depths, viewed by translated pinhole
    # cameras. Truth is saved separately and never handed to the backend.
    rng = random.Random(314159)
    patches = []
    for _ in range(220):
        x,y,z = rng.uniform(-3.3,3.3),rng.uniform(-2,2),rng.uniform(4,7)
        width = rng.uniform(.18,.35)
        texture = Image.new("RGB",(48,48),tuple(rng.randrange(40,200) for _ in range(3)))
        draw = ImageDraw.Draw(texture)
        for __ in range(22):
            left,top = rng.randrange(40),rng.randrange(40)
            size = rng.randrange(3,12)
            draw.rectangle((left,top,left+size,top+size),fill=tuple(rng.randrange(256) for _ in range(3)))
        patches.append((x,y,z,width,texture))
    truth = dict(synthetic=True,width=1920,height=1080,focal_px=1200,
                 camera_centres=[(x,0,0) for x in [-1.2,-.6,0,.6,1.2]],
                 patches=[dict(centre=(x,y,z),width=width) for x,y,z,width,_ in patches])
    views = []
    for cx,_,_ in truth["camera_centres"]:
        image = Image.new("RGB",(1920,1080),(23,28,35))
        for x,y,z,width,texture in sorted(patches,key=lambda p:p[2],reverse=True):
            size = max(1,round(1200*width/z))
            left,top = round(960+1200*(x-cx-width/2)/z),round(540+1200*(y-width/2)/z)
            image.paste(texture.resize((size,size),Image.Resampling.BILINEAR),(left,top))
        views.append(image)
    return views,truth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--blank",action="store_true")
    parser.add_argument("--expect-timeout",action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise FileExistsError("choose a fresh smoke output")
    root.mkdir(parents=True)
    if args.blank:
        views = [Image.new("RGB",(1920,1080),(i*20,35,45)) for i in range(3)]
        truth = dict(synthetic=True,case="textureless byte-distinct images",expected="unavailable")
    else:
        views,truth = render_views()
    store = FrameStore(root/"store")
    records = []
    for i,image in enumerate(views):
        sink = io.BytesIO()
        image.save(sink,"PNG")
        records.append(store.save(CaptureInput(sweep_id="synthetic-reconstruction",upload_id=f"view-{i}",media_sequence=i,
            captured_at=datetime.now(timezone.utc),source="file_import",synthetic=True),sink.getvalue()))
    request = ReconstructionRequest(sweep_id="synthetic-reconstruction",frame_refs=[r.id for r in records],
        same_camera_and_zoom_confirmed=True,camera_provenance="synthetic fixed pinhole camera",
        policy=dict(max_runtime_seconds=1 if args.expect_timeout else 120,min_points3d=100,max_median_reprojection_error_px=2,
                    min_median_triangulation_angle_deg=2))
    input_path = root/"input.json"
    input_path.write_text(json_text(request.model_dump())+"\n",encoding="utf-8")
    (root/"ground-truth.json").write_text(json.dumps(truth,indent=2)+"\n",encoding="utf-8")
    process = subprocess.run([sys.executable,"-B","-m","library_claim.reconstruction","--store",str(store.root),
        "--input",str(input_path),"--output",str(root/"reconstruction")],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,check=True)
    result = json.loads((root/"reconstruction"/"reconstruction_result.json").read_text())
    assert result["synthetic"] and all(result["room"][f] is None for f in ["length_m","width_m","height_m","floor_area_m2"])
    assert result["measurement_status"] == "unavailable"
    assert result["status"] == ("failed" if args.expect_timeout else "unavailable" if args.blank else "connected_provisional"), result["reason"]
    if args.expect_timeout:
        assert result["stage_result"]["errors"][0]["code"] == "backend_timeout"
    else:
        assert result["backend_summary"]["device"] == "cpu"
    for r in records:
        assert (root/"reconstruction"/"images"/Path(r.path).name).read_bytes() == store.read(r.id)
    for artifact in result["artifacts"]:
        assert hashlib.sha256((root/"reconstruction"/artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]
    print(process.stdout.strip())
    print(f'Actual CPU backend smoke passed; status: {result["status"]}; room metrics remain unknown')


if __name__ == "__main__":
    main()
