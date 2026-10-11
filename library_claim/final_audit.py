"""M10 independent saved-source monetary checks and packet arithmetic."""
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

from .valuation import RetailCandidate, ValuationPolicy, retailer_quote, canonical
from .contents_pricing import ItemCandidate, ItemPricePolicy, item_quote


def money_quote(quote, market, policy, evidence):
    amount=Decimal(quote['amount'])
    converted=quote['currency']!=market['currency']
    foreign=quote['market_country']!=market['country']
    if bool(quote.get('foreign_market',foreign))!=foreign:raise ValueError('foreign market declaration mismatch')
    if foreign and not policy['allow_foreign_fallback']:raise ValueError('foreign market fallback not authorized')
    if converted:
        fx=quote.get('fx')
        if not fx:raise ValueError('FX evidence missing')
        raw=json.loads(evidence(fx['evidence_sha256']),parse_float=Decimal)
        if str(raw['base']).upper()!=quote['currency'] or str(raw['quote']).upper()!=market['currency']:
            raise ValueError('FX source currency pair mismatch')
        rate=Decimal(str(raw['rate']));actual=date.fromisoformat(raw['date'])
        if rate<=0 or not rate.is_finite() or rate!=Decimal(fx['rate']) or actual.isoformat()!=fx['date']:
            raise ValueError('FX literal evidence mismatch')
        requested=date.fromisoformat(policy['fx_date'])
        if not 0<=(requested-actual).days<=policy['max_fx_age_days']:raise ValueError('FX date outside policy')
        if fx['source_currency']!=quote['currency'] or fx['target_currency']!=market['currency']:raise ValueError('FX metadata currency mismatch')
        amount*=rate
    elif quote.get('fx'):raise ValueError('unexpected FX for same currency')
    if quote['market_country']==market['country'] and converted:raise ValueError('local offer currency mismatch')
    if converted and not policy['allow_foreign_fallback']:raise ValueError('foreign conversion not authorized')
    amount=amount.quantize(Decimal(1).scaleb(-market['decimal_places']),rounding=ROUND_HALF_EVEN if policy['rounding']=='half_even' else ROUND_HALF_UP)
    if quote['target_currency']!=market['currency'] or bool(quote['converted'])!=converted or amount!=Decimal(quote['target_amount']):raise ValueError('target price differs from independently computed amount')
    return amount


def verified_quote(quote, run, identity, market, component, evidence, frozen_at, item=False):
    request=run['request'];policy=request['policy'];raw=evidence(quote['evidence_sha256'])
    if date.fromisoformat(policy['fx_date'])>frozen_at.date():raise ValueError('future FX request date')
    candidates=[]
    for c in request['candidates']:
        if c['url']!=quote['url']:continue
        if item:
            if c['item_id']!=identity['item']['id']:continue
            candidate=ItemCandidate.model_validate(c)
            try:parsed=item_quote(raw,candidate,identity,ItemPricePolicy.model_validate(policy),frozen_at.date())
            except (ValueError,KeyError,TypeError,ArithmeticError):continue
        else:
            if c['track_id']!=identity['id'] or c['target_country']!=market['country'] or c['component']!=component:continue
            candidate=RetailCandidate.model_validate(c)
            try:parsed=retailer_quote(raw,candidate,identity,ValuationPolicy.model_validate(policy),frozen_at.date())
            except (ValueError,KeyError,TypeError,ArithmeticError):continue
        if all(canonical(parsed.get(k))==canonical(quote.get(k)) for k in parsed):candidates.append(parsed)
    if not candidates:raise ValueError('selected quote does not match a saved eligible source candidate')
    amount=money_quote(quote,market,policy,evidence)
    if not item and amount>=Decimal(str(market['appraisal_threshold'])):raise ValueError('amount requires appraisal')
    return amount


def totals_for(packet):
    books=packet['books'];items=packet['items'];policy=packet['aggregation_policy']
    thickness=[b['spine_thickness_cm'] for b in books]
    known=sum((Decimal(str(v)) for v in thickness if v is not None),Decimal(0))/100
    parts=[[b['replacement_cost']['amount'] is not None,b['used_value']['amount'] is not None] for b in books]
    parts += [[i['replacement_cost']['low'] is not None] for i in items]
    return dict(book_count=len(books),books_identified=sum(bool(b['title']) for b in books),books_unidentified=sum(not b['title'] for b in books),
        shelf_run_m=None if any(v is None for v in thickness) else known,
        books_replacement_cost=sum((Decimal(str(b['replacement_cost']['amount'])) for b in books if b['replacement_cost']['amount'] is not None),Decimal(0)),
        books_used_value=sum((Decimal(str(b['used_value']['amount'])) for b in books if b['used_value']['amount'] is not None),Decimal(0)),
        items_replacement_cost_low=sum((Decimal(str(i['replacement_cost']['low'])) for i in items if i['replacement_cost']['low'] is not None),Decimal(0)),
        items_replacement_cost_high=sum((Decimal(str(i['replacement_cost']['high'])) for i in items if i['replacement_cost']['high'] is not None),Decimal(0)),
        excluded_from_totals=sum(not all(p) if policy['exclusion_basis']=='missing_any_component' else not any(p) for p in parts))


def audit_packet(packet):
    if packet['totals']!=totals_for(packet):raise ValueError('independent total audit failed')
    if any(b['status']=='needs_appraisal' and (b['replacement_cost']['amount'] is not None or b['used_value']['amount'] is not None) for b in packet['books']):raise ValueError('appraisal book entered totals')
    if any(i['status']=='needs_appraisal' and i['replacement_cost']['low'] is not None for i in packet['items']):raise ValueError('appraisal item entered totals')
    if any(i['replacement_cost']['low'] is not None and i['replacement_cost']['high']<i['replacement_cost']['low'] for i in packet['items']):raise ValueError('invalid item range')
    quotes={q['id']:q['quote'] for q in packet['quote_manifest']}
    if len(quotes)!=len(packet['quote_manifest']):raise ValueError('duplicate final quote IDs')
    currency=packet['sweep']['currency']
    for book in packet['books']:
        for field,bases in [('replacement_cost',{'new_physical'}),('used_value',{'used_asking','used_sold'})]:
            p=book[field]
            if p['amount'] is None:continue
            q=quotes.get(p['quote_ref'])
            if q is None or Decimal(str(p['amount']))!=Decimal(q['target_amount']) or p['currency']!=currency or q['target_currency']!=currency or q['source_type'] not in bases or p['url']!=q['url'] or bool(p['converted'])!=bool(q['converted']):
                raise ValueError('book price/quote agreement audit failed')
    for item in packet['items']:
        p=item['replacement_cost']
        if p['low'] is None:continue
        selected=[quotes.get(ref) for ref in p['quote_refs']]
        if not selected or any(q is None or q['target_currency']!=currency or q['source_type']!='item_comparable' for q in selected) or p['currency']!=currency or Decimal(str(p['low']))!=min(Decimal(q['target_amount']) for q in selected) or Decimal(str(p['high']))!=max(Decimal(q['target_amount']) for q in selected):
            raise ValueError('item range/quote agreement audit failed')
    frame_ids={f['id'] for f in packet['evidence_manifest']}
    if any(e['frame_ref'] not in frame_ids for e in packet['books']+packet['items']):raise ValueError('packet frame does not resolve')
    return dict(passed=True,method='independent_decimal_line_sums_and_source_reparse',physical_accuracy_verified=False)


def spoken_summary(packet):
    totals=packet['totals'];currency=packet['sweep']['currency']
    return (("Synthetic fixture; not a real claim. " if packet['synthetic'] else "")+f"This is a {packet['packet_status']} evidence packet. It contains {totals['book_count']} reviewed owned book tracks, "
        f"including {totals['books_identified']} identified and {totals['books_unidentified']} unidentified, and {len(packet['items'])} billable owned non-book objects. "
        f"Priced book replacement subtotal is {totals['books_replacement_cost']} {currency}; priced book used subtotal is {totals['books_used_value']} {currency}. "
        f"Priced other contents replacement subtotal ranges from {totals['items_replacement_cost_low']} to {totals['items_replacement_cost_high']} {currency}. "
        f"{totals['excluded_from_totals']} inventory lines are excluded under the chosen pricing exclusion policy. "
        f"Floor area is {packet['room']['floor_area_m2'] if packet['room']['floor_area_m2'] is not None else 'unknown'} square metres. "
        f"Wall area is {packet['room']['wall_area_m2'] if packet['room']['wall_area_m2'] is not None else 'unknown'} square metres; "
        f"shelved wall area is {packet['room']['shelved_wall_area_m2'] if packet['room']['shelved_wall_area_m2'] is not None else 'unknown'} square metres. "
        f"There are {len(packet['review_queue'])} review findings. Unpriced and appraisal lines do not contribute to money totals; a zero subtotal may mean no priced lines. "
        "Physical room coverage and accuracy remain unverified. This archive will not change when later jobs or corrections arrive.")
