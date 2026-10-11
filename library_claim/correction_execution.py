"""M06c1: explicitly reviewed correction dispatch with recoverable receipts.

The existing inventory/identity stores remain the only mutation authorities.
"""
import argparse
import json
from contextlib import closing
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .capture_store import FrameStore
from .guidance import GuidanceStore, Token, Text
from .identity import IdentityCommand, IdentityStore
from .models import Contract, StageResult, StageError
from .packet import json_text
from .tracking import TrackingCommand, digest


class CorrectionExecution(Contract):
    request_id: Token
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    intent_id: Token
    expected_guidance_revision: int = Field(ge=0)
    expected_inventory_revision: int = Field(ge=0)
    decision: Literal['apply', 'dismiss']
    reviewer: Text
    reason: Text

    @model_validator(mode='after')
    def nonblank(self):
        if not self.reviewer.strip() or not self.reason.strip(): raise ValueError('reviewer and reason must be nonblank')
        return self


class CorrectionExecutor:
    def __init__(self, guidance):
        self.guidance=guidance; self.frames=guidance.frames; self.ledger=guidance.ledger
        self.identity=IdentityStore(self.frames)
        with closing(self.frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS correction_executions (session_id TEXT, request_id TEXT, state TEXT NOT NULL, PRIMARY KEY(session_id,request_id))')
            db.commit()

    @staticmethod
    def read(db, session, request_id):
        row=db.execute('SELECT state FROM correction_executions WHERE session_id=? AND request_id=?',(session,request_id)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def intent(state, intent_id):
        matches=[c for c in state['corrections'] if c['intent_id']==intent_id]
        if len(matches)!=1: raise ValueError('unknown correction intent')
        return matches[0]

    @staticmethod
    def stage(receipt, status, errors=None):
        return StageResult(sweep_id=receipt['request']['session_id'],job_id=receipt['request_sha256'],
            input_revision=receipt['request']['expected_inventory_revision'],stage='guided_correction_execution',status=status,
            started_at=receipt['prepared_at'],finished_at=datetime.now(timezone.utc),evidence_refs=receipt['evidence_refs'],
            warnings=['Recognition, metric calibration and valuation scheduling remain separate.'],errors=errors or []).model_dump(mode='json')

    def prepare(self, request):
        fingerprint=digest(json_text(request.model_dump()).encode())
        # Integrity and capture locale are checked before touching the receipt ledger.
        self.guidance.snapshot(request.session_id)
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            old=self.read(db,request.session_id,request.request_id)
            if old:
                if old['request_sha256']!=fingerprint: raise ValueError('execution request ID reused with different content')
                return old
            state=self.guidance.read(db,request.session_id)
            if state['revision']!=request.expected_guidance_revision: raise ValueError('stale guidance revision; review correction again')
            if state['phase']!='capture_bound': raise ValueError('correction requires bound capture')
            intent=self.intent(state,request.intent_id)
            if intent['status'] not in ['pending_review','review_required','awaiting_target']: raise ValueError('correction is already reserved or resolved')
            inventory=self.ledger._read(db,request.session_id);self.ledger._verify(inventory)
            if inventory['revision']!=request.expected_inventory_revision: raise ValueError('stale inventory revision; review current physical target')
            command=None;refs=[]
            if request.decision=='apply':
                if intent['track_id'] is None: raise ValueError('choose an explicit physical track before applying')
                command=self.guidance.proposal(request.session_id,intent)
                if command is None: raise ValueError('signed/first-edition claims require separate identity/appraisal review')
                if command!=intent['proposed_command']: raise ValueError('correction proposal integrity mismatch')
                if command['expected_revision']!=inventory['revision']: raise ValueError('correction target revision changed; submit a new reviewed intent')
                tracks=[t for t in inventory['tracks'].values() if t['shelf_id']==intent['track_id']] if intent.get('target_kind')=='shelf' else [inventory['tracks'].get(intent['track_id'])]
                if intent.get('target_kind')=='shelf':
                    refs=sorted({o['frame_ref'] for o in inventory['observations'].values() if o['shelf_id']==intent['track_id']})
                    if not refs:raise ValueError('unknown physical shelf')
                else:
                    if not tracks or any(t is None for t in tracks):raise ValueError('unknown physical target')
                    refs=sorted({inventory['observations'][oid]['frame_ref'] for track in tracks for oid in track['observations']})
            if db.execute('SELECT COUNT(*) FROM correction_executions WHERE session_id=?',(request.session_id,)).fetchone()[0]>=200:
                raise ValueError('correction execution review limit reached')
            receipt=dict(schema_version='1.0',request=request.model_dump(mode='json'),request_sha256=fingerprint,
                prepared_at=datetime.now(timezone.utc).isoformat(),status='prepared',applied=False,command=command,
                command_sha256=digest(json_text(command).encode()) if command else None,evidence_refs=refs,
                inventory_revision_before=inventory['revision'],inventory_revision_after=None,ledger_event_revision=None)
            receipt['stage_result']=self.stage(receipt,'partial')
            intent.update(status='dispatching',execution_request_id=request.request_id,execution_result=receipt)
            state['revision']+=1
            state.setdefault('execution_events',[]).append(dict(guidance_revision=state['revision'],request_id=request.request_id,
                phase='prepared',stage_result=receipt['stage_result']))
            db.execute('INSERT INTO correction_executions VALUES (?,?,?)',(request.session_id,request.request_id,json_text(receipt)))
            db.execute('UPDATE guidance_sessions SET state=? WHERE id=?',(json_text(state),request.session_id));db.commit()
        return receipt

    def ledger_event(self, receipt, inventory):
        command=receipt['command']
        if command is None:return None
        events=[e for e in inventory['events'] if e['command']['command_id']==command['command_id']]
        if not events:return None
        if len(events)!=1 or events[0]['command']!=command or events[0]['command_sha256']!=receipt['command_sha256']:
            raise ValueError('executed correction event does not match the prepared command')
        return events[0]

    def dispatch(self, receipt):
        """Called only for a prepared, explicit review. Exact ledger retries are safe."""
        if receipt['request']['decision']=='dismiss':return
        command=receipt['command']
        if 'operation' in command:self.ledger.apply(TrackingCommand.model_validate(command))
        else:self.identity.apply(IdentityCommand.model_validate(command))

    def acknowledge(self, receipt, rejected=None):
        request=receipt['request']
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE');stored=self.read(db,request['session_id'],request['request_id'])
            if stored['status']!='prepared':return stored
            state=self.guidance.read(db,request['session_id']);intent=self.intent(state,request['intent_id'])
            if intent.get('execution_request_id')!=request['request_id'] or intent['status']!='dispatching':raise ValueError('correction reservation changed')
            inventory=self.ledger._read(db,request['session_id']);self.ledger._verify(inventory)
            event=self.ledger_event(stored,inventory)
            if stored['command'] and event is None and rejected is None:raise ValueError('no verified ledger event; retry the same prepared execution')
            applied=event is not None
            status='applied' if applied else 'dismissed' if request['decision']=='dismiss' else 'review_required'
            errors=[] if status!='review_required' else [StageError(code='correction_rejected',reason=str(rejected)[:2000],retryable=False,ref_id=intent['track_id'],field='correction')]
            stored.update(status=status,applied=applied,inventory_revision_after=inventory['revision'],ledger_event_revision=event['revision'] if event else None,
                completed_at=datetime.now(timezone.utc).isoformat(),invalidated_dependencies=(event.get('invalidated_dependencies',['ownership_totals','ownership_dependent_jobs']) if event else []))
            stored['stage_result']=self.stage(stored,'failed' if errors else 'success',errors)
            intent.update(status=status,applied=applied,execution_result=stored)
            state['revision']+=1
            state.setdefault('execution_events',[]).append(dict(guidance_revision=state['revision'],request_id=request['request_id'],phase=status,stage_result=stored['stage_result']))
            db.execute('UPDATE correction_executions SET state=? WHERE session_id=? AND request_id=?',(json_text(stored),request['session_id'],request['request_id']))
            db.execute('UPDATE guidance_sessions SET state=? WHERE id=?',(json_text(state),request['session_id']));db.commit()
        return stored

    def execute(self, request):
        request=CorrectionExecution.model_validate(request.model_dump())
        receipt=self.prepare(request)
        if receipt['status']=='prepared':
            rejected=None
            try:self.dispatch(receipt)
            except ValueError as error:rejected=error
            # Storage failures remain prepared: a ledger commit may already exist.
            receipt=self.acknowledge(receipt,rejected)
        return self.result(receipt)

    def result(self, receipt):
        state=self.guidance.snapshot(receipt['request']['session_id'])
        inventory=self.ledger.snapshot(receipt['request']['session_id'])
        if receipt['applied']:
            event=self.ledger_event(receipt,inventory)
            if event is None or event['revision']!=receipt['ledger_event_revision']:raise ValueError('applied receipt has no matching inventory event')
        return dict(execution=receipt,guidance=state,inventory=inventory)

    def snapshot(self, session):
        self.guidance.snapshot(session)
        with closing(self.frames._connect()) as db:
            receipts=[json.loads(row[0]) for row in db.execute('SELECT state FROM correction_executions WHERE session_id=? ORDER BY request_id',(session,))]
        return dict(session_id=session,executions=[self.result(r)['execution'] for r in receipts])

    def export(self,session,directory):
        root=Path(directory)
        if root.exists():raise FileExistsError('choose a fresh correction export directory')
        state=self.guidance.snapshot(session);receipts=self.snapshot(session);inventory=self.ledger.snapshot(session)
        root.mkdir(parents=True)
        for name,data in [('guidance',state),('executions',receipts),('inventory',inventory)]:
            (root/(name+'.json')).write_text(json_text(data)+'\n',encoding='utf-8')
        self.identity.export_evidence(session,root/'evidence')
        if self.guidance.snapshot(session)['revision']!=state['revision'] or self.ledger.snapshot(session)['revision']!=inventory['revision']:
            raise ValueError('state changed during review export; choose a fresh directory and export again')
        html='<!doctype html><meta charset="utf-8"><title>Guided correction review</title><h1>Guided correction review</h1><p>Explicit reviews only. Recognition and metric calibration remain separate. Applied receipts describe historical ledger events; later reviewed commands can change the current inventory.</p>'
        html+='<table><thead><tr><th>Intent</th><th>Outcome</th><th>Physical target</th><th>Applied revision</th></tr></thead><tbody>'
        for receipt in receipts['executions']:
            values=[receipt['request']['intent_id'],receipt['status'],(receipt['command'] or {}).get('track_id',''),receipt['ledger_event_revision']]
            html+='<tr>'+''.join('<td>'+escape(str(v) if v is not None else 'unknown')+'</td>' for v in values)+'</tr>'
        html+='</tbody></table>'
        for receipt in receipts['executions']:html+='<details><summary>'+escape(receipt['request']['request_id'])+'</summary><pre>'+escape(json.dumps(receipt,ensure_ascii=False,indent=2))+'</pre></details>'
        html+='<p><a href="executions.json">Execution audit</a> · <a href="guidance.json">Guided state</a> · <a href="inventory.json">Current inventory</a> · <a href="evidence/report.html">Portable originals and identity audit</a></p>'
        (root/'report.html').write_text(html,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description='M06c1 explicit guided correction execution')
    parser.add_argument('--store',type=Path,required=True);parser.add_argument('--session-id',required=True)
    parser.add_argument('--request',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('choose a fresh output')
    executor=CorrectionExecutor(GuidanceStore(FrameStore(args.store)))
    if args.request:
        request=CorrectionExecution.model_validate_json(args.request.read_bytes())
        if request.session_id!=args.session_id:parser.error('request session differs')
        executor.execute(request)
    executor.export(args.session_id,args.output);print('Guided correction review exported')


if __name__=='__main__':main()
