"""M05b2: explicit bibliographic review on distinct physical tracks."""
import argparse
import json
import re
from contextlib import closing
from datetime import datetime,timezone
from html import escape
from pathlib import Path
from typing import Annotated,Literal

from pydantic import Field,model_validator

from .capture_store import FrameStore
from .catalogue import CatalogueRequest,evaluate,load_reading,parse_search,query_url
from .models import Contract,StageResult
from .packet import json_text
from .tracking import TrackStore,digest


def isbn_value(value):
    value=re.sub(r'[\s-]','',value).upper()
    valid=(len(value)==10 and re.fullmatch(r'[0-9]{9}[0-9X]',value) is not None
        and sum((10-i)*(10 if c=='X' else int(c)) for i,c in enumerate(value))%11==0)
    valid=valid or (len(value)==13 and re.fullmatch(r'[0-9]{13}',value) is not None and value.startswith(('978','979'))
        and sum(int(c)*(1 if i%2==0 else 3) for i,c in enumerate(value))%10==0)
    if not valid: raise ValueError('ISBN requires a valid ISBN-10/13 checksum')
    return value


class MetadataDecision(Contract):
    field: Literal['edition','publisher','isbn']
    value: str = Field(min_length=1,max_length=500)
    source: Literal['visible_text','claimant_assertion']
    span_id: str | None
    claimant_statement: str | None = Field(max_length=2000)

    @model_validator(mode='after')
    def shape(self):
        if not self.value.strip(): raise ValueError('metadata must be nonblank')
        if self.source=='visible_text':
            if not self.span_id or self.claimant_statement is not None: raise ValueError('visible metadata requires span only')
        elif self.span_id is not None or not self.claimant_statement or not self.claimant_statement.strip():
            raise ValueError('claimant metadata requires a literal statement, not a span')
        if self.field=='isbn': isbn_value(self.value)
        return self


class IdentityCommand(Contract):
    command_id: str = Field(min_length=1,max_length=128)
    sweep_id: str = Field(min_length=1,max_length=128)
    expected_revision: int = Field(ge=0)
    track_id: str = Field(min_length=1,max_length=128)
    action: Literal['accept_work','reject_work','clear_identity']
    catalogue_result_sha256: str | None = Field(pattern=r'^[a-f0-9]{64}$')
    work_id: str | None = Field(pattern=r'^/works/OL[0-9]+W$')
    confirmed_span_ids: Annotated[list[str],Field(max_length=24)]
    metadata: Annotated[list[MetadataDecision],Field(max_length=3)]
    needs_appraisal: bool
    reviewer: str = Field(min_length=1,max_length=200)
    reason: str = Field(min_length=1,max_length=2000)

    @model_validator(mode='after')
    def shape(self):
        if not self.reviewer.strip() or not self.reason.strip(): raise ValueError('reviewer and reason must be nonblank')
        if self.action=='clear_identity':
            if self.catalogue_result_sha256 or self.work_id: raise ValueError('clear has no catalogue target')
        elif not self.catalogue_result_sha256 or not self.work_id: raise ValueError('work review requires pinned catalogue and work')
        if self.action!='accept_work' and (self.metadata or self.confirmed_span_ids or self.needs_appraisal):
            raise ValueError('only acceptance has confirmations, metadata and appraisal flags')
        if len(self.confirmed_span_ids)!=len(set(self.confirmed_span_ids)): raise ValueError('duplicate span confirmation')
        if len({m.field for m in self.metadata})!=len(self.metadata): raise ValueError('one decision per metadata field')
        return self


def validated_bundle(frames,command,directory):
    root=Path(directory);raw=(root/'catalogue_result.json').read_bytes()
    if len(raw)>2*1024*1024 or digest(raw)!=command.catalogue_result_sha256:
        raise ValueError('catalogue result size/hash mismatch')
    result=json.loads(raw);request=CatalogueRequest.model_validate(result['request'])
    reading,reading_request,title,author,evidence=load_reading(frames,root,request)
    if reading_request.sweep_id!=command.sweep_id or reading_request.expected_revision!=command.expected_revision:
        raise ValueError('catalogue input sweep/revision mismatch')
    if reading['crop']['track_id']!=command.track_id: raise ValueError('catalogue observation belongs to another physical track')
    catalogue_raw=(root/'catalogue_response.json').read_bytes()
    if len(catalogue_raw)>2*1024*1024 or digest(catalogue_raw)!=result['catalogue_response_sha256']:
        raise ValueError('catalogue response size/hash mismatch')
    rows,count,complete=parse_search(catalogue_raw,request.limit)
    candidates=evaluate(rows,title,author,reading)
    url=query_url(title,author,request.limit)
    stage=StageResult.model_validate(result['stage_result'])
    job=digest(json_text(dict(request=request.model_dump(),query_url=url)).encode())
    supported=[c for c in candidates if c['disposition']=='supported_candidate']
    outcome='no_match' if count==0 else 'ambiguous' if len(supported)>1 else 'supported_candidate' if len(supported)==1 else 'needs_review'
    expected=dict(candidates=candidates,query_url=url,selected_title=title,selected_author=author,
        reading_source_sha256=request.reading_result_sha256,search_result_count=count,returned_count=len(rows),
        search_complete=complete,outcome=outcome,synthetic=reading['crop']['synthetic'],accepted_work_id=None,
        accepted_edition_id=None,calibrated_confidence=None,inventory_mutated=False,edition_status='unresolved',requires_review=True)
    if any(result.get(k)!=v for k,v in expected.items()): raise ValueError('catalogue projection differs from evidence')
    if (stage.stage!='catalogue_work_candidates' or stage.job_id!=job or stage.sweep_id!=command.sweep_id
            or stage.input_revision!=command.expected_revision or stage.status!='partial' or stage.errors
            or stage.evidence_refs!=[reading['crop']['frame_ref']]): raise ValueError('invalid catalogue stage')
    selected=[c for c in candidates if c['work_id']==command.work_id]
    if len(selected)!=1: raise ValueError('work was not returned in pinned catalogue')
    if command.action=='accept_work' and selected[0]['disposition']!='supported_candidate':
        raise ValueError('only supported candidates can be accepted; obtain corrected evidence first')
    evidence['catalogue_result.json']=raw;evidence['catalogue_response.json']=catalogue_raw
    return result,reading,request,selected[0],evidence


def accepted_identity(command,result,reading,request):
    spans={s['id']:s for s in reading['text_evidence']}
    required=set(request.title_span_ids+request.author_span_ids)
    values=dict(title=result['selected_title'],author=result['selected_author'],edition='',publisher='',isbn='')
    frame=reading['crop']['frame_ref'];refs=dict(title=[frame],author=[frame])
    provenance={f:dict(source='reviewed_visible_text_and_catalogue',span_ids=ids,
        frame_ref=frame,catalogue_source=result['source'],catalogue_result_sha256=command.catalogue_result_sha256) for f,ids in
        [('title',request.title_span_ids),('author',request.author_span_ids)]}
    assertion=False
    for decision in command.metadata:
        value=decision.value
        if decision.source=='visible_text':
            span=spans.get(decision.span_id)
            if not span or span['tentative_role']!=decision.field: raise ValueError('metadata span missing or wrong role')
            matches=isbn_value(span['text'])==isbn_value(value) if decision.field=='isbn' else span['text']==value
            if not matches: raise ValueError('metadata value must preserve literal visible text')
            required.add(decision.span_id);refs[decision.field]=[frame]
        else:
            assertion=True;refs[decision.field]=[]
        values[decision.field]=isbn_value(value) if decision.field=='isbn' else value
        provenance[decision.field]=decision.model_dump(mode='json')
    if set(command.confirmed_span_ids)!=required: raise ValueError('confirm exactly the title/author and used metadata spans')
    flags=' '.join([values['edition']]+[m.claimant_statement or '' for m in command.metadata]).casefold()
    if re.search(r'\b(first edition|1st edition|signed|rare|antiquarian)\b',flags) and not command.needs_appraisal:
        raise ValueError('special-edition/rarity assertion requires appraisal')
    return dict(work_id=command.work_id,accepted_edition_id=None,synthetic=reading['crop']['synthetic'],catalogue_source=result['source'],
        edition_status='claimant_asserted_metadata' if assertion else 'visible_metadata_confirmed' if command.metadata else 'unresolved',
        values=values,status='needs_appraisal' if command.needs_appraisal else 'identified',id_confidence=None,
        field_evidence=refs,field_provenance=provenance,review_command_id=command.command_id,
        catalogue_result_sha256=command.catalogue_result_sha256,requires_edition_review=True)


class IdentityStore:
    def __init__(self,frames):
        self.frames=frames;self.ledger=TrackStore(frames)
        with closing(frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS identity_artifacts (sha256 TEXT PRIMARY KEY, content BLOB NOT NULL)');db.commit()

    @staticmethod
    def retry(state,command,fingerprint):
        for event in state['events']:
            if event['command']['command_id']==command.command_id:
                if event['command_sha256']!=fingerprint: raise ValueError('command ID reused with different payload')
                return True
        return False

    def apply(self,command,bundle=None):
        started=datetime.now(timezone.utc)
        command=IdentityCommand.model_validate(command.model_dump());fingerprint=digest(json_text(command.model_dump()).encode())
        # Check exact retries before loading now-historical input bundles.
        snapshot=self.ledger.snapshot(command.sweep_id)
        if self.retry(snapshot,command,fingerprint): return snapshot
        if snapshot['revision']!=command.expected_revision: raise ValueError('stale inventory revision')
        evidence={};identity=None;candidate=None
        if command.action=='clear_identity':
            if bundle is not None: raise ValueError('clear has no bundle')
        else:
            if bundle is None: raise ValueError('work review requires bundle')
            result,reading,request,candidate,evidence=validated_bundle(self.frames,command,bundle)
            if command.action=='accept_work': identity=accepted_identity(command,result,reading,request)
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE');state=self.ledger._read(db,command.sweep_id);self.ledger._verify(state)
            if self.retry(state,command,fingerprint): return self.ledger._snapshot(state)
            if state['revision']!=command.expected_revision: raise ValueError('inventory changed during identity review')
            if len(state['events'])>=10000: raise ValueError('inventory ledger limit exceeded')
            track=state['tracks'].get(command.track_id)
            if track is None: raise ValueError('unknown physical track')
            previous=track.get('bibliography');rejected=track.setdefault('rejected_work_ids',[])
            if command.action=='accept_work':
                track['bibliography']=identity
                if command.work_id in rejected: rejected.remove(command.work_id)
            elif command.action=='clear_identity': track['bibliography']=None
            else:
                if command.work_id not in rejected: rejected.append(command.work_id)
                if previous and previous['work_id']==command.work_id: track['bibliography']=None
            sources=state.setdefault('identity_evidence',[])
            for name,data in evidence.items():
                if name.startswith('original'): continue # original remains immutable in FrameStore
                sha=digest(data)
                db.execute('INSERT OR IGNORE INTO identity_artifacts VALUES (?,?)',(sha,data))
                if sha not in sources: sources.append(sha)
            state['revision']+=1
            stage=StageResult(sweep_id=command.sweep_id,job_id=fingerprint,input_revision=command.expected_revision,
                stage='bibliographic_review',status='partial' if command.action=='accept_work' else 'success',
                started_at=started,finished_at=datetime.now(timezone.utc),
                evidence_refs=sorted({state['observations'][oid]['frame_ref'] for oid in track['observations']}),
                warnings=['Catalogue edition identity and calibrated confidence remain unknown; no prices inferred.'] if identity else [],errors=[])
            state['events'].append(dict(revision=state['revision'],recorded_at=datetime.now(timezone.utc).isoformat(),
                command_sha256=fingerprint,command=command.model_dump(mode='json'),
                stage_result=stage.model_dump(mode='json'),
                previous_identity=previous,new_identity=track.get('bibliography'),
                invalidated_dependencies=['edition','replacement_cost','used_value','totals'],
                saved_artifacts={name:digest(data) for name,data in evidence.items() if not name.startswith('original')}))
            # Validate projected Book contracts before committing the mutation.
            self.ledger._snapshot(state)
            db.execute('UPDATE physical_inventory SET state=? WHERE sweep_id=?',(json_text(state),command.sweep_id));db.commit()
            return self.ledger._snapshot(state)

    def export_evidence(self,sweep_id,directory):
        snapshot=self.ledger.snapshot(sweep_id);root=Path(directory)
        if root.exists(): raise FileExistsError('choose fresh evidence directory')
        root.mkdir(parents=True)
        with closing(self.frames._connect()) as db:
            for sha in snapshot.get('identity_evidence',[]):
                data=db.execute('SELECT content FROM identity_artifacts WHERE sha256=?',(sha,)).fetchone()[0]
                (root/sha).write_bytes(data)
        (root/'inventory.json').write_text(json_text(snapshot)+'\n',encoding='utf-8')
        manifest=[]
        for ref in sorted({o['frame_ref'] for o in snapshot['observations']}):
            frame=self.frames.get(ref);target=root/frame.path;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(self.frames.read(ref));manifest.append(frame.model_dump(mode='json'))
        (root/'frame-manifest.json').write_text(json_text(manifest)+'\n',encoding='utf-8')
        paths={f['id']:f['path'] for f in manifest};tracks={t['id']:t for t in snapshot['tracks']}
        artifacts={sha:[] for sha in snapshot.get('identity_evidence',[])}
        for event in snapshot['events']:
            for name,sha in event.get('saved_artifacts',{}).items():
                if name not in artifacts[sha]: artifacts[sha].append(name)
        (root/'artifact-manifest.json').write_text(json_text([dict(sha256=sha,path=sha,roles=names) for sha,names in artifacts.items()])+'\n',encoding='utf-8')
        html='<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Reviewed work inventory</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:20px}table{border-collapse:collapse}td,th{padding:12px;border:1px solid #ccd}small{display:block}</style>'
        edition_count=sum(bool(t.get('bibliography',{}).get('accepted_edition_id')) for t in snapshot['tracks'] if t.get('bibliography'))
        edition_message=f'Reviewed catalogue edition records: {edition_count}. Calibrated confidence remains unknown.' if edition_count else 'Catalogue edition identity and calibrated confidence remain unknown.'
        html+=f'<h1>Reviewed work inventory</h1><p>Revision {snapshot["revision"]}; physical tracks {snapshot["assigned_track_count"]}; complete book count unknown.</p><p>Includes synthetic frames: {any(f["synthetic"] for f in manifest)}.</p><p>Work acceptance is explicit review. {edition_message} Prices are unavailable.</p>'
        for book in snapshot['books']:
            info=tracks[book['id']].get('bibliography')
            html+=f'<h2>{escape(book["title"] or "Unidentified book")}</h2><p>{escape(book["id"])} · {book["status"]} · {"Owned" if book["owned"] else "Excluded"}</p><table><tr><th>Field</th><th>Value</th><th>Provenance</th></tr>'
            for field in ['author','edition','publisher','isbn']:
                source=info['field_provenance'].get(field,{}) if info else {}
                html+=f'<tr><td>{field}</td><td>{escape(book[field] or "Unknown")}</td><td>{escape(source.get("source","Unavailable"))}<small>{escape(source.get("claimant_statement") or "")}</small></td></tr>'
            html+='</table>'
            if info:
                html+=f'<p>Reviewed work: {escape(info["work_id"])}; edition metadata: {info["edition_status"]}; accepted catalogue edition: {escape(info.get("accepted_edition_id") or "unknown")}. Work catalogue source: {escape(info.get("catalogue_source","unspecified"))}.</p>'
                if info.get('edition_review'):
                    review=info['edition_review']
                    html+=f'<p>Edition source: {escape(review["catalogue_source"])}. Binding is claimant-declared: {escape(review["owned_physical_format"])}. Statement: {escape(review["format_statement"])}</p>'
            html+=f'<p><a href="{escape(paths[book["frame_ref"]],quote=True)}">Exact saved original</a></p>'
        html+='<h2>Review findings</h2><ul>'
        for review in snapshot['review_queue']: html+=f'<li>{escape(review["reason"])}</li>'
        html+='</ul><h2>Archived reading and catalogue evidence</h2><ul>'
        for sha,names in artifacts.items(): html+=f'<li><a href="{sha}">{escape(", ".join(names))}</a> · {sha}</li>'
        html+='</ul><p><a href="inventory.json">Full inventory and audit events</a> | <a href="frame-manifest.json">Original frame manifest</a> | <a href="artifact-manifest.json">Archived artifact manifest</a></p>'
        (root/'report.html').write_text(html,encoding='utf-8')
        return snapshot


def main():
    parser=argparse.ArgumentParser(description='M05b2 explicit bibliographic review')
    for name in ['store','command','output']: parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--bundle',type=Path)
    args=parser.parse_args()
    if args.output.exists(): raise FileExistsError('choose a fresh output file')
    command=IdentityCommand.model_validate_json(args.command.read_text(encoding='utf-8'))
    snapshot=IdentityStore(FrameStore(args.store)).apply(command,args.bundle)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json_text(snapshot)+'\n',encoding='utf-8')
    print(f'Review saved at revision {snapshot["revision"]}; no prices inferred')


if __name__=='__main__': main()
