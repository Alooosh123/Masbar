import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api, setAuthToken, type AuthUser } from "../lib/api";

interface Props {
  initialSetupRequired: boolean;
  onAuthenticated: (user: AuthUser) => void;
}

export function LoginScreen({ initialSetupRequired, onAuthenticated }: Props) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = initialSetupRequired
        ? await api.initializeOwner({
            setup_token: setupToken.trim(),
            email: email.trim(),
            full_name: fullName.trim(),
            password,
          })
        : await api.login(email.trim(), password);
      setAuthToken(result.access_token);
      onAuthenticated(result.user);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "تعذر تسجيل الدخول. تحقق من الاتصال ثم أعد المحاولة."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-screen" dir="rtl">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-brand-mark" aria-hidden="true">م</div>
        <p className="auth-eyebrow">منصة المساعد الصناعي</p>
        <h1 id="auth-title">مسبار</h1>
        <p className="auth-intro">
          {initialSetupRequired
            ? "أنشئ حساب مالك النظام لأول مرة. هذا الحساب يدير المستخدمين والصلاحيات."
            : "سجّل الدخول للوصول إلى المحادثة والجلسات الصناعية."}
        </p>

        <form className="auth-form" onSubmit={submit}>
          {initialSetupRequired && (
            <>
              <label htmlFor="auth-full-name">الاسم الكامل</label>
              <input
                id="auth-full-name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                autoComplete="name"
                required
                minLength={2}
                maxLength={120}
              />
            </>
          )}

          <label htmlFor="auth-email">البريد الإلكتروني</label>
          <input
            id="auth-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="username"
            required
          />

          <label htmlFor="auth-password">كلمة المرور</label>
          <input
            id="auth-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={initialSetupRequired ? "new-password" : "current-password"}
            required
            minLength={initialSetupRequired ? 12 : 1}
            maxLength={256}
          />

          {initialSetupRequired && (
            <>
              <label htmlFor="auth-setup-token">رمز تهيئة المالك</label>
              <input
                id="auth-setup-token"
                type="password"
                value={setupToken}
                onChange={(event) => setSetupToken(event.target.value)}
                autoComplete="off"
                required
                minLength={16}
              />
              <small className="auth-help">
                يستخدم مرة واحدة لإنشاء حساب المالك الأول، ولا يُستخدم ككلمة مرور للحساب.
              </small>
            </>
          )}

          {error && <p className="auth-error" role="alert">{error}</p>}

          <button className="auth-submit" type="submit" disabled={busy}>
            {busy
              ? "جارٍ التحقق…"
              : initialSetupRequired
                ? "إنشاء حساب المالك"
                : "تسجيل الدخول"}
          </button>
        </form>

        <p className="auth-security-note">
          الاتصال محمي برمز دخول قصير الصلاحية. لا تشارك كلمة المرور أو رمز التهيئة مع الآخرين.
        </p>
      </section>
    </main>
  );
}
