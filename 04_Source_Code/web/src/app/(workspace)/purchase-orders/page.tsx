"use client";

import { useEffect, useState, type FormEvent } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  FileCheck2,
  LoaderCircle,
  PackageCheck,
  Plus,
  Trash2,
} from "lucide-react";
import { amount } from "@/components/invoice-financial";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type Currency, type Project, type PurchaseOrder, type Supplier } from "@/lib/api";

type OrderLine = {
  key: string;
  description: string;
  unit: string;
  ordered_quantity: string;
  unit_price: string;
  tax_rate: string;
};

const currentDate = new Date();
const today = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, "0")}-${String(currentDate.getDate()).padStart(2, "0")}`;
const emptyLine = (): OrderLine => ({
  key: crypto.randomUUID(),
  description: "",
  unit: "",
  ordered_quantity: "1",
  unit_price: "",
  tax_rate: "15",
});

function normalizeDecimal(value: string) {
  return value
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/٫/g, ".");
}

export default function PurchaseOrdersPage() {
  const { user, csrf_token } = useSession();
  const [orders, setOrders] = useState<PurchaseOrder[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [receiptOrder, setReceiptOrder] = useState<string | null>(null);
  const [receiptFile, setReceiptFile] = useState<File | null>(null);
  const [orderForm, setOrderForm] = useState({
    project_id: "",
    supplier_id: "",
    number: "",
    order_date: today,
    currency: "SAR" as Currency,
    items: [emptyLine()],
  });
  const [receiptForm, setReceiptForm] = useState({
    number: "",
    received_date: today,
    note: "",
    quantities: {} as Record<string, string>,
  });

  useEffect(() => {
    let active = true;
    setError("");
    Promise.all([
      api<PurchaseOrder[]>("/purchase-orders"),
      api<Project[]>("/projects"),
      api<Supplier[]>("/suppliers"),
    ])
      .then(([orderData, projectData, supplierData]) => {
        if (!active) return;
        setOrders(orderData);
        setProjects(projectData);
        setSuppliers(supplierData);
      })
      .catch((failure) => {
        if (active) setError(failure.message);
      });
    return () => {
      active = false;
    };
  }, [attempt]);

  function updateLine(key: string, field: keyof OrderLine, value: string) {
    setOrderForm((current) => ({
      ...current,
      items: current.items.map((item) => (item.key === key ? { ...item, [field]: value } : item)),
    }));
  }

  async function createOrder(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await api<PurchaseOrder>("/purchase-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: JSON.stringify({
          ...orderForm,
          items: orderForm.items.map(({ key: _key, ...item }) => ({
            ...item,
            unit: item.unit.trim() || null,
          })),
        }),
      });
      setCreating(false);
      setOrderForm({
        project_id: "",
        supplier_id: "",
        number: "",
        order_date: today,
        currency: "SAR",
        items: [emptyLine()],
      });
      setSuccess("تم إنشاء أمر الشراء وتسجيله في السجل.");
      setAttempt((value) => value + 1);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function openReceipt(order: PurchaseOrder) {
    if (receiptOrder === order.id) {
      setReceiptOrder(null);
      return;
    }
    setReceiptOrder(order.id);
    setReceiptFile(null);
    setReceiptForm({
      number: "",
      received_date: today,
      note: "",
      quantities: Object.fromEntries(order.items.map((item) => [item.id, ""])),
    });
    setError("");
    setSuccess("");
  }

  async function addReceipt(event: FormEvent, order: PurchaseOrder) {
    event.preventDefault();
    if (busy || !receiptFile) {
      setError("اختر مستند إثبات الاستلام بصيغة PDF أو JPG أو PNG.");
      return;
    }
    const items = order.items
      .map((item) => ({
        purchase_order_item_id: item.id,
        received_quantity: receiptForm.quantities[item.id],
      }))
      .filter((item) => item.received_quantity && Number(item.received_quantity) > 0);
    if (!items.length) {
      setError("أدخل الكمية المستلمة لبند واحد على الأقل.");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const body = new FormData();
      body.append(
        "receipt_data",
        JSON.stringify({
          number: receiptForm.number,
          received_date: receiptForm.received_date,
          note: receiptForm.note.trim() || null,
          items,
        }),
      );
      body.append("file", receiptFile);
      await api<PurchaseOrder>(`/purchase-orders/${order.id}/receipts`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrf_token },
        body,
      });
      setReceiptOrder(null);
      setReceiptFile(null);
      setSuccess(`تم حفظ محضر الاستلام لأمر الشراء ${order.number}.`);
      setAttempt((value) => value + 1);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-container purchase-orders-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">الشراء والاستلام</span>
          <h1>أوامر الشراء</h1>
          <p>مرجع الكميات والأسعار وإثباتات الاستلام المستخدمة في تدقيق الفواتير.</p>
        </div>
        {user.role === "FINANCE_MANAGER" && (
          <Button onClick={() => setCreating((value) => !value)}>
            <Plus size={18} />
            {creating ? "إغلاق النموذج" : "أمر شراء جديد"}
          </Button>
        )}
      </div>

      {creating && (
        <form className="surface procurement-form" onSubmit={createOrder}>
          <div className="section-label">
            <span>01</span>
            <div>
              <h2>أمر شراء جديد</h2>
              <p>مدير المالية ينشئ المرجع الرسمي قبل ربطه بالفواتير.</p>
            </div>
          </div>
          <fieldset className="plain-fieldset" disabled={busy}>
            <div className="procurement-fields">
              <div className="field">
                <label htmlFor="po-number">رقم أمر الشراء</label>
                <Input
                  id="po-number"
                  required
                  maxLength={100}
                  value={orderForm.number}
                  onChange={(event) =>
                    setOrderForm((current) => ({ ...current, number: event.target.value }))
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="po-date">تاريخ أمر الشراء</label>
                <Input
                  id="po-date"
                  type="date"
                  dir="ltr"
                  required
                  value={orderForm.order_date}
                  onChange={(event) =>
                    setOrderForm((current) => ({ ...current, order_date: event.target.value }))
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="po-project">المشروع</label>
                <select
                  id="po-project"
                  className="form-field"
                  required
                  value={orderForm.project_id}
                  onChange={(event) =>
                    setOrderForm((current) => ({ ...current, project_id: event.target.value }))
                  }
                >
                  <option value="">اختر المشروع</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name} — {project.code}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="po-supplier">المورد</label>
                <select
                  id="po-supplier"
                  className="form-field"
                  required
                  value={orderForm.supplier_id}
                  onChange={(event) =>
                    setOrderForm((current) => ({ ...current, supplier_id: event.target.value }))
                  }
                >
                  <option value="">اختر المورد</option>
                  {suppliers.map((supplier) => (
                    <option key={supplier.id} value={supplier.id}>
                      {supplier.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="po-currency">العملة</label>
                <select
                  id="po-currency"
                  className="form-field"
                  value={orderForm.currency}
                  onChange={(event) =>
                    setOrderForm((current) => ({
                      ...current,
                      currency: event.target.value as Currency,
                    }))
                  }
                >
                  <option value="SAR">SAR — ريال سعودي</option>
                  <option value="AED">AED — درهم إماراتي</option>
                  <option value="USD">USD — دولار أمريكي</option>
                  <option value="EUR">EUR — يورو</option>
                </select>
              </div>
            </div>
            <div className="order-line-list">
              {orderForm.items.map((item, index) => (
                <fieldset className="order-line" key={item.key}>
                  <legend>البند {index + 1}</legend>
                  <div className="order-line-heading">
                    <div className="field">
                      <label htmlFor={`po-description-${item.key}`}>وصف البند</label>
                      <Input
                        id={`po-description-${item.key}`}
                        required
                        maxLength={500}
                        value={item.description}
                        onChange={(event) =>
                          updateLine(item.key, "description", event.target.value)
                        }
                      />
                    </div>
                    {orderForm.items.length > 1 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setOrderForm((current) => ({
                            ...current,
                            items: current.items.filter((line) => line.key !== item.key),
                          }))
                        }
                      >
                        <Trash2 size={15} /> حذف
                      </Button>
                    )}
                  </div>
                  <div className="order-line-fields">
                    <div className="field">
                      <label htmlFor={`po-unit-${item.key}`}>الوحدة</label>
                      <Input
                        id={`po-unit-${item.key}`}
                        maxLength={40}
                        value={item.unit}
                        onChange={(event) => updateLine(item.key, "unit", event.target.value)}
                      />
                    </div>
                    {(
                      [
                        ["ordered_quantity", "الكمية المطلوبة"],
                        ["unit_price", "سعر الوحدة"],
                        ["tax_rate", "نسبة الضريبة %"],
                      ] as const
                    ).map(([field, label]) => (
                      <div className="field" key={field}>
                        <label htmlFor={`${field}-${item.key}`}>{label}</label>
                        <Input
                          id={`${field}-${item.key}`}
                          required
                          inputMode="decimal"
                          dir="ltr"
                          pattern="[0-9]+(\.[0-9]{1,4})?"
                          value={item[field]}
                          onChange={(event) =>
                            updateLine(item.key, field, normalizeDecimal(event.target.value))
                          }
                        />
                      </div>
                    ))}
                  </div>
                </fieldset>
              ))}
            </div>
            <div className="procurement-form-actions">
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  setOrderForm((current) => ({
                    ...current,
                    items: [...current.items, emptyLine()],
                  }))
                }
                disabled={orderForm.items.length >= 100}
              >
                <Plus size={16} /> إضافة بند
              </Button>
              <Button type="submit">
                {busy ? <LoaderCircle className="animate-spin" size={17} /> : <Check size={17} />}
                حفظ أمر الشراء
              </Button>
            </div>
          </fieldset>
        </form>
      )}

      {success && <p className="success-box">{success}</p>}
      {error && (
        <div className="error-box procurement-error" role="alert">
          {error}
        </div>
      )}

      {!orders ? (
        <div className="inline-state">
          <LoaderCircle className="animate-spin" /> جارٍ تحميل أوامر الشراء…
        </div>
      ) : orders.length === 0 ? (
        <div className="surface inline-state">
          <PackageCheck size={32} />
          <h2>لا توجد أوامر شراء متاحة</h2>
          <p>
            {user.role === "FINANCE_MANAGER"
              ? "أنشئ أول أمر شراء للمشروع والمورد."
              : "ستظهر الأوامر المرتبطة بالمشاريع المكلف بها حسابك."}
          </p>
        </div>
      ) : (
        <div className="purchase-order-list">
          {orders.map((order) => (
            <article className="surface purchase-order-card" key={order.id}>
              <header className="purchase-order-heading">
                <div>
                  <span className="eyebrow">أمر شراء</span>
                  <h2>
                    <bdi>{order.number}</bdi>
                  </h2>
                  <p>
                    {order.project.name} · {order.supplier.name}
                  </p>
                </div>
                <div className="purchase-order-total">
                  <span>الإجمالي</span>
                  <strong>
                    <bdi>{amount(order.totals.grand_total, order.currency)}</bdi>
                  </strong>
                </div>
              </header>
              <div className="purchase-order-meta">
                <span>
                  التاريخ: <bdi>{order.order_date}</bdi>
                </span>
                <span>أنشأه: {order.created_by.name}</span>
                <span>محاضر الاستلام: {order.receipts.length}</span>
              </div>
              <div className="purchase-lines" aria-label={`بنود أمر الشراء ${order.number}`}>
                {order.items.map((item) => {
                  const received = Number(item.received_quantity);
                  const ordered = Number(item.ordered_quantity);
                  const state = received >= ordered ? "مكتمل" : received > 0 ? "جزئي" : "لم يُستلم";
                  return (
                    <div className="purchase-line" key={item.id}>
                      <div>
                        <strong>
                          {item.position}. {item.description}
                        </strong>
                        <span>
                          {amount(item.unit_price, order.currency)} · ضريبة {item.tax_rate}%
                        </span>
                      </div>
                      <div className="receipt-progress">
                        <span
                          className={`receipt-state state-${state === "مكتمل" ? "complete" : state === "جزئي" ? "partial" : "empty"}`}
                        >
                          {state}
                        </span>
                        <span className="received-copy">
                          المستلم <bdi>{item.received_quantity}</bdi> من{" "}
                          <bdi>{item.ordered_quantity}</bdi> {item.unit || ""}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
              {order.receipts.length > 0 && (
                <details className="receipt-history">
                  <summary>محاضر الاستلام المحفوظة ({order.receipts.length})</summary>
                  <div>
                    {order.receipts.map((receipt) => (
                      <article key={receipt.id}>
                        <div>
                          <strong>
                            <bdi>{receipt.number}</bdi>
                          </strong>
                          <span>
                            <bdi>{receipt.received_date}</bdi> · {receipt.created_by.name}
                          </span>
                          {receipt.note && <p>{receipt.note}</p>}
                        </div>
                        <Button asChild variant="outline" size="sm">
                          <a href={receipt.evidence.url} download>
                            <FileCheck2 size={15} /> إثبات الاستلام
                          </a>
                        </Button>
                      </article>
                    ))}
                  </div>
                </details>
              )}
              {user.role === "EMPLOYEE" && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => openReceipt(order)}
                  aria-expanded={receiptOrder === order.id}
                >
                  {receiptOrder === order.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  {receiptOrder === order.id ? "إغلاق محضر الاستلام" : "تسجيل استلام"}
                </Button>
              )}
              {user.role === "EMPLOYEE" && receiptOrder === order.id && (
                <form className="receipt-form" onSubmit={(event) => addReceipt(event, order)}>
                  <h3>محضر استلام جديد</h3>
                  <p>سجّل الكميات التي وصلت فعليًا وأرفق إثبات التسليم.</p>
                  <fieldset className="plain-fieldset" disabled={busy}>
                    <div className="receipt-fields">
                      <div className="field">
                        <label htmlFor={`receipt-number-${order.id}`}>رقم محضر الاستلام</label>
                        <Input
                          id={`receipt-number-${order.id}`}
                          required
                          maxLength={100}
                          value={receiptForm.number}
                          onChange={(event) =>
                            setReceiptForm((current) => ({
                              ...current,
                              number: event.target.value,
                            }))
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`receipt-date-${order.id}`}>تاريخ الاستلام</label>
                        <Input
                          id={`receipt-date-${order.id}`}
                          type="date"
                          dir="ltr"
                          required
                          value={receiptForm.received_date}
                          onChange={(event) =>
                            setReceiptForm((current) => ({
                              ...current,
                              received_date: event.target.value,
                            }))
                          }
                        />
                      </div>
                      <div className="field full-field">
                        <label htmlFor={`receipt-note-${order.id}`}>ملاحظة</label>
                        <Input
                          id={`receipt-note-${order.id}`}
                          maxLength={1000}
                          value={receiptForm.note}
                          onChange={(event) =>
                            setReceiptForm((current) => ({ ...current, note: event.target.value }))
                          }
                        />
                      </div>
                    </div>
                    <div className="receipt-quantities">
                      {order.items.map((item) => (
                        <div className="field" key={item.id}>
                          <label htmlFor={`received-${item.id}`}>
                            {item.position}. {item.description}
                          </label>
                          <Input
                            id={`received-${item.id}`}
                            aria-label={`الكمية المستلمة للبند ${item.position}`}
                            inputMode="decimal"
                            dir="ltr"
                            pattern="[0-9]+(\.[0-9]{1,4})?"
                            placeholder={`المطلوب ${item.ordered_quantity}`}
                            value={receiptForm.quantities[item.id] || ""}
                            onChange={(event) =>
                              setReceiptForm((current) => ({
                                ...current,
                                quantities: {
                                  ...current.quantities,
                                  [item.id]: normalizeDecimal(event.target.value),
                                },
                              }))
                            }
                          />
                        </div>
                      ))}
                    </div>
                    <div className="field receipt-file-field">
                      <label htmlFor={`receipt-file-${order.id}`}>إثبات الاستلام</label>
                      <Input
                        id={`receipt-file-${order.id}`}
                        type="file"
                        required
                        accept="application/pdf,image/jpeg,image/png"
                        onChange={(event) => setReceiptFile(event.target.files?.[0] || null)}
                      />
                      <p className="field-hint">PDF أو JPG أو PNG، بحد أقصى 10 ميجابايت.</p>
                    </div>
                    <Button type="submit">
                      {busy ? (
                        <LoaderCircle className="animate-spin" size={17} />
                      ) : (
                        <FileCheck2 size={17} />
                      )}
                      حفظ محضر الاستلام
                    </Button>
                  </fieldset>
                </form>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
