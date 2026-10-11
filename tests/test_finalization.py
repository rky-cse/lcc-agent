import copy
import io
import json
import unittest
import zipfile
from contextlib import closing
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch

from library_claim.finalization import Finalizer, FinalizationRequest
from library_claim.final_audit import money_quote, audit_packet, spoken_summary
from library_claim.contents import ContentsCommand
from library_claim.valuation import sha
from tests import test_capture_server as capture_fixture
from tests import test_contents as item_fixture
from tests import test_valuation as book_fixture


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.f=capture_fixture.ServerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.frame=self.f.upload().json()['frame'];self.sweep=self.f.sweep['id']
        self.finalizer=Finalizer(self.f.app.state.sessions.store)
        self.f.app.state.sessions.end(self.sweep,'end',0)
        capture=self.f.app.state.sessions.snapshot(self.sweep)
        self.now=datetime.fromisoformat(capture['ended_at'])+timedelta(seconds=1)
        self.finalizer.clock=lambda:self.now
        self.request=FinalizationRequest(run_id='final-one',sweep_id=self.sweep,expected_book_revision=0,expected_contents_revision=0,
            deadline_at=self.now+timedelta(seconds=30),book_valuation_runs=[],item_valuation_runs=[],area_run_id=None,book_measurements=[],
            aggregation=dict(currency_decimal_places=2,shelf_run_basis='sum_spine_thickness',exclusion_basis='missing_any_component'),max_archive_bytes=5_000_000)

    def add_item(self,key='chair'):
        return self.finalizer.contents.apply(ContentsCommand.model_validate(dict(command_id='add-'+key,sweep_id=self.sweep,
            expected_revision=self.finalizer.contents.snapshot(self.sweep)['revision'],operation='observe',item_id=key,
            reviewer='Synthetic reviewer',reason='Reviewed test object',frame_ref=self.frame['id'],frame_sha256=self.frame['sha256'],bounds_px=[20,20,400,800],
            new_owned=True,labels=item_fixture.labels())))

    def test_empty_frozen_archive_is_partial_portable_and_deterministic(self):
        first=self.finalizer.run(self.request)
        self.assertTrue(first['packet_ready']);packet=first['packet'];self.assertEqual(packet['packet_status'],'partial')
        self.assertEqual(packet['totals']['book_count'],0);self.assertTrue(packet['audit']['passed'])
        self.assertEqual(first,self.finalizer.run(self.request))
        a=self.finalizer.archive('final-one',self.sweep);self.assertEqual(a,self.finalizer.archive('final-one',self.sweep))
        with zipfile.ZipFile(io.BytesIO(a)) as archive:
            data=json.loads(archive.read('claim_packet.json'),parse_float=Decimal)
            self.assertEqual(spoken_summary(data).encode(),archive.read('spoken-summary.txt'))
            manifest=json.loads(archive.read('artifact-manifest.json'))
            for entry in manifest['files']:self.assertEqual(sha(archive.read(entry['path'])),entry['sha256'])
            self.assertEqual(archive.read(self.frame['path']),self.f.data)
            self.assertIn(b'frozen-inputs.json',archive.read('report.html'))

    def test_inventory_changes_after_publish_cannot_mutate_packet(self):
        first=self.finalizer.run(self.request);self.add_item()
        self.assertEqual(first,self.finalizer.get('final-one',self.sweep))
        self.assertEqual(first,self.finalizer.run(self.request))
        self.request.run_id='another'
        with self.assertRaisesRegex(ValueError,'stale finalization'):self.finalizer.run(self.request)

    def test_stale_before_freeze_and_conflicting_payload_rejected(self):
        self.request.expected_contents_revision=10
        with self.assertRaisesRegex(ValueError,'stale'):self.finalizer.run(self.request)
        self.request.expected_contents_revision=0;self.finalizer.run(self.request);self.request.max_archive_bytes=6_000_000
        with self.assertRaisesRegex(ValueError,'different payload'):self.finalizer.run(self.request)

    def test_closed_capture_and_deadline_required(self):
        self.request.deadline_at=self.now-timedelta(days=1)
        with self.assertRaisesRegex(ValueError,'precede capture end'):self.finalizer.run(self.request)
        with patch.object(self.finalizer.capture,'snapshot',return_value={'status':'capturing'}):
            with self.assertRaisesRegex(ValueError,'end capture'):self.finalizer.run(self.request)

    def test_pending_jobs_wait_then_publish_partial_at_deadline(self):
        job=dict(status='running',worker_active=True,input={'job_id':'pending'},artifacts={})
        with patch.object(self.finalizer.jobs,'list',return_value=[job]):
            waiting=self.finalizer.run(self.request);self.assertFalse(waiting['packet_ready']);self.assertEqual(waiting['status'],'waiting_for_drain')
            self.now=self.request.deadline_at
            final=self.finalizer.run(self.request);self.assertTrue(final['packet']['finalization']['deadline_partial'])
        self.assertTrue(any('deadline' in r['reason'] for r in final['packet']['review_queue']))

    def test_drained_retry_publishes_without_deadline(self):
        with patch.object(self.finalizer.jobs,'list',return_value=[dict(status='queued',input={'job_id':'pending'},artifacts={})]):self.finalizer.run(self.request)
        result=self.finalizer.run(self.request);self.assertFalse(result['packet']['finalization']['deadline_partial'])

    def test_selected_running_valuation_waits_for_deadline(self):
        self.request.book_valuation_runs=['running-price']
        run=dict(run_id='running-price',sweep_id=self.sweep,status='running')
        with patch.object(self.finalizer.values,'get',return_value=run):
            self.assertFalse(self.finalizer.run(self.request)['packet_ready'])
            self.now=self.request.deadline_at;result=self.finalizer.run(self.request)
        self.assertTrue(result['packet']['coverage']['recognition_drained']);self.assertTrue(result['packet']['finalization']['deadline_partial'])

    def test_result_and_portable_artifact_tampering_fail(self):
        self.finalizer.run(self.request)
        with closing(self.finalizer.frames._connect()) as db:
            db.execute('UPDATE final_files SET content=? WHERE run_id=? AND path=?',(b'corrupted','final-one','spoken-summary.txt'));db.commit()
        with self.assertRaisesRegex(ValueError,'artifact hash'):self.finalizer.get('final-one')

    def test_source_tampering_after_freeze_does_not_change_snapshot(self):
        first=self.finalizer.run(self.request)
        path=self.finalizer.frames.root/self.frame['path'];path.write_bytes(b'bad-original')
        self.assertEqual(first,self.finalizer.get('final-one'));self.assertTrue(self.finalizer.archive('final-one'))

    def test_publication_failure_resume_uses_frozen_inputs(self):
        with patch.object(self.finalizer,'publish',side_effect=OSError('simulated interruption')):
            with self.assertRaises(OSError):self.finalizer.run(self.request)
        self.assertEqual(self.finalizer.get('final-one')['status'],'frozen')
        self.add_item();published=self.finalizer.run(self.request)
        self.assertEqual(published['packet']['items'],[])

    def test_exact_item_price_reaudited_without_network(self):
        self.add_item();self.request.expected_contents_revision=1
        prices=self.f.app.state.contents_prices;prices.fetch=lambda url:item_fixture.html(item_fixture.product())
        prices.clock=lambda:self.now
        request=item_fixture.ItemValuationRequest.model_validate(dict(run_id='item-price',sweep_id=self.sweep,expected_revision=1,item_ids=['chair'],
            market=dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold='1000'),policy=item_fixture.policy(fx_date=self.now.date().isoformat()).model_dump(mode='json'),
            candidates=[item_fixture.candidate(item_id='chair').model_dump()],consent_fetch=True))
        prices.run(request);self.request.item_valuation_runs=['item-price']
        with patch('library_claim.valuation.PublicHTTPS.__call__',side_effect=AssertionError('network called')):
            result=self.finalizer.run(self.request)
        self.assertEqual(result['packet']['totals']['items_replacement_cost_low'],Decimal('10.00'),result['packet']['review_queue'])
        self.assertEqual(result['packet']['items'][0]['status'],'priced')

    def test_independent_arithmetic_detects_changed_total(self):
        packet=self.finalizer.run(self.request)['packet'];packet['totals']['books_replacement_cost']=Decimal(99)
        with self.assertRaisesRegex(ValueError,'total audit'):audit_packet(packet)

    def test_manifest_mismatch_is_detected_even_with_updated_blob_hash(self):
        self.finalizer.run(self.request)
        with closing(self.finalizer.frames._connect()) as db:
            db.execute('UPDATE final_files SET content=?,sha=? WHERE run_id=? AND path=?',(b'{}',sha(b'{}'),'final-one','frozen-inputs.json'));db.commit()
        with self.assertRaisesRegex(ValueError,'manifest hash'):self.finalizer.get('final-one')

    def test_unpriced_owned_objects_stay_in_inventory(self):
        self.add_item();self.request.expected_contents_revision=1
        result=self.finalizer.run(self.request)['packet'];self.assertEqual(len(result['items']),1)
        self.assertEqual(result['totals']['excluded_from_totals'],1);self.assertIsNone(result['items'][0]['replacement_cost']['low'])

    def test_nonowned_items_retained_as_exclusions(self):
        self.add_item()
        self.finalizer.contents.apply(ContentsCommand.model_validate(dict(command_id='exclude',sweep_id=self.sweep,expected_revision=1,operation='ownership',item_id='chair',reviewer='Reviewer',reason='Not owned',new_owned=False)))
        self.request.expected_contents_revision=2;packet=self.finalizer.run(self.request)['packet']
        self.assertEqual(packet['items'],[]);self.assertEqual(packet['ownership_exclusions'][0]['id'],'chair')

    def test_integration_preserves_m09_metric_and_imperial_results(self):
        area=dict(stale=False,status='partial',room=dict(floor_area_m2=12,scale_method='calibrated_multiview_reference'),
            measurements=[dict(id='floor-proof',ref_id='room',field='floor_area_m2',value=12,unit='m2',frame_refs=[self.frame['id']],scale_method='calibrated_multiview_reference',derivation='Controlled integration fixture')],
            geometry=dict(area_units=dict(floor_area_m2=dict(m2=12,ft2=Decimal('129.166925')))))
        # Exercise the bridge separately: native hash/scale gates are tested by M09.
        self.finalizer.run(self.request)
        files={p:raw for p,raw,digest in self.finalizer.files('final-one')}
        frozen=json.loads(files['frozen-inputs.json'],parse_float=Decimal);frozen['area']=area
        packet=self.finalizer.build(frozen,files,self.request)
        self.assertEqual(packet['room']['floor_area_m2'],12);self.assertEqual(packet['room']['floor_area_ft2'],Decimal('129.166925'))

    def test_m08_geometry_is_recomputed_and_bridge_retains_unknown_depth(self):
        f=item_fixture.ContentsTests('test_reviewed_fields_unknown_dimensions_and_restart');f.setUp();self.addCleanup(f.doCleanups)
        f.measure();finalizer=Finalizer(f.frames);finalizer.capture.start('IN','INR','fixture');capture=finalizer.capture.end('fixture','end',0)
        request=self.request.model_copy(update=dict(run_id='dimensions',sweep_id='fixture',expected_contents_revision=2,deadline_at=datetime.fromisoformat(capture['ended_at'])+timedelta(seconds=30)))
        packet=finalizer.run(request)['packet'];item=packet['items'][0]
        self.assertEqual(item['dimensions_cm']['w'],Decimal('2.500'));self.assertEqual(item['dimensions_cm']['h'],Decimal('23.000'));self.assertIsNone(item['dimensions_cm']['d'])
        self.assertEqual(len([m for m in packet['measurements'] if m['ref_id']=='item']),2)

    def test_complete_m09_run_is_portable_with_native_artifacts(self):
        from tests import test_area_store as area_fixture
        f=area_fixture.AreaStoreTests('test_durable_result_replay_and_measurement_evidence');f.setUp();self.addCleanup(f.doCleanups)
        f.run_area();finalizer=Finalizer(f.fixture.store);finalizer.capture.start('IN','INR','fixture');capture=finalizer.capture.end('fixture','end',0)
        request=self.request.model_copy(update=dict(run_id='geometry-final',sweep_id='fixture',area_run_id='area-one',deadline_at=datetime.fromisoformat(capture['ended_at'])+timedelta(seconds=30)))
        packet=finalizer.run(request)['packet'];self.assertEqual(packet['room']['wall_area_m2'],Decimal('36.400000'))
        with zipfile.ZipFile(io.BytesIO(finalizer.archive('geometry-final'))) as archive:
            self.assertIn('geometry/sparse/0/cameras.bin',archive.namelist())
            self.assertEqual(len([p for p in archive.namelist() if p.startswith('geometry/images/')]),3)

    def test_book_quote_reparse_and_both_components(self):
        book=book_fixture.Inventory().books[0];book['frame_ref']=self.frame['id'];book['field_evidence']={'title':[self.frame['id']],'author':[self.frame['id']],'isbn':[self.frame['id']]}
        snapshot=self.finalizer.books.snapshot(self.sweep);snapshot.update(revision=2,books=[book])
        inventory=book_fixture.Inventory();inventory.books=[book]
        values=book_fixture.ValuationStore(self.finalizer.frames,inventory=inventory,fetch=lambda url:book_fixture.html(book_fixture.product()),clock=lambda:self.now)
        req=book_fixture.ValuationRequest.model_validate(dict(run_id='book-price',sweep_id=self.sweep,expected_revision=2,track_ids=['track'],
            markets=[dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold='1000')],policy=book_fixture.policy(fx_date=self.now.date().isoformat()).model_dump(mode='json'),
            candidates=[book_fixture.candidate().model_dump()],consent_fetch=True))
        values.run(req);self.request.expected_book_revision=2;self.request.book_valuation_runs=['book-price']
        with patch.object(self.finalizer.books,'snapshot',return_value=snapshot):
            self.finalizer.values.inventory=self.finalizer.books
            result=self.finalizer.run(self.request)
        self.assertEqual(result['packet']['totals']['books_replacement_cost'],Decimal('12.34'),result['packet']['review_queue'])
        self.assertIsNone(result['packet']['books'][0]['used_value']['amount'])
        # Distinct owned physical copies can use one identical saved offer.
        second=copy.deepcopy(book);second['id']='copy';inventory.books=[book,second];snapshot['books']=[book,second]
        data=req.model_dump(mode='json');data.update(run_id='copies-price',track_ids=['track','copy'],candidates=[book_fixture.candidate().model_dump(),book_fixture.candidate(track_id='copy').model_dump()])
        values.run(book_fixture.ValuationRequest.model_validate(data))
        self.request.run_id='copies-final';self.request.book_valuation_runs=['copies-price']
        with patch.object(self.finalizer.books,'snapshot',return_value=snapshot):copies=self.finalizer.run(self.request)['packet']
        self.assertEqual(copies['totals']['book_count'],2);self.assertEqual(copies['totals']['books_replacement_cost'],Decimal('24.68'))
        self.assertEqual(len(copies['quote_manifest']),1)

    def test_expired_valuation_stays_unpriced_with_review(self):
        self.add_item();self.request.expected_contents_revision=1
        prices=self.f.app.state.contents_prices;prices.fetch=lambda url:item_fixture.html(item_fixture.product());prices.clock=lambda:self.now
        req=item_fixture.ItemValuationRequest.model_validate(dict(run_id='expired',sweep_id=self.sweep,expected_revision=1,item_ids=['chair'],
            market=dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold='1000'),policy=item_fixture.policy(fx_date=self.now.date().isoformat()).model_dump(mode='json'),
            candidates=[item_fixture.candidate(item_id='chair').model_dump()],consent_fetch=True))
        prices.run(req);self.now+=timedelta(days=2);self.request.item_valuation_runs=['expired']
        result=self.finalizer.run(self.request)
        self.assertEqual(result['packet']['totals']['items_replacement_cost_low'],0)
        self.assertTrue(any('expired' in r['reason'] for r in result['packet']['review_queue']))

    def test_book_measurement_cannot_target_absent_track(self):
        from tests import test_planar_measurement as planar_fixture
        from library_claim.planar import MeasurementRequest
        m=MeasurementRequest.model_validate(planar_fixture.fixture(self.finalizer.frames.get(self.frame['id'])))
        self.request.book_measurements=[m]
        with self.assertRaisesRegex(ValueError,'physical observation'):self.finalizer.run(self.request)

    def test_http_scope_origin_schema_and_archive(self):
        client=self.f.client;path=f'/api/sweeps/{self.sweep}/finalizations';body=self.request.model_dump(mode='json')
        for url in ['/packet','/api/finalization/schema','/assets/packet.mjs','/assets/packet_core.mjs']:self.assertEqual(client.get(url).status_code,200)
        self.assertEqual(client.post(path,json=body).status_code,403)
        self.assertEqual(client.post('/api/sweeps/other/finalizations',json=body,headers=self.f.headers).status_code,422)
        result=client.post(path,json=body,headers=self.f.headers);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(client.get(path+'/final-one/archive').status_code,200)
        self.assertEqual(client.get(path+'/final-one/summary').status_code,200)
        self.assertEqual(client.get('/api/sweeps/other/finalizations/final-one').status_code,404)
        with patch.object(self.f.app.state.finalizer,'run',side_effect=OSError('private path should not leak')):
            failure=client.post(path,json=body,headers=self.f.headers)
            self.assertEqual(failure.status_code,503);self.assertIn('final run ID',failure.text);self.assertNotIn('private path',failure.text)


class FXAuditTests(unittest.TestCase):
    def test_dated_fx_and_rounding_with_saved_evidence(self):
        q=dict(amount='10.005',currency='USD',market_country='US',target_currency='INR',converted=True,target_amount='20.01',
            fx=dict(evidence_sha256='fx',rate='2',date='2026-10-09',source_currency='USD',target_currency='INR'))
        market=dict(country='IN',currency='INR',decimal_places=2);policy=dict(fx_date='2026-10-09',max_fx_age_days=0,rounding='half_even',allow_foreign_fallback=True)
        evidence=lambda key:b'{"base":"USD","quote":"INR","rate":2,"date":"2026-10-09"}'
        self.assertEqual(money_quote(q,market,policy,evidence),Decimal('20.01'))
        for update in [dict(target_amount='99'),dict(converted=False),dict(target_currency='EUR')]:
            with self.assertRaises(ValueError):money_quote(q|update,market,policy,evidence)
        with self.assertRaises(ValueError):money_quote(q,market,policy,lambda key:b'{"base":"EUR","quote":"INR","rate":2,"date":"2026-10-09"}')

    def test_foreign_same_currency_requires_authorized_fallback(self):
        quote=dict(amount='10',currency='USD',market_country='CA',target_currency='USD',converted=False,target_amount='10.00')
        with self.assertRaisesRegex(ValueError,'fallback not authorized'):money_quote(quote,dict(country='US',currency='USD',decimal_places=2),dict(allow_foreign_fallback=False),lambda key:b'')


if __name__=='__main__':unittest.main()
