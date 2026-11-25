import { useEffect, useState } from "react";
import { ChatScreen } from "./components/ChatScreen";
import { LoginScreen } from "./components/LoginScreen";
import {
  api,
  clearAuthToken,
  getAuthToken,
  type AuthUser,
} from "./lib/api";

export default function App() {
  const [ready, setReady] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [initialSetupRequired, setInitialSetupRequired] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [startupError, setStartupError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function initialize() {
      try {
        const status = await api.authStatus();
        if (cancelled) return;
        setAuthEnabled(status.auth_enabled);
        setInitialSetupRequired(status.initial_setup_required);

        if (!status.auth_enabled) {
          setReady(true);
          return;
        }

        if (getAuthToken()) {
          try {
            const result = await api.me();
            if (!cancelled && result.authenticated && result.user) {
              setUser(result.user);
            } else {
              clearAuthToken();
            }
          } catch {
            clearAuthToken();
          }
        }
        if (!cancelled) setReady(true);
      } catch {
        if (!cancelled) {
          setStartupError("تعذر الوصول إلى خدمة تسجيل الدخول. حدّث الصفحة بعد التحقق من اتصال الخادم.");
          setReady(true);
        }
      }
    }

    void initialize();
    return () => {
      cancelled = true;
    };
  }, []);

  function logout() {
    clearAuthToken();
    setUser(null);
    setInitialSetupRequired(false);
  }

  if (!ready) {
    return (
      <main className="auth-screen" dir="rtl">
        <div className="auth-loading">جارٍ التحقق من أمان الاتصال…</div>
      </main>
    );
  }

  if (!authEnabled) {
    return <ChatScreen />;
  }

  if (startupError) {
    return (
      <main className="auth-screen" dir="rtl">
        <section className="auth-card">
          <h1>مسبار</h1>
          <p className="auth-error">{startupError}</p>
          <button className="auth-submit" onClick={() => window.location.reload()}>إعادة المحاولة</button>
        </section>
      </main>
    );
  }

  if (!user) {
    return (
      <LoginScreen
        initialSetupRequired={initialSetupRequired}
        onAuthenticated={(authenticatedUser) => {
          setUser(authenticatedUser);
          setInitialSetupRequired(false);
        }}
      />
    );
  }

  return <ChatScreen onLogout={logout} />;
}
