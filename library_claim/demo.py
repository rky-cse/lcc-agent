"""Explicitly synthetic inputs for module review; no provider or catalogue calls."""

import base64
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .models import (Book, FrameEvidence, Item, ItemPrice, MeasurementEvidence,
                     PacketInput, Price, QuoteEvidence, Sweep)
from .packet import json_text


def synthetic_fixture(root: Path, country: str, currency: str) -> PacketInput:
    root = Path(root)
    (root / "frames").mkdir(parents=True, exist_ok=True)
    (root / "quotes").mkdir(parents=True, exist_ok=True)
    image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jM1sAAAAASUVORK5CYII=")
    (root / "frames/fixture.png").write_bytes(image)
    now = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    frame = FrameEvidence(id="frame-1", path="frames/fixture.png",
                          sha256=hashlib.sha256(image).hexdigest(), captured_at=now)
    quotes = []

    def quote(ref, amount, source_type, condition, physical_format):
        q = QuoteEvidence(id=ref, path=f"quotes/{ref}.json", sha256="0" * 64,
                          source="Synthetic fixture source", url=f"https://example.invalid/{ref}",
                          retrieved_at=now, amount=Decimal(amount), currency=currency,
                          condition=condition, physical_format=physical_format,
                          available=True, source_type=source_type)
        saved = q.model_dump(mode="json", exclude={"id", "path", "sha256", "amount"})
        saved.update(amount=q.amount, excerpt=f"SYNTHETIC ONLY: {currency} {amount}", synthetic=True)
        data = json_text(saved).encode("utf-8")
        (root / q.path).write_bytes(data)
        q.sha256 = hashlib.sha256(data).hexdigest()
        quotes.append(q)
        return q

    def price(q):
        return Price(amount=q.amount, currency=q.currency, source=q.source, url=q.url,
                     retrieved_at=q.retrieved_at, condition_assumed=q.condition, quote_ref=q.id)

    new = quote("book-new", "10.005", "new_physical", "new", "paperback")
    used = quote("book-used", "4.10", "used_asking", "good", "paperback")
    low = quote("lamp-low", "20.20", "item_comparable", "new", "lamp")
    high = quote("lamp-high", "30.30", "item_comparable", "new", "lamp")
    books = [Book(id="book-1", frame_ref=frame.id, status="identified", title="Synthetic Book A",
                  field_evidence={"title": [frame.id]}, spine_height_cm=Decimal("20"),
                  spine_thickness_cm=Decimal("2"), replacement_cost=price(new), used_value=price(used)),
             Book(id="book-2", frame_ref=frame.id),
             Book(id="book-3", frame_ref=frame.id, status="needs_appraisal", title="Synthetic signed volume",
                  field_evidence={"title": [frame.id]}, replacement_cost=price(new)),
             Book(id="borrowed-1", frame_ref=frame.id, owned=False)]
    items = [Item(id="lamp-1", frame_ref=frame.id, category="lamp", description="Synthetic lamp",
                  field_evidence={"category": [frame.id], "description": [frame.id]},
                  replacement_cost=ItemPrice(low=low.amount, high=high.amount, source=low.source,
                                             url=low.url, retrieved_at=low.retrieved_at,
                                             quote_refs=[low.id, high.id], condition_assumed=low.condition,
                                             currency=currency)),
             Item(id="art-1", frame_ref=frame.id, category="art", description="Synthetic artwork",
                  field_evidence={"category": [frame.id], "description": [frame.id]})]
    measurements = [MeasurementEvidence(id=f"measurement-{field}", ref_id="book-1", field=field,
                                         value=value, unit="cm", frame_refs=[frame.id],
                                         scale_method="synthetic fixture", derivation="Declared fixture value, no real geometry")
                    for field, value in [("spine_height_cm", Decimal("20")), ("spine_thickness_cm", Decimal("2"))]]
    return PacketInput(sweep=Sweep(id="synthetic-m01", captured_at=now, country=country, currency=currency),
                       books=books, items=items, frames=[frame], quotes=quotes, measurements=measurements,
                       synthetic=True)
