"""Opt-in exact-job HTTP dispatch with real replay workers and server restart."""
import argparse,socket,subprocess,sys,time
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
    fixtures={'reading':dict(legibility='unreadable',spans=[],uncertainty='Synthetic replay; no physical accuracy claimed'),
        'detection':dict(coverage='clear',objects=[dict(kind='book_spine',orientation='upright',polygon_1000=[[300,100],[400,100],[400,800],[300,800]],reason='Synthetic rectangle')],unresolved_regions=[])}
    path=root/'replay.json';path.write_text(json_text(fixtures),encoding='utf-8')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}';process=None;history=[]
    with (root/'server.log').open('w',encoding='utf-8') as log:
        def boot(enabled=True):
            args=[sys.executable,'-B','-m','library_claim.server','--store',str(store),'--port',str(port),'--synthetic']
            if enabled:args+=['--recognition-replay',str(path)]
            child=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT)
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
            with httpx.Client(base_url=origin,headers={'Origin':origin},timeout=15) as client:
                def get(url):r=client.get(url);r.raise_for_status();return r.json()
                def post(url,body):r=client.post(url,json=body);r.raise_for_status();value=r.json();history.append(dict(url=url,status=r.status_code,result=value));return r.status_code,value
                queue=f'/api/guidance/{session}/recognition';dispatch=queue+'/dispatch';before=get(queue);obs=before['observations'][0];frame=before['frames'][0]
                reading=dict(job_id='first-reading',session_id=session,expected_reference_revision=before['reference_revision'],request=dict(sweep_id=session,expected_revision=before['inventory_revision'],observation_id=obs['id'],frame_sha256=obs['frame_sha256']))
                post(queue,reading);post(queue,reading|{'job_id':'selected-reading'})
                detector=dict(kind='detection',job_id='selected-detection',session_id=session,expected_reference_revision=before['reference_revision'],expected_inventory_revision=before['inventory_revision'],
                    request=dict(sweep_id=session,frame_ref=frame['id'],frame_sha256=frame['sha256'],shelf_id='dispatch-synthetic-shelf',shelf_region_px=[0,0,1600,900],policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5)))
                post(queue+'/detection',detector)
                results=[]
                for job_id in ['selected-detection','selected-reading']:
                    status,accepted=post(dispatch,dict(job_id=job_id));assert status==202 and accepted['accepted']
                    deadline=time.monotonic()+15
                    while get(dispatch)['active'] and time.monotonic()<deadline:time.sleep(.02)
                    assert not get(dispatch)['active']
                    status,result=post(dispatch,dict(job_id=job_id));assert status==200 and not result['accepted']
                    assert result['job']['status']=='completed' and not result['job']['worker_active'];results.append(result['job'])
                final=get(queue);assert final['jobs'][0]['status']=='queued'
                assert final['inventory_revision']==before['inventory_revision'] and final['observations']==before['observations'] and final['frames']==before['frames']
                process.terminate();process.wait(timeout=5);process=boot(False)
                assert not get(dispatch)['enabled'];assert client.post(dispatch,json=dict(job_id='first-reading')).status_code==409
                process.terminate();process.wait(timeout=5);process=boot()
                for job in results:assert post(dispatch,dict(job_id=job['input']['job_id']))[1]['job']==job
                assert get(queue)['jobs'][0]['status']=='queued'
                assert not get('/api/health')['provider_calls']
                assert not list((store/'dispatch_replays').glob('*.json'))
        finally:
            if process and process.poll() is None:process.terminate();process.wait(timeout=5)
    (root/'http-history.json').write_text(json_text(history),encoding='utf-8')
    summary=dict(synthetic=True,provider_requests=0,real_reading_and_detection_child_processes=True,explicit_selected_jobs_only=True,
        terminal_repeat_and_restart_no_retry=True,default_disabled=True,inventory_and_originals_unchanged=True,
        worker_slots_released=True,temporary_replays_cleaned=True)
    (root/'smoke-summary.json').write_text(json_text(summary),encoding='utf-8');print(json_text(summary))

if __name__=='__main__':main()
