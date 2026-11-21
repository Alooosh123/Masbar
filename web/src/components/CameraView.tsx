import { useEffect, useRef, useState } from "react";
import type { AssistantResponse } from "../types";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CameraIcon,
  PlugIcon,
  RotateCcwIcon,
  RotateCwIcon,
  SparkIcon,
} from "./Icons";

interface Props {
  session: AssistantResponse;
  busy: boolean;
  onCapture: (imageBase64: string | null, transcript?: string) => void;
}

function CueGlyph({ cueType, size = 26 }: { cueType: string; size?: number }) {
  switch (cueType) {
    case "DISCONNECT_PLUG":
      return <PlugIcon size={size} />;
    case "ROTATE_CCW":
      return <RotateCcwIcon size={size} />;
    case "ROTATE_CW":
      return <RotateCwIcon size={size} />;
    case "PULL_ARROW":
      return <ArrowUpIcon size={size} />;
    case "PUSH_ARROW":
      return <ArrowDownIcon size={size} />;
    default:
      return <SparkIcon size={size} />;
  }
}

export function CameraView({ session, busy, onCapture }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCameraError("المتصفح لا يدعم الكاميرا أو الصفحة غير آمنة.");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
        setReady(true);
      } catch (error) {
        const name = (error as { name?: string })?.name;
        if (name === "NotAllowedError") {
          setCameraError("تم رفض إذن الكاميرا. يمكنك المتابعة بالوضع التجريبي.");
        } else if (name === "NotFoundError") {
          setCameraError("لم يتم العثور على كاميرا. يمكنك المتابعة بالوضع التجريبي.");
        } else {
          setCameraError("تعذر تشغيل الكاميرا. يمكنك المتابعة بالوضع التجريبي.");
        }
      }
    }

    void start();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  function capture() {
    const video = videoRef.current;
    if (!ready || !video || !video.videoWidth) {
      onCapture(null);
      return;
    }
    const maxWidth = 960;
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const context = canvas.getContext("2d");
    if (!context) {
      onCapture(null);
      return;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.82);
    onCapture(dataUrl.split(",")[1]);
  }

  const component = session.identified_component;
  const step = session.current_step;
  const box = component?.bounding_box_2d;

  return (
    <section className="camera-stage" aria-label="بث الكاميرا الميداني">
      <video
        ref={videoRef}
        className={`camera-video ${ready ? "is-ready" : ""}`}
        playsInline
        muted
        autoPlay
      />

      {!ready && (
        <div className="camera-fallback">
          <div className="fallback-grid" />
          <div className="fallback-copy">
            <CameraIcon size={30} />
            <strong>وضع العرض التجريبي</strong>
            <span>{cameraError || "جارٍ تشغيل الكاميرا…"}</span>
          </div>
        </div>
      )}

      <div className="camera-topline">
        <span className={`live-pill ${ready ? "live-on" : "live-off"}`}>
          <span className="live-dot" />
          {ready ? "كاميرا حية" : "بلا كاميرا"}
        </span>
        <span className="session-pill" dir="ltr">
          {session.session_id}
        </span>
      </div>

      {/* Reticle */}
      <div className="reticle" aria-hidden="true">
        <span className="corner tl" />
        <span className="corner tr" />
        <span className="corner bl" />
        <span className="corner br" />
        {!component && <span className="scan-line" />}
      </div>

      {/* AR overlay from the backend bounding box */}
      {component && box && (
        <div
          className="ar-box"
          style={{
            left: `${box[0] * 100}%`,
            top: `${box[1] * 100}%`,
            width: `${(box[2] - box[0]) * 100}%`,
            height: `${(box[3] - box[1]) * 100}%`,
            borderColor: step?.ar_visual_cue?.color_hex || "#F59E0B",
          }}
        >
          <div className="ar-tag" style={{ borderColor: step?.ar_visual_cue?.color_hex || "#F59E0B" }}>
            <span className="ar-part" dir="ltr">
              {component.part_number}
            </span>
            <span className="ar-name">{component.arabic_name}</span>
          </div>

          {step && (
            <div
              className="cue-orb"
              style={{ borderColor: step.ar_visual_cue.color_hex, color: step.ar_visual_cue.color_hex }}
            >
              <CueGlyph cueType={step.ar_visual_cue.cue_type} />
            </div>
          )}

          {step?.torque_spec && (
            <div className="torque-float">
              <strong dir="ltr">{step.torque_spec.value_nm}</strong>
              <span>N·m</span>
            </div>
          )}
        </div>
      )}

      <div className="camera-actions">
        <button
          className="capture-btn"
          onClick={capture}
          disabled={busy}
          aria-label="التقاط الصورة وتحديد القطعة"
        >
          <span className="capture-ring" />
          <span className="capture-core">
            <CameraIcon size={24} />
          </span>
        </button>
        <span className="capture-label">
          {busy ? "جارٍ التحليل…" : ready ? "التقاط وتحديد" : "تحديد تجريبي"}
        </span>
      </div>
    </section>
  );
}
