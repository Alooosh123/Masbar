import { useEffect, useState } from "react";
import type { CSSProperties, FormEvent, ReactNode } from "react";
import { ApiError, api } from "../lib/api";

interface Props {
  children: ReactNode;
}

const panelStyle: CSSProperties = {
  width: "min(92vw, 420px)",
  padding: "30px",
  border: "1px solid rgba(148,163,184,.22)",
  borderRadius: "20px",
  background: "rgba(10,16,29,.96)",
  boxShadow: "0 24px 80px rgba(0,0,0,.4)",
  color: "#e2e8f0",
};

const inputStyle: CSSProperties = {
  width: "100%",
  padding: "13px 14px",
  borderRadius: "11px",
  border: "1px solid rgba(148,163,184,.3)",
  background: "rgba(15,23,42,.9)",
  color: "#f8fafc",
  fontSize: "15px",
  outline: "none",
};

export function AuthGate({ children }: Props) {
  const [status, setStatus] = useState<"loading" | "login" | "ready" | "offline">("loading");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const health = await api.health();
        if (!health.auth_required) {
          if (!cancelled) setStatus("ready");
          return;
        }
        const current = await api.me();
        if (!cancelled) setStatus(current.authenticated ? "ready" : "login");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          setStatus("login");
        } else {
          setStatus("offline");
        }
      }
    }

    void check();
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
      await api.login(email.trim(), password);
      setPassword("");
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "تعذر تسجيل الدخول.");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      setPassword("");
      setStatus("login");
    }
  }

  if (status === "ready") {
    return (
      <>
        {children}
        <button
          type="button"
          onClick={() => void logout()}
          title="تسجيل الخروج"
          aria-label="تسجيل الخروج"
          style={{
            position: "fixed",
            zIndex: 80,
            top: "12px",
            left: "12px",
            padding: "8px 11px",
            borderRadius: "10px",
            border: "1px solid rgba(148,163,184,.24)",
            background: "rgba(8,13,24,.82)",
            color: "#cbd5e1",
            cursor: "pointer",
            fontSize: "11px",
          }}
        >
          خروج
        </button>
      </>
    );
  }

  return (
    <main
      dir="rtl"
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        padding: "24px",
        background: "radial-gradient(circle at top, #17243a, #050811 65%)",
        fontFamily: "inherit",
      }}
    >
      <section style={panelStyle}>
        <div style={{ fontSize: "12px", letterSpacing: ".12em", color: "#fbbf24" }}>
          MASBAR · SECURE ACCESS
        </div>
        <h1 style={{ margin: "10px 0 6px", fontSize: "25px" }}>
          تسجيل الدخول إلى مسبار
        </h1>
        <p style={{ margin: "0 0 24px", color: "#94a3b8", lineHeight: 1.8, fontSize: "13px" }}>
          أدخل حسابك المعتمد للوصول إلى المحادثة وجلسات الصيانة.
        </p>
        {status === "loading" && <p>جارٍ التحقق من حالة الخادم…</p>}
        {status === "offline" && (
          <p role="alert" style={{ color: "#fca5a5", lineHeight: 1.8 }}>
            تعذر الاتصال بالخادم. تحقق من الشبكة ثم حدّث الصفحة.
          </p>
        )}
        {status === "login" && (
          <form onSubmit={submit} style={{ display: "grid", gap: "13px" }}>
            <label style={{ display: "grid", gap: "7px", fontSize: "12px", color: "#cbd5e1" }}>
              البريد الإلكتروني
              <input
                style={inputStyle}
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                maxLength={254}
                placeholder="name@example.com"
              />
            </label>
            <label style={{ display: "grid", gap: "7px", fontSize: "12px", color: "#cbd5e1" }}>
              كلمة المرور
              <input
                style={inputStyle}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                maxLength={256}
              />
            </label>
            {error && (
              <p role="alert" style={{ margin: 0, color: "#fca5a5", fontSize: "12px", lineHeight: 1.7 }}>
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={busy || !email.trim() || !password}
              style={{
                marginTop: "8px",
                padding: "13px",
                border: 0,
                borderRadius: "11px",
                background: "linear-gradient(135deg,#fbbf24,#d97706)",
                color: "#111827",
                fontWeight: 700,
                cursor: busy ? "wait" : "pointer",
                opacity: busy ? .65 : 1,
              }}
            >
              {busy ? "جارٍ التحقق…" : "دخول آمن"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
