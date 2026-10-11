"""M08b: reviewed exact products or defensible physical comparable ranges."""
import argparse
import json
import re
import time
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .capture_store import FrameStore
from .catalogue import normalize
from .contents import Axis, ContentsStore, Token, Text
from .models import Contract, Number
from .valuation import (JSONLD, Market, RetailCandidate, ValuationStore, canonical, objects,
                        schema_token, sha, unique_object)


class ItemPricePolicy(Contract):
    ordinary_unpriced_status: Literal['', 'needs_appraisal']
    aggregation: Literal['min_max']
    min_comparables: int = Field(ge=2,le=10)
    min_distinct_domains: int = Field(ge=1,le=10)
    required_axes: list[Axis] = Field(min_length=1,max_length=3)
    size_tolerance_fraction: Decimal = Field(ge=0,le=Decimal('.5'),allow_inf_nan=False)
    fees: Literal['item_price_only']
    rounding: Literal['half_even','half_up']
    max_quote_age_hours: int = Field(ge=1,le=720)
    allow_foreign_fallback: bool
    fx_date: date
    max_fx_age_days: int = Field(ge=0,le=14)

    @model_validator(mode='after')
    def axes(self):
        if len(set(self.required_axes))!=len(self.required_axes):raise ValueError('duplicate required dimension axis')
        if self.min_distinct_domains>self.min_comparables:raise ValueError('domain minimum exceeds comparable minimum')
        return self


class ItemCandidate(Contract):
    item_id: Token
    url: str = Field(max_length=2000)
    product_id: Text
    offer_index: int = Field(ge=0,le=99)
    market_country: str = Field(pattern=r'^[A-Z]{2}$')
    market_statement: Text
    physical_statement: Text
    reviewer: Text
    match_basis: Literal['exact_model','reviewed_comparable']
    comparable_statement: Text

    @model_validator(mode='after')
    def url_check(self):
        RetailCandidate.url_boundary(self.url)
        return self


class ItemValuationRequest(Contract):
    run_id: Token
    sweep_id: Token
    expected_revision: int = Field(ge=0)
    item_ids: list[Token] = Field(min_length=1,max_length=100)
    market: Market
    policy: ItemPricePolicy
    candidates: list[ItemCandidate] = Field(max_length=40)
    consent_fetch: Literal[True]

    @model_validator(mode='after')
    def scope(self):
        if len(set(self.item_ids))!=len(self.item_ids):raise ValueError('duplicate physical item selection')
        keys=[]
        for candidate in self.candidates:
            if candidate.item_id not in self.item_ids:raise ValueError('candidate is outside the selected items')
            keys.append((candidate.item_id,candidate.url,candidate.product_id,candidate.offer_index))
        if len(set(keys))!=len(keys):raise ValueError('duplicate item quote candidate')
        return self


def quantity_cm(value):
    if not isinstance(value,dict) or schema_token(value.get('@type',''))!='QuantitativeValue':
        raise ValueError('comparable dimension must be a literal QuantitativeValue')
    if value.get('unitCode')=='CMT' or value.get('unitText')=='cm':factor=Decimal(1)
    elif value.get('unitCode')=='MTR' or value.get('unitText')=='m':factor=Decimal(100)
    else:raise ValueError('comparable dimension has unsupported/missing metric unit')
    literal=str(value.get('value',''))
    if not re.fullmatch(r'\d+(?:\.\d{1,8})?',literal):raise ValueError('comparable dimension requires a single literal decimal')
    amount=Decimal(literal)*factor
    if not 0<amount<=Decimal('100000'):raise ValueError('comparable dimension outside supported range')
    return amount


def item_quote(raw,candidate,row,policy,as_of):
    parser=JSONLD();parser.feed(raw.decode('utf-8',errors='strict'))
    matches=[]
    for block in parser.blocks:
        try:document=json.loads(block,parse_float=Decimal,object_pairs_hook=unique_object)
        except (ValueError,RecursionError):continue
        for obj in objects(document):
            types=obj.get('@type',[])
            if not isinstance(types,list):types=[types]
            if any(schema_token(t) in {'Product','IndividualProduct','ProductModel'} for t in types):
                if candidate.product_id in {obj.get('@id'),obj.get('url'),obj.get('sku')}:matches.append(obj)
    if len(matches)!=1:raise ValueError('selected physical product is absent or ambiguous')
    product=matches[0];item=row['item']
    if (product.get('downloadUrl') or product.get('isDigital') is True
            or schema_token(product.get('bookFormat','')) in {'EBook','Audiobook','AudioBook'}):
        raise ValueError('digital/service product cannot establish physical replacement')
    if not isinstance(product.get('category'),str) or normalize(product['category'])!=normalize(item['category']):
        raise ValueError('comparable function/category differs from reviewed physical item')
    comparison={}
    if candidate.match_basis=='exact_model':
        labels=row['labels']
        if any(not labels.get(k) or labels[k]['basis']!='visible_marking' for k in ('brand','model')):
            raise ValueError('exact model requires both reviewed visible brand and model markings')
        brand=product.get('brand',{});brand=brand.get('name','') if isinstance(brand,dict) else brand
        model=product.get('model',{});model=model.get('name','') if isinstance(model,dict) else model
        if normalize(brand)!=normalize(labels['brand']['value']) or normalize(model)!=normalize(labels['model']['value']):
            raise ValueError('source brand/model differs from reviewed literal markings')
    else:
        material=product.get('material','')
        if not row['material'] or not isinstance(material,str) or normalize(material)!=normalize(row['material']):
            raise ValueError('comparable material is absent or differs from reviewed material basis')
        for axis in policy.required_axes:
            target=item['dimensions_cm'][axis]
            if target is None or axis not in row['dimension_proofs']:
                raise ValueError('required size axis is unknown; hidden dimensions cannot be inferred')
            source=quantity_cm(product.get({'w':'width','h':'height','d':'depth'}[axis]))
            target=Decimal(str(target))
            if abs(source-target)/target>policy.size_tolerance_fraction:
                raise ValueError('comparable size exceeds declared tolerance')
            comparison[axis]=dict(owned_cm=str(target),source_cm=str(source),
                                  proof_sha256=row['dimension_proofs'][axis]['artifact_sha256'])
    offers=product.get('offers',[])
    if isinstance(offers,dict):offers=[offers]
    if not isinstance(offers,list) or candidate.offer_index>=len(offers):raise ValueError('selected offer is absent')
    offer=offers[candidate.offer_index]
    if not isinstance(offer,dict) or schema_token(offer.get('@type',''))!='Offer':raise ValueError('range/aggregate offers cannot establish literal prices')
    if schema_token(offer.get('availability',''))!='InStock':raise ValueError('replacement offer is not explicitly in stock')
    if schema_token(offer.get('itemCondition',''))!='NewCondition':raise ValueError('replacement requires explicitly new condition')
    if offer.get('businessFunction') and schema_token(offer['businessFunction'])!='Sell':raise ValueError('rental/service offers cannot establish replacement')
    if offer.get('priceValidUntil') and date.fromisoformat(str(offer['priceValidUntil']))<as_of:raise ValueError('source price validity has expired')
    if 'eligibleRegion' in offer:
        regions=offer['eligibleRegion'];regions=regions if isinstance(regions,list) else [regions]
        codes=[r.get('identifier',r.get('addressCountry','')) if isinstance(r,dict) else r for r in regions]
        if candidate.market_country not in codes:raise ValueError('source market region contradicts review')
    literal=str(offer.get('price',''));currency=offer.get('priceCurrency','')
    if not re.fullmatch(r'\d+(?:\.\d{1,8})?',literal) or Decimal(literal)>Decimal('1000000000'):
        raise ValueError('single supported literal decimal price required')
    if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):raise ValueError('explicit quote currency required')
    return dict(amount=literal,currency=currency,literal_price=literal,condition='NewCondition',
                source_type='item_comparable',source='retailer_jsonld',url=candidate.url,product=product,offer=offer,
                market_country=candidate.market_country,market_basis='explicit_reviewer_statement',
                market_statement=candidate.market_statement,physical_statement=candidate.physical_statement,
                reviewer=candidate.reviewer,match_basis=candidate.match_basis,
                comparable_statement=candidate.comparable_statement,size_comparison=comparison,
                material_basis=row['labels'].get('material'),art_basis=row.get('art'))


class ContentsPricing(ValuationStore):
    def __init__(self,frames,**kwargs):
        super().__init__(frames,inventory=ContentsStore(frames),**kwargs)
        with closing(frames._connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS contents_price_runs (id TEXT PRIMARY KEY,request BLOB NOT NULL,status TEXT NOT NULL,result BLOB,sha TEXT)');db.commit()

    def get(self,run_id,sweep_id=None):
        with closing(self.frames._connect()) as db:
            row=db.execute('SELECT request,status,result,sha FROM contents_price_runs WHERE id=?',(run_id,)).fetchone()
        if row is None:raise KeyError('unknown contents valuation run')
        request=json.loads(row[0])
        if sweep_id is not None and request['sweep_id']!=sweep_id:raise KeyError('unknown contents run in this sweep')
        if row[2] is None:return dict(run_id=run_id,sweep_id=request['sweep_id'],status=row[1],reason='No usable prices; interrupted runs require a new explicit run ID')
        if sha(row[2])!=row[3]:raise ValueError('contents valuation result hash mismatch')
        result=json.loads(row[2])
        for digest in result['evidence_sha256']:self.evidence(digest)
        current=self.inventory.snapshot(request['sweep_id'])
        result['stale']=current['inventory_sha256']!=result['inventory_sha256']
        ages=[(self.clock()-datetime.fromisoformat(q['retrieved_at'])).total_seconds() for r in result['rows'] for q in r['quotes']]
        result['quotes_expired']=any(not 0<=age<=request['policy']['max_quote_age_hours']*3600 for age in ages)
        result['usable_for_current_inventory']=not result['stale'] and not result['quotes_expired']
        result['result_sha256']=row[3]
        return result

    def run(self,request):
        encoded=canonical(request.model_dump(mode='json'))
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT request FROM contents_price_runs WHERE id=?',(request.run_id,)).fetchone()
            if old:
                if old[0]!=encoded:raise ValueError('run ID reused with different payload')
                return self.get(request.run_id,request.sweep_id)
            inventory=self.inventory.snapshot(request.sweep_id)
            if inventory['revision']!=request.expected_revision:raise ValueError('stale contents revision')
            selected={r['item']['id']:r for r in inventory['rows'] if r['item']['id'] in request.item_ids}
            if len(selected)!=len(request.item_ids):raise ValueError('selected physical item is absent')
            if request.policy.fx_date>self.clock().date():raise ValueError('FX date is in the future')
            db.execute('INSERT INTO contents_price_runs VALUES (?,?,?,NULL,NULL)',(request.run_id,encoded,'running'));db.commit()
        rows=[];evidence=set();deadline=time.monotonic()+120
        try:
            for key in request.item_ids:
                source=selected[key];item=dict(source['item']);item['replacement_cost']=dict(low=None,high=None,source='',url='',retrieved_at=None,quote_refs=[],condition_assumed='',currency='')
                row=dict(item=item,source=source,quotes=[],attempts=[],findings=[],quote_basis=None)
                if not source['billable'] or item['status']=='needs_appraisal' or not item['category']:
                    row['findings'].append('excluded ownership/group, appraisal or unknown category; no automatic valuation')
                    if not item['category'] and item['status']!='needs_appraisal':item['status']=request.policy.ordinary_unpriced_status
                    rows.append(row);continue
                candidates=[c for c in request.candidates if c.item_id==key]
                local=[c for c in candidates if c.market_country==request.market.country]
                foreign=[c for c in candidates if c.market_country!=request.market.country]
                selected_quotes=[]
                for group in (local,foreign):
                    if group is foreign and (selected_quotes or not local or not request.policy.allow_foreign_fallback):continue
                    eligible=[]
                    for candidate in group:
                        attempt=dict(url=candidate.url,market_country=candidate.market_country,match_basis=candidate.match_basis,outcome='unavailable');row['attempts'].append(attempt)
                        try:
                            if time.monotonic()>=deadline:raise ValueError('run network budget exhausted; explicit later run required')
                            raw,digest,retrieved=self._source(candidate.url,request.market,request.policy)
                            evidence.add(digest);attempt['evidence_sha256']=digest
                            quote=item_quote(raw,candidate,source,request.policy,self.clock().date())
                            quote.update(evidence_sha256=digest,retrieved_at=retrieved)
                            amount=Decimal(quote['amount']);converted=False
                            if candidate.market_country==request.market.country and quote['currency']!=request.market.currency:raise ValueError('local currency mismatch; no relabeling/conversion')
                            if quote['currency']!=request.market.currency:
                                quote['fx']=self._fx(quote['currency'],request.market,request.policy,evidence)
                                amount*=Decimal(quote['fx']['rate']);converted=True
                            amount=amount.quantize(Decimal(1).scaleb(-request.market.decimal_places),rounding=ROUND_HALF_EVEN if request.policy.rounding=='half_even' else ROUND_HALF_UP)
                            quote.update(target_amount=str(amount),target_currency=request.market.currency,converted=converted,
                                         foreign_market=candidate.market_country!=request.market.country,fees=request.policy.fees)
                            quote['id']='itemquote-'+sha(canonical(quote))[:32]
                            eligible.append(quote);attempt['outcome']='eligible'
                        except (ValueError,TypeError,KeyError,OSError,ArithmeticError,RecursionError) as error:
                            attempt['reason']=str(error)[:300] if type(error) is ValueError else 'source request or evidence validation failed'
                    exact=[q for q in eligible if q['match_basis']=='exact_model']
                    unique={}
                    for q in eligible:
                        if q['match_basis']=='reviewed_comparable':
                            identity=(q['evidence_sha256'],q['product'].get('@id',q['product'].get('sku',q['product'].get('url'))))
                            if identity not in unique or Decimal(q['target_amount'])<Decimal(unique[identity]['target_amount']):
                                unique[identity]=q
                    comparable=list(unique.values())
                    from urllib.parse import urlsplit
                    if exact:
                        selected_quotes=[min(exact,key=lambda q:Decimal(q['target_amount']))];row['quote_basis']='exact_model'
                    elif len(comparable)>=request.policy.min_comparables and len({urlsplit(q['url']).hostname.encode('idna').decode().rstrip('.') for q in comparable})>=request.policy.min_distinct_domains:
                        selected_quotes=comparable;row['quote_basis']='reviewed_comparable_min_max'
                    if selected_quotes:break
                row['quotes']=selected_quotes
                if selected_quotes:
                    low=min(Decimal(q['target_amount']) for q in selected_quotes);high=max(Decimal(q['target_amount']) for q in selected_quotes)
                    if high>=request.market.appraisal_threshold:
                        item['status']='needs_appraisal';row['findings'].append('range/exact amount reaches caller appraisal threshold; both bounds excluded')
                    else:
                        first=selected_quotes[0]
                        item['status']='priced' if low==high else 'range'
                        item['replacement_cost']=dict(low=str(low),high=str(high),source=first['source'],url=first['url'],
                           retrieved_at=first['retrieved_at'],quote_refs=[q['id'] for q in selected_quotes],
                           condition_assumed='NewCondition',currency=request.market.currency)
                else:
                    item['status']=request.policy.ordinary_unpriced_status
                    row['findings'].append('no eligible exact quote or enough defensible comparables; both bounds unavailable')
                rows.append(row)
            totals={bound:str(sum((Decimal(r['item']['replacement_cost'][bound]) for r in rows if r['item']['replacement_cost'][bound] is not None),Decimal(0))) for bound in ('low','high')}
            result=dict(schema_version='1.0',module='M08',run_id=request.run_id,sweep_id=request.sweep_id,
                status='complete',inventory_sha256=inventory['inventory_sha256'],inventory_revision=request.expected_revision,
                request=request.model_dump(mode='json'),request_sha256=sha(encoded),market=request.market.model_dump(mode='json'),
                rows=rows,totals=totals,priced_count=sum(r['item']['replacement_cost']['low'] is not None for r in rows),
                evidence_sha256=sorted(evidence),market_search_complete=False,packet_ready=False,coverage_verified=False,
                created_at=self.clock().isoformat())
            raw=canonical(result)
            with closing(self.frames._connect()) as db:
                db.execute('UPDATE contents_price_runs SET status=?,result=?,sha=? WHERE id=?',('complete',raw,sha(raw),request.run_id));db.commit()
        except BaseException:
            with closing(self.frames._connect()) as db:
                db.execute('UPDATE contents_price_runs SET status=? WHERE id=?',('interrupted',request.run_id));db.commit()
            raise
        return self.get(request.run_id,request.sweep_id)


def main():
    parser=argparse.ArgumentParser(description='M08 explicit non-book comparable pricing')
    parser.add_argument('--store',type=Path,required=True);parser.add_argument('--request',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('choose a fresh output path')
    result=ContentsPricing(FrameStore(args.store)).run(ItemValuationRequest.model_validate_json(args.request.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(canonical(result)+b'\n')


if __name__=='__main__':main()
