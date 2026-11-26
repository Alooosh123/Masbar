import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../lib/api";
import type { AuthUser } from "../types";

interface Props {
  user: AuthUser;
  onComplete: (user: AuthUser) => void;
}

export function ForcedPasswordChange({ user, onComplete }: Props) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (newPassword.length < 8) {
      setError("يجب أن تتكون كلمة المرور الجديدة من 8 أحرف على الأقل.");
      return;
    }
    if (newPassword !== confirmation) {
      setError("تأكيد كلمة المرور غير مطابق.");
      return;
    }
    if (newPassword === currentPassword) {
      setError("اختر كلمة مرور مختلفة عن كلمة المرور المؤقتة.");
      return;
    }

    setBusy(true);
    try {
      const result = await api.changePassword(currentPassword, newPassword);
      onComplete(result.user);
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : "تعذر تغيير كلمة المرور. حاول مرة أخرى."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="password-rotation-page" dir="rtl">
      <section className="password-rotation-card">
        <div className="password-rotation-icon" aria-hidden="true">⌑</div>
        <span className="customer-admin-kicker">خطوة حماية مطلوبة</span>
        <h1>أنشئ كلمة مرورك الشخصية</h1>
        <p>
          مرحبًا {user.display_name}. كلمة المرور الحالية مؤقتة، ويجب استبدالها قبل استخدام التطبيق.
        </p>
        <form onSubmit={submit} className="customer-modal-form">
          <label>
            <span>كلمة المرور المؤقتة الحالية</span>
            <input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              maxLength={256}
            />
          </label>
          <label>
            <span>كلمة المرور الجديدة</span>
            <input
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
              minLength={8}
              maxLength={256}
            />
          </label>
          <label>
            <span>تأكيد كلمة المرور الجديدة</span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              required
              minLength={8}
              maxLength={256}
            />
          </label>
          <p className="customer-modal-note">استخدم 8 أحرف على الأقل، ولا تعِد استخدام كلمة المرور المؤقتة.</p>
          {error && <div className="customer-admin-alert is-error" role="alert">{error}</div>}
          <button type="submit" className="customer-admin-primary password-rotation-submit" disabled={busy || !currentPassword || !newPassword || !confirmation}>
            {busy ? "جارٍ تحديث كلمة المرور…" : "حفظ كلمة المرور والمتابعة"}
          </button>
        </form>
      </section>
    </main>
  );
}
