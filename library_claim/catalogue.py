"""M05b1: evidence-bound Open Library work candidates, never edition inference."""
import argparse
import json
import re
import socket
import time
import unicodedata
from contextlib import closing
from datetime import datetime,timezone
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,build_opener

from pydantic import BaseModel,ConfigDict,Field,model_validator

from .capture_store import FrameStore
from .models import Contract,StageError,StageResult
from .packet import json_text
from .spine_reading import ReadingRequest,ReadingResponse,prepare_crop,text_evidence
from .tracking import TrackStore,digest
from .vision_provider import NoRedirect


class CatalogueRequest(Contract):
    reading_result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    title_span_ids: Annotated[list[str],Field(max_length=8)]
    author_span_ids: Annotated[list[str],Field(max_length=8)]
    limit: int = Field(ge=1,le=10)

    @model_validator(mode="after")
    def unique(self):
        ids=self.title_span_ids+self.author_span_ids
        if len(ids)!=len(set(ids)):
            raise ValueError("text evidence cannot be selected twice")
        return self


class WorkDoc(BaseModel):
    # Catalogue fields may evolve; preserve raw response and ignore unrelated
    # fields here. Required identity fields and evaluated values stay bounded.
    model_config=ConfigDict(extra="ignore")
    key: str = Field(pattern=r"^(?:/works/)?OL[0-9]+W$")
    title: str = Field(min_length=1,max_length=1000)
    author_name: Annotated[list[Annotated[str,Field(max_length=300)]],Field(max_length=32)] = []
    edition_count: int | None = Field(default=None,ge=0)


def normalize(text):
    value=unicodedata.normalize("NFKC",text).casefold()
    return " ".join("".join(" " if unicodedata.category(c).startswith("P") else c for c in value).split())


def load_reading(store,directory,request):
    root=Path(directory)
    raw=(root/"reading_result.json").read_bytes()
    if len(raw)>2*1024*1024 or digest(raw)!=request.reading_result_sha256:
        raise ValueError("reading result size/hash mismatch")
    result=json.loads(raw)
    reading=ReadingRequest.model_validate(result["request"])
    frame,original,crop,metadata=prepare_crop(store,reading)
    if json.loads(json_text(metadata))!=result["crop"] or (root/"crop.png").read_bytes()!=crop:
        raise ValueError("reading crop differs from immutable observation")
    if (root/("original"+Path(frame.path).suffix)).read_bytes()!=original:
        raise ValueError("reading original differs from FrameStore")
    stage=StageResult.model_validate(result["stage_result"])
    if (stage.stage!="spine_visible_text" or stage.sweep_id!=reading.sweep_id
            or stage.input_revision!=reading.expected_revision or stage.evidence_refs!=[frame.id]):
        raise ValueError("reading stage identity mismatch")
    expected_job=digest(json_text(dict(request=reading.model_dump(),crop_sha256=metadata["crop_sha256"],provider=result["provider"])).encode())
    if stage.job_id!=expected_job:
        raise ValueError("reading job fingerprint mismatch")
    response=ReadingResponse.model_validate(result["response"]) if result["response"] is not None else None
    if json.loads(json_text(text_evidence(reading,metadata,response,result["provider"])))!=result["text_evidence"]:
        raise ValueError("reading spans differ from validated response")
    if response is None and (stage.status!="unavailable" or not stage.errors):
        raise ValueError("invalid unavailable reading")
    if response is not None and stage.status != ("success" if response.legibility=="readable" else "partial"):
        raise ValueError("reading status differs from legibility")
    spans={s["id"]:s for s in result["text_evidence"]}
    for ids,role in [(request.title_span_ids,"title"),(request.author_span_ids,"author")]:
        if any(i not in spans or spans[i]["tentative_role"]!=role for i in ids):
            raise ValueError("selected span is missing or has a different tentative role")
    title=" ".join(spans[i]["text"] for i in request.title_span_ids)
    author=" ".join(spans[i]["text"] for i in request.author_span_ids)
    if len(title)>500 or len(author)>500:
        raise ValueError("catalogue text selection exceeds limit")
    # Freeze the validated bytes before any network wait; source files could
    # otherwise change between validation and copying into the review bundle.
    evidence={"reading_result.json":raw,"crop.png":crop,"original"+Path(frame.path).suffix:original}
    return result,reading,title,author,evidence


def query_url(title,author,limit):
    # Solr quoted literals: escape syntax inside extracted text; titles such as
    # "A OR B" must not become operator-driven searches.
    def literal(value): return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
    query='title:'+literal(title)
    if author: query+=' AND author:'+literal(author)
    return "https://openlibrary.org/search.json?"+urlencode(dict(q=query,fields="key,title,author_name,edition_count",limit=limit,offset=0))


def parse_search(raw,limit):
    value=json.loads(raw)
    if not isinstance(value,dict): raise ValueError("catalogue response must be an object")
    docs=value.get("docs")
    count=value.get("numFound",value.get("num_found"))
    if (not isinstance(docs,list) or len(docs)>limit or not isinstance(count,int) or isinstance(count,bool)
            or count<0 or count<len(docs) or value.get("start",0)!=0):
        raise ValueError("invalid bounded catalogue search result")
    rows=[WorkDoc.model_validate(d).model_dump() for d in docs]
    keys=[r["key"].removeprefix('/works/') for r in rows]
    if len(keys)!=len(set(keys)):
        raise ValueError("duplicate catalogue work records")
    return rows,count,value.get("numFoundExact") is True and count==len(rows)


class CatalogueClient:
    """Successful responses cached 24h; persistent per-store reservation/cooldown."""
    def __init__(self,store):
        self.store=store
        with closing(store._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS catalogue_cache (key TEXT PRIMARY KEY, retrieved REAL, raw BLOB)')
            db.execute('CREATE TABLE IF NOT EXISTS catalogue_gate (id INTEGER PRIMARY KEY, next_allowed REAL)')
            db.execute('INSERT OR IGNORE INTO catalogue_gate VALUES (1,0)');db.commit()

    def fetch(self,url,limit):
        if not url.startswith("https://openlibrary.org/search.json?"):
            raise ValueError("unsupported catalogue endpoint")
        return self._fetch(url,lambda raw:parse_search(raw,limit))

    def _fetch(self,url,validator):
        # Fixed-endpoint adapters share the persistent service-wide store gate.
        key=digest(url.encode());now=time.time()
        with closing(self.store._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT retrieved,raw FROM catalogue_cache WHERE key=?',(key,)).fetchone()
            if row and 0<=now-row[0]<86400:
                validator(row[1])
                return row[1],None,dict(requests=0,cache_hit=True,retrieved_at=datetime.fromtimestamp(row[0],timezone.utc).isoformat())
            allowed=db.execute('SELECT next_allowed FROM catalogue_gate WHERE id=1').fetchone()[0]
            if allowed>now:
                return None,dict(code="catalogue_cooldown",reason="Local catalogue request cooldown; no request sent",retryable=True),dict(requests=0,retry_after_seconds=allowed-now,cache_hit=False)
            db.execute('UPDATE catalogue_gate SET next_allowed=? WHERE id=1',(now+1.2,));db.commit()
        started=time.monotonic()
        try:
            call=Request(url,headers={"User-Agent":"LibraryContentsClaim/0.1 (local review prototype)","Accept":"application/json"})
            with build_opener(NoRedirect()).open(call,timeout=20) as response:
                raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024: raise ValueError("catalogue response too large")
            validator(raw)
            retrieved=time.time()
            with closing(self.store._connect()) as db:
                db.execute('INSERT INTO catalogue_cache VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET retrieved=excluded.retrieved,raw=excluded.raw',(key,retrieved,raw));db.commit()
            return raw,None,dict(requests=1,cache_hit=False,elapsed_seconds=time.monotonic()-started,retrieved_at=datetime.fromtimestamp(retrieved,timezone.utc).isoformat())
        except HTTPError as error:
            retry=error.code in {429,500,502,503,504}
            if error.code==429:
                value=error.headers.get('Retry-After','') if error.headers else ''
                seconds=min(3600,max(60,int(value))) if value.isdigit() else 60
                with closing(self.store._connect()) as db:
                    db.execute('UPDATE catalogue_gate SET next_allowed=MAX(next_allowed,?) WHERE id=1',(time.time()+seconds,));db.commit()
            return None,dict(code="catalogue_http_error",reason=f"Open Library HTTP {error.code}; no automatic retry",retryable=retry),dict(requests=1,cache_hit=False,elapsed_seconds=time.monotonic()-started)
        except (URLError,socket.timeout,TimeoutError):
            return None,dict(code="catalogue_unavailable",reason="Open Library network/timeout failure; no retry",retryable=True),dict(requests=1,cache_hit=False,elapsed_seconds=time.monotonic()-started)
        except (ValueError,TypeError,UnicodeError):
            return None,dict(code="catalogue_invalid_response",reason="Catalogue response failed bounded work schema",retryable=False),dict(requests=1,cache_hit=False,elapsed_seconds=time.monotonic()-started)


def evaluate(rows,title,author,reading):
    candidates=[]
    for row in rows:
        reasons=[]
        title_equal=normalize(row["title"])==normalize(title)
        author_equal=bool(author) and any(normalize(a)==normalize(author) for a in row["author_name"])
        if not title_equal: reasons.append("title differs from selected literal text")
        if author and not author_equal: reasons.append("author differs or catalogue author is missing")
        if not author: reasons.append("no visible author selected")
        if reading["response"]["legibility"]!="readable": reasons.append("partial/unreadable transcription needs review")
        # Explicit volume wording can contradict a work even with similar title.
        visible=[s["text"] for s in reading["text_evidence"] if s["tentative_role"]=="volume"]
        for text in visible:
            a=re.search(r'\b(?:vol(?:ume)?|book)\.?\s*(\d+)\b',text,re.I)
            b=re.search(r'\b(?:vol(?:ume)?|book)\.?\s*(\d+)\b',row["title"],re.I)
            if a and b and int(a[1])!=int(b[1]): reasons.append("volume number contradiction")
            elif not a or not b: reasons.append("visible volume not established by work record")
        supported=title_equal and author_equal and not reasons
        key='/works/'+row["key"].removeprefix('/works/')
        candidates.append(dict(work_id=key,url="https://openlibrary.org"+key,title=row["title"],authors=row["author_name"],
            catalogue_edition_count=row["edition_count"],title_exact=title_equal,author_exact=author_equal,
            disposition="supported_candidate" if supported else "contradicted" if (not title_equal or (author and row["author_name"] and not author_equal) or "volume number contradiction" in reasons) else "needs_review",
            reasons=reasons+["Visible transcription is unverified; candidate is not accepted identity"],accepted_edition_id=None,isbn=None))
    return candidates


def export_catalogue(store,request,reading_directory,output,response_bytes=None,live=False):
    output=Path(output)
    if output.exists(): raise FileExistsError("choose a fresh catalogue output directory")
    if live and response_bytes is not None: raise ValueError("live lookup cannot use replay data")
    request=CatalogueRequest.model_validate(request.model_dump());started=datetime.now(timezone.utc)
    reading,reading_request,title,author,evidence=load_reading(store,reading_directory,request)
    failure=usage=None;rows=[];count=None;complete=False;raw=None;url=None
    if not title.strip() or reading["response"] is None or reading["response"]["legibility"]=="unreadable":
        failure=dict(code="no_visible_title",reason="No selected visible title; catalogue was not queried",retryable=False)
        usage=dict(requests=0,cache_hit=False)
    else:
        url=query_url(title,author,request.limit)
        if live: raw,failure,usage=CatalogueClient(store).fetch(url,request.limit)
        else:
            if response_bytes is None: raise ValueError("saved catalogue response required")
            raw=response_bytes;usage=dict(requests=0,cache_hit=False,source="offline_replay")
        if raw is not None:
            if len(raw)>2*1024*1024: raise ValueError("replay response too large")
            rows,count,complete=parse_search(raw,request.limit)
    if TrackStore(store).snapshot(reading_request.sweep_id)["revision"]!=reading_request.expected_revision:
        raise ValueError("inventory changed during catalogue lookup")
    candidates=evaluate(rows,title,author,reading) if rows else []
    supported=[c for c in candidates if c["disposition"]=="supported_candidate"]
    outcome="unavailable" if failure else "no_match" if count==0 else "ambiguous" if len(supported)>1 else "supported_candidate" if len(supported)==1 else "needs_review"
    job=digest(json_text(dict(request=request.model_dump(),query_url=url)).encode())
    stage=StageResult(sweep_id=reading_request.sweep_id,job_id=job,input_revision=reading_request.expected_revision,stage="catalogue_work_candidates",
        status="unavailable" if failure else "partial",started_at=started,finished_at=datetime.now(timezone.utc),evidence_refs=[reading["crop"]["frame_ref"]],
        warnings=["Catalogue candidates are not accepted work/edition identities; no calibrated identification confidence."],
        errors=[StageError(code=failure["code"],reason=failure["reason"],retryable=failure["retryable"],ref_id=reading_request.observation_id,field="catalogue")] if failure else [])
    result=dict(schema_version="1.0",request=request.model_dump(mode="json"),stage_result=stage.model_dump(mode="json"),
        synthetic=reading["crop"]["synthetic"],source="open_library" if live else "offline_replay",query_url=url,
        selected_title=title,selected_author=author,reading_source_sha256=request.reading_result_sha256,
        catalogue_response_sha256=digest(raw) if raw is not None else None,usage=usage,outcome=outcome,candidates=candidates,
        search_result_count=count,returned_count=len(candidates),search_complete=complete,accepted_work_id=None,accepted_edition_id=None,
        calibrated_confidence=None,inventory_mutated=False,edition_status="unresolved",requires_review=True)
    output.mkdir(parents=True)
    (output/"catalogue_result.json").write_text(json_text(result)+'\n',encoding='utf-8')
    for name,data in evidence.items():
        (output/name).write_bytes(data)
    if raw is not None: (output/"catalogue_response.json").write_bytes(raw)
    html='<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'"><title>Catalogue candidates</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:20px;background:#f2f6fa}td,th{padding:12px;border:1px solid #cad6e1}table{border-collapse:collapse}img{max-height:450px;max-width:100%}</style>'
    html+=f'<h1>Catalogue candidate review</h1><p>Outcome: {outcome}. Synthetic: {result["synthetic"]}. Work and edition identity remain unknown.</p><p>Selected literal text: {escape(title)} / {escape(author)}</p><img src="crop.png" alt="Saved spine crop"><table><tr><th>Work candidate</th><th>Author</th><th>Disposition</th><th>Reasons</th></tr>'
    for c in candidates:
        html+=f'<tr><td><a href="{escape(c["url"],quote=True)}">{escape(c["title"])}</a></td><td>{escape(", ".join(c["authors"]))}</td><td>{c["disposition"]}</td><td>{escape("; ".join(c["reasons"]))}</td></tr>'
    html+=f'</table><p>Returned candidates: {len(candidates)}; catalogue result count: {count}; complete search: {complete}.</p>'
    if failure: html+=f'<p>{escape(failure["reason"])}</p>'
    html+='<p>No ISBN, edition, format, market price or identity was accepted.</p><a href="catalogue_result.json">Open evidence JSON</a> | <a href="reading_result.json">Original reading evidence</a>'
    (output/"report.html").write_text(html,encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description='M05b1 evidence-bound catalogue candidate lookup')
    for name in ['store','input','reading','output']: parser.add_argument('--'+name,type=Path,required=True)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--response',type=Path);mode.add_argument('--open-library',action='store_true')
    args=parser.parse_args();request=CatalogueRequest.model_validate_json(args.input.read_text(encoding='utf-8'))
    result=export_catalogue(FrameStore(args.store),request,args.reading,args.output,
        response_bytes=args.response.read_bytes() if args.response else None,live=args.open_library)
    print(f'Catalogue: {result["outcome"]}; {result["returned_count"]} candidates; accepted identities unknown')


if __name__=='__main__': main()
