"""Independent-process queue/enqueue/worker/restart smoke; synthetic, no provider calls."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from library_claim.capture_store import FrameStore
from library_claim.guidance import GuidanceStore
from library_claim.packet import json_text
from library_claim.recognition_jobs import ReadingJob
from library_claim.spine_reading import ReadingRequest
from library_claim.tracking import TrackStore, TrackingCommand


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    root = parser.parse_args().output.resolve()
    if root.exists(): raise FileExistsError('choose a fresh smoke directory')
    root.mkdir(parents=True)
    subprocess.run([sys.executable, '-B', '-m', 'scripts.smoke_guidance', '--output', str(root/'setup')], check=True)
    store = FrameStore(root/'setup'/'store'); session = 'e'*32
    ledger = TrackStore(store); before = ledger.snapshot(session); guide = GuidanceStore(store).snapshot(session)
    obs = before['observations'][0]
    job = ReadingJob(job_id='smoke-reading', session_id=session, expected_reference_revision=guide['reference_revision'],
        request=ReadingRequest(sweep_id=session, expected_revision=before['revision'], observation_id=obs['id'], frame_sha256=obs['frame_sha256']))
    input_file = root/'job.json'; input_file.write_text(json_text(job.model_dump())+'\n', encoding='utf-8')
    response = root/'response.json'; response.write_text(json_text(dict(legibility='unreadable', spans=[], uncertainty='Synthetic blank crop; no physical accuracy claimed')), encoding='utf-8')
    history = []
    def cli(*args):
        child = subprocess.run([sys.executable, '-B', '-m', 'library_claim.recognition_jobs', '--store', str(store.root), *args],
            check=True, capture_output=True, text=True)
        result = json.loads(child.stdout); history.append(dict(args=list(args), result=result)); return result
    queued = cli('--enqueue', str(input_file)); assert queued['status']=='queued'
    assert cli('--enqueue', str(input_file)) == queued
    completed = cli('--run-one', '--response', str(response))
    assert completed['status']=='completed' and completed['result_status']=='partial' and completed['eligible_for_review']
    assert cli('--list')==[completed]
    assert cli('--run-one', '--response', str(response)) is None
    assert ledger.snapshot(session)==before
    ledger.apply(TrackingCommand(command_id='smoke-exclude', sweep_id=session, expected_revision=before['revision'], operation='ownership',
        track_id=before['books'][0]['id'], owned=False, detection_result_sha256=None, decisions=[], provenance='Explicit synthetic smoke correction'))
    stale = cli('--list')[0]; assert stale['status']=='stale' and not stale['eligible_for_review']
    (root/'cli-history.json').write_text(json_text(history)+'\n', encoding='utf-8')
    summary = dict(synthetic=True, provider_requests=0, independent_processes=len(history), completed_status='partial',
        exact_enqueue_retry=True, restart_result_identical=True, no_automatic_retry=True, reading_inventory_unchanged=True,
        later_correction_invalidates_result=True, report=str(store.root/'recognition'/'smoke-reading'/'report.html'))
    (root/'smoke-summary.json').write_text(json_text(summary)+'\n', encoding='utf-8')
    print(json_text(summary))


if __name__ == '__main__': main()
