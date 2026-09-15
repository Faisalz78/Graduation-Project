"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BadgeDollarSign, LoaderCircle, Save } from "lucide-react";
import { useSession } from "@/components/session-provider";
import { api, roles, type ApprovalLimitRow, type Currency } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const currencies: Currency[] = ["SAR", "AED", "USD", "EUR"];

export default function ApprovalLimitsPage() {
  const { user, csrf_token } = useSession();
  const [rows, setRows] = useState<ApprovalLimitRow[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (user.role !== "FINANCE_MANAGER") return;
    api<ApprovalLimitRow[]>("/governance/approval-limits")
      .then((data) => {
        setRows(data);
        setDrafts(
          Object.fromEntries(
            data.flatMap((row) =>
              currencies.map((currency) => [
                `${row.user.id}:${currency}`,
                row.limits[currency] || "",
              ]),
            ),
          ),
        );
      })
      .catch((failure) => setError(failure.message));
  }, [user.role]);

  async function save(userId: string, currency: Currency) {
    const key = `${userId}:${currency}`;
    if (!/^\d{1,16}(\.\d{1,2})?$/.test(drafts[key] || "")) {
      setError("أدخل حدًا موجبًا أو صفرًا حتى منزلتين عشريتين.");
      return;
    }
    setSaving(key);
    setError("");
    setMessage("");
    try {
      const data = await api<ApprovalLimitRow[]>(
        `/governance/approval-limits/${userId}/${currency}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
          body: JSON.stringify({ amount: drafts[key] }),
        },
      );
      setRows(data);
      setMessage(`حُفظ حد ${currency} وسُجل التغيير في سجل التدقيق.`);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving("");
    }
  }

  if (user.role !== "FINANCE_MANAGER")
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <h1>حدود الموافقات متاحة لمدير المالية</h1>
          <Link href="/invoices">العودة إلى الفواتير</Link>
        </div>
      </div>
    );

  return (
    <div className="page-container approval-limits-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">الحوكمة المالية</span>
          <h1>حدود الموافقات</h1>
          <p>يستطيع كل مراجع اعتماد المستند عندما يكون إجماليه ضمن حده المسجل للعملة نفسها.</p>
        </div>
        <span className="feature-icon">
          <BadgeDollarSign size={25} />
        </span>
      </div>
      <div className="surface governance-note">
        لا يوجد تحويل عملات تلقائي. ولمنع رفع المستخدم حدّه بنفسه، يعدّل مدير مالية آخر حد مدير
        المالية الحالي.
      </div>
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className="success-box" role="status">
          {message}
        </div>
      )}
      {!rows ? (
        <div className="surface inline-state">
          <LoaderCircle className="animate-spin" /> جارٍ تحميل الحدود…
        </div>
      ) : (
        <div className="approval-limit-list">
          {rows.map((row) => (
            <section className="surface approval-limit-card" key={row.user.id}>
              <div className="approval-limit-person">
                <div>
                  <h2>{row.user.name}</h2>
                  <p>
                    <bdi>{row.user.email}</bdi> · {roles[row.user.role]}
                  </p>
                </div>
                {row.user.id === user.id && <span className="draft-badge">حسابك</span>}
              </div>
              <div className="approval-limit-grid">
                {currencies.map((currency) => {
                  const key = `${row.user.id}:${currency}`;
                  const disabled = row.user.id === user.id;
                  return (
                    <div className="field" key={currency}>
                      <label htmlFor={key}>الحد بعملة {currency}</label>
                      <div className="approval-limit-input">
                        <Input
                          id={key}
                          dir="ltr"
                          inputMode="decimal"
                          disabled={disabled || saving === key}
                          value={drafts[key] || ""}
                          placeholder="غير مسجل"
                          onChange={(event) =>
                            setDrafts((current) => ({ ...current, [key]: event.target.value }))
                          }
                        />
                        {!disabled && (
                          <Button
                            size="icon"
                            variant="outline"
                            disabled={saving === key}
                            onClick={() => save(row.user.id, currency)}
                            aria-label={`حفظ حد ${currency} للمستخدم ${row.user.name}`}
                          >
                            {saving === key ? <LoaderCircle className="animate-spin" /> : <Save />}
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
