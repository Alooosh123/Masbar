import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import {
  AlertIcon,
  CameraIcon,
  CloseIcon,
  RotateCwIcon,
} from "./Icons";

interface Props {
  onCapture: (imageBase64: string, contextText?: string) => void;
  onClose: () => void;
}

function cameraErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") {
      return "تم رفض إذن الكاميرا. اسمح بالوصول إلى الكاميرا من إعدادات المتصفح ثم أعد المحاولة.";
    }
    if (error.name === "NotFoundError") {
      return "لم أجد كاميرا متصلة بهذا الجهاز.";
    }
    if (error.name === "NotReadableError") {
      return "الكاميرا مشغولة بتطبيق آخر. أغلق التطبيق الآخر ثم أعد المحاولة.";
    }
  }
  return "تعذر تشغيل الكاميرا. تحقق من الإذن ومن اتصال الكاميرا.";
}

export function ChatCamera({ onCapture, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const [attempt, setAttempt] = useState(0);
  const [preview, setPreview] = useState<string | null>(null);
  const [contextText, setContextText] = useState("");
  const [selectedFileName, setSelectedFileName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const submittedRef = useRef(false);
  const capturedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let stream: MediaStream | null = null;
    setReady(false);
    setError(null);

    if (preview) {
      return () => { cancelled = true; };
    }

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("المتصفح لا يدعم الوصول إلى الكاميرا في هذه الصفحة.");
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facing },
            width: { ideal: 1280 },
            height: { ideal: 960 },
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => undefined);
        }
        setReady(true);
      } catch (err) {
        if (!cancelled) setError(cameraErrorMessage(err));
      }
    }

    void start();

    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
      if (streamRef.current === stream) streamRef.current = null;
      if (videoRef.current?.srcObject === stream) videoRef.current.srcObject = null;
    };
  }, [facing, attempt, preview]);

  const capture = useCallback(
    () => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (capturedRef.current) return;
      if (!video || !canvas || !ready || video.videoWidth === 0) {
        setError("الكاميرا لم تجهز بعد. انتظر لحظة ثم أعد المحاولة.");
        return;
      }

      const maxSide = 1280;
      const scale = Math.min(
        1,
        maxSide / Math.max(video.videoWidth, video.videoHeight)
      );
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);

      const context = canvas.getContext("2d");
      if (!context) {
        setError("تعذر تجهيز الصورة من الكاميرا.");
        return;
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", 0.82);
      capturedRef.current = true;
      submittedRef.current = false;
      setPreview(dataUrl);
      setReady(false);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      video.srcObject = null;
    },
    [ready]
  );

  const submitPreview = useCallback(() => {
    if (!preview || submittedRef.current) return;
    submittedRef.current = true;
    onCapture(preview, contextText.trim());
  }, [onCapture, preview, contextText]);

  const retake = useCallback(() => {
    capturedRef.current = false;
    submittedRef.current = false;
    setPreview(null);
    setAttempt((value) => value + 1);
  }, []);

  function selectImageFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("اختر ملف صورة فقط.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError("حجم الصورة أكبر من 5 ميجابايت. اختر صورة أصغر.");
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => setError("تعذر قراءة ملف الصورة. اختر الملف مجددًا.");
    reader.onload = () => {
      if (typeof reader.result !== "string") {
        setError("تعذر تحميل الصورة المختارة.");
        return;
      }
      capturedRef.current = true;
      submittedRef.current = false;
      setPreview(reader.result);
      setSelectedFileName(file.name);
      setContextText("");
      setError(null);
      setReady(false);
    };
    reader.readAsDataURL(file);
  }

  return (
    <div
      className="chat-camera"
      role="dialog"
      aria-modal="true"
      aria-label="كاميرا المحادثة"
    >
      <header className="chat-camera-head">
        <div>
          <strong>كاميرا المحادثة</strong>
          <span>{preview ? "راجع الصورة قبل إرسالها" : ready ? "الكاميرا جاهزة — وجّهها نحو المعدة" : "جارٍ تشغيل الكاميرا…"}</span>
        </div>
        <button
          type="button"
          className="chat-icon-btn"
          onClick={onClose}
          aria-label="إغلاق الكاميرا"
        >
          <CloseIcon size={22} />
        </button>
      </header>

      <div className="chat-camera-stage">
        {preview ? (
          <img className="chat-camera-preview" src={preview} alt="معاينة الصورة للمعدة" />
        ) : (
          <video
            ref={videoRef}
            className={`chat-camera-video ${ready ? "is-ready" : ""}`}
            playsInline
            muted
            autoPlay
          />
        )}

        {!preview && !ready && !error && (
          <div className="chat-camera-state">
            <span className="chat-spinner large" />
            <p>جارٍ طلب إذن الكاميرا…</p>
          </div>
        )}

        {!preview && error && (
          <div className="chat-camera-state is-error">
            <AlertIcon size={28} />
            <p>{error}</p>
            <button
              type="button"
              className="chat-camera-retry"
              onClick={() => setAttempt((value) => value + 1)}
            >
              إعادة المحاولة
            </button>
          </div>
        )}

        {!preview && ready && !error && (
          <div className="chat-camera-frame" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </div>
        )}
      </div>

      {preview && (
        <div className="chat-image-context">
          {selectedFileName && <small>الصورة المختارة: {selectedFileName}</small>}
          <label htmlFor="chat-image-context">اشرح ما تعرفه عن الصورة أو المشكلة (اختياري)</label>
          <textarea id="chat-image-context" value={contextText} onChange={(event) => setContextText(event.target.value)} placeholder="مثلاً: هذه مضخة، أسمع صوتًا غير طبيعي عند التشغيل، ولا أعرف رقم الطراز…" rows={3} dir="auto" />
        </div>
      )}
      <div className="chat-camera-actions">
        {preview ? (
          <>
            <button type="button" className="chat-capture-btn" onClick={retake}>إعادة الالتقاط</button>
            <button type="button" className="chat-capture-btn primary" onClick={submitPreview}>تأكيد الصورة وإرسالها</button>
          </>
        ) : (
          <button type="button" className="chat-capture-btn" onClick={() => fileInputRef.current?.click()}>اختيار صورة من الجهاز</button>\n          <button type="button" className="chat-capture-btn primary" onClick={capture} disabled={!ready}>
            <CameraIcon size={20} />
            التقاط الصورة
          </button>
        )}
      </div>

      <footer className="chat-camera-foot">
        <span>التقاط صورة لتحديد المعدات المدعومة. إذا لم تكن واضحة، سيطلب مسبار إعادة التصوير.</span>
        {!preview && <button
          type="button"
          className="chat-camera-flip"
          onClick={() =>
            setFacing((current) => (current === "environment" ? "user" : "environment"))
          }
          disabled={!ready}
        >
          <RotateCwIcon size={17} />
          تبديل الكاميرا
        </button>}
      </footer>

      <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={selectImageFile} />\n      <canvas ref={canvasRef} hidden />
    </div>
  );
}
