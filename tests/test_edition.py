import json
import unittest
from contextlib import closing
from unittest.mock import MagicMock,patch

from library_claim import edition as ed
from library_claim.identity import MetadataDecision,IdentityStore
from library_claim.tracking import TrackStore,digest
from library_claim.packet import json_text
from tests import test_identity as fixture
from tests.test_spine_reading import span


def record():
    return dict(key='/books/OL1M',title='RIVER ATLAS',works=[dict(key='/works/OL2W')],
        isbn_10=[],isbn_13=['9780306406157'],publishers=['North Press'],physical_format='Paperback',edition_name='')


class EditionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.IdentityTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.frames=self.f.frames;self.root=self.f.root;self.track=self.f.track
        self.f.prepare(1,'isbn',[span('978-0-306-40615-7','isbn')])
        text=self.f.reading['text_evidence'][-1]
        metadata=MetadataDecision(field='isbn',value=text['text'],source='visible_text',span_id=text['id'],claimant_statement=None)
        self.work_command=self.f.command.model_copy(update=dict(metadata=[metadata],confirmed_span_ids=self.f.command.confirmed_span_ids+[text['id']]))
        self.before=self.f.store.apply(self.work_command,self.f.bundle)
        self.request=ed.EditionRequest(sweep_id='fixture',expected_revision=2,track_id=self.track,edition_id='/books/OL1M',limit=5,
            owned_physical_format='paperback',format_statement='Fixture reviewer declares this physical copy is paperback.')
        self.store=ed.EditionStore(self.frames);self.bundle=self.root/'edition'

    def lookup(self,row=None,request=None):
        return ed.export_edition(self.frames,request or self.request,self.bundle,response_bytes=json_text(row or record()).encode())

    def command(self,**update):
        base=dict(command_id='edition-review',sweep_id='fixture',expected_revision=2,track_id=self.track,action='accept_edition',
            edition_result_sha256=digest((self.bundle/'edition_result.json').read_bytes()),edition_id='/books/OL1M',
            reviewer='Fixture reviewer',reason='Explicit review of matching visible ISBN, work and declared physical binding')
        return ed.EditionCommand(**{**base,**update})

    def info(self,snapshot): return next(t['bibliography'] for t in snapshot['tracks'] if t['id']==self.track)

    def test_lookup_does_not_mutate_and_explicit_acceptance_does_not_borrow_fields(self):
        result=self.lookup();self.assertEqual(result['outcome'],'supported_candidate');self.assertIsNone(result['accepted_edition_id'])
        self.assertEqual(TrackStore(self.frames).snapshot('fixture'),self.before)
        snapshot=self.store.apply(self.command(),self.bundle);info=self.info(snapshot)
        self.assertEqual(info['accepted_edition_id'],'/books/OL1M');self.assertEqual(info['edition_status'],'catalogue_matched_reviewed')
        book=self.f.book(snapshot);self.assertEqual(book['publisher'],'');self.assertEqual(book['edition'],'')
        self.assertEqual(book['isbn'],'9780306406157');self.assertIsNone(book['replacement_cost']['amount'])
        self.assertEqual(info['edition_review']['format_source'],'claimant_declaration')

    def test_claimant_only_isbn_never_queries(self):
        self.f.store.apply(self.f.clear(2));self.f.prepare(3,'claimed')
        claim=MetadataDecision(field='isbn',value='9780306406157',source='claimant_assertion',span_id=None,claimant_statement='I think this ISBN is 9780306406157.')
        self.f.store.apply(self.f.command.model_copy(update=dict(metadata=[claim])),self.f.bundle)
        request=self.request.model_copy(update=dict(expected_revision=4))
        with patch.object(ed.EditionClient,'fetch') as fetch: result=ed.export_edition(self.frames,request,self.bundle,live=True)
        fetch.assert_not_called();self.assertEqual(result['outcome'],'unavailable');self.assertEqual(result['usage']['requests'],0)

    def test_work_title_isbn_and_binding_contradictions(self):
        cases=[dict(works=[dict(key='/works/OL99W')]),dict(works=[dict(key='/works/OL2W'),dict(key='/works/OL99W')]),
            dict(title='Another Book'),dict(isbn_13=['9780140328721']),dict(physical_format='Hardcover'),dict(physical_format='E-book')]
        _,info,isbn=ed.context(self.frames,self.request)
        for update in cases:
            with self.subTest(update=update):
                candidate=ed.evaluate_editions([{**record(),**update}],self.request,info,isbn)[0]
                self.assertEqual(candidate['disposition'],'contradicted')

    def test_missing_link_binding_and_invalid_catalogue_isbn_need_review(self):
        _,info,isbn=ed.context(self.frames,self.request)
        for update in [dict(works=[]),dict(physical_format=''),dict(isbn_10=['invalid']),dict(isbn_13=[])]:
            with self.subTest(update=update):
                candidate=ed.evaluate_editions([{**record(),**update}],self.request,info,isbn)[0]
                self.assertEqual(candidate['disposition'],'needs_review')
        result=self.lookup(request=self.request.model_copy(update=dict(owned_physical_format='unknown')))
        self.assertEqual(result['outcome'],'needs_review')

    def test_publisher_and_edition_statement_contradictions(self):
        _,info,isbn=ed.context(self.frames,self.request)
        info['values']['publisher']='Different Press';info['values']['edition']='Second edition'
        candidate=ed.evaluate_editions([record()],self.request,info,isbn)[0]
        self.assertEqual(candidate['disposition'],'contradicted');self.assertIn('catalogue edition statement missing for supplied metadata',candidate['reasons'])

    def test_page_ambiguity_and_incomplete_count(self):
        request=self.request.model_copy(update=dict(edition_id=None))
        page=dict(size=100,entries=[record(),{**record(),'key':'/books/OL2M'}])
        result=ed.export_edition(self.frames,request,self.bundle,response_bytes=json_text(page).encode())
        self.assertEqual(result['outcome'],'ambiguous');self.assertFalse(result['search_complete'])
        snapshot=self.store.apply(self.command(edition_id='/books/OL2M'),self.bundle)
        self.assertEqual(self.info(snapshot)['accepted_edition_id'],'/books/OL2M')

    def test_reject_unsupported_acceptance_and_unreturned_edition(self):
        self.lookup(row={**record(),'physical_format':'Kindle'})
        with self.assertRaisesRegex(ValueError,'not supported'): self.store.apply(self.command(),self.bundle)
        with self.assertRaisesRegex(ValueError,'not returned'): self.store.apply(self.command(edition_id='/books/OL99M'),self.bundle)

    def test_retry_restart_without_bundle_and_conflicting_id(self):
        self.lookup();command=self.command();snapshot=self.store.apply(command,self.bundle)
        self.assertEqual(ed.EditionStore(self.frames).apply(command,self.root/'missing'),snapshot)
        with self.assertRaisesRegex(ValueError,'different payload'): self.store.apply(command.model_copy(update=dict(reason='different')),self.bundle)

    def test_clear_retains_work_literal_metadata_ownership_and_appraisal(self):
        self.lookup();snapshot=self.store.apply(self.command(),self.bundle)
        clear=self.command(command_id='edition-clear',expected_revision=3,action='clear_edition',edition_result_sha256=None,edition_id=None)
        cleared=self.store.apply(clear);info=self.info(cleared)
        self.assertEqual(info['work_id'],'/works/OL2W');self.assertIsNone(info['accepted_edition_id'])
        self.assertEqual(self.f.book(cleared),self.f.book(snapshot));self.assertEqual(cleared['observations'],snapshot['observations'])

    def test_work_clear_invalidates_accepted_edition(self):
        self.lookup();self.store.apply(self.command(),self.bundle)
        cleared=self.f.store.apply(self.f.clear(3));self.assertIsNone(self.info(cleared));self.assertEqual(self.f.book(cleared)['isbn'],'')

    def test_stale_cross_track_and_cross_sweep_commands(self):
        self.lookup();command=self.command()
        for update in [dict(expected_revision=1),dict(track_id='missing'),dict(sweep_id='other')]:
            with self.subTest(update=update),self.assertRaises(ValueError): self.store.apply(command.model_copy(update=update),self.bundle)

    def test_repinned_projection_or_changed_response_rejected(self):
        self.lookup();path=self.bundle/'edition_result.json';result=json.loads(path.read_bytes())
        result['candidates'][0]['record']['physical_format']='Hardcover';path.write_text(json_text(result),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'differs'): self.store.apply(self.command(),self.bundle)
        (self.bundle/'edition_response.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'hash'): self.store.apply(self.command(),self.bundle)

    def test_schema_count_duplicate_wrong_endpoint_and_extra_command_fields(self):
        request=self.request.model_copy(update=dict(edition_id=None))
        for raw in [b'[]',b'{}',json_text(dict(size=True,entries=[])).encode(),json_text(dict(size=2,entries=[record(),record()])).encode()]:
            with self.subTest(raw=raw),self.assertRaises(ValueError): ed.parse_editions(raw,request)
        with self.assertRaises(ValueError): ed.parse_editions(json_text({**record(),'key':'/books/OL99M'}).encode(),self.request)
        with self.assertRaises(ValueError): ed.EditionClient(self.frames).fetch('https://evil.example/books/OL1M.json',self.request)

    def test_cache_survives_restart_and_search_shares_request_gate(self):
        opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value=json_text(record()).encode()
        url=ed.endpoint(self.request,'/works/OL2W')
        with patch('library_claim.catalogue.build_opener',return_value=opener):
            first=ed.EditionClient(self.frames).fetch(url,self.request)
            second=ed.EditionClient(self.frames).fetch(url,self.request)
            from library_claim.catalogue import CatalogueClient,query_url
            other=CatalogueClient(self.frames).fetch(query_url('A','B',5),5)
        self.assertEqual(opener.open.call_count,1);self.assertEqual(first[0],second[0]);self.assertTrue(second[2]['cache_hit'])
        self.assertEqual(second[2]['requests'],0);self.assertEqual(other[2]['requests'],0)

    def test_lookup_failure_is_unavailable_not_zero_editions(self):
        with patch.object(ed.EditionClient,'fetch',return_value=(None,dict(code='quota',reason='quota',retryable=True),dict(requests=1))):
            result=ed.export_edition(self.frames,self.request,self.bundle,live=True)
        self.assertEqual(result['outcome'],'unavailable');self.assertIsNone(result['catalogue_count'])

    def test_archived_edition_corruption_detected(self):
        self.lookup();snapshot=self.store.apply(self.command(),self.bundle);sha=snapshot['events'][-1]['saved_artifacts']['edition_response.json']
        with closing(self.frames._connect()) as db: db.execute('UPDATE identity_artifacts SET content=? WHERE sha256=?',(b'bad',sha));db.commit()
        with self.assertRaisesRegex(ValueError,'corrupted'): TrackStore(self.frames).snapshot('fixture')

    def test_html_escapes_remote_title(self):
        self.lookup(row={**record(),'title':'<script>bad()</script>','publishers':['<img onerror=bad()>']},
            request=self.request.model_copy(update=dict(format_statement='<script>claim()</script>')))
        html=(self.bundle/'report.html').read_text();self.assertNotIn('<script>bad()',html);self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>claim()',html);self.assertNotIn('<img onerror',html)

    def test_rejection_keeps_reviewed_work_and_no_edition(self):
        self.lookup();snapshot=self.store.apply(self.command(action='reject_edition'),self.bundle)
        self.assertIsNone(self.info(snapshot)['accepted_edition_id']);self.assertEqual(self.info(snapshot)['work_id'],'/works/OL2W')

    def test_lookup_during_correction_discards_stale_result(self):
        def changed(*args):
            self.f.store.apply(self.f.clear(2))
            return json_text(record()).encode(),None,dict(requests=1)
        with patch.object(ed.EditionClient,'fetch',side_effect=changed),self.assertRaisesRegex(ValueError,'changed during'):
            ed.export_edition(self.frames,self.request,self.bundle,live=True)
        self.assertFalse(self.bundle.exists())

    def test_review_race_rolls_back_without_edition_mutation(self):
        self.lookup();command=self.command();original=ed.validate_review
        def changed(*args):
            result=original(*args);self.f.store.apply(self.f.clear(2));return result
        with patch.object(ed,'validate_review',side_effect=changed),self.assertRaisesRegex(ValueError,'changed during'):
            self.store.apply(command,self.bundle)
        self.assertIsNone(self.info(TrackStore(self.frames).snapshot('fixture')))

    def test_appraisal_status_survives_edition_acceptance(self):
        self.f.store.apply(self.f.clear(2));self.f.prepare(3,'appraisal',[span('9780306406157','isbn')])
        text=self.f.reading['text_evidence'][-1]
        metadata=MetadataDecision(field='isbn',value=text['text'],source='visible_text',span_id=text['id'],claimant_statement=None)
        cmd=self.f.command.model_copy(update=dict(needs_appraisal=True,metadata=[metadata],confirmed_span_ids=self.f.command.confirmed_span_ids+[text['id']]))
        self.f.store.apply(cmd,self.f.bundle);self.request=self.request.model_copy(update=dict(expected_revision=4))
        self.lookup();snapshot=self.store.apply(self.command(expected_revision=4),self.bundle)
        self.assertEqual(self.f.book(snapshot)['status'],'needs_appraisal');self.assertIsNone(self.f.book(snapshot)['used_value']['amount'])

    def test_rejecting_current_edition_revokes_edition_but_not_work(self):
        self.lookup();self.store.apply(self.command(),self.bundle)
        request=self.request.model_copy(update=dict(expected_revision=3));root=self.root/'again'
        ed.export_edition(self.frames,request,root,response_bytes=json_text(record()).encode())
        command=self.command(command_id='reject-current',expected_revision=3,action='reject_edition',edition_result_sha256=digest((root/'edition_result.json').read_bytes()))
        snapshot=self.store.apply(command,root);self.assertIsNone(self.info(snapshot)['accepted_edition_id'])
        self.assertEqual(self.info(snapshot)['work_id'],'/works/OL2W')


if __name__=='__main__': unittest.main()
