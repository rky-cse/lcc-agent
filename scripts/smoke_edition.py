"""Synthetic owned-ISBN evidence with actual edition CLI/HTTP review boundaries."""
import argparse
import io
import json
import socket
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

import httpx
from PIL import Image,ImageDraw,ImageFont

from library_claim.capture_store import CaptureInput,FrameStore
from library_claim.capture_session import CaptureSessions
from library_claim.catalogue import CatalogueRequest,export_catalogue
from library_claim.edition import EditionRequest,EditionCommand,EditionStore
from library_claim.identity import IdentityCommand,IdentityStore,MetadataDecision
from library_claim.spine_detection import DetectionRequest,DetectionResponse,export_detection
from library_claim.spine_reading import ReadingRequest,ReadingResponse,export_reading
from library_claim.tracking import TrackStore,TrackingCommand,digest
from library_claim.packet import json_text


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists(): raise FileExistsError('choose a fresh smoke directory')
    root.mkdir(parents=True);frames=FrameStore(root/'store');sweep='edition-smoke'
    CaptureSessions(frames).start('IN','INR',sweep) # fixture declaration, not a production locale default
    image=Image.new('RGB',(1600,900),'#e6e8ee');draw=ImageDraw.Draw(image);draw.rectangle((150,100,650,700),fill='#182c48')
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',30)
    labels=[('FANTASTIC MR FOX','title',200),('ROALD DAHL','author',330),('9780140328721','isbn',460)]
    for text,role,y in labels: draw.text((180,y),text,fill='white',font=font)
    sink=io.BytesIO();image.save(sink,'PNG')
    frame=frames.save(CaptureInput(sweep_id=sweep,upload_id='spine',captured_at=datetime.now(timezone.utc),media_sequence=0,source='file_import',synthetic=True),sink.getvalue())
    request=DetectionRequest(sweep_id=sweep,frame_ref=frame.id,frame_sha256=frame.sha256,shelf_id='fixture',shelf_region_px=(0,0,1600,900),
        policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
    detected=export_detection(frames,request,root/'detection',DetectionResponse(coverage='clear',unresolved_regions=[],objects=[dict(kind='book_spine',orientation='upright',
        reason='known synthetic rectangle; no detector inference',polygon_1000=[(150/1.6,100/.9),(650/1.6,100/.9),(650/1.6,700/.9),(150/1.6,700/.9)])]))
    obs=detected['books'][0]['id'];ledger=TrackStore(frames)
    imported=ledger.apply(TrackingCommand(command_id='fixture',sweep_id=sweep,expected_revision=0,operation='import',
        detection_result_sha256=digest((root/'detection/detection_result.json').read_bytes()),track_id=None,owned=None,provenance='known synthetic physical book',
        decisions=[dict(observation_id=obs,action='new',track_id=None,provenance='known fixture rectangle')]),root/'detection')
    reading=export_reading(frames,ReadingRequest(sweep_id=sweep,expected_revision=1,observation_id=obs,frame_sha256=frame.sha256),root/'reading',ReadingResponse(
        legibility='readable',uncertainty='',spans=[dict(text=text,role=role,orientation='horizontal',polygon_1000=[(60,(y-100)/.6),(950,(y-100)/.6),(950,(y-55)/.6),(60,(y-55)/.6)]) for text,role,y in labels]))
    ids={s['tentative_role']:s['id'] for s in reading['text_evidence']};track=imported['books'][0]['id']
    catalogue=CatalogueRequest(reading_result_sha256=digest((root/'reading/reading_result.json').read_bytes()),title_span_ids=[ids['title']],author_span_ids=[ids['author']],limit=5)
    export_catalogue(frames,catalogue,root/'reading',root/'work',response_bytes=json_text(dict(numFound=1,numFoundExact=True,start=0,docs=[dict(key='/works/OL45804W',title='Fantastic Mr. Fox',author_name=['Roald Dahl'])])).encode())
    work=IdentityCommand(command_id='work-review',sweep_id=sweep,expected_revision=1,track_id=track,action='accept_work',
        catalogue_result_sha256=digest((root/'work/catalogue_result.json').read_bytes()),work_id='/works/OL45804W',confirmed_span_ids=list(ids.values()),
        metadata=[MetadataDecision(field='isbn',value='9780140328721',source='visible_text',span_id=ids['isbn'],claimant_statement=None)],needs_appraisal=False,
        reviewer='Synthetic smoke reviewer',reason='Known drawn title/author/ISBN fixture; no physical book recognition inference')
    before=IdentityStore(frames).apply(work,root/'work')
    lookup=EditionRequest(sweep_id=sweep,expected_revision=2,track_id=track,edition_id='/books/OL7353617M',limit=5,
        owned_physical_format='paperback',format_statement='Synthetic fixture claimant declares this copy is paperback.')
    record=dict(key='/books/OL7353617M',title='Fantastic Mr. Fox',works=[dict(key='/works/OL45804W')],isbn_13=['9780140328721'],physical_format='Paperback',publishers=['Fixture Press'])
    (root/'fixture-edition.json').write_text(json_text(record)+'\n',encoding='utf-8')
    def cli(operation,input,name,bundle=None,response=None):
        path=root/(name+'-input.json');path.write_text(json_text(input.model_dump())+'\n',encoding='utf-8')
        output=root/name if operation=='lookup' else root/(name+'-inventory.json')
        args=[sys.executable,'-B','-m','library_claim.edition',operation,'--store',str(root/'store'),'--input',str(path),'--output',str(output)]
        if bundle: args+=['--bundle',str(bundle)]
        if response: args+=['--response',str(response)]
        subprocess.run(args,check=True)
        return json.loads((output/'edition_result.json' if operation=='lookup' else output).read_bytes())
    proposal=cli('lookup',lookup,'edition-replay',response=root/'fixture-edition.json')
    assert proposal['outcome']=='supported_candidate' and proposal['accepted_edition_id'] is None
    assert ledger.snapshot(sweep)==before
    command=EditionCommand(command_id='edition-review',sweep_id=sweep,expected_revision=2,track_id=track,action='accept_edition',
        edition_result_sha256=digest((root/'edition-replay/edition_result.json').read_bytes()),edition_id='/books/OL7353617M',reviewer='Synthetic smoke reviewer',
        reason='Explicit fixture ISBN/work/binding review; not authentication of a real physical book')
    accepted=cli('review',command,'accept',bundle=root/'edition-replay')
    assert accepted['tracks'][0]['bibliography']['accepted_edition_id']=='/books/OL7353617M'
    assert cli('review',command,'retry',bundle=root/'missing')==accepted
    assert accepted['books'][0]['publisher']=='' and accepted['books'][0]['edition']==''
    EditionStore(frames).export_evidence(sweep,root/'accepted-evidence')
    with socket.socket() as sock: sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}';process=None
    with (root/'server.log').open('w',encoding='utf-8') as log:
        def boot():
            child=subprocess.Popen([sys.executable,'-B','-m','library_claim.server','--store',str(root/'store'),'--port',str(port),'--synthetic'],stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                try:
                    if httpx.get(origin+'/api/health',timeout=.5).status_code==200: return child
                except httpx.HTTPError: pass
                if child.poll() is not None: raise RuntimeError('server exited')
                time.sleep(.1)
            child.terminate();child.wait(timeout=5);raise RuntimeError('startup timeout')
        try:
            process=boot()
            with httpx.Client(base_url=origin,timeout=10) as client:
                path=f'/api/sweeps/{sweep}/inventory';response=client.get(path);response.raise_for_status();observed=response.json()
                book=next(row for row in observed['rows'] if row['kind']=='book');assert 'Reviewed edition record' in book['reason']
                process.terminate();process.wait(timeout=5);process=boot()
                response=client.get(path);response.raise_for_status();assert response.json()==observed
                clear=command.model_copy(update=dict(command_id='clear-edition',expected_revision=3,action='clear_edition',edition_result_sha256=None,edition_id=None))
                cleared=cli('review',clear,'clear')
                response=client.get(path);response.raise_for_status();corrected=response.json()
                assert corrected['revision']==4 and 'edition unresolved' in corrected['rows'][0]['reason']
                assert cleared['books']==accepted['books'] and cleared['observations']==before['observations']
                assert cleared['tracks'][0]['bibliography']['accepted_edition_id'] is None
                response=client.get('/api/frames/'+frame.id);response.raise_for_status();assert response.content==sink.getvalue()
                (root/'http-accepted.json').write_text(json_text(observed)+'\n',encoding='utf-8')
                (root/'http-cleared.json').write_text(json_text(corrected)+'\n',encoding='utf-8')
        finally:
            if process and process.poll() is None: process.terminate();process.wait(timeout=5)
    (root/'live-input.json').write_text(json_text(lookup.model_copy(update=dict(expected_revision=4)).model_dump())+'\n',encoding='utf-8')
    summary=dict(synthetic=True,external_requests=0,reading_and_work='known offline fixtures, not inference',edition_record='controlled offline fixture with documented real ID',
        accepted_revision=3,clear_revision=4,retry_added_revision=False,server_restart_identical=True,work_isbn_observations_unchanged=True,
        publisher_and_edition_not_borrowed=True,prices_unknown=True)
    (root/'smoke-summary.json').write_text(json_text(summary)+'\n',encoding='utf-8');print(f'Edition CLI/HTTP/restart/clear smoke passed: {root}')


if __name__=='__main__': main()
