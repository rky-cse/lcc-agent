"""Actual HTTP enrollment, CLI worker and server restart; synthetic, no provider."""
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
    origin=f'http://127.0.0.1:{port}';url=f'/api/guidance/{session}/recognition';history=[];process=None
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
                data=get(url);assert len(data['observations'])==2 and data['jobs']==[]
                obs=data['observations'][0]
                job=dict(job_id='http-reading',session_id=session,expected_reference_revision=data['reference_revision'],request=dict(sweep_id=session,
                    expected_revision=data['inventory_revision'],observation_id=obs['id'],frame_sha256=obs['frame_sha256']))
                queued=post(url,job);assert queued['status']=='queued';assert post(url,job)==queued
                process.terminate();process.wait(timeout=5);process=boot();assert get(url)['jobs']==[queued]
                response_file=root/'response.json';response_file.write_text(json_text(dict(legibility='unreadable',spans=[],uncertainty='Synthetic fixture')),encoding='utf-8')
                subprocess.run([sys.executable,'-B','-m','library_claim.recognition_jobs','--store',str(store),'--run-one','--response',str(response_file)],check=True,capture_output=True,text=True)
                completed=get(url)['jobs'][0];assert completed['status']=='completed' and completed['result_status']=='partial'
                result=get(url+'/http-reading/reading_result.json');assert result['transcription_verified'] is False and result['inventory_mutated'] is False
                assert client.get(url+'/http-reading/crop.png').status_code==200
                other=dict(job,job_id='cancel-reading');other['request']=dict(job['request'],observation_id=data['observations'][1]['id'])
                post(url,other);assert post(url+'/cancel',dict(job_id='cancel-reading'))['status']=='cancelled'
                process.terminate();process.wait(timeout=5);process=boot();saved=get(url)
                assert [j['status'] for j in saved['jobs']]==['completed','cancelled']
                assert saved['inventory_revision']==data['inventory_revision']
                assert client.get('/recognition').status_code==200
                (root/'http-history.json').write_text(json_text(history),encoding='utf-8')
        finally:
            if process and process.poll() is None:process.terminate();process.wait(timeout=5)
    summary=dict(synthetic=True,provider_requests=0,http_enrollment=True,exact_retry=True,server_restart=True,separate_cli_worker=True,
        published_partial_result=True,cancelled_without_worker=True,inventory_unchanged=True,session_id=session)
    (root/'smoke-summary.json').write_text(json_text(summary),encoding='utf-8');print(json_text(summary))

if __name__=='__main__':main()
