import io
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from library_claim.capture_store import FrameStore,CaptureInput
from library_claim.capture_session import CaptureSessions
from library_claim.guidance import GuidanceStore,GuidanceCommand
from library_claim.server import create_app
from library_claim.tracking import TrackStore,TrackingCommand,digest
from library_claim.spine_detection import DetectionRequest,DetectionResponse,export_detection
from tests.test_spine_detection import proposal


SESSION='d'*32


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.frames=FrameStore(self.root/'store');self.guide=GuidanceStore(self.frames);self.guide.start(SESSION)

    def turn(self,payload,speaker='claimant',cid=None,revision=None):
        revision=self.guide.snapshot(SESSION)['revision'] if revision is None else revision
        return GuidanceCommand(command_id=cid or f'turn-{revision}',session_id=SESSION,expected_revision=revision,speaker=speaker,payload=payload)

    def apply(self,payload,**kwargs): return self.guide.apply(self.turn(payload,**kwargs))

    def locale(self): return self.apply(dict(action='locale',country='IN',currency='INR',claimant_statement='Use India and Indian rupees.'))

    def ready(self):
        self.locale();return self.apply(dict(action='skip_reference',claimant_statement='I have no measured reference; keep dimensions unknown.'))

    def bind(self):
        self.ready();CaptureSessions(self.frames).start('IN','INR',SESSION);return self.apply(dict(action='bind_capture'),speaker='agent')

    def reference(self,**update):
        return dict(action='reference',description='Measured card',width_cm='10',height_cm='20',width_uncertainty_cm='0.1',height_uncertainty_cm='0.2',
            dimensions_verified=True,dimension_provenance='Claimant measured with a ruler',claimant_statement='I measured this card myself.',**update)

    def tracks(self):
        sink=io.BytesIO();Image.new('RGB',(1600,900),'white').save(sink,'PNG')
        frame=self.frames.save(CaptureInput(sweep_id=SESSION,upload_id='shelf',captured_at=datetime.now(timezone.utc),media_sequence=0,source='file_import',synthetic=True),sink.getvalue())
        request=DetectionRequest(sweep_id=SESSION,frame_ref=frame.id,frame_sha256=frame.sha256,shelf_id='shelf',shelf_region_px=(0,0,1600,900),policy=dict(min_polygon_area_px2=100,max_pair_overlap_fraction=.5))
        bundle=self.root/'detection';detected=export_detection(self.frames,request,bundle,DetectionResponse(coverage='clear',objects=[proposal(),proposal((300,100,400,800))],unresolved_regions=[]))
        command=TrackingCommand(command_id='import',sweep_id=SESSION,expected_revision=0,operation='import',detection_result_sha256=digest((bundle/'detection_result.json').read_bytes()),
            track_id=None,owned=None,provenance='two distinct fixture copies',decisions=[dict(observation_id=b['id'],action='new',track_id=None,provenance='fixture rectangle') for b in detected['books']])
        return TrackStore(self.frames).apply(command,bundle),frame

    def request(self,reason='isbn_not_visible',request_id='isbn',track=None,inv=0):
        return self.apply(dict(action='request_evidence',request_id=request_id,reason_code=reason,track_id=track,shelf_id='shelf',expected_inventory_revision=inv),speaker='agent')

    def test_start_asks_locale_without_capture_or_defaults_and_restart(self):
        initial=self.guide.snapshot(SESSION)
        self.assertIsNone(initial['locale']);self.assertIn('country',initial['next_prompt']);self.assertIsNone(initial['capture_start_proposal'])
        self.assertEqual(initial,GuidanceStore(self.frames).start(SESSION))
        with self.assertRaises(KeyError): CaptureSessions(self.frames).snapshot(SESSION)

    def test_country_currency_before_reference_and_explicit_locale_validation(self):
        with self.assertRaisesRegex(ValueError,'first'): self.apply(self.reference())
        with self.assertRaises(ValueError): self.apply(dict(action='locale',country='India',currency='INR',claimant_statement='India'))
        state=self.locale();self.assertEqual(state['phase'],'awaiting_reference');self.assertIn('independently measured',state['next_prompt'])

    def test_verified_dimensions_are_declarations_not_calibration(self):
        self.locale();state=self.apply(self.reference())
        self.assertEqual(state['phase'],'ready_to_capture');self.assertFalse(state['metric_ready'])
        self.assertEqual(state['reference']['width_cm'],'10');self.assertEqual(state['reference_revision'],1)
        self.assertEqual(state['calibration_status'],'not_geometrically_verified')

    def test_unknown_unverified_reference_and_skip_do_not_invent_size(self):
        self.locale();payload=self.reference();payload.update(width_cm=None,height_cm=None,width_uncertainty_cm=None,height_uncertainty_cm=None,dimensions_verified=False)
        state=self.apply(payload);self.assertEqual(state['phase'],'awaiting_reference')
        state=self.apply(dict(action='skip_reference',claimant_statement='Cannot provide a measured object.'))
        self.assertTrue(state['reference_skipped']);self.assertFalse(state['metric_ready']);self.assertIsNone(state['reference'])

    def test_invalid_dimensions_nan_missing_tolerance_and_blank_provenance(self):
        for update in [dict(width_cm='NaN'),dict(width_uncertainty_cm=None),dict(width_uncertainty_cm='10'),dict(dimension_provenance=' '),dict(description=' ')]:
            with self.subTest(update=update),self.assertRaises(ValueError): self.turn({**self.reference(),**update})

    def test_capture_requires_same_session_locale_and_reference_disposition(self):
        self.locale()
        with self.assertRaises(ValueError): self.apply(dict(action='bind_capture'),speaker='agent')
        self.apply(dict(action='skip_reference',claimant_statement='No reference.'))
        CaptureSessions(self.frames).start('GB','GBP',SESSION)
        with self.assertRaisesRegex(ValueError,'differs'): self.apply(dict(action='bind_capture'),speaker='agent')

    def test_binding_capture_does_not_open_camera_or_relabel_country(self):
        state=self.bind();self.assertEqual(state['phase'],'capture_bound');self.assertEqual(state['capture_status'],'capturing')
        with self.assertRaisesRegex(ValueError,'relabel'): self.apply(dict(action='locale',country='GB',currency='GBP',claimant_statement='Use UK pounds.'))

    def test_retry_stale_and_conflicting_command_ids(self):
        command=self.turn(dict(action='locale',country='IN',currency='INR',claimant_statement='Use India rupees.'),cid='locale')
        first=self.guide.apply(command);self.assertEqual(first,self.guide.apply(command))
        changed=command.model_copy(update=dict(payload=command.payload.model_copy(update=dict(claimant_statement='Use a different declaration.'))))
        with self.assertRaisesRegex(ValueError,'different payload'): self.guide.apply(changed)
        with self.assertRaisesRegex(ValueError,'stale'): self.guide.apply(command.model_copy(update=dict(command_id='new')))

    def test_roles_and_unknown_fields_rejected(self):
        with self.assertRaises(ValueError): self.turn(dict(action='bind_capture'))
        with self.assertRaises(ValueError): self.turn(dict(action='locale',country='IN',currency='INR',claimant_statement='India',guessed=True))

    def test_isbn_request_respects_same_pass_no_moving_books_and_decline(self):
        self.bind();state=self.request();self.assertIn('without moving a book',state['next_prompt'])
        state=self.apply(dict(action='decline_evidence',request_id='isbn',claimant_statement='ISBN is hidden; I will leave it unknown.'))
        self.assertEqual(state['requests'][0]['status'],'declined_unknown')

    def test_received_frame_remains_analysis_pending_not_reading_success(self):
        self.bind();inventory,frame=self.tracks();self.request(track=inventory['books'][0]['id'],inv=1)
        state=self.apply(dict(action='evidence_received',request_id='isbn',frame_ref=frame.id),speaker='agent')
        self.assertEqual(state['requests'][0]['status'],'received_analysis_pending')
        self.assertEqual(TrackStore(self.frames).snapshot(SESSION),inventory)

    def test_cross_sweep_and_tampered_received_evidence_fail(self):
        self.bind();_,frame=self.tracks();self.request(inv=1)
        data=self.frames.read(frame.id)
        other=self.frames.save(CaptureInput(sweep_id='other',upload_id='other',captured_at=datetime.now(timezone.utc),media_sequence=0,source='file_import',synthetic=True),data)
        with self.assertRaisesRegex(ValueError,'cross-sweep'): self.apply(dict(action='evidence_received',request_id='isbn',frame_ref=other.id),speaker='agent')
        self.apply(dict(action='evidence_received',request_id='isbn',frame_ref=frame.id),speaker='agent')
        (self.frames.root/frame.path).write_bytes(b'bad')
        with self.assertRaises(ValueError): self.guide.snapshot(SESSION)

    def test_binding_answer_is_assertion_and_requires_matching_request(self):
        self.bind();self.request(reason='binding_unknown',request_id='binding')
        state=self.apply(dict(action='binding',request_id='binding',physical_format='unknown',claimant_statement='I cannot tell the binding.'))
        self.assertEqual(state['requests'][0]['answer']['physical_format'],'unknown');self.assertTrue(state['inventory_mutated'] is False)
        with self.assertRaises(ValueError): self.apply(dict(action='binding',request_id='binding',physical_format='paperback',claimant_statement='Paperback.'))

    def test_ambiguous_correction_asks_target_without_title_deduplication(self):
        self.bind();inventory,_=self.tracks()
        state=self.apply(dict(action='correction',intent_id='exclude',operation='exclude',track_id=None,expected_inventory_revision=1,claimant_statement='That book is borrowed.'))
        self.assertEqual(state['corrections'][0]['status'],'awaiting_target');self.assertEqual(len(state['target_choices']),2)
        self.assertIn('Which physical book',state['next_prompt'])
        state=self.apply(dict(action='choose_target',intent_id='exclude',track_id=inventory['books'][1]['id'],expected_inventory_revision=1,claimant_statement='I mean this second physical track.'))
        intent=state['corrections'][0];self.assertEqual(intent['status'],'pending_review');self.assertFalse(intent['applied'])
        TrackingCommand.model_validate(intent['proposed_command']);self.assertEqual(TrackStore(self.frames).snapshot(SESSION),inventory)

    def test_targeted_clear_and_signed_requests_are_not_applied(self):
        self.bind();inventory,_=self.tracks();track=inventory['books'][0]['id']
        state=self.apply(dict(action='correction',intent_id='clear',operation='clear_identity',track_id=track,expected_inventory_revision=1,claimant_statement='The title is wrong.'))
        from library_claim.identity import IdentityCommand
        IdentityCommand.model_validate(state['corrections'][0]['proposed_command'])
        state=self.apply(dict(action='correction',intent_id='signed',operation='signed',track_id=track,expected_inventory_revision=1,claimant_statement='This is signed.'))
        self.assertEqual(state['corrections'][1]['proposed_command']['operation'],'appraisal');self.assertFalse(state['corrections'][1]['applied'])
        self.assertEqual(TrackStore(self.frames).snapshot(SESSION),inventory)

    def test_unknown_targets_and_stale_inventory_rejected(self):
        self.bind();self.tracks()
        with self.assertRaises(ValueError): self.request(track='missing',inv=1)
        with self.assertRaisesRegex(ValueError,'stale inventory'): self.request(inv=0)

    def test_capture_close_blocks_new_recapture_but_retains_pending_turns(self):
        self.bind();self.request();CaptureSessions(self.frames).end(SESSION,'end',0)
        state=self.guide.snapshot(SESSION);self.assertEqual(state['capture_status'],'closed');self.assertIn('ended',state['next_prompt'])
        with self.assertRaisesRegex(ValueError,'ends'): self.request(request_id='again')
        self.assertEqual(state,GuidanceStore(self.frames).snapshot(SESSION))

    def test_reference_change_versions_metric_jobs_without_measurements(self):
        self.bind();state=self.apply(self.reference())
        self.assertEqual(state['reference_revision'],2);self.assertIn('metric_jobs',state['events'][-1]['invalidated_dependencies'])
        self.assertFalse(state['metric_ready']);self.assertEqual(state['capture_status'],'capturing')

    def test_report_escapes_claimant_text(self):
        self.apply(dict(action='locale',country='IN',currency='INR',claimant_statement='<script>bad()</script>'))
        self.guide.export(SESSION,self.root/'export')
        html=(self.root/'export/report.html').read_text();self.assertNotIn('<script>bad()',html);self.assertIn('&lt;script&gt;',html)

    def test_guidance_http_protocol_bounds_and_restart(self):
        origin='http://testserver';app=create_app(self.root/'http',{origin});headers={'Origin':origin}
        with TestClient(app) as client:
            response=client.post('/api/guidance',json=dict(session_id=SESSION),headers=headers);self.assertEqual(response.status_code,200)
            self.assertIsNone(response.json()['locale'])
            command=self.turn(dict(action='locale',country='GB',currency='GBP',claimant_statement='United Kingdom, pounds.'),revision=0)
            response=client.post(f'/api/guidance/{SESSION}/turns',json=command.model_dump(mode='json'),headers=headers)
            self.assertEqual(response.status_code,200);saved=response.json()
            self.assertEqual(client.post(f'/api/guidance/{SESSION}/turns',json=command.model_dump(mode='json')).status_code,403)
            self.assertEqual(client.post('/api/guidance',content=b'x'*4097,headers=headers).status_code,413)
            self.assertEqual(client.get('/api/guidance/missing').status_code,404)
        with TestClient(create_app(self.root/'http',{origin})) as client: self.assertEqual(client.get(f'/api/guidance/{SESSION}').json(),saved)


if __name__=='__main__': unittest.main()
