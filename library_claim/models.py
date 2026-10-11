"""Typed boundaries. Unknown values stay present; monetary inputs use Decimal."""

from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Number = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Confidence = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class Sweep(Contract):
    id: str = Field(min_length=1)
    captured_at: datetime
    device: str = ""
    duration_s: Number | None = None
    country: str
    currency: str

    @field_validator("country", "currency")
    @classmethod
    def locale_code(cls, value: str, info):
        size = 2 if info.field_name == "country" else 3
        if len(value) != size or not value.isascii() or not value.isalpha() or value != value.upper():
            raise ValueError(f"{info.field_name} must be an uppercase {size}-letter code")
        return value

    @field_validator("captured_at")
    @classmethod
    def timezone_required(cls, value: datetime):
        if value.utcoffset() is None:
            raise ValueError("capture timestamp needs a timezone")
        return value


class PacketPolicy(Contract):
    """Caller supplies conventions; no country, rounding or exclusion default."""

    currency_decimal_places: int = Field(ge=0, le=4)
    shelf_run_basis: Literal["sum_spine_thickness"]
    exclusion_basis: Literal["missing_any_component", "missing_all_components"]


class SavedEvidence(Contract):
    id: str = Field(min_length=1)
    path: str
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("path")
    @classmethod
    def portable_relative_path(cls, value: str):
        posix = PurePosixPath(value)
        windows = PureWindowsPath(value)
        if (not value or "\\" in value or posix.is_absolute() or windows.drive
                or ".." in posix.parts or any(ord(c) < 32 for c in value)):
            raise ValueError("evidence path must be a safe portable relative path")
        return value


class FrameEvidence(SavedEvidence):
    captured_at: datetime

    _timezone = field_validator("captured_at")(classmethod(Sweep.timezone_required.__func__))

    @field_validator("path")
    @classmethod
    def frame_path(cls, value: str):
        if not value.startswith("frames/") or PurePosixPath(value).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("frame must be a PNG/JPEG in frames/")
        return value


class QuoteEvidence(SavedEvidence):
    source: str = Field(min_length=1)
    url: str
    retrieved_at: datetime
    amount: Number
    currency: str
    condition: str = Field(min_length=1)
    physical_format: str = Field(min_length=1)
    available: bool
    source_type: Literal["new_physical", "used_asking", "used_sold", "item_comparable"]

    @field_validator("path")
    @classmethod
    def quote_path(cls, value: str):
        if not value.startswith("quotes/") or PurePosixPath(value).suffix.lower() != ".json":
            raise ValueError("quote snapshot must be JSON in quotes/")
        return value

    @field_validator("url")
    @classmethod
    def source_url(cls, value: str):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("price URL must be HTTP(S), without embedded credentials")
        return value

    _timezone = field_validator("retrieved_at")(classmethod(Sweep.timezone_required.__func__))

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value: str):
        if len(value) != 3 or not value.isascii() or not value.isalpha() or value != value.upper():
            raise ValueError("quote currency must be an uppercase three-letter code")
        return value


class MeasurementEvidence(Contract):
    id: str = Field(min_length=1)
    ref_id: str
    field: str
    value: Number
    unit: Literal["cm", "m", "m2"]
    frame_refs: list[str] = Field(min_length=1)
    scale_method: str = Field(min_length=1)
    derivation: str = Field(min_length=1)


class Price(Contract):
    amount: Number | None = None
    source: str = ""
    url: str = ""
    retrieved_at: datetime | None = None
    converted: bool = False
    condition_assumed: str = ""
    quote_ref: str = ""
    currency: str = ""


class ItemPrice(Contract):
    low: Number | None = None
    high: Number | None = None
    source: str = ""
    url: str = ""
    retrieved_at: datetime | None = None
    quote_refs: list[str] = Field(default_factory=list)
    condition_assumed: str = ""
    currency: str = ""

    @model_validator(mode="after")
    def ordered_bounds(self):
        if (self.low is None) != (self.high is None):
            raise ValueError("price range needs both bounds or neither")
        if self.low is not None and self.low > self.high:
            raise ValueError("price low cannot exceed high")
        return self


class Book(Contract):
    id: str = Field(min_length=1)
    shelf: str = ""
    position: int = Field(default=0, ge=0)
    frame_ref: str
    status: Literal["identified", "unidentified", "needs_appraisal"] = "unidentified"
    title: str = ""
    author: str = ""
    edition: str = ""
    isbn: str = ""
    publisher: str = ""
    spine_height_cm: Number | None = None
    spine_thickness_cm: Number | None = None
    id_confidence: Confidence | None = None
    replacement_cost: Price = Field(default_factory=Price)
    used_value: Price = Field(default_factory=Price)
    owned: bool = True
    field_evidence: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def identity_status(self):
        if self.status == "identified" and not self.title.strip():
            raise ValueError("identified book needs a supported title")
        if self.status == "unidentified" and any([self.title, self.author, self.edition, self.isbn, self.publisher]):
            raise ValueError("unidentified book cannot contain bibliographic guesses")
        return self


class Dimensions(Contract):
    w: Number | None = None
    h: Number | None = None
    d: Number | None = None


class Item(Contract):
    id: str = Field(min_length=1)
    category: str = ""
    description: str = ""
    brand_model: str = ""
    frame_ref: str
    dimensions_cm: Dimensions = Field(default_factory=Dimensions)
    status: Literal["", "priced", "range", "needs_appraisal"] = ""
    replacement_cost: ItemPrice = Field(default_factory=ItemPrice)
    confidence: Confidence | None = None
    owned: bool = True
    # An explicit assertion is required before art/portrait pricing.
    artwork_kind: Literal["", "original", "print"] = ""
    field_evidence: dict[str, list[str]] = Field(default_factory=dict)


class Room(Contract):
    length_m: Number | None = None
    width_m: Number | None = None
    height_m: Number | None = None
    floor_area_m2: Number | None = None
    wall_area_m2: Number | None = None
    shelved_wall_area_m2: Number | None = None
    scale_method: str = ""
    confidence: Confidence | None = None


class ReviewFinding(Contract):
    ref_id: str
    reason: str


class PacketInput(Contract):
    sweep: Sweep
    room: Room = Field(default_factory=Room)
    books: list[Book] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    frames: list[FrameEvidence] = Field(default_factory=list)
    quotes: list[QuoteEvidence] = Field(default_factory=list)
    measurements: list[MeasurementEvidence] = Field(default_factory=list)
    review_queue: list[ReviewFinding] = Field(default_factory=list)
    synthetic: bool = False


class StageError(Contract):
    code: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    retryable: bool
    ref_id: str
    field: str


class StageResult(Contract):
    schema_version: str = "1.0"
    sweep_id: str
    job_id: str
    input_revision: int = Field(ge=0)
    stage: str
    status: Literal["success", "partial", "unavailable", "failed"]
    started_at: datetime
    finished_at: datetime
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[StageError] = Field(default_factory=list)

    @model_validator(mode="after")
    def timing(self):
        Sweep.timezone_required(self.started_at)
        Sweep.timezone_required(self.finished_at)
        if self.finished_at < self.started_at:
            raise ValueError("stage finished before it started")
        if self.status == "failed" and not self.errors:
            raise ValueError("failed stage needs an error reason")
        return self
