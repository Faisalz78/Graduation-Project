"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bell, CheckCheck, ChevronLeft, ChevronRight, LoaderCircle } from "lucide-react";
import { api, type NotificationPage } from "@/lib/api";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";

function displayDate(value: string) {
  return new Intl.DateTimeFormat("ar-SA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Riyadh",
  }).format(new Date(value));
}

export default function NotificationsPage() {
  const { csrf_token } = useSession();
  const [data, setData] = useState<NotificationPage | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    const query = new URLSearchParams({
      page: String(page),
      page_size: "20",
      unread_only: String(unreadOnly),
    });
    api<NotificationPage>("/notifications?" + query)
      .then(setData)
      .catch((failure) => setError((failure as Error).message));
  }, [page, unreadOnly]);

  useEffect(() => {
    load();
  }, [load, attempt]);

  function announceChange() {
    window.dispatchEvent(new Event("notifications-changed"));
  }

  async function markRead(id: string) {
    setBusy(id);
    setError("");
    try {
      await api("/notifications/" + id + "/read", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf_token },
      });
      load();
      announceChange();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function markAllRead() {
    setBusy("all");
    setError("");
    try {
      await api("/notifications/read-all", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf_token },
      });
      setPage(1);
      load();
      announceChange();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <div className="page-container">
      <div className="page-heading">
        <div>
          <span className="eyebrow">متابعة العمل</span>
          <h1>التنبيهات</h1>
          <p>الفواتير التي تحتاج إجراءً منك، ونتائج القرارات على فواتيرك.</p>
        </div>
        <Button
          variant="outline"
          onClick={markAllRead}
          disabled={!data?.unread_count || busy === "all"}
        >
          {busy === "all" ? (
            <LoaderCircle size={17} className="animate-spin" />
          ) : (
            <CheckCheck size={17} />
          )}
          قراءة الكل
        </Button>
      </div>

      <div className="notification-toolbar">
        <div className="segmented-control" aria-label="تصفية التنبيهات">
          <button
            type="button"
            className={!unreadOnly ? "active" : ""}
            onClick={() => {
              setUnreadOnly(false);
              setPage(1);
            }}
          >
            الكل
          </button>
          <button
            type="button"
            className={unreadOnly ? "active" : ""}
            onClick={() => {
              setUnreadOnly(true);
              setPage(1);
            }}
          >
            غير المقروءة {data ? "(" + data.unread_count + ")" : ""}
          </button>
        </div>
      </div>

      {error ? (
        <div className="surface inline-state">
          <p role="alert">{error}</p>
          <Button variant="outline" onClick={() => setAttempt((value) => value + 1)}>
            إعادة المحاولة
          </Button>
        </div>
      ) : !data ? (
        <div className="surface inline-state" role="status">
          <LoaderCircle className="animate-spin" />
          جارٍ تحميل التنبيهات…
        </div>
      ) : data.items.length === 0 ? (
        <div className="surface inline-state">
          <Bell size={30} />
          <h2>{unreadOnly ? "لا توجد تنبيهات غير مقروءة" : "لا توجد تنبيهات حتى الآن"}</h2>
          <p>ستظهر هنا الفواتير التي تحتاج مراجعتك ونتائج القرارات.</p>
        </div>
      ) : (
        <>
          <div className="surface notification-list">
            {data.items.map((notification) => (
              <article
                className={"notification-row " + (notification.read_at ? "read" : "unread")}
                key={notification.id}
              >
                <span className="notification-indicator" aria-hidden="true" />
                <div>
                  <Link href={"/invoices/" + notification.invoice_id}>
                    <h2>{notification.title}</h2>
                  </Link>
                  <p>{notification.message}</p>
                  <time dateTime={notification.created_at}>
                    {displayDate(notification.created_at)}
                  </time>
                </div>
                {!notification.read_at && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy === notification.id}
                    onClick={() => markRead(notification.id)}
                  >
                    {busy === notification.id && (
                      <LoaderCircle size={15} className="animate-spin" />
                    )}
                    تمييز كمقروء
                  </Button>
                )}
              </article>
            ))}
          </div>
          {pages > 1 && (
            <div className="pagination">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((value) => value - 1)}
              >
                <ChevronRight size={16} />
                السابق
              </Button>
              <span>
                صفحة {page} من {pages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= pages}
                onClick={() => setPage((value) => value + 1)}
              >
                التالي
                <ChevronLeft size={16} />
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
