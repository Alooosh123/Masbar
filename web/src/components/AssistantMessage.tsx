import type { AssistantResponse } from "../types";
import { SparkIcon, VolumeIcon } from "./Icons";

const INTENT_LABELS: Record<string, string> = {
  IDENTIFY: "تحديد",
  NEXT_STEP: "الخطوة التالية",
  REPEAT_STEP: "إعادة",
  PREV_STEP: "السابق",
  TORQUE_QUERY: "عزم الشد",
  PART_NUMBER_QUERY: "رقم القطعة",
  SAFETY_QUERY: "السلامة",
  CONFIRM_LOTO: "العزل",
  HELP: "مساعدة",
  UNKNOWN: "غير مفهوم",
};

interface Props {
  session: AssistantResponse;
  onSpeak: (text: string) => void;
}

export function AssistantMessage({ session, onSpeak }: Props) {
  if (!session.assistant_message_ar) return null;
  const intent = session.last_intent ? INTENT_LABELS[session.last_intent] : null;

  return (
    <section className="assistant-card">
      <header className="assistant-head">
        <span className="assistant-avatar">
          <SparkIcon size={17} />
        </span>
        <strong>المساعد</strong>
        {intent && <span className="intent-chip">{intent}</span>}
        <button
          className="icon-btn small"
          onClick={() => onSpeak(session.assistant_message_ar)}
          aria-label="إعادة قراءة رد المساعد"
        >
          <VolumeIcon size={17} />
        </button>
      </header>

      <p>{session.assistant_message_ar}</p>

      {session.next_actions_ar.length > 0 && (
        <div className="next-actions">
          {session.next_actions_ar.map((action) => (
            <span key={action}>{action}</span>
          ))}
        </div>
      )}
    </section>
  );
}
