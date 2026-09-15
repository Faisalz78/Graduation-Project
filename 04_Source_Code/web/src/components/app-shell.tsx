"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowUpLeft,
  BadgeDollarSign,
  Bell,
  Building2,
  ChartNoAxesCombined,
  Files,
  FileSpreadsheet,
  FolderKanban,
  LogOut,
  PackageCheck,
  ShieldCheck,
  UsersRound,
  WalletCards,
} from "lucide-react";
import { useSession } from "@/components/session-provider";
import { api, roles, type NotificationPage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { WasilBrand } from "@/components/wasil-brand";

export function AppShell({ children }: { children: ReactNode }) {
  const { user, csrf_token } = useSession();
  const path = usePathname();
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      api<NotificationPage>("/notifications?page_size=1")
        .then((data) => {
          if (active) setUnreadNotifications(data.unread_count);
        })
        .catch(() => {
          if (active) setUnreadNotifications(0);
        });
    };
    refresh();
    window.addEventListener("notifications-changed", refresh);
    return () => {
      active = false;
      window.removeEventListener("notifications-changed", refresh);
    };
  }, [path]);
  async function logout() {
    setBusy(true);
    try {
      await api("/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrf_token } });
      router.replace("/login");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <div className="workspace">
      <aside className="sidebar">
        <Link href="/invoices" className="brand">
          <WasilBrand compact inverted />
          <span>
            <strong className="brand-product-name">منصة واصل</strong>
            <small>تدقيق الفواتير ومصاريف المشاريع</small>
          </span>
        </Link>
        <div className="nav-caption">مساحة العمل</div>
        <nav aria-label="القائمة الرئيسية">
          <Link
            href="/invoices"
            className={`nav-item ${path.startsWith("/invoices") ? "active" : ""}`}
            aria-current={path.startsWith("/invoices") ? "page" : undefined}
          >
            <Files size={20} />
            <span>{user.role === "EMPLOYEE" ? "فواتيري" : "الفواتير"}</span>
            <ArrowUpLeft size={15} className="nav-arrow" />
          </Link>
          <Link
            href="/notifications"
            className={"nav-item " + (path === "/notifications" ? "active" : "")}
            aria-current={path === "/notifications" ? "page" : undefined}
          >
            <Bell size={20} />
            <span>التنبيهات</span>
            {unreadNotifications > 0 ? (
              <span className="notification-count" aria-label="تنبيهات غير مقروءة">
                {unreadNotifications > 99 ? "99+" : unreadNotifications}
              </span>
            ) : (
              <ArrowUpLeft size={15} className="nav-arrow" />
            )}
          </Link>
          <Link
            href="/purchase-orders"
            className={`nav-item ${path.startsWith("/purchase-orders") ? "active" : ""}`}
            aria-current={path.startsWith("/purchase-orders") ? "page" : undefined}
          >
            <PackageCheck size={20} />
            <span>أوامر الشراء</span>
            <ArrowUpLeft size={15} className="nav-arrow" />
          </Link>
          <Link
            href="/projects"
            className={`nav-item ${path === "/projects" ? "active" : ""}`}
            aria-current={path === "/projects" ? "page" : undefined}
          >
            <FolderKanban size={20} />
            <span>المشاريع</span>
            <ArrowUpLeft size={15} className="nav-arrow" />
          </Link>
          <Link
            href="/suppliers"
            className={`nav-item ${path === "/suppliers" ? "active" : ""}`}
            aria-current={path === "/suppliers" ? "page" : undefined}
          >
            <Building2 size={20} />
            <span>الموردون</span>
            <ArrowUpLeft size={15} className="nav-arrow" />
          </Link>
          {user.role !== "EMPLOYEE" && (
            <Link
              href="/budgets"
              className={`nav-item ${path === "/budgets" ? "active" : ""}`}
              aria-current={path === "/budgets" ? "page" : undefined}
            >
              <WalletCards size={20} />
              <span>ميزانيات المشاريع</span>
              <ArrowUpLeft size={15} className="nav-arrow" />
            </Link>
          )}
          {user.role !== "EMPLOYEE" && (
            <Link
              href="/dashboard"
              className={`nav-item ${path === "/dashboard" ? "active" : ""}`}
              aria-current={path === "/dashboard" ? "page" : undefined}
            >
              <ChartNoAxesCombined size={20} />
              <span>اللوحة المالية</span>
              <ArrowUpLeft size={15} className="nav-arrow" />
            </Link>
          )}
          {user.role !== "EMPLOYEE" && (
            <Link
              href="/reports"
              className={"nav-item " + (path === "/reports" ? "active" : "")}
              aria-current={path === "/reports" ? "page" : undefined}
            >
              <FileSpreadsheet size={20} />
              <span>التقارير</span>
              <ArrowUpLeft size={15} className="nav-arrow" />
            </Link>
          )}
          {user.role === "FINANCE_MANAGER" && (
            <Link
              href="/approval-limits"
              className={`nav-item ${path === "/approval-limits" ? "active" : ""}`}
              aria-current={path === "/approval-limits" ? "page" : undefined}
            >
              <BadgeDollarSign size={20} />
              <span>حدود الموافقات</span>
              <ArrowUpLeft size={15} className="nav-arrow" />
            </Link>
          )}
          {user.role === "FINANCE_MANAGER" && (
            <Link
              href="/administration"
              className={`nav-item ${path === "/administration" ? "active" : ""}`}
              aria-current={path === "/administration" ? "page" : undefined}
            >
              <UsersRound size={20} />
              <span>إدارة النظام</span>
              <ArrowUpLeft size={15} className="nav-arrow" />
            </Link>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-note">
            <ShieldCheck size={19} />
            <p>ملفاتك محفوظة بصلاحيات محددة، وتبقى المسودة خاصة بك حتى إرسالها.</p>
          </div>
          <div className="profile">
            <span className="avatar">{user.name.slice(0, 1)}</span>
            <div>
              <strong>{user.name}</strong>
              <small>{roles[user.role]}</small>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={logout}
              disabled={busy}
              aria-label="تسجيل الخروج"
            >
              <LogOut size={18} />
            </Button>
          </div>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
        </div>
      </aside>
      <div className="workspace-content">
        <header className="topbar">
          <span className="breadcrumb">
            مساحة العمل <span>/</span>{" "}
            {path.startsWith("/notifications")
              ? "التنبيهات"
              : path.startsWith("/projects")
                ? "المشاريع"
                : path.startsWith("/purchase-orders")
                  ? "أوامر الشراء والاستلام"
                  : path.startsWith("/budgets")
                    ? "ميزانيات المشاريع"
                    : path.startsWith("/dashboard")
                      ? "اللوحة المالية"
                      : path.startsWith("/reports")
                        ? "التقارير والتصدير"
                        : path.startsWith("/suppliers")
                          ? "الموردون"
                          : path.startsWith("/approval-limits")
                            ? "حدود الموافقات"
                            : path.startsWith("/administration")
                              ? "إدارة المشاريع والمستخدمين"
                              : "الفواتير"}
          </span>
          <span className="account-role">
            <span className="status-dot" />
            {roles[user.role]}
          </span>
        </header>
        <main id="main-content">{children}</main>
        <footer className="workspace-footer">
          <span>واصل · منصة التدقيق الذكي للفواتير ومصاريف المشاريع</span>
          <span>نسخة التطوير السابعة عشرة</span>
        </footer>
      </div>
    </div>
  );
}
