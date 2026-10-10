import json
import unittest
from unittest.mock import MagicMock,patch
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlparse

from library_claim import catalogue as cat
from library_claim.spine_reading import ReadingResponse,export_reading
from tests import test_spine_reading as fixture


def raw(docs=None,count=None):
    docs=docs if docs is not None else [dict(key='/works/OL1W',title='RIVER ATLAS',author_name=['MAYA SEN'],edition_count=20)]
    return json.dumps(dict(docs=docs,numFound=len(docs) if count is None else count,numFoundExact=True,start=0)).encode()


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ReadingTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.store=self.f.fixture.store;self.root=self.f.root;self.reading=self.root/'reading'
        self.make_reading()

    def make_reading(self,legibility='readable',extra=None):
        spans=[] if legibility=='unreadable' else [fixture.span(),fixture.span('MAYA SEN','author')]+(extra or [])
        result=export_reading(self.store,self.f.request,self.reading,ReadingResponse(legibility=legibility,spans=spans,uncertainty='' if legibility=='readable' else 'uncertain lettering'))
        self.request=cat.CatalogueRequest(reading_result_sha256=cat.digest((self.reading/'reading_result.json').read_bytes()),
            title_span_ids=[s['id'] for s in result['text_evidence'] if s['tentative_role']=='title'],
            author_span_ids=[s['id'] for s in result['text_evidence'] if s['tentative_role']=='author'],limit=5)

    def export(self,data=None,**kw):
        return cat.export_catalogue(self.store,self.request,self.reading,self.root/'catalogue',response_bytes=raw() if data is None else data,**kw)

    def test_supported_work_is_not_edition_or_identity_and_preserves_bytes(self):
        before=self.f.fixture.ledger.snapshot('fixture');result=self.export()
        self.assertEqual(result['outcome'],'supported_candidate')
        self.assertIsNone(result['accepted_work_id']);self.assertIsNone(result['accepted_edition_id'])
        self.assertIsNone(result['candidates'][0]['isbn'])
        self.assertEqual(before,self.f.fixture.ledger.snapshot('fixture'))
        self.assertEqual(cat.digest((self.root/'catalogue/reading_result.json').read_bytes()),self.request.reading_result_sha256)

    def test_first_candidate_wrong_author_does_not_win(self):
        docs=json.loads(raw())['docs'];wrong={**docs[0],'key':'OL2W','author_name':['Other Writer']}
        result=self.export(raw([wrong,docs[0]]))
        self.assertEqual([c['disposition'] for c in result['candidates']],['contradicted','supported_candidate'])
        self.assertIsNone(result['accepted_work_id'])

    def test_multiple_matches_remain_ambiguous_and_truncation_visible(self):
        docs=json.loads(raw())['docs'];result=self.export(raw(docs+[{**docs[0],'key':'OL2W'}],10))
        self.assertEqual(result['outcome'],'ambiguous');self.assertFalse(result['search_complete'])

    def test_missing_visible_author_requires_review(self):
        self.request=self.request.model_copy(update=dict(author_span_ids=[]))
        self.assertEqual(self.export()['outcome'],'needs_review')

    def test_partial_text_requires_review(self):
        self.reading=self.root/'partial';self.make_reading('partial')
        self.assertEqual(self.export()['outcome'],'needs_review')

    def test_volume_not_in_work_requires_review(self):
        self.reading=self.root/'volume';self.make_reading(extra=[fixture.span('VOL 2','volume')])
        result=self.export();self.assertEqual(result['outcome'],'needs_review')
        self.assertIn('visible volume not established by work record',result['candidates'][0]['reasons'])

    def test_unreadable_never_calls_catalogue(self):
        self.reading=self.root/'blank';self.make_reading('unreadable')
        with patch.object(cat.CatalogueClient,'fetch') as fetch:
            result=cat.export_catalogue(self.store,self.request,self.reading,self.root/'catalogue',live=True)
        fetch.assert_not_called();self.assertEqual(result['usage']['requests'],0);self.assertEqual(result['outcome'],'unavailable')

    def test_no_match_preserves_unknown(self):
        result=self.export(raw([]));self.assertEqual(result['outcome'],'no_match');self.assertIsNone(result['accepted_work_id'])

    def test_tampered_reading_crop_and_selected_role_rejected(self):
        for which in ['hash','crop','role']:
            with self.subTest(which=which):
                request=self.request
                if which=='hash': request=request.model_copy(update=dict(reading_result_sha256='0'*64))
                if which=='role': request=request.model_copy(update=dict(title_span_ids=request.author_span_ids,author_span_ids=[]))
                if which=='crop': (self.reading/'crop.png').write_bytes(b'changed')
                with self.assertRaises(ValueError): cat.load_reading(self.store,self.reading,request)

    def test_stale_source_rejected(self):
        command=self.f.fixture.command().model_copy(update=dict(command_id='ownership',expected_revision=1,operation='ownership',detection_result_sha256=None,decisions=[],track_id=self.f.snapshot['books'][0]['id'],owned=False))
        self.f.fixture.ledger.apply(command)
        with self.assertRaises(ValueError): self.export()

    def test_service_schema_rejects_bad_keys_duplicate_and_counts(self):
        docs=json.loads(raw())['docs']
        for data in [b'[]',b'{}',raw([{**docs[0],'key':'/books/OL1M'}]),raw(docs+docs),raw(docs,-1),raw(docs*6)]:
            with self.subTest(data=data),self.assertRaises(ValueError): cat.parse_search(data,5)

    def test_correction_during_lookup_rejects_stale_output(self):
        def changed(*args):
            command=self.f.fixture.command().model_copy(update=dict(command_id='ownership',expected_revision=1,operation='ownership',detection_result_sha256=None,decisions=[],track_id=self.f.snapshot['books'][0]['id'],owned=False))
            self.f.fixture.ledger.apply(command)
            return raw(),None,dict(requests=1)
        with patch.object(cat.CatalogueClient,'fetch',side_effect=changed),self.assertRaisesRegex(ValueError,'changed during'):
            cat.export_catalogue(self.store,self.request,self.reading,self.root/'catalogue',live=True)
        self.assertFalse((self.root/'catalogue').exists())

    def test_html_escapes_catalogue_labels(self):
        self.export(raw([dict(key='OL3W',title='<script>bad()</script>',author_name=['<img onerror=bad()>'])]))
        html=(self.root/'catalogue/report.html').read_text()
        self.assertNotIn('<script>bad()',html);self.assertIn('&lt;script&gt;',html)

    def test_stage_legibility_inconsistency_rejected_even_when_repinned(self):
        path=self.reading/'reading_result.json';data=json.loads(path.read_bytes())
        data['stage_result']['status']='partial';path.write_text(json.dumps(data),encoding='utf-8')
        request=self.request.model_copy(update=dict(reading_result_sha256=cat.digest(path.read_bytes())))
        with self.assertRaisesRegex(ValueError,'status differs'): cat.load_reading(self.store,self.reading,request)

    def test_normalization_and_literal_query_escape(self):
        self.assertEqual(cat.normalize('River—ATLAS'),cat.normalize('RIVER ATLAS'))
        self.assertNotEqual(cat.normalize('Volume 1'),cat.normalize('Volume 2'))
        query=parse_qs(urlparse(cat.query_url('A" OR *','B',5)).query)['q'][0]
        self.assertEqual(query,'title:"A\\" OR *" AND author:"B"')

    def test_cached_response_survives_restart_without_network(self):
        opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value=raw()
        url=cat.query_url('RIVER ATLAS','MAYA SEN',5)
        with patch.object(cat,'build_opener',return_value=opener):
            first=cat.CatalogueClient(self.store).fetch(url,5)
            second=cat.CatalogueClient(self.store).fetch(url,5)
        self.assertEqual(opener.open.call_count,1);self.assertEqual(first[0],second[0])
        self.assertEqual(second[2]['requests'],0);self.assertTrue(second[2]['cache_hit'])
        self.assertEqual(first[2]['retrieved_at'],second[2]['retrieved_at'])

    def test_429_persistent_cooldown_has_no_automatic_retry(self):
        opener=MagicMock();opener.open.side_effect=HTTPError('https://openlibrary.org',429,'quota',{'Retry-After':'120'},None)
        with patch.object(cat,'build_opener',return_value=opener):
            first=cat.CatalogueClient(self.store).fetch(cat.query_url('A','B',5),5)
            second=cat.CatalogueClient(self.store).fetch(cat.query_url('C','D',5),5)
        self.assertEqual(opener.open.call_count,1);self.assertTrue(first[1]['retryable'])
        self.assertEqual(second[2]['requests'],0);self.assertGreater(second[2]['retry_after_seconds'],100)

    def test_invalid_live_response_is_unavailable(self):
        opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value=b'[]'
        with patch.object(cat,'build_opener',return_value=opener):
            result=cat.export_catalogue(self.store,self.request,self.reading,self.root/'catalogue',live=True)
        self.assertEqual(result['outcome'],'unavailable');self.assertEqual(result['stage_result']['errors'][0]['code'],'catalogue_invalid_response')


if __name__=='__main__': unittest.main()
