import json
import unittest
from contextlib import closing
from unittest.mock import patch

from pydantic import ValidationError

from library_claim import identity as identity
from library_claim.catalogue import CatalogueRequest,export_catalogue
from library_claim.packet import json_text
from library_claim.spine_reading import ReadingResponse,export_reading
from library_claim.tracking import TrackStore,digest
from tests import test_spine_reading as fixture


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ReadingTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.frames=self.f.fixture.store;self.root=self.f.root;self.store=identity.IdentityStore(self.frames)
        self.track=self.f.snapshot['observations'][0]['track_id'];self.prepare(1,'initial')

    def prepare(self,revision,name,extra=None):
        reading_request=self.f.request.model_copy(update=dict(expected_revision=revision))
        reading_dir=self.root/(name+'-reading');self.bundle=self.root/(name+'-catalogue')
        response=ReadingResponse(legibility='readable',uncertainty='',spans=[fixture.span(),fixture.span('MAYA SEN','author')]+(extra or []))
        self.reading=export_reading(self.frames,reading_request,reading_dir,response)
        request=CatalogueRequest(reading_result_sha256=digest((reading_dir/'reading_result.json').read_bytes()),
            title_span_ids=[s['id'] for s in self.reading['text_evidence'] if s['tentative_role']=='title'],
            author_span_ids=[s['id'] for s in self.reading['text_evidence'] if s['tentative_role']=='author'],limit=5)
        docs=[dict(key='OL1W',title='River Atlas',author_name=['Maya Sen'],edition_count=100),
              dict(key='OL2W',title='River Atlas',author_name=['Maya Sen'],edition_count=2),
              dict(key='OL3W',title='Another Title',author_name=['Maya Sen'],edition_count=1)]
        export_catalogue(self.frames,request,reading_dir,self.bundle,response_bytes=json_text(dict(docs=docs,numFound=3,numFoundExact=True,start=0)).encode())
        self.command=identity.IdentityCommand(command_id=name,sweep_id='fixture',expected_revision=revision,track_id=self.track,
            action='accept_work',catalogue_result_sha256=digest((self.bundle/'catalogue_result.json').read_bytes()),work_id='/works/OL2W',
            confirmed_span_ids=request.title_span_ids+request.author_span_ids,metadata=[],needs_appraisal=False,
            reviewer='Synthetic fixture reviewer',reason='Explicit fixture selection after confirming saved lettering')

    def book(self,snapshot): return next(b for b in snapshot['books'] if b['id']==self.track)

    def clear(self,revision=2,cid='clear'):
        return self.command.model_copy(update=dict(command_id=cid,expected_revision=revision,action='clear_identity',
            catalogue_result_sha256=None,work_id=None,confirmed_span_ids=[],metadata=[],needs_appraisal=False))

    def test_explicit_selection_ambiguous_work_only_and_restart(self):
        snapshot=self.store.apply(self.command,self.bundle);book=self.book(snapshot)
        self.assertEqual(snapshot['revision'],2);self.assertEqual(book['status'],'identified')
        self.assertEqual(book['title'],'RIVER ATLAS');self.assertEqual(book['author'],'MAYA SEN')
        self.assertEqual(book['isbn'],'');self.assertEqual(book['edition'],'');self.assertIsNone(book['id_confidence'])
        self.assertIsNone(book['replacement_cost']['amount']);self.assertEqual(snapshot['assigned_track_count'],3)
        track=next(t for t in snapshot['tracks'] if t['id']==self.track)
        self.assertEqual(track['bibliography']['work_id'],'/works/OL2W');self.assertIsNone(track['bibliography']['accepted_edition_id'])
        self.assertEqual(TrackStore(self.frames).snapshot('fixture'),snapshot)
        self.assertTrue(all(b['status']=='unidentified' for b in snapshot['books'] if b['id']!=self.track))

    def test_retry_after_restart_and_bundle_removal_does_not_increment(self):
        first=self.store.apply(self.command,self.bundle)
        self.assertEqual(identity.IdentityStore(self.frames).apply(self.command,self.root/'missing'),first)
        with self.assertRaisesRegex(ValueError,'different payload'):
            self.store.apply(self.command.model_copy(update=dict(reason='changed')),self.bundle)

    def test_physical_tracking_command_id_collision_rejected(self):
        with self.assertRaisesRegex(ValueError,'different payload'):
            self.store.apply(self.command.model_copy(update=dict(command_id='first')),self.bundle)

    def test_stale_revision_rejected(self):
        self.store.apply(self.command,self.bundle)
        with self.assertRaisesRegex(ValueError,'stale'): self.store.apply(self.command.model_copy(update=dict(command_id='stale')),self.bundle)

    def test_cross_track_and_cross_sweep_rejected_without_mutation(self):
        before=TrackStore(self.frames).snapshot('fixture')
        other=next(b['id'] for b in before['books'] if b['id']!=self.track)
        for update in [dict(track_id=other),dict(sweep_id='other')]:
            with self.subTest(update=update),self.assertRaises(ValueError): self.store.apply(self.command.model_copy(update=update),self.bundle)
        self.assertEqual(TrackStore(self.frames).snapshot('fixture'),before)

    def test_contradicted_or_absent_work_cannot_be_accepted(self):
        for work in ['/works/OL3W','/works/OL99W']:
            with self.subTest(work=work),self.assertRaises(ValueError): self.store.apply(self.command.model_copy(update=dict(work_id=work)),self.bundle)

    def test_all_selected_visible_spans_must_be_confirmed(self):
        with self.assertRaisesRegex(ValueError,'confirm exactly'):
            self.store.apply(self.command.model_copy(update=dict(confirmed_span_ids=[])),self.bundle)

    def test_reject_candidate_preserves_count_unknown_identity_and_evidence(self):
        command=self.command.model_copy(update=dict(action='reject_work',confirmed_span_ids=[]))
        snapshot=self.store.apply(command,self.bundle)
        self.assertEqual(self.book(snapshot)['status'],'unidentified');self.assertEqual(snapshot['assigned_track_count'],3)
        self.assertIn('/works/OL2W',next(t for t in snapshot['tracks'] if t['id']==self.track)['rejected_work_ids'])
        self.assertTrue(snapshot['identity_evidence'])

    def test_clear_preserves_ownership_and_physical_observations(self):
        accepted=self.store.apply(self.command,self.bundle)
        cmd=self.f.fixture.command().model_copy(update=dict(command_id='owned',expected_revision=2,operation='ownership',
            detection_result_sha256=None,decisions=[],track_id=self.track,owned=False))
        excluded=self.f.fixture.ledger.apply(cmd)
        cleared=self.store.apply(self.clear(3))
        self.assertFalse(self.book(cleared)['owned']);self.assertEqual(self.book(cleared)['title'],'')
        self.assertEqual(accepted['observations'],cleared['observations']);self.assertEqual(excluded['assigned_track_count'],cleared['assigned_track_count'])
        self.assertIn('totals',cleared['events'][-1]['invalidated_dependencies'])

    def test_reject_current_work_clears_all_metadata(self):
        self.store.apply(self.command,self.bundle);self.prepare(2,'reject-current')
        command=self.command.model_copy(update=dict(action='reject_work',confirmed_span_ids=[]))
        snapshot=self.store.apply(command,self.bundle);self.assertEqual(self.book(snapshot)['status'],'unidentified')

    def test_reject_different_work_keeps_accepted_identity(self):
        self.store.apply(self.command,self.bundle);self.prepare(2,'reject-other')
        command=self.command.model_copy(update=dict(action='reject_work',work_id='/works/OL1W',confirmed_span_ids=[]))
        self.assertEqual(self.book(self.store.apply(command,self.bundle))['title'],'RIVER ATLAS')

    def test_visible_isbn_publisher_and_edition_are_metadata_not_catalogue_edition(self):
        self.prepare(1,'metadata',[fixture.span('978-0-306-40615-7','isbn'),fixture.span('North Press','publisher'),fixture.span('Second edition','edition')])
        extra=[s for s in self.reading['text_evidence'] if s['tentative_role'] in ['isbn','publisher','edition']]
        metadata=[identity.MetadataDecision(field=s['tentative_role'],value=s['text'],source='visible_text',span_id=s['id'],claimant_statement=None) for s in extra]
        command=self.command.model_copy(update=dict(metadata=metadata,confirmed_span_ids=self.command.confirmed_span_ids+[s['id'] for s in extra]))
        snapshot=self.store.apply(command,self.bundle);book=self.book(snapshot)
        self.assertEqual(book['isbn'],'9780306406157');self.assertEqual(book['publisher'],'North Press');self.assertEqual(book['edition'],'Second edition')
        self.assertIsNone(next(t for t in snapshot['tracks'] if t['id']==self.track)['bibliography']['accepted_edition_id'])

    def test_visible_metadata_cannot_borrow_missing_or_different_text(self):
        self.prepare(1,'publisher',[fixture.span('North Press','publisher')]);span=self.reading['text_evidence'][-1]
        for span_id,value in [(span['id'],'South Press'),('missing','North Press'),(self.command.confirmed_span_ids[0],'RIVER ATLAS')]:
            metadata=[identity.MetadataDecision(field='publisher',value=value,source='visible_text',span_id=span_id,claimant_statement=None)]
            with self.subTest(span=span_id),self.assertRaises(ValueError):
                self.store.apply(self.command.model_copy(update=dict(metadata=metadata,confirmed_span_ids=self.command.confirmed_span_ids+[span_id])),self.bundle)

    def test_claimant_assertion_stays_distinct_and_first_edition_requires_appraisal(self):
        metadata=[identity.MetadataDecision(field='edition',value='First edition',source='claimant_assertion',span_id=None,claimant_statement='I say this is a signed first edition.')]
        command=self.command.model_copy(update=dict(metadata=metadata))
        with self.assertRaisesRegex(ValueError,'appraisal'): self.store.apply(command,self.bundle)
        snapshot=self.store.apply(command.model_copy(update=dict(needs_appraisal=True)),self.bundle);book=self.book(snapshot)
        self.assertEqual(book['status'],'needs_appraisal');self.assertEqual(book['field_evidence']['edition'],[])
        self.assertIsNone(book['used_value']['amount'])
        self.assertIn('claimant metadata requires verification',snapshot['review_queue'][-1]['reason'])

    def test_invalid_isbn_and_command_shapes_rejected(self):
        for value in ['9780306406158','123','９７８０３０６４０６１５７']:
            with self.subTest(value=value),self.assertRaises(ValueError): identity.isbn_value(value)
        self.assertEqual(identity.isbn_value('0-8044-2957-X'),'080442957X')
        for update in [dict(reviewer=' '),dict(action='clear_identity'),dict(confirmed_span_ids=['a','a']),dict(accepted_edition_id='/books/OL1M')]:
            with self.subTest(update=update),self.assertRaises(ValidationError): identity.IdentityCommand.model_validate({**self.command.model_dump(),**update})

    def test_catalogue_response_and_repinned_candidate_tampering_rejected(self):
        path=self.bundle/'catalogue_result.json';data=json.loads(path.read_bytes())
        data['candidates'][2]['disposition']='supported_candidate';path.write_text(json_text(data),encoding='utf-8')
        command=self.command.model_copy(update=dict(catalogue_result_sha256=digest(path.read_bytes()),work_id='/works/OL3W'))
        with self.assertRaisesRegex(ValueError,'projection'): self.store.apply(command,self.bundle)

    def test_changed_raw_catalogue_response_rejected(self):
        (self.bundle/'catalogue_response.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'hash mismatch'): self.store.apply(self.command,self.bundle)

    def test_concurrent_ownership_change_rejects_review_commit(self):
        original=identity.validated_bundle
        def changed(*args):
            result=original(*args)
            command=self.f.fixture.command().model_copy(update=dict(command_id='ownership-race',expected_revision=1,operation='ownership',
                detection_result_sha256=None,decisions=[],track_id=self.track,owned=False))
            self.f.fixture.ledger.apply(command)
            return result
        with patch.object(identity,'validated_bundle',side_effect=changed),self.assertRaisesRegex(ValueError,'changed during'):
            self.store.apply(self.command,self.bundle)
        snapshot=TrackStore(self.frames).snapshot('fixture')
        self.assertEqual(snapshot['revision'],2);self.assertFalse(self.book(snapshot)['owned'])
        self.assertEqual(self.book(snapshot)['status'],'unidentified')

    def test_reacceptance_replaces_prior_assertions_without_copying_metadata(self):
        metadata=[identity.MetadataDecision(field='publisher',value='Claimed Press',source='claimant_assertion',span_id=None,claimant_statement='I believe this publisher is Claimed Press.')]
        self.store.apply(self.command.model_copy(update=dict(metadata=metadata)),self.bundle)
        self.prepare(2,'replacement')
        snapshot=self.store.apply(self.command,self.bundle)
        self.assertEqual(self.book(snapshot)['publisher'],'');self.assertEqual(snapshot['revision'],3)
        self.assertEqual(snapshot['events'][-1]['previous_identity']['values']['publisher'],'Claimed Press')

    def test_archived_evidence_integrity_checked_after_restart(self):
        snapshot=self.store.apply(self.command,self.bundle);sha=snapshot['identity_evidence'][0]
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE identity_artifacts SET content=? WHERE sha256=?',(b'corrupt',sha));db.commit()
        with self.assertRaisesRegex(ValueError,'corrupted'): TrackStore(self.frames).snapshot('fixture')

    def test_transaction_rolls_back_if_projection_fails(self):
        before=TrackStore(self.frames).snapshot('fixture')
        with patch.object(TrackStore,'_snapshot',side_effect=[before,ValueError('projection failed')]),self.assertRaises(ValueError):
            self.store.apply(self.clear(1))
        self.assertEqual(TrackStore(self.frames).snapshot('fixture'),before)

    def test_evidence_export_reopens_exact_hashed_bytes(self):
        snapshot=self.store.apply(self.command,self.bundle);root=self.root/'export'
        self.store.export_evidence('fixture',root)
        for sha in snapshot['identity_evidence']: self.assertEqual(digest((root/sha).read_bytes()),sha)
        self.assertEqual(json.loads((root/'inventory.json').read_bytes()),snapshot)
        manifest=json.loads((root/'frame-manifest.json').read_bytes())
        for frame in manifest: self.assertEqual(digest((root/frame['path']).read_bytes()),frame['sha256'])
        self.assertIn('Catalogue edition identity and calibrated confidence remain unknown',(root/'report.html').read_text())


if __name__=='__main__': unittest.main()
