"""Offline M11 evaluation. Never imported by capture, recognition or pricing.

Human truth and physical matching are explicit inputs, not a runtime catalogue.
Hashes bind inputs; they do not prove an annotator's independence or honesty.
"""
import argparse
import csv
import hashlib
import html
import io
import json
import statistics
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import Contract, Confidence, Number, Sweep
from .packet import json_text
from .final_audit import audit_packet, spoken_summary, verified_quote

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json_text(value).encode('utf-8')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_float=Decimal,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


class PriceTruth(Contract):
    component: Literal['replacement_cost', 'used_value']
    availability: Literal['available', 'unavailable']
    amount: Positive | None
    source_type: Literal['new_physical', 'used_asking', 'used_sold'] | None
    condition: str
    country: str
    currency: str
    fees: Literal['item_price_only']
    url: str
    retrieved_at: datetime
    edition_basis: Text
    evidence: Text

    @model_validator(mode='after')
    def valid(self):
        Sweep.timezone_required(self.retrieved_at)
        if self.availability == 'available':
            if self.amount is None or self.source_type is None or not self.condition or not self.url.startswith('https://'):
                raise ValueError('available truth needs amount, source type, condition and HTTPS source')
            if (self.component == 'replacement_cost') != (self.source_type == 'new_physical'):
                raise ValueError('price component/source type mismatch')
        elif self.amount is not None:
            raise ValueError('unavailable truth cannot have an amount')
        return self


class TruthBook(Contract):
    id: Text
    location: Text
    owned: bool
    legible: bool
    title: str
    author: str = ''
    publisher: str = ''
    edition_evidence: str = ''
    orientation: Literal['upright', 'horizontal', 'stacked', 'unknown'] = 'unknown'
    measurement_uncertainty: str = ''
    legibility_basis: Text
    spine_sample: bool
    height_cm: Positive | None
    thickness_cm: Positive | None
    measurement_evidence: str
    price_sample: bool
    prices: list[PriceTruth]

    @model_validator(mode='after')
    def valid(self):
        if self.legible and not self.title.strip():
            raise ValueError('legible truth needs a title')
        if self.spine_sample and (self.height_cm is None or self.thickness_cm is None or not self.measurement_evidence):
            raise ValueError('spine sample needs both independent measurements and evidence')
        if self.price_sample and {p.component for p in self.prices} != {'replacement_cost', 'used_value'}:
            raise ValueError('price sample needs explicit new and used availability')
        if len({p.component for p in self.prices}) != len(self.prices):
            raise ValueError('duplicate price component')
        if not self.owned and (self.spine_sample or self.price_sample):
            raise ValueError('excluded books cannot enter samples')
        return self


class TruthItem(Contract):
    id: Text
    location: Text
    owned: bool
    category: Text
    evidence: Text


class RoomTruth(Contract):
    floor_area_m2: Positive
    wall_area_m2: Positive
    wall_basis: Literal['gross', 'net']
    method: Text
    uncertainty: Text
    evidence: Text
    length_m: Positive | None = None
    width_m: Positive | None = None
    height_m: Positive | None = None


class EvaluationPolicy(Contract):
    confidence_threshold: Confidence
    confident_wrong_denominator: Literal['high_confidence', 'human_legible']
    dimension_aggregation: Literal['all_comparisons']
    price_aggregation: Literal['all_available_comparisons']


class Truth(Contract):
    dataset_id: Text
    annotator: Text
    annotated_at: datetime
    independence_statement: Text
    country: str
    currency: str
    enclosed_room: bool
    shelving_units: Annotated[int, Field(ge=0)]
    books: list[TruthBook]
    items: list[TruthItem]
    room: RoomTruth

    @model_validator(mode='after')
    def valid(self):
        Sweep.timezone_required(self.annotated_at)
        Sweep(id='truth', captured_at=self.annotated_at, country=self.country, currency=self.currency)
        ids = [b.id for b in self.books] + [i.id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError('truth IDs must be unique')
        for book in self.books:
            for price in book.prices:
                if (price.country, price.currency) != (self.country, self.currency):
                    raise ValueError('truth price locale mismatch')
                if price.retrieved_at > self.annotated_at:
                    raise ValueError('price truth postdates annotation')
        return self


class FrozenTruth(Contract):
    schema_version: Literal['m11-1']
    frozen_at: datetime
    truth: Truth
    policy: EvaluationPolicy
    runtime_config: dict
    payload_sha256: str

    @model_validator(mode='after')
    def valid(self):
        Sweep.timezone_required(self.frozen_at)
        if self.truth.annotated_at > self.frozen_at:
            raise ValueError('truth annotation postdates freeze')
        value = self.model_dump(exclude={'payload_sha256'})
        if digest(canonical(value)) != self.payload_sha256:
            raise ValueError('frozen truth/config hash mismatch')
        return self


def freeze(truth, policy, config, now=None):
    value = dict(schema_version='m11-1', frozen_at=now or datetime.now(timezone.utc),
                 truth=Truth.model_validate(truth).model_dump(),
                 policy=EvaluationPolicy.model_validate(policy).model_dump(), runtime_config=config)
    return FrozenTruth.model_validate(dict(value, payload_sha256=digest(canonical(value))))


class Match(Contract):
    truth_id: Text
    predicted_id: Text
    physical_evidence: Text
    title_correct: bool | None
    title_evidence: str
    price_basis_confirmed: list[Literal['replacement_cost', 'used_value']]

    @model_validator(mode='after')
    def valid(self):
        if self.title_correct is not None and not self.title_evidence:
            raise ValueError('title judgment needs independent evidence')
        if len(self.price_basis_confirmed) != len(set(self.price_basis_confirmed)):
            raise ValueError('duplicate price basis judgment')
        return self


class Timing(Contract):
    clock_id: Text
    sweep_started: Number
    sweep_ended: Number
    packet_ready: Number
    packet_sha256: str
    evidence: Text

    @model_validator(mode='after')
    def valid(self):
        if not self.sweep_started <= self.sweep_ended <= self.packet_ready:
            raise ValueError('invalid monotonic event ordering')
        return self


class Stage(Contract):
    stage: Text
    job_id: Text
    clock_id: Text
    queued: Number
    started: Number
    ended: Number
    retries: Annotated[int, Field(ge=0)]
    usage: dict[str, Number]
    evidence: Text

    @model_validator(mode='after')
    def valid(self):
        if not self.queued <= self.started <= self.ended:
            raise ValueError('invalid stage ordering')
        return self


class Cost(Contract):
    job_id: Text
    kind: Literal['actual', 'estimated', 'unknown']
    amount: Number | None
    currency: str
    usage_basis: Text
    rate_date: str
    evidence: Text

    @model_validator(mode='after')
    def valid(self):
        if (self.kind == 'unknown') != (self.amount is None):
            raise ValueError('unknown cost is null; known cost needs an amount')
        return self


class Assessment(Contract):
    reviewer: Text
    reviewed_at: datetime
    truth_sha256: str
    packet_sha256: str
    matches: list[Match]
    false_merges: list[Text]
    false_splits: list[Text]
    timing: Timing | None
    stages: list[Stage]
    costs: list[Cost]
    cost_coverage_complete: bool
    second_locale_book_ids: list[Text]
    second_locale_country: str | None = None

    @model_validator(mode='after')
    def valid(self):
        Sweep.timezone_required(self.reviewed_at)
        for key in ('truth_id', 'predicted_id'):
            ids = [getattr(m, key) for m in self.matches]
            if len(set(ids)) != len(ids):
                raise ValueError('physical matches must be one-to-one')
        for rows in (self.stages, self.costs):
            if len({r.job_id for r in rows}) != len(rows):
                raise ValueError('duplicate telemetry job ID')
        if len(set(self.second_locale_book_ids)) != len(self.second_locale_book_ids):
            raise ValueError('duplicate second-locale book ID')
        if self.second_locale_country is not None and (len(self.second_locale_country)!=2 or not self.second_locale_country.isascii() or not self.second_locale_country.isalpha() or not self.second_locale_country.isupper()):
            raise ValueError('second country needs uppercase two-letter code')
        return self


def load_archive(path, max_bytes=134217728):
    """Read without extraction; enforce full M10 manifest and arithmetic audit."""
    if Path(path).stat().st_size > max_bytes:
        raise ValueError('archive exceeds byte budget')
    data = Path(path).read_bytes()
    if len(data) > max_bytes:
        raise ValueError('archive exceeds byte budget')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or len(names) > 10000:
            raise ValueError('duplicate/too many archive entries')
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or str(p) != name:
                raise ValueError('unsafe archive path')
        if sum(i.file_size for i in infos) > max_bytes:
            raise ValueError('expanded archive exceeds byte budget')
        files = {name: archive.read(name) for name in names}
    manifest = json.loads(files['artifact-manifest.json'])
    rows = manifest['files']
    if len({r['path'] for r in rows}) != len(rows):
        raise ValueError('duplicate manifest path')
    if set(files) != {r['path'] for r in rows} | {'artifact-manifest.json'}:
        raise ValueError('archive/manifest file set differs')
    for row in rows:
        raw = files[row['path']]
        if len(raw) != row['byte_size'] or digest(raw) != row['sha256']:
            raise ValueError('archive evidence hash/size mismatch')
    packet = json.loads(files['claim_packet.json'], parse_float=Decimal)
    audit_packet(packet)
    if 'report.html' not in files or 'spoken-summary.txt' not in files or 'frozen-inputs.json' not in files:
        raise ValueError('incomplete finalized archive')
    from .report import render_report
    if files['report.html'].decode('utf-8') != render_report(packet):
        raise ValueError('report differs from packet')
    # M10 adds a terminal newline to these text artifacts.
    if files['spoken-summary.txt'].decode('utf-8').rstrip('\n') != spoken_summary(packet).rstrip('\n'):
        raise ValueError('summary differs from packet')
    for frame in packet['evidence_manifest']:
        if frame['path'] not in files or digest(files[frame['path']]) != frame['sha256']:
            raise ValueError('frame evidence missing or changed')
    frozen = json.loads(files['frozen-inputs.json'], parse_float=Decimal)
    frozen_at = datetime.fromisoformat(packet['finalization']['frozen_at'])
    def source(sha):
        raw = files['sources/'+sha+'.txt']
        if digest(raw) != sha:
            raise ValueError('price/FX source hash mismatch')
        return raw
    for entry in packet['quote_manifest']:
        q = entry['quote']
        if entry['sha256'] != q['evidence_sha256'] or entry['path'] != 'sources/'+q['evidence_sha256']+'.txt':
            raise ValueError('quote manifest differs from literal source')
        source(q['evidence_sha256'])
        found = False
        for item, runs in [(False, frozen['book_runs']), (True, frozen['item_runs'])]:
            for run in runs:
                for market in ([run] if item else run.get('markets', [])):
                    for row in market.get('rows', []):
                        for component, candidate in ([('replacement', v) for v in row.get('quotes', [])] if item else
                                                     [(c,row.get(c)) for c in ['replacement','used']]):
                            if candidate is None or canonical(candidate) != canonical(q):
                                continue
                            identity = next(r for r in frozen['contents']['rows'] if r['item']['id']==row['item']['id']) if item else next(r for r in frozen['books']['books'] if r['id']==row['track_id'])
                            if canonical(row['source'] if item else row['identity']) != canonical(identity):
                                raise ValueError('frozen valuation identity differs from physical ledger')
                            verified_quote(q, run, identity, market['market'], component, source, frozen_at, item=item)
                            found = True
        if not found:
            raise ValueError('quote lacks independently reparsable frozen valuation')
    return packet, files, digest(data)


def second_locale_from_archive(packet, files, assessment):
    """Use M07's saved second market, which M10 already bundles with sources."""
    assessment = Assessment.model_validate(assessment)
    country = assessment.second_locale_country
    if country is None:
        return None
    if country == packet['sweep']['country'] or len(assessment.second_locale_book_ids)!=10:
        raise ValueError('second locale needs another country and exactly ten physical IDs')
    frozen = json.loads(files['frozen-inputs.json'],parse_float=Decimal)
    books = {b['id']:b for b in packet['books']}
    selected, currency = {}, None
    def source(sha):
        raw = files['sources/'+sha+'.txt']
        if digest(raw)!=sha:
            raise ValueError('second locale source/FX hash mismatch')
        return raw
    for run in frozen['book_runs']:
        if not run.get('usable_for_current_inventory',False):
            continue
        for market in run.get('markets',[]):
            if market['market']['country']!=country:
                continue
            for row in market['rows']:
                id = row['track_id']
                if id not in assessment.second_locale_book_ids:
                    continue
                if id in selected or id not in books:
                    raise ValueError('second locale has ambiguous/missing physical rows')
                identity = next(b for b in frozen['books']['books'] if b['id']==id)
                if canonical(row['identity'])!=canonical(identity):
                    raise ValueError('second locale identity differs from frozen ledger')
                if currency is not None and currency != market['market']['currency']:
                    raise ValueError('second locale has mixed currency')
                currency = market['market']['currency']
                book = dict(books[id])
                for component,field in [('replacement','replacement_cost'),('used','used_value')]:
                    q = row[component] if row['status']!='needs_appraisal' else None
                    price = dict(amount=None,source='',url='',retrieved_at=None,converted=False,quote_ref=None,currency=currency)
                    if q:
                        amount = verified_quote(q,run,identity,market['market'],component,source,datetime.fromisoformat(frozen['frozen_at']))
                        price.update(amount=amount,url=q['url'],retrieved_at=q['retrieved_at'],converted=q['converted'],
                                     quote_ref='final-quote-'+digest(canonical(q))[:32],source=q['source'],quote=q)
                    book[field] = price
                selected[id] = book
    if set(selected)!=set(assessment.second_locale_book_ids):
        raise ValueError('second locale lacks saved same-ten market rows')
    return dict(sweep=dict(packet['sweep'],country=country,currency=currency),books=list(selected.values()))


def relative_error(predicted, truth):
    if predicted is None:
        return None
    value = Decimal(str(predicted))
    if not value.is_finite() or value < 0:
        return None
    return abs(value - Decimal(str(truth))) / Decimal(str(truth))


def metric(value, bar, direction='max', strict=False):
    if value is None:
        return dict(value=None, bar=bar, status='not_measured')
    passed = (value < bar if strict else value <= bar) if direction == 'max' else value >= bar
    return dict(value=value, bar=bar, status='pass' if passed else 'fail')


def samples_metric(rows, required, bar):
    available = [r for r in rows if r['truth_available']]
    errors = [r['error'] for r in available if r['error'] is not None]
    complete = len(rows) == required
    result = dict(status='not_measured' if not complete or not available else
                  ('pass' if all(r['within_bar'] for r in available) else 'fail'),
                  required_comparisons=required, comparisons=len(rows), available=len(available),
                  unavailable=len(rows)-len(available), missing_predictions=sum(r['error'] is None for r in available),
                  within_bar=sum(r['within_bar'] for r in available), bar=bar,
                  mean=statistics.mean(errors) if errors else None,
                  median=statistics.median(errors) if errors else None, maximum=max(errors) if errors else None)
    if result['unavailable']:
        result['status'] = 'fail' if result['status'] == 'fail' else 'not_measured'
    return result


def evaluate(packet, frozen, assessment, second_packet=None):
    frozen = FrozenTruth.model_validate(frozen)
    assessment = Assessment.model_validate(assessment)
    truth, policy = frozen.truth, frozen.policy
    packet_sha = digest(canonical(packet))
    if assessment.packet_sha256 != packet_sha or assessment.truth_sha256 != frozen.payload_sha256:
        raise ValueError('assessment is bound to different inputs')
    captured = Sweep.timezone_required(datetime.fromisoformat(packet['sweep']['captured_at']))
    if frozen.frozen_at >= captured:
        raise ValueError('truth/config must be frozen before capture')
    if assessment.reviewed_at < captured:
        raise ValueError('review predates capture')
    if (truth.country, truth.currency) != (packet['sweep']['country'], packet['sweep']['currency']):
        raise ValueError('packet/truth locale differs')
    books = {b.id: b for b in truth.books if b.owned}
    items = {i.id: i for i in truth.items if i.owned}
    predictions = {b['id']: b for b in packet['books']}
    item_predictions = {i['id']: i for i in packet['items']}
    if len(predictions) != len(packet['books']) or len(item_predictions) != len(packet['items']) or set(predictions) & set(item_predictions):
        raise ValueError('duplicate prediction IDs')
    matches = {m.truth_id: m for m in assessment.matches}
    for m in assessment.matches:
        if m.truth_id in books:
            if m.predicted_id not in predictions:
                raise ValueError('book match lacks physical book prediction')
            if m.title_correct is not None and not predictions[m.predicted_id]['title']:
                raise ValueError('blank predicted title cannot have a correctness judgment')
        elif m.truth_id in items:
            if m.predicted_id not in item_predictions or m.title_correct is not None or m.price_basis_confirmed:
                raise ValueError('invalid non-book match')
        else:
            raise ValueError('match references unknown or excluded truth')
    title_rows, dimension_rows, price_rows, item_rows = [], [], [], []
    quotes = {q['id']: q['quote'] for q in packet['quote_manifest']}
    correct = 0
    high = {id for id, b in predictions.items() if b.get('title') and b.get('id_confidence') is not None
            and Decimal(str(b['id_confidence'])) >= policy.confidence_threshold}
    high_correct = set()
    for id, b in books.items():
        m = matches.get(id)
        pred = predictions.get(m.predicted_id) if m else None
        title_ok = bool(pred and pred['title'] and m.title_correct is True)
        if pred and pred['title'] and m.title_correct is None:
            raise ValueError('every matched nonblank book title needs an independent judgment')
        correct += int(b.legible and title_ok)
        if title_ok:
            high_correct.add(m.predicted_id)
        title_rows.append(dict(truth_id=id, location=b.location, predicted_id=m.predicted_id if m else None,
                               legible=b.legible, truth_title=b.title, predicted_title=pred['title'] if pred else None,
                               correct=title_ok, physical_evidence=m.physical_evidence if m else None))
        if b.spine_sample:
            for field, actual in [('spine_height_cm', b.height_cm), ('spine_thickness_cm', b.thickness_cm)]:
                value = pred[field] if pred else None
                error = relative_error(value, actual)
                dimension_rows.append(dict(truth_id=id, component=field, truth=actual, predicted=value,
                                           truth_available=True, error=error, within_bar=error is not None and error <= Decimal('.15'),
                                           evidence=b.measurement_evidence))
        if b.price_sample:
            for price in b.prices:
                p = pred[price.component] if pred else None
                q = quotes.get(p.get('quote_ref')) if p else None
                same_basis = bool(q and m and price.component in m.price_basis_confirmed and
                                  q['source_type'] == price.source_type and q['condition'] == price.condition and
                                  q['target_currency'] == price.currency and q['fees'] == price.fees)
                error = relative_error(p['amount'], price.amount) if price.availability == 'available' and p and same_basis else None
                price_rows.append(dict(truth_id=id, component=price.component, truth=price.amount,
                                       predicted=p['amount'] if p else None, truth_available=price.availability == 'available',
                                       same_basis=same_basis, error=error, within_bar=error is not None and error <= Decimal('.25'),
                                       truth_url=price.url, predicted_url=p['url'] if p else None, evidence=price.evidence))
    for id, item in items.items():
        m = matches.get(id)
        pred = item_predictions.get(m.predicted_id) if m else None
        item_rows.append(dict(truth_id=id, predicted_id=m.predicted_id if m else None,
                              truth_category=item.category, predicted_category=pred['category'] if pred else None,
                              correct=bool(pred and pred['category'] == item.category), evidence=item.evidence))
    legible = sum(b.legible for b in books.values())
    wrong_high = len(high - high_correct)  # unmatched high-confidence outputs are unverified/wrong, never credited.
    metrics = dict(book_count=metric(relative_error(len(predictions), len(books)) if books else None, Decimal('.05')),
                   title_identification=metric(Decimal(correct)/legible if legible else None, Decimal('.70'), 'min'),
                   confident_wrong_high_confidence=metric(Decimal(wrong_high)/len(high) if high else None, Decimal('.03')),
                   confident_wrong_human_legible=metric(Decimal(wrong_high)/legible if legible else None, Decimal('.03')),
                   spine_dimensions=samples_metric(dimension_rows, 40, Decimal('.15')),
                   book_prices=samples_metric(price_rows, 30, Decimal('.25')),
                   non_books=metric(Decimal(sum(i['correct'] for i in item_rows))/len(items) if items else None, Decimal('.80'), 'min'))
    metrics['confident_wrong'] = dict(metrics['confident_wrong_'+policy.confident_wrong_denominator], denominator=policy.confident_wrong_denominator)
    geometry = packet.get('room_geometry') or {}
    wall_basis_matches = geometry.get('request', {}).get('interpretation', {}).get('wall_area_basis') == truth.room.wall_basis
    for field, actual, bar in [('floor_area_m2', truth.room.floor_area_m2, '.10'), ('wall_area_m2', truth.room.wall_area_m2, '.15')]:
        value = packet['room'][field]
        error = relative_error(value, actual) if field == 'floor_area_m2' or wall_basis_matches else None
        # Known independent truth plus missing/mismatched output is a failed observation.
        metrics[field] = dict(metric(error, Decimal(bar)), predicted=value, truth=actual)
        if error is None:
            metrics[field].update(status='fail', reason='missing output or incompatible wall convention')
    timing = assessment.timing
    if timing and timing.packet_sha256 != packet_sha:
        raise ValueError('timing belongs to a different packet')
    if timing and any(s.clock_id != timing.clock_id or s.ended > timing.packet_ready for s in assessment.stages):
        raise ValueError('stage telemetry must use the same clock and finish before packet readiness')
    metrics['packet_latency'] = metric(timing.packet_ready-timing.sweep_ended if timing else None, Decimal(300), strict=True)
    metrics['sweep_duration'] = metric(timing.sweep_ended-timing.sweep_started if timing else None, Decimal(180), strict=True)
    matched_pred = {m.predicted_id for m in assessment.matches}
    physical = dict(truth_books=len(books), predicted_books=len(predictions), legible_books=legible,
                    correct_titles=correct, high_confidence=len(high), wrong_high_confidence=wrong_high,
                    precision=Decimal(sum(id in matched_pred for id in predictions))/len(predictions) if predictions else None,
                    recall=Decimal(sum(id in matches for id in books))/len(books) if books else None,
                    unmatched_truth=[id for id in list(books)+list(items) if id not in matches],
                    unmatched_predictions=[id for id in list(predictions)+list(item_predictions) if id not in matched_pred],
                    false_merges=assessment.false_merges, false_splits=assessment.false_splits,
                    non_book_false_positives=[id for id in item_predictions if id not in matched_pred])
    scenario = dict(enclosed_room=truth.enclosed_room, books_at_least_60=len(books)>=60,
                    shelving_units_at_least_2=truth.shelving_units>=2, non_books_at_least_8=len(items)>=8,
                    independent_truth_asserted=True, frozen_before_capture=True)
    eligible = all(scenario.values()) and not packet.get('synthetic', False) and not any(f.get('synthetic',False) for f in packet.get('evidence_manifest',[]))
    costs = {}
    for currency in {c.currency for c in assessment.costs}:
        costs[currency] = {kind: sum((c.amount for c in assessment.costs if c.currency==currency and c.kind==kind), Decimal(0))
                           if any(c.currency==currency and c.kind==kind for c in assessment.costs) else None for kind in ['actual', 'estimated']}
    complete_cost = bool(assessment.costs) and assessment.cost_coverage_complete and all(c.kind=='actual' for c in assessment.costs)
    if assessment.cost_coverage_complete and {s.job_id for s in assessment.stages} - {c.job_id for c in assessment.costs}:
        raise ValueError('complete cost coverage lacks stage job entries')
    stage_rows = [dict(s.model_dump(), queue_s=s.started-s.queued, execution_s=s.ended-s.started) for s in assessment.stages]
    second_rows = []
    if second_packet:
        second_books = {b['id']: b for b in second_packet['books']}
        if len(assessment.second_locale_book_ids) != 10:
            raise ValueError('second locale needs exactly ten prespecified physical IDs')
        if second_packet['sweep']['id'] != packet['sweep']['id'] or second_packet['sweep']['country'] == packet['sweep']['country']:
            raise ValueError('second locale must retain the sweep and change country')
        for id in assessment.second_locale_book_ids:
            a, b = predictions.get(id), second_books.get(id)
            if not a or not b or not a['title'] or any(a[k]!=b[k] for k in ['title','author','edition','isbn']):
                raise ValueError('second locale altered/missing book identity')
            for component in ['replacement_cost', 'used_value']:
                p = b[component]
                q = p.get('quote',{})
                second_rows.append(dict(predicted_id=id, component=component, country=second_packet['sweep']['country'],
                                        currency=second_packet['sweep']['currency'], amount=p['amount'],
                                        status='unavailable' if p['amount'] is None else 'converted' if p['converted'] else 'foreign_same_currency' if q.get('foreign_market') else 'local',
                                        quote_ref=p.get('quote_ref'), url=p['url'], retrieved_at=p['retrieved_at'],
                                        condition=q.get('condition',p.get('condition_assumed')),source_type=q.get('source_type'),fx=q.get('fx'),source_sha256=q.get('evidence_sha256')))
    errors = [dict(ref_id=r['truth_id'], component=r['component'], error=r['error'],
                   reason='missing/incompatible prediction' if r['error'] is None else 'outside pass bar')
              for r in dimension_rows+price_rows if r['truth_available'] and not r['within_bar']]
    errors += [dict(ref_id=r['truth_id'], component='title', error=None, reason='missing/wrong title')
               for r in title_rows if r['legible'] and not r['correct']]
    errors += [dict(ref_id=r['truth_id'], component='category', error=None, reason='missing/wrong category')
               for r in item_rows if not r['correct']]
    errors += [dict(ref_id='room' if name.endswith('_m2') else 'sweep', component=name, error=value.get('value'), reason='failed aggregate')
               for name,value in metrics.items() if value['status']=='fail' and name not in ['spine_dimensions','book_prices','confident_wrong_high_confidence','confident_wrong_human_legible']]
    for i,error in enumerate(errors):
        error['id'] = 'E'+str(i+1).zfill(4)
    return dict(schema_version='m11-results-1', dataset_id=truth.dataset_id, captured_at=captured,
                sweep_id=packet['sweep']['id'], truth_sha256=frozen.payload_sha256,
                packet_sha256=packet_sha, synthetic=bool(packet.get('synthetic', False)), acceptance_eligible=eligible,
                scenario=scenario, metrics=metrics, physical_matching=physical,
                cost=dict(totals_by_currency=costs, complete_actual_cost=complete_cost,
                          status='measured' if complete_cost else 'not_measured', entries=[c.model_dump() for c in assessment.costs]),
                tables=dict(books=title_rows, dimensions=dimension_rows, prices=price_rows, items=item_rows,
                            stages=stage_rows, second_locale=second_rows), errors=errors,
                second_locale_status='recorded' if second_rows else 'not_measured',
                limitations=['Human matching, independence, same price basis and telemetry are reviewer assertions; hashes bind inputs, not external truth.',
                             'Missing confidence is not calibrated confidence. Empty denominators are undefined.',
                             'Stage duration sums are not the concurrent critical path. No timing or cost inferred from defaults.',
                             'Observed mismatches do not establish root causes, a measured repair or held-out generalization.'])


def write_results(output, result, frozen, assessment, archive_sha, second_sha=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result.update(archive_sha256=archive_sha, second_archive_sha256=second_sha)
    (output/'results.json').write_text(json_text(result)+'\n', encoding='utf-8')
    (output/'frozen-truth.json').write_text(json_text(frozen.model_dump())+'\n', encoding='utf-8')
    (output/'assessment.json').write_text(json_text(assessment.model_dump())+'\n', encoding='utf-8')
    for name, rows in result['tables'].items():
        with (output/(name+'.csv')).open('w', encoding='utf-8', newline='') as file:
            if rows:
                writer = csv.DictWriter(file, fieldnames=list(rows[0]))
                writer.writeheader()
                # Prevent formula execution when a reviewer opens untrusted source text in a spreadsheet.
                for row in rows:
                    writer.writerow({k: "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for k,v in row.items()})
            else:
                file.write('status\r\nnot_measured\r\n')
    esc = lambda v: html.escape(str(v))
    rows = ''.join('<tr><td>'+esc(k)+'</td><td>'+esc(v['status'])+'</td><td>'+esc(v.get('value',v.get('within_bar')))+'</td><td>'+esc(v['bar'])+'</td></tr>' for k,v in result['metrics'].items())
    text = '<!doctype html><meta charset="utf-8"><title>Independent sweep evaluation</title><h1>Sweep evaluation</h1><p>Acceptance eligible: '+esc(result['acceptance_eligible'])+'</p><p>Synthetic: '+esc(result['synthetic'])+'</p><table><tr><th>Measure</th><th>Status</th><th>Value / within bar</th><th>Bar</th></tr>'+rows+'</table><p>Full provenance and denominators: <a href="results.json">results.json</a>. Raw sample tables accompany this report.</p>'
    text += ''.join('<p>'+esc(s)+'</p>' for s in result['limitations'])
    (output/'evaluation.html').write_text(text+'\n', encoding='utf-8')
    manifest = [{'path':p.name,'sha256':digest(p.read_bytes()),'byte_size':p.stat().st_size} for p in sorted(output.iterdir())]
    (output/'evaluation-manifest.json').write_text(json_text(dict(files=manifest, manifest_self_hash_excluded=True))+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Offline independent truth freeze and full-room evaluation; no provider calls')
    commands = parser.add_subparsers(dest='command', required=True)
    t = commands.add_parser('templates')
    t.add_argument('--output', type=Path, required=True)
    f = commands.add_parser('freeze')
    for name in ['truth','policy','config','output']:
        f.add_argument('--'+name, type=Path, required=True)
    e = commands.add_parser('evaluate')
    for name in ['archive','frozen-truth','assessment','output']:
        e.add_argument('--'+name, type=Path, required=True)
    e.add_argument('--second-archive', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('choose a fresh output')
    if args.command == 'templates':
        args.output.mkdir(parents=True)
        values = dict(truth=dict(dataset_id='',annotator='',annotated_at=None,independence_statement='',country='',currency='',
                     enclosed_room=False,shelving_units=0,books=[],items=[],room=dict(floor_area_m2=None,wall_area_m2=None,
                     wall_basis=None,method='',uncertainty='',evidence='')),
                     policy=dict(confidence_threshold=None,confident_wrong_denominator=None,
                                 dimension_aggregation='all_comparisons',price_aggregation='all_available_comparisons'),
                     config=dict(code_revision='',device='',models={},recognition_policy={},calibration={},valuation_policy={},area_policy={}),
                     assessment=dict(reviewer='',reviewed_at=None,truth_sha256='',packet_sha256='',matches=[],false_merges=[],false_splits=[],
                                     timing=None,stages=[],costs=[],cost_coverage_complete=False,second_locale_book_ids=[],second_locale_country=None))
        for name,value in values.items():
            (args.output/(name+'.json')).write_text(json_text(value)+'\n',encoding='utf-8')
        for name,model in [('truth',Truth),('policy',EvaluationPolicy),('assessment',Assessment)]:
            (args.output/(name+'.schema.json')).write_text(json.dumps(model.model_json_schema(),indent=2)+'\n',encoding='utf-8')
        print('Blank templates saved; fill required fields before freeze/evaluation')
    elif args.command == 'freeze':
        result = freeze(read_json(args.truth), read_json(args.policy), read_json(args.config))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_text(result.model_dump())+'\n', encoding='utf-8')
        print('Frozen truth/config: '+result.payload_sha256)
    else:
        packet, files, sha = load_archive(args.archive)
        second, second_sha = None, None
        if args.second_archive:
            second, _, second_sha = load_archive(args.second_archive)
        frozen = FrozenTruth.model_validate(read_json(args.frozen_truth))
        assessment = Assessment.model_validate(read_json(args.assessment))
        if assessment.second_locale_country:
            if second is not None:
                raise ValueError('choose bundled second market or second archive, not both')
            second = second_locale_from_archive(packet, files, assessment)
        result = evaluate(packet, frozen, assessment, second)
        write_results(args.output, result, frozen, assessment, sha, second_sha)
        print('Evaluation saved; acceptance eligible: '+str(result['acceptance_eligible']))


if __name__ == '__main__':
    main()
