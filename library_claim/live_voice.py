"""M06b: bounded Gemini Live transport; proposals require explicit claimant review."""
import asyncio
import base64
import binascii
import hashlib
import io
import json
import time
from contextlib import asynccontextmanager, closing, suppress

from PIL import Image
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from .guidance import GuidanceCommand
from .packet import json_text


async def storage_call(function, *args, **kwargs):
    """Drain local storage work before a cancelled voice task releases its session."""
    task=asyncio.create_task(run_in_threadpool(function,*args,**kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Cancelling an asyncio waiter cannot stop the underlying SQLite thread.
        with suppress(Exception): await task
        raise

MODEL = 'gemini-3.8-live'
POLICY = '''You guide a library contents claim. Ask country and currency first, then the
actual reference object, independently measured centimetre dimensions, tolerances and
provenance. Never assume an object size. Keep books in place during one shelf pass;
never ask to pull books or scan an individual item. An invisible ISBN stays unknown.
Read the authoritative next_prompt. Measurements, identity, prices and ownership are
unknown unless the authoritative state supports them. Voice transcriptions and visual
preview are not evidence of a reviewed identity. Use propose_guidance for explicit
claimant answers only; proposals need claimant confirmation in the browser. Do not
say they are saved or corrections applied. Ask for clarification if ambiguous. Never
pick a physical copy by title. Capture, recognition, geometry and correction execution
are separate. Camera previews cannot establish metric scale or identify a book here.
Use guidance_state to check current state. Speak briefly. Do not repeat a cancelled turn.'''
POLICY += ''' Correction acknowledgments come only from authoritative execution
receipts. applied=true confirms the recorded historical ledger revision, not an
unchanging present ownership state. Read correction_targets for current ownership.
A dispatching/prepared correction has an uncertain acknowledgment; ask the claimant
to resume its saved request, never say it failed or succeeded without a receipt.'''
POLICY += ''' Claimant proposal payloads (all fields required unless explicitly nullable):
locale: action=locale,country=uppercase two-letter code,currency=uppercase three-letter
code,claimant_statement=literal claimant words. Never convert an ambiguous place name.
reference: action=reference,description,width_cm,height_cm,width_uncertainty_cm,
height_uncertainty_cm,dimensions_verified,dimension_provenance,claimant_statement.
Numbers are centimetres and can all be null; no invented tolerances. Verified is a
claimant measurement declaration, not geometry. When the claimant gives independently
measured centimetre dimensions and provenance, set dimensions_verified=true so setup
can proceed to capture. If claimant has no reference or chooses to skip it, propose
skip_reference: action=skip_reference,claimant_statement. binding: action=binding,request_id,physical_format=hardcover or
paperback or other_print or unknown,claimant_statement. decline_evidence:
action=decline_evidence,request_id,claimant_statement. correction: action=correction,
intent_id=unique token,operation=exclude or include or clear_identity or signed or
first_edition,track_id=null if ambiguous,expected_inventory_revision=current inventory
revision,claimant_statement. choose_target: action=choose_target,intent_id,track_id,
expected_inventory_revision,claimant_statement. Only propose after explicit answers;
never propose agent-only actions, infer a physical track or rewrite claimant words.'''
POLICY += ''' recognition_progress contains proposal counts, not accepted titles or
physical counts. Use latest_quality and capture_hints to request short same-pass
recaptures. If a portrait or framed art is visible, ask whether it is an original or
a print; original/unknown requires appraisal. An explicit art answer can be proposed
with action=art,frame_ref=the saved current frame,description,classification=print or
original or unknown,claimant_statement. Do not infer print status from appearance.
When capture closes, explain that recognition/reviews may be pending; do not claim a
finished packet, geometry or valuation from recognition_drained alone.'''
POLICY += ''' For an explicitly named shelf correction propose action=shelf_correction,
intent_id,operation=exclude_shelf or include_shelf,shelf_id=an existing physical shelf,
expected_inventory_revision=current revision,claimant_statement. Never infer the
shelf from a title. The browser reviews all affected tracks before applying it.
Signed/first-edition corrections only flag appraisal; they do not authenticate or
accept an edition. Say applied only after an authoritative execution receipt.'''


class VoiceJournal:
    """No raw audio or keys. Persist bounded transcript/proposal events and epoch."""
    def __init__(self, frames):
        self.frames = frames
        with closing(frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS voice_journal (id TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.commit()

    def read(self, db, session):
        row = db.execute('SELECT state FROM voice_journal WHERE id=?', (session,)).fetchone()
        return json.loads(row[0]) if row else dict(epoch=0, events=[], proposals={})

    def update(self, session, kind=None, payload=None, new_epoch=False):
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE'); state = self.read(db, session)
            if new_epoch: state['epoch'] += 1
            if kind:
                if kind == 'proposal':
                    old = state['proposals'].get(payload['call_id'])
                    if old and old['command'] != payload['command']: raise ValueError('tool call ID changed')
                    if not old and len(state['proposals']) >= 20: raise ValueError('proposal review limit reached')
                    state['proposals'][payload['call_id']] = old or payload
                if kind == 'cancelled':
                    for call_id in payload['ids']:
                        if call_id in state['proposals']: state['proposals'][call_id]['cancelled'] = True
                if kind == 'dismissed':
                    if payload['call_id'] not in state['proposals']: raise ValueError('unknown proposal')
                    state['proposals'][payload['call_id']]['dismissed'] = True
                state['events'].append(dict(kind=kind, payload=payload))
                state['events'] = state['events'][-500:]
            db.execute('INSERT OR REPLACE INTO voice_journal VALUES (?,?)', (session, json_text(state)))
            db.commit(); return state

    def snapshot(self, session):
        with closing(self.frames._connect()) as db: return self.read(db, session)


class GeminiLive:
    """Optional SDK imported only when explicitly enabled by server CLI."""
    def __init__(self, key, model=MODEL):
        if model != MODEL: raise ValueError('voice model must be the reviewed free-tier model')
        from google import genai
        self.client = genai.Client(api_key=key, http_options={'api_version': 'v1beta'})
        self.model = model

    @asynccontextmanager
    async def connect(self, handle):
        from google.genai import types
        config = types.LiveConnectConfig(response_modalities=['AUDIO'], system_instruction=POLICY,
            input_audio_transcription=types.AudioTranscriptionConfig(), output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(handle=handle),
            context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name='guidance_state', description='Read authoritative guidance state.', parameters_json_schema={'type':'object','properties':{}}),
                types.FunctionDeclaration(name='propose_guidance', description='Propose an explicit claimant answer for browser review. Payload is JSON matching a claimant GuidanceCommand action; no mutations.',
                    parameters_json_schema={'type':'object','properties':{'payload_json':{'type':'string'}},'required':['payload_json']})])])
        async with self.client.aio.live.connect(model=self.model, config=config) as session:
            yield GeminiSession(session)


class GeminiSession:
    def __init__(self, session): self.session = session
    async def text(self, text):
        from google.genai import types
        await self.session.send_client_content(turns=types.Content(role='user', parts=[types.Part(text=text)]), turn_complete=True)
    async def audio(self, data):
        from google.genai import types
        await self.session.send_realtime_input(audio=types.Blob(data=data, mime_type='audio/pcm;rate=16000'))
    async def video(self, data):
        from google.genai import types
        await self.session.send_realtime_input(video=types.Blob(data=data, mime_type='image/jpeg'))
    async def audio_end(self): await self.session.send_realtime_input(audio_stream_end=True)
    async def tool_response(self, call, response):
        from google.genai import types
        # SDK tool dictionaries must contain JSON values, not Decimal objects.
        response=json.loads(json_text(response))
        await self.session.send_tool_response(function_responses=[types.FunctionResponse(id=call['id'], name=call['name'], response=response)])
    async def events(self):
        while True:
            async for response in self.session.receive():
                if response.session_resumption_update:
                    update = response.session_resumption_update
                    yield dict(type='resumption', handle=update.new_handle, resumable=update.resumable)
                if response.go_away: yield dict(type='go_away')
                if response.tool_call_cancellation: yield dict(type='cancelled', ids=response.tool_call_cancellation.ids or [])
                if response.tool_call:
                    for call in response.tool_call.function_calls or []:
                        yield dict(type='tool', id=call.id, name=call.name, args=call.args or {})
                content = response.server_content
                if not content: continue
                if content.interrupted: yield dict(type='interrupted')
                for speaker, chunk in [('claimant',content.input_transcription), ('agent',content.output_transcription)]:
                    if chunk and chunk.text and not (speaker=='agent' and content.interrupted):
                        yield dict(type='transcript', speaker=speaker, text=chunk.text[:8000], finished=bool(chunk.finished))
                if content.model_turn and not content.interrupted:
                    for part in content.model_turn.parts or []:
                        blob = part.inline_data
                        if blob and blob.mime_type == 'audio/pcm;rate=24000' and blob.data and len(blob.data)%2 == 0:
                            yield dict(type='audio', data=base64.b64encode(blob.data).decode())
                if content.turn_complete: yield dict(type='turn_complete')


def input_message(raw):
    if len(raw.encode()) > 48000: raise ValueError('voice input too large')
    try: message = json.loads(raw)
    except (ValueError, TypeError): raise ValueError('invalid voice JSON')
    if not isinstance(message,dict): raise ValueError('voice object required')
    kind = message.get('type')
    fields = {'audio':{'type','data'}, 'text':{'type','text'}, 'frame':{'type','frame_ref'},
        'refresh':{'type'}, 'watch':{'type','enabled'}, 'audio_end':{'type'}, 'close':{'type'}}
    if kind not in fields or set(message) != fields[kind]: raise ValueError('invalid voice input fields')
    if kind == 'audio':
        try: data = base64.b64decode(message['data'],validate=True)
        except (ValueError,TypeError,binascii.Error): raise ValueError('invalid PCM encoding')
        if not data or len(data)>16000 or len(data)%2: raise ValueError('audio requires at most 0.5 seconds PCM16 at 16000 Hz')
        message['bytes'] = data
    if kind == 'text' and (not isinstance(message['text'],str) or not message['text'].strip() or len(message['text'])>2000): raise ValueError('text requires 1–2000 characters')
    if kind == 'frame' and (not isinstance(message['frame_ref'],str) or not 1<=len(message['frame_ref'])<=128): raise ValueError('frame ID required')
    if kind=='watch' and not isinstance(message['enabled'],bool):raise ValueError('watch requires explicit boolean')
    return message


class VoiceHub:
    def __init__(self, guidance, provider=None):
        self.guidance=guidance; self.provider=provider; self.journal=VoiceJournal(guidance.frames)
        self.active=set(); self.handles={}

    def preview(self, session, frame_id):
        state=self.guidance.snapshot(session)
        if state['phase']!='capture_bound' or state['capture_status']!='capturing': raise ValueError('active bound capture required for preview')
        frame=self.guidance.frames.get(frame_id)
        if frame.sweep_id!=session: raise ValueError('preview must belong to this sweep')
        with Image.open(io.BytesIO(self.guidance.frames.read(frame_id))) as image:
            image=image.convert('RGB');image.thumbnail((640,640));sink=io.BytesIO();image.save(sink,format='JPEG',quality=70)
        return sink.getvalue()

    def proposal(self, session, call):
        if not isinstance(call.get('id'),str) or not 1<=len(call['id'])<=128: raise ValueError('tool ID required')
        if set(call['args']) != {'payload_json'} or not isinstance(call['args']['payload_json'],str) or len(call['args']['payload_json'])>3500: raise ValueError('bounded payload JSON required')
        payload=json.loads(call['args']['payload_json'])
        if payload.get('action') == 'reference' and payload.get('width_cm') is not None and payload.get('height_cm') is not None:
            payload['dimensions_verified'] = True
        state=self.guidance.snapshot(session)
        command=GuidanceCommand.model_validate(dict(command_id='voice-'+hashlib.sha256((session+'\0'+call['id']).encode()).hexdigest()[:32],
            session_id=session,expected_revision=state['revision'],speaker='claimant',payload=payload))
        old=self.journal.snapshot(session)['proposals'].get(call['id'])
        if old:
            if old['command']['payload'] != command.model_dump(mode='json')['payload']: raise ValueError('tool call ID changed')
            return old
        result=dict(call_id=call['id'],command=command.model_dump(mode='json'),cancelled=False,applied=False,requires_claimant_review=True)
        self.journal.update(session,'proposal',result);return result

    async def serve(self, socket, session):
        # Caller enforces WS Host/Origin independently of HTTP middleware.
        if self.provider is None: await socket.close(code=1013);return
        if session in self.active or len(self.active)>=1: await socket.close(code=1013);return
        try: state=await storage_call(self.guidance.snapshot,session)
        except (KeyError,ValueError,OSError): await socket.close(code=1008);return
        self.active.add(session); tasks=[]; accepted=False
        try:
            await socket.accept();accepted=True
            journal=await storage_call(self.journal.update,session,new_epoch=True);epoch=journal['epoch']
            send_lock=asyncio.Lock()
            async def send(event):
                async with send_lock:
                    # Support exact numeric events as well as JSON-mode proposals.
                    async with asyncio.timeout(10): await socket.send_text(json_text({**event,'epoch':epoch}))
            entry=self.handles.get(session);handle=entry[0] if entry and time.monotonic()-entry[1]<7000 else None
            async with asyncio.timeout(25):
                manager=self.provider.connect(handle);live=await manager.__aenter__()
            try:
                watching=False
                await send(dict(type='ready',state=state,journal=journal,resumed=bool(handle),model=getattr(self.provider,'model','fixture')))
                # Always rehydrate authoritative state, not a guessed model summary.
                history=[e for e in journal['events'] if e['kind'] in {'transcript','text'}][-12:]
                await live.text('Authoritative guidance state: '+json_text(state)+'\nRecent unverified conversation: '+json_text(history)+'\nAsk the authoritative next_prompt briefly. Do not assume pending proposals were confirmed.')
                async def incoming():
                    nonlocal watching
                    windows={}
                    while True:
                        raw=await socket.receive_text()
                        try:
                            message=input_message(raw);kind=message['type'];now=time.monotonic()
                            period,limit=(1,20) if kind=='audio' else (1,1) if kind=='frame' else (60,30)
                            window=[t for t in windows.get(kind,[]) if now-t<period]
                            if len(window)>=limit: raise ValueError('voice input rate exceeded')
                            windows[kind]=window+[now]
                            if kind=='close': return
                            if kind=='audio': await live.audio(message['bytes'])
                            elif kind=='audio_end': await live.audio_end()
                            elif kind=='text':
                                await storage_call(self.journal.update,session,'text',dict(speaker='claimant',text=message['text']))
                                await live.text(message['text'])
                            elif kind=='frame':
                                data=await storage_call(self.preview,session,message['frame_ref']);await live.video(data)
                                await send(dict(type='preview_sent',frame_ref=message['frame_ref'],evidence_original_preserved=True))
                            elif kind=='refresh':
                                current=await storage_call(self.guidance.snapshot,session)
                                await send(dict(type='state',state=current))
                                await live.text('Updated authoritative guidance state: '+json_text(current)+'\nAsk next_prompt. Pending corrections are not applied.')
                            elif kind=='watch':watching=message['enabled']
                        except (ValueError,ValidationError,KeyError): await send(dict(type='input_error',message='Invalid, stale or unavailable voice input. Review the saved state and retry.'))
                async def outgoing():
                    async for event in live.events():
                        kind=event['type']
                        if kind=='resumption':
                            if event.get('resumable') and event.get('handle'): self.handles[session]=(event['handle'],time.monotonic())
                            else: self.handles.pop(session,None)
                            continue # provider handle never reaches browser/journal
                        if kind=='go_away': await send(dict(type='reconnect_required'));return
                        if kind=='tool':
                            try:
                                if event['name']=='guidance_state': result=await storage_call(self.guidance.snapshot,session)
                                elif event['name']=='propose_guidance':
                                    result=await storage_call(self.proposal,session,event);await send(dict(type='proposal',proposal=result))
                                else: raise ValueError('unsupported tool')
                            except (ValueError,ValidationError,KeyError): result=dict(error='Invalid or stale proposal. Ask the claimant to clarify; nothing was saved to guidance.')
                            await live.tool_response(event,result);continue
                        if kind in {'transcript','cancelled','interrupted','turn_complete'}:
                            await storage_call(self.journal.update,session,kind,{k:v for k,v in event.items() if k!='type'})
                        await send(event)
                async def progress_updates():
                    last_frame=None;last_state=None;last_prompt=state['next_prompt'];last_spoken=time.monotonic()
                    while True:
                        await asyncio.sleep(5)
                        if not watching:continue
                        try:
                            current=await storage_call(self.guidance.snapshot,session)
                        except (ValueError,KeyError,OSError):
                            await send(dict(type='input_error',message='Sweep progress is temporarily unavailable. Voice remains connected.'))
                            continue
                        compact={k:current[k] for k in ('id','revision','inventory_revision','capture_status','next_prompt','recognition_progress','latest_quality')}
                        fingerprint=json_text(compact)
                        if fingerprint!=last_state:
                            await send(dict(type='state',state=current))
                            # Initial watch/polls must not start a duplicate model
                            # turn while the reference question is still playing.
                            last_state=fingerprint
                        announce=current['next_prompt']!=last_prompt or (current['capture_status']=='capturing' and time.monotonic()-last_spoken>=30)
                        if announce and time.monotonic()-last_spoken>=10:
                            await live.text('Updated authoritative sweep progress: '+fingerprint+'\nSpeak one short sentence. Proposal counts are not accepted identities.')
                            last_prompt=current['next_prompt'];last_spoken=time.monotonic()
                        ref=current.get('latest_frame_ref')
                        if ref and ref!=last_frame and current['capture_status']=='capturing':
                            try:data=await storage_call(self.preview,session,ref)
                            except (ValueError,KeyError,OSError):continue
                            await live.video(data);last_frame=ref
                            await send(dict(type='preview_sent',frame_ref=ref,evidence_original_preserved=True))
                tasks=[asyncio.create_task(incoming()),asyncio.create_task(outgoing()),asyncio.create_task(progress_updates())]
                done,_=await asyncio.wait(tasks,timeout=20*60,return_when=asyncio.FIRST_COMPLETED)
                if not done: await send(dict(type='reconnect_required'))
                for task in done: task.result()
            finally:
                for task in tasks: task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
                with suppress(Exception):
                    async with asyncio.timeout(10): await manager.__aexit__(None,None,None)
        except WebSocketDisconnect: pass
        except Exception as error:
            # SDK errors can include credentials/handles; never forward or log their text.
            self.handles.pop(session,None)
            if accepted:
                with suppress(Exception):
                    await storage_call(self.journal.update,session,'connection_error',dict(category=type(error).__name__))
                with suppress(Exception): await socket.send_json(dict(type='error',message='Voice connection ended. Saved guidance remains available for reconnection.'))
        finally:
            if accepted:
                with suppress(Exception): await storage_call(self.journal.update,session,'disconnected',dict(pending_turns_preserved=True))
                with suppress(Exception): await socket.close()
            self.active.discard(session)
