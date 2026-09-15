"use client";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { api, ApiError, type AuthSession } from "@/lib/api";
import { Button } from "@/components/ui/button";

const Context = createContext<AuthSession | null>(null);
export function useSession() {
  const session = useContext(Context);
  if (!session) throw new Error("Session provider is required");
  return session;
}
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const router = useRouter();
  useEffect(() => {
    let active = true;
    api<AuthSession>("/auth/session")
      .then((data) => {
        if (active) setSession(data);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [router, attempt]);
  if (!session)
    return (
      <div className="screen-center">
        <div className="loading-box">
          {error ? (
            <>
              <p role="alert">{error}</p>
              <Button
                variant="outline"
                onClick={() => {
                  setError("");
                  setAttempt((n) => n + 1);
                }}
              >
                <RefreshCw size={16} />
                إعادة المحاولة
              </Button>
            </>
          ) : (
            <>
              <LoaderCircle className="animate-spin" size={24} />
              <span>جارٍ تجهيز مساحة العمل…</span>
            </>
          )}
        </div>
      </div>
    );
  return <Context.Provider value={session}>{children}</Context.Provider>;
}
