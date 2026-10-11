import json
import unittest
from contextlib import closing
from unittest.mock import patch

from fastapi.testclient import TestClient

from library_claim.correction_execution import CorrectionExecutor,CorrectionExecution
from library_claim.guidance import GuidanceStore
from library_claim.identity import IdentityStore,IdentityCommand
from library_claim.catalogue import CatalogueRequest,export_catalogue
from library_claim.spine_reading import ReadingRequest,ReadingResponse,export_reading
from library_claim.tracking import TrackingCommand,digest
from library_claim.packet import json_text
from library_claim.server import create_app
from tests import test_guidance as guidance_fixture
from tests.test_spine_reading import span
SESSION=guidance_fixture.SESSION


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.fx=guidance_fixture.GuidanceTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.bind();self.before,self.frame=self.fx.tracks();self.a,self.b=[b['id'] for b in self.before['books']]
        self.executor=CorrectionExecutor(self.fx.guide)
    def intent(self,operation='exclude',track='default',name='borrowed'):
        if track=='default':track=self.b
        inv=self.fx.guide.ledger.snapshot(SESSION)['revision']
        return self.fx.apply(dict(action='correction',intent_id=name,operation=operation,track_id=track,expected_inventory_revision=inv,claimant_statement='This physical copy is borrowed.'))
    def request(self,decision='apply',intent_id='borrowed',request_id='execute',**update):
        state=self.fx.guide.snapshot(SESSION)
        return CorrectionExecution.model_validate(dict(request_id=request_id,session_id=SESSION,intent_id=intent_id,expected_guidance_revision=state['revision'],
            expected_inventory_revision=state['inventory_revision'],decision=decision,reviewer='Synthetic reviewer',reason='Reviewed shelf position and saved original',**update))
    def book(self,inventory,track=None):return next(b for b in inventory['books'] if b['id']==(track or self.b))
    def test_only_selected_copy_excluded_receipt_verified(self):
        state=self.intent();result=self.executor.execute(self.request());receipt=result['execution']
        self.assertTrue(receipt['applied']);self.assertEqual(receipt['status'],'applied');self.assertEqual(receipt['ledger_event_revision'],2)
        self.assertFalse(self.book(result['inventory'])['owned']);self.assertTrue(self.book(result['inventory'],self.a)['owned'])
        self.assertEqual(result['inventory']['assigned_track_count'],2);self.assertEqual(result['guidance']['revision'],state['revision']+2)
        self.assertEqual(receipt['evidence_refs'],[self.frame.id]);self.assertEqual(receipt['stage_result']['status'],'success')
        self.assertTrue(result['guidance']['inventory_mutated']);self.assertFalse(result['guidance']['correction_execution_pending'])
    def test_exact_retry_after_restart_no_revisions(self):
        self.intent();request=self.request();first=self.executor.execute(request)
        restarted=CorrectionExecutor(GuidanceStore(self.fx.frames));self.assertEqual(restarted.execute(request),first)
    def test_changed_request_id_content_rejected(self):
        self.intent();request=self.request();self.executor.execute(request)
        with self.assertRaisesRegex(ValueError,'different'):self.executor.execute(request.model_copy(update=dict(reason='changed')))
    def test_stale_guidance_rejected_before_prepare(self):
        self.intent();request=self.request();self.fx.apply(dict(action='skip_reference',claimant_statement='Still no measured reference.'))
        with self.assertRaisesRegex(ValueError,'guidance'):self.executor.execute(request)
        self.assertEqual(self.fx.guide.ledger.snapshot(SESSION),self.before)
    def test_stale_inventory_and_proposal_not_rebased(self):
        self.intent();request=self.request();self.competing()
        with self.assertRaisesRegex(ValueError,'stale inventory'):self.executor.execute(request)
        fresh=request.model_copy(update=dict(expected_inventory_revision=2))
        with self.assertRaisesRegex(ValueError,'new reviewed intent'):self.executor.execute(fresh)
        self.assertFalse(self.book(self.fx.guide.ledger.snapshot(SESSION),self.a)['owned']);self.assertTrue(self.book(self.fx.guide.ledger.snapshot(SESSION))['owned'])
    def competing(self):
        command=TrackingCommand(command_id='other',sweep_id=SESSION,expected_revision=1,operation='ownership',track_id=self.a,owned=False,
            detection_result_sha256=None,decisions=[],provenance='Separate explicit fixture review')
        return self.fx.guide.ledger.apply(command)
    def test_ambiguous_assertion_cannot_dispatch(self):
        self.intent('exclude',None,'ambiguous')
        with self.assertRaises(ValueError):self.executor.execute(self.request(intent_id='ambiguous',request_id='ambiguous'))
        self.assertEqual(self.fx.guide.ledger.snapshot(SESSION),self.before)

    def test_signed_claim_flags_appraisal_without_identity_or_authentication(self):
        self.intent('signed',self.b,'signed');result=self.executor.execute(self.request(intent_id='signed',request_id='signed'))
        book=self.book(result['inventory']);self.assertEqual(book['status'],'needs_appraisal');self.assertEqual(book['title'],'')
        self.assertEqual(book['edition'],'');self.assertTrue(book['owned'])
        track=next(t for t in result['inventory']['tracks'] if t['id']==self.b)
        self.assertFalse(track['appraisal_claims'][0]['authenticated'])
        self.assertEqual(self.book(result['inventory'],self.a)['status'],'unidentified')

    def test_shelf_exclusion_atomic_and_exact_receipt_replay(self):
        shelf=self.before['books'][0]['shelf']
        self.fx.apply(dict(action='shelf_correction',intent_id='shelf-exclusion',operation='exclude_shelf',shelf_id=shelf,
            expected_inventory_revision=1,claimant_statement='The books on this shelf are not mine'))
        request=self.request(intent_id='shelf-exclusion',request_id='shelf-exclusion');result=self.executor.execute(request)
        self.assertTrue(result['execution']['applied']);self.assertEqual(result['inventory']['revision'],2)
        self.assertTrue(all(not b['owned'] for b in result['inventory']['books']))
        self.assertEqual(result['inventory']['shelf_ownership'][shelf],False)
        self.assertEqual(self.executor.execute(request)['inventory']['revision'],2)
    def test_dismiss_ambiguous_does_not_mutate_inventory(self):
        self.intent(track=None);result=self.executor.execute(self.request(decision='dismiss'))
        self.assertEqual(result['execution']['status'],'dismissed');self.assertFalse(result['execution']['applied']);self.assertEqual(result['inventory'],self.before)
    def test_closed_capture_still_allows_reviewed_correction(self):
        self.intent();self.fx.guide.capture.end(SESSION,'done',0)
        result=self.executor.execute(self.request());self.assertTrue(result['execution']['applied']);self.assertEqual(result['guidance']['capture_status'],'closed')
    def test_crash_after_prepare_recovered_exact_request(self):
        self.intent();request=self.request();self.executor.prepare(request)
        state=self.fx.guide.snapshot(SESSION);self.assertEqual(state['corrections'][0]['status'],'dispatching');self.assertIsNone(state['inventory_mutated'])
        self.assertEqual(self.fx.guide.ledger.snapshot(SESSION),self.before)
        result=CorrectionExecutor(GuidanceStore(self.fx.frames)).execute(request);self.assertEqual(result['inventory']['revision'],2)
    def test_crash_after_inventory_commit_before_ack_no_double_apply(self):
        self.intent();request=self.request()
        with patch.object(self.executor,'acknowledge',side_effect=OSError('controlled crash')):
            with self.assertRaises(OSError):self.executor.execute(request)
        self.assertEqual(self.fx.guide.ledger.snapshot(SESSION)['revision'],2)
        result=CorrectionExecutor(GuidanceStore(self.fx.frames)).execute(request)
        self.assertEqual(result['inventory']['revision'],2);self.assertEqual(result['execution']['ledger_event_revision'],2)
    def test_new_request_cannot_steal_reserved_intent(self):
        self.intent();self.executor.prepare(self.request())
        with self.assertRaisesRegex(ValueError,'reserved'):self.executor.execute(self.request(request_id='second'))
    def test_other_guidance_turn_between_dispatch_and_ack_preserved(self):
        self.intent();request=self.request();receipt=self.executor.prepare(request);self.executor.dispatch(receipt)
        self.fx.apply(dict(action='skip_reference',claimant_statement='Reference remains unknown.'))
        self.executor.acknowledge(receipt);state=self.fx.guide.snapshot(SESSION)
        self.assertEqual(state['reference_skip_statement'],'Reference remains unknown.');self.assertTrue(state['corrections'][0]['applied'])
    def test_inventory_race_returns_failure_receipt_without_wrong_copy_change(self):
        self.intent();request=self.request();self.executor.prepare(request);self.competing()
        result=self.executor.execute(request);self.assertEqual(result['execution']['status'],'review_required');self.assertFalse(result['execution']['applied'])
        self.assertEqual(result['execution']['stage_result']['status'],'failed');self.assertTrue(self.book(result['inventory'])['owned'])
        self.assertEqual(self.executor.execute(request),result)
    def test_ack_requires_verified_event(self):
        self.intent();receipt=self.executor.prepare(self.request())
        with self.assertRaisesRegex(ValueError,'no verified'):self.executor.acknowledge(receipt)
    def test_later_include_keeps_historical_exclude_receipt(self):
        self.intent();first=self.request();self.executor.execute(first)
        self.intent(operation='include',name='include');result=self.executor.execute(self.request(intent_id='include',request_id='include'))
        self.assertTrue(self.book(result['inventory'])['owned']);self.assertEqual(result['inventory']['revision'],3)
        replay=self.executor.execute(first);self.assertTrue(replay['execution']['applied']);self.assertEqual(replay['execution']['ledger_event_revision'],2)
        self.assertTrue(self.book(replay['inventory'])['owned'])
    def accept_work(self):
        obs=next(o for o in self.before['observations'] if o['track_id']==self.b)
        reading_dir=self.fx.root/'reading';bundle=self.fx.root/'catalogue'
        reading=export_reading(self.fx.frames,ReadingRequest(sweep_id=SESSION,expected_revision=1,observation_id=obs['id'],frame_sha256=obs['frame_sha256']),reading_dir,
            ReadingResponse(legibility='readable',spans=[span(),span('MAYA SEN','author')],uncertainty=''))
        request=CatalogueRequest(reading_result_sha256=digest((reading_dir/'reading_result.json').read_bytes()),title_span_ids=[reading['text_evidence'][0]['id']],author_span_ids=[reading['text_evidence'][1]['id']],limit=5)
        export_catalogue(self.fx.frames,request,reading_dir,bundle,response_bytes=json_text(dict(docs=[dict(key='OL1W',title='River Atlas',author_name=['Maya Sen'],edition_count=1)],numFound=1,numFoundExact=True,start=0)).encode())
        return IdentityStore(self.fx.frames).apply(IdentityCommand(command_id='accept',sweep_id=SESSION,expected_revision=1,track_id=self.b,action='accept_work',
            catalogue_result_sha256=digest((bundle/'catalogue_result.json').read_bytes()),work_id='/works/OL1W',confirmed_span_ids=request.title_span_ids+request.author_span_ids,
            metadata=[],needs_appraisal=False,reviewer='Synthetic reviewer',reason='Controlled fixture literal confirmation'),bundle)
    def test_clear_accepted_work_preserves_copy_evidence_and_ownership(self):
        before=self.accept_work();self.assertEqual(self.book(before)['title'],'RIVER ATLAS')
        self.intent('clear_identity');result=self.executor.execute(self.request());book=self.book(result['inventory'])
        self.assertEqual(book['title'],'');self.assertEqual(book['status'],'unidentified');self.assertTrue(book['owned'])
        self.assertEqual(result['inventory']['observations'],before['observations']);self.assertEqual(result['inventory']['identity_evidence'],before['identity_evidence'])
        self.assertIn('edition',result['execution']['invalidated_dependencies']);self.assertIsNone(book['replacement_cost']['amount'])
    def test_tampered_original_blocks_dispatch(self):
        self.intent();request=self.request();(self.fx.frames.root/self.frame.path).write_bytes(b'broken')
        with self.assertRaises((ValueError,OSError)):self.executor.execute(request)
    def test_forged_proposed_command_rejected(self):
        self.intent()
        with closing(self.fx.frames._connect()) as db:
            state=self.fx.guide.read(db,SESSION);state['corrections'][0]['proposed_command']['track_id']=self.a
            db.execute('UPDATE guidance_sessions SET state=? WHERE id=?',(json_text(state),SESSION));db.commit()
        with self.assertRaisesRegex(ValueError,'integrity'):self.executor.execute(self.request())
    def test_receipt_with_missing_event_not_reported_as_applied(self):
        self.intent();request=self.request();self.executor.execute(request)
        with closing(self.fx.frames._connect()) as db:
            state=self.fx.guide.ledger._read(db,SESSION);state['events']=state['events'][:-1]
            db.execute('UPDATE physical_inventory SET state=? WHERE sweep_id=?',(json_text(state),SESSION));db.commit()
        with self.assertRaisesRegex(ValueError,'no matching'):self.executor.execute(request)
    def test_unknown_intent_blank_extra_fields_rejected(self):
        with self.assertRaises(ValueError):self.executor.execute(self.request())
        for update in [dict(reviewer=' '),dict(reason=' '),dict(extra=True)]:
            body=self.request().model_dump();body.update(update)
            with self.assertRaises(ValueError):CorrectionExecution.model_validate(body)
    def test_export_escaped_and_fresh_path(self):
        self.intent();request=self.request().model_copy(update=dict(reason='<script>not HTML</script>'));self.executor.execute(request)
        output=self.fx.root/'review';self.executor.export(SESSION,output)
        html=(output/'report.html').read_text();self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
        self.assertEqual((output/'evidence'/self.frame.path).read_bytes(),self.fx.frames.read(self.frame.id))
        with self.assertRaises(FileExistsError):self.executor.export(SESSION,output)
    def test_http_execution_origin_body_target_restart(self):
        self.intent();request=self.request();app=create_app(self.fx.frames.root,{'http://testserver'})
        with TestClient(app) as client:
            path=f'/api/guidance/{SESSION}/corrections'
            self.assertEqual(client.post(path,json=request.model_dump(mode='json')).status_code,403)
            self.assertEqual(client.post(path,content=b'x'*4097,headers={'Origin':'http://testserver'}).status_code,413)
            self.assertEqual(client.post('/api/guidance/'+'f'*32+'/corrections',json=request.model_dump(mode='json'),headers={'Origin':'http://testserver'}).status_code,422)
            first=client.post(path,json=request.model_dump(mode='json'),headers={'Origin':'http://testserver'});self.assertEqual(first.status_code,200)
        with TestClient(create_app(self.fx.frames.root,{'http://testserver'})) as client:
            repeat=client.post(path,json=request.model_dump(mode='json'),headers={'Origin':'http://testserver'})
            self.assertEqual(repeat.json(),first.json());self.assertEqual(client.get(path).json()['executions'][0]['status'],'applied')


if __name__=='__main__':unittest.main()
