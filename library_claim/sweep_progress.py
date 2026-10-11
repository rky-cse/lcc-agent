"""Read-only live guidance projection; never treats proposals as accepted facts."""
import json
from collections import Counter
from contextlib import closing
from .tracking import digest


def recognition_progress(frames, session, inventory_revision, reference_revision):
    counts=Counter(); hints=[]; readings=[]; uncertain=False; shelves=set()
    with closing(frames._connect()) as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='recognition_jobs'").fetchone()
        rows=db.execute('SELECT state FROM recognition_jobs').fetchall() if exists else []
    for row in rows:
        job=json.loads(row[0]); inputs=job['input']
        if inputs['session_id']!=session:continue
        status=job['status']; request=inputs['request']; kind=inputs.get('kind','reading')
        revision=inputs.get('expected_inventory_revision',request.get('expected_revision'))
        if status=='completed' and (revision!=inventory_revision or inputs['expected_reference_revision']!=reference_revision):status='stale'
        counts[status]+=1;uncertain|=bool(job.get('worker_active')) or status=='running'
        if kind=='detection':shelves.add(request['shelf_id'])
        if status!='completed':continue
        name='reading_result.json' if kind=='reading' else 'detection_result.json'
        path=frames.root/'recognition'/inputs['job_id']/name
        if name not in job['artifacts'] or path.is_symlink() or not path.is_file() or digest(path.read_bytes())!=job['artifacts'][name]:
            raise ValueError('recognition evidence integrity failure')
        result=json.loads(path.read_text(encoding='utf-8'))
        if kind=='reading':
            response=result.get('response') or {}
            if result.get('legibility') in ('partial','unreadable') or response.get('legibility') in ('partial','unreadable') or job.get('result_status')=='partial':
                hints.append('Some saved spine text is partial or unreadable. Slow down and hold this shelf steady; keep books in place.')
            readings.append(dict(job_id=inputs['job_id'],observation_id=request['observation_id'],accepted_identity=False))
        elif result.get('coverage_assertion')=='uncertain' or result.get('unresolved_regions'):
            hints.append('Shelf coverage is uncertain or occluded. Pause and show the whole shelf with overlap before moving on.')
    return dict(counts=dict(counts),worker_uncertain_or_active=uncertain,shelves_observed=sorted(shelves),
        reading_proposals=readings[-20:],capture_hints=list(dict.fromkeys(hints))[:3],
        accepted_identity=False,coverage_verified=False,packet_ready=False)
