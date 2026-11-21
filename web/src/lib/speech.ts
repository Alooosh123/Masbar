/* Arabic speech helpers with server-side neural TTS and a browser fallback. */

import { API_URL } from "./api";

type AnyRecognition = any;

const MAX_CHUNK_LENGTH = 900;

const ARABIC_VOICE_HINTS = [
  "zariyah",
  "hamed",
  "salma",
  "shakir",
  "fatima",
  "hamdan",
  "sana",
  "taim",
  "naayf",
  "hoda",
  "arabic",
  "عربي",
  "العربية",
];

let activeSession = 0;
let currentAudio: HTMLAudioElement | null = null;
let currentAbort: AbortController | null = null;
let currentStop: (() => void) | null = null;

export function recognitionSupported(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as any;
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
}

export function createArabicRecognizer(): AnyRecognition | null {
  if (typeof window === "undefined") return null;
  const w = window as any;
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (!Ctor) return null;

  const recognition = new Ctor();
  recognition.lang = "ar-SA";
  recognition.interimResults = false;
  recognition.continuous = false;
  recognition.maxAlternatives = 1;
  return recognition;
}

/** Split long Arabic replies into speakable chunks at natural boundaries. */
function splitForSpeech(text: string): string[] {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return [];
  if (clean.length <= MAX_CHUNK_LENGTH) return [clean];

  const chunks: string[] = [];
  let rest = clean;
  while (rest.length > MAX_CHUNK_LENGTH) {
    const windowText = rest.slice(0, MAX_CHUNK_LENGTH);
    let cut = -1;
    for (const separator of [". ", "؟ ", "! ", "، ", "; ", " "]) {
      const index = windowText.lastIndexOf(separator);
      if (index > cut) cut = index;
    }
    if (cut < MAX_CHUNK_LENGTH * 0.4) cut = MAX_CHUNK_LENGTH - 1;
    chunks.push(rest.slice(0, cut + 1).trim());
    rest = rest.slice(cut + 1).trim();
  }
  if (rest) chunks.push(rest);
  return chunks.filter(Boolean);
}

function pickArabicVoice(): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  const arabic = voices.filter((voice) => voice.lang.toLowerCase().startsWith("ar"));
  if (!arabic.length) return null;

  const scored = arabic.map((voice) => {
    const name = voice.name.toLowerCase();
    let score = 0;
    if (voice.lang.toLowerCase().startsWith("ar-sa")) score += 5;
    for (const hint of ARABIC_VOICE_HINTS) {
      if (name.includes(hint)) score += 3;
    }
    if (voice.localService) score += 1;
    return { voice, score };
  });
  scored.sort((a, b) => b.score - a.score);
  return scored[0].voice;
}

function speakWithBrowser(text: string): boolean {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
  const voice = pickArabicVoice();
  // Never hand Arabic text to an English system voice: that is the behaviour
  // this fallback exists to avoid. If no Arabic voice is installed, stay silent
  // and let the server-side neural voice handle it.
  if (!voice) return false;

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = voice.lang || "ar-SA";
  utterance.voice = voice;
  utterance.rate = 0.96;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
  return true;
}

/** Fetch one Arabic MP3 chunk and resolve once it finishes playing. */
async function playArabicChunk(text: string, session: number): Promise<boolean> {
  if (typeof window === "undefined" || typeof fetch !== "function") return false;

  const controller = new AbortController();
  currentAbort = controller;
  let objectUrl: string | null = null;
  let audioEl: HTMLAudioElement | null = null;

  try {
    const response = await fetch(`${API_URL}/api/v1/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    });
    if (!response.ok) return false;

    const blob = await response.blob();
    if (!blob.size || session !== activeSession) return false;

    objectUrl = URL.createObjectURL(blob);
    const audio = new Audio(objectUrl);
    audioEl = audio;
    currentAudio = audio;

    return await new Promise<boolean>((resolve) => {
      const finish = (ok: boolean) => {
        currentStop = null;
        resolve(ok);
      };
      currentStop = () => finish(false);
      audio.onended = () => finish(true);
      audio.onerror = () => finish(false);
      audio.play().catch(() => finish(false));
    });
  } catch (error) {
    if ((error as DOMException)?.name !== "AbortError") {
      console.warn("Arabic neural TTS unavailable.", error);
    }
    return false;
  } finally {
    if (currentAbort === controller) currentAbort = null;
    if (currentAudio === audioEl) currentAudio = null;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}

/**
 * Speak Arabic text. Tries the server's Arabic neural voice first, then an
 * Arabic browser voice. Returns true when audio playback actually started.
 */
export async function speakArabic(text: string, enabled = true): Promise<boolean> {
  if (!enabled || !text) return false;
  stopSpeaking();
  const session = activeSession;
  const chunks = splitForSpeech(text);

  let playedAny = false;
  for (const chunk of chunks) {
    if (session !== activeSession) return playedAny;
    const played = await playArabicChunk(chunk, session);
    if (session !== activeSession) return playedAny;
    if (!played) {
      const browserPlayed = speakWithBrowser(chunk);
      return playedAny || browserPlayed;
    }
    playedAny = true;
  }
  return playedAny;
}

export function stopSpeaking(): void {
  activeSession += 1;
  const stop = currentStop;
  currentStop = null;
  if (stop) stop();

  if (currentAbort) {
    currentAbort.abort();
    currentAbort = null;
  }
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.src = "";
    currentAudio = null;
  }
  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}
