"use client";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Check,
  FileText,
  LoaderCircle,
  LockKeyhole,
  UploadCloud,
  X,
} from "lucide-react";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { api, type Invoice, type Project } from "@/lib/api";
import { fileSize } from "@/lib/utils";

export default function NewInvoicePage() {
  const { user, csrf_token } = useSession();
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestKey = useRef("");
  useEffect(() => {
    let active = true;
    api<Project[]>("/projects")
      .then((data) => {
        if (active) {
          setProjects(data);
          setLoadingProjects(false);
        }
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          setLoadingProjects(false);
        }
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  function chooseFile(next: File | undefined) {
    if (busy || !next) return;
    setError("");
    requestKey.current = "";
    if (!/\.(pdf|png|jpe?g|xml)$/i.test(next.name)) {
      setFile(null);
      setError("اختر ملف PDF أو صورة JPEG أو PNG أو ملف UBL XML.");
      return;
    }
    const limit = /\.xml$/i.test(next.name) ? 2 : 10;
    if (next.size > limit * 1024 * 1024) {
      setFile(null);
      setError(`حجم الملف يتجاوز ${limit} ميغابايت.`);
      return;
    }
    if (next.size === 0) {
      setFile(null);
      setError("الملف فارغ. اختر ملفًا صالحًا.");
      return;
    }
    setFile(next);
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!file || !projectId) {
      setError("اختر ملف الفاتورة والمشروع قبل الحفظ.");
      return;
    }
    setBusy(true);
    requestKey.current ||= crypto.randomUUID();
    const data = new FormData();
    data.append("file", file);
    data.append("project_id", projectId);
    if (note.trim()) data.append("note", note.trim());
    try {
      const invoice = await api<Invoice>("/invoices", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf_token, "Idempotency-Key": requestKey.current },
        body: data,
      });
      router.push(`/invoices/${invoice.id}?saved=1`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  if (user.role !== "EMPLOYEE")
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <LockKeyhole size={28} />
          <h1>رفع الفواتير متاح للموظف</h1>
          <Button asChild variant="outline">
            <Link href="/invoices">العودة للفواتير</Link>
          </Button>
        </div>
      </div>
    );
  return (
    <div className="page-container">
      <Link className="back-link" href="/invoices">
        <ArrowRight size={17} />
        العودة إلى الفواتير
      </Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">إضافة مستند جديد</span>
          <h1>رفع فاتورة</h1>
          <p>أضف الملف الأصلي وحدد المشروع لحفظ فاتورتك كمسودة.</p>
        </div>
        <span className="step-label">
          الملف والمشروع <span>01</span>
        </span>
      </div>
      <div className="upload-layout">
        <form className="surface upload-form" onSubmit={submit}>
          <div className="section-label">
            <span>01</span>
            <div>
              <h2>ملف الفاتورة</h2>
              <p>اختر نسخة واضحة من المستند الأصلي.</p>
            </div>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.xml,application/xml,text/xml"
            aria-label="ملف الفاتورة"
            className="sr-only"
            tabIndex={-1}
            disabled={busy}
            onChange={(e) => chooseFile(e.target.files?.[0])}
          />
          <div
            className={`dropzone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              chooseFile(e.dataTransfer.files[0]);
            }}
          >
            {file ? (
              <>
                <div className="selected-file-icon">
                  <FileText size={30} />
                </div>
                <strong className="selected-filename">{file.name}</strong>
                <p>
                  {fileSize(file.size)} <span>· جاهز للرفع</span>
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={() => {
                    setFile(null);
                    requestKey.current = "";
                    if (inputRef.current) inputRef.current.value = "";
                  }}
                >
                  <X size={15} />
                  إزالة الملف
                </Button>
              </>
            ) : (
              <>
                <div className="upload-icon">
                  <UploadCloud size={29} strokeWidth={1.5} />
                </div>
                <h3>اسحب الفاتورة إلى هنا</h3>
                <p>أو اختر الملف من جهازك</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => inputRef.current?.click()}
                >
                  اختيار ملف
                </Button>
                <small>PDF، JPEG، PNG حتى 10 ميغابايت · UBL XML حتى 2 ميغابايت</small>
              </>
            )}
          </div>
          <div className="section-label second-section">
            <span>02</span>
            <div>
              <h2>ربط الفاتورة بالمشروع</h2>
              <p>يساعد اختيار المشروع على تنظيم مصروفاته.</p>
            </div>
          </div>
          <div className="field">
            <label htmlFor="project">
              المشروع <span className="required-mark">*</span>
            </label>
            <select
              id="project"
              className="form-field"
              required
              disabled={busy || loadingProjects}
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
                requestKey.current = "";
              }}
            >
              <option value="">{loadingProjects ? "جارٍ تحميل المشاريع…" : "اختر المشروع"}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {p.code}
                </option>
              ))}
            </select>
            {!loadingProjects && !projects.length && (
              <div className="field-hint">
                لا توجد مشاريع متاحة.{" "}
                <button
                  type="button"
                  className="text-action"
                  onClick={() => {
                    setLoadingProjects(true);
                    setAttempt((n) => n + 1);
                  }}
                >
                  تحديث القائمة
                </button>
              </div>
            )}
          </div>
          <div className="field">
            <label htmlFor="note">
              ملاحظة <span className="optional-mark">اختياري</span>
            </label>
            <textarea
              id="note"
              className="form-field"
              rows={3}
              maxLength={1000}
              disabled={busy}
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                requestKey.current = "";
              }}
              placeholder="أضف وصفًا مختصرًا يساعدك على تذكر الفاتورة…"
            />
            <span className="char-count">{note.length.toLocaleString("ar-SA")} / ١٬٠٠٠</span>
          </div>
          {error && (
            <div className="error-box" role="alert">
              {error}
            </div>
          )}
          <div className="form-actions">
            <Button type="submit" disabled={busy || !file || !projectId}>
              {busy ? (
                <>
                  <LoaderCircle size={17} className="animate-spin" />
                  جارٍ حفظ المسودة…
                </>
              ) : (
                <>
                  <Check size={17} />
                  حفظ المسودة
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => router.push("/invoices")}
            >
              إلغاء
            </Button>
          </div>
        </form>
        <aside className="upload-aside">
          <div className="aside-symbol">
            <LockKeyhole size={24} />
          </div>
          <h2>
            ملفك الأصلي،
            <br />
            محفوظ مع الفاتورة.
          </h2>
          <p>نحفظ المستند كما رفعته، مع المشروع وصاحب الرفع وتاريخه.</p>
          <ol className="upload-checklist">
            <li>
              <Check size={16} />
              ارفع فاتورة واضحة وكاملة
            </li>
            <li>
              <Check size={16} />
              تأكد من اختيار المشروع الصحيح
            </li>
            <li>
              <Check size={16} />
              راجع المسودة بعد حفظها
            </li>
          </ol>
          <div className="aside-footnote">الحفظ ينشئ مسودة خاصة بك. لم تُرسل للمراجعة بعد.</div>
        </aside>
      </div>
    </div>
  );
}
