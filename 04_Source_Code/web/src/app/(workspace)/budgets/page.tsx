"use client";

import { useEffect, useState } from "react";
import { Archive, CircleDollarSign, LoaderCircle, Plus, Save, Tags, Trash2 } from "lucide-react";
import { amount } from "@/components/invoice-financial";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  api,
  ApiError,
  type Currency,
  type ExpenseCategory,
  type Project,
  type ProjectBudgetLine,
  type ProjectBudgetView,
} from "@/lib/api";

const currencies: Currency[] = ["SAR", "AED", "USD", "EUR"];

type DraftLine = {
  key: string;
  id: string | null;
  expense_category_id: string;
  description: string;
  unit: string;
  planned_quantity: string;
  planned_unit_price: string;
  allocated_amount: string;
};

function toDraft(line: ProjectBudgetLine): DraftLine {
  return {
    key: line.id,
    id: line.id,
    expense_category_id: line.expense_category.id,
    description: line.description,
    unit: line.unit || "",
    planned_quantity: line.planned_quantity || "",
    planned_unit_price: line.planned_unit_price || "",
    allocated_amount: line.allocated_amount,
  };
}

function decimalInput(value: string) {
  return value
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/٫/g, ".");
}

export default function BudgetsPage() {
  const { user, csrf_token } = useSession();
  const canEdit = user.role === "FINANCE_MANAGER";
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [projectId, setProjectId] = useState("");
  const [currency, setCurrency] = useState<Currency>("SAR");
  const [view, setView] = useState<ProjectBudgetView | null>(null);
  const [total, setTotal] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [categoryCode, setCategoryCode] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([api<Project[]>("/projects"), api<ExpenseCategory[]>("/expense-categories")])
      .then(([projectRows, categoryRows]) => {
        if (!active) return;
        setProjects(projectRows);
        setCategories(categoryRows);
        setProjectId((current) => current || projectRows[0]?.id || "");
        setError("");
      })
      .catch((failure) => active && setError(failure.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [attempt]);

  useEffect(() => {
    if (!projectId) {
      setView(null);
      return;
    }
    let active = true;
    setLoading(true);
    setMessage("");
    api<ProjectBudgetView>(`/projects/${projectId}/budgets/${currency}`)
      .then((data) => {
        if (!active) return;
        setView(data);
        setTotal(data.budget?.total_amount || "");
        setLines((data.budget?.lines || []).map(toDraft));
        setError("");
      })
      .catch((failure) => active && setError(failure.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [projectId, currency, attempt]);

  function changeLine(key: string, name: keyof DraftLine, raw: string) {
    setMessage("");
    setLines((current) =>
      current.map((line) => {
        if (line.key !== key) return line;
        const value = ["planned_quantity", "planned_unit_price", "allocated_amount"].includes(name)
          ? decimalInput(raw)
          : raw;
        const next = { ...line, [name]: value };
        if (name === "planned_quantity" || name === "planned_unit_price") {
          const quantity = Number(next.planned_quantity);
          const price = Number(next.planned_unit_price);
          if (next.planned_quantity && next.planned_unit_price && quantity > 0 && price >= 0) {
            next.allocated_amount = (quantity * price).toFixed(2);
          }
        }
        return next;
      }),
    );
  }

  function addLine() {
    if (!categories.length) {
      setError("أنشئ فئة مصروف واحدة على الأقل قبل إضافة بنود الميزانية.");
      return;
    }
    setLines((current) => [
      ...current,
      {
        key: crypto.randomUUID(),
        id: null,
        expense_category_id: categories[0].id,
        description: "",
        unit: "",
        planned_quantity: "",
        planned_unit_price: "",
        allocated_amount: "",
      },
    ]);
  }

  async function addCategory() {
    if (!categoryCode.trim() || !categoryName.trim()) {
      setError("أدخل رمز الفئة واسمها.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const category = await api<ExpenseCategory>("/expense-categories", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: JSON.stringify({ code: categoryCode.trim(), name: categoryName.trim() }),
      });
      setCategories((current) =>
        [...current, category].sort((a, b) => a.code.localeCompare(b.code)),
      );
      setCategoryCode("");
      setCategoryName("");
      setMessage("أُضيفت فئة المصروف وسُجلت في سجل التدقيق.");
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function saveBudget() {
    if (!projectId || !/^\d{1,16}(\.\d{1,2})?$/.test(total)) {
      setError("اختر المشروع وأدخل إجمالي الميزانية حتى منزلتين.");
      return;
    }
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const data = await api<ProjectBudgetView>(`/projects/${projectId}/budgets/${currency}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: JSON.stringify({
          currency,
          revision: view?.budget?.revision || 0,
          total_amount: total,
          lines: lines.map((line) => ({
            id: line.id,
            expense_category_id: line.expense_category_id,
            description: line.description.trim(),
            unit: line.unit.trim() || null,
            planned_quantity: line.planned_quantity || null,
            planned_unit_price: line.planned_unit_price || null,
            allocated_amount: line.allocated_amount,
          })),
        }),
      });
      setView(data);
      setTotal(data.budget?.total_amount || "");
      setLines((data.budget?.lines || []).map(toDraft));
      setMessage("حُفظت الميزانية وحُدثت أرقام الاستخدام وسجل التدقيق.");
    } catch (failure) {
      setError((failure as Error).message);
      if (failure instanceof ApiError && failure.status === 409) setAttempt((value) => value + 1);
    } finally {
      setSaving(false);
    }
  }

  if (user.role === "EMPLOYEE") {
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <h1>ميزانيات المشاريع متاحة للمراجعين</h1>
          <p>يظهر للموظف بند الميزانية المناسب أثناء تحرير فاتورته.</p>
        </div>
      </div>
    );
  }

  const budget = view?.budget;
  return (
    <div className="page-container budgets-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">الرقابة على مصاريف المشاريع</span>
          <h1>ميزانية المشروع وبنودها</h1>
          <p>تصنيف المصروف ومتابعة المعتمد والملتزم وقيد المراجعة لكل عملة دون خلط.</p>
        </div>
        <span className="feature-icon">
          <CircleDollarSign size={26} />
        </span>
      </div>

      <section className="surface budget-filters">
        <div className="field">
          <label htmlFor="budget-project">المشروع</label>
          <select
            id="budget-project"
            className="form-field"
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
          >
            {(projects || []).map((project) => (
              <option key={project.id} value={project.id}>
                {project.name} — {project.code}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="budget-currency">العملة</label>
          <select
            id="budget-currency"
            className="form-field"
            value={currency}
            onChange={(event) => setCurrency(event.target.value as Currency)}
          >
            {currencies.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </div>
      </section>

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

      {loading ? (
        <div className="surface inline-state">
          <LoaderCircle className="animate-spin" /> جارٍ تحميل الميزانية…
        </div>
      ) : !projects?.length ? (
        <div className="surface inline-state">لا توجد مشاريع نشطة متاحة لهذا الحساب.</div>
      ) : (
        <>
          {budget && (
            <section className="budget-metrics">
              {(
                [
                  ["إجمالي الميزانية", budget.total_amount],
                  ["المعتمد", budget.usage.approved],
                  ["الملتزم", budget.usage.committed],
                  ["قيد المراجعة", budget.usage.pending],
                  ["المتبقي", budget.usage.remaining],
                ] as const
              ).map(([label, value]) => (
                <article className="surface" key={label}>
                  <small>{label}</small>
                  <strong>{amount(value, currency)}</strong>
                </article>
              ))}
            </section>
          )}

          {canEdit && (
            <section className="surface category-creator">
              <div>
                <Tags size={20} />
                <div>
                  <h2>فئات المصروفات</h2>
                  <p>رموز موحدة للشركة تستخدمها بنود ميزانيات المشاريع.</p>
                </div>
              </div>
              <div className="category-fields">
                <Input
                  dir="ltr"
                  value={categoryCode}
                  maxLength={40}
                  placeholder="MAT"
                  aria-label="رمز فئة المصروف"
                  onChange={(event) => setCategoryCode(event.target.value)}
                />
                <Input
                  value={categoryName}
                  maxLength={160}
                  placeholder="مواد المشروع"
                  aria-label="اسم فئة المصروف"
                  onChange={(event) => setCategoryName(event.target.value)}
                />
                <Button variant="outline" disabled={saving} onClick={addCategory}>
                  <Plus size={17} /> إضافة فئة
                </Button>
              </div>
              <div className="category-chips">
                {categories.map((category) => (
                  <span key={category.id}>
                    <bdi>{category.code}</bdi> · {category.name}
                  </span>
                ))}
              </div>
            </section>
          )}

          <section className="surface budget-editor">
            <div className="budget-editor-heading">
              <div>
                <h2>جدول بنود الميزانية</h2>
                <p>
                  {canEdit
                    ? "أدخل مخصصًا مباشرًا، أو كمية وسعر وحدة ليحسب النظام المخصص."
                    : "عرض حي لبنود الميزانية واستخدامها حسب حالة المستندات."}
                </p>
              </div>
              {canEdit && (
                <div className="field budget-total-field">
                  <label htmlFor="budget-total">إجمالي الميزانية ({currency})</label>
                  <Input
                    id="budget-total"
                    dir="ltr"
                    inputMode="decimal"
                    value={total}
                    disabled={saving}
                    onChange={(event) => setTotal(decimalInput(event.target.value))}
                  />
                </div>
              )}
            </div>

            {!lines.length && (
              <div className="financial-empty">
                {budget ? "لا توجد بنود نشطة في هذه الميزانية." : "لم تُنشأ ميزانية لهذه العملة."}
              </div>
            )}
            <div className="budget-lines">
              {lines.map((line, index) => {
                const saved = budget?.lines.find((row) => row.id === line.id);
                return (
                  <fieldset key={line.key} className="budget-line" disabled={!canEdit || saving}>
                    <legend>البند {index + 1}</legend>
                    <div className="budget-line-grid">
                      <div className="field">
                        <label htmlFor={`category-${line.key}`}>فئة المصروف</label>
                        <select
                          id={`category-${line.key}`}
                          className="form-field"
                          value={line.expense_category_id}
                          onChange={(event) =>
                            changeLine(line.key, "expense_category_id", event.target.value)
                          }
                        >
                          {categories.map((category) => (
                            <option key={category.id} value={category.id}>
                              {category.code} — {category.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="field budget-description">
                        <label htmlFor={`description-${line.key}`}>وصف بند الميزانية</label>
                        <Input
                          id={`description-${line.key}`}
                          required
                          maxLength={500}
                          value={line.description}
                          onChange={(event) =>
                            changeLine(line.key, "description", event.target.value)
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`unit-${line.key}`}>الوحدة</label>
                        <Input
                          id={`unit-${line.key}`}
                          maxLength={40}
                          value={line.unit}
                          onChange={(event) => changeLine(line.key, "unit", event.target.value)}
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`quantity-${line.key}`}>الكمية المخططة</label>
                        <Input
                          id={`quantity-${line.key}`}
                          dir="ltr"
                          inputMode="decimal"
                          value={line.planned_quantity}
                          onChange={(event) =>
                            changeLine(line.key, "planned_quantity", event.target.value)
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`price-${line.key}`}>سعر الوحدة</label>
                        <Input
                          id={`price-${line.key}`}
                          dir="ltr"
                          inputMode="decimal"
                          value={line.planned_unit_price}
                          onChange={(event) =>
                            changeLine(line.key, "planned_unit_price", event.target.value)
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`allocation-${line.key}`}>المخصص</label>
                        <Input
                          id={`allocation-${line.key}`}
                          dir="ltr"
                          inputMode="decimal"
                          required
                          value={line.allocated_amount}
                          readOnly={Boolean(line.planned_quantity && line.planned_unit_price)}
                          onChange={(event) =>
                            changeLine(line.key, "allocated_amount", event.target.value)
                          }
                        />
                      </div>
                    </div>
                    {saved && (
                      <div className="budget-line-usage">
                        <span>معتمد {amount(saved.usage.approved, currency)}</span>
                        <span>ملتزم {amount(saved.usage.committed, currency)}</span>
                        <span>قيد المراجعة {amount(saved.usage.pending, currency)}</span>
                        <strong>متبقي {amount(saved.usage.remaining, currency)}</strong>
                      </div>
                    )}
                    {canEdit && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setLines((current) => current.filter((row) => row.key !== line.key))
                        }
                      >
                        <Trash2 size={15} /> أرشفة البند عند الحفظ
                      </Button>
                    )}
                  </fieldset>
                );
              })}
            </div>
            {canEdit && (
              <div className="budget-actions">
                <Button
                  variant="outline"
                  disabled={saving || lines.length >= 100}
                  onClick={addLine}
                >
                  <Plus size={17} /> إضافة بند
                </Button>
                <Button disabled={saving} onClick={saveBudget}>
                  {saving ? <LoaderCircle className="animate-spin" /> : <Save size={17} />}
                  حفظ الميزانية
                </Button>
              </div>
            )}
          </section>

          {budget?.archived_lines.length ? (
            <details className="surface archived-budget-lines">
              <summary>
                <Archive size={17} /> البنود المؤرشفة ({budget.archived_lines.length})
              </summary>
              {budget.archived_lines.map((line) => (
                <p key={line.id}>
                  {line.expense_category.code} · {line.description} ·{" "}
                  {amount(line.allocated_amount, currency)}
                </p>
              ))}
            </details>
          ) : null}

          {view && (
            <section className="surface budget-definitions">
              <strong>تعريف الأرقام:</strong> {view.definitions.approved}{" "}
              {view.definitions.committed} {view.definitions.pending} {view.definitions.excluded}{" "}
              {view.definitions.currency}
            </section>
          )}
        </>
      )}
    </div>
  );
}
