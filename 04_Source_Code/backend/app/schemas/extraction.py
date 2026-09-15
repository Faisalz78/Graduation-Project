from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.invoice_data import InputModel


class ExtractionRequest(InputModel):
    revision: int = Field(ge=1, strict=True)
    language: Literal["ar", "en"] = "ar"
    force: bool = Field(default=False, strict=True)


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    value: str = Field(max_length=500)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal["OCR", "PDF_TEXT", "QR", "XML"]
    page: int | None = Field(default=None, ge=1, le=3)
    bbox: list[Annotated[float, Field(ge=0, le=1)]] | None = Field(
        default=None, min_length=4, max_length=4
    )
    evidence: str = Field(max_length=2000)
    recognition_reads: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=30
    )
    needs_review: Literal[True] = True
    interpretation: Literal["LOCAL_VISION"] | None = None

    @model_validator(mode="after")
    def ordered_box(self):
        if self.source in ("OCR", "PDF_TEXT", "QR") and (self.page is None or self.bbox is None):
            raise ValueError("Visual evidence requires page coordinates")
        if self.source == "XML" and (self.page is not None or self.bbox is not None):
            raise ValueError("XML evidence cannot use page coordinates")
        if self.bbox and (self.bbox[0] > self.bbox[2] or self.bbox[1] > self.bbox[3]):
            raise ValueError("Invalid evidence coordinates")
        return self


class StructuredValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(max_length=500)
    evidence: str = Field(max_length=500)


class StructuredSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["QR", "XML"]
    location: Literal["DOCUMENT_PAGE", "UPLOAD", "PDF_ATTACHMENT"]
    page: int | None = Field(default=None, ge=1, le=3)
    bbox: list[Annotated[float, Field(ge=0, le=1)]] | None = Field(
        default=None, min_length=4, max_length=4
    )
    name: str | None = Field(default=None, max_length=160)
    document_type: Literal["ZATCA_TLV", "Invoice", "CreditNote", "DebitNote"]
    present_tags: list[Annotated[int, Field(ge=1, le=9)]] = Field(max_length=9)
    fields: dict[str, StructuredValue] = Field(max_length=12)

    @model_validator(mode="after")
    def valid_location(self):
        if self.type == "QR" and (
            self.location != "DOCUMENT_PAGE" or not self.page or not self.bbox
        ):
            raise ValueError("QR evidence requires page coordinates")
        if self.type == "XML" and (self.page is not None or self.bbox is not None):
            raise ValueError("XML evidence cannot use page coordinates")
        return self


class ExtractionToken(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal["OCR", "PDF_TEXT"]
    page: int = Field(ge=1, le=3)
    bbox: list[Annotated[float, Field(ge=0, le=1)]] = Field(min_length=4, max_length=4)
    layout_bbox: list[Annotated[float, Field(ge=0, le=1)]] | None = Field(
        default=None, min_length=4, max_length=4
    )
    reading_order: int = Field(ge=1, le=2500)
    line_number: int = Field(ge=1, le=2500)
    recognition_reads: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=30
    )

    @model_validator(mode="after")
    def valid_coordinates(self):
        for box in (self.bbox, self.layout_bbox):
            if box and (box[0] > box[2] or box[1] > box[3]):
                raise ValueError("Invalid token coordinates")
        if self.source == "PDF_TEXT" and self.confidence is not None:
            raise ValueError("Direct text has no recognition confidence")
        return self


class PageRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    page: int = Field(ge=1, le=3)
    method: Literal["PDF_TEXT", "OCR", "BLANK"]
    reason: Literal[
        "SEARCHABLE_TEXT",
        "MAINLY_SCANNED",
        "DIRECT_EXTRACTION_FAILED",
        "NO_SEARCHABLE_TEXT",
        "UNUSABLE_TEXT",
        "IMAGE_UPLOAD",
        "BLANK_PAGE",
    ]
    image_coverage: float = Field(ge=0, le=1)


class LocalUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: Literal["qwen3-vl:8b-instruct"]
    version: str = Field(max_length=80)
    status: Literal["COMPLETED", "PARTIAL", "UNAVAILABLE", "NOT_APPLICABLE"]
    pages: int = Field(ge=0, le=3)
    added_fields: int = Field(ge=0, le=10)
    confirmed_fields: int = Field(ge=0, le=200)
    added_rows: int = Field(ge=0, le=100)
    conflicts: int = Field(ge=0, le=2500)
    rejected_values: int = Field(ge=0, le=2500)
    seconds: float = Field(ge=0, le=600)


class ImagePreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, le=3)
    method: Literal["ORIGINAL", "PERSPECTIVE_CORRECTED"]
    reread_regions: int = Field(ge=0, le=6)
    rotation: Literal[0, 90, 180, 270] = 0
    curvature_corrected: bool = False


class ConflictDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal[
        "supplier_name",
        "invoice_number",
        "invoice_date",
        "currency",
        "subtotal",
        "tax_total",
        "grand_total",
        "description",
        "quantity",
        "unit_price",
        "discount_amount",
        "tax_rate",
        "document_total",
    ]
    row: int | None = Field(default=None, ge=1, le=100)
    reason: Literal["DISAGREEMENT", "ROW_TOTAL_MISMATCH"]
    current: Suggestion | None = None
    proposed: Suggestion


class ReadingRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    page: int = Field(ge=1, le=3)
    kind: Literal["HEADER", "TOTALS", "TABLE"]
    bbox: list[Annotated[float, Field(ge=0, le=1)]] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def ordered_coordinates(self):
        if self.bbox[0] >= self.bbox[2] or self.bbox[1] >= self.bbox[3]:
            raise ValueError("Invalid region coordinates")
        return self


class GuidedReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempted: int = Field(ge=0, le=18)
    completed: int = Field(ge=0, le=18)
    table_sections: int = Field(ge=0, le=12)
    recovered_tokens: int = Field(ge=0, le=2500)
    status: Literal["COMPLETED", "PARTIAL", "UNAVAILABLE"]
    regions: list[ReadingRegion] = Field(max_length=18)

    @model_validator(mode="after")
    def consistent_counts(self):
        if (
            self.completed > self.attempted
            or self.table_sections > self.completed
            or len(self.regions) != self.attempted
        ):
            raise ValueError("Inconsistent region progress")
        return self


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reader_version: str = Field(max_length=80)
    parser_version: str = Field(max_length=80)
    fields: dict[str, Suggestion] = Field(max_length=10)
    items: list[Annotated[dict[str, Suggestion], Field(max_length=7)]] = Field(max_length=100)
    warnings: list[Annotated[str, Field(max_length=100)]] = Field(max_length=100)
    requires_human_review: Literal[True]
    structured_version: str | None = Field(default=None, max_length=80)
    structured_sources: list[StructuredSource] = Field(default_factory=list, max_length=6)
    text: str = Field(default="", max_length=85000)
    tokens: list[ExtractionToken] = Field(default_factory=list, max_length=2500)
    page_routes: list[PageRoute] = Field(default_factory=list, max_length=3)
    local_understanding: LocalUnderstanding | None = None
    image_preparation: list[ImagePreparation] = Field(default_factory=list, max_length=3)
    conflict_details: list[ConflictDetail] = Field(default_factory=list, max_length=60)
    guided_reading: GuidedReading | None = None

    @model_validator(mode="after")
    def valid_reading_order(self):
        if [token.reading_order for token in self.tokens] != list(range(1, len(self.tokens) + 1)):
            raise ValueError("Reading order must be contiguous and unique")
        if [token.page for token in self.tokens] != sorted(token.page for token in self.tokens):
            raise ValueError("Token pages must be ordered")
        pages = [route.page for route in self.page_routes]
        if pages != list(range(1, len(pages) + 1)):
            raise ValueError("Page routes must be contiguous and unique")
        return self
