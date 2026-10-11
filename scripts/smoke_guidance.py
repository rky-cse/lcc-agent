"""M06a actual local HTTP typed dialogue, restart and CLI export; no voice/model."""
import argparse
import io
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import httpx
from PIL import Image,ImageDraw

from library_claim.capture_store import FrameStore
from library_claim.spine_detection import DetectionRequest,DetectionResponse,export_detection
from library_claim.tracking import TrackStore,TrackingCommand,digest
from library_claim.packet import json_text


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists(): raise FileExistsError('choose fresh smoke directory')
    root.mkdir(parents=True);session='e'*32;responses=[]
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
            child.terminate();child.wait(timeout=5);raise RuntimeError('server startup timed out')
        try:
            process=boot()
            with httpx.Client(base_url=origin,headers={'Origin':origin},timeout=20) as client:
                def post(path,data):
                    response=client.post(path,json=data);response.raise_for_status();return response.json()
                state=post('/api/guidance',dict(session_id=session));responses.append(dict(step='start',state=state))
                assert state['locale'] is None and 'country' in state['next_prompt'] and state['capture_status'] is None
                def turn(payload,speaker='claimant'):
                    nonlocal state
                    body=dict(command_id=f'turn-{state["revision"]}',session_id=session,expected_revision=state['revision'],speaker=speaker,payload=payload)
                    (root/(body['command_id']+'.json')).write_text(json_text(body)+'\n',encoding='utf-8')
                    state=post(f'/api/guidance/{session}/turns',body);responses.append(dict(step=payload['action'],state=state));return body
                turn(dict(action='locale',country='GB',currency='GBP',claimant_statement='Synthetic claimant chooses United Kingdom and pounds.'))
                turn(dict(action='reference',description='Fixture measured card',width_cm=None,height_cm=None,width_uncertainty_cm=None,height_uncertainty_cm=None,
                    dimensions_verified=False,dimension_provenance='Not yet measured',claimant_statement='I have a card, but have not measured it.'))
                assert state['phase']=='awaiting_reference' and state['reference']['width_cm'] is None
                turn(dict(action='reference',description='Fixture measured card',width_cm='12',height_cm='8',width_uncertainty_cm='0.1',height_uncertainty_cm='0.1',
                    dimensions_verified=True,dimension_provenance='Synthetic claimant ruler declaration; not a real object calibration',claimant_statement='Fixture ruler values are 12 by 8 cm, plus or minus 0.1 cm.'))
                assert state['phase']=='ready_to_capture' and state['metric_ready'] is False
                capture=post('/api/sweeps',state['capture_start_proposal']);assert capture['country']=='GB' and capture['currency']=='GBP'
                turn(dict(action='bind_capture'),speaker='agent')
                image=Image.new('RGB',(1600,900),'white');draw=ImageDraw.Draw(image);draw.rectangle((160,90,320,720),fill='navy');draw.rectangle((480,90,640,720),fill='maroon')
                sink=io.BytesIO();image.save(sink,'PNG')
                response=client.post(f'/api/sweeps/{session}/frames',params=dict(upload_id='fixture',media_sequence=0,captured_at='2026-10-10T00:00:00Z'),content=sink.getvalue(),headers={'Content-Type':'image/png'})
                response.raise_for_status();frame=response.json()['frame'];frames=FrameStore(root/'store')
                request=DetectionRequest(sweep_id=session,frame_ref=frame['id'],frame_sha256=frame['sha256'],shelf_id='fixture',shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
                detector=DetectionResponse(coverage='clear',unresolved_regions=[],objects=[dict(kind='book_spine',orientation='upright',reason='known synthetic rectangle',
                    polygon_1000=[(x,100),(x+100,100),(x+100,800),(x,800)]) for x in [100,300]])
                detection=export_detection(frames,request,root/'detection',detector)
                ledger=TrackStore(frames);before=ledger.apply(TrackingCommand(command_id='fixture',sweep_id=session,expected_revision=0,operation='import',
                    detection_result_sha256=digest((root/'detection/detection_result.json').read_bytes()),decisions=[dict(observation_id=b['id'],action='new',track_id=None,provenance='two fixture physical rectangles') for b in detection['books']],
                    track_id=None,owned=None,provenance='synthetic fixture annotations'),root/'detection')
                a,b=[book['id'] for book in before['books']]
                turn(dict(action='request_evidence',request_id='isbn',reason_code='isbn_not_visible',track_id=a,shelf_id='fixture',expected_inventory_revision=1),speaker='agent')
                assert 'without moving a book' in state['next_prompt']
                turn(dict(action='decline_evidence',request_id='isbn',claimant_statement='The ISBN is hidden; leave the edition unknown.'))
                turn(dict(action='request_evidence',request_id='binding',reason_code='binding_unknown',track_id=a,shelf_id='fixture',expected_inventory_revision=1),speaker='agent')
                turn(dict(action='binding',request_id='binding',physical_format='paperback',claimant_statement='Fixture claimant declares paperback.'))
                turn(dict(action='correction',intent_id='borrowed',operation='exclude',track_id=None,expected_inventory_revision=1,claimant_statement='That book is borrowed.'))
                assert len(state['target_choices'])==2 and 'Which physical book' in state['next_prompt']
                last=turn(dict(action='choose_target',intent_id='borrowed',track_id=b,expected_inventory_revision=1,claimant_statement='I mean the second listed physical track.'))
                assert state['corrections'][0]['status']=='pending_review' and not state['corrections'][0]['applied']
                assert state['corrections'][0]['proposed_command']['track_id']==b
                assert ledger.snapshot(session)==before
                retry=post(f'/api/guidance/{session}/turns',last);assert retry==state
                process.terminate();process.wait(timeout=5);process=boot()
                response=client.get(f'/api/guidance/{session}');response.raise_for_status();assert response.json()==state
                post(f'/api/sweeps/{session}/end',dict(end_id='end',capture_gaps=0))
                response=client.get(f'/api/guidance/{session}');response.raise_for_status();state=response.json();assert state['capture_status']=='closed'
                response=client.post(f'/api/guidance/{session}/turns',json=dict(command_id='late',session_id=session,expected_revision=state['revision'],speaker='agent',
                    payload=dict(action='request_evidence',request_id='late',reason_code='glare',track_id=a,shelf_id='fixture',expected_inventory_revision=1)))
                assert response.status_code==409
                assert ledger.snapshot(session)==before
                responses.append(dict(step='capture_closed',state=state))
        finally:
            if process and process.poll() is None: process.terminate();process.wait(timeout=5)
    (root/'dialogue.json').write_text(json_text(responses)+'\n',encoding='utf-8')
    subprocess.run([sys.executable,'-B','-m','library_claim.guidance','--store',str(root/'store'),'--session-id',session,'--output',str(root/'review')],check=True)
    summary=dict(synthetic=True,provider_requests=0,voice_connected=False,locale_asked_first=True,declared_locale='GB/GBP',
        reference_measured_declaration='12 x 8 cm +/- 0.1 cm; not metric calibration',metric_ready=False,hidden_isbn_retained_unknown=True,
        binding_recorded_as_assertion=True,ambiguous_correction_target_explicit=True,correction_pending_not_applied=True,
        inventory_unchanged=True,restart_state_identical=True,exact_retry_no_revision=True,late_recapture_rejected=True)
    (root/'smoke-summary.json').write_text(json_text(summary)+'\n',encoding='utf-8');print(f'Guidance HTTP/dialogue/restart/CLI smoke passed: {root}')


if __name__=='__main__': main()
