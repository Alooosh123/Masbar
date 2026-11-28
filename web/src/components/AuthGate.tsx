import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, api } from "../lib/api";
import type { AuthUser } from "../types";
import { AuthContext } from "./AuthContext";
import { CustomerManagement } from "./CustomerManagement";
import { ForcedPasswordChange } from "./ForcedPasswordChange";

interface Props {
  children: ReactNode;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (options: {
            client_id: string;
            callback: (response: { credential?: string }) => void;
            auto_select?: boolean;
            cancel_on_tap_outside?: boolean;
          }) => void;
          renderButton: (element: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

type GateStatus = "loading" | "login" | "ready" | "offline";

const ROLE_LABELS: Record<AuthUser["role"], string> = {
  owner: "مالك النظام",
  admin: "مدير",
  technician: "فني",
  customer: "عميل",
  viewer: "مشاهد",
};

export function AuthGate({ children }: Props) {
  const [status, setStatus] = useState<GateStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showCustomerManagement, setShowCustomerManagement] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function checkSession() {
      try {
        const health = await api.health();
        if (!health.auth_required) {
          if (!cancelled) {
            setUser(null);
            setStatus("ready");
          }
          return;
        }

        const current = await api.me();
        if (cancelled) return;
        setUser(current.authenticated ? current.user : null);
        setStatus(current.authenticated ? "ready" : "login");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          setUser(null);
          setStatus("login");
        } else {
          setStatus("offline");
        }
      }
    }

    void checkSession();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleGoogleCredential(credential: string) {
    setBusy(true);
    setError("");
    try {
      const result = await api.googleLogin(credential);
      setUser(result.user);
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "تعذر التحقق من حساب Google.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (status !== "login") return;
    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;
    const googleApi = window.google?.accounts?.id;
    if (!clientId || !googleApi) return;
    googleApi.initialize({
      client_id: clientId,
      callback: (response: { credential?: string }) => {
        if (response.credential) void handleGoogleCredential(response.credential);
      },
      auto_select: false,
      cancel_on_tap_outside: true,
    });
    const button = document.getElementById("google-signin-button");
    if (button) {
      button.replaceChildren();
      googleApi.renderButton(button, { theme: "outline", size: "large", width: 320, text: "continue_with", shape: "pill", locale: "ar" });
    }
  }, [status]);

  async function logout() {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setShowCustomerManagement(false);
      setStatus("login");
    }
  }

  if (status === "ready") {
    const canManageCustomers = user?.role === "owner" || user?.role === "admin";
    return (
      <AuthContext.Provider value={user}>
        {user?.must_change_password ? (
          <ForcedPasswordChange user={user} onComplete={setUser} />
        ) : showCustomerManagement && canManageCustomers ? (
          <CustomerManagement onClose={() => setShowCustomerManagement(false)} />
        ) : (
          children
        )}
        {user && (
          <div className="auth-user-chip" dir="rtl">
            <strong>{user.display_name || user.email}</strong>
            <span className="auth-user-role">{ROLE_LABELS[user.role]}</span>
            {canManageCustomers && !user.must_change_password && (
              <button
                type="button"
                className="auth-manage-customers"
                onClick={() => setShowCustomerManagement((visible) => !visible)}
                aria-pressed={showCustomerManagement}
              >
                {showCustomerManagement ? "إغلاق الإدارة" : "إدارة العملاء"}
              </button>
            )}
            <button type="button" className="auth-logout" onClick={() => void logout()}>
              خروج
            </button>
          </div>
        )}
      </AuthContext.Provider>
    );
  }

  return (
    <main className="auth-page" dir="rtl">
      <section className="auth-layout" aria-label="بوابة تسجيل الدخول إلى مسبار">
        <div className="auth-story">
          <div className="auth-brand">
            <span className="auth-brand-mark" aria-hidden="true">
              <svg width="27" height="27" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 3 4.5 6v6c0 4.5 3 7.6 7.5 9 4.5-1.4 7.5-4.5 7.5-9V6Z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </span>
            <span className="auth-brand-copy">
              <strong>مِسبار</strong>
              <small>INDUSTRIAL INTELLIGENCE</small>
            </span>
          </div>

          <div className="auth-story-content">
            <span className="auth-kicker">
              <span aria-hidden="true">✦</span>
              مساعدك الصناعي الذكي
            </span>
            <h1>
              افهم معداتك.
              <br />
              <span>ابدأ من المعلومة الصحيحة.</span>
            </h1>
            <p className="auth-story-copy">
              مساحة موحدة للاستفسار عن المعدات الصناعية، وتحليل صور القطع،
              ومتابعة جلسات الفحص والصيانة بحسب صلاحيات حسابك.
            </p>

            <div className="auth-feature-list">
              <div className="auth-feature">
                <span className="auth-feature-icon" aria-hidden="true">✧</span>
                <span>محادثة عربية للاستفسارات الفنية</span>
              </div>
              <div className="auth-feature">
                <span className="auth-feature-icon" aria-hidden="true">◈</span>
                <span>إرسال صور المعدات والقطع للتحليل</span>
              </div>
              <div className="auth-feature">
                <span className="auth-feature-icon" aria-hidden="true">✓</span>
                <span>جلسات فحص وصلاحيات بحسب نوع الحساب</span>
              </div>
            </div>
          </div>

          <div className="auth-story-foot">
            <span aria-hidden="true" />
            بوابة دخول آمنة · مسبار
          </div>
        </div>

        <div className="auth-form-side">
          <header className="auth-form-heading">
            <p className="auth-form-eyebrow">بوابة العملاء والمستخدمين</p>
            <h2>تسجيل الدخول</h2>
            <p>سجّل الدخول باستخدام حساب Google. سيتم التحقق من بريدك تلقائيًا.</p>
          </header>

          {status === "loading" && (
            <div className="auth-offline" role="status">جارٍ التحقق من اتصال النظام وجلسة الدخول…</div>
          )}

          {status === "offline" && (
            <div>
              <div className="auth-offline" role="alert">
                تعذر الاتصال بالخادم حاليًا. تحقق من اتصال الإنترنت ثم أعد المحاولة.
              </div>
              <button type="button" className="auth-retry" onClick={() => window.location.reload()}>
                إعادة المحاولة
              </button>
            </div>
          )}

          {status === "login" && (
            <div className="auth-form" aria-label="تسجيل الدخول عبر Google">
              <div id="google-signin-button" className="google-signin-button" />
              {!import.meta.env.VITE_GOOGLE_CLIENT_ID && (
                <div className="auth-offline" role="status">
                  تسجيل Google يحتاج إعداد Google OAuth Client ID من مسؤول النظام.
                </div>
              )}
              {error && <div className="auth-error" role="alert">{error}</div>}
              {busy && <div className="auth-offline" role="status">جارٍ التحقق من حساب Google…</div>}
            </div>
          )}
          <p className="auth-account-help">
            لا تملك حسابًا بعد؟ اطلب من مسؤول المنشأة إنشاء <strong>حساب عميل</strong> وتزويدك ببيانات الدخول.
            لا يوجد تسجيل عام مفتوح في الوقت الحالي.
          </p>
          <p className="auth-form-foot">
            تسجيل الدخول عبر Google · التحقق من البريد تلقائي
          </p>
        </div>
      </section>
    </main>
  );
}
