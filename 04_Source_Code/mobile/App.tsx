import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { StatusBar } from "expo-status-bar";

import { clearToken, getToken, request, storeToken } from "./src/api";
import { AppHeader, BottomNavigation } from "./src/components/AppChrome";
import { InvoiceDetailScreen } from "./src/screens/InvoiceDetailScreen";
import { InvoiceListScreen } from "./src/screens/InvoiceListScreen";
import { LoginScreen } from "./src/screens/LoginScreen";
import { UploadScreen } from "./src/screens/UploadScreen";
import type { AuthSession, MobileLoginResult } from "./src/types";

type Screen =
  | { name: "invoices" }
  | { name: "upload" }
  | { name: "detail"; invoiceId: string };

export default function App() {
  const [booting, setBooting] = useState(true);
  const [session, setSession] = useState<AuthSession | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>({ name: "invoices" });

  useEffect(() => {
    let active = true;
    async function restoreSession() {
      const savedToken = await getToken();
      if (!savedToken) {
        if (active) setBooting(false);
        return;
      }
      try {
        const restored = await request<AuthSession>(
          "/auth/session",
          savedToken,
        );
        if (active) {
          setToken(savedToken);
          setSession(restored);
        }
      } catch {
        await clearToken();
      } finally {
        if (active) setBooting(false);
      }
    }
    void restoreSession();
    return () => {
      active = false;
    };
  }, []);

  async function handleLogin(result: MobileLoginResult) {
    await storeToken(result.access_token);
    setToken(result.access_token);
    setSession({
      user: result.user,
      csrf_token: result.csrf_token,
      expires_at: result.expires_at,
    });
    setScreen({ name: "invoices" });
  }

  async function handleLogout() {
    if (token) {
      try {
        await request("/auth/logout", token, { method: "POST" });
      } catch {
        // The local credential is still removed if the server is unavailable.
      }
    }
    await clearToken();
    setToken(null);
    setSession(null);
    setScreen({ name: "invoices" });
  }

  function handleExpired() {
    void clearToken();
    setToken(null);
    setSession(null);
    setScreen({ name: "invoices" });
  }

  if (booting) {
    return (
      <SafeAreaView style={styles.loading}>
        <StatusBar style="dark" />
        <View style={styles.loadingMark}>
          <Text style={styles.loadingMarkText}>دقّق</Text>
        </View>
        <ActivityIndicator color="#0b6b57" size="large" />
        <Text style={styles.loadingText}>جارٍ التحقق من الجلسة…</Text>
      </SafeAreaView>
    );
  }

  if (!session || !token) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  return (
    <SafeAreaView style={styles.app}>
      <StatusBar style="dark" />
      <AppHeader session={session} onLogout={handleLogout} />
      <View style={styles.content}>
        {screen.name === "invoices" ? (
          <InvoiceListScreen
            token={token}
            onExpired={handleExpired}
            onOpenInvoice={(invoiceId) =>
              setScreen({ name: "detail", invoiceId })
            }
          />
        ) : null}
        {screen.name === "upload" ? (
          <UploadScreen
            token={token}
            role={session.user.role}
            onExpired={handleExpired}
            onUploaded={(invoiceId) => setScreen({ name: "detail", invoiceId })}
          />
        ) : null}
        {screen.name === "detail" ? (
          <InvoiceDetailScreen
            invoiceId={screen.invoiceId}
            token={token}
            onBack={() => setScreen({ name: "invoices" })}
            onExpired={handleExpired}
          />
        ) : null}
      </View>
      {screen.name !== "detail" ? (
        <BottomNavigation
          active={screen.name}
          canUpload={session.user.role === "EMPLOYEE"}
          onChange={(name) =>
            setScreen(
              name === "upload" ? { name: "upload" } : { name: "invoices" },
            )
          }
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  app: { flex: 1, backgroundColor: "#f4f7f5" },
  content: { flex: 1 },
  loading: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 18,
    backgroundColor: "#f4f7f5",
  },
  loadingMark: {
    width: 76,
    height: 76,
    borderRadius: 24,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#0b6b57",
  },
  loadingMarkText: { color: "#fff", fontSize: 22, fontWeight: "900" },
  loadingText: { color: "#5f6f68", fontSize: 15 },
});
