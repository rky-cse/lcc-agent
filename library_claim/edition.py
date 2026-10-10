"""M05b3: bounded edition lookup and explicit owned-copy review."""
import argparse
import json
import re
from contextlib import closing
from datetime import datetime,timezone
from html import escape
from pathlib import Path
from typing import Annotated,Literal

from pydantic import BaseModel,ConfigDict,Field,model_validator

from .capture_store import FrameStore
from .catalogue import CatalogueClient,normalize
from .identity import IdentityStore,isbn_value
from .models import Contract,StageError,StageResult
from .packet import json_text
from .tracking import TrackStore,digest


class EditionRequest(Contract):
    sweep_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    track_id: str = Field(min_length=1)
    edition_id: str | None = Field(pattern=r'^/books/OL[0-9]+M$')
    limit: int = Field(ge=1,le=10)
    owned_physical_format: Literal['hardcover','paperback','other_print','unknown']
    format_statement: str = Field(min_length=1,max_length=2000)

    @model_validator(mode='after')
    def nonblank(self):
        if not self.format_statement.strip(): raise ValueError('record a literal binding declaration or uncertainty')
        return self


class Ref(BaseModel):
    model_config=ConfigDict(extra='ignore')
    key: str = Field(pattern=r'^/works/OL[0-9]+W$')


class EditionDoc(BaseModel):
    model_config=ConfigDict(extra='ignore')
    key: str = Field(pattern=r'^/books/OL[0-9]+M$')
    title: str = Field(min_length=1,max_length=1000)
    works: Annotated[list[Ref],Field(max_length=16)] = Field(default_factory=list)
    isbn_10: Annotated[list[Annotated[str,Field(max_length=40)]],Field(max_length=32)] = Field(default_factory=list)
    isbn_13: Annotated[list[Annotated[str,Field(max_length=40)]],Field(max_length=32)] = Field(default_factory=list)
    publishers: Annotated[list[Annotated[str,Field(max_length=500)]],Field(max_length=32)] = Field(default_factory=list)
    physical_format: str = Field(default='',max_length=200)
    edition_name: str = Field(default='',max_length=500)


def parse_editions(raw,request):
    value=json.loads(raw)
    if not isinstance(value,dict): raise ValueError('edition response must be an object')
    if request.edition_id:
        row=EditionDoc.model_validate(value).model_dump()
        if row['key']!=request.edition_id: raise ValueError('edition endpoint returned another edition')
        return [row],1,True
    entries=value.get('entries');count=value.get('size')
    if (not isinstance(entries,list) or len(entries)>request.limit or not isinstance(count,int) or isinstance(count,bool)
            or count<len(entries) or count<0): raise ValueError('invalid bounded work editions page')
    rows=[EditionDoc.model_validate(row).model_dump() for row in entries]
    if len({r['key'] for r in rows})!=len(rows): raise ValueError('duplicate edition records')
    return rows,count,count==len(rows)


def context(frames,request):
    snapshot=TrackStore(frames).snapshot(request.sweep_id)
    if snapshot['revision']!=request.expected_revision: raise ValueError('stale inventory revision')
    matches=[t for t in snapshot['tracks'] if t['id']==request.track_id]
    if len(matches)!=1 or not matches[0].get('bibliography'): raise ValueError('edition lookup requires a reviewed physical work')
    info=matches[0]['bibliography'];provenance=info['field_provenance'].get('isbn',{})
    isbn=None
    if provenance.get('source')=='visible_text' and info['values']['isbn']:
        isbn=isbn_value(info['values']['isbn'])
        # Verify the ISBN was part of the reviewed, archived observation, not
        # borrowed later from a remote edition or claimant assertion.
        events=[e for e in snapshot['events'] if e['command']['command_id']==info['review_command_id']]
        if len(events)!=1: raise ValueError('missing original work review')
        sha=events[0]['saved_artifacts']['reading_result.json']
        with closing(frames._connect()) as db:
            raw=db.execute('SELECT content FROM identity_artifacts WHERE sha256=?',(sha,)).fetchone()[0]
        reading=json.loads(raw)
        spans=[s for s in reading['text_evidence'] if s['id']==provenance['span_id']]
        if (len(spans)!=1 or spans[0]['tentative_role']!='isbn' or isbn_value(spans[0]['text'])!=isbn
                or reading['crop']['track_id']!=request.track_id): raise ValueError('owned ISBN differs from reviewed observation')
    return snapshot,info,isbn


def endpoint(request,work_id):
    if request.edition_id: return 'https://openlibrary.org'+request.edition_id+'.json'
    return f'https://openlibrary.org{work_id}/editions.json?limit={request.limit}&offset=0'


def format_kind(value):
    text=normalize(value)
    if any(word in text for word in ['ebook','e book','digital','audio','kindle','electronic']): return 'digital'
    if text in ['hardcover','hardback','hard cover','hard back']: return 'hardcover'
    if text in ['paperback','paper back','softcover','soft cover','softback','soft back','mass market paperback','trade paperback']: return 'paperback'
    return 'unknown'


def evaluate_editions(rows,request,info,isbn):
    candidates=[]
    for row in rows:
        reasons=[];contradictions=[]
        links=[w['key'] for w in row['works']]
        if not links: reasons.append('edition work link missing')
        elif links!=[info['work_id']]: contradictions.append('edition does not link exclusively to reviewed work')
        if normalize(row['title'])!=normalize(info['values']['title']): contradictions.append('edition title differs from reviewed title')
        remote=[]
        for value in row['isbn_10']+row['isbn_13']:
            try: remote.append(isbn_value(value))
            except ValueError: reasons.append('catalogue contains an invalid ISBN')
        if not remote: reasons.append('catalogue ISBN missing or unusable')
        elif isbn not in remote: contradictions.append('reviewed visible ISBN absent from edition record')
        kind=format_kind(row['physical_format'])
        if kind=='digital': contradictions.append('digital/audio format is ineligible for physical copy')
        elif kind=='unknown' or request.owned_physical_format in ['unknown','other_print']: reasons.append('physical binding not established by supported format vocabulary')
        elif kind!=request.owned_physical_format: contradictions.append('physical binding contradicts declared copy')
        publisher=info['values']['publisher'];edition=info['values']['edition']
        if publisher:
            if not row['publishers']: reasons.append('catalogue publisher missing for supplied metadata')
            elif not any(normalize(p)==normalize(publisher) for p in row['publishers']): contradictions.append('publisher contradicts supplied metadata')
        if edition:
            if not row['edition_name']: reasons.append('catalogue edition statement missing for supplied metadata')
            elif normalize(edition)!=normalize(row['edition_name']): contradictions.append('edition statement contradicts supplied metadata')
        candidates.append(dict(edition_id=row['key'],record=row,physical_format=kind,
            disposition='contradicted' if contradictions else 'needs_review' if reasons else 'supported_candidate',
            reasons=contradictions+reasons))
    return candidates


class EditionClient(CatalogueClient):
    def fetch(self,url,request):
        if not re.fullmatch(r'https://openlibrary\.org/(?:books/OL[0-9]+M\.json|works/OL[0-9]+W/editions\.json\?limit=(?:[1-9]|10)&offset=0)',url):
            raise ValueError('unsupported edition endpoint')
        return self._fetch(url,lambda raw:parse_editions(raw,request))


def computed(request,info,isbn,raw):
    rows,count,complete=parse_editions(raw,request);candidates=evaluate_editions(rows,request,info,isbn)
    supported=[c for c in candidates if c['disposition']=='supported_candidate']
    outcome='no_match' if count==0 else 'ambiguous' if len(supported)>1 else 'supported_candidate' if len(supported)==1 else 'needs_review'
    return dict(candidates=candidates,returned_count=len(rows),catalogue_count=count,search_complete=complete,outcome=outcome)


def export_edition(frames,request,output,response_bytes=None,live=False):
    request=EditionRequest.model_validate(request.model_dump());root=Path(output);started=datetime.now(timezone.utc)
    if root.exists(): raise FileExistsError('choose a fresh edition directory')
    if live and response_bytes is not None: raise ValueError('live lookup cannot use replay')
    snapshot,info,isbn=context(frames,request);url=endpoint(request,info['work_id']);raw=None;failure=None;usage=dict(requests=0,cache_hit=False)
    projection=dict(candidates=[],returned_count=0,catalogue_count=None,search_complete=False,outcome='unavailable')
    if isbn is None: failure=dict(code='owned_isbn_unverified',reason='No reviewed visible ISBN; edition was not queried',retryable=False)
    else:
        if live: raw,failure,usage=EditionClient(frames).fetch(url,request)
        else:
            if response_bytes is None: raise ValueError('saved edition response required')
            raw=response_bytes
        if raw is not None:
            if len(raw)>2*1024*1024: raise ValueError('edition response too large')
            projection=computed(request,info,isbn,raw)
    if TrackStore(frames).snapshot(request.sweep_id)['revision']!=request.expected_revision: raise ValueError('inventory changed during edition lookup')
    fingerprint=digest(json_text(dict(request=request.model_dump(),work_id=info['work_id'],owned_isbn=isbn,query_url=url)).encode())
    refs=sorted({o['frame_ref'] for o in snapshot['observations'] if o['track_id']==request.track_id})
    stage=StageResult(sweep_id=request.sweep_id,job_id=fingerprint,input_revision=request.expected_revision,stage='catalogue_edition_candidates',
        status='unavailable' if failure else 'partial',started_at=started,finished_at=datetime.now(timezone.utc),evidence_refs=refs,
        warnings=['Edition candidates require explicit review; binding is claimant-declared; no prices or authentication.'],
        errors=[StageError(**failure,ref_id=request.track_id,field='edition')] if failure else [])
    result=dict(schema_version='1.0',request=request.model_dump(mode='json'),stage_result=stage.model_dump(mode='json'),
        work_id=info['work_id'],work_review_command_id=info['review_command_id'],owned_isbn=isbn,synthetic=info['synthetic'],
        source='open_library' if live else 'offline_replay',query_url=url,response_sha256=digest(raw) if raw is not None else None,
        usage=usage,accepted_edition_id=None,inventory_mutated=False,requires_review=True,**projection)
    root.mkdir(parents=True);(root/'edition_result.json').write_text(json_text(result)+'\n',encoding='utf-8')
    if raw is not None: (root/'edition_response.json').write_bytes(raw)
    html='<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Edition candidate review</title><style>body{font:16px system-ui;max-width:1050px;margin:30px auto;padding:20px}td,th{padding:10px;border:1px solid #ccd}table{border-collapse:collapse}</style><h1>Edition candidate review</h1>'
    html+=f'<p>Outcome: {projection["outcome"]}; synthetic: {info["synthetic"]}; source: {result["source"]}. No edition accepted; prices unknown.</p><p>Reviewed visible ISBN: {escape(isbn or "unknown")}; declared binding: {request.owned_physical_format}.</p>'
    html+=f'<p>Binding declaration: {escape(request.format_statement)}</p><p>Reviewed work: {escape(info["work_id"])}; source work-review command: {escape(info["review_command_id"])}. The ISBN observation is preserved in the ledger evidence archive.</p>'
    if failure: html+=f'<p>{escape(failure["reason"])}</p>'
    for candidate in projection['candidates']:
        html+=f'<h2>{escape(candidate["edition_id"])}</h2><p>{escape(candidate["record"]["title"])} · {candidate["disposition"]}</p><p>{escape("; ".join(candidate["reasons"]) or "Exact evidence checks passed; explicit review required")}</p>'
        row=candidate['record']
        values=dict(work_links=', '.join(w['key'] for w in row['works']),isbn=', '.join(row['isbn_10']+row['isbn_13']),
            physical_format=row['physical_format'],publishers=', '.join(row['publishers']),edition_statement=row['edition_name'])
        html+='<table><tr><th>Catalogue field</th><th>Literal value</th></tr>'
        for field,value in values.items(): html+=f'<tr><td>{field}</td><td>{escape(value or "Missing")}</td></tr>'
        html+=f'</table><p><a href="https://openlibrary.org{escape(candidate["edition_id"],quote=True)}">Catalogue edition page</a></p>'
    html+=f'<p>Returned {projection["returned_count"]}; catalogue count {projection["catalogue_count"]}; complete: {projection["search_complete"]}.</p><a href="edition_result.json">Evidence JSON</a>'
    (root/'report.html').write_text(html,encoding='utf-8');return result


class EditionCommand(Contract):
    command_id: str = Field(min_length=1,max_length=128)
    sweep_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    track_id: str = Field(min_length=1)
    action: Literal['accept_edition','reject_edition','clear_edition']
    edition_result_sha256: str | None = Field(pattern=r'^[a-f0-9]{64}$')
    edition_id: str | None = Field(pattern=r'^/books/OL[0-9]+M$')
    reviewer: str = Field(min_length=1,max_length=200)
    reason: str = Field(min_length=1,max_length=2000)

    @model_validator(mode='after')
    def shape(self):
        if not self.reviewer.strip() or not self.reason.strip(): raise ValueError('reviewer/reason must be nonblank')
        if self.action=='clear_edition':
            if self.edition_result_sha256 or self.edition_id: raise ValueError('clear has no edition bundle target')
        elif not self.edition_result_sha256 or not self.edition_id: raise ValueError('edition decision requires pinned result and edition')
        return self


def validate_review(frames,command,bundle):
    root=Path(bundle);raw=(root/'edition_result.json').read_bytes()
    if len(raw)>2*1024*1024 or digest(raw)!=command.edition_result_sha256: raise ValueError('edition result hash/size mismatch')
    result=json.loads(raw);request=EditionRequest.model_validate(result['request'])
    if (request.sweep_id,request.expected_revision,request.track_id)!=(command.sweep_id,command.expected_revision,command.track_id): raise ValueError('edition review target/revision mismatch')
    snapshot,info,isbn=context(frames,request)
    if isbn is None: raise ValueError('edition acceptance requires reviewed visible ISBN')
    response=(root/'edition_response.json').read_bytes()
    if len(response)>2*1024*1024 or digest(response)!=result['response_sha256']: raise ValueError('edition response hash/size mismatch')
    projection=computed(request,info,isbn,response);url=endpoint(request,info['work_id'])
    expected=dict(**projection,work_id=info['work_id'],work_review_command_id=info['review_command_id'],owned_isbn=isbn,
        query_url=url,synthetic=info['synthetic'],accepted_edition_id=None,inventory_mutated=False,requires_review=True)
    if any(result.get(k)!=v for k,v in expected.items()): raise ValueError('edition result differs from validated records')
    stage=StageResult.model_validate(result['stage_result'])
    job=digest(json_text(dict(request=request.model_dump(),work_id=info['work_id'],owned_isbn=isbn,query_url=url)).encode())
    refs=sorted({o['frame_ref'] for o in snapshot['observations'] if o['track_id']==command.track_id})
    if (stage.stage!='catalogue_edition_candidates' or stage.job_id!=job or stage.input_revision!=command.expected_revision
            or stage.sweep_id!=command.sweep_id or stage.status!='partial' or stage.errors or stage.evidence_refs!=refs): raise ValueError('invalid edition stage')
    selected=[c for c in projection['candidates'] if c['edition_id']==command.edition_id]
    if len(selected)!=1: raise ValueError('edition was not returned')
    if command.action=='accept_edition' and selected[0]['disposition']!='supported_candidate': raise ValueError('edition candidate not supported')
    return result,{'edition_result.json':raw,'edition_response.json':response}


class EditionStore(IdentityStore):
    def apply(self,command,bundle=None):
        command=EditionCommand.model_validate(command.model_dump());fingerprint=digest(json_text(command.model_dump()).encode());started=datetime.now(timezone.utc)
        snapshot=self.ledger.snapshot(command.sweep_id)
        if self.retry(snapshot,command,fingerprint): return snapshot
        if snapshot['revision']!=command.expected_revision: raise ValueError('stale inventory revision')
        evidence={};result=None
        if command.action=='clear_edition':
            if bundle is not None: raise ValueError('clear has no bundle')
        else:
            if bundle is None: raise ValueError('edition review requires bundle')
            result,evidence=validate_review(self.frames,command,bundle)
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE');state=self.ledger._read(db,command.sweep_id);self.ledger._verify(state)
            if self.retry(state,command,fingerprint): return self.ledger._snapshot(state)
            if state['revision']!=command.expected_revision: raise ValueError('inventory changed during edition review')
            if len(state['events'])>=10000: raise ValueError('inventory ledger limit exceeded')
            track=state['tracks'].get(command.track_id)
            if track is None or not track.get('bibliography'): raise ValueError('edition target has no reviewed work')
            previous=track['bibliography'];info=json.loads(json_text(previous));track['bibliography']=info
            rejected=track.setdefault('rejected_edition_ids',[])
            if command.action=='accept_edition':
                info.setdefault('metadata_status',info['edition_status']);info['accepted_edition_id']=command.edition_id
                info['edition_status']='catalogue_matched_reviewed';info['requires_edition_review']=False
                info['edition_review']=dict(command_id=command.command_id,edition_result_sha256=command.edition_result_sha256,
                    catalogue_source=result['source'],owned_physical_format=result['request']['owned_physical_format'],
                    format_statement=result['request']['format_statement'],format_source='claimant_declaration')
                if command.edition_id in rejected: rejected.remove(command.edition_id)
            else:
                if command.action=='reject_edition' and command.edition_id not in rejected: rejected.append(command.edition_id)
                if command.action=='clear_edition' or info['accepted_edition_id']==command.edition_id:
                    info['accepted_edition_id']=None;info['edition_status']=info.pop('metadata_status',info['edition_status'])
                    info.pop('edition_review',None);info['requires_edition_review']=True
            hashes=state.setdefault('identity_evidence',[])
            for name,data in evidence.items():
                sha=digest(data);db.execute('INSERT OR IGNORE INTO identity_artifacts VALUES (?,?)',(sha,data))
                if sha not in hashes: hashes.append(sha)
            state['revision']+=1
            stage=StageResult(sweep_id=command.sweep_id,job_id=fingerprint,input_revision=command.expected_revision,stage='edition_review',
                status='success',started_at=started,finished_at=datetime.now(timezone.utc),
                evidence_refs=sorted({state['observations'][oid]['frame_ref'] for oid in track['observations']}),
                warnings=['Binding remains claimant-declared; edition match does not authenticate printing/signature or determine price.'],errors=[])
            state['events'].append(dict(revision=state['revision'],recorded_at=datetime.now(timezone.utc).isoformat(),command=command.model_dump(mode='json'),
                command_sha256=fingerprint,stage_result=stage.model_dump(mode='json'),previous_identity=previous,new_identity=info,
                invalidated_dependencies=['replacement_cost','used_value','totals'],saved_artifacts={name:digest(data) for name,data in evidence.items()}))
            self.ledger._snapshot(state);db.execute('UPDATE physical_inventory SET state=? WHERE sweep_id=?',(json_text(state),command.sweep_id));db.commit()
            return self.ledger._snapshot(state)


def main():
    parser=argparse.ArgumentParser(description='M05b3 evidence-bound edition lookup/review');sub=parser.add_subparsers(dest='operation',required=True)
    lookup=sub.add_parser('lookup');review=sub.add_parser('review')
    for part in [lookup,review]:
        for name in ['store','input','output']: part.add_argument('--'+name,type=Path,required=True)
    mode=lookup.add_mutually_exclusive_group(required=True);mode.add_argument('--response',type=Path);mode.add_argument('--open-library',action='store_true')
    review.add_argument('--bundle',type=Path)
    args=parser.parse_args()
    if args.output.exists(): raise FileExistsError('choose fresh output')
    frames=FrameStore(args.store)
    if args.operation=='lookup':
        request=EditionRequest.model_validate_json(args.input.read_bytes());result=export_edition(frames,request,args.output,args.response.read_bytes() if args.response else None,args.open_library)
        print(f'Edition lookup: {result["outcome"]}; edition unaccepted')
    else:
        command=EditionCommand.model_validate_json(args.input.read_bytes());result=EditionStore(frames).apply(command,args.bundle)
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json_text(result)+'\n',encoding='utf-8')
        print(f'Edition review saved at revision {result["revision"]}; no prices inferred')


if __name__=='__main__': main()
