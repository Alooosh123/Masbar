import type { IdentifiedComponent } from "../types";
import { ShieldIcon } from "./Icons";

const SOURCE_LABELS: Record<string, string> = {
  MANUAL: "اختيار يدوي",
  TEXT_SEARCH: "بحث نصي",
  VISION_MOCK: "رؤية تجريبية",
  VISION_VLM: "تحليل VLM",
};

interface Props {
  component: IdentifiedComponent;
}

export function ComponentCard({ component }: Props) {
  const confidence = Math.round(component.confidence_score * 100);
  const isSample = component.verification_status !== "verified";

  return (
    <section className="component-card">
      <div className="component-head">
        <div className="component-title">
          <span className="part-number" dir="ltr">
            {component.part_number}
          </span>
          <h2>{component.arabic_name}</h2>
          <p dir="ltr">{component.english_name}</p>
        </div>
        <div className="confidence" aria-label={`نسبة الثقة ${confidence}%`}>
          <strong>{confidence}%</strong>
          <span>ثقة</span>
        </div>
      </div>

      <div className="confidence-track">
        <span style={{ width: `${confidence}%` }} />
      </div>

      <div className="component-meta">
        <span className="chip">
          {SOURCE_LABELS[component.identification_source] || component.identification_source}
        </span>
        {isSample ? (
          <span className="chip chip-amber">
            <ShieldIcon size={13} />
            بيانات تجريبية
          </span>
        ) : (
          <span className="chip chip-green">موثق من الكتيب</span>
        )}
      </div>
    </section>
  );
}
