"""Explicit arithmetic policy v1; it does not infer tax rates or regulatory treatment."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from fastapi import HTTPException

from app.schemas.invoice_data import CalculationInput

CENT = Decimal("0.01")
POLICY = "line-exclusive-half-up-v1"


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate(data: CalculationInput):
    if not data.items:
        return {"items": [], "totals": None, "calculation_policy": POLICY}
    lines = []
    subtotal = discount = tax = Decimal("0.00")
    with localcontext() as context:
        context.prec = 40
        for position, item in enumerate(data.items, 1):
            gross = money(item.quantity * item.unit_price)
            if item.discount_amount > gross:
                raise HTTPException(422, f"خصم البند {position} يتجاوز قيمته قبل الضريبة.")
            net = gross - item.discount_amount
            line_tax = money(net * item.tax_rate / Decimal("100"))
            lines.append(
                {
                    "position": position,
                    "description": item.description,
                    "unit": item.unit,
                    "quantity": format(item.quantity, ".4f"),
                    "unit_price": format(item.unit_price, ".4f"),
                    "discount_amount": format(item.discount_amount, ".2f"),
                    "tax_rate": format(item.tax_rate, ".4f"),
                    "gross_amount": format(gross, ".2f"),
                    "net_amount": format(net, ".2f"),
                    "tax_amount": format(line_tax, ".2f"),
                    "total_amount": format(net + line_tax, ".2f"),
                }
            )
            subtotal += gross
            discount += item.discount_amount
            tax += line_tax
    return {
        "items": lines,
        "totals": {
            "subtotal": format(subtotal, ".2f"),
            "discount_total": format(discount, ".2f"),
            "net_total": format(subtotal - discount, ".2f"),
            "tax_total": format(tax, ".2f"),
            "grand_total": format(subtotal - discount + tax, ".2f"),
        },
        "calculation_policy": POLICY,
    }
