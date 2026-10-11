import copy
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from library_claim.evaluation import (freeze, FrozenTruth, Assessment, Timing, Stage, Cost,
                                    canonical, digest, evaluate, load_archive, write_results)
from library_claim.evaluation import second_locale_from_archive
from library_claim.delivery import load_results, Delivery, check, recompute_result
from library_claim.models import Book, Item
from tests import test_finalization as final_fixture
from tests import test_valuation as book_fixture


def inputs():
    now = datetime(2026,10,11,tzinfo=timezone.utc)
    books = [dict(id='T'+str(i),location='shelf '+str(i//30)+' position '+str(i%30),owned=True,legible=True,
                  title='Title '+str(i),legibility_basis='Independent pre-run spine viewing',spine_sample=i<20,
                  height_cm=20 if i<20 else None,thickness_cm=2 if i<20 else None,measurement_evidence='Tape sheet' if i<20 else '',
                  price_sample=i<15,prices=[dict(component=c,availability='available',amount=100,
                  source_type='new_physical' if c=='replacement_cost' else 'used_asking',condition='NewCondition' if c=='replacement_cost' else 'UsedCondition',
                  country='IN',currency='INR',fees='item_price_only',url='https://example.com/book',retrieved_at=now-timedelta(days=1),
                  edition_basis='Reviewed same edition',evidence='Independent saved quote') for c in ['replacement_cost','used_value']] if i<15 else []) for i in range(60)]
    truth = dict(dataset_id='room-one',annotator='Human',annotated_at=now,independence_statement='Recorded without predictions',
                 country='IN',currency='INR',enclosed_room=True,shelving_units=2,books=books,
                 items=[dict(id='I'+str(i),location='room position '+str(i),owned=True,category='chair',evidence='Tape sheet') for i in range(8)],
                 room=dict(floor_area_m2=12,wall_area_m2=36,wall_basis='gross',method='Tape polygon',uncertainty='1 cm',evidence='Room sheet'))
    frozen = freeze(truth,dict(confidence_threshold='.9',confident_wrong_denominator='high_confidence',dimension_aggregation='all_comparisons',price_aggregation='all_available_comparisons'),{'model':'explicit-test'},now+timedelta(seconds=1))
    packet = dict(sweep=dict(id='test-sweep',captured_at=(now+timedelta(seconds=2)).isoformat(),country='IN',currency='INR'),synthetic=True,
                  books=[Book(id='P'+str(i),status='identified',frame_ref='test-frame',title='Title '+str(i),spine_height_cm=20,spine_thickness_cm=2,id_confidence='.95').model_dump(mode='json') for i in range(60)],
                  items=[Item(id='J'+str(i),frame_ref='test-frame',category='chair').model_dump(mode='json') for i in range(8)],
                  room=dict(floor_area_m2=12,wall_area_m2=36),quote_manifest=[],
                  room_geometry=dict(request=dict(interpretation=dict(wall_area_basis='gross'))))
    assessment = dict(reviewer='Independent reviewer',reviewed_at=now+timedelta(seconds=10),truth_sha256=frozen.payload_sha256,packet_sha256=digest(canonical(packet)),
                      matches=[dict(truth_id='T'+str(i),predicted_id='P'+str(i),physical_evidence='Original position',title_correct=True,title_evidence='Independent visible title',price_basis_confirmed=[]) for i in range(60)]+
                      [dict(truth_id='I'+str(i),predicted_id='J'+str(i),physical_evidence='Original position',title_correct=None,title_evidence='',price_basis_confirmed=[]) for i in range(8)],
                      false_merges=[],false_splits=[],timing=None,stages=[],costs=[],cost_coverage_complete=False,second_locale_book_ids=[])
    return packet,frozen,assessment


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.packet,self.frozen,self.assessment=inputs()

    def run_eval(self):
        self.assessment['packet_sha256']=digest(canonical(self.packet))
        return evaluate(self.packet,self.frozen,self.assessment)

    def test_full_denominators_and_missing_prices(self):
        r=self.run_eval()
        self.assertEqual(r['metrics']['title_identification']['status'],'pass')
        self.assertEqual(r['metrics']['spine_dimensions']['status'],'pass')
        self.assertEqual(r['metrics']['book_prices']['missing_predictions'],30)
        self.assertEqual(r['metrics']['book_prices']['status'],'fail')
        self.assertEqual(r['metrics']['packet_latency']['status'],'not_measured')
        self.assertFalse(r['acceptance_eligible'])

    def test_misses_do_not_shrink_title_or_sample_denominators(self):
        self.packet['books']=self.packet['books'][20:]
        self.assessment['matches']=self.assessment['matches'][20:]
        r=self.run_eval()
        self.assertEqual(r['metrics']['title_identification']['value'],Decimal(40)/60)
        self.assertEqual(r['metrics']['spine_dimensions']['missing_predictions'],40)
        self.assertEqual(r['metrics']['spine_dimensions']['status'],'fail')
        self.assertEqual(len(r['physical_matching']['unmatched_truth']),20)

    def test_count_cancellation_retains_false_positives_and_misses(self):
        self.assessment['matches']=self.assessment['matches'][1:]
        r=self.run_eval()
        self.assertEqual(r['metrics']['book_count']['status'],'pass')
        self.assertIn('P0',r['physical_matching']['unmatched_predictions'])
        self.assertIn('T0',r['physical_matching']['unmatched_truth'])
        self.assertEqual(r['physical_matching']['wrong_high_confidence'],1)

    def test_double_physical_match_rejected(self):
        self.assessment['matches'][1]['predicted_id']='P0'
        with self.assertRaisesRegex(ValueError,'one-to-one'):self.run_eval()

    def test_unknown_truth_and_cross_kind_match_rejected(self):
        self.assessment['matches'][0]['truth_id']='missing'
        with self.assertRaisesRegex(ValueError,'unknown'):self.run_eval()
        self.assessment['matches'][0]['truth_id']='T0'
        self.assessment['matches'][0]['predicted_id']='J0'
        with self.assertRaisesRegex(ValueError,'one-to-one|book match'):self.run_eval()

    def test_truth_hash_and_post_capture_freeze_rejected(self):
        value=self.frozen.model_dump();value['truth']['books'][0]['title']='changed'
        with self.assertRaisesRegex(ValueError,'hash'):FrozenTruth.model_validate(value)
        value=self.frozen.model_dump(exclude={'payload_sha256'});value['frozen_at']=datetime(2026,10,12,tzinfo=timezone.utc)
        value['payload_sha256']=digest(canonical(value));self.frozen=FrozenTruth.model_validate(value)
        self.assessment['truth_sha256']=self.frozen.payload_sha256
        with self.assertRaisesRegex(ValueError,'before capture'):self.run_eval()

    def test_confidence_unknown_is_undefined(self):
        for b in self.packet['books']:b['id_confidence']=None
        r=self.run_eval();self.assertEqual(r['metrics']['confident_wrong']['status'],'not_measured')
        self.assertEqual(r['metrics']['confident_wrong_human_legible']['value'],0)

    def test_blank_title_is_not_correct(self):
        self.packet['books'][0]['title']=''
        with self.assertRaisesRegex(ValueError,'blank'):self.run_eval()
        self.assessment['matches'][0].update(title_correct=None,title_evidence='')
        self.assertEqual(self.run_eval()['physical_matching']['correct_titles'],59)

    def test_missing_independent_title_judgment_rejected(self):
        self.assessment['matches'][0].update(title_correct=None,title_evidence='')
        with self.assertRaisesRegex(ValueError,'judgment'):self.run_eval()

    def test_wrong_title_penalizes_both_confidence_denominators(self):
        for m in self.assessment['matches'][:3]:m['title_correct']=False
        r=self.run_eval()
        self.assertEqual(r['metrics']['confident_wrong']['status'],'fail')
        self.assertEqual(r['metrics']['confident_wrong_human_legible']['value'],Decimal('.05'))

    def test_missing_dimensions_and_exact_boundary(self):
        self.packet['books'][0]['spine_height_cm']=23
        self.assertEqual(self.run_eval()['metrics']['spine_dimensions']['status'],'pass')
        self.packet['books'][0]['spine_height_cm']=None
        self.assertEqual(self.run_eval()['metrics']['spine_dimensions']['status'],'fail')

    def test_price_sample_unavailable_truth_not_a_pass(self):
        value=self.frozen.truth.model_dump();value['books'][0]['prices'][0].update(availability='unavailable',amount=None)
        self.frozen=freeze(value,self.frozen.policy.model_dump(),{},self.frozen.frozen_at)
        self.assessment['truth_sha256']=self.frozen.payload_sha256
        r=self.run_eval();self.assertEqual(r['metrics']['book_prices']['unavailable'],1)

    def test_insufficient_samples_not_measured(self):
        value=self.frozen.truth.model_dump();value['books'][0]['spine_sample']=False
        self.frozen=freeze(value,self.frozen.policy.model_dump(),{},self.frozen.frozen_at)
        self.assessment['truth_sha256']=self.frozen.payload_sha256
        self.assertEqual(self.run_eval()['metrics']['spine_dimensions']['status'],'not_measured')

    def test_price_basis_required_even_with_equal_amount(self):
        b=self.packet['books'][0];b['replacement_cost'].update(amount=100,quote_ref='q')
        self.packet['quote_manifest']=[dict(id='q',quote=dict(source_type='new_physical',condition='NewCondition',target_currency='INR',fees='item_price_only'))]
        r=self.run_eval();self.assertIsNone(r['tables']['prices'][0]['error'])
        self.assessment['matches'][0]['price_basis_confirmed']=['replacement_cost']
        r=self.run_eval();self.assertEqual(r['tables']['prices'][0]['error'],0)
        self.packet['quote_manifest'][0]['quote']['condition']='UsedCondition'
        self.assertIsNone(self.run_eval()['tables']['prices'][0]['error'])

    def test_unknown_area_and_mismatched_wall_convention_fail(self):
        self.packet['room']['floor_area_m2']=None
        self.packet['room_geometry']['request']['interpretation']['wall_area_basis']='net'
        r=self.run_eval();self.assertEqual(r['metrics']['floor_area_m2']['status'],'fail')
        self.assertEqual(r['metrics']['wall_area_m2']['status'],'fail')

    def test_latency_strict_boundary_and_hash_binding(self):
        self.assessment['timing']=dict(clock_id='one-process',sweep_started=0,sweep_ended=180,packet_ready=480,
                                       packet_sha256=digest(canonical(self.packet)),evidence='Monotonic log')
        r=self.run_eval();self.assertEqual(r['metrics']['packet_latency']['status'],'fail')
        self.assertEqual(r['metrics']['sweep_duration']['status'],'fail')
        self.assessment['timing']['packet_ready']=479
        self.assertEqual(self.run_eval()['metrics']['packet_latency']['status'],'pass')
        self.assessment['timing']['packet_sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'different packet'):self.run_eval()

    def test_telemetry_ordering_and_cost_unknown(self):
        with self.assertRaises(ValueError):Stage(stage='detection',job_id='j',clock_id='c',queued=5,started=1,ended=6,retries=0,usage={},evidence='log')
        with self.assertRaises(ValueError):Cost(job_id='j',kind='unknown',amount=0,currency='INR',usage_basis='usage',rate_date='',evidence='log')
        self.assessment['costs']=[dict(job_id='j',kind='estimated',amount=0,currency='INR',usage_basis='quota',rate_date='2026-10-11',evidence='local record')]
        r=self.run_eval();self.assertFalse(r['cost']['complete_actual_cost'])
        self.assertIsNone(r['cost']['totals_by_currency']['INR']['actual'])

    def test_second_locale_preserves_exact_physical_identity(self):
        second=copy.deepcopy(self.packet);second['sweep']['country']='US';second['sweep']['currency']='USD'
        self.assessment['second_locale_book_ids']=['P'+str(i) for i in range(10)]
        r=evaluate(self.packet,self.frozen,self.assessment,second)
        self.assertEqual(len(r['tables']['second_locale']),20)
        second['books'][0]['edition']='different'
        with self.assertRaisesRegex(ValueError,'identity'):evaluate(self.packet,self.frozen,self.assessment,second)

    def test_outputs_integrity_escaping_and_fresh_directory(self):
        self.frozen.truth.books[0].title='<script>' # Re-freeze to bind changed test truth.
        self.frozen=freeze(self.frozen.truth.model_dump(),self.frozen.policy.model_dump(),{},self.frozen.frozen_at)
        self.assessment['truth_sha256']=self.frozen.payload_sha256
        r=self.run_eval();r['tables']['books'][0]['truth_title']='=HYPERLINK("evil")'
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'result';a=Assessment.model_validate(self.assessment)
            write_results(out,r,self.frozen,a,'archivehash')
            self.assertIn("'=HYPERLINK",(out/'books.csv').read_text())
            self.assertEqual(load_results(out)['truth_sha256'],self.frozen.payload_sha256)
            with self.assertRaises(FileExistsError):write_results(out,r,self.frozen,a,'archivehash')
            (out/'prices.csv').write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'):load_results(out)


class ArchiveEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.f=final_fixture.FinalizationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.finalizer.run(self.f.request)
        self.raw=self.f.finalizer.archive(self.f.request.run_id,self.f.sweep)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'packet.zip';self.path.write_bytes(self.raw)

    def test_actual_finalizer_archive_accepted_offline(self):
        packet,files,sha=load_archive(self.path)
        self.assertEqual(packet['sweep']['id'],self.f.sweep)
        self.assertEqual(sha,digest(self.raw));self.assertIn('report.html',files)

    def test_saved_book_and_item_quotes_reparsed_without_network(self):
        for method,run in [('test_book_quote_reparse_and_both_components','copies-final'),('test_exact_item_price_reaudited_without_network','final-one')]:
            f=final_fixture.FinalizationTests();f.setUp();self.addCleanup(f.doCleanups)
            getattr(f,method)()
            self.path.write_bytes(f.finalizer.archive(run,f.sweep))
            with patch('library_claim.valuation.PublicHTTPS.__call__',side_effect=AssertionError('network called')):
                packet,_,_=load_archive(self.path)
            self.assertTrue(packet['quote_manifest'])

    def test_same_ten_second_market_consumed_from_m10_archive(self):
        f=final_fixture.FinalizationTests();f.setUp();self.addCleanup(f.doCleanups)
        book=book_fixture.Inventory().books[0];book['frame_ref']=f.frame['id']
        book['field_evidence']={'title':[f.frame['id']],'author':[f.frame['id']],'isbn':[f.frame['id']]}
        books=[dict(book,id='copy'+str(i)) for i in range(10)]
        inventory=book_fixture.Inventory();inventory.books=books
        snapshot=f.finalizer.books.snapshot(f.sweep);snapshot.update(revision=2,books=books)
        def fetch(url):
            p=book_fixture.product();p['offers']['priceCurrency']='USD' if '/us/' in url else 'INR'
            return book_fixture.html(p)
        values=book_fixture.ValuationStore(f.finalizer.frames,inventory=inventory,fetch=fetch,clock=lambda:f.now)
        request=book_fixture.ValuationRequest.model_validate(dict(run_id='ten',sweep_id=f.sweep,expected_revision=2,track_ids=[b['id'] for b in books],
            markets=[dict(country=c,currency=u,decimal_places=2,appraisal_threshold='1000') for c,u in [('IN','INR'),('US','USD')]],
            policy=book_fixture.policy(fx_date=f.now.date().isoformat()).model_dump(mode='json'),
            candidates=[book_fixture.candidate(track_id=b['id'],target_country=c,market_country=c,url='https://seller.example/'+c.lower()+'/book').model_dump() for b in books for c in ['IN','US']],consent_fetch=True))
        values.run(request);f.request.expected_book_revision=2;f.request.book_valuation_runs=['ten']
        with patch.object(f.finalizer.books,'snapshot',return_value=snapshot):
            f.finalizer.values.inventory=f.finalizer.books;f.finalizer.run(f.request)
        self.path.write_bytes(f.finalizer.archive('final-one',f.sweep));packet,files,_=load_archive(self.path)
        _,_,assessment=inputs();assessment['second_locale_book_ids']=[b['id'] for b in books];assessment['second_locale_country']='US'
        second=second_locale_from_archive(packet,files,assessment)
        self.assertEqual(second['sweep']['currency'],'USD');self.assertEqual(len(second['books']),10)
        self.assertEqual(second['books'][0]['replacement_cost']['amount'],Decimal('12.34'))
        self.assertIsNone(second['books'][0]['used_value']['amount'])
        assessment['second_locale_book_ids'][0]='missing'
        with self.assertRaisesRegex(ValueError,'lacks saved'):second_locale_from_archive(packet,files,assessment)

    def test_mutated_evidence_rejected(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as z:files={n:z.read(n) for n in z.namelist()}
        files['report.html']+=b'changed'
        with zipfile.ZipFile(self.path,'w') as z:
            for n,data in files.items():z.writestr(n,data)
        with self.assertRaisesRegex(ValueError,'hash'):load_archive(self.path)

    def test_extra_or_unsafe_entries_rejected(self):
        with zipfile.ZipFile(self.path,'a') as z:z.writestr('../escape','bad')
        with self.assertRaisesRegex(ValueError,'unsafe'):load_archive(self.path)

    def test_archive_byte_budget(self):
        with self.assertRaisesRegex(ValueError,'budget'):load_archive(self.path,max_bytes=100)

    def result_directory(self):
        packet,_,sha=load_archive(self.path)
        _,frozen,a=inputs();a['matches']=[];a['packet_sha256']=digest(canonical(packet))
        a['reviewed_at']=datetime.now(timezone.utc)+timedelta(days=1)
        out=Path(self.temp.name)/'repair-results'
        write_results(out,evaluate(packet,frozen,a),frozen,Assessment.model_validate(a),sha)
        return out

    def test_repair_results_recomputed_from_actual_archived_packet(self):
        out=self.result_directory()
        result=recompute_result(out,self.path)
        self.assertEqual(result['metrics']['book_count']['status'],'fail')
        self.assertEqual(result['metrics']['book_count']['value'],1)

    def test_rehashed_false_pass_summary_cannot_prove_measured_repair(self):
        out=self.result_directory()
        result=json.loads((out/'results.json').read_text())
        result['metrics']['book_count'].update(value=0,status='pass')
        (out/'results.json').write_text(json.dumps(result)+'\n')
        manifest=json.loads((out/'evaluation-manifest.json').read_text())
        for entry in manifest['files']:
            if entry['path']=='results.json':
                raw=(out/'results.json').read_bytes();entry.update(sha256=digest(raw),byte_size=len(raw))
        (out/'evaluation-manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'independent recomputation'):recompute_result(out,self.path)

    def test_delivery_missing_evidence_stays_unmeasured(self):
        packet,_,sha=load_archive(self.path)
        _,frozen,a=inputs();a['matches']=[];a['packet_sha256']=digest(canonical(packet))
        a['reviewed_at']=datetime.now(timezone.utc)+timedelta(days=1)
        out=Path(self.temp.name)/'results'
        r=evaluate(packet,frozen,a)
        write_results(out,r,frozen,Assessment.model_validate(a),sha)
        architecture=Path(self.temp.name)/'architecture.md';architecture.write_text('Test architecture')
        spec=dict(archive=str(self.path),results=str(out),architecture=dict(path=str(architecture),sha256=digest(architecture.read_bytes())),
                  demo=None,setup=None,failures=[],repair=None,repo_url='',private_repo_asserted=False)
        d=check(spec,Path(self.temp.name))
        self.assertEqual(d['statuses']['demo'],'not_measured')
        self.assertEqual(d['statuses']['failure_log'],'not_measured')
        self.assertFalse(d['external_submission_performed'])
        spec['failures']=[dict(error_id='invented',impact='bad',root_cause='guess',evidence=spec['architecture'],tried='nothing',next_two_weeks='fix')]
        with self.assertRaisesRegex(ValueError,'not observed'):check(spec,Path(self.temp.name))


if __name__=='__main__':unittest.main()
