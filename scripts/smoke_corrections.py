"""M06c1 actual target HTTP/restart/CLI with controlled synthetic physical copies."""
import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from library_claim.capture_store import FrameStore
from library_claim.correction_execution import CorrectionExecutor,CorrectionExecution
from library_claim.guidance import GuidanceStore
from library_claim.packet import json_text
from library_claim.tracking import TrackStore,TrackingCommand

SESSION='e'*32


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--commit-without-ack',type=Path);args=parser.parse_args()
    root=args.output
    if args.commit_without_ack:
        executor=CorrectionExecutor(GuidanceStore(FrameStore(root/'setup/store')))
        receipt=executor.prepare(CorrectionExecution.model_validate_json(args.commit_without_ack.read_bytes()));executor.dispatch(receipt)
        print('Controlled fixture exit after inventory commit and before acknowledgment');return
    if root.exists():parser.error('choose a fresh output')
    root.mkdir(parents=True);records=[]
    subprocess.run([sys.executable,'-B','-m','scripts.smoke_guidance','--output',str(root/'setup')],check=True)
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    origin=f'http://127.0.0.1:{port}';store=root/'setup/store';process=None
    with (root/'server.log').open('w',encoding='utf-8') as log:
        def boot():
            nonlocal process
            process=subprocess.Popen([sys.executable,'-B','-m','library_claim.server','--store',str(store),'--port',str(port),'--synthetic'],stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                try:
                    if httpx.get(origin+'/api/health',timeout=.5).status_code==200:return
                except httpx.HTTPError:pass
                time.sleep(.1)
            raise RuntimeError('target server did not start')
        def stop():
            if process and process.poll() is None:process.terminate();process.wait(timeout=10)
        try:
            boot()
            with httpx.Client(base_url=origin,headers={'Origin':origin},timeout=20) as client:
                def get(path):response=client.get(path);response.raise_for_status();return response.json()
                def post(path,body):
                    response=client.post(path,json=body);response.raise_for_status();result=response.json();records.append(dict(path=path,body=body,result=result));return result
                path=f'/api/guidance/{SESSION}';state=get(path)
                target=state['corrections'][0]['track_id'];assert state['capture_status']=='closed'
                def execution(intent,decision,request_id):
                    return dict(request_id=request_id,session_id=SESSION,intent_id=intent,expected_guidance_revision=state['revision'],
                        expected_inventory_revision=state['inventory_revision'],decision=decision,reviewer='Synthetic smoke reviewer',reason='Reviewed exact physical target and saved original')
                def intent(operation,name):
                    nonlocal state
                    state=post(path+'/turns',dict(command_id=name,session_id=SESSION,expected_revision=state['revision'],speaker='claimant',
                        payload=dict(action='correction',intent_id=name,operation=operation,track_id=target,expected_inventory_revision=state['inventory_revision'],claimant_statement=f'Explicit synthetic {operation} correction for the selected copy.')))
                exclude=execution('borrowed','apply','exclude');first=post(path+'/corrections',exclude);state=first['guidance']
                assert first['execution']['applied'] and first['inventory']['revision']==2
                assert first['inventory']['owned_assigned_track_count']==1 and first['inventory']['assigned_track_count']==2
                assert post(path+'/corrections',exclude)==first
                stop();boot();assert post(path+'/corrections',exclude)==first
                intent('include','include');include=execution('include','apply','include');request_file=root/'include-request.json';request_file.write_text(json_text(include),encoding='utf-8')
                stop()
                subprocess.run([sys.executable,'-B',__file__,'--output',str(root),'--commit-without-ack',str(request_file)],check=True)
                boot();pending=get(path);assert pending['correction_execution_pending']
                before=TrackStore(FrameStore(store)).snapshot(SESSION);assert before['revision']==3 and before['owned_assigned_track_count']==2
                recovered=post(path+'/corrections',include);state=recovered['guidance'];assert recovered['execution']['applied']
                assert recovered['inventory']['revision']==3 and not state['correction_execution_pending']
                intent('signed','signed');signed=execution('signed','apply','signed')
                response=client.post(path+'/corrections',json=signed);assert response.status_code==409
                dismissed=post(path+'/corrections',execution('signed','dismiss','dismiss-signed'));state=dismissed['guidance'];assert not dismissed['execution']['applied'];assert dismissed['inventory']['revision']==3
                intent('exclude','stale');stale=execution('stale','apply','stale')
                ledger=TrackStore(FrameStore(store));ledger.apply(TrackingCommand(command_id='independent-review',sweep_id=SESSION,expected_revision=3,operation='ownership',
                    track_id=target,owned=False,detection_result_sha256=None,decisions=[],provenance='Independent controlled fixture review changes the inventory revision'))
                response=client.post(path+'/corrections',json=stale);assert response.status_code==409
                state=get(path);assert state['inventory_revision']==4
                intent('clear_identity','clear');cleared=post(path+'/corrections',execution('clear','apply','clear'));state=cleared['guidance']
                assert cleared['inventory']['revision']==5 and cleared['inventory']['assigned_track_count']==2
                assert next(b for b in cleared['inventory']['books'] if b['id']==target)['owned'] is False
                assert next(b for b in cleared['inventory']['books'] if b['id']==target)['status']=='unidentified'
                refs=cleared['execution']['evidence_refs'];assert refs
                frame=FrameStore(store).get(refs[0]);original=client.get('/api/frames/'+frame.id);original.raise_for_status();assert hashlib.sha256(original.content).hexdigest()==frame.sha256
                stop();boot();assert get(path)==state
                assert get(path+'/corrections')['executions']
        finally:stop()
    subprocess.run([sys.executable,'-B','-m','library_claim.correction_execution','--store',str(store),'--session-id',SESSION,'--output',str(root/'review')],check=True)
    (root/'http-dialogue.json').write_text(json_text(records)+'\n',encoding='utf-8')
    summary=dict(synthetic=True,provider_requests=0,reviewed_target_only=True,assigned_copies=2,final_inventory_revision=5,final_owned_copies=1,
        exact_retry_no_revision=True,restart_state_identical=True,commit_before_ack_recovered_without_double_apply=True,signed_not_authenticated=True,
        stale_target_rejected=True,clear_preserved_physical_evidence_and_ownership=True,original_hash_preserved=True,metric_ready=False,recognition_scheduling=False)
    (root/'smoke-summary.json').write_text(json_text(summary)+'\n',encoding='utf-8');print('Correction HTTP/restart/CLI smoke passed: '+str(root))


if __name__=='__main__':main()
