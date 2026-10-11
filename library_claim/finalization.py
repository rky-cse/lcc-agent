"""M10 closed-capture barrier, immutable snapshot, portable packet publication."""
import argparse
import io
import json
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import Field, field_validator, model_validator

from .area_store import AreaStore
from .capture_store import FrameStore
from .capture_session import CaptureSessions
from .contents import ContentsStore, ContentsCommand, Token
from .contents_pricing import ContentsPricing
from .guidance import GuidanceStore
from .recognition_jobs import RecognitionQueue
from .tracking import TrackStore
from .valuation import ValuationStore, canonical, sha
from .models import (Contract, PacketPolicy, PacketInput, Sweep, Room, Book, Item, Price,
                     ItemPrice, MeasurementEvidence, ReviewFinding)
from .packet import build_packet, json_text
from .report import render_report
from .measurement import measure
from .planar import MeasurementRequest, inside
from .final_audit import verified_quote, totals_for, audit_packet, spoken_summary


class FinalizationRequest(Contract):
    run_id: Token
    sweep_id: Token
    expected_book_revision: int = Field(ge=0)
    expected_contents_revision: int = Field(ge=0)
    deadline_at: datetime
    book_valuation_runs: list[Token] = Field(max_length=10)
    item_valuation_runs: list[Token] = Field(max_length=10)
    area_run_id: Token | None
    book_measurements: list[MeasurementRequest] = Field(max_length=20)
    aggregation: PacketPolicy
    max_archive_bytes: int = Field(ge=1_000_000,le=128*1024*1024)
    _timezone=field_validator('deadline_at')(classmethod(Sweep.timezone_required.__func__))

    @model_validator(mode='after')
    def scope(self):
        for group in (self.book_valuation_runs,self.item_valuation_runs):
            if len(group)!=len(set(group)):raise ValueError('duplicate valuation run selection')
        if any(m.sweep_id!=self.sweep_id for m in self.book_measurements):raise ValueError('measurement belongs to another sweep')
        return self


class Finalizer:
    def __init__(self, frames, *, clock=None):
        self.frames=frames;self.capture=CaptureSessions(frames);self.books=TrackStore(frames)
        self.contents=ContentsStore(frames);self.values=ValuationStore(frames)
        self.item_values=ContentsPricing(frames);self.areas=AreaStore(frames)
        self.jobs=RecognitionQueue(frames);self.guidance=GuidanceStore(frames)
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.values.clock=lambda:self.clock()
        self.item_values.clock=lambda:self.clock()
        with closing(frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS final_runs (id TEXT PRIMARY KEY,request BLOB NOT NULL,status TEXT NOT NULL,result BLOB,sha TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS final_files (run_id TEXT NOT NULL,path TEXT NOT NULL,sha TEXT NOT NULL,content BLOB NOT NULL,PRIMARY KEY(run_id,path))');db.commit()

    def get(self, run_id, sweep_id=None):
        with closing(self.frames._connect()) as db:
            row=db.execute('SELECT request,status,result,sha FROM final_runs WHERE id=?',(run_id,)).fetchone()
        if row is None:raise KeyError('unknown final packet run')
        request=json.loads(row[0])
        if sweep_id is not None and request['sweep_id']!=sweep_id:raise KeyError('unknown final run in this sweep')
        if row[2] is None:return dict(run_id=run_id,sweep_id=request['sweep_id'],status=row[1],packet_ready=False,deadline_at=request['deadline_at'])
        if sha(row[2])!=row[3]:raise ValueError('final packet hash mismatch')
        packet=json.loads(row[2],parse_float=Decimal)
        audit_packet(packet)
        saved={}
        for path,content,digest in self.files(run_id):
            if sha(content)!=digest:raise ValueError('final artifact hash mismatch')
            saved[path]=content
        if saved.get('claim_packet.json')!=row[2]+b'\n' or saved.get('spoken-summary.txt')!=spoken_summary(packet).encode('utf-8') or saved.get('report.html')!=render_report(packet).encode('utf-8'):
            raise ValueError('packet/report/summary agreement audit failed')
        manifest=json.loads(saved['artifact-manifest.json'])
        if {e['path'] for e in manifest['files']}!=set(saved)-{'artifact-manifest.json'}:raise ValueError('portable manifest file set mismatch')
        for entry in manifest['files']:
            if sha(saved[entry['path']])!=entry['sha256'] or len(saved[entry['path']])!=entry['byte_size']:raise ValueError('portable manifest hash mismatch')
        return dict(run_id=run_id,sweep_id=request['sweep_id'],status='published',packet_ready=True,result_sha256=row[3],packet=packet)

    def files(self, run_id):
        with closing(self.frames._connect()) as db:
            rows=db.execute('SELECT path,content,sha FROM final_files WHERE run_id=? ORDER BY path',(run_id,)).fetchall()
        for path,content,digest in rows:
            relative=Path(path)
            if relative.is_absolute() or relative.drive or '..' in relative.parts or '\\' in path:raise ValueError('unsafe final artifact path')
            if sha(content)!=digest:raise ValueError('final artifact hash mismatch')
        return rows

    def archive(self, run_id, sweep_id=None):
        result=self.get(run_id,sweep_id)
        if not result['packet_ready']:raise ValueError('final packet has not been published')
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for path,content,digest in self.files(run_id):
                entry=zipfile.ZipInfo(path,date_time=(1980,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(entry,content)
        return stream.getvalue()

    def run(self, request):
        request=FinalizationRequest.model_validate(request.model_dump());encoded=canonical(request.model_dump(mode='json'))
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT request,status FROM final_runs WHERE id=?',(request.run_id,)).fetchone()
            if old and old[0]!=encoded:raise ValueError('final run ID reused with different payload')
            if old and old[1] in ('frozen','published'):
                db.commit()
                if old[1]=='frozen':self.publish(request)
                return self.get(request.run_id,request.sweep_id)
            capture=self.capture.snapshot(request.sweep_id)
            if capture['status']!='closed':raise ValueError('end capture explicitly before finalizing')
            ended=datetime.fromisoformat(capture['ended_at'])
            if request.deadline_at<ended:raise ValueError('deadline cannot precede capture end')
            books=self.books.snapshot(request.sweep_id);contents=self.contents.snapshot(request.sweep_id)
            if books['revision']!=request.expected_book_revision or contents['revision']!=request.expected_contents_revision:raise ValueError('stale finalization inventory revision')
            jobs=self.jobs.list(request.sweep_id);now=self.clock()
            pending=[j for j in jobs if j['status'] in ('queued','running') or j.get('worker_active',False)]
            book_runs=[self.values.get(key,request.sweep_id) for key in request.book_valuation_runs]
            item_runs=[self.item_values.get(key,request.sweep_id) for key in request.item_valuation_runs]
            pending+= [r for r in book_runs+item_runs if r['status']=='running']
            if pending and now<request.deadline_at:
                if not old:db.execute('INSERT INTO final_runs VALUES (?,?,?,NULL,NULL)',(request.run_id,encoded,'waiting_for_drain'))
                db.commit();return self.get(request.run_id,request.sweep_id)
            files={};size=0
            def add(path,raw):
                nonlocal size
                if path in files:
                    if files[path]!=raw:raise ValueError('conflicting final artifact')
                    return
                size+=len(raw)
                if size>request.max_archive_bytes:raise ValueError('frozen evidence exceeds entered archive byte limit')
                files[path]=raw
            for f in capture['frames']:add(f['path'],self.frames.read(f['id']))
            try:guide=self.guidance.snapshot(request.sweep_id)
            except KeyError:guide=None
            for digest in books.get('identity_evidence',[]):
                row=db.execute('SELECT content FROM identity_artifacts WHERE sha256=?',(digest,)).fetchone()
                if row is None or sha(row[0])!=digest:raise ValueError('identity evidence integrity failed')
                add('artifacts/identity/'+digest+'.json',row[0])
            for row in contents['rows']:
                for proof in row['dimension_proofs'].values():add('artifacts/contents/'+proof['artifact_sha256']+'.json',self.contents.artifact(proof['artifact_sha256']))
            for event in contents['events']:
                digest=event['command'].get('proposal_sha256')
                if digest:add('artifacts/contents/'+digest+'.json',self.contents.artifact(digest))
            unreviewed_contents=[]
            reviewed_proposals={(e['command'].get('proposal_sha256'),e['command'].get('proposal_index')) for e in contents['events']}
            for digest,raw in db.execute('SELECT sha,content FROM contents_artifacts'):
                artifact=json.loads(raw);scope=artifact.get('request',artifact.get('command',{})).get('sweep_id')
                if scope!=request.sweep_id:continue
                if sha(raw)!=digest:raise ValueError('contents artifact integrity failed')
                add('artifacts/contents/'+digest+'.json',raw)
                for proposal in artifact.get('proposals',[]):
                    if (digest,proposal['proposal_index']) not in reviewed_proposals:
                        unreviewed_contents.append(dict(ref_id='contents-proposal-'+digest[:12]+'-'+str(proposal['proposal_index']),reason='Archived non-book detection proposal has no reviewed physical acceptance; historical/stale proposals are not counted automatically'))
            for job in jobs:
                for name,digest in job.get('artifacts',{}).items():
                    if Path(name).name!=name:raise ValueError('unsafe recognition artifact name')
                    path=self.frames.root/'recognition'/job['input']['job_id']/name
                    raw=path.read_bytes()
                    if sha(raw)!=digest:raise ValueError('recognition artifact hash mismatch')
                    add('artifacts/recognition/'+job['input']['job_id']+'/'+name,raw)
            for run,provider in [(r,self.values) for r in book_runs]+[(r,self.item_values) for r in item_runs]:
                for digest in run.get('evidence_sha256',[]):add('sources/'+digest+'.txt',provider.evidence(digest))
            area=self.areas.get(request.area_run_id,request.sweep_id) if request.area_run_id else None
            if area:
                model=self.areas.model_path(self.areas_request(area))
                for name in ('request.json','reconstruction_result.json','frames.json'):add('geometry/'+name,(model/name).read_bytes())
                for frame in area['frames']:add('geometry/images/'+Path(frame['path']).name,self.frames.read(frame['id']))
                model_result=json.loads((model/'reconstruction_result.json').read_text(encoding='utf-8'))
                component=str(model_result['backend_summary']['models'][0]['model_id'])
                required={f'sparse/{component}/{name}.bin' for name in ('cameras','images','points3D','frames','rigs')}
                for entry in area['reconstruction_artifacts']:
                    if entry['path'] not in required:continue
                    target=(model/entry['path']).resolve()
                    if not target.is_relative_to(model):raise ValueError('unsafe native geometry path')
                    raw=target.read_bytes()
                    if sha(raw)!=entry['sha256']:raise ValueError('native geometry hash mismatch')
                    add('geometry/'+entry['path'],raw)
            measurements=[];measured_ids=set()
            for m in request.book_measurements:
                for spine in m.spines:
                    if spine.id in measured_ids:raise ValueError('duplicate physical book measurement')
                    measured_ids.add(spine.id)
                    observations=[o for o in books['observations'] if o['track_id']==spine.id and o['frame_ref']==spine.frame_ref]
                    if not any(all(inside(p,o['polygon_px']) for p in spine.corners_px) for o in observations):raise ValueError('book measurement is outside reviewed physical observation')
                proof=measure(self.frames,m);measurements.extend(proof['measurements'])
                add('artifacts/book-measurement-'+proof['input_sha256']+'.json',canonical(dict(request=m.model_dump(),result=proof)))
            # Recompute M08 geometry rather than accepting only stored dimensions.
            for row in contents['rows']:
                proofs={p['artifact_sha256'] for p in row['dimension_proofs'].values()}
                for digest in proofs:
                    artifact=json.loads(self.contents.artifact(digest));command=ContentsCommand.model_validate(artifact['command'])
                    result=measure(self.frames,command.measurement)['results'][0]
                    for axis,field in [(command.height_axis,'spine_height_cm'),(command.width_axis,'spine_thickness_cm')]:
                        proof=row['dimension_proofs'].get(axis)
                        if proof and proof['artifact_sha256']==digest:
                            if result['status']!='measured' or Decimal(str(result[field]))!=Decimal(str(proof['value_cm'])):raise ValueError('item dimension differs from recomputed geometry')
                            measurements.append(dict(id='item-'+digest[:20]+'-'+axis,ref_id=row['item']['id'],field='dimensions_cm.'+axis,value=proof['value_cm'],unit='cm',frame_refs=[proof['frame_ref']],scale_method='verified_planar_face',derivation='Recomputed archived M08 measurement '+digest))
            frozen=dict(request=request.model_dump(mode='json'),frozen_at=now.isoformat(),capture=capture,books=books,contents=contents,jobs=jobs,
                guidance=guide,book_runs=book_runs,item_runs=item_runs,area=area,measurements=measurements,deadline_partial=bool(pending),unreviewed_contents=unreviewed_contents)
            add('frozen-inputs.json',canonical(frozen))
            if not old:db.execute('INSERT INTO final_runs VALUES (?,?,?,NULL,NULL)',(request.run_id,encoded,'frozen'))
            else:db.execute('UPDATE final_runs SET status=? WHERE id=?',('frozen',request.run_id))
            for path,raw in files.items():db.execute('INSERT INTO final_files VALUES (?,?,?,?)',(request.run_id,path,sha(raw),raw))
            db.commit()
        self.publish(request)
        return self.get(request.run_id,request.sweep_id)

    @staticmethod
    def areas_request(area):
        from .areas import AreaRequest
        return AreaRequest.model_validate(area['request'])

    def publish(self, request):
        files={path:raw for path,raw,digest in self.files(request.run_id)}
        frozen=json.loads(files['frozen-inputs.json'],parse_float=Decimal)
        packet=self.build(frozen,files,request)
        encoded=canonical(packet)
        manifest=[dict(path=p,sha256=sha(raw),byte_size=len(raw)) for p,raw in sorted(files.items())]
        manifest.append(dict(path='claim_packet.json',sha256=sha(encoded+b'\n'),byte_size=len(encoded)+1))
        report=render_report(json.loads(encoded,parse_float=Decimal)).encode('utf-8')
        summary=spoken_summary(json.loads(encoded,parse_float=Decimal)).encode('utf-8')
        outputs={'claim_packet.json':encoded+b'\n','report.html':report,'spoken-summary.txt':summary}
        manifest.extend(dict(path=p,sha256=sha(raw),byte_size=len(raw)) for p,raw in outputs.items() if p!='claim_packet.json')
        outputs['artifact-manifest.json']=canonical(dict(files=manifest,manifest_self_hash_excluded=True))
        if sum(len(v) for v in files.values())+sum(len(v) for v in outputs.values())>request.max_archive_bytes:raise ValueError('packet exceeds entered archive byte limit')
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status FROM final_runs WHERE id=?',(request.run_id,)).fetchone()
            if row[0]=='published':return
            for path,raw in outputs.items():db.execute('INSERT INTO final_files VALUES (?,?,?,?)',(request.run_id,path,sha(raw),raw))
            db.execute('UPDATE final_runs SET status=?,result=?,sha=? WHERE id=?',('published',encoded,sha(encoded),request.run_id));db.commit()

    def build(self, frozen, files, request):
        capture=frozen['capture'];books=[Book.model_validate(b) for b in frozen['books']['books']]
        items=[Item.model_validate(r['item']) for r in frozen['contents']['rows'] if r['billable']]
        review=[ReviewFinding(ref_id='sweep',reason='Physical inventory/room coverage and measurement accuracy are unverified')]
        review.extend(ReviewFinding.model_validate(r) for r in frozen.get('unreviewed_contents',[]))
        for row in frozen['books']['review_queue']:review.append(ReviewFinding(ref_id=row.get('ref_id',row.get('observation_id','sweep')),reason=row['reason']))
        if capture['capture_gaps']:review.append(ReviewFinding(ref_id='sweep',reason='Capture transport gaps: '+str(capture['capture_gaps'])))
        if frozen['deadline_partial']:review.append(ReviewFinding(ref_id='sweep',reason='Finalization deadline reached with pending recognition or selected valuation; late results excluded from this archive'))
        for job in frozen['jobs']:
            if job['status'] not in ('completed',):review.append(ReviewFinding(ref_id=job['input']['job_id'],reason='Recognition job '+job['status']+'; output not accepted into inventory automatically'))
        guide=frozen['guidance']
        if guide:
            for c in guide.get('corrections',[]):
                if c['status'] not in ('applied','rejected','cancelled'):review.append(ReviewFinding(ref_id=c.get('id','sweep'),reason='Pending reviewed correction: '+c['status']))
            for r in guide.get('requests',[]):
                if r['status'] in ('awaiting_answer','awaiting_evidence'):review.append(ReviewFinding(ref_id=r.get('id','sweep'),reason='Unanswered evidence request'))
        area=frozen['area'];room=Room()
        measurements=[MeasurementEvidence.model_validate(m) for m in frozen['measurements']]
        if area and not area['stale'] and area['status']!='unavailable':
            room=Room.model_validate(area['room']);measurements.extend(MeasurementEvidence.model_validate(m) for m in area['measurements'])
        elif area:review.append(ReviewFinding(ref_id='room',reason='Selected geometry is stale or unavailable; dimensions excluded'))
        for b in books:
            for field in ('spine_height_cm','spine_thickness_cm'):
                proof=next((m for m in measurements if m.ref_id==b.id and m.field==field),None)
                if proof:setattr(b,field,proof.value)
        frames=[self.frames_type(f) for f in capture['frames']]
        accepted_ids={b.id for b in books}|{i.id for i in items}|{'room'}
        measurements=[m for m in measurements if m.ref_id in accepted_ids]
        draft=PacketInput(sweep=Sweep(id=request.sweep_id,captured_at=capture['started_at'],country=capture['country'],currency=capture['currency']),room=room,
            books=books,items=items,frames=frames,measurements=measurements,review_queue=review,synthetic=any(f['synthetic'] for f in capture['frames']))
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for frame in frames:
                target=root/frame.path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(files[frame.path])
            packet=build_packet(draft,root,request.aggregation)
        for item in packet['items']:
            original=next(r for r in frozen['contents']['rows'] if r['item']['id']==item['id'])
            if original.get('art') and original['art']['kind']=='print' and original['item']['status']!='needs_appraisal':
                item['status']='';item['artwork_kind']='print'
                for finding in packet['review_queue']:
                    if finding['ref_id']==item['id'] and finding['reason']=='replacement_cost: needs human appraisal; automatic valuation excluded':finding['reason']='replacement_cost: replacement price unavailable'
        packet['ownership_exclusions'].extend(r['item'] for r in frozen['contents']['rows'] if not r['item']['owned'])
        self.price(packet,frozen,files,request)
        packet['totals']=totals_for(packet)
        packet['coverage'].update(physical_coverage_verified=False,inventory_complete=False,recognition_drained=not any(j['status'] in ('queued','running') or j.get('worker_active',False) for j in frozen['jobs']),
            books_replacement_priced=sum(b['replacement_cost']['amount'] is not None for b in packet['books']),books_used_priced=sum(b['used_value']['amount'] is not None for b in packet['books']),
            items_priced=sum(i['replacement_cost']['low'] is not None for i in packet['items']))
        packet['packet_status']='partial'
        packet['finalization']=dict(run_id=request.run_id,frozen_at=frozen['frozen_at'],deadline_partial=frozen['deadline_partial'],
            book_revision=frozen['books']['revision'],contents_revision=frozen['contents']['revision'],immutable=True,artifact_manifest='artifact-manifest.json')
        packet['group_exclusions']=[r['item'] for r in frozen['contents']['rows'] if r['item']['owned'] and not r['billable']]
        if area:
            packet['room_geometry']=area
            if not area['stale'] and area.get('geometry'):
                for field,units in area['geometry']['area_units'].items():
                    if packet['room'][field] is not None:packet['room'][field.replace('_m2','_ft2')]=units['ft2']
        packet['audit']=audit_packet(packet)
        return packet

    @staticmethod
    def frames_type(record):
        from .models import FrameEvidence
        return FrameEvidence.model_validate({k:record[k] for k in ('id','path','sha256','captured_at')})

    def price(self,packet,frozen,files,request):
        now=datetime.fromisoformat(frozen['frozen_at']);quotes=[];seen_books=set();seen_items=set()
        source=lambda digest:files['sources/'+digest+'.txt']
        def flag(ref,reason):
            value=dict(ref_id=ref,reason=reason)
            if value not in packet['review_queue']:packet['review_queue'].append(value)
        def clear(ref,component):packet['review_queue'][:]=[r for r in packet['review_queue'] if not (r['ref_id']==ref and r['reason'].startswith(component+':'))]
        def record(q):
            digest=sha(canonical(q));key='final-quote-'+digest[:32]
            if not any(row['id']==key for row in quotes):quotes.append(dict(id=key,path='sources/'+q['evidence_sha256']+'.txt',sha256=q['evidence_sha256'],quote=q))
            return key
        for run in frozen['book_runs']:
            if not run.get('usable_for_current_inventory',False):flag('sweep','Selected book valuation is stale, expired or unfinished: '+run['run_id']);continue
            markets=[m for m in run['markets'] if (m['market']['country'],m['market']['currency'])==(packet['sweep']['country'],packet['sweep']['currency'])]
            if len(markets)!=1:flag('sweep','Book valuation has no unique captured locale');continue
            market=markets[0]['market']
            if market['decimal_places']!=request.aggregation.currency_decimal_places:raise ValueError('valuation decimal places differ from packet policy')
            for row in markets[0]['rows']:
                book=next((b for b in packet['books'] if b['id']==row['track_id']),None)
                if not book:continue
                if book['id'] in seen_books:raise ValueError('overlapping primary book valuation runs')
                seen_books.add(book['id'])
                original=next(b for b in frozen['books']['books'] if b['id']==book['id'])
                if canonical(row['identity'])!=canonical(original):raise ValueError('valuation identity differs from frozen book')
                if row['status']=='needs_appraisal':book['status']='needs_appraisal'
                if book['status']=='needs_appraisal':flag(book['id'],'Authentication/appraisal required');continue
                for component,field in [('replacement','replacement_cost'),('used','used_value')]:
                    q=row[component]
                    if q is None:continue
                    try:amount=verified_quote(q,run,original,market,component,source,now)
                    except (ValueError,KeyError,TypeError,ArithmeticError) as error:flag(book['id'],field+': independent source audit failed');continue
                    book[field]=Price(amount=amount,source=q['source'],url=q['url'],retrieved_at=q['retrieved_at'],converted=q['converted'],condition_assumed=q['condition'],quote_ref=record(q),currency=q['target_currency']).model_dump()
                    clear(book['id'],field)
        for run in frozen['item_runs']:
            if not run.get('usable_for_current_inventory',False):flag('sweep','Selected item valuation is stale, expired or unfinished: '+run['run_id']);continue
            market=run['market']
            if (market['country'],market['currency'])!=(packet['sweep']['country'],packet['sweep']['currency']):flag('sweep','Item valuation locale differs');continue
            if market['decimal_places']!=request.aggregation.currency_decimal_places:raise ValueError('item decimal places differ from packet policy')
            for row in run['rows']:
                item=next((i for i in packet['items'] if i['id']==row['item']['id']),None)
                if not item:continue
                if item['id'] in seen_items:raise ValueError('overlapping item valuation runs')
                seen_items.add(item['id']);original=next(r for r in frozen['contents']['rows'] if r['item']['id']==item['id'])
                if canonical(row['source'])!=canonical(original):raise ValueError('valuation physical item differs from frozen ledger')
                if original['item']['status']=='needs_appraisal' or row['item']['status']=='needs_appraisal':item['status']='needs_appraisal';continue
                if not row['quotes']:continue
                try:
                    amounts=[verified_quote(q,run,original,market,'replacement',source,now,item=True) for q in row['quotes']]
                    if row['quote_basis']=='exact_model':
                        if len(row['quotes'])!=1 or row['quotes'][0]['match_basis']!='exact_model':raise ValueError('exact item quote basis mismatch')
                    elif row['quote_basis']=='reviewed_comparable_min_max':
                        from urllib.parse import urlsplit
                        policy=run['request']['policy'];selected=row['quotes']
                        if any(q['match_basis']!='reviewed_comparable' for q in selected) or len(selected)<policy['min_comparables'] or len({urlsplit(q['url']).hostname.lower() for q in selected})<policy['min_distinct_domains']:
                            raise ValueError('comparable range lacks policy coverage')
                        identities={(q['evidence_sha256'],str(q['product'].get('@id',q['product'].get('sku',q['product'].get('url'))))) for q in selected}
                        if len(identities)!=len(selected):raise ValueError('duplicate physical comparable')
                    else:raise ValueError('unknown quote aggregation basis')
                    p=row['item']['replacement_cost']
                    if min(amounts)!=Decimal(str(p['low'])) or max(amounts)!=Decimal(str(p['high'])):raise ValueError('item bounds differ from independent quote range')
                except (ValueError,KeyError,TypeError,ArithmeticError):flag(item['id'],'replacement_cost: independent comparable audit failed');continue
                refs=[record(q) for q in row['quotes']];q=row['quotes'][0]
                item['replacement_cost']=ItemPrice(low=min(amounts),high=max(amounts),source=q['source'],url=q['url'],retrieved_at=q['retrieved_at'],quote_refs=refs,condition_assumed='NewCondition',currency=market['currency']).model_dump()
                item['status']='priced' if min(amounts)==max(amounts) else 'range';clear(item['id'],'replacement_cost')
        packet['quote_manifest']=quotes


def main():
    parser=argparse.ArgumentParser(description='M10 immutable final packet and portable evidence archive')
    parser.add_argument('--store',type=Path,required=True);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('choose a fresh archive output')
    finalizer=Finalizer(FrameStore(args.store));request=FinalizationRequest.model_validate_json(args.input.read_text(encoding='utf-8'))
    result=finalizer.run(request)
    if result['packet_ready']:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_bytes(finalizer.archive(request.run_id,request.sweep_id))
    print('Finalization: '+result['status'])


if __name__=='__main__':main()
