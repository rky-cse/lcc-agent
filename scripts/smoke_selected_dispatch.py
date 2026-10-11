"""Exact-ID recognition dispatch in independent CLI processes; synthetic replay only."""
import argparse,json,subprocess,sys
from pathlib import Path
from library_claim.capture_store import FrameStore
from library_claim.guidance import GuidanceStore
from library_claim.recognition_jobs import ReadingJob,DetectionJob
from library_claim.spine_reading import ReadingRequest
from library_claim.spine_detection import DetectionRequest
from library_claim.tracking import TrackStore
from library_claim.packet import json_text


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    root=parser.parse_args().output.resolve()
    if root.exists():raise FileExistsError('choose a fresh smoke directory')
    root.mkdir(parents=True)
    subprocess.run([sys.executable,'-B','-m','scripts.smoke_guidance','--output',str(root/'setup')],check=True)
    store=FrameStore(root/'setup'/'store');session='e'*32
    ledger=TrackStore(store);before=ledger.snapshot(session);guide=GuidanceStore(store).snapshot(session)
    obs=before['observations'][0];frame=store.get(obs['frame_ref'])
    reading=ReadingJob(job_id='first-reading',session_id=session,expected_reference_revision=guide['reference_revision'],
        request=ReadingRequest(sweep_id=session,expected_revision=before['revision'],observation_id=obs['id'],frame_sha256=frame.sha256))
    detection=DetectionJob(kind='detection',job_id='first-detection',session_id=session,
        expected_inventory_revision=before['revision'],expected_reference_revision=guide['reference_revision'],
        request=DetectionRequest(sweep_id=session,frame_ref=frame.id,frame_sha256=frame.sha256,shelf_id='selected-synthetic-shelf',
            shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5)))
    history=[]
    def cli(*flags):
        result=subprocess.run([sys.executable,'-B','-m','library_claim.recognition_jobs','--store',str(store.root),*flags],check=True,capture_output=True,text=True)
        value=json.loads(result.stdout);history.append(dict(args=list(flags),result=value));return value
    jobs=[reading,detection,reading.model_copy(update={'job_id':'selected-reading'}),detection.model_copy(update={'job_id':'selected-detection'})]
    for job in jobs:
        path=root/(job.job_id+'.json');path.write_text(json_text(job.model_dump()),encoding='utf-8');assert cli('--enqueue',str(path))['status']=='queued'
    reading_file=root/'reading-response.json';reading_file.write_text(json_text(dict(legibility='unreadable',spans=[],uncertainty='Synthetic fixture; no real accuracy claimed')),encoding='utf-8')
    detection_file=root/'detection-response.json';detection_file.write_text(json_text(dict(coverage='clear',objects=[dict(kind='book_spine',orientation='upright',polygon_1000=[[300,100],[400,100],[400,800],[300,800]],reason='Synthetic rectangle')],unresolved_regions=[])),encoding='utf-8')
    detection_result=cli('--run-one','--job-id','selected-detection','--response',str(detection_file))
    assert detection_result['status']=='completed' and detection_result['input']['job_id']=='selected-detection'
    assert cli('--run-one','--job-id','selected-detection','--response',str(detection_file))==detection_result
    assert [j['status'] for j in cli('--list')]==['queued','queued','queued','completed']
    reading_result=cli('--run-one','--job-id','selected-reading','--response',str(reading_file))
    assert reading_result['status']=='completed' and reading_result['result_status']=='partial'
    assert cli('--run-one','--job-id','selected-reading','--response',str(reading_file))==reading_result
    assert [j['status'] for j in cli('--list')]==['queued','queued','completed','completed']
    cancelled=cli('--cancel','first-reading')
    assert cli('--run-one','--job-id','first-reading','--response',str(reading_file))==cancelled
    assert [j['status'] for j in cli('--list')]==['cancelled','queued','completed','completed']
    assert ledger.snapshot(session)==before
    assert all(not j.get('worker_active',False) for j in cli('--list'))
    (root/'cli-history.json').write_text(json_text(history),encoding='utf-8')
    summary=dict(synthetic=True,provider_requests=0,selected_reading_and_detection=True,non_fifo=True,
        repeated_selection_and_restart_no_retry=True,cancelled_selection_no_fallback=True,inventory_unchanged=True,
        worker_slots_released=True,independent_processes=len(history))
    (root/'smoke-summary.json').write_text(json_text(summary),encoding='utf-8');print(json_text(summary))

if __name__=='__main__':main()
