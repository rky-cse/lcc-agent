"""Browser access to the existing evidence-bound catalogue and geometry stages.

Bundle locations are server-owned. Requests never accept a client filesystem path.
Completed outputs have a hash ledger; interrupted work cannot masquerade as a result.
"""
import json
import re
from contextlib import closing
from pathlib import Path
from pydantic import Field
from .models import Contract
from .catalogue import CatalogueRequest, export_catalogue
from .edition import EditionRequest, EditionCommand, EditionStore, export_edition
from .identity import IdentityCommand, IdentityStore
from .measurement import measure
from .planar import MeasurementRequest
from .reconstruction import ReconstructionRequest, run_reconstruction
from .recognition_jobs import RecognitionQueue
from .tracking import digest
from .packet import json_text

Token=str
class CatalogueLookup(Contract):
    run_id: str=Field(pattern=r'^[a-f0-9]{32}$')
    job_id: str=Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    request: CatalogueRequest

class EditionLookup(Contract):
    run_id: str=Field(pattern=r'^[a-f0-9]{32}$')
    request: EditionRequest

class IdentityReview(Contract):
    bundle_id: str | None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
    command: IdentityCommand

class EditionReview(Contract):
    bundle_id: str | None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
    command: EditionCommand

class MeasurementRun(Contract):
    run_id: str=Field(pattern=r'^[a-f0-9]{32}$')
    request: MeasurementRequest

class ReconstructionRun(Contract):
    run_id: str=Field(pattern=r'^[a-f0-9]{32}$')
    request: ReconstructionRequest

class BrowserStages:
    def __init__(self,frames):
        self.frames=frames;self.jobs=RecognitionQueue(frames)
        with closing(frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS browser_stages (id TEXT PRIMARY KEY,sweep TEXT NOT NULL,kind TEXT NOT NULL,request BLOB NOT NULL,status TEXT NOT NULL,result BLOB,ledger BLOB)');db.commit()

    def path(self,run_id):
        if not re.fullmatch('[a-f0-9]{32}',run_id):raise ValueError('invalid stage run ID')
        path=self.frames.root/'browser-stages'/run_id
        if path.is_symlink() or not path.resolve().is_relative_to(self.frames.root.resolve()):raise ValueError('unsafe stage location')
        return path

    def get(self,sweep,run_id,kind=None):
        with closing(self.frames._connect()) as db:row=db.execute('SELECT sweep,kind,status,result,ledger,request FROM browser_stages WHERE id=?',(run_id,)).fetchone()
        if row is None or row[0]!=sweep or kind is not None and row[1]!=kind:raise KeyError('unknown stage in this sweep')
        if row[2]!='complete':return dict(run_id=run_id,sweep_id=sweep,kind=row[1],status=row[2],result=None)
        root=self.path(run_id)
        for name,sha in json.loads(row[4]).items():
            file=root/name
            if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()) or digest(file.read_bytes())!=sha:raise ValueError('browser stage artifact integrity failure')
        result=json.loads(row[3])
        return dict(run_id=run_id,sweep_id=sweep,kind=row[1],status='complete',result=result,input=json.loads(row[5]),
                    result_sha256=digest(row[3]),reconstruction_path=f'browser-stages/{run_id}' if row[1]=='reconstruction' else None)

    def list(self,sweep):
        with closing(self.frames._connect()) as db:ids=[r[0] for r in db.execute('SELECT id FROM browser_stages WHERE sweep=? ORDER BY rowid',(sweep,))]
        return [self.get(sweep,key) for key in ids]

    def bundle(self,sweep,run_id,kind):
        result=self.get(sweep,run_id,kind)
        if result['status']!='complete':raise ValueError('stage bundle is not complete')
        return self.path(run_id)

    def execute(self,sweep,kind,body):
        encoded=json_text(body.model_dump(mode='json')).encode();root=self.path(body.run_id)
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT sweep,kind,request FROM browser_stages WHERE id=?',(body.run_id,)).fetchone()
            if old:
                if old!=(sweep,kind,encoded):raise ValueError('stage ID reused with different inputs')
                db.commit();return self.get(sweep,body.run_id,kind)
            if db.execute('SELECT COUNT(*) FROM browser_stages WHERE sweep=?',(sweep,)).fetchone()[0]>=200:raise ValueError('browser stage limit reached')
            db.execute('INSERT INTO browser_stages VALUES (?,?,?,?,?,NULL,NULL)',(body.run_id,sweep,kind,encoded,'running'));db.commit()
        try:
            if kind=='catalogue':
                job=self.jobs.get(body.job_id)
                if job['input']['session_id']!=sweep or job['input'].get('kind','reading')!='reading' or not job['eligible_for_review']:raise ValueError('reading is not current for this sweep')
                result=export_catalogue(self.frames,body.request,self.jobs._directory(body.job_id),root,live=True)
            else:
                if body.request.sweep_id!=sweep:raise ValueError('stage sweep differs from URL')
                if kind=='edition':result=export_edition(self.frames,body.request,root,live=True)
                elif kind=='measurement':
                    result=measure(self.frames,body.request);root.mkdir(parents=True);(root/'measurement_result.json').write_text(json_text(result),encoding='utf-8')
                elif kind=='reconstruction':result=run_reconstruction(self.frames,body.request,root)
                else:raise ValueError('unknown stage')
            # Pin the actual saved result bytes used by review commands.
            name={'catalogue':'catalogue_result.json','edition':'edition_result.json','measurement':'measurement_result.json','reconstruction':'reconstruction_result.json'}[kind]
            encoded_result=(root/name).read_bytes()
            if json.loads(encoded_result)!=json.loads(json_text(result)):raise ValueError('saved stage result differs')
            ledger={str(p.relative_to(root).as_posix()):digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
            with closing(self.frames._connect()) as db:db.execute('UPDATE browser_stages SET status=?,result=?,ledger=? WHERE id=?',('complete',encoded_result,json_text(ledger),body.run_id));db.commit()
            return self.get(sweep,body.run_id,kind)
        except Exception:
            with closing(self.frames._connect()) as db:db.execute('UPDATE browser_stages SET status=? WHERE id=?',('failed',body.run_id));db.commit()
            raise

    def identity(self,sweep,body):
        if body.command.sweep_id!=sweep:raise ValueError('identity sweep differs from URL')
        bundle=self.bundle(sweep,body.bundle_id,'catalogue') if body.bundle_id else None
        return IdentityStore(self.frames).apply(body.command,bundle)

    def edition(self,sweep,body):
        if body.command.sweep_id!=sweep:raise ValueError('edition sweep differs from URL')
        bundle=self.bundle(sweep,body.bundle_id,'edition') if body.bundle_id else None
        return EditionStore(self.frames).apply(body.command,bundle)
