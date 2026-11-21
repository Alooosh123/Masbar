import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AuditEntry } from "../types";
import { CloseIcon, HistoryIcon } from "./Icons";

interface Props {
  sessionId: string;
  onClose: () => void;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("ar-SA", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function AuditSheet({ sessionId, onClose }: Props) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .audit(sessionId)
      .then((response) => {
        if (!cancelled) setEntries(response.entries);
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "تعذر تحميل السجل.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return (
    <div className="sheet-backdrop" onClick={onClose} role="presentation">
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="سجل تدقيق الجلسة"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="sheet-head">
          <div>
            <h2>سجل تدقيق الجلسة</h2>
            <p dir="ltr">{sessionId}</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="إغلاق">
            <CloseIcon size={20} />
          </button>
        </header>

        <div className="audit-note">
          <HistoryIcon size={16} />
          <span>
            كل تحديد وتأكيد عزل وسؤال يُسجّل تلقائيًا على الخادم بوقت الحدوث.
          </span>
        </div>

        <div className="audit-list">
          {entries === null && !error && <div className="search-state">جارٍ تحميل السجل…</div>}
          {error && <div className="search-state error">{error}</div>}
          {entries?.length === 0 && <div className="search-state">لا توجد أحداث بعد.</div>}

          {entries?.map((entry) => (
            <div className="audit-entry" key={entry.id}>
              <span className="audit-dot" />
              <div className="audit-body">
                <div className="audit-meta">
                  <code dir="ltr">{entry.event}</code>
                  <time dateTime={entry.timestamp}>{formatTime(entry.timestamp)}</time>
                </div>
                <p>{entry.detail_ar}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
