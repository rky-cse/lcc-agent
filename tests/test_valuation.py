import copy
import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from library_claim.capture_store import FrameStore
from library_claim.models import Book
from library_claim.packet import json_text
from library_claim.valuation import (Market, PublicHTTPS, RetailCandidate, ValuationPolicy,
                                     ValuationRequest, ValuationStore, retailer_quote)
from tests import test_capture_server as server_fixture


def product(**updates):
    value = dict(**{'@type': 'Book', '@id': 'book'}, name='River Atlas',
                 author={'@type': 'Person', 'name': 'Maya Sen'}, isbn='9780306406157',
                 bookFormat='https://schema.org/Hardcover',
                 offers={'@type': 'Offer', 'price': '12.345', 'priceCurrency': 'INR',
                         'availability': 'https://schema.org/InStock',
                         'itemCondition': 'https://schema.org/NewCondition'})
    value.update(updates)
    return value


def html(value):
    return ('<html><script type="application/ld+json">' + json_text(value) + '</script></html>').encode()


def policy(**updates):
    value = dict(used_basis='used_asking', used_condition='Very good', fees='item_price_only',
                 rounding='half_even', max_quote_age_hours=24, allow_equivalent_replacement=False,
                 allow_foreign_fallback=False, fx_date='2026-10-09', max_fx_age_days=3)
    value.update(updates)
    return ValuationPolicy.model_validate(value)


def candidate(**updates):
    value = dict(track_id='track', target_country='IN', market_country='IN', url='https://seller.example/book',
                 product_id='book', offer_index=0, component='replacement', match_basis='exact_isbn',
                 physical_format='hardcover', reviewer='Synthetic reviewer',
                 market_statement='Synthetic test market declaration', equivalence_statement='')
    value.update(updates)
    return RetailCandidate.model_validate(value)


class Inventory:
    def __init__(self):
        self.revision = 2
        self.books = [Book(id='track', shelf='shelf', position=0, frame_ref='frame', status='identified',
                           title='River Atlas', author='Maya Sen', isbn='9780306406157').model_dump(mode='json')]

    def snapshot(self, sweep):
        return copy.deepcopy(dict(revision=self.revision, books=self.books))


class QuotesTests(unittest.TestCase):
    def setUp(self):
        self.book = Inventory().books[0]

    def quote(self, value=None, c=None, p=None):
        return retailer_quote(html(value or product()), c or candidate(), self.book, p or policy(),
                              datetime(2026, 10, 11).date())

    def test_literal_decimal_and_provenance(self):
        row = self.quote()
        self.assertEqual(row['amount'], '12.345')
        self.assertEqual(row['source_type'], 'new_physical')
        self.assertEqual(row['offer']['price'], row['literal_price'])
        self.assertEqual(row['market_basis'], 'explicit_reviewer_statement')

    def test_missing_malformed_and_nonphysical_fields_never_quote(self):
        cases = [dict(name='Another title'), dict(author=[]), dict(author={'name': 'Other author'}),
                 dict(isbn='9780140328721'), dict(isbn=''), dict(bookFormat='EBook'), dict(bookFormat='AudioBook'),
                 dict(bookFormat=''), dict(bookFormat='Paperback'), dict(**{'@id': 'other'}),
                 dict(offers=[]), dict(offers={'@type': 'AggregateOffer', 'lowPrice': 1})]
        for update in cases:
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.quote(product(**update))

    def test_offer_fields_not_assumed(self):
        cases = [dict(price=''), dict(price='1,000'), dict(price='$12'), dict(price='NaN'), dict(price='-1'),
                 dict(price='1e2'), dict(price=True), dict(priceCurrency='inr'), dict(priceCurrency=''),
                 dict(availability='OutOfStock'), dict(availability='PreOrder'), dict(availability=''),
                 dict(itemCondition=''), dict(itemCondition='UsedCondition'), dict(priceValidUntil='2026-10-01'),
                 dict(eligibleRegion='US')]
        for update in cases:
            value = product(); value['offers'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.quote(value)

    def test_true_zero_preserved(self):
        value=product();value['offers']['price']='0'
        self.assertEqual(self.quote(value)['amount'],'0')

    def test_source_region_and_validity_supported(self):
        value=product();value['offers'].update(eligibleRegion={'@type':'Country','identifier':'IN'},priceValidUntil='2026-10-11')
        self.assertEqual(self.quote(value)['currency'],'INR')

    def test_ambiguous_products_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):self.quote([product(),product()])
        raw=html(product()).replace(b'"price":"12.345"',b'"price":"1","price":"2"')
        with self.assertRaises(ValueError):retailer_quote(raw,candidate(),self.book,policy())

    def test_used_grade_is_literal_not_inferred(self):
        value=product();value['offers'].update(itemCondition='UsedCondition',description='Very good')
        q=self.quote(value,candidate(component='used'));self.assertEqual(q['source_type'],'used_asking')
        value['offers']['description']='Good'
        with self.assertRaises(ValueError):self.quote(value,candidate(component='used'))

    def test_sold_policy_rejects_asking_offer(self):
        value=product();value['offers'].update(itemCondition='UsedCondition',description='Very good')
        with self.assertRaisesRegex(ValueError,'completed sales'):
            self.quote(value,candidate(component='used'),policy(used_basis='used_sold'))

    def test_equivalent_requires_review_and_policy_and_is_replacement_only(self):
        self.book['isbn']=''
        c=candidate(match_basis='reviewed_equivalent_work',equivalence_statement='Same work in reviewed binding')
        with self.assertRaises(ValueError):self.quote(c=c)
        self.assertEqual(self.quote(c=c,p=policy(allow_equivalent_replacement=True))['match_basis'],'reviewed_equivalent_work')
        for change in [dict(equivalence_statement=''),dict(component='used')]:
            with self.assertRaises(ValueError):self.quote(c=c.model_copy(update=change),p=policy(allow_equivalent_replacement=True))

    def test_url_boundary(self):
        for url in ['http://seller.example/a','https://user:pass@seller.example/a','https://seller.example/a#b',
                    'https://seller.example:123/a','https://seller.example/a\n']:
            with self.subTest(url=url),self.assertRaises(ValueError):candidate(url=url)
        for update in [dict(reviewer=' '),dict(market_statement=' ')]:
            with self.assertRaises(ValueError):candidate(**update)
        with self.assertRaises(ValueError):policy(used_condition=' ')

    def test_private_and_mixed_dns_rejected_before_connection(self):
        for ips in [('127.0.0.1',),('192.168.1.1',),('::1',),('8.8.8.8','10.0.0.1')]:
            addresses=[(2,1,6,'',(ip,443)) for ip in ips]
            with patch('library_claim.valuation.socket.getaddrinfo',return_value=addresses),self.assertRaises(ValueError):
                PublicHTTPS()('https://seller.example/a')


class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.frames=FrameStore(Path(self.temp.name));self.inventory=Inventory()
        self.now=datetime(2026,10,11,tzinfo=timezone.utc);self.calls=[]
        self.data={'https://seller.example/book':html(product())}
        self.store=ValuationStore(self.frames,fetch=self.fetch,inventory=self.inventory,clock=self.clock)

    def clock(self):
        self.now+=timedelta(seconds=2)
        return self.now

    def fetch(self,url):
        self.calls.append(url)
        value=self.data[url]
        if isinstance(value,Exception):raise value
        return value

    def request(self,**updates):
        value=dict(run_id='run',sweep_id='sweep',expected_revision=2,track_ids=['track'],
                   markets=[dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold='1000')],
                   policy=policy().model_dump(mode='json'),candidates=[candidate().model_dump()],consent_fetch=True)
        value.update(updates)
        return ValuationRequest.model_validate(value)

    def row(self,result):return result['markets'][0]['rows'][0]

    def test_exact_decimal_total_immutable_identity_and_evidence(self):
        before=self.inventory.snapshot('sweep');r=self.store.run(self.request());row=self.row(r)
        self.assertEqual(row['replacement']['target_amount'],'12.34');self.assertIsNone(row['used'])
        self.assertEqual(r['markets'][0]['totals'],{'replacement':'12.34','used':'0'})
        self.assertEqual(before,self.inventory.snapshot('sweep'));self.assertFalse(r['packet_ready'])
        self.assertEqual(self.store.evidence(r['evidence_sha256'][0]),html(product()))
        self.assertTrue(r['usable_for_current_inventory']);self.assertFalse(r['market_search_complete'])

    def test_rounding_policy_and_non_cent_currency(self):
        p=policy(rounding='half_up').model_dump(mode='json')
        r=self.store.run(self.request(policy=p));self.assertEqual(self.row(r)['replacement']['target_amount'],'12.35')
        r=self.store.run(self.request(run_id='whole',policy=p,markets=[dict(country='IN',currency='INR',decimal_places=0,appraisal_threshold=1000)]))
        self.assertEqual(self.row(r)['replacement']['target_amount'],'12')

    def test_no_source_and_zero_are_distinct(self):
        r=self.store.run(self.request(candidates=[]));self.assertIsNone(self.row(r)['replacement'])
        value=product();value['offers']['price']='0';self.data[candidate().url]=html(value)
        r=self.store.run(self.request(run_id='zero'));self.assertEqual(self.row(r)['replacement']['target_amount'],'0.00')
        self.assertEqual(r['markets'][0]['priced_counts']['replacement'],1)

    def test_outage_timeout_invalid_response_retained_as_no_amount(self):
        for i,value in enumerate([TimeoutError(),OSError('sensitive debug'),b'',b'x'*(2*1024*1024+1),b'no offer']):
            self.data[candidate().url]=value
            # Fresh URL avoids intentionally cached successful bytes.
            url=f'https://seller.example/test-{i}';self.data[url]=value
            r=self.store.run(self.request(run_id=f'error{i}',candidates=[candidate(url=url).model_dump()]))
            self.assertIsNone(self.row(r)['replacement']);self.assertNotIn('sensitive debug',json.dumps(r))

    def test_idempotent_restart_no_network_and_payload_collision(self):
        req=self.request();r=self.store.run(req);calls=list(self.calls)
        restarted=ValuationStore(self.frames,fetch=lambda url:self.fail('retry fetched'),inventory=self.inventory,clock=self.clock)
        again=restarted.run(req);self.assertEqual(r['result_sha256'],again['result_sha256']);self.assertEqual(calls,self.calls)
        with self.assertRaisesRegex(ValueError,'different payload'):self.store.run(self.request(candidates=[]))

    def test_stale_before_and_after_appraisal_or_ownership_change(self):
        self.inventory.revision=3
        with self.assertRaisesRegex(ValueError,'stale'):self.store.run(self.request())
        self.assertEqual(self.calls,[]);self.inventory.revision=2
        r=self.store.run(self.request());self.inventory.revision=3
        self.inventory.books[0]['owned']=False
        r=self.store.get('run');self.assertTrue(r['stale']);self.assertFalse(r['usable_for_current_inventory'])
        self.assertEqual(self.row(r)['identity']['owned'],True)

    def test_expired_saved_quote_is_historical(self):
        self.store.run(self.request());self.now+=timedelta(days=2)
        r=self.store.get('run');self.assertTrue(r['quotes_expired']);self.assertFalse(r['usable_for_current_inventory'])

    def test_ineligible_tracks_never_fetch(self):
        for i,update in enumerate([dict(owned=False),dict(status='needs_appraisal'),dict(status='unidentified',title='')]):
            self.inventory.books[0].update(update)
            r=self.store.run(self.request(run_id=f'exclude{i}'));self.assertIsNone(self.row(r)['replacement'])
        self.assertEqual(self.calls,[])

    def test_threshold_has_no_amount_and_source_proof_is_retained(self):
        r=self.store.run(self.request(markets=[dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold='12')]))
        self.assertIsNone(self.row(r)['replacement']);self.assertIn('appraisal threshold',str(self.row(r)['findings']))
        self.assertEqual(len(r['evidence_sha256']),1)
        self.assertEqual(self.row(r)['status'],'needs_appraisal')
        self.assertEqual(self.row(r)['appraisal_quote']['amount'],'12.345')

    def test_high_used_quote_revokes_low_replacement_from_market_total(self):
        used=product();used['offers'].update(price='2000',itemCondition='UsedCondition',description='Very good')
        self.data['https://seller.example/used']=html(used)
        req=self.request(candidates=[candidate().model_dump(),candidate(component='used',url='https://seller.example/used').model_dump()])
        r=self.store.run(req);row=self.row(r)
        self.assertEqual(row['status'],'needs_appraisal')
        self.assertIsNone(row['replacement']);self.assertIsNone(row['used'])
        self.assertEqual(r['markets'][0]['totals']['replacement'],'0')
        self.assertEqual(self.inventory.books[0]['status'],'identified')

    def test_market_comparison_cardinality_and_identification_gates(self):
        markets=[dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold=1000),
                 dict(country='GB',currency='GBP',decimal_places=2,appraisal_threshold=100)]
        with self.assertRaises(ValueError):self.request(markets=markets)
        self.inventory.books=[dict(self.inventory.books[0],id=f't{i}') for i in range(10)]
        self.inventory.books[0]['status']='needs_appraisal'
        with self.assertRaisesRegex(ValueError,'identified'):
            self.store.run(self.request(markets=markets,track_ids=[f't{i}' for i in range(10)],candidates=[]))

    def test_expired_cache_fetches_fresh_quote_only_in_new_explicit_run(self):
        self.store.run(self.request());self.now+=timedelta(days=2)
        value=product();value['offers']['price']='15';self.data[candidate().url]=html(value)
        r=self.store.run(self.request(run_id='fresh'))
        self.assertEqual(self.row(r)['replacement']['target_amount'],'15.00');self.assertEqual(len(self.calls),2)
        self.assertEqual(self.row(self.store.get('run'))['replacement']['target_amount'],'12.34')

    def test_local_first_and_lowest_eligible(self):
        a=product();a['offers']['price']='20';b=product();b['offers']['price']='10'
        self.data['https://seller.example/a']=html(a);self.data['https://seller.example/b']=html(b)
        cs=[candidate(url='https://seller.example/a'),candidate(url='https://seller.example/b'),candidate(market_country='US',url='https://foreign.example/book')]
        r=self.store.run(self.request(policy=policy(allow_foreign_fallback=True).model_dump(mode='json'),candidates=[c.model_dump() for c in cs]))
        self.assertEqual(self.row(r)['replacement']['target_amount'],'10.00');self.assertEqual(len(self.calls),2)

    def foreign(self,fx=None):
        value=product();value['offers']['priceCurrency']='USD';value['offers']['price']='1.005'
        url='https://foreign.example/book';self.data[url]=html(value)
        self.data[candidate().url]=html(product(name='Wrong local book'))
        rate='https://api.frankfurter.dev/v2/rate/usd/inr?date=2026-10-09&providers=ecb'
        self.data[rate]=json_text(fx or dict(base='USD',quote='INR',date='2026-10-09',rate='80')).encode()
        return self.request(policy=policy(allow_foreign_fallback=True).model_dump(mode='json'),
                            candidates=[candidate().model_dump(),candidate(url=url,market_country='US').model_dump()])

    def test_foreign_fallback_dated_fx_and_literal_original(self):
        r=self.store.run(self.foreign());q=self.row(r)['replacement']
        self.assertEqual(q['target_amount'],'80.40');self.assertEqual(q['amount'],'1.005')
        self.assertTrue(q['converted']);self.assertTrue(q['foreign_market'])
        self.assertEqual(q['fx']['rate'],'80');self.assertEqual(len(r['evidence_sha256']),3)

    def test_foreign_requires_local_attempt_and_policy(self):
        req=self.foreign()
        for i,update in enumerate([dict(candidates=req.candidates[1:]),dict(policy=policy(allow_foreign_fallback=False))]):
            req2=req.model_copy(update=dict(run_id=f'blocked{i}',**update))
            r=self.store.run(req2);self.assertIsNone(self.row(r)['replacement'])
        self.assertFalse(any('foreign.example' in url for url in self.calls))

    def test_bad_fx_pair_date_and_rate_excluded_with_evidence(self):
        for i,fx in enumerate([dict(base='EUR',quote='INR',date='2026-10-09',rate=80),
                             dict(base='USD',quote='INR',date='2026-09-01',rate=80),
                             dict(base='USD',quote='INR',date='2026-10-10',rate=80),
                             dict(base='USD',quote='INR',date='2026-10-09',rate=0)]):
            req=self.foreign(fx).model_copy(update=dict(run_id=f'fx{i}',policy=policy(allow_foreign_fallback=True,max_quote_age_hours=i+1)))
            r=self.store.run(req);self.assertIsNone(self.row(r)['replacement']);self.assertEqual(len(r['evidence_sha256']),3)

    def test_local_currency_mismatch_is_not_converted(self):
        value=product();value['offers']['priceCurrency']='USD';self.data[candidate().url]=html(value)
        r=self.store.run(self.request());self.assertIsNone(self.row(r)['replacement']);self.assertEqual(len(self.calls),1)

    def test_cache_isolated_by_locale_and_policy(self):
        self.store.run(self.request());self.store.run(self.request(run_id='cached'));self.assertEqual(len(self.calls),1)
        self.store.run(self.request(run_id='country',markets=[dict(country='US',currency='USD',decimal_places=2,appraisal_threshold=1000)],
                                    candidates=[candidate(target_country='US',market_country='US').model_dump()]))
        self.assertEqual(len(self.calls),2)
        self.store.run(self.request(run_id='grade',policy=policy(used_condition='Good').model_dump(mode='json')))
        self.assertEqual(len(self.calls),3)

    def test_evidence_and_result_corruption_block_replay(self):
        r=self.store.run(self.request())
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE valuation_evidence SET content=?',(b'corrupt',));db.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.store.get('run')
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE valuation_runs SET result=?',(b'{}',));db.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.store.get('run')

    def test_cross_sweep_and_interrupted_run_no_price(self):
        self.store.run(self.request())
        with self.assertRaises(KeyError):self.store.get('run','other')
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE valuation_runs SET status=?,result=NULL,sha=NULL',('interrupted',));db.commit()
        r=self.store.run(self.request());self.assertEqual(r['status'],'interrupted');self.assertNotIn('markets',r)

    def test_two_markets_reprice_same_ten_tracks_independently(self):
        self.inventory.books=[dict(self.inventory.books[0],id=f't{i}') for i in range(10)]
        value=product();value['offers'].update(price='7',priceCurrency='GBP')
        self.data['https://british.example/book']=html(value)
        candidates=[candidate(track_id=f't{i}',target_country=country,market_country=country,url=url).model_dump()
                    for i in range(10) for country,url in [('IN',candidate().url),('GB','https://british.example/book')]]
        r=self.store.run(self.request(track_ids=[f't{i}' for i in range(10)],candidates=candidates,
                    markets=[dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold=1000),
                             dict(country='GB',currency='GBP',decimal_places=2,appraisal_threshold=100)]))
        self.assertEqual(r['markets'][0]['totals']['replacement'],'123.40')
        self.assertEqual(r['markets'][1]['totals']['replacement'],'70.00')
        self.assertEqual([x['track_id'] for x in r['markets'][0]['rows']],[x['track_id'] for x in r['markets'][1]['rows']])
        self.assertEqual(len(self.calls),2);self.assertTrue(all(not x['replacement']['converted'] for m in r['markets'] for x in m['rows']))

    def test_selection_contracts_and_future_date(self):
        for updates in [dict(track_ids=['track','track']),dict(consent_fetch=False),dict(candidates=[candidate(track_id='other').model_dump()]),
                        dict(markets=[dict(country='GB',currency='GBP',decimal_places=2,appraisal_threshold=100)])]:
            with self.assertRaises(ValueError):self.request(**updates)
        with self.assertRaises(ValueError):self.store.run(self.request(policy=policy(fx_date='2027-01-01').model_dump(mode='json')))
        with self.assertRaises(ValueError):self.store.run(self.request(track_ids=['other'],candidates=[]))


class ValuationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=server_fixture.ServerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.inventory=Inventory();self.service=self.f.app.state.valuations
        self.service.inventory=self.inventory;self.service.fetch=lambda url:html(product())
        self.path=f'/api/sweeps/{self.f.sweep["id"]}/valuations'

    def request(self):
        return dict(run_id='http',sweep_id=self.f.sweep['id'],expected_revision=2,track_ids=['track'],
                    markets=[dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold=1000)],
                    policy=policy().model_dump(mode='json'),candidates=[candidate().model_dump()],consent_fetch=True)

    def test_page_assets_and_explicit_fetch_and_saved_evidence(self):
        for path in ['/valuation','/assets/valuation.mjs']:
            self.assertEqual(self.f.client.get(path).status_code,200)
        r=self.f.client.post(self.path,json=self.request(),headers=self.f.headers);self.assertEqual(r.status_code,200,r.text)
        saved=r.json();read=self.f.client.get(self.path+'/http');self.assertEqual(read.status_code,200)
        digest=saved['evidence_sha256'][0]
        r=self.f.client.get(self.path+'/http/evidence/'+digest)
        self.assertEqual(r.content,html(product()));self.assertIn('text/plain',r.headers['content-type'])
        self.assertEqual(self.f.client.get(self.path+'/http/evidence/'+'a'*64).status_code,404)

    def test_http_boundaries_and_stale_result(self):
        self.assertEqual(self.f.client.post(self.path,json=self.request()).status_code,403)
        invalid=self.request();invalid['consent_fetch']=False
        self.assertEqual(self.f.client.post(self.path,json=invalid,headers=self.f.headers).status_code,422)
        wrong=self.request();wrong['markets'][0].update(country='US',currency='USD');wrong['candidates']=[]
        self.assertEqual(self.f.client.post(self.path,json=wrong,headers=self.f.headers).status_code,422)
        self.assertEqual(self.f.client.post(self.path,content=b'x'*(128*1024+1),headers=self.f.headers).status_code,413)
        self.f.client.post(self.path,json=self.request(),headers=self.f.headers)
        self.inventory.revision+=1
        self.assertTrue(self.f.client.get(self.path+'/http').json()['stale'])
        self.assertEqual(self.f.client.get('/api/sweeps/other/valuations/http').status_code,404)
