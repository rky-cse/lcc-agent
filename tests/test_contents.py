import copy
import io
import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from library_claim.capture_store import CaptureInput, FrameStore
from library_claim.contents import ContentsCommand, ContentsStore
from library_claim.contents_detection import ContentsDetectionInput, ContentsDetectionResponse, detect
from library_claim.contents_pricing import (ItemCandidate, ItemPricePolicy, ItemValuationRequest,
                                           ContentsPricing, item_quote, quantity_cm)
from library_claim.models import Item
from library_claim.packet import json_text
from tests import test_planar_measurement as planar_fixture
from tests import test_capture_server as server_fixture


def labels(category='chair'):
    return [dict(field=k,value=v,basis='visible_marking' if k in {'brand','model'} else 'visible_appearance',
                 statement='Synthetic reviewed visible fixture')
            for k,v in [('category',category),('description','Visible chair'),('material','wood'),('brand','WoodCo'),('model','A-1')]]


def product(price='10',**updates):
    result={'@type':'Product','@id':'product','name':'Synthetic chair','category':'chair','material':'wood',
            'brand':{'@type':'Brand','name':'WoodCo'},'model':'A-1',
            'width':{'@type':'QuantitativeValue','value':'2.5','unitCode':'CMT'},
            'height':{'@type':'QuantitativeValue','value':'23','unitText':'cm'},
            'offers':{'@type':'Offer','price':price,'priceCurrency':'INR','availability':'InStock','itemCondition':'NewCondition'}}
    result.update(updates);return result


def html(value):return ('<script type="application/ld+json">'+json_text(value)+'</script>').encode()


def policy(**updates):
    result=dict(ordinary_unpriced_status='',aggregation='min_max',min_comparables=2,min_distinct_domains=2,
                required_axes=['w','h'],size_tolerance_fraction='0.1',fees='item_price_only',rounding='half_even',
                max_quote_age_hours=24,allow_foreign_fallback=False,fx_date='2026-10-09',max_fx_age_days=3)
    result.update(updates);return ItemPricePolicy.model_validate(result)


def candidate(**updates):
    result=dict(item_id='item',url='https://one.example/product',product_id='product',offer_index=0,
                market_country='IN',market_statement='Synthetic reviewed market statement',
                physical_statement='Synthetic reviewed physical replacement',reviewer='Synthetic reviewer',
                match_basis='exact_model',comparable_statement='Synthetic fixture visible model matches')
    result.update(updates);return ItemCandidate.model_validate(result)


class ContentsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.frames=FrameStore(Path(self.temp.name));self.ledger=ContentsStore(self.frames)
        out=io.BytesIO();Image.new('RGB',(1920,1080),'white').save(out,'PNG');self.data=out.getvalue()
        self.capture=CaptureInput(sweep_id='fixture',upload_id='first',media_sequence=0,
                                  captured_at=datetime(2026,10,11,tzinfo=timezone.utc),source='file_import',synthetic=True)
        self.frame=self.frames.save(self.capture,self.data)
        self.base=dict(command_id='observe',sweep_id='fixture',expected_revision=0,operation='observe',item_id='item',
                       reviewer='Synthetic reviewer',reason='Explicit physical object review',frame_ref=self.frame.id,
                       frame_sha256=self.frame.sha256,bounds_px=[100,50,1500,1000],new_owned=True,labels=labels())
        self.ledger.apply(ContentsCommand.model_validate(self.base))

    def command(self,operation,**updates):
        value=dict(command_id=operation,sweep_id='fixture',expected_revision=self.ledger.snapshot('fixture')['revision'],
                   operation=operation,item_id='item',reviewer='Synthetic reviewer',reason='Explicit fixture review')
        value.update(updates);return ContentsCommand.model_validate(value)

    def observe(self,key,**updates):
        value=dict(self.base,command_id='observe-'+key,item_id=key,
                   expected_revision=self.ledger.snapshot('fixture')['revision'],bounds_px=[10,10,80,80])
        value.update(updates);return self.ledger.apply(ContentsCommand.model_validate(value))

    def measure(self,**updates):
        request=planar_fixture.fixture(self.frame);request['spines']=request['spines'][:1];request['spines'][0]['id']='item'
        request.update(updates)
        return self.ledger.apply(self.command('measure',measurement=request,height_axis='h',width_axis='w'))

    def test_reviewed_fields_unknown_dimensions_and_restart(self):
        r=self.ledger.snapshot('fixture');row=r['rows'][0]
        self.assertEqual(row['item']['brand_model'],'WoodCo A-1');self.assertEqual(row['material'],'wood')
        self.assertEqual(row['item']['dimensions_cm'],dict(w=None,h=None,d=None))
        self.assertIsNone(row['item']['confidence']);self.assertEqual(r['billable_entity_count'],1)
        self.assertIsNone(r['total_item_count']);self.assertFalse(r['coverage_verified'])
        self.assertEqual(ContentsStore(self.frames).snapshot('fixture'),r)

    def test_exact_retry_id_collision_and_stale_revision(self):
        self.assertEqual(self.ledger.apply(ContentsCommand.model_validate(self.base))['revision'],1)
        with self.assertRaisesRegex(ValueError,'different payload'):
            self.ledger.apply(ContentsCommand.model_validate(dict(self.base,reason='Changed')))
        with self.assertRaisesRegex(ValueError,'stale'):
            self.ledger.apply(self.command('ownership',expected_revision=0,new_owned=False))

    def test_repeated_view_one_physical_item_and_no_silent_label_replacement(self):
        frame=self.frames.save(self.capture.model_copy(update=dict(upload_id='second',media_sequence=1)),self.data)
        repeated=dict(self.base,command_id='repeat',expected_revision=1,frame_ref=frame.id,frame_sha256=frame.sha256,new_owned=None)
        r=self.ledger.apply(ContentsCommand.model_validate(repeated));self.assertEqual(r['reviewed_entity_count'],1)
        self.assertEqual(len(r['rows'][0]['observations']),2)
        with self.assertRaises(ValueError):self.ledger.apply(ContentsCommand.model_validate(dict(repeated,command_id='another',expected_revision=2)))
        third=self.frames.save(self.capture.model_copy(update=dict(upload_id='third',media_sequence=2)),self.data)
        changed=dict(repeated,command_id='change',expected_revision=2,frame_ref=third.id,frame_sha256=third.sha256,labels=labels('table'))
        with self.assertRaisesRegex(ValueError,'silently replace'):self.ledger.apply(ContentsCommand.model_validate(changed))
        self.assertEqual(self.ledger.snapshot('fixture')['revision'],2)

    def test_duplicate_identical_region_cannot_create_another_item(self):
        with self.assertRaisesRegex(ValueError,'already assigned'):
            self.observe('copy',bounds_px=self.base['bounds_px'])
        self.assertEqual(self.ledger.snapshot('fixture')['reviewed_entity_count'],1)

    def test_invalid_region_cross_sweep_changed_hash_and_irrelevant_fields(self):
        for update in [dict(bounds_px=[0,0,1920,1080]),dict(bounds_px=[100,50,90,80]),dict(frame_sha256='a'*64),dict(sweep_id='other')]:
            with self.subTest(update=update),self.assertRaises(ValueError):self.observe('bad',**update)
        with self.assertRaises(ValueError):self.command('ownership',new_owned=False,members=['item'])
        self.assertEqual(self.ledger.snapshot('fixture')['revision'],1)

    def test_unreadable_model_not_invented_and_category_review(self):
        self.observe('unknown',labels=[dict(field='category',value='unknown',basis='visible_appearance',statement='Not classifiable')])
        row=self.ledger.snapshot('fixture')['rows'][1]
        self.assertEqual(row['item']['category'],'');self.assertEqual(row['item']['brand_model'],'')
        for field in ['brand','model']:
            with self.assertRaises(ValueError):self.command('label',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,
                labels=[dict(field=field,value='Guess',basis='claimant_assertion',statement='Guess')])

    def test_planar_face_dimensions_and_hidden_depth_preserved(self):
        r=self.measure();row=r['rows'][0]
        self.assertEqual(row['item']['dimensions_cm'],dict(w='2.500',h='23.000',d=None))
        self.assertFalse(row['dimension_proofs']['w']['confidence_bound'])
        digest=row['dimension_proofs']['w']['artifact_sha256']
        self.assertIn('geometry',json.loads(self.ledger.artifact(digest)))

    def test_invalid_measurement_does_not_commit(self):
        before=self.ledger.snapshot('fixture')
        with self.assertRaisesRegex(ValueError,'unavailable'):self.measure(reference=None)
        self.assertEqual(self.ledger.snapshot('fixture'),before)

    def test_art_print_original_and_unknown_have_separate_assertions(self):
        self.ledger.apply(self.command('label',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,labels=labels('art')))
        self.assertEqual(self.ledger.snapshot('fixture')['rows'][0]['item']['status'],'needs_appraisal')
        for i,kind in enumerate(['print','original','unknown']):
            r=self.ledger.apply(self.command('art',command_id=f'art{i}',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,
                                  artwork_kind=kind,claimant_statement='This is '+kind))
            row=r['rows'][0];self.assertFalse(row['art']['authenticated'])
            self.assertEqual(row['item']['status'],'' if kind=='print' else 'needs_appraisal')
        self.ledger.apply(self.command('label',command_id='relabel',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,labels=labels('decor')))
        self.assertEqual(self.ledger.snapshot('fixture')['rows'][0]['item']['status'],'needs_appraisal')

    def test_saved_guidance_assertion_requires_matching_frozen_turn(self):
        self.ledger.apply(self.command('label',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,labels=labels('portrait')))
        state=dict(revision=7,art_declarations=[dict(frame_ref=self.frame.id,classification='print',claimant_statement='It is a print')])
        with closing(self.frames._connect()) as db:
            db.execute('CREATE TABLE guidance_sessions (id TEXT PRIMARY KEY,state TEXT NOT NULL)')
            db.execute('INSERT INTO guidance_sessions VALUES (?,?)',('fixture',json_text(state)));db.commit()
        cmd=self.command('art',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,artwork_kind='print',
                          claimant_statement='It is a print',guidance_revision=7,declaration_index=0)
        for update in [dict(guidance_revision=6),dict(claimant_statement='Other')]:
            with self.assertRaises(ValueError):self.ledger.apply(cmd.model_copy(update=update))
        self.assertEqual(self.ledger.apply(cmd)['rows'][0]['art']['guidance_revision'],7)

    def grouped(self,basis='set'):
        self.observe('set',labels=labels('furniture_set'))
        self.observe('component',bounds_px=[20,110,80,170])
        return self.ledger.apply(self.command('group',item_id='set',members=['item','component'],counting_basis=basis))

    def test_set_and_component_counting_never_price_both(self):
        r=self.grouped();self.assertEqual(r['billable_entity_count'],1)
        self.assertEqual([x['item']['id'] for x in r['rows'] if x['billable']],['set'])
        r=self.ledger.apply(self.command('group',command_id='components',item_id='set',members=['item','component'],counting_basis='components'))
        self.assertEqual(r['billable_entity_count'],2)
        self.assertFalse(next(x for x in r['rows'] if x['item']['id']=='set')['billable'])

    def test_group_ownership_and_overlap_guards(self):
        self.grouped()
        with self.assertRaises(ValueError):self.ledger.apply(self.command('ownership',new_owned=False))
        r=self.ledger.apply(self.command('ownership',item_id='set',new_owned=False))
        self.assertEqual(r['billable_entity_count'],0);self.assertTrue(all(not x['item']['owned'] for x in r['rows']))
        with self.assertRaises(ValueError):self.ledger.apply(self.command('merge',source_item_id='component'))
        with self.assertRaises(ValueError):self.ledger.apply(self.command('group',item_id='item',members=['set'],counting_basis='set'))

    def test_sensitive_set_member_propagates_appraisal_and_parent_relabel_needs_ungroup(self):
        self.grouped()
        self.ledger.apply(self.command('label',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,labels=labels('art')))
        r=self.ledger.snapshot('fixture');parent=next(x for x in r['rows'] if x['item']['id']=='set')
        self.assertEqual(parent['item']['status'],'needs_appraisal')
        with self.assertRaisesRegex(ValueError,'ungroup'):
            self.ledger.apply(self.command('label',command_id='relabel-parent',item_id='set',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,labels=labels('chair')))

    def test_merge_retains_views_retires_alias_and_revokes_geometry(self):
        self.measure();self.observe('alias')
        r=self.ledger.apply(self.command('merge',source_item_id='alias'))
        self.assertEqual(r['reviewed_entity_count'],1);self.assertEqual(len(r['rows'][0]['observations']),2)
        self.assertEqual(r['rows'][0]['dimension_proofs'],{});self.assertIn('alias',r['retired'])
        with self.assertRaises(ValueError):self.observe('alias',bounds_px=[30,30,70,70])

    def test_conflicting_merge_and_remove(self):
        self.observe('different',labels=labels('table'))
        with self.assertRaisesRegex(ValueError,'conflicting'):self.ledger.apply(self.command('merge',source_item_id='different'))
        r=self.ledger.apply(self.command('remove',item_id='different'))
        self.assertEqual(r['reviewed_entity_count'],1);self.assertIn('different',r['retired'])

    def test_corruption_blocks_ledger_geometry_and_originals(self):
        r=self.measure();digest=r['rows'][0]['dimension_proofs']['w']['artifact_sha256']
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE contents_artifacts SET content=? WHERE sha=?',(b'corrupt',digest));db.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.ledger.snapshot('fixture')
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE contents_ledgers SET state=?',(b'{}',));db.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.ledger.snapshot('fixture')

    def detection(self):
        request=ContentsDetectionInput(sweep_id='fixture',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,expected_revision=1)
        response=ContentsDetectionResponse(objects=[dict(category='chair',bounds_1000=(10,10,30,30),
            description='Visible chair',material_appearance='wood-like',visible_marking='',reason='Tentative visible object')],
            unresolved=['Hidden depth'],coverage='Tentative, not verified')
        return request,response

    def test_detection_is_provisional_archived_and_inventory_unchanged(self):
        req,response=self.detection();before=self.ledger.snapshot('fixture');r=detect(self.frames,req,response)
        self.assertFalse(r['inventory_mutated']);self.assertFalse(r['proposals'][0]['accepted'])
        self.assertEqual(self.ledger.snapshot('fixture'),before)
        self.assertEqual(json.loads(self.ledger.artifact(r['artifact_sha256']))['response']['objects'][0]['category'],'chair')

    def test_proposal_acceptance_exact_original_and_historical_ack(self):
        req,response=self.detection();r=detect(self.frames,req,response)
        self.ledger.apply(self.command('ownership',new_owned=False))
        values=dict(proposal_sha256=r['artifact_sha256'],proposal_index=0,bounds_px=r['proposals'][0]['bounds_px'])
        with self.assertRaisesRegex(ValueError,'historical'):self.observe('proposed',**values)
        result=self.observe('proposed',acknowledge_historical_proposal=True,**values)
        self.assertEqual(result['reviewed_entity_count'],2)

    def test_detection_provider_failure_and_input_guards(self):
        req,response=self.detection()
        with patch('library_claim.contents_detection.request_structured',return_value=(None,{'code':'unavailable'},None,None)):
            r=detect(self.frames,req,key='not-a-real-key');self.assertEqual(r['status'],'unavailable')
        with self.assertRaises(ValueError):detect(self.frames,req,response,key='key')
        with self.assertRaises(ValueError):detect(self.frames,req.model_copy(update=dict(frame_sha256='a'*64)),response)
        with self.assertRaises(ValueError):detect(self.frames,req.model_copy(update=dict(expected_revision=0)),response)


class ItemPricingTests(unittest.TestCase):
    command=ContentsTests.command
    observe=ContentsTests.observe
    measure=ContentsTests.measure
    grouped=ContentsTests.grouped
    def setUp(self):
        ContentsTests.setUp(self);self.now=datetime(2026,10,11,tzinfo=timezone.utc);self.calls=[]
        self.sources={'https://one.example/product':html(product())}
        self.prices=ContentsPricing(self.frames,fetch=self.fetch,clock=self.clock)

    def clock(self):self.now+=timedelta(seconds=2);return self.now
    def fetch(self,url):
        self.calls.append(url);value=self.sources[url]
        if isinstance(value,Exception):raise value
        return value
    def request(self,**updates):
        value=dict(run_id='price',sweep_id='fixture',expected_revision=self.ledger.snapshot('fixture')['revision'],
                   item_ids=['item'],market=dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold='1000'),
                   policy=policy().model_dump(mode='json'),candidates=[candidate().model_dump()],consent_fetch=True)
        value.update(updates);return ItemValuationRequest.model_validate(value)

    def test_exact_literal_price_zero_and_unknown_no_model(self):
        r=self.prices.run(self.request());self.assertEqual(r['rows'][0]['item']['replacement_cost']['low'],'10.00')
        self.assertEqual(r['rows'][0]['quote_basis'],'exact_model');Item.model_validate(r['rows'][0]['item'])
        self.sources['https://one.example/zero']=html(product('0'))
        r=self.prices.run(self.request(run_id='zero',candidates=[candidate(url='https://one.example/zero').model_dump()]))
        self.assertEqual(r['priced_count'],1);self.assertEqual(r['totals']['low'],'0.00')

    def test_suppressed_components_and_set_have_no_double_valuation(self):
        self.grouped('components')
        self.sources['https://one.example/component']=html(product('5'))
        req=self.request(item_ids=['item','component','set'],candidates=[candidate().model_dump(),
            candidate(item_id='component',url='https://one.example/component').model_dump(),candidate(item_id='set').model_dump()])
        r=self.prices.run(req)
        self.assertEqual(r['priced_count'],2);self.assertEqual(r['totals'],dict(low='15.00',high='15.00'))
        self.assertIsNone(next(row for row in r['rows'] if row['item']['id']=='set')['item']['replacement_cost']['low'])

    def test_exact_requires_legible_brand_model_not_appearance(self):
        row=self.ledger.snapshot('fixture')['rows'][0];row['labels']['model']['basis']='visible_appearance'
        with self.assertRaisesRegex(ValueError,'visible'):
            item_quote(html(product()),candidate(),row,policy(),self.now.date())
        for update in [dict(brand='Other'),dict(model='Other'),dict(category='sofa')]:
            with self.assertRaises(ValueError):item_quote(html(product(**update)),candidate(),self.ledger.snapshot('fixture')['rows'][0],policy(),self.now.date())

    def comparables(self):
        self.measure();self.sources['https://two.example/product']=html(product('20'))
        return [candidate(match_basis='reviewed_comparable').model_dump(),
                candidate(url='https://two.example/product',match_basis='reviewed_comparable').model_dump()]

    def test_comparable_range_exact_min_max_and_size_proofs(self):
        r=self.prices.run(self.request(candidates=self.comparables()));row=r['rows'][0]
        self.assertEqual(r['totals'],dict(low='10.00',high='20.00'));self.assertEqual(row['item']['status'],'range')
        self.assertEqual(row['quote_basis'],'reviewed_comparable_min_max');self.assertEqual(len(row['quotes']),2)
        self.assertEqual(row['quotes'][0]['size_comparison']['w']['owned_cm'],'2.500')
        self.assertIsNone(row['item']['dimensions_cm']['d']);Item.model_validate(row['item'])

    def test_range_requires_material_size_grade_and_multiple_sources(self):
        c=candidate(match_basis='reviewed_comparable')
        with self.assertRaisesRegex(ValueError,'unknown'):
            item_quote(html(product()),c,self.ledger.snapshot('fixture')['rows'][0],policy(),self.now.date())
        self.measure();row=self.ledger.snapshot('fixture')['rows'][0]
        for value in [product(material='metal'),product(width={'@type':'QuantitativeValue','value':10,'unitText':'cm'}),
                      product(width={'@type':'QuantitativeValue','value':2.5,'unitText':'in'})]:
            with self.assertRaises(ValueError):item_quote(html(value),c,row,policy(),self.now.date())
        with self.assertRaisesRegex(ValueError,'hidden'):
            item_quote(html(product()),c,row,policy(required_axes=['d']),self.now.date())
        r=self.prices.run(self.request(candidates=[c.model_dump()]));self.assertIsNone(r['rows'][0]['item']['replacement_cost']['low'])

    def test_one_domain_cannot_satisfy_two_domain_policy(self):
        self.measure();self.sources['https://one.example/second']=html(product('20'))
        cs=[candidate(match_basis='reviewed_comparable').model_dump(),candidate(url='https://one.example/second',match_basis='reviewed_comparable').model_dump()]
        r=self.prices.run(self.request(candidates=cs));self.assertEqual(r['priced_count'],0)

    def test_repeated_identical_source_snapshot_is_not_two_comparables(self):
        self.measure();self.sources['https://two.example/product']=html(product())
        cs=[candidate(match_basis='reviewed_comparable').model_dump(),candidate(url='https://two.example/product',match_basis='reviewed_comparable').model_dump()]
        r=self.prices.run(self.request(candidates=cs));self.assertEqual(r['priced_count'],0)

    def test_out_of_stock_used_rental_digital_expired_price_and_currency_rejected(self):
        row=self.ledger.snapshot('fixture')['rows'][0]
        for update in [dict(availability='OutOfStock'),dict(itemCondition='UsedCondition'),dict(businessFunction='LeaseOut'),
                       dict(priceValidUntil='2026-01-01'),dict(price=''),dict(priceCurrency='')]:
            value=product();value['offers'].update(update)
            with self.assertRaises(ValueError):item_quote(html(value),candidate(),row,policy(),self.now.date())
        with self.assertRaises(ValueError):item_quote(html(product(downloadUrl='https://download.example/')),candidate(),row,policy(),self.now.date())
        value=product();value['offers']['priceCurrency']='USD';self.sources[candidate().url]=html(value)
        r=self.prices.run(self.request());self.assertEqual(r['priced_count'],0);self.assertEqual(len(self.calls),1)

    def test_art_unanswered_original_never_fetch_print_requires_recorded_assertion(self):
        self.ledger.apply(self.command('label',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,labels=labels('art')))
        self.sources[candidate().url]=html(product(category='art'))
        r=self.prices.run(self.request());self.assertEqual(r['priced_count'],0);self.assertEqual(self.calls,[])
        self.ledger.apply(self.command('art',frame_ref=self.frame.id,frame_sha256=self.frame.sha256,artwork_kind='print',claimant_statement='It is a print'))
        r=self.prices.run(self.request(run_id='print'));self.assertEqual(r['priced_count'],1)
        self.assertFalse(r['rows'][0]['quotes'][0]['art_basis']['authenticated'])

    def test_threshold_range_high_appraisal_excludes_both_bounds(self):
        r=self.prices.run(self.request(candidates=self.comparables(),market=dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold='15')))
        self.assertEqual(r['rows'][0]['item']['status'],'needs_appraisal');self.assertEqual(r['priced_count'],0)
        self.assertEqual(r['totals'],dict(low='0',high='0'));self.assertEqual(len(r['rows'][0]['quotes']),2)

    def test_ordinary_missing_amount_semantics_are_explicit_policy(self):
        for i,status in enumerate(['','needs_appraisal']):
            r=self.prices.run(self.request(run_id=f'unknown{i}',candidates=[],policy=policy(ordinary_unpriced_status=status).model_dump(mode='json')))
            self.assertEqual(r['rows'][0]['item']['status'],status);self.assertIsNone(r['rows'][0]['item']['replacement_cost']['low'])

    def test_ownership_or_group_suppression_blocks_prices(self):
        self.ledger.apply(self.command('ownership',new_owned=False))
        r=self.prices.run(self.request());self.assertEqual(r['priced_count'],0);self.assertEqual(self.calls,[])

    def test_foreign_exact_fallback_dated_fx_local_failure_and_original_amount(self):
        self.sources[candidate().url]=html(product(model='Wrong'))
        value=product('1.005');value['offers']['priceCurrency']='USD';self.sources['https://foreign.example/product']=html(value)
        self.sources['https://api.frankfurter.dev/v2/rate/usd/inr?date=2026-10-09&providers=ecb']=json_text(dict(base='USD',quote='INR',date='2026-10-09',rate=80)).encode()
        req=self.request(candidates=[candidate().model_dump(),candidate(url='https://foreign.example/product',market_country='US').model_dump()],
                          policy=policy(allow_foreign_fallback=True).model_dump(mode='json'))
        r=self.prices.run(req);q=r['rows'][0]['quotes'][0]
        self.assertEqual(q['amount'],'1.005');self.assertEqual(q['target_amount'],'80.40');self.assertTrue(q['converted'])
        self.assertEqual(len(r['evidence_sha256']),3)

    def test_stale_and_expired_result_idempotence_and_request_collision(self):
        req=self.request();r=self.prices.run(req);calls=list(self.calls)
        self.assertEqual(self.prices.run(req)['result_sha256'],r['result_sha256']);self.assertEqual(self.calls,calls)
        with self.assertRaises(ValueError):self.prices.run(self.request(candidates=[]))
        self.now+=timedelta(days=2);self.assertTrue(self.prices.get('price')['quotes_expired'])
        self.ledger.apply(self.command('ownership',new_owned=False));r=self.prices.get('price');self.assertTrue(r['stale'])
        self.assertFalse(r['usable_for_current_inventory'])

    def test_price_outage_no_retry_and_hash_corruption(self):
        self.sources[candidate().url]=TimeoutError()
        r=self.prices.run(self.request());self.assertEqual(r['priced_count'],0);self.assertEqual(len(self.calls),1)
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE contents_price_runs SET result=?',(b'{}',));db.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.prices.get('price')

    def test_restart_interruption_source_scope_and_hash_validation(self):
        req=self.request();r=self.prices.run(req)
        restarted=ContentsPricing(self.frames,fetch=lambda url:self.fail('unexpected network'),clock=self.clock)
        self.assertEqual(restarted.run(req)['result_sha256'],r['result_sha256'])
        with self.assertRaises(KeyError):restarted.get('price','other')
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE contents_price_runs SET status=?,result=NULL,sha=NULL',('interrupted',));db.commit()
        r=restarted.run(req);self.assertEqual(r['status'],'interrupted');self.assertNotIn('rows',r)

    def test_archived_source_hash_corruption_blocks_saved_price(self):
        self.prices.run(self.request())
        with closing(self.frames._connect()) as db:
            db.execute('UPDATE valuation_evidence SET content=?',(b'corrupt',));db.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.prices.get('price')

    def test_policy_and_quantity_contracts(self):
        self.assertEqual(quantity_cm({'@type':'QuantitativeValue','value':'0.5','unitText':'m'}),50)
        for update in [dict(required_axes=['w','w']),dict(min_comparables=1),dict(min_distinct_domains=3),dict(size_tolerance_fraction='0.6')]:
            with self.assertRaises(ValueError):policy(**update)
        with self.assertRaises(ValueError):self.request(consent_fetch=False)
        with self.assertRaises(ValueError):self.request(item_ids=['other'])


class ContentsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=server_fixture.ServerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.frame=self.f.upload().json()['frame'];self.path=f'/api/sweeps/{self.f.sweep["id"]}/contents'
        self.command=dict(command_id='add',sweep_id=self.f.sweep['id'],expected_revision=0,operation='observe',item_id='chair',
            reviewer='Fixture reviewer',reason='Reviewed physical fixture',frame_ref=self.frame['id'],frame_sha256=self.frame['sha256'],
            bounds_px=[10,10,400,800],new_owned=True,labels=labels())

    def test_page_read_write_scoped_inventory_and_origin(self):
        for path in ['/contents','/assets/contents.mjs',self.path]:self.assertEqual(self.f.client.get(path).status_code,200)
        self.assertEqual(self.f.client.post(self.path,json=self.command).status_code,403)
        r=self.f.client.post(self.path,json=self.command,headers=self.f.headers);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['reviewed_entity_count'],1)
        wrong=dict(self.command,command_id='wrong',sweep_id='other')
        self.assertEqual(self.f.client.post(self.path,json=wrong,headers=self.f.headers).status_code,422)
        self.assertEqual(self.f.client.get('/api/sweeps/other/contents').status_code,404)

    def test_explicit_http_pricing_evidence_stale_and_currency_guards(self):
        self.f.client.post(self.path,json=self.command,headers=self.f.headers)
        self.f.app.state.contents_prices.fetch=lambda url:html(product())
        req=dict(run_id='run',sweep_id=self.f.sweep['id'],expected_revision=1,item_ids=['chair'],
            market=dict(country='IN',currency='INR',decimal_places=2,appraisal_threshold='1000'),policy=policy().model_dump(mode='json'),
            candidates=[candidate(item_id='chair').model_dump()],consent_fetch=True)
        r=self.f.client.post(self.path+'/valuations',json=req,headers=self.f.headers);self.assertEqual(r.status_code,200,r.text)
        result=r.json();self.assertEqual(result['priced_count'],1)
        digest=result['evidence_sha256'][0];url=self.path+'/valuations/run/evidence/'+digest
        self.assertEqual(self.f.client.get(url).content,html(product()));self.assertIn('text/plain',self.f.client.get(url).headers['content-type'])
        self.assertEqual(self.f.client.get(self.path+'/valuations/run/evidence/'+'a'*64).status_code,404)
        wrong=copy.deepcopy(req);wrong['market']['currency']='USD'
        self.assertEqual(self.f.client.post(self.path+'/valuations',json=wrong,headers=self.f.headers).status_code,422)
        cmd=dict(command_id='exclude',sweep_id=self.f.sweep['id'],expected_revision=1,operation='ownership',item_id='chair',reviewer='Fixture',reason='Not owned',new_owned=False)
        self.f.client.post(self.path,json=cmd,headers=self.f.headers)
        self.assertTrue(self.f.client.get(self.path+'/valuations/run').json()['stale'])
