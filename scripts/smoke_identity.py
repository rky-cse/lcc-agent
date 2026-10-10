"""Actual CLI + HTTP restart smoke of synthetic bibliographic review."""
import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from library_claim.capture_session import CaptureSessions
from library_claim.capture_store import FrameStore
from library_claim.identity import IdentityCommand,IdentityStore,MetadataDecision
from library_claim.packet import json_text
from library_claim.tracking import TrackStore,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    subprocess.run([sys.executable,'-B','-m','scripts.smoke_catalogue','--output',str(root)],check=True)
    frames=FrameStore(root/'store');ledger=TrackStore(frames);before=ledger.snapshot('catalogue-smoke')
    CaptureSessions(frames).start('IN','INR','catalogue-smoke') # explicit synthetic locale only
    bundle=root/'ambiguous';reading=json.loads((bundle/'reading_result.json').read_bytes())
    spans=[s['id'] for s in reading['text_evidence'] if s['tentative_role'] in ['title','author']]
    accept=IdentityCommand(command_id='review-work',sweep_id='catalogue-smoke',expected_revision=1,track_id=before['books'][0]['id'],
        action='accept_work',catalogue_result_sha256=digest((bundle/'catalogue_result.json').read_bytes()),work_id='/works/OL3W',
        confirmed_span_ids=spans,metadata=[MetadataDecision(field='edition',value='First edition',source='claimant_assertion',span_id=None,
            claimant_statement='Synthetic fixture claimant says this is a signed first edition.')],needs_appraisal=True,
        reviewer='Synthetic smoke reviewer',reason='Fixture review of exact lettering; selecting second of two invented supported work IDs')
    clear=accept.model_copy(update=dict(command_id='clear-correction',expected_revision=2,action='clear_identity',
        catalogue_result_sha256=None,work_id=None,confirmed_span_ids=[],metadata=[],needs_appraisal=False,
        reason='Synthetic claimant correction retracts the bibliographic identity'))
    def cli(command,name,bundle=None):
        path=root/(name+'-command.json');path.write_text(json_text(command.model_dump())+'\n',encoding='utf-8')
        args=[sys.executable,'-B','-m','library_claim.identity','--store',str(root/'store'),'--command',str(path),'--output',str(root/(name+'-inventory.json'))]
        if bundle: args+=['--bundle',str(bundle)]
        subprocess.run(args,check=True)
        return json.loads((root/(name+'-inventory.json')).read_bytes())
    accepted=cli(accept,'accept',bundle)
    assert accepted['revision']==2 and accepted['books'][0]['status']=='needs_appraisal'
    assert accepted['books'][0]['field_evidence']['edition']==[]
    retried=cli(accept,'retry',root/'missing-bundle');assert retried==accepted
    IdentityStore(frames).export_evidence('catalogue-smoke',root/'accepted-evidence')
    with socket.socket() as sock: sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}';process=None
    with (root/'identity-server.log').open('w',encoding='utf-8') as log:
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
            with httpx.Client(base_url=origin,timeout=10) as client:
                path='/api/sweeps/catalogue-smoke/inventory'
                response=client.get(path);response.raise_for_status();observed=response.json()
                book=next(row for row in observed['rows'] if row['kind']=='book')
                assert book['title']=='PRIDE AND PREJUDICE' and book['status']=='needs_appraisal'
                assert 'edition unresolved' in book['reason']
                original=client.get('/api/frames/'+book['frame_ref']);original.raise_for_status()
                assert original.content==(bundle/'original.png').read_bytes()
                process.terminate();process.wait(timeout=5);process=boot()
                restarted=client.get(path);restarted.raise_for_status();assert restarted.json()==observed
                cleared=cli(clear,'clear')
                response=client.get(path);response.raise_for_status();corrected=response.json()
                assert corrected['revision']==3
                assert next(row for row in corrected['rows'] if row['kind']=='book')['title']==''
                assert cleared['observations']==before['observations'] and cleared['assigned_track_count']==1
                assert cleared['books'][0]['edition']=='' and cleared['books'][0]['isbn']==''
                assert cleared['books'][0]['replacement_cost']['amount'] is None and cleared['books'][0]['used_value']['amount'] is None
                exported=client.get(path+'/export');exported.raise_for_status();assert exported.json()==cleared
                for name,data in [('http-accepted',observed),('http-corrected',corrected)]:
                    (root/(name+'.json')).write_text(json_text(data)+'\n',encoding='utf-8')
        finally:
            if process and process.poll() is None: process.terminate();process.wait(timeout=5)
    summary=dict(synthetic=True,external_requests=0,work_ids='invented offline fixtures; not genuine catalogue IDs',
        accepted_revision=accepted['revision'],retry_added_revision=False,server_restart_identical=True,
        correction_revision=cleared['revision'],physical_tracks_unchanged=True,original_bytes_unchanged=True,
        appraisal_assertion_preserved=True,accepted_edition_id=None,prices_unknown=True)
    (root/'identity-smoke-summary.json').write_text(json_text(summary)+'\n',encoding='utf-8')
    print(f'Identity CLI/HTTP/restart/correction smoke passed: {root}')


if __name__=='__main__': main()
