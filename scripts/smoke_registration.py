"""Synthetic registration HTTP/CLI/restart smoke; explicit new/unresolved decisions."""
import argparse,json,socket,subprocess,sys,time
from pathlib import Path
import httpx
from library_claim.packet import json_text

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists():raise FileExistsError('choose fresh output')
    root.mkdir(parents=True)
    subprocess.run([sys.executable,'-B','-m','scripts.smoke_guidance','--output',str(root/'setup')],check=True)
    store=root/'setup'/'store';session='e'*32
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}';queue_url=f'/api/guidance/{session}/recognition';process=None
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
                def get(path):r=client.get(path);r.raise_for_status();return r.json()
                def post(path,body):r=client.post(path,json=body);r.raise_for_status();return r.json()
                data=get(queue_url);frame=data['frames'][0]
                job=dict(kind='detection',job_id='registration-detection',session_id=session,expected_inventory_revision=data['inventory_revision'],expected_reference_revision=data['reference_revision'],request=dict(sweep_id=session,frame_ref=frame['id'],frame_sha256=frame['sha256'],shelf_id='reviewed-synthetic-shelf',shelf_region_px=[0,0,1600,900],policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5)))
                post(queue_url+'/detection',job)
                response=dict(coverage='clear',objects=[dict(kind='book_spine',orientation='upright',polygon_1000=[[100,100],[200,100],[200,800],[100,800]],reason='Synthetic first rectangle'),dict(kind='book_spine',orientation='upright',polygon_1000=[[300,100],[400,100],[400,800],[300,800]],reason='Synthetic second rectangle')],unresolved_regions=[])
                response_file=root/'response.json';response_file.write_text(json_text(response),encoding='utf-8')
                subprocess.run([sys.executable,'-B','-m','library_claim.recognition_jobs','--store',str(store),'--kind','detection','--run-one','--response',str(response_file)],check=True,capture_output=True,text=True)
                url=f'/api/guidance/{session}/registration/registration-detection';review=get(url)
                assert review['can_register'] and review['inventory_revision']==1
                request=dict(review_id='smoke-review',session_id=session,job_id=job['job_id'],expected_inventory_revision=1,expected_reference_revision=data['reference_revision'],reviewer='Synthetic reviewer',reason='Explicit saved-rectangle comparison',decisions=[dict(observation_id=c['observation_id'],action=a,track_id=None,provenance='Synthetic physical decision') for c,a in zip(review['candidates'],['new','unresolved'])])
                first=post(url,request);assert first['applied'] and first['ledger_event_revision']==2
                assert first['inventory']['assigned_track_count']==3 and len(first['inventory']['review_queue'])==1
                assert post(url,request)==first
                process.terminate();process.wait(timeout=5);process=boot();assert post(url,request)==first
                historical=get(url);assert not historical['can_register'] and len(historical['registration_events'])==1
                assert get(queue_url)['frames']==data['frames']
                (root/'review-request.json').write_text(json_text(request),encoding='utf-8');(root/'receipt.json').write_text(json_text(first),encoding='utf-8')
        finally:
            if process and process.poll() is None:process.terminate();process.wait(timeout=5)
    summary=dict(synthetic=True,provider_requests=0,explicit_new_and_unresolved=True,assigned_tracks=3,unresolved_observations=1,ledger_revision=2,exact_retry_and_restart=True,original_hash_preserved=True,no_automatic_registration=True)
    (root/'smoke-summary.json').write_text(json_text(summary),encoding='utf-8');print(json_text(summary))

if __name__=='__main__':main()
