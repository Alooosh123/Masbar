import { useState } from "react";
import type { SafetyLockoutProtocol } from "../types";
import { AlertIcon, CheckIcon, ShieldIcon } from "./Icons";

interface Props {
  protocol: SafetyLockoutProtocol;
  busy: boolean;
  onConfirm: (confirmedIds: string[]) => void;
  readOnly?: boolean;
}

export function SafetyPanel({ protocol, busy, onConfirm, readOnly = false }: Props) {
  const [checked, setChecked] = useState<Set<string>>(new Set());

  if (!protocol.loto_required && protocol.warnings_ar.length === 0) return null;

  // Never turn an unverified/demo checklist into a false sense of safety.
  if (protocol.source_status !== "verified") {
    return (
      <section className="safety-panel critical" role="alert">
        <header>
          <span className="safety-icon"><ShieldIcon size={22} /></span>
          <div>
            <h2>إيقاف آمن — معلومات السلامة غير معتمدة</h2>
            <p>لا يمكن فتح بوابة الصيانة أو اعتبار تأكيد الشاشة دليلاً على العزل.</p>
          </div>
        </header>
        <ul className="warning-list">
          {protocol.warnings_ar.map((warning) => (
            <li key={warning}><AlertIcon size={16} /><span>{warning}</span></li>
          ))}
        </ul>
        <p className="gate-hint">
          {protocol.blocked_reason_ar ||
            "لا توجد تعليمات سلامة وعزل مراجعة ومطابقة للمعدة. أوقف العمل حتى يراجع فني مؤهل كتيب الطراز الصحيح."}
        </p>
      </section>
    );
  }

  if (protocol.acknowledged_by_technician) {
    return (
      <div className="safety-strip">
        <CheckIcon size={18} />
        <span>تم توثيق إجراءات العزل (LOTO) لهذه الجلسة وفق المصدر المعتمد.</span>
      </div>
    );
  }

  if (!protocol.loto_required) {
    return (
      <section className="safety-panel warning">
        <header>
          <AlertIcon size={20} />
          <h2>تحذيرات السلامة المعتمدة</h2>
        </header>
        <ul className="warning-list">
          {protocol.warnings_ar.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      </section>
    );
  }

  if (readOnly) {
    return (
      <section className={`safety-panel ${protocol.severity === "CRITICAL" ? "critical" : "warning"}`}>
        <header>
          <span className="safety-icon"><ShieldIcon size={22} /></span>
          <div>
            <h2>متطلبات السلامة (LOTO)</h2>
            <p>راجع هذه المتطلبات مع فني مؤهل. لا يمكن لحساب العميل اعتماد العزل أو فتح خطوات التنفيذ.</p>
          </div>
        </header>
        <ul className="warning-list">
          {protocol.warnings_ar.map((warning) => (
            <li key={warning}><AlertIcon size={16} /><span>{warning}</span></li>
          ))}
        </ul>
        <div className="customer-safety-list">
          <strong>قائمة التحقق التي يجب أن يراجعها الفني:</strong>
          <ul>
            {protocol.checklist.map((item) => <li key={item.id}>{item.label_ar}</li>)}
          </ul>
        </div>
      </section>
    );
  }

  const allChecked =
    protocol.checklist.length > 0 &&
    protocol.checklist.every((item) => checked.has(item.id));

  function toggle(id: string) {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section className={`safety-panel ${protocol.severity === "CRITICAL" ? "critical" : "warning"}`}>
      <header>
        <span className="safety-icon"><ShieldIcon size={22} /></span>
        <div>
          <h2>بوابة السلامة الإلزامية (LOTO)</h2>
          <p>لن تظهر خطوات الصيانة حتى تؤكد كل بند من المصدر المعتمد. التأكيد يُسجَّل في سجل الجلسة.</p>
        </div>
      </header>
      <ul className="warning-list">
        {protocol.warnings_ar.map((warning) => (
          <li key={warning}><AlertIcon size={16} /><span>{warning}</span></li>
        ))}
      </ul>
      <div className="checklist">
        {protocol.checklist.map((item) => {
          const isChecked = checked.has(item.id);
          return (
            <label className={`check-row ${isChecked ? "is-checked" : ""}`} key={item.id}>
              <input type="checkbox" checked={isChecked} onChange={() => toggle(item.id)} />
              <span className="check-box"><CheckIcon size={16} /></span>
              <span className="check-label">{item.label_ar}</span>
            </label>
          );
        })}
      </div>
      <button
        className="confirm-safety-btn"
        disabled={!allChecked || busy || protocol.source_status !== "verified"}
        onClick={() => onConfirm(protocol.checklist.map((item) => item.id))}
      >
        {busy ? "جارٍ التوثيق…" : "أؤكد إتمام جميع إجراءات العزل — متابعة"}
      </button>
      {!allChecked && (
        <p className="gate-hint">
          أكّد جميع البنود ({protocol.checklist.filter((item) => checked.has(item.id)).length}/
          {protocol.checklist.length}) لفتح بوابة السلامة.
        </p>
      )}
    </section>
  );
}
