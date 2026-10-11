import asyncio
import base64
import json
import tempfile
import time
import unittest
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from library_claim.live_voice import VoiceHub, VoiceJournal, input_message, GeminiLive
from library_claim.server import create_app

SESSION='a'*32
LOCALE=dict(action='locale',country='GB',currency='GBP',claimant_statement='Britain, pounds please')


class FakeSession:
    def __init__(self): self.queue=asyncio.Queue();self.inputs=[];self.responses=[];self.closed=False
    async def text(self,text): self.inputs.append(('text',text));await self.queue.put(dict(type='turn_complete'))
    async def audio(self,data): self.inputs.append(('audio',data));await self.queue.put(dict(type='interrupted'))
    async def video(self,data): self.inputs.append(('video',data));await self.queue.put(dict(type='turn_complete'))
    async def audio_end(self): self.inputs.append(('audio_end',None))
    async def tool_response(self,call,response): self.responses.append(response);await self.queue.put(dict(type='turn_complete'))
    async def events(self):
        while True: yield await self.queue.get()


class FakeProvider:
    model='fixture'
    def __init__(self,initial=()): self.handles=[];self.sessions=[];self.initial=initial
    @asynccontextmanager
    async def connect(self,handle):
        self.handles.append(handle);session=FakeSession();self.sessions.append(session)
        for event in self.initial: await session.queue.put(event)
        try: yield session
        finally: session.closed=True


class VoiceTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.provider=FakeProvider();self.app=create_app(Path(self.temp.name),{'http://testserver'},voice_provider=self.provider)
        self.client=TestClient(self.app);self.client.__enter__();self.client.post('/api/guidance',json=dict(session_id=SESSION),headers={'Origin':'http://testserver'})
    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()
    @contextmanager
    def connect(self,**kwargs):
        with self.client.websocket_connect('/ws/voice/'+SESSION,headers={'Origin':'http://testserver'},**kwargs) as ws:
            try: yield ws
            finally:
                with suppress(RuntimeError,WebSocketDisconnect):ws.send_json({'type':'close'})
                with suppress(RuntimeError,WebSocketDisconnect):
                    while True:ws.receive_json()
    def test_ready_rehydrates_guidance(self):
        with self.connect() as ws:
            ready=ws.receive_json();self.assertEqual(ready['type'],'ready');self.assertIsNone(ready['state']['locale']);self.assertIn('country',ready['state']['next_prompt'])
            ws.send_json({'type':'close'})
        self.assertIn('Authoritative guidance state',self.provider.sessions[0].inputs[0][1]);self.assertTrue(self.provider.sessions[0].closed)
    def test_ws_origin_enforced(self):
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect('/ws/voice/'+SESSION,headers={'Origin':'http://evil'}): pass
        self.assertEqual(caught.exception.code,1008);self.assertFalse(self.provider.sessions)
    def test_ws_host_enforced(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws/voice/'+SESSION,headers={'Origin':'http://testserver','Host':'evil'}): pass
    def test_missing_session(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws/voice/'+'f'*32,headers={'Origin':'http://testserver'}): pass
    def test_disabled_by_default(self):
        app=create_app(Path(self.temp.name),{'http://testserver'})
        with TestClient(app) as client:
            self.assertFalse(client.get('/api/health').json()['voice_enabled'])
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/ws/voice/'+SESSION,headers={'Origin':'http://testserver'}): pass
    def test_single_connection(self):
        with self.connect() as ws:
            ws.receive_json()
            with self.assertRaises(WebSocketDisconnect) as caught:
                with self.connect():pass
            self.assertEqual(caught.exception.code,1013);ws.send_json({'type':'close'})
    def test_pcm_and_interruption(self):
        with self.connect() as ws:
            ws.receive_json();ws.receive_json();ws.send_json(dict(type='audio',data=base64.b64encode(b'\0\0'*160).decode()))
            self.assertEqual(ws.receive_json()['type'],'interrupted');ws.send_json(dict(type='close'))
        self.assertEqual(self.provider.sessions[0].inputs[-1],('audio',b'\0\0'*160))
    def test_invalid_input_does_not_reach_provider(self):
        with self.connect() as ws:
            ws.receive_json();ws.receive_json();ws.send_json(dict(type='audio',data='AA=='))
            self.assertEqual(ws.receive_json()['type'],'input_error');ws.send_json(dict(type='close'))
        self.assertEqual(len(self.provider.sessions[0].inputs),1)
    def test_unbound_frame_rejected(self):
        with self.connect() as ws:
            ws.receive_json();ws.receive_json();ws.send_json(dict(type='frame',frame_ref='unknown'))
            self.assertEqual(ws.receive_json()['type'],'input_error');ws.send_json(dict(type='close'))
    def test_tool_proposal_not_mutation_then_explicit_confirmation(self):
        self.provider.initial=[dict(type='tool',id='call1',name='propose_guidance',args=dict(payload_json=json.dumps(LOCALE)))]
        with self.connect() as ws:
            ws.receive_json();proposal=ws.receive_json()['proposal'];self.assertTrue(proposal['requires_claimant_review'])
            self.assertIsNone(self.app.state.guidance.snapshot(SESSION)['locale']);ws.send_json({'type':'close'})
        result=self.client.post('/api/guidance/'+SESSION+'/turns',json=proposal['command'],headers={'Origin':'http://testserver'})
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['locale']['country'],'GB')
        self.assertEqual(self.app.state.voice.journal.snapshot(SESSION)['proposals']['call1'],proposal)
    def test_proposal_retry_and_changed_call(self):
        call=dict(id='same',args=dict(payload_json=json.dumps(LOCALE)))
        first=self.app.state.voice.proposal(SESSION,call);self.assertEqual(self.app.state.voice.proposal(SESSION,call),first)
        call['args']['payload_json']=json.dumps({**LOCALE,'country':'IN'})
        with self.assertRaises(ValueError):self.app.state.voice.proposal(SESSION,call)
    def test_model_cannot_propose_agent_action(self):
        with self.assertRaises(ValueError):self.app.state.voice.proposal(SESSION,dict(id='bad',args=dict(payload_json='{"action":"bind_capture"}')))
    def test_decimal_reference_proposal_retry(self):
        payload=dict(action='reference',description='Measured card',width_cm=12,height_cm=8,width_uncertainty_cm=.1,height_uncertainty_cm=.1,
            dimensions_verified=True,dimension_provenance='Independently measured with ruler',claimant_statement='12 by 8 centimetres')
        call=dict(id='reference',args=dict(payload_json=json.dumps(payload)))
        first=self.app.state.voice.proposal(SESSION,call)
        self.assertEqual(first,self.app.state.voice.proposal(SESSION,call))
    def test_reference_proposal_delivered_without_disconnecting_voice(self):
        payload=dict(action='reference',description='Measured card',width_cm=12.5,height_cm=8.2,width_uncertainty_cm=.1,height_uncertainty_cm=.1,
                     dimensions_verified=True,dimension_provenance='Independent ruler',claimant_statement='12.5 by 8.2 cm')
        self.provider.initial=[dict(type='tool',id='reference-live',name='propose_guidance',args=dict(payload_json=json.dumps(payload)))]
        with self.connect() as ws:
            self.assertEqual(ws.receive_json()['type'],'ready')
            proposal=ws.receive_json();self.assertEqual(proposal['type'],'proposal')
            self.assertEqual(float(proposal['proposal']['command']['payload']['width_cm']),12.5)
            # A second user turn proves the socket/provider tasks survive delivery.
            ws.send_json(dict(type='text',text='Keep talking'))
            while ws.receive_json()['type']!='turn_complete':pass
            ws.send_json(dict(type='close'))
        self.assertTrue(self.provider.sessions[0].responses)
    def test_unknown_tool_returns_failure(self):
        self.provider.initial=[dict(type='tool',id='bad',name='apply_ownership',args={})]
        with self.connect() as ws:
            ws.receive_json();ws.receive_json();ws.send_json(dict(type='close'))
        self.assertIn('error',self.provider.sessions[0].responses[0]);self.assertEqual(self.app.state.guidance.snapshot(SESSION)['revision'],0)
    def test_resumption_secret_and_epoch(self):
        self.provider.initial=[dict(type='resumption',resumable=True,handle='private-handle')]
        with self.connect() as ws:
            first=ws.receive_json();ws.receive_json();ws.send_json({'type':'close'})
        self.assertNotIn('private-handle',json.dumps(self.app.state.voice.journal.snapshot(SESSION)))
        with self.connect() as ws:
            second=ws.receive_json();self.assertTrue(second['resumed']);self.assertGreater(second['epoch'],first['epoch']);ws.send_json({'type':'close'})
        self.assertEqual(self.provider.handles,[None,'private-handle'])
    def test_restart_journal_durable_handle_not_restored(self):
        self.app.state.voice.journal.update(SESSION,'transcript',dict(speaker='claimant',text='unfinished',finished=False))
        app=create_app(Path(self.temp.name),{'http://testserver'},voice_provider=self.provider)
        state=app.state.voice.journal.snapshot(SESSION);self.assertEqual(state['events'][-1]['payload']['text'],'unfinished');self.assertEqual(app.state.voice.handles,{})
    def test_cancellation_preserves_audit_blocks_proposal(self):
        call=dict(id='cancel',args=dict(payload_json=json.dumps(LOCALE)));self.app.state.voice.proposal(SESSION,call)
        self.app.state.voice.journal.update(SESSION,'cancelled',dict(ids=['cancel']))
        self.assertTrue(self.app.state.voice.journal.snapshot(SESSION)['proposals']['cancel']['cancelled'])
    def test_page_and_assets(self):
        for path in ['/voice','/assets/voice.mjs','/assets/pcm-worklet.mjs','/assets/voice_core.mjs']:
            self.assertEqual(self.client.get(path).status_code,200)
    def test_dismiss_proposal_durable_without_guidance_mutation(self):
        self.app.state.voice.proposal(SESSION,dict(id='dismiss',args=dict(payload_json=json.dumps(LOCALE))))
        result=self.client.post('/api/guidance/'+SESSION+'/voice/dismiss',json=dict(call_id='dismiss'),headers={'Origin':'http://testserver'})
        self.assertEqual(result.status_code,200);self.assertTrue(result.json()['proposals']['dismiss']['dismissed'])
        self.assertEqual(self.app.state.guidance.snapshot(SESSION)['revision'],0)
        restarted=VoiceJournal(self.app.state.guidance.frames);self.assertTrue(restarted.snapshot(SESSION)['proposals']['dismiss']['dismissed'])
    def test_journal_bounded(self):
        for i in range(502):self.app.state.voice.journal.update(SESSION,'transcript',dict(text=str(i)))
        self.assertEqual(len(self.app.state.voice.journal.snapshot(SESSION)['events']),500)
    def test_provider_exception_redacted(self):
        class Broken:
            @asynccontextmanager
            async def connect(self,handle): raise RuntimeError('SECRET KEY');yield
        self.app.state.voice.provider=Broken()
        with self.connect() as ws:
            result=ws.receive_json();self.assertEqual(result['type'],'error');self.assertNotIn('SECRET',json.dumps(result))
    def test_input_contracts(self):
        for raw in ['[]','null','{','{"type":"text","text":" "}',json.dumps(dict(type='audio',data='%%%')),json.dumps(dict(type='audio',data=base64.b64encode(b'a'*16002).decode())),json.dumps(dict(type='close',extra=True))]:
            with self.subTest(raw=raw[:40]),self.assertRaises(ValueError):input_message(raw)
        self.assertEqual(input_message('{"type":"audio_end"}'),dict(type='audio_end'))
    def test_model_allowlist(self):
        with self.assertRaises(ValueError):GeminiLive('never-used',model='paid-model')


if __name__=='__main__':unittest.main()
