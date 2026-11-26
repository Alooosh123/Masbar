import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ApiError, api } from "../lib/api";
import type { AuthUser } from "../types";
import { AuthContext } from "./AuthContext";

interface Props {
  children: ReactNode;
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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    setBusy(true);
    setError("");
    try {
      const result = await api.login(email.trim(), password);
      setUser(result.user);
      setPassword("");
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "تعذر تسجيل الدخول. تحقق من بيانات الحساب.");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setPassword("");
      setStatus("login");
    }
  }

  if (status === "ready") {
    return (
      <AuthContext.Provider value={user}>
        {children}
        {user && (
          <div className="auth-user-chip" dir="rtl">
            <strong>{user.display_name || user.email}</strong>
            <span className="auth-user-role">{ROLE_LABELS[user.role]}</span>
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
            <p>أدخل البريد الإلكتروني وكلمة المرور المخصصة لحسابك للوصول إلى التطبيق.</p>
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
            <form className="auth-form" onSubmit={submit}>
              <label className="auth-field">
                <span className="auth-label">البريد الإلكتروني</span>
                <input
                  className="auth-input"
                  type="email"
                  dir="ltr"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  maxLength={254}
                  placeholder="name@example.com"
                />
              </label>

              <label className="auth-field">
                <span className="auth-label">كلمة المرور</span>
                <span className="auth-input-wrap">
                  <input
                    className="auth-input auth-password-input"
                    type={showPassword ? "text" : "password"}
                    dir="ltr"
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                    maxLength={256}
                    placeholder="أدخل كلمة المرور"
                  />
                  <button
                    type="button"
                    className="auth-toggle-password"
                    onClick={() => setShowPassword((visible) => !visible)}
                    aria-label={showPassword ? "إخفاء كلمة المرور" : "إظهار كلمة المرور"}
                    aria-pressed={showPassword}
                  >
                    {showPassword ? "إخفاء" : "إظهار"}
                  </button>
                </span>
              </label>

              {error && <div className="auth-error" role="alert">{error}</div>}

              <button
                type="submit"
                className="auth-submit"
                disabled={busy || !email.trim() || !password}
              >
                {busy ? "جارٍ التحقق من الحساب…" : "دخول إلى مسبار"}
                {!busy && <span aria-hidden="true">←</span>}
              </button>
            </form>
          )}

          <p className="auth-account-help">
            لا تملك حسابًا بعد؟ اطلب من مسؤول المنشأة إنشاء <strong>حساب عميل</strong> وتزويدك ببيانات الدخول.
            لا يوجد تسجيل عام مفتوح في الوقت الحالي.
          </p>
          <p className="auth-form-foot">
            حماية الحسابات مفعّلة · لا تشارك كلمة المرور مع أي شخص
          </p>
        </div>
      </section>
    </main>
  );
}
