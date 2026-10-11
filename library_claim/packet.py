"""Evidence checks, deterministic aggregation and portable packet export."""

import hashlib
import json
import re
import shutil
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .models import ItemPrice, PacketInput, PacketPolicy, Price

SQFT_PER_M2 = Decimal("10.7639104167")


def json_text(value) -> str:
    """Encode Decimal as an exact JSON number, never via binary float."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite JSON number")
        return format(value, "f")
    if isinstance(value, datetime):
        return json.dumps(value.isoformat())
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(str(k)) + ":" + json_text(v) for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(json_text(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _saved_file(root: Path, evidence) -> Path:
    path = (root / evidence.path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"missing or unsafe saved evidence: {evidence.id}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != evidence.sha256.lower():
        raise ValueError(f"evidence hash mismatch: {evidence.id}")
    return path


def build_packet(draft: PacketInput, evidence_root: Path, policy: PacketPolicy) -> dict:
    """Validate structural evidence, remove unsupported values, calculate totals.

    Malformed IDs/files fail the build. Unsupported semantic fields/valuations
    become unknown with review reasons; this does not verify upstream accuracy.
    """
    draft = PacketInput.model_validate(draft.model_dump())
    root = Path(evidence_root)
    identifiers = [x.id for x in draft.books + draft.items]
    if len(identifiers) != len(set(identifiers)) or "room" in identifiers:
        raise ValueError("inventory IDs must be unique and cannot be 'room'")
    evidence = draft.frames + draft.quotes + draft.measurements
    if len({x.id for x in evidence}) != len(evidence):
        raise ValueError("evidence IDs must be unique")
    frames = {x.id: x for x in draft.frames}
    quotes = {x.id: x for x in draft.quotes}
    measures = {x.id: x for x in draft.measurements}
    for x in draft.frames + draft.quotes:
        _saved_file(root, x)
    for measurement in draft.measurements:
        if any(ref not in frames for ref in measurement.frame_refs):
            raise ValueError(f"measurement has missing frame: {measurement.id}")
        if measurement.ref_id not in set(identifiers) | {"room"}:
            raise ValueError(f"measurement has missing inventory reference: {measurement.id}")
    measurement_keys = [(m.ref_id, m.field) for m in draft.measurements]
    if len(measurement_keys) != len(set(measurement_keys)):
        raise ValueError("one accepted measurement per inventory field is required")
    for entity in draft.books + draft.items:
        if entity.frame_ref not in frames:
            raise ValueError(f"inventory frame_ref does not resolve: {entity.id}")

    review = [x.model_dump() for x in draft.review_queue]

    def flag(ref: str, reason: str):
        finding = {"ref_id": ref, "reason": reason}
        if finding not in review:
            review.append(finding)

    def supported_text(entity, field: str):
        value = getattr(entity, field)
        refs = entity.field_evidence.get(field, [])
        if value and (not refs or any(ref not in frames for ref in refs)):
            setattr(entity, field, "")
            flag(entity.id, f"{field}: no saved-frame provenance; left unknown")

    def measured(ref: str, field: str, value, unit: str):
        if value is None:
            flag(ref, f"{field}: measurement unavailable")
            return None
        if not any(m.ref_id == ref and m.field == field and m.value == value
                   and m.unit == unit for m in measures.values()):
            flag(ref, f"{field}: no matching measurement evidence; left unknown")
            return None
        return value

    quantum = Decimal(1).scaleb(-policy.currency_decimal_places)

    def rounded(value):
        return value.quantize(quantum, rounding=ROUND_HALF_UP)

    def valid_quote(q, source_types):
        if q is None:
            return "missing saved quote evidence"
        if not q.available:
            return "source listing unavailable"
        if q.currency != draft.sweep.currency:
            return "currency mismatch; verified FX conversion is not implemented in M01"
        if q.source_type not in source_types:
            return "wrong quote source type"
        if q.physical_format.lower() in {"ebook", "e-book", "digital", "audiobook"}:
            return "nonphysical format cannot price physical contents"
        try:
            saved = json.loads(_saved_file(root, q).read_text(encoding="utf-8"), parse_float=Decimal)
            if not isinstance(saved, dict) or Decimal(str(saved.get("amount"))) != q.amount:
                return "saved source amount does not match quote"
            expected = q.model_dump(mode="json", exclude={"id", "path", "sha256", "amount"})
            if any(saved.get(key) != value for key, value in expected.items()):
                return "saved source metadata does not match quote"
            excerpt = saved.get("excerpt")
            if not isinstance(excerpt, str) or not excerpt.strip():
                return "readable source excerpt missing"
            tokens = re.findall(r"(?<![\w.\-])\d[\d,]*(?:\.\d+)?(?![\w.])", excerpt)
            if not any(Decimal(token.replace(",", "")) == q.amount for token in tokens):
                return "literal price absent from saved excerpt"
        except (ValueError, TypeError, UnicodeError, ArithmeticError):
            return "invalid saved quote snapshot"
        return None

    def price(entity, component, source_types):
        p = getattr(entity, component)
        reason = None
        q = quotes.get(p.quote_ref)
        if entity.status == "needs_appraisal":
            reason = "needs human appraisal; automatic valuation excluded"
        elif not entity.title:
            reason = "book identity unavailable; automatic valuation excluded"
        elif p.amount is None:
            reason = "price unavailable"
        elif p.converted:
            reason = "verified FX conversion is not implemented in M01"
        else:
            reason = valid_quote(q, source_types)
            if reason is None and (p.amount != q.amount or p.currency != q.currency
                                  or p.source != q.source or p.url != q.url
                                  or p.retrieved_at != q.retrieved_at
                                  or p.condition_assumed != q.condition):
                reason = "price/condition/source does not match saved quote"
        if reason:
            setattr(entity, component, Price())
            flag(entity.id, f"{component}: {reason}")
        else:
            p.amount = rounded(p.amount)

    excluded_ownership = [x.model_dump() for x in draft.books + draft.items if not x.owned]
    books = [x for x in draft.books if x.owned]
    items = [x for x in draft.items if x.owned]
    for b in books:
        for field in ("title", "author", "edition", "isbn", "publisher"):
            supported_text(b, field)
        if not b.title and b.status == "identified":
            b.status = "unidentified"
            b.author = b.edition = b.isbn = b.publisher = ""
            b.id_confidence = None
        if not b.title:
            flag(b.id, "title: unidentified book retained in physical count")
        for field in ("spine_height_cm", "spine_thickness_cm"):
            setattr(b, field, measured(b.id, field, getattr(b, field), "cm"))
        price(b, "replacement_cost", {"new_physical"})
        price(b, "used_value", {"used_asking", "used_sold"})

    for item in items:
        for field in ("category", "description", "brand_model"):
            supported_text(item, field)
        if not item.category:
            flag(item.id, "category: unknown")
        for field in ("w", "h", "d"):
            setattr(item.dimensions_cm, field, measured(item.id, f"dimensions_cm.{field}",
                                                       getattr(item.dimensions_cm, field), "cm"))
        if item.category.lower() in {"art", "portrait", "framed_art", "painting"}:
            # M06/M08 will supply verified claimant-turn assertions. A flag by
            # itself is not yet enough evidence to automatically price a print.
            item.status = "needs_appraisal"
        p = item.replacement_cost
        qs = [quotes.get(ref) for ref in p.quote_refs]
        reason = None
        if item.status == "needs_appraisal":
            reason = "needs human appraisal; automatic valuation excluded"
        elif not item.category:
            reason = "item category unavailable; automatic valuation excluded"
        elif p.low is None or not qs:
            reason = "replacement price unavailable"
        else:
            reason = next((r for q in qs if (r := valid_quote(q, {"item_comparable"}))), None)
            if reason is None:
                primary = qs[0]
                if (p.low != min(q.amount for q in qs) or p.high != max(q.amount for q in qs)
                        or p.currency != primary.currency or p.source != primary.source
                        or p.url != primary.url or p.retrieved_at != primary.retrieved_at
                        or not p.condition_assumed
                        or any(q.condition != p.condition_assumed for q in qs)):
                    reason = "range/condition/source does not match saved comparable quotes"
        if reason:
            item.replacement_cost = ItemPrice()
            if item.status != "needs_appraisal":
                item.status = ""
            flag(item.id, f"replacement_cost: {reason}")
        else:
            p.low, p.high = rounded(p.low), rounded(p.high)
            item.status = "priced" if p.low == p.high else "range"

    room = draft.room.model_dump()
    for field in ("length_m", "width_m", "height_m", "floor_area_m2", "wall_area_m2", "shelved_wall_area_m2"):
        unit = "m2" if field.endswith("m2") else "m"
        room[field] = measured("room", field, room[field], unit)
    for field in ("floor_area", "wall_area", "shelved_wall_area"):
        room[field + "_ft2"] = None if room[field + "_m2"] is None else room[field + "_m2"] * SQFT_PER_M2
    if all(room[field] is None for field in ("length_m", "width_m", "height_m", "floor_area_m2", "wall_area_m2", "shelved_wall_area_m2")):
        room["scale_method"], room["confidence"] = "", None

    thicknesses = [b.spine_thickness_cm for b in books]
    measured_run = sum((n for n in thicknesses if n is not None), Decimal(0)) / 100
    missing_measurements = sum(n is None for n in thicknesses)
    eligible = [[b.replacement_cost.amount is not None, b.used_value.amount is not None] for b in books]
    eligible += [[i.replacement_cost.low is not None] for i in items]
    excluded = sum(not all(parts) if policy.exclusion_basis == "missing_any_component" else not any(parts)
                   for parts in eligible)
    totals = {
        "book_count": len(books), "books_identified": sum(bool(b.title) for b in books),
        "books_unidentified": sum(not b.title for b in books),
        "shelf_run_m": None if missing_measurements else measured_run,
        "books_replacement_cost": sum((b.replacement_cost.amount or Decimal(0) for b in books), Decimal(0)),
        "books_used_value": sum((b.used_value.amount or Decimal(0) for b in books), Decimal(0)),
        "items_replacement_cost_low": sum((i.replacement_cost.low or Decimal(0) for i in items), Decimal(0)),
        "items_replacement_cost_high": sum((i.replacement_cost.high or Decimal(0) for i in items), Decimal(0)),
        "excluded_from_totals": excluded,
    }
    return {
        "schema_version": "1.0", "packet_status": "partial" if review else "complete",
        "synthetic": draft.synthetic, "sweep": draft.sweep.model_dump(), "room": room,
        "books": [dict(b.model_dump(), identification_status="identified" if b.title else "unidentified") for b in books],
        "items": [i.model_dump() for i in items],
        "totals": totals, "review_queue": review, "aggregation_policy": policy.model_dump(),
        "evidence_manifest": [x.model_dump() for x in draft.frames],
        "quote_manifest": [x.model_dump() for x in draft.quotes],
        "measurements": [x.model_dump() for x in draft.measurements],
        "ownership_exclusions": excluded_ownership,
        "coverage": {"books_replacement_priced": sum(b.replacement_cost.amount is not None for b in books),
                     "books_used_priced": sum(b.used_value.amount is not None for b in books),
                     "items_priced": sum(i.replacement_cost.low is not None for i in items),
                     "shelf_run_measured_m": measured_run,
                     "spine_thickness_missing": missing_measurements},
    }


def export_packet(draft: PacketInput, evidence_root: Path, output_dir: Path,
                  policy: PacketPolicy) -> tuple[Path, Path]:
    """Copy referenced evidence and render JSON/HTML from one serialized packet."""
    from .report import render_report

    packet = build_packet(draft, evidence_root, policy)
    encoded = json_text(packet)
    # Rendering consumes the serialized packet, preserving its numeric tokens.
    report = render_report(json.loads(encoded, parse_float=Decimal))
    output_dir = Path(output_dir).resolve()
    paths = (output_dir / "claim_packet.json", output_dir / "report.html")
    if any(path.exists() for path in paths):
        raise FileExistsError("packet output already exists; choose a new output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    for entry in draft.frames + draft.quotes:
        source = _saved_file(Path(evidence_root), entry)
        target = (output_dir / entry.path).resolve()
        if not target.is_relative_to(output_dir) or target in paths:
            raise ValueError("unsafe export evidence path")
        if target.exists() and target != source:
            if hashlib.sha256(target.read_bytes()).hexdigest() != entry.sha256.lower():
                raise FileExistsError("conflicting export evidence")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if source != target:
                shutil.copyfile(source, target)
    paths[0].write_text(encoded + "\n", encoding="utf-8")
    paths[1].write_text(report, encoding="utf-8")
    return paths
