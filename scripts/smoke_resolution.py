"""Synthetic unresolved-observation HTTP/restart smoke; no provider requests."""
import argparse, socket, subprocess, sys, time
from pathlib import Path
import httpx
from library_claim.packet import json_text


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists():raise FileExistsError('choose fresh output')
    root.mkdir(parents=True)
    subprocess.run([sys.executable,'-B','-m','scripts.smoke_registration','--output',str(root/'setup')],check=True)
    store=root/'setup'/'setup'/'store';session='e'*32
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}';process=None
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
                queue=f'/api/guidance/{session}/recognition';before=get(queue)
                obs=next(o for o in before['observations'] if o['track_id'] is None)
                url=f'/api/guidance/{session}/resolution/{obs["id"]}';view=get(url)
                assert view['can_resolve'] and view['inventory_revision']==2
                assert get(queue)==before  # review reads never mutate inventory
                request=dict(review_id='smoke-resolution',session_id=session,expected_inventory_revision=2,
                    expected_reference_revision=view['reference_revision'],reviewer='Synthetic reviewer',reason='Distinct rectangle on the saved original',
                    decisions=[dict(observation_id=obs['id'],action='new',track_id=None,provenance='Explicit distinct fixture copy')])
                first=post(url,request);assert first['applied'] and first['ledger_event_revision']==3
                assert first['inventory']['assigned_track_count']==4
                assert all(o['track_id'] for o in first['inventory']['observations'])
                assert post(url,request)==first
                process.terminate();process.wait(timeout=5);process=boot()
                assert post(url,request)==first
                historical=get(url);assert not historical['can_resolve'] and len(historical['resolution_events'])==1
                assert get(queue)['frames']==before['frames']
                assert client.post(url,json=request|{'reason':'Changed content'}).status_code==409
                (root/'review-request.json').write_text(json_text(request),encoding='utf-8')
                (root/'receipt.json').write_text(json_text(first),encoding='utf-8')
        finally:
            if process and process.poll() is None:process.terminate();process.wait(timeout=5)
    summary=dict(synthetic=True,provider_requests=0,explicit_resolution=True,assigned_tracks=4,
        unresolved_observations=0,ledger_revision=3,exact_retry_and_restart=True,original_hash_preserved=True)
    (root/'smoke-summary.json').write_text(json_text(summary),encoding='utf-8');print(json_text(summary))

if __name__=='__main__':main()
