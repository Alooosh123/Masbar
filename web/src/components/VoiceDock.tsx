import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { createArabicRecognizer, recognitionSupported } from "../lib/speech";
import { CloseIcon, MicIcon, StopIcon } from "./Icons";

interface Props {
  busy: boolean;
  onAsk: (transcript: string) => void;
}

export function VoiceDock({ busy, onAsk }: Props) {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [textMode, setTextMode] = useState(!recognitionSupported());
  const [draft, setDraft] = useState("");
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.abort();
      } catch {
        /* ignore */
      }
    };
  }, []);

  function startListening() {
    setError(null);
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }

    const recognizer = createArabicRecognizer();
    if (!recognizer) {
      setTextMode(true);
      return;
    }

    recognitionRef.current = recognizer;
    recognizer.onstart = () => {
      setListening(true);
      setError(null);
    };
    recognizer.onresult = (event: any) => {
      const text = event.results?.[0]?.[0]?.transcript?.trim();
      if (text) {
        setTranscript(text);
        onAsk(text);
      }
    };
    recognizer.onerror = (event: any) => {
      const code = event?.error;
      const messages: Record<string, string> = {
        "not-allowed": "تم رفض إذن الميكروفون. اسمح بالوصول من إعدادات المتصفح.",
        "no-speech": "لم أسمع صوتًا. حاول مرة أخرى في مكان أقل ضوضاءً.",
        network: "تعذر الاتصال بخدمة التعرف الصوتي.",
        "audio-capture": "لم يتم العثور على ميكروفون.",
      };
      setError(messages[code] || "تعذر التعرف على الصوت. جرّب الكتابة.");
      setListening(false);
    };
    recognizer.onend = () => setListening(false);

    try {
      recognizer.start();
    } catch {
      setError("تعذر بدء الميكروفون.");
      setListening(false);
    }
  }

  function submitText(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setTranscript(text);
    setDraft("");
    onAsk(text);
  }

  return (
    <div className="voice-dock">
      <div className="voice-dock-inner">
        {transcript && (
          <div className="transcript-chip">
            <span>سمعت:</span>
            <p>{transcript}</p>
            <button onClick={() => setTranscript("")} aria-label="مسح النص">
              <CloseIcon size={14} />
            </button>
          </div>
        )}

        {error && <div className="voice-error">{error}</div>}

        {textMode ? (
          <form className="voice-text-form" onSubmit={submitText}>
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="اكتب طلبك للمساعد…"
              dir="auto"
              aria-label="نص الطلب"
            />
            <button type="submit" disabled={busy || !draft.trim()}>
              إرسال
            </button>
          </form>
        ) : (
          <div className="voice-main">
            <button
              className={`mic-btn ${listening ? "is-listening" : ""}`}
              onClick={startListening}
              disabled={busy}
              aria-label={listening ? "إيقاف الاستماع" : "بدء التحدث"}
            >
              <span className="mic-ring" />
              {listening ? <StopIcon size={24} /> : <MicIcon size={28} />}
            </button>

            <div className="voice-copy">
              <strong>{busy ? "جارٍ التنفيذ…" : listening ? "جاري الاستماع…" : "اضغط وتحدث"}</strong>
              <span>
                {listening
                  ? "قل: الخطوة التالية، أعد الخطوة، كم العزم؟"
                  : "المساعد يفهم اللهجة العربية والمصطلحات الإنجليزية"}
              </span>
            </div>

            <button className="text-toggle" onClick={() => setTextMode(true)}>
              كتابة
            </button>
          </div>
        )}

        {textMode && recognitionSupported() && (
          <button className="voice-switch" onClick={() => setTextMode(false)}>
            العودة إلى الصوت
          </button>
        )}
      </div>
    </div>
  );
}
