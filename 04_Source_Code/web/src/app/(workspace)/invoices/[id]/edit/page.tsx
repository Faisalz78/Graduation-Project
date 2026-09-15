"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, Check, Download, FileText, LoaderCircle, Plus, Trash2 } from "lucide-react";
import {
  api,
  ApiError,
  type Calculation,
  type Currency,
  type DocumentType,
  type Invoice,
  type ItemInput,
  type PurchaseOrder,
  type ProjectBudgetView,
  type RelatedDocument,
  type Supplier,
  type ExtractionJob,
  statusLabels,
} from "@/lib/api";
import { useSession } from "@/components/session-provider";
import { InvoiceTotals } from "@/components/invoice-financial";
import { SupplierDialog } from "@/components/supplier-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { InvoiceExtraction } from "@/components/invoice-extraction";

type EditItem = ItemInput & { key: string };
type DraftForm = {
  supplier_id: string;
  purchase_order_id: string;
  document_type: DocumentType;
  related_invoice_id: string;
  invoice_number: string;
  invoice_date: string;
  currency: Currency | "";
  document_totals: { subtotal: string; tax_total: string; grand_total: string };
  note: string;
  items: EditItem[];
};
function fromInvoice(invoice: Invoice): DraftForm {
  return {
    supplier_id: invoice.supplier?.id || "",
    purchase_order_id: invoice.purchase_order?.id || "",
    document_type: invoice.document_type,
    related_invoice_id: invoice.related_document?.id || "",
    invoice_number: invoice.invoice_number || "",
    invoice_date: invoice.invoice_date || "",
    currency: invoice.currency || "",
    document_totals: {
      subtotal: invoice.document_totals?.subtotal || "",
      tax_total: invoice.document_totals?.tax_total || "",
      grand_total: invoice.document_totals?.grand_total || "",
    },
    note: invoice.note || "",
    items: (invoice.items || []).map((item) => ({
      key: crypto.randomUUID(),
      description: item.description,
      unit: item.unit || "",
      quantity: item.quantity,
      unit_price: item.unit_price,
      discount_amount: item.discount_amount,
      tax_rate: item.tax_rate,
      purchase_order_item_id: item.purchase_order_item_id,
      project_budget_line_id: item.project_budget_line_id,
    })),
  };
}
function decimalInput(value: string) {
  return value
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/٫/g, ".");
}
function itemPayload(items: EditItem[]) {
  return items.map(({ key: _key, ...item }) => ({
    ...item,
    unit: item.unit?.trim() || null,
    purchase_order_item_id: item.purchase_order_item_id || null,
    project_budget_line_id: item.project_budget_line_id || null,
  }));
}

export default function EditInvoicePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { csrf_token, user } = useSession();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [form, setForm] = useState<DraftForm | null>(null);
  const [initial, setInitial] = useState("");
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [purchaseOrders, setPurchaseOrders] = useState<PurchaseOrder[]>([]);
  const [relatedOptions, setRelatedOptions] = useState<RelatedDocument[]>([]);
  const [budgetView, setBudgetView] = useState<ProjectBudgetView | null>(null);
  const [budgetLoading, setBudgetLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [preview, setPreview] = useState<{ signature: string; data: Calculation } | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [extractionJob, setExtractionJob] = useState<string | null>(null);
  const [extractionConfirmed, setExtractionConfirmed] = useState(false);
  const dirty = form !== null && JSON.stringify(form) !== initial;
  useEffect(() => {
    let active = true;
    setLoadError("");
    setInvoice(null);
    setForm(null);
    setExtractionJob(null);
    setExtractionConfirmed(false);
    Promise.all([
      api<Invoice>(`/invoices/${id}`),
      api<Supplier[]>("/suppliers"),
      api<PurchaseOrder[]>("/purchase-orders"),
      api<RelatedDocument[]>(`/invoices/${id}/related-options`),
    ])
      .then(([data, choices, orders, related]) => {
        if (!active) return;
        const next = fromInvoice(data);
        setInvoice(data);
        setForm(next);
        setInitial(JSON.stringify(next));
        setSuppliers(choices);
        setPurchaseOrders(orders);
        setRelatedOptions(related);
        setConflict(false);
        setError("");
      })
      .catch((failure) => {
        if (active) setLoadError(failure.message);
      });
    return () => {
      active = false;
    };
  }, [id, attempt]);
  useEffect(() => {
    if (!invoice || !form?.currency) {
      setBudgetView(null);
      return;
    }
    let active = true;
    setBudgetLoading(true);
    api<ProjectBudgetView>(`/projects/${invoice.project.id}/budgets/${form.currency}`)
      .then((data) => active && setBudgetView(data))
      .catch((failure) => active && setError(failure.message))
      .finally(() => active && setBudgetLoading(false));
    return () => {
      active = false;
    };
  }, [invoice, form?.currency]);
  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      event.preventDefault();
    }
    if (dirty && !busy) window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, busy]);
  const completeItems = form?.items.every(
    (item) =>
      item.description.trim() &&
      [item.quantity, item.unit_price, item.discount_amount, item.tax_rate].every((value) =>
        /^\d+(\.\d{1,4})?$/.test(value),
      ),
  );
  const signature =
    form?.items.length && form.currency && completeItems
      ? JSON.stringify({ currency: form.currency, items: itemPayload(form.items) })
      : "";
  useEffect(() => {
    setPreviewError("");
    if (!signature) {
      setPreview(null);
      return;
    }
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api<Calculation>(`/invoices/${id}/calculate`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: signature,
      })
        .then((data) => {
          if (active) setPreview({ signature, data });
        })
        .catch((failure) => {
          if (active) setPreviewError(failure.message);
        });
    }, 350);
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [signature, csrf_token, id]);
  function field<K extends keyof DraftForm>(name: K, value: DraftForm[K]) {
    setExtractionConfirmed(false);
    if (!conflict) setError("");
    setForm((current) => current && { ...current, [name]: value });
  }
  function changeItem(key: string, name: keyof ItemInput, value: string) {
    setExtractionConfirmed(false);
    if (!conflict) setError("");
    setForm(
      (current) =>
        current && {
          ...current,
          items: current.items.map((item) =>
            item.key === key ? { ...item, [name]: value } : item,
          ),
        },
    );
  }
  function documentTotal(name: keyof DraftForm["document_totals"], value: string) {
    setExtractionConfirmed(false);
    if (!conflict) setError("");
    setForm(
      (current) =>
        current && {
          ...current,
          document_totals: { ...current.document_totals, [name]: value },
        },
    );
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form || !invoice || invoice.id !== id || busy) return;
    if (extractionJob && !extractionConfirmed) {
      setError("أكد مراجعة الاقتراحات ومطابقتها للأصل قبل الحفظ.");
      return;
    }
    setBusy(true);
    setError("");
    setConflict(false);
    try {
      const result = await api<Invoice>(`/invoices/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: JSON.stringify({
          revision: invoice.revision,
          supplier_id: form.supplier_id || null,
          purchase_order_id: form.purchase_order_id || null,
          document_type: form.document_type,
          related_invoice_id: form.related_invoice_id || null,
          invoice_number: form.invoice_number.trim() || null,
          invoice_date: form.invoice_date || null,
          currency: form.currency || null,
          document_totals: Object.values(form.document_totals).some(Boolean)
            ? Object.fromEntries(
                Object.entries(form.document_totals).map(([name, value]) => [name, value || null]),
              )
            : null,
          note: form.note.trim() || null,
          items: itemPayload(form.items),
          extraction_job_id: extractionJob,
          extraction_confirmed: extractionConfirmed,
        }),
      });
      setInitial(JSON.stringify(form));
      router.push(`/invoices/${result.id}?updated=1`);
    } catch (failure) {
      setError((failure as Error).message);
      setConflict(failure instanceof ApiError && failure.status === 409);
      setBusy(false);
    }
  }
  function importSuggestions(job: ExtractionJob) {
    if (!job.result || job.is_stale || !invoice || job.base_revision !== invoice.revision) return;
    const result = job.result;
    const sourceDocumentType = result.structured_sources
      ?.map((source) => source.document_type)
      .find((value) => value === "CreditNote" || value === "DebitNote");
    setForm(
      (current) =>
        current && {
          ...current,
          document_type:
            current.document_type !== "INVOICE"
              ? current.document_type
              : sourceDocumentType === "CreditNote"
                ? "CREDIT_NOTE"
                : sourceDocumentType === "DebitNote"
                  ? "DEBIT_NOTE"
                  : "INVOICE",
          invoice_number: current.invoice_number || result.fields.invoice_number?.value || "",
          invoice_date: current.invoice_date || result.fields.invoice_date?.value || "",
          currency:
            current.currency ||
            (["SAR", "AED", "USD", "EUR"].includes(result.fields.currency?.value)
              ? (result.fields.currency.value as Currency)
              : ""),
          document_totals: {
            subtotal: current.document_totals.subtotal || result.fields.subtotal?.value || "",
            tax_total: current.document_totals.tax_total || result.fields.tax_total?.value || "",
            grand_total:
              current.document_totals.grand_total || result.fields.grand_total?.value || "",
          },
          items: current.items.length
            ? current.items
            : result.items.map((item) => ({
                key: crypto.randomUUID(),
                description: item.description?.value || "",
                unit: item.unit?.value || "",
                quantity: item.quantity?.value || "",
                unit_price: item.unit_price?.value || "",
                discount_amount: item.discount_amount?.value || "",
                tax_rate: item.tax_rate?.value || "",
                purchase_order_item_id: null,
                project_budget_line_id: null,
              })),
        },
    );
    setExtractionJob(job.id);
    setExtractionConfirmed(false);
    setError("");
  }
  if (user.role !== "EMPLOYEE")
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <h1>تعديل المسودة متاح لصاحبها الموظف</h1>
          <Link href="/invoices">العودة للفواتير</Link>
        </div>
      </div>
    );
  if (loadError)
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <p role="alert">{loadError}</p>
          <Button onClick={() => setAttempt((n) => n + 1)}>إعادة المحاولة</Button>
        </div>
      </div>
    );
  if (!invoice || invoice.id !== id || !form)
    return (
      <div className="inline-state">
        <LoaderCircle className="animate-spin" />
        جارٍ تحميل بيانات الفاتورة…
      </div>
    );
  if (!invoice.workflow?.allowed_actions.includes("EDIT"))
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <h1>الفاتورة غير متاحة للتعديل حاليًا</h1>
          <p>{statusLabels[invoice.status]}</p>
          <Link href={`/invoices/${id}`}>العودة إلى تفاصيل الفاتورة</Link>
        </div>
      </div>
    );
  const totals = preview?.signature === signature ? preview.data.totals : null;
  const availableOrders = purchaseOrders.filter((order) => order.project.id === invoice.project.id);
  const selectedOrder = availableOrders.find((order) => order.id === form.purchase_order_id);
  return (
    <div className="page-container">
      <Link className="back-link" href={`/invoices/${id}`}>
        <ArrowRight size={17} />
        العودة إلى تفاصيل الفاتورة
      </Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">استخراج ومراجعة البيانات</span>
          <h1>بيانات الفاتورة</h1>
          <p>استعن بقراءة المستند أو أدخل البيانات يدويًا، ثم راجعها مع الأصل.</p>
        </div>
        <span className="draft-badge large">
          نسخة {invoice.revision} · {statusLabels[invoice.status]}
        </span>
      </div>
      <InvoiceExtraction
        invoice={invoice}
        disabled={busy || conflict}
        onImport={importSuggestions}
      />
      <form className="invoice-editor-layout" onSubmit={save}>
        <div className="editor-main">
          <section className="surface editor-section">
            <div className="section-label">
              <span>01</span>
              <div>
                <h2>المورد وبيانات الفاتورة</h2>
                <p>الحقول الناقصة تبقى غير مدخلة حتى تكملها.</p>
              </div>
            </div>
            <fieldset className="plain-fieldset" disabled={busy}>
              <div className="editor-fields">
                <div className="field">
                  <label htmlFor="document-type">نوع المستند</label>
                  <select
                    id="document-type"
                    className="form-field"
                    value={form.document_type}
                    onChange={(event) => {
                      const value = event.target.value as DocumentType;
                      setExtractionConfirmed(false);
                      setForm((current) =>
                        current
                          ? {
                              ...current,
                              document_type: value,
                              related_invoice_id:
                                value === "INVOICE" ? "" : current.related_invoice_id,
                              purchase_order_id:
                                value === "INVOICE" ? current.purchase_order_id : "",
                              items: current.items.map((item) => ({
                                ...item,
                                purchase_order_item_id:
                                  value === "INVOICE" ? item.purchase_order_item_id : null,
                              })),
                            }
                          : current,
                      );
                    }}
                  >
                    <option value="INVOICE">فاتورة أصلية</option>
                    <option value="CREDIT_NOTE">إشعار دائن</option>
                    <option value="DEBIT_NOTE">إشعار مدين</option>
                  </select>
                </div>
                {form.document_type !== "INVOICE" && (
                  <div className="field">
                    <label htmlFor="related-invoice">الفاتورة الأصلية</label>
                    <select
                      id="related-invoice"
                      className="form-field"
                      required
                      value={form.related_invoice_id}
                      onChange={(event) => field("related_invoice_id", event.target.value)}
                    >
                      <option value="">اختر فاتورة سبق إرسالها</option>
                      {relatedOptions.map((original) => (
                        <option key={original.id} value={original.id}>
                          {original.invoice_number || "دون رقم"} —{" "}
                          {original.invoice_date || "دون تاريخ"} —{" "}
                          {original.grand_total || "غير مكتمل"} {original.currency || ""}
                        </option>
                      ))}
                    </select>
                    <p className="field-hint">
                      يلزم تطابق المشروع والمورد والعملة مع الفاتورة الأصلية.
                    </p>
                  </div>
                )}
                <div className="field supplier-field">
                  <label htmlFor="invoice-supplier">المورد</label>
                  <div className="supplier-picker">
                    <select
                      id="invoice-supplier"
                      className="form-field"
                      value={form.supplier_id}
                      onChange={(e) => field("supplier_id", e.target.value)}
                    >
                      <option value="">اختر المورد عند توفر بياناته</option>
                      {suppliers.map((supplier) => (
                        <option key={supplier.id} value={supplier.id}>
                          {supplier.name}
                        </option>
                      ))}
                    </select>
                    <Button type="button" variant="outline" onClick={() => setAdding(true)}>
                      <Plus size={16} />
                      إضافة مورد
                    </Button>
                  </div>
                </div>
                {form.document_type === "INVOICE" && (
                  <div className="field full-field">
                    <label htmlFor="invoice-purchase-order">
                      أمر الشراء <span className="optional-mark">اختياري</span>
                    </label>
                    <select
                      id="invoice-purchase-order"
                      className="form-field"
                      value={form.purchase_order_id}
                      onChange={(event) => {
                        setExtractionConfirmed(false);
                        if (!conflict) setError("");
                        setForm((current) =>
                          current
                            ? {
                                ...current,
                                purchase_order_id: event.target.value,
                                items: current.items.map((item) => ({
                                  ...item,
                                  purchase_order_item_id: null,
                                })),
                              }
                            : current,
                        );
                      }}
                    >
                      <option value="">بدون أمر شراء</option>
                      {availableOrders.map((order) => (
                        <option key={order.id} value={order.id}>
                          {order.number} — {order.supplier.name}
                        </option>
                      ))}
                    </select>
                    <p className="field-hint">
                      تظهر أوامر المشروع الحالي فقط. سيقارن التدقيق المورد والعملة والبنود
                      والاستلام.
                    </p>
                  </div>
                )}
                <div className="field">
                  <label htmlFor="invoice-number">رقم الفاتورة</label>
                  <Input
                    id="invoice-number"
                    maxLength={100}
                    value={form.invoice_number}
                    onChange={(e) => field("invoice_number", e.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="invoice-date">تاريخ الفاتورة</label>
                  <Input
                    id="invoice-date"
                    type="date"
                    dir="ltr"
                    value={form.invoice_date}
                    onChange={(e) => field("invoice_date", e.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="invoice-currency">العملة</label>
                  <select
                    id="invoice-currency"
                    className="form-field"
                    required={form.items.length > 0}
                    value={form.currency}
                    onChange={(event) => {
                      setExtractionConfirmed(false);
                      setForm((current) =>
                        current
                          ? {
                              ...current,
                              currency: event.target.value as Currency | "",
                              items: current.items.map((item) => ({
                                ...item,
                                project_budget_line_id: null,
                              })),
                            }
                          : current,
                      );
                    }}
                  >
                    <option value="">اختر العملة</option>
                    <option value="SAR">SAR — ريال سعودي</option>
                    <option value="AED">AED — درهم إماراتي</option>
                    <option value="USD">USD — دولار أمريكي</option>
                    <option value="EUR">EUR — يورو</option>
                  </select>
                </div>
                <div className="field full-field">
                  <label htmlFor="invoice-note">ملاحظة</label>
                  <textarea
                    id="invoice-note"
                    className="form-field"
                    maxLength={1000}
                    rows={2}
                    value={form.note}
                    onChange={(e) => field("note", e.target.value)}
                  />
                </div>
              </div>
            </fieldset>
          </section>
          <section className="surface editor-section">
            <div className="section-label">
              <span>02</span>
              <div>
                <h2>بنود الفاتورة</h2>
                <p>أدخل سعر الوحدة قبل الضريبة، والخصم كمبلغ على البند.</p>
              </div>
            </div>
            {!form.items.length && (
              <div className="financial-empty">
                لم تضف بنودًا بعد. يمكنك حفظ بيانات المسودة والعودة لإكمالها.
              </div>
            )}
            {form.items.map((item, index) => (
              <fieldset key={item.key} className="item-editor" disabled={busy}>
                <legend>البند {index + 1}</legend>
                <div className="item-editor-top">
                  <label htmlFor={`desc-${item.key}`}>وصف البند</label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      field(
                        "items",
                        form.items.filter((row) => row.key !== item.key),
                      )
                    }
                    aria-label={`حذف البند ${index + 1}`}
                  >
                    <Trash2 size={15} />
                    حذف
                  </Button>
                </div>
                <Input
                  id={`desc-${item.key}`}
                  required
                  maxLength={500}
                  value={item.description}
                  onChange={(e) => changeItem(item.key, "description", e.target.value)}
                  placeholder="اسم المادة أو الخدمة كما في الفاتورة"
                />
                <div className="item-fields">
                  {form.currency && (
                    <div className="field full-field budget-item-picker">
                      <label htmlFor={`budget-item-${item.key}`}>
                        بند ميزانية المشروع <span className="optional-mark">اختياري</span>
                      </label>
                      <select
                        id={`budget-item-${item.key}`}
                        className="form-field"
                        value={item.project_budget_line_id || ""}
                        disabled={budgetLoading || !budgetView?.budget?.lines.length}
                        onChange={(event) =>
                          changeItem(item.key, "project_budget_line_id", event.target.value)
                        }
                      >
                        <option value="">
                          {budgetLoading
                            ? "جارٍ تحميل البنود…"
                            : budgetView?.budget
                              ? "غير مصنف"
                              : "لا توجد ميزانية لهذه العملة"}
                        </option>
                        {budgetView?.budget?.lines.map((budgetLine) => (
                          <option key={budgetLine.id} value={budgetLine.id}>
                            {budgetLine.expense_category.code} — {budgetLine.description} — متبقي{" "}
                            {budgetLine.usage.remaining} {form.currency}
                          </option>
                        ))}
                      </select>
                      <p className="field-hint">
                        يضيف التصنيف فحص ارتباط الميزانية ويحدث المصروف عند إرسال المستند.
                      </p>
                    </div>
                  )}
                  {selectedOrder && (
                    <div className="field full-field po-item-picker">
                      <label htmlFor={`po-item-${item.key}`}>
                        بند أمر الشراء <span className="optional-mark">اختياري</span>
                      </label>
                      <select
                        id={`po-item-${item.key}`}
                        className="form-field"
                        value={item.purchase_order_item_id || ""}
                        onChange={(event) =>
                          changeItem(item.key, "purchase_order_item_id", event.target.value)
                        }
                      >
                        <option value="">غير مرتبط</option>
                        {selectedOrder.items.map((orderItem) => (
                          <option key={orderItem.id} value={orderItem.id}>
                            {orderItem.position}. {orderItem.description} — المطلوب{" "}
                            {orderItem.ordered_quantity} {orderItem.unit || ""}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  <div className="field">
                    <label htmlFor={`unit-${item.key}`}>
                      الوحدة <span className="optional-mark">اختياري</span>
                    </label>
                    <Input
                      id={`unit-${item.key}`}
                      maxLength={40}
                      value={item.unit || ""}
                      onChange={(e) => changeItem(item.key, "unit", e.target.value)}
                      placeholder="قطعة، متر…"
                    />
                  </div>
                  {(
                    [
                      ["quantity", "الكمية", "0.0001"],
                      ["unit_price", "سعر الوحدة", "0"],
                      ["discount_amount", "خصم البند", "0"],
                      ["tax_rate", "نسبة الضريبة %", "0"],
                    ] as const
                  ).map(([name, label]) => (
                    <div className="field" key={name}>
                      <label htmlFor={`${name}-${item.key}`}>{label}</label>
                      <Input
                        id={`${name}-${item.key}`}
                        type="text"
                        inputMode="decimal"
                        dir="ltr"
                        required
                        pattern={
                          name === "discount_amount"
                            ? "[0-9]+(\\.[0-9]{1,2})?"
                            : "[0-9]+(\\.[0-9]{1,4})?"
                        }
                        maxLength={24}
                        value={item[name]}
                        onChange={(e) => changeItem(item.key, name, decimalInput(e.target.value))}
                      />
                    </div>
                  ))}
                </div>
              </fieldset>
            ))}
            <Button
              type="button"
              variant="outline"
              disabled={busy || form.items.length >= 100}
              onClick={() =>
                field("items", [
                  ...form.items,
                  {
                    key: crypto.randomUUID(),
                    description: "",
                    unit: "",
                    quantity: "1",
                    unit_price: "",
                    discount_amount: "0",
                    tax_rate: "",
                    purchase_order_item_id: null,
                    project_budget_line_id: null,
                  },
                ])
              }
            >
              <Plus size={17} />
              إضافة بند
            </Button>
            <p className="field-hint">
              حتى 100 بند. الكمية والسعر والنسبة حتى 4 منازل عشرية؛ الخصم حتى منزلتين. أدخل نسبة
              الضريبة صراحة، بما فيها صفر عند انطباقه.
            </p>
          </section>
          <section className="surface editor-section">
            <div className="section-label">
              <span>03</span>
              <div>
                <h2>الإجماليات الظاهرة على أصل الفاتورة</h2>
                <p>انقل القيم كما تظهر على الأصل؛ سيقارنها النظام بنتيجة حساب البنود بعد الحفظ.</p>
              </div>
            </div>
            <fieldset className="plain-fieldset" disabled={busy}>
              <div className="document-total-fields">
                {(
                  [
                    ["subtotal", "الصافي قبل الضريبة"],
                    ["tax_total", "إجمالي الضريبة"],
                    ["grand_total", "الإجمالي المستحق"],
                  ] as const
                ).map(([name, label]) => (
                  <div className="field" key={name}>
                    <label htmlFor={`document-${name}`}>
                      {label} <span className="optional-mark">اختياري</span>
                    </label>
                    <Input
                      id={`document-${name}`}
                      type="text"
                      inputMode="decimal"
                      dir="ltr"
                      pattern="[0-9]+(\.[0-9]{1,2})?"
                      maxLength={19}
                      value={form.document_totals[name]}
                      onChange={(event) => documentTotal(name, decimalInput(event.target.value))}
                    />
                  </div>
                ))}
              </div>
              <p className="field-hint">
                اترك القيمة فارغة إذا لم تظهر بوضوح على المستند. لا يستنتج النظام مبلغًا مفقودًا.
              </p>
            </fieldset>
          </section>
          {error && (
            <div className="error-box" role="alert">
              {error}
              {conflict && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setForm(null);
                    setInvoice(null);
                    setAttempt((n) => n + 1);
                  }}
                >
                  تحميل النسخة الأحدث وإلغاء تعديلاتي
                </Button>
              )}
            </div>
          )}
          {extractionJob && (
            <label className="extraction-confirm">
              <input
                type="checkbox"
                checked={extractionConfirmed}
                onChange={(event) => setExtractionConfirmed(event.target.checked)}
                disabled={busy}
              />
              راجعت الحقول والبنود المقترحة وصححتها وطابقتها مع الفاتورة الأصلية.
            </label>
          )}
          <div className="editor-actions">
            <div>
              <Button
                type="submit"
                disabled={busy || (extractionJob !== null && !extractionConfirmed)}
              >
                {busy ? <LoaderCircle size={17} className="animate-spin" /> : <Check size={17} />}
                حفظ بيانات الفاتورة
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={busy}
                onClick={() => router.push(`/invoices/${id}`)}
              >
                إلغاء التعديلات
              </Button>
            </div>
            <p>الحفظ لا يرسل الفاتورة للموافقة. التعديلات لا تُحفظ تلقائيًا.</p>
          </div>
        </div>
        <aside className="editor-aside">
          <section className="surface calculation-card">
            <h2>معاينة الإجماليات</h2>
            <p>تُحسب من البنود المدخلة قبل حفظها.</p>
            {signature && !totals && !previewError ? (
              <p role="status" className="financial-empty">
                جارٍ حساب الإجماليات…
              </p>
            ) : (
              <InvoiceTotals totals={totals} currency={form.currency || null} />
            )}
            {previewError && (
              <p className="error-box" role="alert">
                {previewError}
              </p>
            )}
            <p className="calculation-note">
              نحسب الضريبة بعد خصم البند، ونقرب المبالغ إلى منزلتين لكل بند. هذه معاينة حسابية وليست
              نتيجة تدقيق.
            </p>
          </section>
          <section className="surface editor-original">
            <h2>مرجعك: الملف الأصلي</h2>
            {invoice.attachment.media_type.startsWith("image/") ? (
              <img src={invoice.attachment.url} alt="أصل الفاتورة للمراجعة" />
            ) : (
              <div className="mini-original">
                <FileText size={35} />
                <strong>{invoice.attachment.name}</strong>
              </div>
            )}
            <Button asChild variant="outline">
              <a href={invoice.attachment.url} download>
                <Download size={16} />
                تحميل الأصل
              </a>
            </Button>
            <p>المشروع: {invoice.project.name}</p>
          </section>
        </aside>
      </form>
      {adding && (
        <SupplierDialog
          onClose={() => setAdding(false)}
          onCreated={(supplier) => {
            setSuppliers((current) => [...current, supplier]);
            field("supplier_id", supplier.id);
          }}
        />
      )}
    </div>
  );
}
