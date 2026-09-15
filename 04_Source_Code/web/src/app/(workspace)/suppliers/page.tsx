"use client";
import { useEffect, useState } from "react";
import { BadgeCheck, Building2, LoaderCircle, Plus, Search } from "lucide-react";
import { api, supplierRegions, type Supplier, type SupplierRegionCode } from "@/lib/api";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SupplierDialog } from "@/components/supplier-dialog";

export default function SuppliersPage() {
  const { user, csrf_token } = useSession();
  const [suppliers, setSuppliers] = useState<Supplier[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [reviewing, setReviewing] = useState<Supplier | null>(null);
  const [verificationStatus, setVerificationStatus] = useState<"PENDING" | "VERIFIED" | "REJECTED">(
    "PENDING",
  );
  const [verificationNote, setVerificationNote] = useState("");
  const [region, setRegion] = useState<"" | SupplierRegionCode>("");
  const [savingVerification, setSavingVerification] = useState(false);
  useEffect(() => {
    let active = true;
    setError("");
    api<Supplier[]>("/suppliers")
      .then((data) => {
        if (active) setSuppliers(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  const filtered = suppliers?.filter((supplier) =>
    `${supplier.name} ${supplier.tax_number || ""}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  const verificationLabels = {
    UNVERIFIED: "غير مراجع",
    PENDING: "قيد المراجعة",
    VERIFIED: "متحقق داخليًا",
    REJECTED: "مرفوض داخليًا",
  } as const;
  async function saveVerification(event: React.FormEvent) {
    event.preventDefault();
    if (!reviewing || savingVerification) return;
    setSavingVerification(true);
    setError("");
    try {
      await api(`/suppliers/${reviewing.id}/verification`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: JSON.stringify({
          status: verificationStatus,
          note: verificationNote.trim() || null,
          region_code: region || null,
        }),
      });
      setReviewing(null);
      setVerificationNote("");
      setAttempt((value) => value + 1);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSavingVerification(false);
    }
  }
  return (
    <div className="page-container">
      <div className="page-heading">
        <div>
          <span className="eyebrow">بيانات الشركة</span>
          <h1>الموردون</h1>
          <p>دليل مشترك لربط فواتيرك بالمورد الصحيح.</p>
        </div>
        {user.role !== "PROJECT_MANAGER" && (
          <Button onClick={() => setAdding(true)}>
            <Plus size={18} />
            إضافة مورد
          </Button>
        )}
      </div>
      <div className="surface supplier-list">
        <div className="supplier-search">
          <Search size={19} />
          <Input
            aria-label="البحث عن مورد"
            placeholder="ابحث بالاسم أو الرقم الضريبي…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {error ? (
          <div className="inline-state">
            <p role="alert">{error}</p>
            <Button variant="outline" onClick={() => setAttempt((n) => n + 1)}>
              إعادة المحاولة
            </Button>
          </div>
        ) : !suppliers ? (
          <div role="status" className="inline-state">
            <LoaderCircle className="animate-spin" />
            جارٍ تحميل الموردين…
          </div>
        ) : !filtered?.length ? (
          <div className="inline-state">
            <Building2 size={28} />
            <h2>{query ? "لا توجد نتائج مطابقة" : "أضف المورد الأول"}</h2>
            <p>تظهر هنا بيانات الموردين التي تُضاف داخل شركتك.</p>
          </div>
        ) : (
          filtered.map((supplier) => (
            <article className="supplier-row" key={supplier.id}>
              <span className="file-icon">
                <Building2 size={22} />
              </span>
              <div>
                <h2>{supplier.name}</h2>
                <p>
                  الرقم الضريبي: <bdi>{supplier.tax_number || "غير مدخل"}</bdi>
                </p>
                <p>المنطقة: {supplier.region_name || "غير محددة"}</p>
                {supplier.verification_note && <p>{supplier.verification_note}</p>}
              </div>
              <div className="supplier-verification-actions">
                <span
                  className={`draft-badge verification-${supplier.verification_status.toLowerCase()}`}
                >
                  {verificationLabels[supplier.verification_status]}
                </span>
                {user.role === "FINANCE_MANAGER" && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setReviewing(supplier);
                      setVerificationStatus(
                        supplier.verification_status === "UNVERIFIED"
                          ? "PENDING"
                          : supplier.verification_status,
                      );
                      setVerificationNote(supplier.verification_note || "");
                      setRegion(supplier.region_code || "");
                    }}
                  >
                    <BadgeCheck size={15} />
                    مراجعة
                  </Button>
                )}
              </div>
            </article>
          ))
        )}
        {reviewing && (
          <form className="supplier-verification-form" onSubmit={saveVerification}>
            <div>
              <h2>التحقق الداخلي من {reviewing.name}</h2>
              <p>هذه مراجعة داخل الشركة ولا تمثل تحققًا حكوميًا أو اتصالًا خارجيًا.</p>
            </div>
            <label className="field">
              منطقة المورد
              <select
                className="form-field"
                value={region}
                onChange={(event) => setRegion(event.target.value as "" | SupplierRegionCode)}
              >
                <option value="">غير محددة</option>
                {supplierRegions.map(([code, label]) => (
                  <option value={code} key={code}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              الحالة
              <select
                className="form-field"
                value={verificationStatus}
                onChange={(event) =>
                  setVerificationStatus(event.target.value as typeof verificationStatus)
                }
              >
                <option value="PENDING">قيد المراجعة</option>
                <option value="VERIFIED">متحقق داخليًا</option>
                <option value="REJECTED">مرفوض داخليًا</option>
              </select>
            </label>
            <label className="field">
              دليل المراجعة أو سبب القرار
              <textarea
                className="form-field"
                rows={3}
                maxLength={1000}
                required={verificationStatus !== "PENDING"}
                value={verificationNote}
                onChange={(event) => setVerificationNote(event.target.value)}
              />
            </label>
            <div className="workflow-actions">
              <Button disabled={savingVerification}>
                {savingVerification && <LoaderCircle size={15} className="animate-spin" />}
                حفظ المراجعة
              </Button>
              <Button type="button" variant="outline" onClick={() => setReviewing(null)}>
                إلغاء
              </Button>
            </div>
          </form>
        )}
      </div>
      {adding && (
        <SupplierDialog
          onClose={() => setAdding(false)}
          onCreated={() => setAttempt((n) => n + 1)}
        />
      )}
    </div>
  );
}
