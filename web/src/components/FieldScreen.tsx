import { useState } from "react";
import type { AssistantResponse, SessionState } from "../types";
import { AssistantMessage } from "./AssistantMessage";
import { AuditSheet } from "./AuditSheet";
import { CameraView } from "./CameraView";
import { ComponentCard } from "./ComponentCard";
import { ManualSearch } from "./ManualSearch";
import { SafetyPanel } from "./SafetyPanel";
import { StepCard } from "./StepCard";
import { VoiceDock } from "./VoiceDock";
import {
  AlertIcon,
  BackIcon,
  CloseIcon,
  HistoryIcon,
  SearchIcon,
  ShieldIcon,
  SparkIcon,
  VolumeIcon,
  VolumeOffIcon,
} from "./Icons";

const STATE_LABELS: Record<SessionState, string> = {
  CREATED: "بانتظار التحديد",
  IDENTIFIED: "تم التحديد",
  AWAITING_LOTO: "بوابة السلامة مغلقة",
  READY: "جاهز للتنفيذ",
  IN_PROGRESS: "قيد التنفيذ",
  COMPLETED: "مكتمل",
};

interface Props {
  session: AssistantResponse;
  busy: boolean;
  error: string | null;
  autoSpeak: boolean;
  onToggleSpeak: () => void;
  onBack: () => void;
  onDismissError: () => void;
  onCapture: (imageBase64: string | null, transcript?: string) => void;
  onSelectCandidate: (partNumber: string) => void;
  onConfirmLoto: (confirmedIds: string[]) => void;
  onStep: (action: "next" | "prev" | "repeat") => void;
  onAsk: (transcript: string) => void;
  onSpeak: (text: string) => void;
  onRestart: () => void;
}

export function FieldScreen({
  session,
  busy,
  error,
  autoSpeak,
  onToggleSpeak,
  onBack,
  onDismissError,
  onCapture,
  onSelectCandidate,
  onConfirmLoto,
  onStep,
  onAsk,
  onSpeak,
  onRestart,
}: Props) {
  const [manualOpen, setManualOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const component = session.identified_component;
  const waitingSafety = Boolean(
    component &&
      session.safety_lockout?.loto_required &&
      !session.safety_lockout.acknowledged_by_technician
  );
  const readyForSteps = Boolean(component && !waitingSafety);

  return (
    <div className="app-shell field-shell">
      <header className="field-hud">
        <button className="icon-btn" onClick={onBack} aria-label="العودة للرئيسية">
          <BackIcon size={21} />
        </button>

        <div className="hud-title">
          <strong>{session.equipment_model}</strong>
          <span className={`state-dot state-${session.state.toLowerCase()}`}>
            {STATE_LABELS[session.state]}
          </span>
        </div>

        <div className="hud-actions">
          <button
            className={`icon-btn ${autoSpeak ? "is-active" : ""}`}
            onClick={onToggleSpeak}
            aria-label={autoSpeak ? "إيقاف القراءة التلقائية" : "تشغيل القراءة التلقائية"}
          >
            {autoSpeak ? <VolumeIcon size={20} /> : <VolumeOffIcon size={20} />}
          </button>
          <button
            className="icon-btn"
            onClick={() => setAuditOpen(true)}
            aria-label="سجل الجلسة"
          >
            <HistoryIcon size={20} />
          </button>
          <button
            className="icon-btn"
            onClick={() => setManualOpen(true)}
            aria-label="البحث اليدوي"
          >
            <SearchIcon size={20} />
          </button>
        </div>
      </header>

      <CameraView session={session} busy={busy} onCapture={onCapture} />

      {error && (
        <div className="field-error" role="alert">
          <AlertIcon size={18} />
          <span>{error}</span>
          <button onClick={onDismissError} aria-label="إغلاق الخطأ">
            <CloseIcon size={16} />
          </button>
        </div>
      )}

      <main className="field-content">
        {session.requires_closer_inspection && (
          <section className="inspection-card">
            <span className="inspection-icon">
              <AlertIcon size={20} />
            </span>
            <div>
              <strong>الرؤية غير كافية</strong>
              <p>{session.inspection_prompt_ar}</p>
            </div>
          </section>
        )}

        {!component && !session.requires_closer_inspection && (
          <section className="start-card">
            <h2>ابدأ تحديد القطعة</h2>
            <p>
              وجّه الكاميرا نحو القطعة ثم اضغط زر الالتقاط. إن كانت الرؤية غير واضحة،
              ابحث برقم القطعة أو اسمها.
            </p>
            <div className="start-actions">
              <button className="primary-btn" onClick={() => onCapture(null)} disabled={busy}>
                <SparkIcon size={18} />
                تحديد تجريبي
              </button>
              <button className="ghost-btn" onClick={() => setManualOpen(true)}>
                <SearchIcon size={18} />
                بحث يدوي
              </button>
            </div>
          </section>
        )}

        {session.retrieval_candidates.length > 0 && (
          <section className="candidates-card">
            <h3>نتائج محتملة — اختر القطعة الصحيحة</h3>
            <div className="candidate-list">
              {session.retrieval_candidates.map((candidate) => (
                <button
                  key={candidate.part_number}
                  className="candidate"
                  onClick={() => onSelectCandidate(candidate.part_number)}
                  disabled={busy}
                >
                  <span className="candidate-main">
                    <bdi className="candidate-part" dir="ltr">
                      {candidate.part_number}
                    </bdi>
                    <strong>{candidate.arabic_name}</strong>
                    <small dir="ltr">{candidate.english_name}</small>
                  </span>
                  <span className="candidate-score">{candidate.score}</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {component && <ComponentCard component={component} />}

        {component && session.safety_lockout && (
          <SafetyPanel
            key={`${session.identification_id || session.session_id}-${component.part_number}`}
            protocol={session.safety_lockout}
            busy={busy}
            onConfirm={onConfirmLoto}
          />
        )}

        {waitingSafety && (
          <div className="locked-note">
            <ShieldIcon size={18} />
            <span>خطوات الفك مقفلة على الخادم حتى تأكيد جميع بنود العزل.</span>
          </div>
        )}

        {readyForSteps && (
          <StepCard session={session} busy={busy} onStep={onStep} onSpeak={onSpeak} />
        )}

        {session.state === "COMPLETED" && (
          <div className="completion-actions">
            <button className="primary-btn" onClick={onRestart} disabled={busy}>
              جلسة جديدة
            </button>
            <button className="ghost-btn" onClick={() => setAuditOpen(true)}>
              سجل الجلسة
            </button>
            <button className="ghost-btn" onClick={onBack}>
              العودة للرئيسية
            </button>
          </div>
        )}

        <AssistantMessage session={session} onSpeak={onSpeak} />

        <p className="data-disclaimer">{session.data_disclaimer_ar}</p>
      </main>

      <VoiceDock busy={busy} onAsk={onAsk} />

      {manualOpen && (
        <ManualSearch
          equipmentModel={session.equipment_model}
          busy={busy}
          onSelect={(partNumber) => {
            setManualOpen(false);
            onSelectCandidate(partNumber);
          }}
          onClose={() => setManualOpen(false)}
        />
      )}

      {auditOpen && (
        <AuditSheet
          sessionId={session.session_id}
          onClose={() => setAuditOpen(false)}
        />
      )}
    </div>
  );
}
