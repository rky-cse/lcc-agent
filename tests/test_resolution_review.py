import json
import unittest
from contextlib import closing
from unittest.mock import patch
from fastapi.testclient import TestClient
from library_claim.capture_store import CaptureInput
from library_claim.resolution_review import ResolutionReviewer, ResolutionReview
from library_claim.tracking import TrackingCommand
from library_claim.server import create_app
from tests import test_registration_review as registration_fixture
from tests.test_guidance import SESSION


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=registration_fixture.RegistrationTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        # A saved revisit of the original shelf leaves both detections explicitly unresolved.
        frame=f.fx.frames.save(CaptureInput(sweep_id=SESSION,upload_id='unresolved-revisit',captured_at=f.frame.captured_at,
            media_sequence=1,source='file_import',synthetic=True),f.fx.frames.read(f.frame.id))
        f.complete(f.job.model_copy(update={'request':f.job.request.model_copy(update={'frame_ref':frame.id,'frame_sha256':frame.sha256,'shelf_id':'shelf'})}))
        self.before=f.reviewer.apply(f.review([('unresolved',None),('unresolved',None)]))['inventory']
        self.oid=next(o['id'] for o in self.before['observations'] if o['track_id'] is None)
        self.service=ResolutionReviewer(f.fx.guide)

    def review(self,action='new',target=None):
        return ResolutionReview(review_id='resolution-review',session_id=SESSION,expected_inventory_revision=2,
            expected_reference_revision=self.fixture.job.expected_reference_revision,reviewer='Synthetic reviewer',
            reason='Explicit saved geometry review',decisions=[dict(observation_id=self.oid,action=action,track_id=target,provenance='Distinct physical evidence')])

    def test_read_only_then_new_leaves_other_observation_unresolved(self):
        view=self.service.snapshot(SESSION,self.oid)
        self.assertTrue(view['can_resolve']);self.assertEqual(len(view['targets']),2)
        self.assertEqual(self.service.ledger.snapshot(SESSION),self.before)
        result=self.service.apply(self.review());self.assertTrue(result['applied'])
        self.assertEqual(result['ledger_event_revision'],3);self.assertEqual(result['inventory']['assigned_track_count'],3)
        self.assertEqual(sum(o['track_id'] is None for o in result['inventory']['observations']),1)
        self.assertFalse(self.service.snapshot(SESSION,self.oid)['can_resolve'])

    def test_same_copy_preserves_ownership_and_count(self):
        target=self.before['tracks'][0]['id']
        self.service.ledger.apply(TrackingCommand(command_id='exclude',sweep_id=SESSION,expected_revision=2,operation='ownership',
            track_id=target,owned=False,detection_result_sha256=None,decisions=[],provenance='Explicit excluded fixture'))
        result=self.service.apply(self.review('same',target).model_copy(update={'expected_inventory_revision':3}))
        self.assertEqual(result['inventory']['assigned_track_count'],2)
        track=next(t for t in result['inventory']['tracks'] if t['id']==target)
        self.assertFalse(track['owned']);self.assertEqual(len(track['observations']),2)

    def test_exact_retry_after_restart_and_later_reference_change(self):
        review=self.review();first=self.service.apply(review)
        self.fixture.fx.apply(self.fixture.fx.reference())
        restarted=ResolutionReviewer(self.fixture.fx.guide)
        self.assertEqual(restarted.apply(review),first)
        with self.assertRaises(ValueError):restarted.apply(review.model_copy(update={'reason':'Changed content'}))
        with self.assertRaises(ValueError):restarted.apply(review.model_copy(update={'review_id':'another'}))
        self.assertEqual(restarted.ledger.snapshot(SESSION)['revision'],3)

    def test_ack_lost_after_commit_recovers_exact_event(self):
        review=self.review();original=self.service.ledger._snapshot
        def lost(state):
            if state['revision']==3:raise OSError('lost after commit')
            return original(state)
        with patch.object(self.service.ledger,'_snapshot',side_effect=lost):
            with self.assertRaises(OSError):self.service.apply(review)
        self.assertEqual(self.service.ledger.snapshot(SESSION)['revision'],3)
        self.assertEqual(self.service.apply(review)['ledger_event_revision'],3)

    def test_stale_inventory_and_reference_reject_without_mutation(self):
        for field in ['expected_inventory_revision','expected_reference_revision']:
            with self.assertRaises(ValueError):self.service.apply(self.review().model_copy(update={field:99}))
        self.assertEqual(self.service.ledger.snapshot(SESSION),self.before)

    def test_reference_race_checked_under_writer_lock(self):
        original=self.service.ledger.apply
        def race(*args,**kwargs):self.fixture.fx.apply(self.fixture.fx.reference());return original(*args,**kwargs)
        with patch.object(self.service.ledger,'apply',side_effect=race):
            with self.assertRaises(ValueError):self.service.apply(self.review())
        self.assertEqual(self.service.ledger.snapshot(SESSION),self.before)

    def test_unknown_target_and_same_frame_merge_rollback(self):
        with self.assertRaises(ValueError):self.service.apply(self.review('same','missing'))
        first=self.service.apply(self.review())
        target=next(o['track_id'] for o in first['inventory']['observations'] if o['id']==self.oid)
        other=next(o['id'] for o in first['inventory']['observations'] if o['track_id'] is None)
        review=self.review('same',target).model_dump();review.update(review_id='other',expected_inventory_revision=3)
        review['decisions'][0]['observation_id']=other
        with self.assertRaises(ValueError):self.service.apply(ResolutionReview.model_validate(review))
        self.assertEqual(self.service.ledger.snapshot(SESSION),first['inventory'])

    def test_blank_unresolved_multiple_decisions_rejected(self):
        data=self.review().model_dump()
        for update in [dict(reviewer=' '),dict(reason=' '),dict(decisions=[]),dict(decisions=data['decisions']*2),
                       dict(decisions=[data['decisions'][0]|{'action':'unresolved'}]),dict(decisions=[data['decisions'][0]|{'provenance':' '}])]:
            with self.assertRaises(ValueError):ResolutionReview.model_validate(data|update)

    def test_archived_geometry_or_event_corruption_blocks_review(self):
        for corruption in ['geometry','event']:
            with self.subTest(corruption=corruption),closing(self.fixture.fx.frames._connect()) as db:
                state=self.service.ledger._read(db,SESSION);original=json.dumps(state)
                if corruption=='geometry':state['observations'][self.oid]['polygon_px'][0][0]+=1
                else:state['events'][-1]['command']['provenance']='tampered'
                db.execute('UPDATE physical_inventory SET state=? WHERE sweep_id=?',(json.dumps(state),SESSION));db.commit()
                with self.assertRaises(ValueError):self.service.snapshot(SESSION,self.oid)
                db.execute('UPDATE physical_inventory SET state=? WHERE sweep_id=?',(original,SESSION));db.commit()

    def test_http_scope_origin_size_receipt_and_read_only_page(self):
        url=f'/api/guidance/{SESSION}/resolution/{self.oid}';body=self.review().model_dump(mode='json')
        with TestClient(create_app(self.fixture.fx.frames.root,{'http://testserver'})) as client:
            self.assertEqual(client.get(url).status_code,200)
            self.assertEqual(client.get('/resolution').status_code,200)
            self.assertEqual(client.get('/assets/resolution_page.mjs').status_code,200)
            self.assertEqual(client.get(url.replace(SESSION,'a'*32)).status_code,404)
            self.assertEqual(client.post(url,json=body).status_code,403)
            headers={'Origin':'http://testserver'}
            self.assertEqual(client.post(url+'other',json=body,headers=headers).status_code,422)
            self.assertEqual(client.post(url,content='x'*(16*1024+1),headers=headers).status_code,413)
            first=client.post(url,json=body,headers=headers);self.assertEqual(first.status_code,200)
            self.assertEqual(client.post(url,json=body,headers=headers).json(),first.json())
            self.assertFalse(client.get(url).json()['can_resolve'])

if __name__=='__main__':unittest.main()
