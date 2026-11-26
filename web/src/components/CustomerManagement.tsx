import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../lib/api";
import type { AuthUser } from "../types";

interface Props {
  onClose: () => void;
}

interface IssuedPassword {
  displayName: string;
  email: string;
  password: string;
  action: "created" | "reset";
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "تعذر إكمال العملية. حاول مرة أخرى.";
}

function dateLabel(value: string | null): string {
  if (!value) return "لم يسجل الدخول بعد";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ar-YE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function CustomerManagement({ onClose }: Props) {
  const [customers, setCustomers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<AuthUser | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [issuedPassword, setIssuedPassword] = useState<IssuedPassword | null>(null);
  const [copyStatus, setCopyStatus] = useState("");

  async function loadCustomers() {
    setLoading(true);
    setError("");
    try {
      const result = await api.customers();
      setCustomers(result.customers);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCustomers();
  }, []);

  const filteredCustomers = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return customers;
    return customers.filter((customer) =>
      [customer.display_name, customer.email].some((value) =>
        value.toLocaleLowerCase().includes(normalized)
      )
    );
  }, [customers, query]);

  function openCreate() {
    setDisplayName("");
    setEmail("");
    setEditing(null);
    setError("");
    setCreateOpen(true);
  }

  function openEdit(customer: AuthUser) {
    setDisplayName(customer.display_name);
    setEmail(customer.email);
    setEditing(customer);
    setError("");
    setCreateOpen(true);
  }

  async function submitCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusyId(editing?.id ?? "create");
    try {
      if (editing) {
        const result = await api.updateCustomer(editing.id, {
          display_name: displayName.trim(),
          email: email.trim(),
        });
        setCustomers((current) =>
          current.map((item) => (item.id === editing.id ? result.user : item))
        );
        setNotice("تم حفظ بيانات العميل.");
        setCreateOpen(false);
      } else {
        const result = await api.createCustomer(email.trim(), displayName.trim());
        setCustomers((current) => [result.user, ...current]);
        setIssuedPassword({
          displayName: result.user.display_name,
          email: result.user.email,
          password: result.temporary_password,
          action: "created",
        });
        setCreateOpen(false);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function toggleActivation(customer: AuthUser) {
    const action = customer.is_active ? "تعطيل" : "تفعيل";
    const confirmed = window.confirm(
      customer.is_active
        ? `هل تريد تعطيل حساب ${customer.display_name}؟ سيتم إنهاء جلساته الحالية فورًا.`
        : `هل تريد إعادة تفعيل حساب ${customer.display_name}؟`
    );
    if (!confirmed) return;

    setError("");
    setNotice("");
    setBusyId(customer.id);
    try {
      const result = await api.setCustomerActive(customer.id, !customer.is_active);
      setCustomers((current) =>
        current.map((item) => (item.id === customer.id ? result.user : item))
      );
      setNotice(result.user.is_active ? "تم تفعيل حساب العميل." : "تم تعطيل الحساب وإنهاء جلساته.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function resetPassword(customer: AuthUser) {
    const confirmed = window.confirm(
      `إصدار كلمة مرور مؤقتة جديدة للعميل ${customer.display_name}؟ ستُلغى جلساته الحالية ويجب عليه تغييرها عند الدخول.`
    );
    if (!confirmed) return;

    setError("");
    setNotice("");
    setBusyId(customer.id);
    try {
      const result = await api.resetCustomerPassword(customer.id);
      setCustomers((current) =>
        current.map((item) => (item.id === customer.id ? result.user : item))
      );
      setIssuedPassword({
        displayName: result.user.display_name,
        email: result.user.email,
        password: result.temporary_password,
        action: "reset",
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function copyIssuedPassword() {
    if (!issuedPassword) return;
    try {
      await navigator.clipboard.writeText(issuedPassword.password);
      setCopyStatus("تم نسخ كلمة المرور. سلّمها للعميل عبر قناة آمنة.");
    } catch {
      setCopyStatus("تعذر النسخ التلقائي؛ حدّد كلمة المرور وانسخها يدويًا.");
    }
  }

  return (
    <main className="customer-admin-page" dir="rtl">
      <header className="customer-admin-header">
        <div>
          <span className="customer-admin-kicker">لوحة المالك · الحسابات</span>
          <h1>إدارة العملاء</h1>
          <p>إنشاء حسابات العملاء ومراجعة حالتها وتحديث بيانات الدخول.</p>
        </div>
        <button type="button" className="customer-admin-back" onClick={onClose}>
          العودة إلى التطبيق
        </button>
      </header>

      <section className="customer-admin-stats" aria-label="ملخص العملاء">
        <div>
          <span>إجمالي العملاء</span>
          <strong>{customers.length}</strong>
        </div>
        <div>
          <span>الحسابات النشطة</span>
          <strong>{customers.filter((customer) => customer.is_active).length}</strong>
        </div>
        <div>
          <span>الحسابات المعطلة</span>
          <strong>{customers.filter((customer) => !customer.is_active).length}</strong>
        </div>
      </section>

      <section className="customer-admin-panel">
        <div className="customer-admin-toolbar">
          <label className="customer-admin-search">
            <span aria-hidden="true">⌕</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="ابحث بالاسم أو البريد الإلكتروني"
              aria-label="البحث عن عميل"
            />
          </label>
          <button type="button" className="customer-admin-primary" onClick={openCreate}>
            <span aria-hidden="true">＋</span>
            إنشاء حساب عميل
          </button>
        </div>

        {error && <div className="customer-admin-alert is-error" role="alert">{error}</div>}
        {notice && <div className="customer-admin-alert is-success" role="status">{notice}</div>}

        {loading ? (
          <div className="customer-admin-empty" role="status">جارٍ تحميل قائمة العملاء…</div>
        ) : filteredCustomers.length === 0 ? (
          <div className="customer-admin-empty">
            {customers.length === 0 ? "لا توجد حسابات عملاء حتى الآن." : "لا توجد نتائج مطابقة للبحث."}
          </div>
        ) : (
          <div className="customer-admin-table-wrap">
            <table className="customer-admin-table">
              <thead>
                <tr>
                  <th>العميل</th>
                  <th>الحالة</th>
                  <th>آخر دخول</th>
                  <th>تاريخ الإنشاء</th>
                  <th>الإجراءات</th>
                </tr>
              </thead>
              <tbody>
                {filteredCustomers.map((customer) => (
                  <tr key={customer.id}>
                    <td>
                      <div className="customer-admin-identity">
                        <strong>{customer.display_name}</strong>
                        <bdi dir="ltr">{customer.email}</bdi>
                      </div>
                    </td>
                    <td>
                      <span className={customer.is_active ? "customer-status is-active" : "customer-status is-disabled"}>
                        {customer.is_active ? "نشط" : "معطل"}
                      </span>
                      {customer.must_change_password && (
                        <small className="customer-password-pending">بانتظار تغيير كلمة المرور</small>
                      )}
                    </td>
                    <td>{dateLabel(customer.last_login_at)}</td>
                    <td>{dateLabel(customer.created_at)}</td>
                    <td>
                      <div className="customer-admin-actions">
                        <button type="button" onClick={() => openEdit(customer)} disabled={busyId === customer.id}>
                          تعديل
                        </button>
                        <button type="button" onClick={() => void resetPassword(customer)} disabled={busyId === customer.id}>
                          {busyId === customer.id ? "جارٍ…" : "إعادة تعيين"}
                        </button>
                        <button
                          type="button"
                          className={customer.is_active ? "is-danger" : "is-positive"}
                          onClick={() => void toggleActivation(customer)}
                          disabled={busyId === customer.id}
                        >
                          {customer.is_active ? "تعطيل" : "تفعيل"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="customer-admin-footnote">
        كلمات المرور المؤقتة لا تُخزّن كنص واضح. تُعرض للمسؤول مرة واحدة فقط، وتُبطل الجلسات الحالية،
        ويُطلب من العميل استبدالها قبل استخدام مسبار.
      </p>

      {createOpen && (
        <div className="customer-modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setCreateOpen(false);
        }}>
          <section className="customer-modal" role="dialog" aria-modal="true" aria-labelledby="customer-form-title">
            <header className="customer-modal-head">
              <div>
                <span>بيانات الحساب</span>
                <h2 id="customer-form-title">{editing ? "تعديل بيانات العميل" : "إنشاء حساب عميل"}</h2>
              </div>
              <button type="button" aria-label="إغلاق" onClick={() => setCreateOpen(false)}>×</button>
            </header>
            <form onSubmit={submitCustomer} className="customer-modal-form">
              <label>
                <span>اسم العميل</span>
                <input
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  minLength={2}
                  maxLength={120}
                  required
                  autoComplete="name"
                />
              </label>
              <label>
                <span>البريد الإلكتروني</span>
                <input
                  type="email"
                  dir="ltr"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  maxLength={254}
                  required
                  autoComplete="email"
                />
              </label>
              {!editing && (
                <p className="customer-modal-note">
                  سيُنشأ للحساب رمز مرور مؤقت تلقائيًا. يجب على العميل تغييره عند أول تسجيل دخول.
                </p>
              )}
              {error && <div className="customer-admin-alert is-error" role="alert">{error}</div>}
              <div className="customer-modal-actions">
                <button type="button" className="customer-modal-cancel" onClick={() => setCreateOpen(false)}>
                  إلغاء
                </button>
                <button type="submit" className="customer-admin-primary" disabled={busyId !== null}>
                  {busyId ? "جارٍ الحفظ…" : editing ? "حفظ التعديلات" : "إنشاء الحساب"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {issuedPassword && (
        <div className="customer-modal-backdrop">
          <section className="customer-modal customer-credential-modal" role="dialog" aria-modal="true" aria-labelledby="issued-password-title">
            <header className="customer-modal-head">
              <div>
                <span>{issuedPassword.action === "created" ? "تم إنشاء الحساب" : "تم إصدار كلمة مرور جديدة"}</span>
                <h2 id="issued-password-title">بيانات دخول مؤقتة</h2>
              </div>
              <button type="button" aria-label="إغلاق" onClick={() => setIssuedPassword(null)}>×</button>
            </header>
            <p className="customer-credential-intro">
              الحساب: <strong>{issuedPassword.displayName}</strong>
              <br />
              البريد: <bdi dir="ltr">{issuedPassword.email}</bdi>
            </p>
            <label className="customer-credential-field">
              <span>كلمة المرور المؤقتة · تظهر مرة واحدة</span>
              <input readOnly dir="ltr" value={issuedPassword.password} onFocus={(event) => event.currentTarget.select()} />
            </label>
            <button type="button" className="customer-admin-primary customer-copy-button" onClick={() => void copyIssuedPassword()}>
              نسخ كلمة المرور
            </button>
            {copyStatus && <p className="customer-copy-status" role="status">{copyStatus}</p>}
            <p className="customer-modal-note">
              سلّم كلمة المرور للعميل مباشرة عبر قناة آمنة، ولا ترسلها في مجموعة عامة. بعد الدخول سيُطلب منه تعيين كلمة مرور شخصية جديدة.
            </p>
            <div className="customer-modal-actions">
              <button type="button" className="customer-admin-primary" onClick={() => {
                setIssuedPassword(null);
                setCopyStatus("");
              }}>
                انتهيت
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
