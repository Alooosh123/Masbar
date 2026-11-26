import { useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { ConversationDetail, ConversationSummary } from "../types";
import { CloseIcon } from "./Icons";

interface Props {
  onClose: () => void;
  onSelect: (detail: ConversationDetail) => void;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "تعذر تحميل سجل المحادثات.";
}

function dateText(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ar-YE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function ConversationHistory({ onClose, onSelect }: Props) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const result = await api.conversations();
      setItems(result.conversations);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function openConversation(item: ConversationSummary) {
    setBusyId(item.id);
    setError("");
    try {
      const result = await api.getConversation(item.id);
      onSelect(result);
      onClose();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusyId(null);
    }
  }

  async function removeConversation(item: ConversationSummary) {
    const confirmed = window.confirm(`حذف محادثة "${item.title}" نهائيًا؟`);
    if (!confirmed) return;
    setBusyId(item.id);
    setError("");
    try {
      await api.deleteConversation(item.id);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="conversation-history-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside className="conversation-history-panel" dir="rtl" role="dialog" aria-modal="true" aria-labelledby="conversation-history-title">
        <header className="conversation-history-head">
          <div>
            <span className="customer-admin-kicker">ذاكرة الحساب</span>
            <h2 id="conversation-history-title">سجل المحادثات</h2>
            <p>محادثاتك محفوظة في حسابك ويمكنك استكمالها لاحقًا.</p>
          </div>
          <button type="button" className="chat-icon-btn" onClick={onClose} aria-label="إغلاق سجل المحادثات">
            <CloseIcon size={20} />
          </button>
        </header>

        {error && <div className="customer-admin-alert is-error" role="alert">{error}</div>}

        {loading ? (
          <div className="conversation-history-empty" role="status">جارٍ تحميل محادثاتك…</div>
        ) : items.length === 0 ? (
          <div className="conversation-history-empty">
            <strong>لا توجد محادثات محفوظة حتى الآن</strong>
            <span>ابدأ محادثة جديدة وستظهر هنا تلقائيًا.</span>
          </div>
        ) : (
          <div className="conversation-history-list">
            {items.map((item) => (
              <article className="conversation-history-item" key={item.id}>
                <button
                  type="button"
                  className="conversation-history-open"
                  onClick={() => void openConversation(item)}
                  disabled={busyId !== null}
                >
                  <strong>{item.title || "محادثة جديدة"}</strong>
                  <span>{item.preview}</span>
                  <small>{dateText(item.updated_at)} · {item.message_count} رسالة</small>
                </button>
                <button
                  type="button"
                  className="conversation-history-delete"
                  onClick={() => void removeConversation(item)}
                  disabled={busyId !== null}
                  aria-label={`حذف محادثة ${item.title}`}
                  title="حذف المحادثة"
                >
                  حذف
                </button>
                {busyId === item.id && <span className="conversation-history-loading">جارٍ…</span>}
              </article>
            ))}
          </div>
        )}

        <footer className="conversation-history-foot">
          لا تُحفظ الصور الأصلية؛ يُحفظ نص المحادثة وإشارة إلى الرسائل التي تضمنت صورة.
        </footer>
      </aside>
    </div>
  );
}
