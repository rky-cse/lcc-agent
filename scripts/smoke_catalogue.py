"""Synthetic evidence and offline catalogue smoke; live lookup is a separate CLI."""
import argparse
import io
from datetime import datetime,timezone
from pathlib import Path

from PIL import Image,ImageDraw,ImageFont

from library_claim.capture_store import CaptureInput,FrameStore
from library_claim.catalogue import CatalogueRequest,export_catalogue
from library_claim.packet import json_text
from library_claim.spine_detection import DetectionRequest,DetectionResponse,export_detection
from library_claim.spine_reading import ReadingRequest,ReadingResponse,export_reading
from library_claim.tracking import TrackStore,TrackingCommand,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists(): raise FileExistsError('choose a fresh smoke directory')
    root.mkdir(parents=True)
    image=Image.new('RGB',(1600,900),'#e6e8ee');draw=ImageDraw.Draw(image)
    draw.rectangle((150,100,650,700),fill='#182c48')
    font_path=Path('C:/Windows/Fonts/arial.ttf')
    font=ImageFont.truetype(str(font_path),30) if font_path.exists() else ImageFont.load_default(size=30)
    labels=[('PRIDE AND PREJUDICE','title',200),('JANE AUSTEN','author',330)]
    for text,role,y in labels: draw.text((180,y),text,fill='white',font=font)
    sink=io.BytesIO();image.save(sink,'PNG');store=FrameStore(root/'store')
    frame=store.save(CaptureInput(sweep_id='catalogue-smoke',upload_id='spine',captured_at=datetime.now(timezone.utc),
        media_sequence=0,source='file_import',synthetic=True),sink.getvalue())
    detection=DetectionRequest(sweep_id='catalogue-smoke',frame_ref=frame.id,frame_sha256=frame.sha256,shelf_id='fixture',
        shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
    detected=export_detection(store,detection,root/'detection',DetectionResponse(coverage='clear',unresolved_regions=[],objects=[dict(
        kind='book_spine',orientation='upright',reason='known synthetic rectangle; no detector inference',
        polygon_1000=[(150/1.6,100/.9),(650/1.6,100/.9),(650/1.6,700/.9),(150/1.6,700/.9)])]))
    observation=detected['books'][0]['id']
    command=TrackingCommand(command_id='fixture',sweep_id='catalogue-smoke',expected_revision=0,operation='import',
        detection_result_sha256=digest((root/'detection/detection_result.json').read_bytes()),track_id=None,owned=None,
        provenance='synthetic physical copy',decisions=[dict(observation_id=observation,action='new',track_id=None,provenance='known fixture')])
    before=TrackStore(store).apply(command,root/'detection')
    request=ReadingRequest(sweep_id='catalogue-smoke',expected_revision=1,observation_id=observation,frame_sha256=frame.sha256)
    response=ReadingResponse(legibility='readable',uncertainty='',spans=[dict(text=text,role=role,orientation='horizontal',
        polygon_1000=[(60,(y-100)/.6),(950,(y-100)/.6),(950,(y-55)/.6),(60,(y-55)/.6)]) for text,role,y in labels])
    reading=export_reading(store,request,root/'reading-replay',response)
    lookup=CatalogueRequest(reading_result_sha256=digest((root/'reading-replay/reading_result.json').read_bytes()),
        title_span_ids=[s['id'] for s in reading['text_evidence'] if s['tentative_role']=='title'],
        author_span_ids=[s['id'] for s in reading['text_evidence'] if s['tentative_role']=='author'],limit=5)
    (root/'catalogue-input.json').write_text(json_text(lookup.model_dump())+'\n',encoding='utf-8')
    good=dict(key='/works/OL1W',title='Pride and Prejudice',author_name=['Jane Austen'],edition_count=100)
    cases=dict(wrong_first=[{**good,'key':'OL2W','author_name':['Wrong Writer']},good],ambiguous=[good,{**good,'key':'OL3W'}],no_match=[])
    results={}
    for case,docs in cases.items():
        raw=json_text(dict(docs=docs,numFound=len(docs),numFoundExact=True,start=0)).encode()
        result=export_catalogue(store,lookup,root/'reading-replay',root/case,response_bytes=raw)
        results[case]=dict(outcome=result['outcome'],accepted_work_id=result['accepted_work_id'],accepted_edition_id=result['accepted_edition_id'])
    assert results['wrong_first']['outcome']=='supported_candidate'
    assert results['ambiguous']['outcome']=='ambiguous'
    assert results['no_match']['outcome']=='no_match'
    assert TrackStore(store).snapshot('catalogue-smoke')==before
    (root/'smoke-summary.json').write_text(json_text(dict(synthetic=True,reading_source='known literal replay; no OCR inference',
        catalogue_source='offline fixtures with invented work IDs',provider_requests=0,inventory_unchanged=True,cases=results))+'\n',encoding='utf-8')
    print(f'Catalogue offline smoke passed: {root}; provider requests 0')


if __name__=='__main__': main()
