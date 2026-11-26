import type { AssistantResponse } from "../types";
import {
  AlertIcon,
  CheckCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  RotateCcwIcon,
  VolumeIcon,
  WrenchIcon,
} from "./Icons";

interface Props {
  session: AssistantResponse;
  busy: boolean;
  onStep: (action: "next" | "prev" | "repeat") => void;
  onSpeak: (text: string) => void;
  readOnly?: boolean;
}

export function StepCard({ session, busy, onStep, onSpeak, readOnly = false }: Props) {
  const step = session.current_step;

  if (session.state === "COMPLETED") {
    return (
      <section className="completion-card">
        <span className="completion-icon">
          <CheckCircleIcon size={34} />
        </span>
        <h2>تم إنجاز جميع الخطوات</h2>
        <p>{step?.verification_ar || "راجع المنطقة بصريًا وتأكد من عدم وجود تسريب قبل إغلاق الجلسة."}</p>
        {session.manual_reference && (
          <span className="source-line">
            المرجع: <bdi dir="ltr">{session.manual_reference.document_id}</bdi> صفحة{" "}
            {session.manual_reference.page_number}
          </span>
        )}
      </section>
    );
  }

  if (!step) return null;

  const progress = Math.round((step.step_number / step.total_steps) * 100);

  return (
    <section className="step-card">
      <div className="step-progress">
        <div className="step-progress-head">
          <span>
            الخطوة <strong>{step.step_number}</strong> من {step.total_steps}
          </span>
          <span className="cue-chip" style={{ color: step.ar_visual_cue.color_hex }}>
            {step.ar_visual_cue.label_ar}
          </span>
        </div>
        <div className="progress-track">
          <span style={{ width: `${progress}%` }} />
        </div>
      </div>

      <p className="step-instruction">{step.instruction_ar}</p>

      <div className="step-tool">
        <WrenchIcon size={17} />
        <span>الأداة: {step.tool_required_ar}</span>
      </div>

      {step.warning_ar && (
        <div className="step-warning">
          <AlertIcon size={17} />
          <span>{step.warning_ar}</span>
        </div>
      )}

      {step.torque_spec && (
        <div className="torque-card">
          <div className="torque-main">
            <span className="torque-label">{step.torque_spec.verified_from_manual ? "عزم الشد المعتمد" : "قيمة عزم تجريبية — غير معتمدة"}</span>
            <div className="torque-value">
              <strong dir="ltr">{step.torque_spec.value_nm}</strong>
              <span>N·m</span>
              <small dir="ltr">({step.torque_spec.value_lbft} lb-ft)</small>
            </div>
          </div>
          {step.torque_spec.tightening_sequence && (
            <p className="torque-sequence">{step.torque_spec.tightening_sequence}</p>
          )}
          <div className="torque-source">
            <span>المصدر</span>
            <bdi dir="ltr">{step.torque_spec.source_document_id}</bdi>
            <span>صفحة {step.torque_spec.source_page}</span>
            {step.torque_spec.source_status !== "verified" && (
              <span className="sample-tag">بيانات تجريبية</span>
            )}
          </div>
        </div>
      )}

      {step.verification_ar && (
        <div className="verification-note">
          <strong>التحقق بعد التنفيذ:</strong> {step.verification_ar}
        </div>
      )}

      {!readOnly && <div className="step-actions">
        <button
          className="step-btn secondary"
          onClick={() => onStep("prev")}
          disabled={busy || step.step_number <= 1}
          aria-label="الخطوة السابقة"
        >
          <ChevronRightIcon size={22} />
          السابق
        </button>

        <button
          className="step-btn ghost"
          onClick={() => onStep("repeat")}
          disabled={busy}
          aria-label="إعادة الخطوة"
        >
          <RotateCcwIcon size={19} />
          إعادة
        </button>

        <button
          className="step-btn primary"
          onClick={() => onStep("next")}
          disabled={busy}
        >
          {step.step_number >= step.total_steps ? "إنهاء الإجراء" : "الخطوة التالية"}
          <ChevronLeftIcon size={22} />
        </button>
      </div>}

      {readOnly && (
        <p className="customer-readonly-note">يمكنك الاطلاع على الإرشادات. تنفيذ الخطوات واعتمادها مخصص للفنيين المعتمدين.</p>
      )}

      <button
        className="speak-inline"
        onClick={() => onSpeak(step.instruction_ar)}
        aria-label="قراءة الخطوة صوتيًا"
      >
        <VolumeIcon size={17} />
        اقرأ الخطوة صوتيًا
      </button>

      {session.manual_reference && (
        <div className="manual-ref">
          <span>المرجع الفني</span>
          <bdi dir="ltr">{session.manual_reference.document_id}</bdi>
          <span>صفحة {session.manual_reference.page_number}</span>
          <span className="manual-section">{session.manual_reference.section_title}</span>
        </div>
      )}
    </section>
  );
}
