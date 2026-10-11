"""Detection queue HTTP/restart/CLI smoke. Synthetic replay; no registration."""
import argparse,json,socket,subprocess,sys,time
from pathlib import Path
import httpx
from library_claim.packet import json_text
from library_claim.capture_store import FrameStore
from library_claim.tracking import TrackStore,TrackingCommand

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists():raise FileExistsError('choose fresh output')
    root.mkdir(parents=True)
    subprocess.run([sys.executable,'-B','-m','scripts.smoke_guidance','--output',str(root/'setup')],check=True)
    store=root/'setup'/'store';session='e'*32;frames=FrameStore(store);ledger=TrackStore(frames);before=ledger.snapshot(session)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}';url=f'/api/guidance/{session}/recognition';process=None;history=[]
    with (root/'server.log').open('w',encoding='utf-8') as log:
        def boot():
            child=subprocess.Popen([sys.executable,'-B','-m','library_claim.server','--store',str(store),'--port',str(port),'--synthetic'],stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                try:
                    if httpx.get(origin+'/api/health',timeout=.5).status_code==200:return child
                except httpx.HTTPError:pass
                if child.poll() is not None:raise RuntimeError('server exited')
                time.sleep(.1)
            child.terminate();child.wait(timeout=5);raise RuntimeError('server timeout')
        try:
            process=boot()
            with httpx.Client(base_url=origin,headers={'Origin':origin},timeout=20) as client:
                def get(path):
                    response=client.get(path);response.raise_for_status();return response.json()
                def post(path,body):
                    response=client.post(path,json=body);response.raise_for_status();result=response.json();history.append(dict(path=path,body=body,result=result));return result
                data=get(url);frame=frames.get(data['observations'][0]['frame_ref'])
                job=dict(kind='detection',job_id='shelf-detection',session_id=session,expected_reference_revision=data['reference_revision'],expected_inventory_revision=data['inventory_revision'],
                    request=dict(sweep_id=session,frame_ref=frame.id,frame_sha256=frame.sha256,shelf_id='explicit-fixture-shelf',shelf_region_px=[0,0,1600,900],policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5)))
                queued=post(url+'/detection',job);assert post(url+'/detection',job)==queued
                process.terminate();process.wait(timeout=5);process=boot();assert get(url)['jobs']==[queued]
                response_file=root/'response.json';response_file.write_text(json_text(dict(coverage='clear',objects=[dict(kind='book_spine',orientation='upright',polygon_1000=[[100,100],[200,100],[200,800],[100,800]],reason='Synthetic saved rectangle')],unresolved_regions=[])),encoding='utf-8')
                subprocess.run([sys.executable,'-B','-m','library_claim.recognition_jobs','--store',str(store),'--kind','detection','--run-one','--response',str(response_file)],check=True,capture_output=True,text=True)
                completed=get(url)['jobs'][0];assert completed['status']=='completed' and completed['eligible_for_review']
                detection=get(url+'/shelf-detection/detection_result.json');stage=get(url+'/shelf-detection/queue_stage.json')
                assert detection['provisional_observed_count']==1 and stage['stage_result']['input_revision']==before['revision']
                assert ledger.snapshot(session)==before
                assert frames.get(frame.id).sha256==frame.sha256
                process.terminate();process.wait(timeout=5);process=boot();assert get(url)['jobs']==[completed]
                ledger.apply(TrackingCommand(command_id='exclude-after-detection',sweep_id=session,expected_revision=before['revision'],operation='ownership',track_id=before['books'][0]['id'],owned=False,detection_result_sha256=None,decisions=[],provenance='Explicit synthetic correction'))
                assert get(url)['jobs'][0]['status']=='stale'
                (root/'http-history.json').write_text(json_text(history),encoding='utf-8')
        finally:
            if process and process.poll() is None:process.terminate();process.wait(timeout=5)
    summary=dict(synthetic=True,provider_requests=0,http_exact_enrollment_retry=True,queued_and_completed_restart=True,separate_detection_cli_worker=True,
        original_hash_preserved=True,detection_did_not_register_tracks=True,inventory_unchanged_by_detection=True,later_correction_invalidates=True,
        assigned_tracks=before['assigned_track_count'],provisional_detected_objects=detection['provisional_observed_count'])
    (root/'smoke-summary.json').write_text(json_text(summary),encoding='utf-8');print(json_text(summary))

if __name__=='__main__':main()
