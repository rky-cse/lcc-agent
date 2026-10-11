"""Actual local HTTP inventory/restart smoke using synthetic labeled views."""
import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from library_claim.capture_store import FrameStore
from library_claim.spine_detection import DetectionRequest,DetectionResponse,export_detection
from library_claim.tracking import TrackStore,TrackingCommand,digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,required=True,help='Completed smoke_matching output')
    args=parser.parse_args()
    root=args.output.resolve()
    if root.exists(): raise FileExistsError('choose a fresh smoke directory')
    root.mkdir(parents=True)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    command=[sys.executable,'-m','library_claim.server','--store',str(root/'store'),'--port',str(port),'--synthetic']
    process=None
    with (root/'server.log').open('w',encoding='utf-8') as log:
        def boot():
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                try:
                    response=httpx.get(origin+'/api/health',timeout=.5)
                    if response.status_code==200: return child
                except httpx.HTTPError: pass
                if child.poll() is not None: raise RuntimeError('server exited')
                time.sleep(.1)
            child.terminate(); child.wait(timeout=5); raise RuntimeError('startup timeout')
        try:
            process=boot()
            with httpx.Client(base_url=origin,headers={'Origin':origin},timeout=30) as client:
                response=client.post('/api/sweeps',json=dict(start_id='c'*32,country='IN',currency='INR'))
                response.raise_for_status(); sweep=response.json()['id']
                path=f'/api/sweeps/{sweep}/inventory'
                empty=client.get(path).json()
                assert empty['total_book_count'] is None and empty['rows']==[]
                frames=FrameStore(root/'store'); ledger=TrackStore(frames)
                initial=None
                for sequence,name in enumerate(['anchor','revisit']):
                    data=(args.fixture/name/'original.png').read_bytes()
                    response=client.post(f'/api/sweeps/{sweep}/frames',params=dict(upload_id=name,media_sequence=sequence,
                        captured_at='2026-10-10T00:00:00Z'),content=data,headers={'Content-Type':'image/png'})
                    response.raise_for_status(); frame=response.json()['frame']
                    detector=DetectionResponse.model_validate_json((args.fixture/name/'detector_response.json').read_text(encoding='utf-8'))
                    request=DetectionRequest(sweep_id=sweep,frame_ref=frame['id'],frame_sha256=frame['sha256'],shelf_id='a',
                        shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
                    bundle=root/name; result=export_detection(frames,request,bundle,detector)
                    decisions=[]
                    for index,book in enumerate(result['books']):
                        target=initial['observations'][index]['track_id'] if initial and index<3 else None
                        decisions.append(dict(observation_id=book['id'],action='new' if not initial else 'same' if target else 'unresolved',
                            track_id=target,provenance='synthetic fixture reviewer identity'))
                    cmd=TrackingCommand(command_id=name,sweep_id=sweep,expected_revision=sequence,operation='import',
                        detection_result_sha256=digest((bundle/'detection_result.json').read_bytes()),decisions=decisions,
                        track_id=None,owned=None,provenance='synthetic HTTP inventory review')
                    snap=ledger.apply(cmd,bundle)
                    if sequence==0: initial=snap
                before=client.get(path).json()
                assert before['assigned_track_count']==3 and before['review_count']==1 and before['revision']==2
                exclude=TrackingCommand(command_id='borrowed',sweep_id=sweep,expected_revision=2,operation='ownership',
                    detection_result_sha256=None,decisions=[],track_id=snap['books'][0]['id'],owned=False,provenance='synthetic borrowed copy')
                ledger.apply(exclude)
                response=client.post(f'/api/sweeps/{sweep}/end',json=dict(end_id='end',capture_gaps=0));response.raise_for_status()
                final=client.get(path).json()
                assert final['owned_assigned_track_count']==2 and final['capture_status']=='closed'
                page=client.get(path+'?offset=3&limit=1').json();assert page['rows'][0]['kind']=='review'
                exported=client.get(path+'/export');exported.raise_for_status()
                (root/'inventory-export.json').write_text(exported.text,encoding='utf-8')
            process.terminate();process.wait(timeout=5);process=boot()
            with httpx.Client(base_url=origin,timeout=30) as client:
                assert client.get(path).json()==final
                for row in final['rows']:
                    assert client.get('/api/frames/'+row['frame_ref']).status_code==200
            (root/'inventory-view.json').write_text(json.dumps(final,indent=2)+'\n',encoding='utf-8')
            summary=dict(synthetic=True,provider_calls=0,sweep_id=sweep,revision=final['revision'],assigned_tracks=3,
                owned_tracks=2,review_entries=1,restart_equal=True,http_pages_verified=True,total_book_count=None,
                real_camera_tested=False,browser_tested=False)
            (root/'smoke-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(summary))
        finally:
            if process is not None and process.poll() is None:
                process.terminate();process.wait(timeout=5)


if __name__=='__main__': main()
