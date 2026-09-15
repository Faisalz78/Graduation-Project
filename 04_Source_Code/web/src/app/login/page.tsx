"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Check,
  Eye,
  EyeOff,
  FileText,
  LoaderCircle,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WasilBrand } from "@/components/wasil-brand";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function login(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      router.replace("/invoices");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <section className="login-form-panel">
        <div className="brand login-brand">
          <WasilBrand compact />
          <span>
            <strong className="brand-product-name">منصة واصل</strong>
            <small>دقة · رؤية · استمرارية</small>
          </span>
        </div>
        <div className="login-form-wrap">
          <span className="eyebrow">مساحة العمل المالية الذكية</span>
          <h1>
            صِل فواتيرك
            <br />
            بقرارات أوضح.
          </h1>
          <p className="lead">سجّل دخولك لتدقيق الفواتير ومتابعة مصاريف المشاريع من مساحة واحدة.</p>
          <form onSubmit={login} className="login-form">
            <div className="field">
              <label htmlFor="email">البريد الإلكتروني</label>
              <Input
                id="email"
                type="email"
                dir="ltr"
                autoComplete="username"
                required
                maxLength={254}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
              />
            </div>
            <div className="field">
              <label htmlFor="password">كلمة المرور</label>
              <div className="password-field">
                <Input
                  id="password"
                  type={visible ? "text" : "password"}
                  dir="ltr"
                  autoComplete="current-password"
                  required
                  maxLength={256}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setVisible(!visible)}
                  aria-label={visible ? "إخفاء كلمة المرور" : "إظهار كلمة المرور"}
                >
                  {visible ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>
            {error && (
              <div className="error-box" role="alert">
                {error}
              </div>
            )}
            <Button type="submit" disabled={busy} className="login-submit">
              {busy ? (
                <LoaderCircle size={18} className="animate-spin" />
              ) : (
                <>
                  الدخول إلى مساحة العمل <ArrowLeft size={18} />
                </>
              )}
            </Button>
          </form>
          <p className="login-footnote">
            <ShieldCheck size={15} />
            الدخول مخصص للحسابات المسجلة في النظام.
          </p>
        </div>
        <span className="login-copyright">واصل · من أرضنا إلى مستقبل أكثر كفاءة</span>
      </section>
      <section className="login-story" aria-label="منصة واصل لتدقيق الفواتير">
        <div className="story-grid" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className="story-top">
          <span>من رؤيتنا نصل لمستقبل أفضل</span>
          <span className="story-index">VISION 2030</span>
        </div>
        <WasilBrand inverted className="login-hero-brand" />
        <div className="product-scene" aria-hidden="true">
          <div className="heritage-landscape">
            <span className="heritage-sun" />
            <span className="heritage-dune dune-back" />
            <span className="heritage-dune dune-front" />
            <span className="najdi-fort">
              <i />
              <i />
              <i />
              <i />
              <i />
              <i />
            </span>
            <span className="heritage-palm">
              <i />
              <b />
            </span>
          </div>
          <div className="dashboard-device">
            <div className="device-screen">
              <div className="mini-sidebar">
                <strong>واصل</strong>
                <span />
                <span />
                <span />
                <span />
              </div>
              <div className="mini-dashboard">
                <div className="mini-welcome">
                  <strong>صباح الخير</strong>
                  <span>نظرة أوضح على مصاريف مشاريعك</span>
                </div>
                <div className="mini-metrics">
                  <span>
                    <small>إجمالي الفواتير</small>
                    <strong>1,248</strong>
                  </span>
                  <span>
                    <small>تحتاج مراجعة</small>
                    <strong>23</strong>
                  </span>
                  <span>
                    <small>المصاريف</small>
                    <strong>2.4M</strong>
                  </span>
                </div>
                <div className="mini-analytics">
                  <span className="mini-bars">
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </span>
                  <span className="mini-donut" />
                </div>
              </div>
            </div>
            <span className="device-base" />
          </div>
          <div className="verification-card">
            <div className="verification-heading">
              <ScanLine size={17} />
              <strong>تدقيق الفاتورة</strong>
            </div>
            <span>
              <Check size={12} /> استخراج البيانات
            </span>
            <span>
              <Check size={12} /> مطابقة المشروع
            </span>
            <span>
              <Check size={12} /> فحص الفروقات
            </span>
            <strong className="verification-approved">تم التحقق</strong>
          </div>
          <div className="invoice-float">
            <FileText size={17} />
            <span>
              INVOICE <small>INV-2026-0315</small>
            </span>
            <b>✓</b>
          </div>
        </div>
        <div className="story-copy">
          <h2>
            دقة في الأرقام،
            <br />
            رؤية في القرار.
          </h2>
          <p>
            ارفع الفاتورة، واربطها بالمشروع،
            <br />
            ودع واصل يكشف الفروقات قبل اعتمادها.
          </p>
        </div>
        <div className="story-bottom">
          <span>استخراج ذكي</span>
          <i />
          <span>تدقيق موثوق</span>
          <i />
          <span>قرار أوضح</span>
        </div>
      </section>
    </main>
  );
}
