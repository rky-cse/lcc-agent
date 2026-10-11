import unittest
from unittest.mock import patch

from library_claim.recognition_jobs import RecognitionQueue, ReadingJob
from library_claim.spine_reading import ReadingRequest, ReadingResponse, export_reading
from library_claim.tracking import TrackingCommand
from library_claim.packet import json_text
from tests import test_guidance as fixture


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixture.GuidanceTests(); self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.fx.bind(); self.inventory, self.frame = self.fx.tracks()
        self.queue = RecognitionQueue(self.fx.frames)
        self.job = ReadingJob(job_id='reading-1', session_id=fixture.SESSION, expected_reference_revision=self.fx.guide.snapshot(fixture.SESSION)["reference_revision"],
            request=ReadingRequest(sweep_id=fixture.SESSION, expected_revision=1,
                observation_id=self.inventory['observations'][0]['id'], frame_sha256=self.frame.sha256))
        self.response = ReadingResponse(legibility='unreadable', spans=[], uncertainty='Synthetic blank fixture')

    def change_inventory(self):
        self.fx.guide.ledger.apply(TrackingCommand(command_id='borrowed', sweep_id=fixture.SESSION, expected_revision=1,
            operation='ownership', track_id=self.inventory['books'][0]['id'], owned=False,
            detection_result_sha256=None, decisions=[], provenance='Explicit synthetic ownership correction'))

    def test_completed_partial_no_mutation_and_restart(self):
        self.queue.enqueue(self.job)
        result = self.queue.run_next(response=self.response)
        self.assertEqual(result['status'], 'completed'); self.assertEqual(result['result_status'], 'partial')
        self.assertTrue(result['eligible_for_review']); self.assertFalse(result['inventory_mutated'])
        self.assertEqual(self.inventory, self.fx.guide.ledger.snapshot(fixture.SESSION))
        self.assertEqual(result, RecognitionQueue(self.fx.frames).get(self.job.job_id))
        self.assertIsNone(self.queue.run_next(response=self.response))

    def test_exact_enqueue_retry_even_after_revision_change(self):
        self.queue.enqueue(self.job); self.change_inventory()
        self.assertEqual(self.queue.enqueue(self.job)['status'], 'queued')
        with self.assertRaisesRegex(ValueError, 'different'):
            self.queue.enqueue(self.job.model_copy(update={'expected_reference_revision': 99}))

    def test_stale_before_run_zero_provider_calls(self):
        self.queue.enqueue(self.job); self.change_inventory()
        with patch('library_claim.recognition_jobs.export_reading') as call:
            self.assertEqual(self.queue.run_next(response=self.response)['status'], 'stale')
            call.assert_not_called()

    def test_reference_change_invalidates(self):
        self.queue.enqueue(self.job); self.fx.apply(self.fx.reference())
        self.assertEqual(self.queue.run_next(response=self.response)['status'], 'stale')

    def test_unrelated_guidance_turn_does_not_invalidate(self):
        self.queue.enqueue(self.job)
        self.fx.request(track=self.inventory['books'][0]['id'], inv=1)
        self.assertEqual(self.queue.run_next(response=self.response)['status'], 'completed')

    def test_late_correction_never_publishes_result(self):
        self.queue.enqueue(self.job)
        def execute(*args, **kwargs):
            result = export_reading(*args, **kwargs); self.change_inventory(); return result
        with patch('library_claim.recognition_jobs.export_reading', side_effect=execute):
            result = self.queue.run_next(response=self.response)
        self.assertEqual(result['status'], 'stale'); self.assertFalse(result['eligible_for_review'])

    def test_completed_result_becomes_stale_on_read(self):
        self.queue.enqueue(self.job); self.queue.run_next(response=self.response); self.change_inventory()
        self.assertEqual(self.queue.get(self.job.job_id)['status'], 'stale')
        self.assertFalse(self.queue.get(self.job.job_id)['eligible_for_review'])

    def test_cancel_during_provider_revokes_publication(self):
        self.queue.enqueue(self.job)
        def execute(*args, **kwargs):
            self.queue.cancel(self.job.job_id); return export_reading(*args, **kwargs)
        with patch('library_claim.recognition_jobs.export_reading', side_effect=execute):
            self.assertEqual(self.queue.run_next(response=self.response)['status'], 'cancelled')
        self.assertIsNone(self.queue.run_next(response=self.response))

    def test_interrupted_attempt_blocks_restart_until_explicit_close_no_retry(self):
        self.queue.enqueue(self.job)
        with patch('library_claim.recognition_jobs.export_reading', side_effect=SystemExit):
            with self.assertRaises(SystemExit): self.queue.run_next(response=self.response)
        restarted = RecognitionQueue(self.fx.frames)
        with self.assertRaisesRegex(ValueError, 'resolve running'):
            restarted.run_next(response=self.response)
        self.assertEqual(restarted.interrupt(self.job.job_id)['status'], 'interrupted')
        self.assertIsNone(restarted.run_next(response=self.response))
        with self.assertRaises(ValueError): restarted.interrupt(self.job.job_id)

    def test_error_messages_not_journaled_and_not_retried(self):
        self.queue.enqueue(self.job)
        with patch('library_claim.recognition_jobs.export_reading', side_effect=RuntimeError('SECRET_KEY')):
            result = self.queue.run_next(response=self.response)
        self.assertEqual(result['status'], 'failed'); self.assertNotIn('SECRET_KEY', json_text(result))
        self.assertIsNone(self.queue.run_next(response=self.response))

    def test_integrity_failure(self):
        self.queue.enqueue(self.job); self.queue.run_next(response=self.response)
        (self.queue._directory(self.job.job_id) / 'reading_result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'integrity'): self.queue.get(self.job.job_id)

    def test_limits_and_cancel(self):
        with patch.object(self.queue, 'MAX_PENDING', 1):
            self.queue.enqueue(self.job)
            with self.assertRaisesRegex(ValueError, 'limit'):
                self.queue.enqueue(self.job.model_copy(update={'job_id': 'second'}))
            self.queue.cancel(self.job.job_id)
            self.queue.enqueue(self.job.model_copy(update={'job_id': 'second'}))
        with patch.object(self.queue, 'MAX_JOBS', 2):
            with self.assertRaises(ValueError): self.queue.enqueue(self.job.model_copy(update={'job_id': 'third'}))

    def test_hash_and_revision_validation_before_enrollment(self):
        for update in [{'frame_sha256': '0'*64}, {'expected_revision': 0}, {'observation_id': 'missing'}]:
            bad = self.job.model_copy(update={'request': self.job.request.model_copy(update=update)})
            with self.assertRaises(ValueError): self.queue.enqueue(bad)
        self.assertEqual(self.queue.list(), [])

    def test_provider_unavailable_export_retained(self):
        self.queue.enqueue(self.job)
        with patch('library_claim.spine_reading.request_structured', return_value=(None,
            {'code': 'rate_limit', 'reason': 'Provider quota unavailable', 'retryable': True}, None, None)):
            result = self.queue.run_next(key='not-a-real-key')
        self.assertEqual(result['result_status'], 'unavailable'); self.assertEqual(result['status'], 'completed')
        self.assertIsNone(self.queue.run_next(response=self.response))

    def test_busy_worker_guard(self):
        self.queue.enqueue(self.job)
        def execute(*args, **kwargs):
            with self.assertRaisesRegex(ValueError, 'worker busy'): self.queue.run_next(response=self.response)
            return export_reading(*args, **kwargs)
        with patch('library_claim.recognition_jobs.export_reading', side_effect=execute):
            self.assertEqual(self.queue.run_next(response=self.response)['status'], 'completed')


if __name__ == '__main__': unittest.main()
