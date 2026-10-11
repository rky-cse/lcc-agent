"""Actual HTTP/WebSocket voice smoke. Fixture default; --gemini explicitly opts in."""
import argparse
import asyncio
import base64
import io
import hashlib
import json
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
from PIL import Image
from websockets.asyncio.client import connect

from library_claim.live_voice import GeminiLive
from library_claim.server import create_app
from library_claim.vision_provider import read_key

ID='b'*32
LOCALE=dict(action='locale',country='GB',currency='GBP',claimant_statement='United Kingdom, GBP')


class FixtureSession:
    def __init__(self):self.queue=asyncio.Queue()
    async def text(self,text):
        await self.queue.put(dict(type='resumption',resumable=True,handle='fixture-private'))
        await self.queue.put(dict(type='transcript',speaker='agent',text='Which country and currency?',finished=True))
        await self.queue.put(dict(type='audio',data=base64.b64encode(b'\0\0'*240).decode()))
        if text=='United Kingdom, GBP':await self.queue.put(dict(type='tool',id='locale-fixture',name='propose_guidance',args=dict(payload_json=json.dumps(LOCALE))))
        await self.queue.put(dict(type='turn_complete'))
    async def audio(self,data):await self.queue.put(dict(type='interrupted'))
    async def audio_end(self):pass
    async def video(self,data):await self.queue.put(dict(type='turn_complete'))
    async def tool_response(self,call,result):await self.queue.put(dict(type='turn_complete'))
    async def events(self):
        while True:yield await self.queue.get()


class FixtureProvider:
    model='fixture'
    @asynccontextmanager
    async def connect(self,handle):yield FixtureSession()


async def smoke(root,port,gemini,key_file):
    origin=f'http://127.0.0.1:{port}';child=None;records=[];summary=dict(synthetic=True,real_microphone_verified=False,three_minute_session_verified=False,provider='gemini' if gemini else 'fixture')
    log=(root/'server.log').open('w',encoding='utf-8')
    def boot():
        nonlocal child
        cmd=[sys.executable,'-B',__file__,'--serve','--output',str(root),'--port',str(port)]
        if gemini:cmd+=['--gemini','--free-tier-confirmed','--key-file',str(key_file)] if key_file else ['--gemini','--free-tier-confirmed']
        child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                if httpx.get(origin+'/api/health',timeout=.5).status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.1)
        raise RuntimeError('target server did not start')
    def stop():
        if child:child.terminate();child.wait(timeout=10)
    async def until(ws,kind,timeout=45):
        async with asyncio.timeout(timeout):
            while True:
                event=json.loads(await ws.recv());records.append(event)
                if event['type']=='error':raise RuntimeError('target live connection failed')
                if event['type']==kind:return event
    try:
        boot()
        async with httpx.AsyncClient(base_url=origin,headers={'Origin':origin}) as client:
            async def post(path,body):
                response=await client.post(path,json=body);response.raise_for_status();return response.json()
            initial=await post('/api/guidance',dict(session_id=ID));assert initial['locale'] is None
            async with connect(f'ws://127.0.0.1:{port}/ws/voice/{ID}',origin=origin,max_size=2000000) as ws:
                first=await until(ws,'ready');assert first['state']['locale'] is None
                await until(ws,'turn_complete')
                await ws.send(json.dumps(dict(type='text',text='United Kingdom, GBP')))
                proposed=(await until(ws,'proposal'))['proposal'];assert proposed['applied'] is False
                response=await client.get('/api/guidance/'+ID);assert response.json()['locale'] is None
                state=await post('/api/guidance/'+ID+'/turns',proposed['command']);assert state['locale']['country']=='GB'
                state=await post('/api/guidance/'+ID+'/turns',dict(command_id='skip',session_id=ID,expected_revision=state['revision'],speaker='claimant',payload=dict(action='skip_reference',claimant_statement='Synthetic smoke: no metric reference supplied')))
                capture=await post('/api/sweeps',state['capture_start_proposal'])
                state=await post('/api/guidance/'+ID+'/turns',dict(command_id='bind',session_id=ID,expected_revision=state['revision'],speaker='agent',payload=dict(action='bind_capture')))
                image=Image.new('RGB',(1600,900),'navy');sink=io.BytesIO();image.save(sink,format='PNG')
                response=await client.post(f'/api/sweeps/{ID}/frames',params=dict(upload_id='fixture',captured_at='2026-10-10T00:00:00Z',media_sequence=0),content=sink.getvalue(),headers={'Content-Type':'image/png'});response.raise_for_status();frame=response.json()['frame']
                await ws.send(json.dumps(dict(type='refresh')));await until(ws,'state');await until(ws,'turn_complete')
                await ws.send(json.dumps(dict(type='frame',frame_ref=frame['id'])));await until(ws,'preview_sent')
                original=await client.get('/api/frames/'+frame['id']);original.raise_for_status();assert hashlib.sha256(original.content).hexdigest()==frame['sha256']
                await ws.send(json.dumps(dict(type='audio',data=base64.b64encode(b'\0\0'*3200).decode())))
                await ws.send(json.dumps(dict(type='audio_end')))
                if not gemini:await until(ws,'interrupted')
                await ws.send(json.dumps(dict(type='close')))
            # Wait for cleanup rather than treating socket disconnect as sweep completion.
            await asyncio.sleep(.2)
            async with connect(f'ws://127.0.0.1:{port}/ws/voice/{ID}',origin=origin) as ws:
                second=await until(ws,'ready');assert second['epoch']>first['epoch'];assert second['state']['revision']==state['revision']
                summary['provider_resumed']=second['resumed'];await ws.send(json.dumps(dict(type='close')))
            if not gemini:
                stop();boot()
                async with connect(f'ws://127.0.0.1:{port}/ws/voice/{ID}',origin=origin) as ws:
                    restarted=await until(ws,'ready');assert not restarted['resumed'];assert restarted['state']['revision']==state['revision']
                    assert restarted['journal']['proposals'];await ws.send(json.dumps(dict(type='close')))
                summary['server_restart_verified']=True
            capture=(await client.get('/api/sweeps/'+ID)).json();assert capture['status']=='capturing'
            inventory=(await client.get('/api/sweeps/'+ID+'/inventory')).json();assert inventory['revision']==0
            summary.update(passed=True,locale_asked_first=True,proposal_only_until_confirmation=True,confirmed_locale='GB/GBP',saved_original_preview_sent=True,
                inventory_unchanged=True,disconnect_did_not_end_capture=True,epoch_guard_verified=True,audio_messages=sum(e['type']=='audio' for e in records),
                interruption_verified=not gemini,metric_ready=False)
    except Exception as error:
        summary.update(passed=False,error_class=type(error).__name__) # no SDK credentials/handle error text
    finally:
        stop();log.close()
        safe_records=[{k:v for k,v in e.items() if k!='data'} for e in records]
        (root/'events.json').write_text(json.dumps(safe_records,indent=2),encoding='utf-8')
        (root/'smoke-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    return summary['passed']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--port',type=int);parser.add_argument('--serve',action='store_true');parser.add_argument('--gemini',action='store_true');parser.add_argument('--key-file',type=Path);parser.add_argument('--free-tier-confirmed',action='store_true');args=parser.parse_args()
    if args.gemini and not args.free_tier_confirmed:parser.error('explicit free-tier confirmation required')
    if args.serve:
        provider=GeminiLive(read_key(args.key_file)) if args.gemini else FixtureProvider()
        origin=f'http://127.0.0.1:{args.port}';uvicorn.run(create_app(args.output/'store',{origin},synthetic=True,voice_provider=provider),host='127.0.0.1',port=args.port);return
    if args.output.exists():parser.error('choose a fresh output')
    args.output.mkdir(parents=True)
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    if not asyncio.run(smoke(args.output,port,args.gemini,args.key_file)):sys.exit(1)


if __name__=='__main__':main()
