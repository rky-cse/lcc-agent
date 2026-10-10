import hashlib
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from library_claim.demo import synthetic_fixture
from library_claim.models import Book, FrameEvidence, ItemPrice, PacketPolicy, StageResult
from library_claim.packet import build_packet, export_packet, json_text
from library_claim.report import render_report


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.draft = synthetic_fixture(self.root, "IN", "INR")
        self.policy = PacketPolicy(currency_decimal_places=2, shelf_run_basis="sum_spine_thickness",
                                   exclusion_basis="missing_any_component")

    def build(self):
        return build_packet(self.draft, self.root, self.policy)

    def rewrite_quote(self, q, **changes):
        path = self.root / q.path
        saved = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        saved.update(changes)
        path.write_text(json_text(saved), encoding="utf-8")
        q.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_synthetic_mixed_packet(self):
        packet = self.build()
        self.assertEqual(packet["totals"], dict(book_count=3, books_identified=2, books_unidentified=1,
                         shelf_run_m=None, books_replacement_cost=Decimal("10.01"), books_used_value=Decimal("4.10"),
                         items_replacement_cost_low=Decimal("20.20"), items_replacement_cost_high=Decimal("30.30"),
                         excluded_from_totals=3))
        self.assertEqual(packet["coverage"]["shelf_run_measured_m"], Decimal("0.02"))
        self.assertEqual(packet["items"][1]["status"], "needs_appraisal")
        self.assertEqual(packet["books"][2]["replacement_cost"]["amount"], None)
        self.assertEqual(packet["ownership_exclusions"][0]["id"], "borrowed-1")

    def test_unknown_required_fields_survive_json(self):
        packet = json.loads(json_text(self.build()), parse_float=Decimal)
        unknown = packet["books"][1]
        for field in ["title", "author", "edition", "isbn", "publisher"]:
            self.assertEqual(unknown[field], "")
        self.assertIsNone(unknown["spine_height_cm"])
        self.assertIsNone(unknown["used_value"]["amount"])
        self.assertIn("retrieved_at", unknown["used_value"])
        self.assertIsNone(packet["room"]["floor_area_ft2"])
        self.assertIsNone(packet["sweep"]["duration_s"])
        self.assertEqual(packet["books"][2]["identification_status"], "identified")

    def test_build_does_not_mutate_input(self):
        before = self.draft.model_dump()
        self.build()
        self.assertEqual(self.draft.model_dump(), before)

    def test_exact_decimal_json(self):
        self.assertEqual(json_text({"amount": Decimal("0.1") + Decimal("0.2")}), '{"amount":0.3}')
        self.assertIn('"amount":10.01', json_text(self.build()))
        with self.assertRaises(ValueError):
            json_text(Decimal("NaN"))

    def test_true_zero_price_is_priced(self):
        q = self.draft.quotes[0]
        q.amount = Decimal(0)
        self.rewrite_quote(q, amount=Decimal(0), excerpt="SYNTHETIC INR 0")
        self.draft.books[0].replacement_cost.amount = Decimal(0)
        p = self.build()
        self.assertEqual(p["books"][0]["replacement_cost"]["amount"], Decimal("0.00"))
        self.assertEqual(p["coverage"]["books_replacement_priced"], 1)

    def test_duplicate_physical_ids_rejected(self):
        self.draft.books[1].id = "book-1"
        with self.assertRaisesRegex(ValueError, "unique"):
            self.build()

    def test_distinct_copies_not_merged_by_title(self):
        copy = self.draft.books[0].model_copy(deep=True)
        copy.id = "copy-2"
        self.draft.books.append(copy)
        p = self.build()
        self.assertEqual(p["totals"]["book_count"], 4)
        self.assertEqual(p["totals"]["books_replacement_cost"], Decimal("20.02"))

    def test_missing_quote_excludes_price(self):
        self.draft.books[0].replacement_cost.quote_ref = "absent"
        self.assertIsNone(self.build()["books"][0]["replacement_cost"]["amount"])

    def test_fx_and_wrong_currency_excluded(self):
        self.draft.books[0].replacement_cost.converted = True
        self.assertIsNone(self.build()["books"][0]["replacement_cost"]["amount"])
        self.draft.books[0].replacement_cost.converted = False
        self.draft.sweep.currency = "USD"
        self.assertEqual(self.build()["coverage"]["books_replacement_priced"], 0)

    def test_unsupported_source_variants(self):
        for changes in [{"available": False}, {"physical_format": "ebook"}, {"source_type": "used_asking"}]:
            with self.subTest(changes=changes):
                original = self.draft.quotes[0].model_copy(deep=True)
                for key, value in changes.items():
                    setattr(self.draft.quotes[0], key, value)
                self.assertIsNone(self.build()["books"][0]["replacement_cost"]["amount"])
                self.draft.quotes[0] = original

    def test_snapshot_must_match_literal_amount_and_metadata(self):
        q = self.draft.quotes[0]
        for changes in [{"excerpt": "No price here"}, {"amount": Decimal("100")},
                        {"condition": "poor"}, {"excerpt": ""}]:
            with self.subTest(changes=changes):
                before = (self.root / q.path).read_bytes()
                self.rewrite_quote(q, **changes)
                self.assertIsNone(self.build()["books"][0]["replacement_cost"]["amount"])
                (self.root / q.path).write_bytes(before)
                q.sha256 = hashlib.sha256(before).hexdigest()

    def test_forged_price_metadata_excluded(self):
        self.draft.books[0].replacement_cost.condition_assumed = "invented"
        self.assertIsNone(self.build()["books"][0]["replacement_cost"]["amount"])

    def test_range_bounds_and_mismatch(self):
        with self.assertRaises(ValidationError):
            ItemPrice(low=2, high=1)
        with self.assertRaises(ValidationError):
            ItemPrice(low=1)
        self.draft.items[0].replacement_cost.high = Decimal("100")
        item = self.build()["items"][0]
        self.assertIsNone(item["replacement_cost"]["high"])
        self.assertEqual(item["status"], "")

    def test_exact_comparable_and_mixed_condition(self):
        p = self.draft.items[0].replacement_cost
        p.quote_refs = [p.quote_refs[0]]
        p.high = p.low
        self.assertEqual(self.build()["items"][0]["status"], "priced")
        p.quote_refs.append("lamp-high")
        p.high = Decimal("30.30")
        self.draft.quotes[3].condition = "used"
        self.assertIsNone(self.build()["items"][0]["replacement_cost"]["low"])

    def test_art_print_assertion_alone_cannot_enable_price(self):
        art = self.draft.items[1]
        art.artwork_kind = "print"
        art.replacement_cost = self.draft.items[0].replacement_cost.model_copy(deep=True)
        result = self.build()["items"][1]
        self.assertEqual(result["status"], "needs_appraisal")
        self.assertIsNone(result["replacement_cost"]["low"])

    def test_unsupported_identity_cleared(self):
        self.draft.books[0].field_evidence = {}
        b = self.build()["books"][0]
        self.assertEqual(b["status"], "unidentified")
        self.assertEqual(b["title"], "")
        self.assertIsNone(b["replacement_cost"]["amount"])

    def test_unmatched_measurement_cleared(self):
        self.draft.books[0].spine_thickness_cm = Decimal("7")
        p = self.build()
        self.assertIsNone(p["books"][0]["spine_thickness_cm"])
        self.assertIsNone(p["totals"]["shelf_run_m"])
        self.assertEqual(p["coverage"]["shelf_run_measured_m"], 0)

    def test_empty_inventory_true_zero(self):
        self.draft.books = []
        self.draft.items = []
        self.draft.measurements = []
        p = self.build()
        self.assertEqual(p["totals"]["shelf_run_m"], 0)
        self.assertEqual(p["totals"]["books_replacement_cost"], 0)
        self.assertEqual(p["coverage"]["books_replacement_priced"], 0)

    def test_exclusion_policy_is_explicit(self):
        self.draft.books[0].used_value.amount = None
        self.assertEqual(self.build()["totals"]["excluded_from_totals"], 4)
        self.policy.exclusion_basis = "missing_all_components"
        self.assertEqual(self.build()["totals"]["excluded_from_totals"], 3)
        with self.assertRaises(ValidationError):
            PacketPolicy(currency_decimal_places=2)

    def test_missing_hash_and_frame_evidence_fail(self):
        self.draft.frames[0].sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.build()
        self.draft.frames[0].sha256 = hashlib.sha256((self.root / self.draft.frames[0].path).read_bytes()).hexdigest()
        self.draft.books[0].frame_ref = "absent"
        with self.assertRaisesRegex(ValueError, "does not resolve"):
            self.build()

    def test_unsafe_paths_rejected(self):
        for path in ["../escape.png", "C:/frames/a.png", "frames/../a.png", "frames\\a.png", "/frames/a.png"]:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                FrameEvidence(id="bad", path=path, sha256="0" * 64, captured_at=self.draft.sweep.captured_at)

    def test_invalid_numbers_and_identity_rejected(self):
        for value in ["NaN", "Infinity", "-1"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Book(id="x", frame_ref="frame-1", spine_height_cm=value)
        with self.assertRaises(ValidationError):
            Book(id="x", frame_ref="frame-1", status="unidentified", title="guess")

    def test_stage_timing_and_failure_contract(self):
        args = dict(sweep_id="s", job_id="j", input_revision=1, stage="test", status="failed",
                    started_at=self.draft.sweep.captured_at, finished_at=self.draft.sweep.captured_at)
        with self.assertRaises(ValidationError):
            StageResult(**args)
        error = dict(code="unavailable", reason="Unavailable", retryable=True, ref_id="s", field="capture")
        self.assertEqual(StageResult(**args, errors=[error]).status, "failed")
        args["started_at"] = "2026-10-11T10:00:00Z"
        with self.assertRaises(ValidationError):
            StageResult(**args, errors=[error])

    def test_conflicting_measurement_records_fail(self):
        duplicate = self.draft.measurements[0].model_copy(deep=True)
        duplicate.id = "conflicting-measure"
        duplicate.value = Decimal("99")
        self.draft.measurements.append(duplicate)
        with self.assertRaisesRegex(ValueError, "one accepted measurement"):
            self.build()

    def test_measurement_foreign_reference_fails(self):
        self.draft.measurements[0].ref_id = "absent"
        with self.assertRaisesRegex(ValueError, "missing inventory"):
            self.build()

    def test_unknown_item_category_cannot_be_priced(self):
        self.draft.items[0].field_evidence.pop("category")
        self.assertIsNone(self.build()["items"][0]["replacement_cost"]["low"])

    def test_square_foot_conversion_from_declared_area(self):
        m = self.draft.measurements[0].model_copy(deep=True)
        m.id, m.ref_id, m.field, m.value, m.unit = "floor", "room", "floor_area_m2", Decimal("12"), "m2"
        self.draft.measurements.append(m)
        self.draft.room.floor_area_m2 = Decimal("12")
        self.assertEqual(self.build()["room"]["floor_area_ft2"], Decimal("129.1669250004"))

    def test_html_escape_and_numeric_consistency(self):
        self.draft.books[0].title = '<script>alert("test")</script>'
        p = json.loads(json_text(self.build()), parse_float=Decimal)
        report = render_report(p)
        self.assertNotIn('<script>', report)
        self.assertIn('&lt;script&gt;', report)
        self.assertIn('10.01', report)
        self.assertIn('SYNTHETIC FIXTURE', report)
        self.assertIn('Unknown', report)

    def test_portable_export_and_no_overwrite(self):
        output = self.root / "export"
        packet_path, report_path = export_packet(self.draft, self.root, output, self.policy)
        p = json.loads(packet_path.read_text(encoding="utf-8"), parse_float=Decimal)
        self.assertEqual(report_path.read_text(encoding="utf-8"), render_report(p))
        for evidence in p["evidence_manifest"] + p["quote_manifest"]:
            copied = output / evidence["path"]
            (self.root / evidence["path"]).unlink()
            self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), evidence["sha256"])
        # A second build from the exported evidence still validates independently.
        self.assertEqual(build_packet(self.draft, output, self.policy)["totals"], p["totals"])
        with self.assertRaises(FileExistsError):
            export_packet(self.draft, output, output, self.policy)


if __name__ == "__main__":
    unittest.main()
