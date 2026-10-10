"""Synthetic text/blank spine fixtures; optional live reading is separate CLI."""
import argparse
import io
from datetime import datetime,timezone
from pathlib import Path

from PIL import Image,ImageDraw,ImageFont

from library_claim.capture_store import CaptureInput,FrameStore
from library_claim.packet import json_text
from library_claim.spine_detection import DetectionRequest,DetectionResponse,export_detection
from library_claim.spine_reading import ReadingRequest,ReadingResponse,export_reading
from library_claim.tracking import TrackStore,TrackingCommand,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists(): raise FileExistsError('choose a fresh smoke directory')
    root.mkdir(parents=True)
    image=Image.new('RGB',(1600,900),'#e4e8ee');draw=ImageDraw.Draw(image)
    draw.rectangle((180,120,460,800),fill='#182c48',outline='white',width=4)
    draw.rectangle((620,120,900,800),fill='#87424a',outline='white',width=4)
    font_path=Path('C:/Windows/Fonts/arial.ttf')
    font=ImageFont.truetype(str(font_path),30) if font_path.exists() else ImageFont.load_default(size=30)
    labels=[('RIVER ATLAS','title',200),('MAYA SEN','author',320),('NORTH PRESS','publisher',440),('VOL 2','volume',560)]
    for text,role,y in labels: draw.text((205,y),text,fill='white',font=font)
    sink=io.BytesIO();image.save(sink,'PNG')
    store=FrameStore(root/'store')
    frame=store.save(CaptureInput(sweep_id='reading-smoke',upload_id='spines',captured_at=datetime.now(timezone.utc),
        media_sequence=0,source='file_import',synthetic=True),sink.getvalue())
    objects=[]
    for x0,x1 in [(180,460),(620,900)]:
        objects.append(dict(kind='book_spine',orientation='upright',reason='labeled synthetic crop boundary; no detection inference',
            polygon_1000=[(x0/1.6,120/.9),(x1/1.6,120/.9),(x1/1.6,800/.9),(x0/1.6,800/.9)]))
    request=DetectionRequest(sweep_id='reading-smoke',frame_ref=frame.id,frame_sha256=frame.sha256,shelf_id='fixture',
        shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
    result=export_detection(store,request,root/'detection',DetectionResponse(coverage='clear',objects=objects,unresolved_regions=[]))
    command=TrackingCommand(command_id='fixture',sweep_id='reading-smoke',expected_revision=0,operation='import',
        detection_result_sha256=digest((root/'detection/detection_result.json').read_bytes()),track_id=None,owned=None,
        provenance='labeled fixture physical copies',decisions=[dict(observation_id=b['id'],action='new',track_id=None,
            provenance='distinct synthetic rectangles') for b in result['books']])
    TrackStore(store).apply(command,root/'detection')
    truth=[]
    for index,name in enumerate(['legible','blank']):
        reading=ReadingRequest(sweep_id='reading-smoke',expected_revision=1,observation_id=result['books'][index]['id'],frame_sha256=frame.sha256)
        (root/(name+'-input.json')).write_text(json_text(reading.model_dump())+'\n',encoding='utf-8')
        spans=[dict(text=text,role=role,orientation='horizontal',polygon_1000=[(80,(y-120)/.68),(920,(y-120)/.68),
               (920,(y-80)/.68),(80,(y-80)/.68)]) for text,role,y in labels] if index==0 else []
        response=ReadingResponse(legibility='readable' if index==0 else 'unreadable',spans=spans,
            uncertainty='' if index==0 else 'plain colored spine; no text')
        (root/(name+'-response.json')).write_text(json_text(response.model_dump())+'\n',encoding='utf-8')
        exported=export_reading(store,reading,root/(name+'-replay'),response)
        truth.append(dict(case=name,visible_text=[s['text'] for s in spans],accepted_identity=None,
            result_status=exported['stage_result']['status']))
    (root/'fixture-truth.json').write_text(json_text(truth)+'\n',encoding='utf-8')
    print(f'Synthetic crop/replay smoke ready: {root}; provider calls 0')


if __name__=='__main__': main()
