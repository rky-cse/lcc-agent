"""M07: explicit retailer offers, independent markets and dated Decimal FX.

Network work is opt-in. A retailer URL is a reviewed candidate, not a promise
of a price or a complete market search. Evidence and results are immutable.
"""
import argparse
import hashlib
import ipaddress
import json
import re
import socket
import time
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlencode

from pydantic import Field, field_validator, model_validator

from .capture_store import FrameStore
from .catalogue import normalize
from .identity import isbn_value
from .models import Contract, Number, Sweep
from .packet import json_text
from .tracking import TrackStore


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json_text(value).encode('utf-8')


class Market(Contract):
    country: str
    currency: str
    decimal_places: int = Field(ge=0, le=4)
    appraisal_threshold: Number
    _codes = field_validator('country', 'currency')(classmethod(Sweep.locale_code.__func__))


class ValuationPolicy(Contract):
    used_basis: Literal['used_asking', 'used_sold']
    used_condition: str = Field(min_length=1, max_length=200)
    fees: Literal['item_price_only']
    rounding: Literal['half_even', 'half_up']
    max_quote_age_hours: int = Field(ge=1, le=720)
    allow_equivalent_replacement: bool
    allow_foreign_fallback: bool
    fx_date: date
    max_fx_age_days: int = Field(ge=0, le=14)

    @field_validator('used_condition')
    @classmethod
    def nonblank_condition(cls, value):
        if not value.strip():
            raise ValueError('used condition must be a nonblank comparison grade')
        return value


class RetailCandidate(Contract):
    track_id: str = Field(min_length=1, max_length=128)
    target_country: str
    market_country: str
    url: str = Field(max_length=2000)
    product_id: str = Field(min_length=1, max_length=1000)
    offer_index: int = Field(ge=0, le=99)
    component: Literal['replacement', 'used']
    match_basis: Literal['exact_isbn', 'reviewed_equivalent_work']
    physical_format: Literal['hardcover', 'paperback', 'other_print']
    reviewer: str = Field(min_length=1, max_length=200)
    market_statement: str = Field(min_length=1, max_length=1000)
    equivalence_statement: str = Field(max_length=1000)

    @field_validator('reviewer', 'market_statement')
    @classmethod
    def nonblank_review(cls, value):
        if not value.strip():
            raise ValueError('reviewer and market statement must be nonblank')
        return value

    @field_validator('target_country', 'market_country')
    @classmethod
    def country(cls, value):
        if not re.fullmatch('[A-Z]{2}', value):
            raise ValueError('country needs an uppercase two-letter code')
        return value

    @field_validator('url')
    @classmethod
    def url_boundary(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in {None, 443}
                or any(ord(c) < 33 for c in value)):
            raise ValueError('retailer URL must be ordinary HTTPS without credentials or fragment')
        return value


class ValuationRequest(Contract):
    run_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    sweep_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    expected_revision: int = Field(ge=0)
    track_ids: list[str] = Field(min_length=1, max_length=100)
    markets: list[Market] = Field(min_length=1, max_length=2)
    policy: ValuationPolicy
    candidates: list[RetailCandidate] = Field(max_length=40)
    consent_fetch: Literal[True]

    @model_validator(mode='after')
    def coherent(self):
        if len(set(self.track_ids)) != len(self.track_ids):
            raise ValueError('duplicate physical track')
        countries = [m.country for m in self.markets]
        if len(set(countries)) != len(countries):
            raise ValueError('market countries must differ')
        if len(self.markets) == 2 and len(self.track_ids) != 10:
            raise ValueError('second-country comparison requires the same ten physical tracks')
        keys = []
        for c in self.candidates:
            if c.track_id not in self.track_ids or c.target_country not in countries:
                raise ValueError('candidate is outside this selection')
            keys.append((c.track_id, c.target_country, c.component, c.url, c.product_id, c.offer_index))
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate candidate')
        return self


class JSONLD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.parts = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'script':
            self.active = dict(attrs).get('type', '').lower() == 'application/ld+json'
            self.parts = []

    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.active:
            self.blocks.append(''.join(self.parts))
            self.active = False

    def handle_data(self, text):
        if self.active:
            self.parts.append(text)


def objects(value):
    if isinstance(value, list):
        for item in value:
            yield from objects(item)
    elif isinstance(value, dict):
        yield value
        for item in value.values():
            if isinstance(item, (dict, list)):
                yield from objects(item)


def schema_token(value):
    return str(value).rstrip('/').rsplit('/', 1)[-1].rsplit('#', 1)[-1]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate source JSON key')
        result[key] = value
    return result


def format_of(product):
    value = schema_token(product.get('bookFormat', ''))
    return {'Hardcover': 'hardcover', 'Paperback': 'paperback', 'PrintBook': 'other_print'}.get(value)


def retailer_quote(raw, candidate, book, policy, as_of=None):
    """No guessed currency, price, availability, binding, condition or identity."""
    parser = JSONLD()
    parser.feed(raw.decode('utf-8', errors='strict'))
    matches = []
    for block in parser.blocks:
        try:
            document = json.loads(block, parse_float=Decimal, object_pairs_hook=unique_object)
        except (ValueError, RecursionError):
            continue
        for obj in objects(document):
            types = obj.get('@type', [])
            if not isinstance(types, list):
                types = [types]
            if any(schema_token(t) in {'Book', 'Product'} for t in types):
                if candidate.product_id in {obj.get('@id'), obj.get('url'), obj.get('sku')}:
                    matches.append(obj)
    if len(matches) != 1:
        raise ValueError('selected product is absent or ambiguous')
    product = matches[0]
    physical = format_of(product)
    if physical is None or physical != candidate.physical_format:
        raise ValueError('physical book format is absent or differs from review')
    if normalize(product.get('name', '')) != normalize(book['title']):
        raise ValueError('product title differs from reviewed book')
    authors = product.get('author', [])
    if not isinstance(authors, list):
        authors = [authors]
    names = [a.get('name', '') if isinstance(a, dict) else str(a) for a in authors]
    if not book['author'] or normalize(book['author']) not in [normalize(n) for n in names]:
        raise ValueError('product author is absent or differs from reviewed book')
    if candidate.match_basis == 'exact_isbn':
        if not book['isbn'] or not product.get('isbn'):
            raise ValueError('exact edition requires both reviewed and source ISBN')
        if isbn_value(book['isbn']) != isbn_value(str(product['isbn'])):
            raise ValueError('source ISBN differs from reviewed edition')
    elif (candidate.component != 'replacement' or not policy.allow_equivalent_replacement
            or not candidate.equivalence_statement.strip()):
        raise ValueError('equivalent work is permitted only for explicitly reviewed replacement')
    offers = product.get('offers', [])
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list) or candidate.offer_index >= len(offers):
        raise ValueError('selected offer is absent')
    offer = offers[candidate.offer_index]
    if not isinstance(offer, dict) or schema_token(offer.get('@type', '')) != 'Offer':
        raise ValueError('aggregate/range offers cannot be literal quotes')
    if schema_token(offer.get('availability', '')) != 'InStock':
        raise ValueError('offer is not explicitly in stock')
    if offer.get('priceValidUntil') and date.fromisoformat(str(offer['priceValidUntil'])) < (as_of or datetime.now(timezone.utc).date()):
        raise ValueError('source price validity has expired')
    if 'eligibleRegion' in offer:
        regions = offer['eligibleRegion']
        if not isinstance(regions, list):
            regions = [regions]
        codes = [r.get('identifier', r.get('addressCountry', '')) if isinstance(r, dict) else r for r in regions]
        if candidate.market_country not in codes:
            raise ValueError('source eligible region contradicts reviewed market')
    condition = schema_token(offer.get('itemCondition', ''))
    if candidate.component == 'replacement':
        if condition != 'NewCondition':
            raise ValueError('replacement requires explicitly new condition')
        basis, condition_label = 'new_physical', 'NewCondition'
    else:
        if policy.used_basis == 'used_sold':
            raise ValueError('retailer asking offers do not establish completed sales')
        if condition != 'UsedCondition':
            raise ValueError('used value requires explicitly used condition')
        # A generic UsedCondition does not establish Very Good or any other grade.
        condition_label = offer.get('description', '')
        if normalize(condition_label) != normalize(policy.used_condition):
            raise ValueError('listed used condition differs from declared comparison condition')
        basis = 'used_asking'
    currency = offer.get('priceCurrency', '')
    if not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
        raise ValueError('literal uppercase price currency required')
    literal = str(offer.get('price', ''))
    if not re.fullmatch(r'\d+(?:\.\d{1,8})?', literal):
        raise ValueError('single nonnegative literal decimal price required')
    amount = Decimal(literal)
    if amount > Decimal('1000000000'):
        raise ValueError('price exceeds supported monetary range')
    return dict(amount=str(amount), currency=currency, source_type=basis,
                condition=condition_label, physical_format=physical, available=True,
                product=product, offer=offer, literal_price=literal,
                market_country=candidate.market_country, market_basis='explicit_reviewer_statement',
                reviewer=candidate.reviewer, market_statement=candidate.market_statement,
                match_basis=candidate.match_basis, equivalence_statement=candidate.equivalence_statement,
                source='retailer_jsonld', url=candidate.url)


class PublicHTTPS:
    """Pin public DNS addresses for the request, with TLS host verification.

    DNS rebinding is prevented by connecting to the checked address; redirects
    and proxies are not followed. Tests supply an injected transport instead.
    """
    def __call__(self, url):
        import http.client
        import ssl
        import time
        parsed = urlsplit(url)
        RetailCandidate.url_boundary(url)
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('source host is not public')
        deadline = time.monotonic() + 20
        address = addresses[0][4]
        class Pinned(http.client.HTTPSConnection):
            def connect(connection):
                sock = socket.socket(addresses[0][0], socket.SOCK_STREAM)
                sock.settimeout(max(.1, deadline-time.monotonic()))
                try:
                    sock.connect(address)
                    connection.sock = connection._context.wrap_socket(sock, server_hostname=parsed.hostname)
                except BaseException:
                    sock.close()
                    raise
        connection = Pinned(parsed.hostname, timeout=20, context=ssl.create_default_context())
        try:
            connection.request('GET', parsed.path + ('?' + parsed.query if parsed.query else '') or '/',
                               headers={'User-Agent': 'LibraryContentsClaim/0.1', 'Accept': 'text/html, application/json',
                                        'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError('source unavailable (HTTP status %s)' % response.status)
            chunks, size = [], 0
            while True:
                connection.sock.settimeout(max(.1, deadline-time.monotonic())) if connection.sock else None
                if time.monotonic() >= deadline:
                    raise TimeoutError('source deadline exceeded')
                block = response.read1(65536)
                if not block:
                    break
                size += len(block)
                if size > 2*1024*1024:
                    raise ValueError('source response exceeds 2 MiB')
                chunks.append(block)
            return b''.join(chunks)
        finally:
            connection.close()


class ValuationStore:
    def __init__(self, frames, *, fetch=None, inventory=None, clock=None):
        self.frames = frames
        self.inventory = inventory or TrackStore(frames)
        self.fetch = fetch or PublicHTTPS()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with closing(frames._connect()) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS valuation_runs
                (id TEXT PRIMARY KEY, request BLOB NOT NULL, status TEXT NOT NULL, result BLOB, sha TEXT);
                CREATE TABLE IF NOT EXISTS valuation_evidence
                (sha TEXT PRIMARY KEY, content BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS valuation_cache
                (key TEXT PRIMARY KEY, sha TEXT NOT NULL, retrieved TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS valuation_gate (host TEXT PRIMARY KEY, next_at REAL NOT NULL);''')

    def _evidence(self, raw):
        key = sha(raw)
        with closing(self.frames._connect()) as db:
            db.execute('INSERT OR IGNORE INTO valuation_evidence VALUES (?,?)', (key, raw))
            db.commit()
        return key

    def evidence(self, key):
        with closing(self.frames._connect()) as db:
            row = db.execute('SELECT content FROM valuation_evidence WHERE sha=?', (key,)).fetchone()
        if row is None:
            raise KeyError('unknown valuation evidence')
        if sha(row[0]) != key:
            raise ValueError('valuation evidence hash mismatch')
        return row[0]

    def _source(self, url, market, policy):
        key = sha(canonical(dict(url=url, market=market.model_dump(), policy=policy.model_dump(mode='json'))))
        now = self.clock()
        with closing(self.frames._connect()) as db:
            row = db.execute('SELECT sha,retrieved FROM valuation_cache WHERE key=?', (key,)).fetchone()
            if row and 0 <= (now-datetime.fromisoformat(row[1])).total_seconds() <= policy.max_quote_age_hours*3600:
                return self.evidence(row[0]), row[0], row[1]
            host = urlsplit(url).hostname
            db.execute('BEGIN IMMEDIATE')
            gate = db.execute('SELECT next_at FROM valuation_gate WHERE host=?', (host,)).fetchone()
            delay = max(0, gate[0]-now.timestamp()) if gate else 0
            if delay > 2:
                raise ValueError('source rate limited; explicit later retry required')
            db.execute('INSERT OR REPLACE INTO valuation_gate VALUES (?,?)', (host, now.timestamp()+delay+1))
            db.commit()
        if delay:
            time.sleep(delay)
        raw = self.fetch(url)
        if not isinstance(raw, bytes) or not raw or len(raw) > 2*1024*1024:
            raise ValueError('source returned invalid or oversized bytes')
        digest = self._evidence(raw)
        with closing(self.frames._connect()) as db:
            db.execute('INSERT OR REPLACE INTO valuation_cache VALUES (?,?,?)', (key, digest, now.isoformat()))
            db.commit()
        return raw, digest, now.isoformat()

    def _fx(self, source, market, policy, evidence):
        url = ('https://api.frankfurter.dev/v2/rate/' + source.lower() + '/' + market.currency.lower()
               + '?' + urlencode({'date': policy.fx_date.isoformat(), 'providers': 'ecb'}))
        raw, digest, retrieved = self._source(url, market, policy)
        evidence.add(digest)
        row = json.loads(raw, parse_float=Decimal, object_pairs_hook=unique_object)
        if (not isinstance(row, dict) or str(row.get('base', '')).upper() != source
                or str(row.get('quote', '')).upper() != market.currency):
            raise ValueError('FX currency pair differs from requested pair')
        actual = date.fromisoformat(row['date'])
        if not 0 <= (policy.fx_date-actual).days <= policy.max_fx_age_days:
            raise ValueError('FX observation outside approved date window')
        rate = Decimal(str(row['rate']))
        if not rate.is_finite() or rate <= 0:
            raise ValueError('FX rate must be positive and finite')
        return dict(rate=str(rate), date=actual.isoformat(), requested_date=policy.fx_date.isoformat(),
                    source_currency=source, target_currency=market.currency, source='Frankfurter ECB',
                    url=url, evidence_sha256=digest, retrieved_at=retrieved)

    def get(self, run_id, sweep_id=None):
        with closing(self.frames._connect()) as db:
            row = db.execute('SELECT request,status,result,sha FROM valuation_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError('unknown valuation run')
        request = json.loads(row[0])
        if sweep_id is not None and request['sweep_id'] != sweep_id:
            raise KeyError('unknown valuation run in this sweep')
        if row[2] is None:
            return dict(run_id=run_id, sweep_id=request['sweep_id'], status=row[1],
                        reason='Interrupted/running run never supplies prices; choose a fresh run ID after interruption')
        if sha(row[2]) != row[3]:
            raise ValueError('valuation result hash mismatch')
        result = json.loads(row[2])
        for digest in result['evidence_sha256']:
            self.evidence(digest)
        current = self.inventory.snapshot(request['sweep_id'])
        result['stale'] = current['revision'] != request['expected_revision']
        policy = ValuationPolicy.model_validate(request['policy'])
        ages = [(self.clock()-datetime.fromisoformat(r[c]['retrieved_at'])).total_seconds()
                for market in result['markets'] for r in market['rows']
                for c in ('replacement', 'used', 'appraisal_quote') if r.get(c)]
        result['quotes_expired'] = any(not 0 <= age <= policy.max_quote_age_hours*3600 for age in ages)
        result['usable_for_current_inventory'] = not result['stale'] and not result['quotes_expired']
        result['result_sha256'] = row[3]
        return result

    def run(self, request):
        encoded = canonical(request.model_dump(mode='json'))
        with closing(self.frames._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT request FROM valuation_runs WHERE id=?', (request.run_id,)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ValueError('run ID reused with different payload')
                return self.get(request.run_id, request.sweep_id)
            snapshot = self.inventory.snapshot(request.sweep_id)
            if snapshot['revision'] != request.expected_revision:
                raise ValueError('stale inventory revision')
            selected = {b['id']: b for b in snapshot['books'] if b['id'] in request.track_ids}
            if len(selected) != len(request.track_ids):
                raise ValueError('selected track is absent from inventory')
            if len(request.markets) == 2 and any(b['status'] != 'identified' for b in selected.values()):
                raise ValueError('second-country comparison requires ten identified physical books')
            if request.policy.fx_date > self.clock().date():
                raise ValueError('FX date is in the future')
            db.execute('INSERT INTO valuation_runs VALUES (?,?,?,NULL,NULL)', (request.run_id, encoded, 'running'))
            db.commit()
        evidence = set()
        markets = []
        deadline = time.monotonic()+120
        try:
            for market in request.markets:
                rows = []
                for track in request.track_ids:
                    book = selected[track]
                    row = dict(track_id=track, identity=book, status=book['status'], replacement=None, used=None, findings=[], attempts=[])
                    if not book['owned'] or book['status'] != 'identified':
                        row['findings'].append('not owned, unidentified or appraisal required; excluded')
                        rows.append(row)
                        continue
                    for component in ('replacement', 'used'):
                        candidates = [c for c in request.candidates if c.track_id == track
                                      and c.target_country == market.country and c.component == component]
                        local = [c for c in candidates if c.market_country == market.country]
                        foreign = [c for c in candidates if c.market_country != market.country]
                        chosen = []
                        for group in (local, foreign):
                            if group is foreign and (chosen or not local or not request.policy.allow_foreign_fallback):
                                continue
                            for candidate in group:
                                attempt = dict(component=component, url=candidate.url,
                                               market_country=candidate.market_country, outcome='unavailable')
                                row['attempts'].append(attempt)
                                try:
                                    if time.monotonic() >= deadline:
                                        raise ValueError('run network budget exhausted; explicit later run required')
                                    raw, digest, retrieved = self._source(candidate.url, market, request.policy)
                                    evidence.add(digest)
                                    attempt['evidence_sha256'] = digest
                                    quote = retailer_quote(raw, candidate, book, request.policy, self.clock().date())
                                    quote.update(evidence_sha256=digest, retrieved_at=retrieved)
                                    amount = Decimal(quote['amount'])
                                    converted = False
                                    if candidate.market_country == market.country and quote['currency'] != market.currency:
                                        raise ValueError('local source currency differs from requested currency')
                                    if quote['currency'] != market.currency:
                                        fx = self._fx(quote['currency'], market, request.policy, evidence)
                                        evidence.add(fx['evidence_sha256'])
                                        amount *= Decimal(fx['rate'])
                                        quote['fx'] = fx
                                        converted = True
                                    quantum = Decimal(1).scaleb(-market.decimal_places)
                                    rounded = amount.quantize(quantum, rounding=ROUND_HALF_EVEN if request.policy.rounding == 'half_even' else ROUND_HALF_UP)
                                    quote.update(target_amount=str(rounded), target_currency=market.currency,
                                                 converted=converted, foreign_market=candidate.market_country != market.country,
                                                 fees=request.policy.fees)
                                    chosen.append(quote)
                                    attempt['outcome'] = 'eligible'
                                except (ValueError, TypeError, KeyError, OSError, ArithmeticError, RecursionError) as error:
                                    # URL/source content cannot write arbitrary provider errors into UI/logs.
                                    attempt['reason'] = (str(error)[:300] if type(error) is ValueError
                                                         else 'source request or evidence validation failed')
                            if chosen:
                                break
                        if chosen:
                            # A disclosed deterministic selection, not a fair-market appraisal.
                            quote = min(chosen, key=lambda q: Decimal(q['target_amount']))
                            if Decimal(quote['target_amount']) >= market.appraisal_threshold:
                                row['status'] = 'needs_appraisal'
                                row['appraisal_quote'] = quote
                                row['findings'].append(component + ': amount meets caller appraisal threshold; excluded')
                                break
                            else:
                                row[component] = quote
                        else:
                            row['findings'].append(component + ': no eligible quote; no amount')
                    if row['status'] == 'needs_appraisal':
                        row['replacement'] = row['used'] = None
                    rows.append(row)
                totals = {c: str(sum((Decimal(r[c]['target_amount']) for r in rows if r[c]), Decimal(0)))
                          for c in ('replacement', 'used')}
                markets.append(dict(market=market.model_dump(mode='json'), rows=rows, totals=totals,
                                    priced_counts={c: sum(r[c] is not None for r in rows) for c in totals}))
            result = dict(schema_version='1.0', module='M07', run_id=request.run_id, sweep_id=request.sweep_id,
                          inventory_revision=request.expected_revision, track_ids=request.track_ids,
                          request=request.model_dump(mode='json'), request_sha256=sha(encoded),
                          policy=request.policy.model_dump(mode='json'), markets=markets,
                          selection_rule='lowest eligible quoted item price from supplied candidates; local first',
                          market_search_complete=False, evidence_sha256=sorted(evidence),
                          created_at=self.clock().isoformat(), status='complete', packet_ready=False,
                          coverage_verified=False)
            raw = canonical(result)
            with closing(self.frames._connect()) as db:
                db.execute('UPDATE valuation_runs SET status=?,result=?,sha=? WHERE id=?',
                           ('complete', raw, sha(raw), request.run_id))
                db.commit()
        except BaseException:
            with closing(self.frames._connect()) as db:
                db.execute('UPDATE valuation_runs SET status=? WHERE id=?', ('interrupted', request.run_id))
                db.commit()
            raise
        return self.get(request.run_id, request.sweep_id)


def main():
    parser = argparse.ArgumentParser(description='M07 explicit source-backed book valuation')
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('choose a fresh result path')
    request = ValuationRequest.model_validate_json(args.request.read_text(encoding='utf-8'))
    result = ValuationStore(FrameStore(args.store)).run(request)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json_text(result)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
