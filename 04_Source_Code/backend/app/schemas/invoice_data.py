import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.regions import validate_region_code

Currency = Literal["SAR", "AED", "USD", "EUR"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_null_character(cls, value):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("النص يحتوي على محرف غير مسموح.")
        return value


class SupplierInput(InputModel):
    name: str = Field(min_length=2, max_length=200)
    tax_number: str | None = Field(default=None, max_length=40)
    region_code: str | None = Field(default=None, max_length=30)

    @field_validator("tax_number", "region_code")
    @classmethod
    def empty_optional_value(cls, value):
        return value or None

    @field_validator("region_code")
    @classmethod
    def known_region(cls, value):
        return validate_region_code(value)


class ItemInput(InputModel):
    purchase_order_item_id: uuid.UUID | None = None
    project_budget_line_id: uuid.UUID | None = None
    description: str = Field(min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=40)
    quantity: Annotated[Decimal, Field(gt=0, le=1_000_000, max_digits=14, decimal_places=4)]
    unit_price: Annotated[Decimal, Field(ge=0, le=1_000_000_000, max_digits=18, decimal_places=4)]
    discount_amount: Annotated[Decimal, Field(ge=0, le=10**15, max_digits=22, decimal_places=2)]
    tax_rate: Annotated[Decimal, Field(ge=0, le=100, max_digits=7, decimal_places=4)]

    @field_validator("quantity", "unit_price", "discount_amount", "tax_rate", mode="before")
    @classmethod
    def decimal_text(cls, value):
        # JSON strings preserve exact decimals across browsers, including large amounts.
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,18}(?:\.\d{1,4})?", value):
            raise ValueError("أدخل رقمًا عشريًا موجبًا أو صفرًا بصيغة نصية دون فاصلة آلاف.")
        return value

    @field_validator("unit")
    @classmethod
    def empty_unit(cls, value):
        return value or None


class CalculationInput(InputModel):
    currency: Currency | None
    items: list[ItemInput] = Field(max_length=100)

    @model_validator(mode="after")
    def currency_for_items(self):
        if self.items and not self.currency:
            raise ValueError("اختر العملة قبل حفظ البنود.")
        return self


class DocumentTotalsInput(InputModel):
    subtotal: Annotated[
        Decimal | None, Field(default=None, ge=0, le=10**15, max_digits=22, decimal_places=2)
    ]
    tax_total: Annotated[
        Decimal | None, Field(default=None, ge=0, le=10**15, max_digits=22, decimal_places=2)
    ]
    grand_total: Annotated[
        Decimal | None, Field(default=None, ge=0, le=10**15, max_digits=22, decimal_places=2)
    ]

    @field_validator("subtotal", "tax_total", "grand_total", mode="before")
    @classmethod
    def decimal_text(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,16}(?:\.\d{1,2})?", value):
            raise ValueError("أدخل مبلغًا موجبًا أو صفرًا كنص عشري حتى منزلتين.")
        return value


class InvoiceUpdate(CalculationInput):
    extraction_job_id: uuid.UUID | None = None
    extraction_confirmed: bool = Field(default=False, strict=True)
    revision: int = Field(ge=1)
    supplier_id: uuid.UUID | None
    purchase_order_id: uuid.UUID | None = None
    document_type: Literal["INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"] = "INVOICE"
    related_invoice_id: uuid.UUID | None = None
    invoice_number: str | None = Field(max_length=100)
    invoice_date: date | None
    document_totals: DocumentTotalsInput | None = None
    note: str | None = Field(max_length=1000)

    @model_validator(mode="after")
    def extraction_review(self):
        if bool(self.extraction_job_id) != self.extraction_confirmed:
            raise ValueError("أكد مراجعة اقتراحات الاستخراج ومطابقتها للأصل قبل حفظها.")
        if (self.document_type == "INVOICE") != (self.related_invoice_id is None):
            raise ValueError("اربط الإشعار الدائن أو المدين بفاتورته الأصلية فقط.")
        return self

    @field_validator("invoice_number", "note")
    @classmethod
    def empty_text(cls, value):
        return value or None

    @field_validator("invoice_date", mode="before")
    @classmethod
    def iso_date(cls, value):
        if value is not None and (
            not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
        ):
            raise ValueError("التاريخ مطلوب بصيغة YYYY-MM-DD أو قيمة خالية.")
        return value
