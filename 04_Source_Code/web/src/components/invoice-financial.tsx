import { type FinancialData, type Totals } from "@/lib/api";

export function amount(value: string | null | undefined, currency?: string | null) {
  if (value == null) return "غير مدخل";
  const [whole, fraction = "00"] = value.split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction.padEnd(2, "0")} ${currency || ""}`.trim();
}

export function InvoiceTotals({
  totals,
  currency,
}: {
  totals: Totals | null;
  currency: string | null;
}) {
  if (!totals) return <p className="financial-empty">لا توجد إجماليات محسوبة بعد.</p>;
  return (
    <dl className="invoice-totals">
      <div>
        <dt>قيمة البنود قبل الخصم</dt>
        <dd>
          <bdi>{amount(totals.subtotal, currency)}</bdi>
        </dd>
      </div>
      <div>
        <dt>الخصم</dt>
        <dd>
          <bdi>{amount(totals.discount_total, currency)}</bdi>
        </dd>
      </div>
      <div>
        <dt>الصافي قبل الضريبة</dt>
        <dd>
          <bdi>{amount(totals.net_total, currency)}</bdi>
        </dd>
      </div>
      <div>
        <dt>الضريبة</dt>
        <dd>
          <bdi>{amount(totals.tax_total, currency)}</bdi>
        </dd>
      </div>
      <div className="grand-total">
        <dt>الإجمالي</dt>
        <dd data-testid="grand-total">
          <bdi>{amount(totals.grand_total, currency)}</bdi>
        </dd>
      </div>
    </dl>
  );
}

export function InvoiceDataView({
  data,
  showNote = false,
}: {
  data: FinancialData;
  showNote?: boolean;
}) {
  const documentLabels = {
    INVOICE: "فاتورة أصلية",
    CREDIT_NOTE: "إشعار دائن",
    DEBIT_NOTE: "إشعار مدين",
  } as const;
  const verificationLabels = {
    UNVERIFIED: "غير مراجع داخليًا",
    PENDING: "التحقق الداخلي قيد المراجعة",
    VERIFIED: "متحقق داخليًا",
    REJECTED: "مرفوض في التحقق الداخلي",
  } as const;
  return (
    <>
      <dl className="financial-metadata">
        <div>
          <dt>نوع المستند</dt>
          <dd>{documentLabels[data.document_type || "INVOICE"]}</dd>
        </div>
        <div>
          <dt>الفاتورة الأصلية</dt>
          <dd>
            <bdi>{data.related_document?.invoice_number || "غير مرتبط"}</bdi>
          </dd>
        </div>
        <div>
          <dt>المورد</dt>
          <dd>{data.supplier?.name || "غير مدخل"}</dd>
        </div>
        <div>
          <dt>الرقم الضريبي للمورد</dt>
          <dd>
            <bdi>{data.supplier?.tax_number || "غير مدخل"}</bdi>
          </dd>
        </div>
        <div>
          <dt>رقم الفاتورة</dt>
          <dd>
            <bdi>{data.invoice_number || "غير مدخل"}</bdi>
          </dd>
        </div>
        <div>
          <dt>تاريخ الفاتورة</dt>
          <dd>
            <bdi>{data.invoice_date || "غير مدخل"}</bdi>
          </dd>
        </div>
        <div>
          <dt>العملة</dt>
          <dd>{data.currency || "غير مدخلة"}</dd>
        </div>
        <div>
          <dt>أمر الشراء</dt>
          <dd>
            <bdi>{data.purchase_order?.number || "غير مرتبط"}</bdi>
          </dd>
        </div>
        {showNote && (
          <div>
            <dt>الملاحظة</dt>
            <dd>{data.note || "لا توجد ملاحظة"}</dd>
          </div>
        )}
      </dl>
      {data.supplier && (
        <p
          className={`field-hint supplier-verification verification-${data.supplier.verification_status.toLowerCase()}`}
        >
          {verificationLabels[data.supplier.verification_status]}
          {data.supplier.verification_note ? ` — ${data.supplier.verification_note}` : ""}
        </p>
      )}
      {data.document_totals && (
        <div className="document-totals-view">
          <h3>الإجماليات الظاهرة على أصل الفاتورة</h3>
          <dl className="invoice-totals">
            <div>
              <dt>الصافي قبل الضريبة</dt>
              <dd>
                <bdi>{amount(data.document_totals.subtotal, data.currency)}</bdi>
              </dd>
            </div>
            <div>
              <dt>إجمالي الضريبة</dt>
              <dd>
                <bdi>{amount(data.document_totals.tax_total, data.currency)}</bdi>
              </dd>
            </div>
            <div>
              <dt>الإجمالي المستحق</dt>
              <dd>
                <bdi>{amount(data.document_totals.grand_total, data.currency)}</bdi>
              </dd>
            </div>
          </dl>
        </div>
      )}
      {data.items?.length ? (
        <div className="line-results">
          {data.items.map((item) => (
            <article key={item.position} className="line-result">
              <strong>
                {item.position}. {item.description}
              </strong>
              <p>
                الكمية: <bdi>{item.quantity}</bdi>
                {item.unit ? ` ${item.unit}` : ""} · سعر الوحدة:{" "}
                <bdi>{amount(item.unit_price, data.currency)}</bdi>
              </p>
              <p>
                الخصم: <bdi>{amount(item.discount_amount, data.currency)}</bdi> · الضريبة:{" "}
                <bdi>{item.tax_rate}%</bdi> (<bdi>{amount(item.tax_amount, data.currency)}</bdi>)
              </p>
              {item.purchase_order_item_position && (
                <p className="po-line-link">
                  مرتبط بالبند {item.purchase_order_item_position} من أمر الشراء
                </p>
              )}
              <div>
                إجمالي البند{" "}
                <strong>
                  <bdi>{amount(item.total_amount, data.currency)}</bdi>
                </strong>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="financial-empty">لم تُضف بنود الفاتورة بعد.</p>
      )}
      <InvoiceTotals totals={data.totals} currency={data.currency} />
    </>
  );
}
