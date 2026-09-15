"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { LoaderCircle, X } from "lucide-react";
import { api, supplierRegions, type Supplier, type SupplierRegionCode } from "@/lib/api";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function SupplierDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (supplier: Supplier) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { csrf_token } = useSession();
  const [name, setName] = useState("");
  const [tax, setTax] = useState("");
  const [region, setRegion] = useState<"" | SupplierRegionCode>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const supplier = await api<Supplier>("/suppliers", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: JSON.stringify({
          name: name.trim(),
          tax_number: tax.trim() || null,
          region_code: region || null,
        }),
      });
      onCreated(supplier);
      onClose();
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="supplier-dialog"
      aria-labelledby="supplier-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
    >
      <div className="dialog-heading">
        <div>
          <span className="eyebrow">دليل الموردين</span>
          <h2 id="supplier-dialog-title">إضافة مورد</h2>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} disabled={busy} aria-label="إغلاق">
          <X size={19} />
        </Button>
      </div>
      <p className="dialog-intro">
        أدخل بيانات المورد كما تظهر في الفاتورة. سيكون متاحًا داخل شركتك.
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy} className="plain-fieldset">
          <div className="field">
            <label htmlFor="supplier-name">اسم المورد</label>
            <Input
              id="supplier-name"
              required
              minLength={2}
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="field">
            <label htmlFor="supplier-region">
              منطقة المورد <span className="optional-mark">اختياري</span>
            </label>
            <select
              id="supplier-region"
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
          </div>
          <div className="field">
            <label htmlFor="supplier-tax">
              الرقم الضريبي <span className="optional-mark">اختياري</span>
            </label>
            <Input
              id="supplier-tax"
              dir="ltr"
              maxLength={40}
              value={tax}
              onChange={(e) => setTax(e.target.value)}
            />
          </div>
          <p className="field-hint">
            إضافة المورد تحفظ بياناته فقط، ولا تعني التحقق من تسجيله الضريبي.
          </p>
          {error && (
            <p role="alert" className="error-box">
              {error}
            </p>
          )}
          <div className="form-actions">
            <Button type="submit">
              {busy && <LoaderCircle size={16} className="animate-spin" />}حفظ المورد
            </Button>
            <Button type="button" variant="ghost" onClick={onClose}>
              إلغاء
            </Button>
          </div>
        </fieldset>
      </form>
    </dialog>
  );
}
