import type { EquipmentSummary, HealthResponse } from "../types";
import {
  BoltIcon,
  ChevronLeftIcon,
  EngineIcon,
  GaugeIcon,
  ShieldIcon,
  SparkIcon,
  TruckIcon,
  WrenchIcon,
} from "./Icons";

interface Props {
  equipment: EquipmentSummary[];
  health: HealthResponse | null;
  loading: boolean;
  busy: boolean;
  error: string | null;
  apiUrl: string;
  onStart: (equipmentModel: string) => void;
  onRetry: () => void;
}

function EquipmentGlyph({ name }: { name: string }) {
  if (/siemens|panel|لوحة/i.test(name)) return <BoltIcon size={26} />;
  if (/320|excavator|حفار/i.test(name)) return <TruckIcon size={26} />;
  return <EngineIcon size={26} />;
}

export function HomeScreen({
  equipment,
  health,
  loading,
  busy,
  error,
  apiUrl,
  onStart,
  onRetry,
}: Props) {
  return (
    <div className="app-shell home-shell">
      <header className="home-top">
        <div className="brand">
          <span className="brand-mark">
            <ShieldIcon size={22} />
          </span>
          <span className="brand-text">
            <strong>المساعد الصناعي</strong>
            <small>SPATIAL AI · FIELD</small>
          </span>
        </div>
        <span className="version-chip">MVP 0.1</span>
      </header>

      <main className="home-main">
        <section className="hero">
          <div className="hero-eyebrow">
            <SparkIcon size={15} />
            صيانة ميدانية بلا هلوسة
          </div>
          <h1>
            انظر إلى القطعة.
            <br />
            <span>واسأل بالعربية.</span>
          </h1>
          <p className="hero-copy">
            حدد القطعة بصريًا، أكمل بوابة العزل، واحصل على خطوات وعزم شد
            <strong> من مصدر موثق فقط</strong> — بصوت عربي وخطوات واحدة في كل مرة.
          </p>

          <div className="hero-metrics">
            <div>
              <strong>{health ? health.components : "—"}</strong>
              <span>قطعة موثقة</span>
            </div>
            <div>
              <strong>{health ? health.equipment : "—"}</strong>
              <span>معدات</span>
            </div>
            <div>
              <strong>0</strong>
              <span>قيم مُخمّنة</span>
            </div>
          </div>
        </section>

        {error && (
          <div className="error-card" role="alert">
            <div>
              <strong>تعذر تحميل البيانات</strong>
              <p>{error}</p>
            </div>
            <button className="ghost-btn" onClick={onRetry}>
              إعادة المحاولة
            </button>
          </div>
        )}

        <div className="sample-banner">
          <ShieldIcon size={18} />
          <p>
            قاعدة المعرفة الحالية <strong>بيانات عرض تجريبية</strong> وليست كتيب صيانة رسميًا.
            لا تستخدمها في صيانة معدات حقيقية.
          </p>
        </div>

        <section className="section">
          <div className="section-head">
            <h2>اختر المعدة</h2>
            <span className="section-meta">
              {loading ? "جارٍ التحميل…" : `${equipment.length} معدات متاحة`}
            </span>
          </div>

          <div className="equipment-list">
            {loading &&
              [0, 1, 2].map((index) => (
                <div className="equipment-card skeleton" key={index}>
                  <span className="skeleton-icon" />
                  <div className="skeleton-lines">
                    <span />
                    <span />
                  </div>
                </div>
              ))}

            {!loading &&
              equipment.map((item) => (
                <button
                  key={item.equipment_family}
                  className="equipment-card"
                  onClick={() => onStart(item.equipment_family)}
                  disabled={busy}
                >
                  <span className="equipment-icon">
                    <EquipmentGlyph name={item.equipment_family} />
                  </span>
                  <span className="equipment-info">
                    <strong>{item.equipment_family}</strong>
                    <small>{item.manufacturer}</small>
                    <span className="equipment-tags">
                      <span>{item.component_count} قطع</span>
                      <span className="sample-tag">بيانات تجريبية</span>
                    </span>
                  </span>
                  <span className="equipment-arrow">
                    <ChevronLeftIcon size={22} />
                  </span>
                </button>
              ))}

            {!loading && !equipment.length && !error && (
              <div className="empty-card">
                <GaugeIcon size={28} />
                <p>لا توجد معدات في قاعدة المعرفة.</p>
              </div>
            )}
          </div>
        </section>

        <section className="how">
          <h2>كيف تعمل الجلسة</h2>
          <ol className="how-list">
            <li>
              <span className="how-num">1</span>
              <div>
                <strong>التحديد البصري</strong>
                <p>وجّه الكاميرا نحو القطعة، أو ابحث برقمها إذا كانت الرؤية غير واضحة.</p>
              </div>
            </li>
            <li>
              <span className="how-num">2</span>
              <div>
                <strong>بوابة السلامة LOTO</strong>
                <p>لن تظهر أي خطوة فك قبل تأكيد كل بنود العزل على الخادم — لا يكفي قول «تم».</p>
              </div>
            </li>
            <li>
              <span className="how-num">3</span>
              <div>
                <strong>خطوة واحدة في كل مرة</strong>
                <p>اسأل صوتيًا: «الخطوة التالية»، «أعد الخطوة»، أو «كم العزم؟».</p>
              </div>
            </li>
          </ol>
        </section>

        <footer className="home-footer">
          <div className="footer-chips">
            <span className={`chip ${health ? "chip-green" : "chip-dim"}`}>
              {health ? "الخادم متصل" : "الخادم غير متصل"}
            </span>
            <span className="chip">
              <WrenchIcon size={13} />
              {health?.vision_provider === "openai" ? "VLM حقيقي" : "رؤية تجريبية"}
            </span>
          </div>
          <code dir="ltr">{apiUrl}</code>
        </footer>
      </main>
    </div>
  );
}
